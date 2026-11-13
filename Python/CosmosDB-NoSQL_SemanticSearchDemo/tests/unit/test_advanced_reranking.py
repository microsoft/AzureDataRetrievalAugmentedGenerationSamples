"""Offline advanced contract tests, including the actual SDK response model."""
import copy
import json
from unittest.mock import Mock

import pytest
from azure.data.ai.models import SemanticRerankingInferenceResult

from search_demo import RerankOptions, SearchError, rerank, search


def candidates():
    return [
        {"id": str(i), "title": f"Title {i}", "text": "duplicate description",
         "SimilarityScore": i / 10, "metadata": {"source": i},
         "embedding": [1.0], "_etag": "not for inference"}
        for i in range(3)
    ]


@pytest.mark.parametrize("paths", [("title",), ("text",), ("title", "text")])
@pytest.mark.parametrize("k", [1, 3, 10])
def test_json_whitelist_topk_and_index_mapping(paths, k):
    rows = candidates()
    original = copy.deepcopy(rows)
    indices = [2, 0, 1][:min(k, len(rows))]
    client = Mock()
    client.semantic_rerank.return_value = SemanticRerankingInferenceResult({
        "scores": [{"index": i, "score": 0.9 - n / 10, "document": "ignored"}
                   for n, i in enumerate(indices)]
    })
    result = rerank(client, "query", rows, RerankOptions("json", paths, k))
    payload = client.semantic_rerank.call_args.args[0]
    assert payload == {
        "query": "query", "documents": [
            json.dumps({key: row[key] for key in paths}, ensure_ascii=True) for row in rows],
        "documentType": "json", "targetPaths": ",".join(paths),
        "topK": min(k, 3), "sort": True, "returnDocuments": False,
    }
    assert [row["id"] for row in result] == [str(i) for i in indices]
    for row, i in zip(result, indices):
        assert row["metadata"] == original[i]["metadata"]
        assert row["SimilarityScore"] == original[i]["SimilarityScore"]
        assert row["retrieval_index"] == i and row["retrieval_rank"] == i + 1
    assert rows == original


@pytest.mark.parametrize("options", [
    RerankOptions(top_k=0), RerankOptions(top_k=11), RerankOptions(top_k=True),
    RerankOptions(top_k=1.5), RerankOptions(document_format="xml"),
    RerankOptions("json", ()), RerankOptions("json", ("embedding",)),
    RerankOptions("json", ("title", "title")), RerankOptions(return_sentence_scores=1),
])
def test_invalid_advanced_settings_fail_before_services_but_off_ignores(options):
    container, client = Mock(), Mock()
    container.query_items.return_value = candidates()
    with pytest.raises(ValueError):
        search(container, "ranking", "query", True, client, rerank_options=options)
    container.query_items.assert_not_called()
    client.semantic_rerank.assert_not_called()
    result = search(container, "ranking", "query", False, client, rerank_options=options)
    assert result.rows == candidates() and result.retrieved_count == 3
    client.semantic_rerank.assert_not_called()


@pytest.mark.parametrize("scores", [
    [], [{"index": 0, "score": 1}, {"index": 1, "score": 0}],
    [{"index": 3, "score": 1}], [{"index": -1, "score": 1}],
    [{"index": 1, "score": float("nan")}], [{"index": 1, "score": float("inf")}],
    [{"index": 1}], [None],
])
def test_subset_rejects_malformed_response(scores):
    client = Mock()
    client.semantic_rerank.return_value = {"scores": scores}
    with pytest.raises(SearchError, match="response"):
        rerank(client, "query", candidates(), RerankOptions(top_k=1))


@pytest.mark.parametrize("sentence_scores", [
    None, [], [{"index": 7, "score": 0.75}, {"index": 9, "score": 0.25}],
])
def test_optional_diagnostics_and_no_invented_text(sentence_scores):
    client = Mock()
    score = {"index": 2, "score": 0.9}
    if sentence_scores is not None:
        score["sentenceScores"] = sentence_scores
    client.semantic_rerank.return_value = SemanticRerankingInferenceResult({"scores": [score]})
    result = rerank(client, "query", candidates(),
                    RerankOptions(top_k=1, return_sentence_scores=True))
    assert client.semantic_rerank.call_args.args[0]["returnSentenceScore"] is True
    assert result[0]["sentence_scores"] == sentence_scores
    result = rerank(client, "query", candidates(), RerankOptions(top_k=1))
    assert "returnSentenceScore" not in client.semantic_rerank.call_args.args[0]
    assert "sentence_scores" not in result[0]


@pytest.mark.parametrize("diagnostics", [
    "bad", [None], [{"index": -1, "score": 1}], [{"index": True, "score": 1}],
    [{"index": 0, "score": float("nan")}], [{"index": 0}],
    [{"index": 0, "score": 1}, {"index": 0, "score": 0}],
])
def test_malformed_diagnostics_fail_closed(diagnostics):
    client = Mock()
    client.semantic_rerank.return_value = {
        "scores": [{"index": 0, "score": 1, "sentenceScores": diagnostics}]}
    with pytest.raises(SearchError, match="response"):
        rerank(client, "query", candidates(),
               RerankOptions(top_k=1, return_sentence_scores=True))


def test_empty_and_fewer_candidates():
    client, container = Mock(), Mock()
    container.query_items.return_value = []
    result = search(container, "ranking", "query", True, client,
                    rerank_options=RerankOptions(top_k=1))
    assert result.rows == [] and result.retrieved_count == 0 and not result.reranked
    client.semantic_rerank.assert_not_called()
    container.query_items.return_value = candidates()[:1]
    client.semantic_rerank.return_value = {"scores": [{"index": 0, "score": 1}]}
    result = search(container, "ranking", "query", True, client,
                    rerank_options=RerankOptions(top_k=10))
    assert len(result.rows) == result.retrieved_count == 1
    assert client.semantic_rerank.call_args.args[0]["topK"] == 1
