"""Read-only live matrix. azd up supplies original text and real embeddings."""

import hashlib
import json
import math
import os

import pytest

from search_demo import RerankOptions, search, validate_vector
from seed_movies import SOURCE, SOURCE_ROWS, SOURCE_URL, SOURCE_SHA256, provenance, read_source

pytestmark = pytest.mark.live


def test_original_movie_readback(live_containers):
    rows = read_source(os.getenv("MOVIELENS_SOURCE_FILE"))
    assert len(rows) == SOURCE_ROWS == 4489
    # Independent membership/content assertions, not the loader's snapshot or
    # prepare_source implementation. Keep one page of vectors, never all targets.
    expected = {f"{SOURCE}-{index:04d}-{row['id']}": (index, row)
                for index, row in enumerate(rows, 1)}
    assert len(expected) == 4489
    def normalized(value):
        # Independent implementation of the documented numeric JSON hashing:
        # 1 and 1.0 have the same numeric value, but bool and number remain distinct.
        if isinstance(value, dict):
            return {k: normalized(v) for k, v in value.items()}
        if isinstance(value, list):
            return [normalized(v) for v in value]
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    source_hashes = {
        identifier: hashlib.sha256(json.dumps(
            normalized(row), sort_keys=True, ensure_ascii=False, separators=(",", ":"),
            allow_nan=False).encode("utf-8")).hexdigest()
        for identifier, (_, row) in expected.items()
    }
    for name, container in live_containers.items():
        seen = set()
        feed = container.query_items(
            query="SELECT * FROM c WHERE STARTSWITH(c.id, @prefix)",
            parameters=[{"name": "@prefix", "value": SOURCE + "-"}],
            enable_cross_partition_query=True, max_item_count=128)
        for page_number, page in enumerate(feed.by_page(), 1):
            for actual in page:
                identifier = actual["id"]
                if identifier not in expected:
                    continue  # Unrelated records are not part of the source corpus.
                assert identifier not in seen, f"{name}: duplicate source ID {identifier}"
                index, row = expected[identifier]
                assert actual["title"] == row["title"]
                assert actual["text"] == row["overview"]
                assert actual["source_movie_id"] == row["id"]
                assert actual["source_metadata"] == {k: v for k, v in row.items() if k != "vector"}
                assert actual["sample_source"] == SOURCE
                assert actual["source_provenance"]["url"] == SOURCE_URL
                assert actual["source_provenance"]["sha256"] == SOURCE_SHA256
                assert actual["source_provenance"]["rows"] == 4489
                assert actual["source_provenance"]["row_index"] == index
                assert actual["source_provenance"]["row_sha256"] == source_hashes[identifier]
                assert actual["embedding_provenance"] == provenance(
                    row["overview"], os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
                    os.environ["AZURE_OPENAI_EMBEDDING_MODEL"], os.environ["AZURE_OPENAI_EMBEDDING_VERSION"])
                validate_vector(actual["embedding"])
                seen.add(identifier)
            print(f"{name}: independent readback page {page_number}, "
                  f"{len(seen)}/4489 source records verified.", flush=True)
        assert seen == expected.keys(), f"{name}: missing source IDs: {sorted(expected.keys() - seen)[:3]}"


@pytest.mark.parametrize("mode,search_type", [
    ("vector", "all keywords"), ("fulltext", "all keywords"),
    ("fulltext", "any keywords"), ("ranking", "all keywords"),
    ("hybrid", "all keywords"),
])
@pytest.mark.parametrize("enabled", [False, True])
def test_real_embeddings_every_mode_and_toggle(live_containers, mode, search_type, enabled):
    for container in live_containers.values():
        # No embedder injection: this exercises the same real client as the UI.
        result = search(container, mode, "Woody Buzz", use_reranker=enabled,
                        search_type=search_type)
        assert result.rows
        assert result.reranked is enabled
        assert len({row["id"] for row in result.rows}) == len(result.rows)
        assert result.ru is not None and result.ru > 0
        position = next((i for i, row in enumerate(result.rows)
                         if row["id"] == "movielens-4489-v1-0001-862"), None)
        assert len(result.rows) <= 10  # Candidate limit, NOT corpus size.
        # Any-keyword filtering is unordered and can match more than ten movies.
        if mode != "fulltext" or search_type == "all keywords":
            assert position is not None
        # Boolean matching has no ranking contract. Other modes need only a modest top-3 hit.
        if mode != "fulltext":
            assert position < 3
        if mode in ("vector", "hybrid"):
            assert result.embedding_seconds > 0
        if enabled:
            assert all(math.isfinite(row["rerank_score"]) for row in result.rows)


@pytest.mark.parametrize("format,paths,k,diagnostics", [
    ("text", ("title", "text"), 1, False),
    ("text", ("title", "text"), 3, True),
    ("json", ("title",), 1, True),
    ("json", ("text",), 3, True),
    ("json", ("title", "text"), 10, True),
    ("json", ("title", "text"), 3, False),
])
def test_live_advanced_subsets(live_containers, format, paths, k, diagnostics):
    options = RerankOptions(format, paths, k, diagnostics)
    for container in live_containers.values():
        baseline = search(container, "vector", "Woody Buzz")
        # Same real embedding/retrieval path, with no seed or other writes.
        off = search(container, "vector", "Woody Buzz", rerank_options=options)
        assert [r["id"] for r in off.rows] == [r["id"] for r in baseline.rows]
        assert not off.reranked and not off.sentence_scores_requested
        result = search(container, "vector", "Woody Buzz", use_reranker=True,
                        rerank_options=options)
        assert result.reranked
        assert len(result.rows) == min(k, result.retrieved_count)
        assert len({row["retrieval_index"] for row in result.rows}) == len(result.rows)
        for row in result.rows:
            original = baseline.rows[row["retrieval_index"]]
            assert all(row[key] == original[key] for key in ("id", "title", "text"))
            assert math.isfinite(row["rerank_score"])
            assert row["retrieval_rank"] == row["retrieval_index"] + 1
            if diagnostics:
                # Presence is service-dependent. Validate returned values without inventing text.
                for score in row["sentence_scores"] or []:
                    assert type(score["index"]) is int and score["index"] >= 0
                    assert math.isfinite(score["score"])
            else:
                assert "sentence_scores" not in row
