"""Validated, bounded fixture/data loading into existing containers only."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import logging
from pathlib import Path
import time

from azure.cosmos.exceptions import CosmosHttpResponseError

from search_demo import Settings, embed_text, error_details, get_containers, validate_vector

logger = logging.getLogger(__name__)


def boolean(value):
    if isinstance(value, bool):
        return value
    if value.lower() in ("true", "1", "yes"):
        return True
    if value.lower() in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError("Use true or false.")


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be positive.")
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path_to_json_array", required=True)
    parser.add_argument("--text_field_name", default="text")
    parser.add_argument("--vector_field_name", default="embedding")
    parser.add_argument("--database_name", help="Must match COSMOS_DB_DATABASE if supplied.")
    parser.add_argument("--concurrency", type=positive, default=1)
    parser.add_argument("--re_embed", type=boolean, default=False)
    parser.add_argument("--existing-only", action="store_true",
                        help="Compatibility flag: existing-only behavior is always enforced.")
    parser.add_argument("--max-items", type=positive, required=True,
                        help="Maximum documents selected from the input array.")
    parser.add_argument("--confirm-write", action="store_true", required=True,
                        help="Explicitly authorize upserts into both sample containers.")
    args = parser.parse_args(argv)
    if args.concurrency > 8:
        parser.error("--concurrency cannot exceed 8.")
    if args.max_items > 10000:
        parser.error("--max-items cannot exceed 10000 per invocation.")
    return args


def read_json(path):
    if path.startswith("https://"):
        import requests
        with requests.get(path, timeout=(10, 60), stream=True) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 64 * 1024 * 1024:
                    raise ValueError("JSON input exceeds 64 MiB.")
                chunks.append(chunk)
            return json.loads(b"".join(chunks))
    if "://" in path:
        raise ValueError("Use a local JSON file or an HTTPS URL.")
    source = Path(path)
    if source.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("JSON input exceeds 64 MiB.")
    return json.loads(source.read_text(encoding="utf-8"))


def prepare_items(items, text_field="text", vector_field="embedding", re_embed=False,
                  embedder=None):
    if not isinstance(items, list) or not items:
        raise ValueError("Input must be a nonempty JSON array.")
    if text_field == vector_field:
        raise ValueError("Text and vector fields must differ.")
    if text_field in ("id", "title") or vector_field in ("id", "title"):
        raise ValueError("id and title are reserved metadata fields, not rename sources.")
    prepared, seen = [], set()
    for source in items:
        if not isinstance(source, dict):
            raise ValueError("Each item must be a JSON object.")
        item = copy.deepcopy(source)
        identifier = item.get("id")
        if (not isinstance(identifier, str) or not identifier.strip()
                or any(c in identifier for c in "/\\?#")
                or len(identifier.encode("utf-8")) > 1023):
            raise ValueError("Every item needs a nonempty valid string id.")
        if identifier in seen:
            raise ValueError("Duplicate item id in input.")
        seen.add(identifier)
        for name in ("title", text_field):
            if not isinstance(item.get(name), str) or not item[name].strip():
                raise ValueError(f"Every item requires a nonempty string {name}.")
        text = item[text_field]
        vector = (embedder or embed_text)(text) if re_embed else item.get(vector_field)
        validate_vector(vector)
        if text_field != "text":
            item.pop(text_field)
        if vector_field != "embedding":
            item.pop(vector_field, None)
        item["text"], item["embedding"] = text, vector
        for field in ("_rid", "_self", "_etag", "_attachments", "_ts"):
            item.pop(field, None)
        if len(json.dumps(item, allow_nan=False).encode("utf-8")) >= 2 * 1024 * 1024:
            raise ValueError("Item is too large for Cosmos DB.")
        prepared.append(item)
    return prepared


def upsert_with_retry(container, item, attempts=3, sleep=time.sleep):
    if not 1 <= attempts <= 5:
        raise ValueError("attempts must be between 1 and 5.")
    for attempt in range(attempts):
        try:
            container.upsert_item(body=item)
            return
        except CosmosHttpResponseError as exc:
            if exc.status_code not in (408, 429, 449, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
            try:
                retry_after = float((exc.headers or {}).get("x-ms-retry-after-ms", 0)) / 1000
            except (ValueError, TypeError):
                retry_after = 0
            # If the server requests a longer wait, fail rather than retry too early.
            if retry_after > 60:
                raise
            sleep(max(min(2 ** attempt, 8), retry_after))


def load_items(containers, items, concurrency=1, failures=None):
    if not 1 <= concurrency <= 8:
        raise ValueError("concurrency must be between 1 and 8.")
    counts = {name: {"attempted": 0, "succeeded": 0, "failed": 0} for name in containers}

    def write(task):
        name, container, item = task
        try:
            upsert_with_retry(container, item)
            return name, True, None
        except Exception as exc:
            logger.exception("Document upsert failed.")
            return name, False, error_details(exc)

    tasks = ((name, container, item) for item in items for name, container in containers.items())
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        for name, ok, detail in executor.map(write, tasks):
            counts[name]["attempted"] += 1
            counts[name]["succeeded" if ok else "failed"] += 1
            if not ok and failures is not None and len(failures) < 20:
                failures.append({"container": name, **detail})
    return counts


def main(argv=None):
    args = parse_args(argv)
    phase = "input-read"
    try:
        source = read_json(args.path_to_json_array)
        if not isinstance(source, list):
            raise ValueError("Input must be a JSON array.")
        phase = "document-validation"
        items = prepare_items(source[:args.max_items], args.text_field_name,
                              args.vector_field_name, args.re_embed)
        phase = "configuration"
        settings = Settings.from_env()
        if args.database_name and args.database_name != settings.database:
            raise ValueError("--database_name must match COSMOS_DB_DATABASE.")
        phase = "client-initialization"
        containers = get_containers(settings)
        # Read and verify policies for BOTH containers before the first write.
        from container_setup import validate_policy
        phase = "container-policy-read"
        for name, container in containers.items():
            if name in ("search_qflat", "search_diskann"):
                validate_policy(container.read(), name)
        phase = "document-upsert"
        failures = []
        counts = load_items(containers, items, args.concurrency, failures)
        print(json.dumps({"source_items": len(source), "selected_items": len(items),
                          "containers": counts, "failures": failures}, indent=2))
        return int(any(count["failed"] for count in counts.values()))
    except Exception as exc:
        logger.exception("Load failed during %s.", phase)
        print(json.dumps({"error": "Load failed. Check input, environment, existing container "
                          "policies, Cosmos Data Contributor permission and network access.",
                          "complete": False, "phase": phase,
                          "diagnostic": error_details(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
