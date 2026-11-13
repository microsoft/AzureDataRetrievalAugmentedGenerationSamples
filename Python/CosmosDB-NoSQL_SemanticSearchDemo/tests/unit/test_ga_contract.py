"""Public GA package and wire contract, with no external network calls."""
import json
from importlib.metadata import version
from unittest.mock import Mock

import pytest
from azure.core.credentials import AccessToken
from azure.core.pipeline.transport import HttpResponse, HttpTransport
from azure.data.ai import InferenceClient
from azure.data.ai.models import SemanticRerankingInferenceResult

from search_demo import RerankOptions, SearchError, rerank


class Response(HttpResponse):
    def __init__(self, request):
        super().__init__(request, None)
        self.status_code = 200
        self.headers = {"content-type": "application/json"}
        self.content_type = "application/json"

    def body(self):
        return json.dumps({
            "scores": [{"index": 1, "score": 0.9}, {"index": 0, "score": 0.2}],
            "meta": {"modelName": "test-model", "modelVersion": "1"},
        }).encode()

    def json(self):
        return json.loads(self.body())


class Transport(HttpTransport):
    def __init__(self):
        self.requests = []

    def open(self):
        pass

    def close(self):
        pass

    def __exit__(self, *args):
        self.close()

    def send(self, request, **kwargs):
        self.requests.append(request)
        return Response(request)


def test_public_ga_version_and_metadata_model():
    assert version("azure-data-ai") == "1.0.0"
    result = SemanticRerankingInferenceResult({
        "scores": [{"index": 0, "score": 0.75}],
        "meta": {"modelName": "test-model", "modelVersion": "1"},
    })
    assert result.meta.model_name == "test-model"
    assert result.meta.model_version == "1"
    assert result["scores"][0]["index"] == 0


@pytest.mark.parametrize("paths", [("title",), ("text",), ("title", "text")])
def test_application_dictionary_target_paths_stays_comma_string_on_wire(paths):
    # Exercise the actual SDK pipeline, not only the mocked method arguments.
    # Keep the raw dictionary path: typed target_paths getters are not needed.
    transport = Transport()
    credential = Mock()
    credential.get_token.return_value = AccessToken("offline-token", 4102444800)
    rows = [
        {"id": "a", "title": "First", "text": "duplicate"},
        {"id": "b", "title": "Second", "text": "duplicate"},
    ]
    with InferenceClient("https://offline.invalid", credential, transport=transport) as client:
        result = rerank(client, "query", rows, RerankOptions("json", paths))
    payload = json.loads(transport.requests[0].body)
    assert payload["targetPaths"] == ",".join(paths)
    assert isinstance(payload["targetPaths"], str)
    assert payload["documentType"] == "json"
    assert payload["topK"] == 2
    assert payload["sort"] is True
    assert payload["returnDocuments"] is False
    assert [row["id"] for row in result] == ["b", "a"]
    assert [row["retrieval_index"] for row in result] == [1, 0]


def test_existing_candidate_limit_rejects_before_sdk_call():
    client = Mock()
    rows = [{"id": str(i), "title": "Title", "text": "Text"} for i in range(11)]
    with pytest.raises(SearchError, match="at most 10"):
        rerank(client, "query", rows)
    client.semantic_rerank.assert_not_called()
