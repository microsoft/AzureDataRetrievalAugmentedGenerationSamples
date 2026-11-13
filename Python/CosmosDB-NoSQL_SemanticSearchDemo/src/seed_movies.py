"""Restore the complete pinned MovieLens corpus. No startup writes or provisioning."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import time
from uuid import uuid4

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from openai import APIStatusError

from container_setup import validate_policy
from search_demo import (
    DIMENSIONS, Settings, get_cosmos_client, get_embedding_client, load_environment,
    validate_vector,
)

SOURCE = "movielens-4489-v1"
SOURCE_ROWS = 4489
SOURCE_BYTES = 48244182
SOURCE_SHA256 = "5f43a3b0815b80b85c647b38d3d86c320aaf0c0937a79561fe643156e62c6295"
SOURCE_URL = (
    "https://raw.githubusercontent.com/TheovanKraay/AzureDataRetrievalAugmentedGenerationSamples/"
    "7fd162fc633617857f8b8ed2c5b2b92d4d8ef0b6/DataSet/Movies/MovieLens-4489-256D.json"
)
LEGACY_SOURCE = "original-movies-v1"
LEGACY_IDS = {f"{LEGACY_SOURCE}-{suffix}" for suffix in (
    "spectre", "courier", "orbit", "ocean", "bakery", "garden", "jazz", "archive", "mountain", "robot")}
ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / ".local/movielens"
PYTHON_CONTAINERS = ("search_qflat", "search_diskann")
DOTNET_CONTAINERS = ("reranker_dotnet_qflat", "reranker_dotnet_diskann")
SYSTEM_FIELDS = {"_rid", "_self", "_etag", "_attachments", "_ts"}
SNAPSHOT_PAGE_SIZE = 128
logger = logging.getLogger(__name__)


def digest(value):
    # Cosmos can round-trip JSON 1.0 as 1. Hash numeric values, not that spelling.
    def canonical(item):
        if isinstance(item, dict):
            return {k: canonical(v) for k, v in item.items()}
        if isinstance(item, list):
            return [canonical(v) for v in item]
        if isinstance(item, float) and math.isfinite(item) and item.is_integer():
            return int(item)
        return item
    return hashlib.sha256(json.dumps(
        canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("utf-8")).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False),
                             encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_source(rows):
    if not isinstance(rows, list) or len(rows) != SOURCE_ROWS:
        raise ValueError(f"MovieLens source must contain exactly {SOURCE_ROWS} rows; no truncation.")
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or any(
                not isinstance(row.get(k), str) or not row[k].strip()
                for k in ("id", "title", "overview")):
            raise ValueError(f"Invalid MovieLens schema at source row {index}.")
        vector = row.get("vector")
        if (not isinstance(vector, list) or len(vector) != 256 or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in vector)):
            raise ValueError(f"Invalid source vector at row {index}; expected 256 finite values.")
        if not row["id"].isdigit():
            raise ValueError(f"Invalid original movie ID at row {index}.")
        digest(row)  # Also reject nonfinite metadata. Never send this metadata for embedding.
    return rows


def read_source(source_file=None, cache_dir=CACHE_DIR):
    """File overrides obey the SAME byte size, checksum, schema and row count."""
    path = Path(source_file) if source_file else Path(cache_dir) / "MovieLens.source.json"
    if source_file is None and not path.exists():
        import requests
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
        try:
            size = 0
            hasher = hashlib.sha256()
            with requests.get(SOURCE_URL, stream=True, timeout=(10, 120)) as response:
                response.raise_for_status()
                with temporary.open("wb") as output:
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > SOURCE_BYTES:
                            raise ValueError("MovieLens download exceeds pinned bytes.")
                        hasher.update(chunk)
                        output.write(chunk)
            if size != SOURCE_BYTES or hasher.hexdigest() != SOURCE_SHA256:
                raise ValueError("MovieLens download bytes/SHA256 mismatch; source not cached.")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    if path.stat().st_size != SOURCE_BYTES:
        raise ValueError(f"MovieLens source must be exactly {SOURCE_BYTES} bytes (raw LF, not CRLF).")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("MovieLens source SHA256 mismatch.")
    return validate_source(json.loads(raw))


def prepare_source(rows):
    return [{
        "id": f"{SOURCE}-{index:04d}-{row['id']}",
        "title": row["title"], "text": row["overview"],
        "source_movie_id": row["id"], "sample_source": SOURCE,
        "source_metadata": {k: v for k, v in row.items() if k != "vector"},
        "source_provenance": {
            "url": SOURCE_URL, "sha256": SOURCE_SHA256, "rows": SOURCE_ROWS,
            "row_index": index, "row_sha256": digest(row),
        },
    } for index, row in enumerate(validate_source(rows), 1)]


def provenance(text, deployment, model, version):
    return {"provider": "azure-openai", "deployment": deployment, "model": model,
            "version": version, "dimensions": DIMENSIONS,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def wait_for_role(operation):
    """Bounded 403 propagation and 429/5xx retries; rethrow the original exception."""
    roles = transient = 0
    while True:
        try:
            return operation()
        except (CosmosHttpResponseError, APIStatusError) as error:
            status = error.status_code
            if status == 403 and roles < 12:
                roles += 1
                delay = 10
            elif (status == 429 or 500 <= status <= 599) and transient < 5:
                transient += 1
                headers = getattr(error, "headers", None)
                if headers is None:
                    headers = getattr(getattr(error, "response", None), "headers", {}) or {}
                try:
                    requested = max(float(headers.get("retry-after", 0)),
                                    float(headers.get("x-ms-retry-after-ms", 0)) / 1000)
                except (ValueError, TypeError):
                    requested = 0
                if not math.isfinite(requested) or requested > 60:
                    raise
                delay = max(2 ** (transient - 1), requested)
            else:
                raise
            print(f"Service HTTP {status}; retrying in {delay:g}s.", flush=True)
            time.sleep(delay)


def read_item(container, identifier):
    try:
        return wait_for_role(lambda: container.read_item(item=identifier, partition_key=identifier))
    except CosmosResourceNotFoundError:
        return None


def public_body(row):
    return {k: v for k, v in row.items() if k not in SYSTEM_FIELDS}


def owned_body(existing, expected):
    body = {k: v for k, v in public_body(existing).items()
            if k not in ("embedding", "embedding_provenance")}
    return digest(body) == digest(expected)


def snapshot(container, name, source_by_id, expected_hashes=None):
    """Stream full documents one container/page at a time; retain only hashes/etags.

    Filter by ID, never by ownership: a foreign record at an expected ID must
    still be seen. Full documents also expose unexpected user fields. Exhaust
    the SDK pager, including empty pages, rather than inferring completion from
    page length or a count. A failed feed is retried from scratch, not resumed
    through an iterator whose internal state might have advanced.
    """
    phase = "verification" if expected_hashes is not None else "ownership preflight"
    def collect():
        found, page_count = {}, 0
        feed = container.query_items(
            query="SELECT * FROM c WHERE STARTSWITH(c.id, @prefix)",
            parameters=[{"name": "@prefix", "value": SOURCE + "-"}],
            enable_cross_partition_query=True, max_item_count=SNAPSHOT_PAGE_SIZE)
        for page in feed.by_page():
            page_count += 1
            for existing in page:
                identifier = existing.get("id")
                if identifier not in source_by_id:
                    continue  # Unrelated same-prefix IDs are not migration targets.
                if identifier in found:
                    raise ValueError(f"{name}/{identifier}: duplicate ID in {phase} snapshot.")
                body_hash = digest(public_body(existing))
                if expected_hashes is None:
                    if not owned_body(existing, source_by_id[identifier]) or not existing.get("_etag"):
                        raise ValueError(f"{name}/{identifier}: collision with non-owned or changed source data.")
                else:
                    if body_hash != expected_hashes[identifier]:
                        raise ValueError(f"{name}/{identifier}: full readback verification failed.")
                    validate_vector(existing["embedding"])
                found[identifier] = (body_hash, existing.get("_etag"))
            print(f"{name}: {phase} page {page_count}; "
                  f"matched {len(found)}/{len(source_by_id)} expected IDs.", flush=True)
        if expected_hashes is not None and found.keys() != expected_hashes.keys():
            missing = sorted(expected_hashes.keys() - found.keys())
            raise ValueError(f"{name}: full readback verification missing {len(missing)} IDs: {missing[:3]}.")
        return found, page_count
    return wait_for_role(collect)


def cached_vector(cache_dir, row, prov, vector=None):
    key = digest({"source": row["source_provenance"], "content": digest(row),
                  "embedding_provenance": prov})
    path = Path(cache_dir) / "embeddings" / key[:2] / (key + ".json")
    if path.exists():
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            checked = validate_vector(entry["embedding"])
            if (entry["key"] != key or entry["provenance"] != prov
                    or entry["sha256"] != digest(checked)):
                raise ValueError("hash or provenance mismatch")
            return checked
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError(f"Invalid embedding cache {path}. Remove this entry to regenerate.") from error
    if vector is not None:
        validate_vector(vector)
        atomic_json(path, {"key": key, "provenance": prov, "embedding": vector,
                           "sha256": digest(vector)})
    return vector


def read_legacy_fixture():
    rows = json.loads((ROOT / "sample-data/movies.original.json").read_text(encoding="utf-8"))
    if (len(rows) != 10 or {r["id"] for r in rows} != LEGACY_IDS or any(
            set(r) != {"id", "title", "text"} or not r["id"].startswith(LEGACY_SOURCE + "-")
            for r in rows)):
        raise ValueError("Invalid legacy cleanup fixture.")
    return rows


def cleanup_fixtures(containers, deployment, model, version, receipt):
    # ALL targets have already passed full membership/content/vector readback.
    # Preflight ALL exact legacy IDs before deleting any; never query-delete a prefix.
    if (receipt.get("source_rows") != SOURCE_ROWS or any(
            receipt.get("containers", {}).get(name, {}).get("verified") != SOURCE_ROWS
            for name in containers)):
        raise ValueError("Legacy cleanup requires complete verification of ALL targets.")
    candidates = []
    for name, container in containers.items():
        for row in read_legacy_fixture():
            existing = read_item(container, row["id"])
            if existing is None:
                continue
            expected = {**row, "sample_source": LEGACY_SOURCE,
                        "embedding_provenance": provenance(row["text"], deployment, model, version)}
            body = public_body(existing)
            vector = body.pop("embedding", None)
            if body != expected or not existing.get("_etag"):
                raise ValueError(f"{name}/{row['id']}: changed or foreign legacy record; cleanup refused.")
            validate_vector(vector)
            candidates.append((name, container, row["id"], existing["_etag"]))
    for name, container, identifier, etag in candidates:
        # A concurrent edit produces 412. Never retry with a newly fetched etag.
        wait_for_role(lambda: container.delete_item(
            item=identifier, partition_key=identifier, etag=etag,
            match_condition=MatchConditions.IfNotModified))
        receipt["removed_fixtures"] += 1
        receipt["containers"][name]["removed_fixtures"] += 1
    for name in containers:
        print(f"{name}: removed {receipt['containers'][name]['removed_fixtures']} exact legacy fixtures.",
              flush=True)


def seed(containers, rows, client, deployment, model, version, *,
         cache_dir=CACHE_DIR, batch_size=32, cleanup_original_fixtures=False, receipt=None,
         write_workers=5):
    source = prepare_source(rows)
    if (not containers or any(n not in (*PYTHON_CONTAINERS, *DOTNET_CONTAINERS) for n in containers)
            or not 1 <= batch_size <= 64 or type(write_workers) is not int
            or not 1 <= write_workers <= 8):
        raise ValueError("Use dedicated sample containers, batch size 1-64 and write workers 1-8.")
    if not all(isinstance(v, str) and v.strip() for v in (deployment, model, version)):
        raise ValueError("Embedding deployment, model and version provenance are required.")
    receipt = receipt if receipt is not None else {}
    receipt.update(status="in-progress", source_rows=len(source), source_url=SOURCE_URL,
                   source_sha256=SOURCE_SHA256, removed_fixtures=0, containers={},
                   embeddings={"generated": 0, "cache_reused": 0})
    receipt["execution"] = {"verification": "paged-full-document-v1",
                            "snapshot_page_size": SNAPSHOT_PAGE_SIZE, "write_workers": write_workers}
    provenance_rows = [provenance(r["text"], deployment, model, version) for r in source]
    source_by_id = {row["id"]: row for row in source}
    snapshots = {}
    # Inspect EVERY target before embedding charges or writes. Snapshots are
    # observations, not locks: creates still reject collisions and replacements
    # must use the observed etag. A fresh full readback follows even skipped writes.
    for name, container in containers.items():
        started = time.perf_counter()
        policy = wait_for_role(container.read)
        if policy.get("id") != name:
            raise ValueError("Container response does not match selected target.")
        alias = "search_qflat" if name.endswith("qflat") else "search_diskann"
        validate_policy({**policy, "id": alias}, alias)
        receipt["containers"][name] = dict(created=0, replaced=0, skipped=0, verified=0,
                                           removed_fixtures=0)
        snapshots[name], pages = snapshot(container, name, source_by_id)
        receipt["containers"][name].update(
            preflight_pages=pages, preflight_seconds=time.perf_counter() - started)
        print(f"{name}: ownership preflight complete; "
              f"{len(snapshots[name])} existing of {len(source)} expected IDs.", flush=True)
    prepared = []
    for start in range(0, len(source), batch_size):
        batch = source[start:start + batch_size]
        vectors = [cached_vector(cache_dir, row, provenance_rows[start + i])
                   for i, row in enumerate(batch)]
        missing = [i for i, v in enumerate(vectors) if v is None]
        receipt["embeddings"]["cache_reused"] += len(batch) - len(missing)
        if missing:
            response = wait_for_role(lambda: client.embeddings.create(
                input=[batch[i]["text"] for i in missing], model=deployment, dimensions=DIMENSIONS))
            if len(response.data) != len(missing):
                raise ValueError("Embedding response count does not match batch.")
            indexed = {}
            for entry in response.data:
                if (type(entry.index) is not int or not 0 <= entry.index < len(missing)
                        or entry.index in indexed):
                    raise ValueError("Invalid or duplicate embedding response index.")
                indexed[entry.index] = validate_vector(entry.embedding)
            # Cache only after the ENTIRE response passes validation.
            for response_index, batch_index in enumerate(missing):
                vectors[batch_index] = cached_vector(
                    cache_dir, batch[batch_index], provenance_rows[start + batch_index],
                    indexed[response_index])
                receipt["embeddings"]["generated"] += 1
        prepared.extend({**row, "embedding": vectors[i],
                         "embedding_provenance": provenance_rows[start + i]}
                        for i, row in enumerate(batch))
        print(f"Embeddings: {min(start + batch_size, len(source))}/{len(source)}; "
              f"generated={receipt['embeddings']['generated']}, "
              f"cache reused={receipt['embeddings']['cache_reused']}.", flush=True)
    expected_hashes = {row["id"]: digest(row) for row in prepared}
    for name, container in containers.items():
        started = time.perf_counter()
        counts = receipt["containers"][name]
        def write_one(row, previous):
            if previous:
                wait_for_role(lambda: container.replace_item(
                    item=row["id"], body=row, etag=previous[1],
                    match_condition=MatchConditions.IfNotModified))
                return "replaced"
            # Create, NOT upsert: a concurrent foreign collision must return 409.
            wait_for_role(lambda: container.create_item(body=row))
            return "created"
        # Only one container writes at a time. Both active workers and queued
        # work are bounded; unchanged rows never enter the executor.
        with ThreadPoolExecutor(max_workers=write_workers) as executor:
            for start in range(0, len(prepared), batch_size):
                pending = []
                for row in prepared[start:start + batch_size]:
                    previous = snapshots[name].get(row["id"])
                    if previous and previous[0] == expected_hashes[row["id"]]:
                        counts["skipped"] += 1
                    else:
                        pending.append(executor.submit(write_one, row, previous))
                failure = None
                for future in as_completed(pending):
                    try:
                        counts[future.result()] += 1
                    except Exception as error:
                        if failure is None:
                            failure = error
                        else:
                            logger.exception("Additional document write failed in the settled batch.")
                # Account for settled successes, then stop before any next
                # batch/container or cleanup. Never leave background writes.
                if failure is not None:
                    raise failure
                print(f"{name}: seeded/unchanged {min(start + batch_size, len(prepared))}"
                      f"/{len(prepared)}.", flush=True)
        counts["write_seconds"] = time.perf_counter() - started
    for name, container in containers.items():
        started = time.perf_counter()
        verified, pages = snapshot(container, name, source_by_id, expected_hashes)
        receipt["containers"][name].update(
            verified=len(verified), readback_pages=pages,
            readback_seconds=time.perf_counter() - started)
        print(f"{name}: full readback verified {len(verified)}/{len(prepared)}.", flush=True)
    if cleanup_original_fixtures:
        cleanup_fixtures(containers, deployment, model, version, receipt)
    receipt["status"] = "complete"
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-dotnet", action="store_true")
    parser.add_argument("--confirm-write", required=True, action="store_true")
    parser.add_argument("--cleanup-original-fixtures", action="store_true",
                        help="After full verification, remove only exact unchanged ten legacy fixture IDs.")
    parser.add_argument("--source-file", type=Path, help="Pinned raw bytes only; no alternate corpus.")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--write-workers", type=int, default=5,
                        help="Concurrent conditional writes per container, 1-8; default 5. No RU changes.")
    args = parser.parse_args()
    receipt = {"status": "failed", "started_utc": datetime.now(timezone.utc).isoformat()}
    try:
        rows = read_source(args.source_file)
        load_environment()
        settings = Settings.from_env()
        receipt["target"] = {"endpoint": settings.endpoint, "database": settings.database}
        database = get_cosmos_client(settings.endpoint).get_database_client(settings.database)
        names = (*PYTHON_CONTAINERS, *(DOTNET_CONTAINERS if args.include_dotnet else ()))
        seed({name: database.get_container_client(name) for name in names},
             rows, get_embedding_client(), os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
             os.environ["AZURE_OPENAI_EMBEDDING_MODEL"], os.environ["AZURE_OPENAI_EMBEDDING_VERSION"],
             batch_size=args.batch_size, cleanup_original_fixtures=args.cleanup_original_fixtures,
             receipt=receipt, write_workers=args.write_workers)
    except BaseException as error:
        receipt.update(status="failed", error_type=type(error).__name__, error=str(error))
        raise  # Preserve original service diagnostics and a nonzero process exit.
    finally:
        receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
        path = CACHE_DIR / ("receipt-" + uuid4().hex + ".json")
        try:
            atomic_json(path, receipt)
            print(f"Local receipt: {path}", flush=True)
        except OSError:
            if receipt["status"] == "complete":
                raise
            logger.exception("Could not save local receipt; preserving the original seed failure.")
    print(json.dumps(receipt, indent=2), flush=True)


if __name__ == "__main__":
    main()
