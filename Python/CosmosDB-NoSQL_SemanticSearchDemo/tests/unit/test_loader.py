import copy
import json
from unittest.mock import Mock

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError

from load_data import load_items, main, parse_args, prepare_items, upsert_with_retry
from container_setup import container_resource, validate_policy


def item():
    return {"id": "synthetic-1", "title": "Original", "text": "space rescue",
            "embedding": [1.0] + [0.0] * 1535}


def test_boolean_false_and_required_write_guards():
    args = parse_args(["--path_to_json_array", "x.json", "--max-items", "3",
                       "--confirm-write", "--re_embed", "False"])
    assert args.re_embed is False
    for args in ([], ["--path_to_json_array", "x.json", "--max-items", "3"]):
        with pytest.raises(SystemExit):
            parse_args(args)
    with pytest.raises(SystemExit):
        parse_args(["--path_to_json_array", "x", "--max-items", "3",
                    "--confirm-write", "--re_embed", "maybe"])


def test_preembedded_no_mutation_or_openai():
    original = [item()]
    before = copy.deepcopy(original)
    embedder = Mock(side_effect=AssertionError("OpenAI not allowed"))
    result = prepare_items(original, "text", "embedding", False, embedder)
    assert result == before and original == before
    embedder.assert_not_called()


def test_rename_and_reembed():
    source = {"id": "x", "title": "X", "overview": "words", "vector": [9]}
    result = prepare_items([source], "overview", "vector", True,
                           lambda text: item()["embedding"])
    assert result[0]["text"] == "words"
    assert "overview" not in result[0] and "vector" not in result[0]
    assert result[0]["embedding"] == item()["embedding"]
    assert source["vector"] == [9]


@pytest.mark.parametrize("change", [
    {"id": ""}, {"id": "bad/id"}, {"text": ""}, {"title": None},
    {"embedding": [1]}, {"embedding": [0] * 1536},
])
def test_schema_rejected_before_writes(change):
    with pytest.raises(ValueError):
        prepare_items([{**item(), **change}], "text", "embedding", False)


def test_duplicate_ids_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        prepare_items([item(), item()], "text", "embedding", False)


@pytest.mark.parametrize("text,vector", [("id", "embedding"), ("title", "embedding"),
                                       ("text", "id"), ("text", "title")])
def test_reserved_fields_cannot_be_removed(text, vector):
    with pytest.raises(ValueError, match="reserved"):
        prepare_items([item()], text, vector)


def test_retry_after_too_long_fails_without_early_retry():
    container, sleep = Mock(), Mock()
    error = CosmosHttpResponseError(status_code=429, message="throttle")
    error.headers = {"x-ms-retry-after-ms": "120000"}
    container.upsert_item.side_effect = error
    with pytest.raises(CosmosHttpResponseError):
        upsert_with_retry(container, item(), sleep=sleep)
    container.upsert_item.assert_called_once()
    sleep.assert_not_called()


def test_max_items_is_enforced(tmp_path, monkeypatch, capsys):
    path = tmp_path / "items.json"
    path.write_text(json.dumps([item(), {**item(), "id": "second"}]), encoding="utf-8")
    container = Mock()
    monkeypatch.setattr("load_data.get_containers", lambda settings: {"test": container})
    monkeypatch.setattr("load_data.Settings.from_env", lambda: Mock())
    assert main(["--path_to_json_array", str(path), "--max-items", "1",
                 "--confirm-write"]) == 0
    container.upsert_item.assert_called_once()
    output = json.loads(capsys.readouterr().out)
    assert output["source_items"] == 2 and output["selected_items"] == 1


def test_timeout_diagnostic_is_actionable_without_private_message(tmp_path, monkeypatch, capsys):
    from azure.core.exceptions import ServiceResponseTimeoutError
    path = tmp_path / "items.json"
    path.write_text(json.dumps([item()]), encoding="utf-8")
    monkeypatch.setattr("load_data.Settings.from_env", lambda: Mock())
    def fail(_):
        raise ServiceResponseTimeoutError("secret endpoint token must not be printed")
    monkeypatch.setattr("load_data.get_containers", fail)
    assert main(["--path_to_json_array", str(path), "--max-items", "1", "--confirm-write"]) == 1
    output = capsys.readouterr().out
    diagnostic = json.loads(output)
    assert diagnostic["phase"] == "client-initialization"
    assert diagnostic["diagnostic"]["category"] == "timeout"
    assert diagnostic["diagnostic"]["exception_type"] == "ServiceResponseTimeoutError"
    assert "secret endpoint" not in output and "token must" not in output


def test_http_diagnostic_retains_status_not_service_body():
    from search_demo import error_details
    error = CosmosHttpResponseError(status_code=403, message="private body")
    detail = error_details(error)
    assert detail["status_code"] == 403
    assert detail["category"] == "authorization"
    assert "private body" not in json.dumps(detail)


def test_bounded_retry_and_retry_after():
    container, sleep = Mock(), Mock()
    error = CosmosHttpResponseError(status_code=429, message="throttle")
    error.headers = {"x-ms-retry-after-ms": "1500"}
    container.upsert_item.side_effect = [error, error, {}]
    upsert_with_retry(container, item(), attempts=3, sleep=sleep)
    assert container.upsert_item.call_count == 3
    assert sleep.call_args_list[0].args[0] == 1.5
    container.upsert_item.side_effect = error
    with pytest.raises(CosmosHttpResponseError):
        upsert_with_retry(container, item(), attempts=3, sleep=sleep)
    assert container.upsert_item.call_count == 6


def test_non_retryable_and_truthful_partial_counts():
    good, bad = Mock(), Mock()
    bad.upsert_item.side_effect = CosmosHttpResponseError(status_code=403, message="denied")
    counts = load_items({"good": good, "bad": bad}, [item()], concurrency=1)
    assert counts == {"good": {"attempted": 1, "succeeded": 1, "failed": 0},
                      "bad": {"attempted": 1, "succeeded": 0, "failed": 1}}
    assert bad.upsert_item.call_count == 1


def test_cli_failure_exit(tmp_path, monkeypatch, capsys):
    path = tmp_path / "items.json"
    path.write_text(json.dumps([item()]), encoding="utf-8")
    bad = Mock()
    bad.upsert_item.side_effect = CosmosHttpResponseError(status_code=403, message="private")
    monkeypatch.setattr("load_data.get_containers", lambda settings: {"bad": bad})
    monkeypatch.setattr("load_data.Settings.from_env", lambda: Mock())
    code = main(["--path_to_json_array", str(path), "--max-items", "1",
                 "--confirm-write", "--re_embed", "false"])
    assert code == 1
    assert '"failed": 1' in capsys.readouterr().out


@pytest.mark.parametrize("name,index", [("search_qflat", "quantizedFlat"),
                                       ("search_diskann", "diskANN")])
def test_container_policy(name, index):
    resource = container_resource(name)
    validate_policy(resource, name)
    assert resource["partitionKey"]["paths"] == ["/id"]
    assert resource["indexingPolicy"]["vectorIndexes"][0]["type"] == index
    resource["vectorEmbeddingPolicy"]["vectorEmbeddings"][0]["dimensions"] = 256
    with pytest.raises(ValueError, match="incompatible"):
        validate_policy(resource, name)


def server_enriched_policy(name="search_qflat"):
    # Exact policy additions observed in a real SDK container.read() response.
    resource = container_resource(name)
    resource["fullTextPolicy"] = {
        "defaultLanguage": "en-US",
        "package": "legacy",
        "defaultSpec": {"language": "en-US", "stopWordListKind": "extended"},
        "fullTextPaths": [{"path": "/text", "language": "en-US"}],
    }
    resource["indexingPolicy"]["vectorIndexes"][0].update({
        "quantizerType": "product", "quantizationByteSize": 96,
    })
    return resource


@pytest.mark.parametrize("name", ["search_qflat", "search_diskann"])
def test_server_added_policy_metadata_is_compatible(name):
    resource = server_enriched_policy(name)
    before = copy.deepcopy(resource)
    validate_policy(resource, name)
    assert resource == before, "Inspection must not mutate the server response."


@pytest.mark.parametrize("section,field,value", [
    ("partitionKey", "paths", ["/tenant"]),
    ("partitionKey", "kind", "MultiHash"),
    ("fullTextPolicy", "defaultLanguage", "fr-FR"),
    ("fullTextPolicy", "fullTextPaths", [{"path": "/other", "language": "en-US"}]),
    ("fullTextPolicy", "fullTextPaths", [{"path": "/text", "language": "fr-FR"}]),
    ("indexingPolicy", "indexingMode", "none"),
    ("indexingPolicy", "automatic", False),
    ("indexingPolicy", "vectorIndexes", [{"path": "/embedding", "type": "diskANN"}]),
    ("indexingPolicy", "fullTextIndexes", [{"path": "/other"}]),
])
def test_server_metadata_does_not_mask_real_mismatches(section, field, value):
    resource = server_enriched_policy()
    resource[section][field] = value
    with pytest.raises(ValueError, match="incompatible"):
        validate_policy(resource, "search_qflat")


@pytest.mark.parametrize("field,value", [
    ("path", "/other"), ("dataType", "int8"),
    ("dimensions", 256), ("distanceFunction", "euclidean"),
])
def test_vector_contract_still_required_with_extra_metadata(field, value):
    resource = server_enriched_policy()
    resource["vectorEmbeddingPolicy"]["vectorEmbeddings"][0][field] = value
    with pytest.raises(ValueError, match="incompatible"):
        validate_policy(resource, "search_qflat")


def test_duplicate_required_policy_path_is_rejected():
    resource = server_enriched_policy()
    resource["indexingPolicy"]["vectorIndexes"].append(
        {"path": "/embedding", "type": "diskANN"})
    with pytest.raises(ValueError, match="incompatible"):
        validate_policy(resource, "search_qflat")
