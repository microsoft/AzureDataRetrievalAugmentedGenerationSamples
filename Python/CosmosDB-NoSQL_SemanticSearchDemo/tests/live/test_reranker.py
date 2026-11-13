import math

import pytest

from search_demo import get_inference_client, rerank, search

pytestmark = pytest.mark.live


def test_standalone_reranker_real_service(fixture_rows):
    rows = [{key: row[key] for key in ("id", "title", "text")} for row in fixture_rows]
    result = rerank(get_inference_client(), "astronauts rescued from a stranded spacecraft", rows)
    assert result[0]["id"] == "synthetic-orbit-rescue"
    assert {row["id"] for row in result} == {row["id"] for row in rows}
    assert all(math.isfinite(row["rerank_score"]) for row in result)
    assert [row["rerank_score"] for row in result] == sorted(
        [row["rerank_score"] for row in result], reverse=True)
    assert all(row["title"] == next(r["title"] for r in rows if r["id"] == row["id"])
               for row in result)


@pytest.mark.parametrize("mode", ["vector", "hybrid"])
@pytest.mark.parametrize("enabled", [False, True])
def test_actual_vector_and_hybrid_queries_with_fixture_vectors(loaded_containers, mode, enabled):
    # Deterministic schema/integration check, NOT semantic embedding-quality validation.
    for container in loaded_containers.values():
        result = search(container, mode, "orbital rescue", use_reranker=enabled,
                        embedder=lambda _: [1.0] + [0.0] * 1535)
        assert result.rows, "Expected loaded fixture results. Check indexing readiness."
        assert any(row["id"] == "synthetic-orbit-rescue" for row in result.rows)
        assert result.reranked is enabled
        if mode == "vector":
            assert result.rows[0]["id"] == "synthetic-orbit-rescue"
