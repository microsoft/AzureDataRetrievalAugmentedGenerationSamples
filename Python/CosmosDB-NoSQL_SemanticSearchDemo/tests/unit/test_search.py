import copy
from unittest.mock import Mock

import pytest
from azure.core.exceptions import HttpResponseError

from search_demo import (
    SearchError, Settings, build_query, embed_text, rerank, search, validate_vector,
)


def rows():
    return [
        {"id": "a", "title": "First", "text": "same text", "SimilarityScore": 0.2},
        {"id": "b", "title": "Second", "text": "same text", "SimilarityScore": 0.3},
    ]


def test_rerank_contract_preserves_metadata_and_duplicate_text():
    original = rows()
    before = copy.deepcopy(original)
    client = Mock()
    client.semantic_rerank.return_value = {
        "scores": [{"index": 1, "score": 0.9}, {"index": 0, "score": 0.1}]
    }
    result = rerank(client, "question", original)
    client.semantic_rerank.assert_called_once_with({
        "query": "question", "documents": ["same text", "same text"],
        "topK": 2, "sort": True, "returnDocuments": False,
    })
    assert [r["id"] for r in result] == ["b", "a"]
    assert result[0] == {**original[1], "rerank_score": 0.9,
                         "retrieval_index": 1, "retrieval_rank": 2}
    assert original == before


@pytest.mark.parametrize("response", [
    {}, {"Scores": []}, {"scores": None}, {"scores": []},
    {"scores": [{"index": -1, "score": 1}, {"index": 0, "score": 0}]},
    {"scores": [{"index": 2, "score": 1}, {"index": 0, "score": 0}]},
    {"scores": [{"index": 0, "score": 1}, {"index": 0, "score": 0}]},
    {"scores": [{"index": True, "score": 1}, {"index": 1, "score": 0}]},
    {"scores": [{"index": 0.0, "score": 1}, {"index": 1, "score": 0}]},
    {"scores": [{"index": 0, "score": "1"}, {"index": 1, "score": 0}]},
    {"scores": [{"index": 0, "score": float("nan")}, {"index": 1, "score": 0}]},
    {"scores": [{"index": 0, "score": float("inf")}, {"index": 1, "score": 0}]},
    {"scores": [{"index": 0, "score": True}, {"index": 1, "score": 0}]},
    {"scores": [{"index": "0", "score": 1}, {"index": 1, "score": 0}]},
    {"scores": ["invalid", {"index": 1, "score": 0}]},
    {"scores": [{"index": 0}, {"index": 1, "score": 0}]},
])
def test_bad_rerank_response_fails(response):
    client = Mock()
    client.semantic_rerank.return_value = response
    with pytest.raises(SearchError, match="response"):
        rerank(client, "question", rows())


def test_rerank_empty_and_error():
    client = Mock()
    assert rerank(client, "question", []) == []
    client.semantic_rerank.assert_not_called()
    client.semantic_rerank.side_effect = HttpResponseError("private service detail")
    with pytest.raises(SearchError, match="Reranking failed") as caught:
        rerank(client, "question", rows())
    assert "private service detail" not in str(caught.value)


def test_actual_sdk_model_response():
    from azure.data.ai.models import SemanticRerankingInferenceResult
    client = Mock()
    client.semantic_rerank.return_value = SemanticRerankingInferenceResult({
        "scores": [{"index": 1, "score": 0.9}, {"index": 0, "score": 0.1}]
    })
    assert [row["id"] for row in rerank(client, "question", rows())] == ["b", "a"]


def test_empty_retrieval_does_not_resolve_inference(monkeypatch):
    container = Mock()
    container.query_items.return_value = []
    client = Mock(side_effect=AssertionError("Must not create inference client"))
    monkeypatch.setattr("search_demo.get_inference_client", client)
    result = search(container, "fulltext", "missing", True)
    assert result.rows == [] and result.reranked is False
    client.assert_not_called()


def test_query_error_is_sanitized():
    container = Mock()
    container.query_items.side_effect = RuntimeError("private account information")
    with pytest.raises(SearchError, match="Search failed") as caught:
        search(container, "fulltext", "words")
    assert "private account" not in str(caught.value)


@pytest.mark.parametrize("phase", ["embedding", "retrieval", "reranking"])
def test_service_wrappers_preserve_exact_cause_and_traceback(monkeypatch, caplog, phase):
    import traceback

    original = ValueError("https://private.invalid/?key=secret document-content")
    operation = Mock(side_effect=original)
    client = Mock()
    if phase == "embedding":
        client.embeddings.create = operation
        monkeypatch.setattr("search_demo.get_embedding_client", lambda: client)
        monkeypatch.setenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "offline")
        call = lambda: embed_text("question")
    elif phase == "retrieval":
        client.query_items = operation
        call = lambda: search(client, "fulltext", "question")
    else:
        client.semantic_rerank = operation
        call = lambda: rerank(client, "question", rows())
    with pytest.raises(SearchError) as caught:
        call()
    assert caught.value.__cause__ is original
    assert original.__traceback__ is not None
    assert str(original) not in str(caught.value)
    assert str(original) in "".join(traceback.format_exception(caught.value))
    operation.assert_called_once()
    assert not caplog.records  # Only the owning UI/CLI boundary logs the failure.


def test_metrics_accumulate_per_response_hook():
    container = Mock()

    def query(*args, **kwargs):
        for ru, millis in [(2, 30), (3, 50)]:
            kwargs["response_hook"]({
                "x-ms-request-charge": str(ru),
                "x-ms-documentdb-query-metrics": f"totalExecutionTimeInMs={millis};other=1",
            }, {})
        return rows()

    container.query_items.side_effect = query
    result = search(container, "fulltext", "words")
    assert result.ru == 5
    assert result.server_seconds == pytest.approx(0.08)


def test_unreported_metrics_are_not_fabricated_as_zero():
    container = Mock()
    container.query_items.return_value = rows()
    result = search(container, "ranking", "words")
    assert result.ru is None and result.server_seconds is None


def test_cosmos_timeout_units_match_pinned_sdk(monkeypatch):
    import search_demo
    from azure.cosmos.cosmos_client import _build_connection_policy
    factory = Mock()
    monkeypatch.setattr("azure.cosmos.CosmosClient", factory)
    monkeypatch.setattr(search_demo, "get_credential", lambda: Mock())
    search_demo.get_cosmos_client.cache_clear()
    try:
        search_demo.get_cosmos_client("https://example.documents.azure.com")
        options = factory.call_args.kwargs.copy()
        options.pop("credential")
        assert "request_timeout" not in options
        assert options["connection_timeout"] == 30
        assert _build_connection_policy(options).RequestTimeout == 30
    finally:
        search_demo.get_cosmos_client.cache_clear()


@pytest.mark.parametrize("mode,fragment", [
    ("vector", "ORDER BY VectorDistance"),
    ("fulltext", "FullTextContainsAll"),
    ("ranking", "ORDER BY RANK FullTextScore"),
    ("hybrid", "ORDER BY RANK RRF"),
])
@pytest.mark.parametrize("enabled", [False, True])
def test_all_paths_wire_retrieval_and_reranker(mode, fragment, enabled):
    container, inference = Mock(), Mock()
    container.query_items.return_value = rows()
    inference.semantic_rerank.return_value = {
        "scores": [{"index": 1, "score": 0.9}, {"index": 0, "score": 0.1}]
    }
    embedder = Mock(return_value=[1.0] + [0.0] * 1535)
    result = search(container, mode, "space rescue", enabled, inference, embedder)
    assert fragment in container.query_items.call_args.args[0]
    assert len(result.rows) == 2
    assert result.reranked is enabled
    assert inference.semantic_rerank.call_count == int(enabled)
    assert embedder.call_count == int(mode in ("vector", "hybrid"))
    assert result.total_seconds >= result.retrieval_seconds


def test_query_escaping_and_any():
    query, parameters = build_query("fulltext", 'rescue "quote" \\ x', "any keywords")
    assert "FullTextContainsAny" in query
    # Text terms are parameters, not SQL fragments.
    assert '"quote"' not in query
    assert any(p["value"] == '"quote"' for p in parameters)
    ranked, _ = build_query("ranking", 'rescue "quoted"')
    assert '\\"quoted\\"' in ranked
    with pytest.raises(ValueError):
        build_query("fulltext", " ")
    with pytest.raises(ValueError):
        build_query("unknown", "text")


def test_optional_embeddings_actionable(monkeypatch):
    with pytest.raises(SearchError, match="AZURE_OPENAI_EMBEDDING_DEPLOYMENT"):
        embed_text("text")
    with pytest.raises(SearchError, match="COSMOS_URI"):
        Settings.from_env()


@pytest.mark.parametrize("vector", [[0.0] * 1536, [1.0], [float("inf")] * 1536,
                                     [True] * 1536, ["1"] * 1536])
def test_bad_vectors(vector):
    with pytest.raises(ValueError):
        validate_vector(vector)
