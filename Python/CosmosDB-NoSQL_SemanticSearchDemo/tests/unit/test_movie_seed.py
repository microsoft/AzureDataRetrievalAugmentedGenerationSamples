"""Offline contracts. Tiny generated inputs are NOT the production source."""
import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError

import seed_movies as seed
from container_setup import container_resource


class Container:
    def __init__(self, name):
        self.name = name
        self.items = {"unrelated": {"id": "unrelated", "text": "leave me alone"}}
        self.writes = self.deletes = self.reads = 0
        self.queries = 0
        self.fail = False

    def read(self):
        alias = "search_qflat" if self.name.endswith("qflat") else "search_diskann"
        return {**container_resource(alias), "id": self.name}

    def read_item(self, item, partition_key):
        assert item == partition_key
        self.reads += 1
        if item not in self.items:
            raise CosmosResourceNotFoundError(status_code=404)
        return copy.deepcopy(self.items[item])

    def query_items(self, query, parameters, enable_cross_partition_query, max_item_count):
        assert query == "SELECT * FROM c WHERE STARTSWITH(c.id, @prefix)"
        assert parameters == [{"name": "@prefix", "value": seed.SOURCE + "-"}]
        assert enable_cross_partition_query and max_item_count == seed.SNAPSHOT_PAGE_SIZE
        self.queries += 1
        # Snapshot at query creation, not at consumption: supports stale-etag tests.
        rows = copy.deepcopy([r for k, r in self.items.items() if k.startswith(seed.SOURCE + "-")])
        def by_page():
            yield iter([])  # Empty pages are not end-of-feed.
            for offset in range(0, len(rows), 2):
                yield iter(rows[offset:offset + 2])
                yield iter([])
        return SimpleNamespace(by_page=by_page)

    def create_item(self, body):
        if self.fail:
            raise RuntimeError("simulated partial write failure")
        if body["id"] in self.items:
            raise CosmosHttpResponseError(status_code=409)
        self.writes += 1
        self.items[body["id"]] = {**copy.deepcopy(body), "_etag": str(self.writes)}

    def replace_item(self, item, body, etag, match_condition):
        if self.items[item]["_etag"] != etag:
            raise CosmosHttpResponseError(status_code=412)
        assert match_condition == seed.MatchConditions.IfNotModified
        self.items.pop(item)
        self.create_item(body)

    def delete_item(self, item, partition_key, etag, match_condition):
        assert item == partition_key
        assert self.items[item]["_etag"] == etag
        assert match_condition == seed.MatchConditions.IfNotModified
        self.deletes += 1
        self.items.pop(item)


class Client:
    def __init__(self):
        self.embeddings = self
        self.calls = []
        self.fail_at = None
        self.bad = None

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == self.fail_at:
            raise RuntimeError("embedding batch failed")
        count = len(kwargs["input"])
        assert 1 <= count <= 2
        data = [SimpleNamespace(index=i, embedding=[1.0] + [0.0] * 1535)
                for i in reversed(range(count))]
        if self.bad:
            self.bad(data)
        return SimpleNamespace(data=data)


@pytest.fixture
def corpus(monkeypatch):
    monkeypatch.setattr(seed, "SOURCE_ROWS", 5)
    rows = [{"id": "10991" if i in (0, 4) else str(i),
             "title": "Offline original title", "overview": f"Offline test overview {i}",
             "vector": [1.0] * 256, "genres": [{"name": "Test"}]} for i in range(5)]
    rows[4]["overview"] = rows[0]["overview"]
    rows[4]["genres"] = [{"name": "Different source metadata"}]
    return rows


@pytest.fixture
def targets():
    return {name: Container(name) for name in (*seed.PYTHON_CONTAINERS, *seed.DOTNET_CONTAINERS)}


def run(targets, corpus, tmp_path, client=None, **kwargs):
    return seed.seed(targets, corpus, client or Client(), "deployment",
                     "text-embedding-3-small", "1", cache_dir=tmp_path, batch_size=2, **kwargs)


def test_ids_preserve_duplicate_movie_ids_and_all_metadata(corpus):
    rows = seed.prepare_source(corpus)
    assert len({r["id"] for r in rows}) == 5
    assert rows[0]["source_movie_id"] == rows[4]["source_movie_id"] == "10991"
    assert rows[0]["id"] != rows[4]["id"]
    assert rows[0]["text"] == rows[4]["text"]
    assert rows[0]["source_metadata"] != rows[4]["source_metadata"]
    assert rows == seed.prepare_source(copy.deepcopy(corpus))
    assert rows[0]["text"] == corpus[0]["overview"]
    assert rows[0]["source_metadata"]["genres"] == corpus[0]["genres"]
    assert "vector" not in rows[0]["source_metadata"]


def test_source_bytes_hash_size_schema_count(tmp_path, corpus, monkeypatch):
    raw = json.dumps(corpus).encode()
    path = tmp_path / "source.json"
    path.write_bytes(raw)
    monkeypatch.setattr(seed, "SOURCE_BYTES", len(raw))
    monkeypatch.setattr(seed, "SOURCE_SHA256", hashlib.sha256(raw).hexdigest())
    assert seed.read_source(path, tmp_path) == corpus
    path.write_bytes(raw.replace(b"overview", b"overvieW", 1))
    with pytest.raises(ValueError, match="SHA256"):
        seed.read_source(path, tmp_path)
    path.write_bytes(raw + b"\n")
    with pytest.raises(ValueError, match="bytes"):
        seed.read_source(path, tmp_path)
    for bad in (corpus[:-1], { "rows": corpus }, [*corpus[:-1], {"id": "1"}]):
        with pytest.raises(ValueError):
            seed.validate_source(bad)
    corpus[0]["vector"][0] = float("nan")
    with pytest.raises(ValueError):
        seed.validate_source(corpus)


def test_full_readback_repeat_no_calls_or_writes_and_missing_repaired(targets, corpus, tmp_path):
    foreign_id = seed.SOURCE + "-unrelated"
    for container in targets.values():
        container.items[foreign_id] = {"id": foreign_id, "text": "Not a source member"}
    client = Client()
    receipt = run(targets, corpus, tmp_path, client)
    assert len(client.calls) == 3
    assert all(r["verified"] == 5 for r in receipt["containers"].values())
    assert all(r["readback_pages"] > 1 for r in receipt["containers"].values())
    counts = [c.writes for c in targets.values()]
    run(targets, corpus, tmp_path, client)
    assert len(client.calls) == 3
    assert [c.writes for c in targets.values()] == counts
    missing = seed.prepare_source(corpus)[-1]["id"]
    targets["search_diskann"].items.pop(missing)
    result = run(targets, corpus, tmp_path, client)
    assert len(client.calls) == 3
    assert result["containers"]["search_diskann"]["created"] == 1
    for container in targets.values():
        assert container.items["unrelated"]["text"] == "leave me alone"
        assert container.items[foreign_id]["text"] == "Not a source member"
        assert container.reads == 0  # No per-corpus-ID point reads in either pass.
        assert container.queries == 6  # Fresh exhaustive preflight AND readback on each run.


def test_last_target_foreign_collision_prevents_any_embedding_or_write(targets, corpus, tmp_path):
    row = seed.prepare_source(corpus)[-1]
    targets["reranker_dotnet_diskann"].items[row["id"]] = {"id": row["id"]}
    client = Client()
    with pytest.raises(ValueError, match="owned"):
        run(targets, corpus, tmp_path, client)
    assert not client.calls
    assert not any(c.writes or c.deletes for c in targets.values())


def test_batch_failure_resumes_completed_cache(targets, corpus, tmp_path):
    client = Client()
    client.fail_at = 2
    with pytest.raises(RuntimeError, match="embedding batch"):
        run(targets, corpus, tmp_path, client)
    assert not any(c.writes or c.deletes for c in targets.values())
    resumed = Client()
    receipt = run(targets, corpus, tmp_path, resumed)
    assert len(resumed.calls) == 2
    assert receipt["embeddings"]["cache_reused"] == 2


def test_cache_hash_corruption_fails_closed(targets, corpus, tmp_path):
    run(targets, corpus, tmp_path)
    path = next((tmp_path / "embeddings").rglob("*.json"))
    cached = json.loads(path.read_text())
    cached["embedding"][0] = 9.0
    path.write_text(json.dumps(cached))
    with pytest.raises(ValueError, match="cache"):
        run(targets, corpus, tmp_path)


def test_provenance_change_invalidates_cache(targets, corpus, tmp_path):
    run(targets, corpus, tmp_path)
    client = Client()
    seed.seed(targets, corpus, client, "other-deployment", "text-embedding-3-small",
              "2", cache_dir=tmp_path, batch_size=2)
    assert len(client.calls) == 3


@pytest.mark.parametrize("mutate", [
    lambda data: data.pop(),
    lambda data: setattr(data[0], "index", data[-1].index),
    lambda data: setattr(data[0], "index", True),
    lambda data: setattr(data[0], "embedding", [0.0] * 1536),
    lambda data: setattr(data[0], "embedding", [float("inf")] * 1536),
    lambda data: setattr(data[0], "embedding", [1.0] * 256),
])
def test_bad_batch_never_writes_or_cleans(targets, corpus, tmp_path, mutate):
    client = Client()
    client.bad = mutate
    with pytest.raises(ValueError):
        run(targets, corpus, tmp_path, client)
    assert not any(c.writes or c.deletes for c in targets.values())


def add_legacy(targets):
    for container in targets.values():
        for row in seed.read_legacy_fixture():
            container.items[row["id"]] = {
                **row, "sample_source": seed.LEGACY_SOURCE,
                "embedding": [1.0] + [0.0] * 1535,
                "embedding_provenance": seed.provenance(row["text"], "deployment",
                                                         "text-embedding-3-small", "1"),
                "_etag": "legacy",
            }


def test_only_exact_legacy_rows_deleted_after_all_targets_verified(targets, corpus, tmp_path):
    add_legacy(targets)
    for c in targets.values():
        c.items["original-movies-v1-foreign"] = {"id": "original-movies-v1-foreign"}
    receipt = run(targets, corpus, tmp_path, cleanup_original_fixtures=True)
    assert all(c.deletes == 10 for c in targets.values())
    assert receipt["removed_fixtures"] == 40
    assert all("original-movies-v1-foreign" in c.items for c in targets.values())


def test_partial_write_failure_cannot_delete_fixture(targets, corpus, tmp_path):
    add_legacy(targets)
    targets["reranker_dotnet_diskann"].fail = True
    with pytest.raises(RuntimeError, match="partial"):
        run(targets, corpus, tmp_path, cleanup_original_fixtures=True)
    assert not any(c.deletes for c in targets.values())


def test_readback_last_missing_row_blocks_cleanup(targets, corpus, tmp_path, monkeypatch):
    add_legacy(targets)
    last = targets["reranker_dotnet_diskann"]
    original = last.create_item
    last_id = seed.prepare_source(corpus)[-1]["id"]
    def lose(body):
        original(body)
        if body["id"] == last_id:
            last.items.pop(last_id)
    monkeypatch.setattr(last, "create_item", lose)
    with pytest.raises(ValueError, match="verification"):
        run(targets, corpus, tmp_path, cleanup_original_fixtures=True)
    assert not any(c.deletes for c in targets.values())


def test_changed_legacy_data_refused_before_any_cleanup(targets, corpus, tmp_path):
    add_legacy(targets)
    identifier = seed.read_legacy_fixture()[-1]["id"]
    targets["reranker_dotnet_diskann"].items[identifier]["title"] = "Changed by someone"
    with pytest.raises(ValueError, match="legacy"):
        run(targets, corpus, tmp_path, cleanup_original_fixtures=True)
    assert not any(c.deletes for c in targets.values())


def test_cleanup_requires_complete_membership_receipt(targets):
    add_legacy(targets)
    with pytest.raises(ValueError, match="ALL targets"):
        seed.cleanup_fixtures(targets, "deployment", "text-embedding-3-small", "1",
                              {"source_rows": seed.SOURCE_ROWS, "containers": {}})
    assert not any(c.deletes for c in targets.values())


def test_cleanup_etag_race_is_not_overridden(targets, corpus, tmp_path, monkeypatch):
    add_legacy(targets)
    first = targets["search_qflat"]
    identifier = seed.read_legacy_fixture()[0]["id"]
    def changed(**kwargs):
        assert kwargs["etag"] == "legacy"
        first.items[identifier]["text"] = "Concurrent foreign edit"
        raise CosmosHttpResponseError(status_code=412)
    monkeypatch.setattr(first, "delete_item", changed)
    with pytest.raises(CosmosHttpResponseError):
        run(targets, corpus, tmp_path, cleanup_original_fixtures=True)
    assert not any(c.deletes for c in targets.values())
    assert first.items[identifier]["text"] == "Concurrent foreign edit"


def test_cache_key_includes_content_and_provenance(corpus, tmp_path):
    row = seed.prepare_source(corpus)[0]
    prov = seed.provenance(row["text"], "d", "m", "1")
    vector = [1.0] + [0.0] * 1535
    seed.cached_vector(tmp_path, row, prov, vector)
    assert seed.cached_vector(tmp_path, row, prov) == vector
    for field in ("deployment", "model", "version", "dimensions", "text_sha256"):
        assert seed.cached_vector(tmp_path, row, {**prov, field: "changed"}) is None
    assert seed.cached_vector(tmp_path, {**row, "title": "Changed"}, prov) is None


def test_semantic_numeric_digest_survives_json_number_spelling():
    assert seed.digest({"number": 1.0, "list": [0.0]}) == seed.digest({"number": 1, "list": [0]})
    assert seed.digest({"video": False}) != seed.digest({"video": 0})


def test_changed_owned_metadata_refused_without_more_calls_or_writes(targets, corpus, tmp_path):
    run(targets, corpus, tmp_path)
    identifier = seed.prepare_source(corpus)[0]["id"]
    targets["reranker_dotnet_diskann"].items[identifier]["source_metadata"]["title"] = "Foreign edit"
    previous_writes = [c.writes for c in targets.values()]
    client = Client()
    with pytest.raises(ValueError, match="changed source"):
        run(targets, corpus, tmp_path, client)
    assert not client.calls
    assert [c.writes for c in targets.values()] == previous_writes


def test_concurrent_foreign_create_is_not_upserted(targets, corpus, tmp_path, monkeypatch):
    container = targets["search_qflat"]
    def conflict(body):
        container.items[body["id"]] = {"id": body["id"], "text": "Concurrent foreign create"}
        raise CosmosHttpResponseError(status_code=409)
    monkeypatch.setattr(container, "create_item", conflict)
    with pytest.raises(CosmosHttpResponseError):
        run(targets, corpus, tmp_path, cleanup_original_fixtures=True)
    assert not any(c.writes or c.deletes for c in targets.values())
    assert container.items[seed.prepare_source(corpus)[0]["id"]]["text"] == "Concurrent foreign create"


def test_retry_after_and_too_long_wait(monkeypatch):
    sleeps = []
    monkeypatch.setattr(seed.time, "sleep", sleeps.append)
    throttled = CosmosHttpResponseError(status_code=429)
    throttled.headers = {"x-ms-retry-after-ms": "7000"}
    attempts = iter([throttled, None])
    def transient():
        error = next(attempts)
        if error:
            raise error
        return "ok"
    assert seed.wait_for_role(transient) == "ok"
    assert sleeps == [7]
    def too_long():
        error = CosmosHttpResponseError(status_code=429)
        error.headers = {"retry-after": "61"}
        raise error
    with pytest.raises(CosmosHttpResponseError):
        seed.wait_for_role(too_long)
    assert sleeps == [7]


def test_download_is_pinned_bounded_atomic_and_reused(tmp_path, corpus, monkeypatch):
    import requests
    raw = json.dumps(corpus).encode()
    monkeypatch.setattr(seed, "SOURCE_BYTES", len(raw))
    monkeypatch.setattr(seed, "SOURCE_SHA256", hashlib.sha256(raw).hexdigest())
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def raise_for_status(self):
            pass
        def iter_content(self, size):
            yield raw[:17]
            yield raw[17:]
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        assert url == seed.SOURCE_URL and kwargs["stream"]
        return Response()
    monkeypatch.setattr(requests, "get", get)
    assert seed.read_source(cache_dir=tmp_path) == corpus
    assert seed.read_source(cache_dir=tmp_path) == corpus
    assert calls == [seed.SOURCE_URL]
    (tmp_path / "MovieLens.source.json").unlink()
    monkeypatch.setattr(seed, "SOURCE_BYTES", len(raw) - 1)
    with pytest.raises(ValueError, match="exceeds pinned"):
        seed.read_source(cache_dir=tmp_path)
    assert not list(tmp_path.glob("*"))


@pytest.mark.parametrize("status,expected", [(403, 13), (429, 6), (503, 6), (400, 1)])
def test_service_retry_is_bounded_preserves_original_error(monkeypatch, status, expected):
    calls, sleeps = [], []
    monkeypatch.setattr(seed.time, "sleep", sleeps.append)
    error = CosmosHttpResponseError(status_code=status)
    def fail():
        calls.append(1)
        raise error
    with pytest.raises(CosmosHttpResponseError) as result:
        seed.wait_for_role(fail)
    assert result.value is error
    assert len(calls) == expected
    assert len(sleeps) == expected - 1


def test_snapshot_retries_whole_feed_after_partial_service_failure(targets, corpus, tmp_path, monkeypatch):
    run(targets, corpus, tmp_path)
    container = targets["search_qflat"]
    original = container.query_items
    attempts = []
    def query(**kwargs):
        feed = original(**kwargs)
        attempts.append(1)
        if len(attempts) > 1:
            return feed
        def partial():
            pages = feed.by_page()
            yield next(pages)  # Empty.
            yield next(pages)  # First two records.
            raise CosmosHttpResponseError(status_code=503)
        return SimpleNamespace(by_page=partial)
    monkeypatch.setattr(container, "query_items", query)
    monkeypatch.setattr(seed.time, "sleep", lambda seconds: None)
    source = {row["id"]: row for row in seed.prepare_source(corpus)}
    actual, pages = seed.snapshot(container, container.name, source)
    assert set(actual) == set(source) and pages > 1
    assert len(attempts) == 2
    assert all(isinstance(value[0], str) and isinstance(value[1], str) for value in actual.values())


def test_duplicate_snapshot_id_fails_instead_of_silent_dedup(targets, corpus, tmp_path, monkeypatch):
    run(targets, corpus, tmp_path)
    container = targets["search_qflat"]
    identifier = seed.prepare_source(corpus)[0]["id"]
    row = copy.deepcopy(container.items[identifier])
    monkeypatch.setattr(container, "query_items", lambda **kwargs: SimpleNamespace(
        by_page=lambda: iter([iter([]), iter([row]), iter([]), iter([row])])))
    with pytest.raises(ValueError, match="duplicate"):
        run(targets, corpus, tmp_path)


def test_stale_snapshot_etag_cannot_replace_new_foreign_owner(targets, corpus, tmp_path, monkeypatch):
    run(targets, corpus, tmp_path)
    container = targets["search_qflat"]
    identifier = seed.prepare_source(corpus)[0]["id"]
    original = container.query_items
    def stale(**kwargs):
        feed = original(**kwargs)  # Captures old owned body and etag.
        container.items[identifier]["sample_source"] = "foreign-owner"
        container.items[identifier]["_etag"] = "concurrent-etag"
        return feed
    monkeypatch.setattr(container, "query_items", stale)
    with pytest.raises(CosmosHttpResponseError) as result:
        seed.seed(targets, corpus, Client(), "new-deployment", "text-embedding-3-small", "1",
                  cache_dir=tmp_path, batch_size=2, cleanup_original_fixtures=True)
    assert result.value.status_code == 412
    assert container.items[identifier]["sample_source"] == "foreign-owner"
    assert container.items[identifier]["_etag"] == "concurrent-etag"
    assert not any(c.deletes for c in targets.values())


def test_stale_unchanged_snapshot_still_requires_fresh_full_readback(targets, corpus, tmp_path, monkeypatch):
    run(targets, corpus, tmp_path)
    container = targets["search_qflat"]
    identifier = seed.prepare_source(corpus)[-1]["id"]
    original = container.query_items
    writes = [c.writes for c in targets.values()]
    def stale(**kwargs):
        feed = original(**kwargs)
        container.items[identifier]["text"] = "Concurrent content edit"
        return feed
    monkeypatch.setattr(container, "query_items", stale)
    with pytest.raises(ValueError, match="verification"):
        run(targets, corpus, tmp_path, cleanup_original_fixtures=True)
    assert [c.writes for c in targets.values()] == writes
    assert not any(c.deletes for c in targets.values())


def test_last_page_vector_corruption_blocks_cleanup(targets, corpus, tmp_path, monkeypatch):
    add_legacy(targets)
    last = targets["reranker_dotnet_diskann"]
    identifier = seed.prepare_source(corpus)[-1]["id"]
    original = last.create_item
    def corrupt(body):
        original(body)
        if body["id"] == identifier:
            last.items[identifier]["embedding"] = [0.0] * 1536
    monkeypatch.setattr(last, "create_item", corrupt)
    with pytest.raises(ValueError, match="verification"):
        run(targets, corpus, tmp_path, cleanup_original_fixtures=True)
    assert not any(c.deletes for c in targets.values())


def test_conditional_writes_run_concurrently_with_bounded_workers(targets, corpus, tmp_path, monkeypatch):
    from threading import Barrier, Lock
    container = targets["search_qflat"]
    original = container.create_item
    lock, barrier = Lock(), Barrier(2)
    state = {"active": 0, "peak": 0, "started": 0}
    def create(body):
        with lock:
            state["active"] += 1
            state["started"] += 1
            first_pair = state["started"] <= 2
            state["peak"] = max(state["peak"], state["active"])
        try:
            if first_pair:
                barrier.wait(timeout=5)
            with lock:
                original(body)
        finally:
            with lock:
                state["active"] -= 1
    monkeypatch.setattr(container, "create_item", create)
    receipt = run({"search_qflat": container}, corpus, tmp_path, write_workers=2)
    assert state == {"active": 0, "peak": 2, "started": 5}
    assert receipt["containers"]["search_qflat"]["created"] == 5
    assert receipt["containers"]["search_qflat"]["verified"] == 5


@pytest.mark.parametrize("workers", [0, 9, True, 1.5])
def test_write_worker_bound_rejected_before_service_calls(targets, corpus, tmp_path, workers):
    client = Client()
    with pytest.raises(ValueError, match="workers"):
        run(targets, corpus, tmp_path, client, write_workers=workers)
    assert not client.calls
    assert not any(c.queries or c.reads or c.writes for c in targets.values())


def test_failed_parallel_batch_settles_and_records_success_without_cleanup(targets, corpus, tmp_path, monkeypatch):
    from threading import Barrier
    container = targets["search_qflat"]
    original = container.create_item
    identifiers = [row["id"] for row in seed.prepare_source(corpus)]
    barrier = Barrier(2)
    failure = RuntimeError("Original write diagnostic")
    def create(body):
        barrier.wait(timeout=5)
        if body["id"] == identifiers[0]:
            raise failure
        original(body)
    monkeypatch.setattr(container, "create_item", create)
    receipt = {}
    with pytest.raises(RuntimeError) as result:
        run(targets, corpus, tmp_path, receipt=receipt, cleanup_original_fixtures=True)
    assert result.value is failure
    assert container.writes == receipt["containers"]["search_qflat"]["created"] == 1
    assert identifiers[1] in container.items
    assert identifiers[2] not in container.items  # No next batch scheduled.
    assert not any(c.deletes for c in targets.values())
    assert not any(c.writes for name, c in targets.items() if name != "search_qflat")
    assert receipt["status"] != "complete"


def test_parallel_failures_keep_primary_and_log_secondary(
        targets, corpus, tmp_path, monkeypatch, caplog):
    identifiers = [row["id"] for row in seed.prepare_source(corpus)]
    errors = {identifier: ValueError(f"private failure {index}")
              for index, identifier in enumerate(identifiers[:2])}
    calls = []

    def create(body):
        calls.append(body["id"])
        raise errors[body["id"]]

    monkeypatch.setattr(targets["search_qflat"], "create_item", create)
    with pytest.raises(ValueError) as caught:
        run(targets, corpus, tmp_path, cleanup_original_fixtures=True)
    assert set(calls) == set(errors)  # Only the settled first batch, no retry.
    records = [record for record in caplog.records if record.exc_info]
    assert len(records) == 1
    assert {caught.value, records[0].exc_info[1]} == set(errors.values())
    assert records[0].exc_info[2] is not None and caught.value.__traceback__ is not None
    assert not any(c.writes or c.deletes for c in targets.values())


def test_receipt_failure_logs_secondary_without_replacing_primary(monkeypatch, caplog, capsys):
    import sys
    from unittest.mock import Mock

    primary = ValueError("private source failure")
    secondary = OSError("private receipt path")
    monkeypatch.setattr(sys, "argv", ["seed_movies.py", "--confirm-write"])
    monkeypatch.setattr(seed, "read_source", Mock(side_effect=primary))
    monkeypatch.setattr(seed, "atomic_json", Mock(side_effect=secondary))
    with pytest.raises(ValueError) as caught:
        seed.main()
    assert caught.value is primary
    records = [record for record in caplog.records if record.exc_info]
    assert len(records) == 1 and records[0].exc_info[1] is secondary
    assert records[0].exc_info[2] is not None
    assert "private" not in capsys.readouterr().out


def test_live_readback_is_paged_and_independent_of_loader_snapshot():
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parents[1] /
                      "live/test_original_movies.py").read_text(encoding="utf-8"))
    readback = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "test_original_movie_readback")
    calls = [node.func for node in ast.walk(readback) if isinstance(node, ast.Call)]
    attributes = {node.attr for node in calls if isinstance(node, ast.Attribute)}
    names = {node.id for node in calls if isinstance(node, ast.Name)}
    assert "by_page" in attributes and "query_items" in attributes
    assert "read_item" not in attributes
    assert not {"snapshot", "prepare_source"} & names
    assert "validate_vector" in names and "sha256" in attributes
