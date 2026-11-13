import json
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

import search_demo

APP = Path(__file__).resolve().parents[2] / "src/app/cosmos-app.py"

DATASET_SOURCE = (
    "https://github.com/TheovanKraay/AzureDataRetrievalAugmentedGenerationSamples/"
    "blob/7fd162fc633617857f8b8ed2c5b2b92d4d8ef0b6/DataSet/Movies/MovieLens-4489-256D.json"
)


def test_summary_uses_pinned_source_contract_not_smoke_fixture():
    from seed_movies import SOURCE_ROWS, SOURCE_URL
    assert SOURCE_ROWS == 4489
    assert SOURCE_URL.endswith("/DataSet/Movies/MovieLens-4489-256D.json")
    assert "7fd162fc633617857f8b8ed2c5b2b92d4d8ef0b6" in SOURCE_URL
    assert "movies.original.json" not in APP.read_text(encoding="utf-8")


def assert_dataset_summary(app, container="search_qflat", database="Not configured"):
    text = "\n".join(item.value for item in app.main.markdown)
    assert "Default source corpus: MovieLens" in text
    assert "4,489 source rows" in text
    assert "10 original movie plots" not in text
    assert f"[View pinned MovieLens source]({DATASET_SOURCE})" in text
    assert "azd up" in text and "custom data" in text
    assert "not a live inventory" in text
    assert all(example in text for example in (
        "Woody Buzz", "fishing buddies", "toys learning to share a child's affection"))
    config = "\n".join(item.value for item in app.main.text)
    assert f"Configured database: {database}" in config
    assert f"Selected container: {container}" in config


def test_dataset_summary_uses_config_only_and_tracks_selection(monkeypatch):
    monkeypatch.setenv("COSMOS_DB_DATABASE", "custom-movies")
    monkeypatch.setenv("COSMOS_URI", "https://private-endpoint.invalid")
    for name in ("get_container", "get_inference_client", "get_cosmos_client",
                 "get_credential", "get_embedding_client", "embed_text"):
        monkeypatch.setattr(search_demo, name, Mock(side_effect=AssertionError(name)))
    # First Streamlit run includes cold imports after the full unit suite.
    # Bound startup separately; keep all service guards and exception assertions.
    app = AppTest.from_file(str(APP)).run(timeout=15)
    assert not app.exception
    assert_dataset_summary(app, database="custom-movies")
    assert len(app.table) == 0
    app.selectbox(key="index_selection").select("DiskANN & Full Text Search Index").run()
    assert not app.exception
    assert_dataset_summary(app, container="search_diskann", database="custom-movies")
    assert "private-endpoint" not in "\n".join(
        item.value for item in [*app.main.markdown, *app.main.text])


def fake_services(monkeypatch):
    container = Mock()
    container.query_items.return_value = [
        {"id": "a", "title": "Space rescue", "text": "An orbital rescue."},
        {"id": "b", "title": "Garden", "text": "A peaceful garden."},
    ]
    inference = Mock()
    inference.semantic_rerank.return_value = {
        "scores": [{"index": 0, "score": 0.9}, {"index": 1, "score": 0.1}]
    }
    monkeypatch.setattr(search_demo, "get_container", lambda name: container)
    monkeypatch.setattr(search_demo, "get_inference_client", lambda: inference)
    monkeypatch.setattr(search_demo, "embed_text", lambda text: [1.0] + [0.0] * 1535)
    return container, inference


def test_startup_does_not_create_clients_or_write(monkeypatch):
    for name in ("get_container", "get_inference_client", "embed_text"):
        monkeypatch.setattr(search_demo, name, Mock(side_effect=AssertionError(name)))
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert len(app.button) == 4
    assert len(app.selectbox) == 3
    assert len(app.checkbox) == 2
    assert len(app.radio) == 1
    assert all(button.disabled for button in app.button)
    assert app.selectbox(key="rerank_format").value == "text"
    assert app.number_input(key="rerank_top_k").value == 10
    assert not app.checkbox(key="sentence_diagnostics").value
    assert app.selectbox(key="rerank_format").disabled
    assert app.selectbox(key="rerank_fields").disabled
    assert app.number_input(key="rerank_top_k").disabled
    assert app.checkbox(key="sentence_diagnostics").disabled
    assert_dataset_summary(app)
    assert len(app.table) == 0


@pytest.mark.parametrize("button", ["location_search", "full_text_search",
                                    "full_text_ranking", "hybrid_search"])
@pytest.mark.parametrize("enabled", [False, True])
def test_ui_all_buttons(monkeypatch, button, enabled):
    container, inference = fake_services(monkeypatch)
    app = AppTest.from_file(str(APP)).run()
    app.text_input(key="user_query").set_value("space rescue")
    app.checkbox(key="use_reranker").set_value(enabled)
    app.run()
    app.button(key=button).click().run()
    assert not app.exception and not app.error
    assert len(app.table) == 1
    assert len(app.table[0].value) == 2
    assert ("rerank_score" in app.table[0].value.columns) is enabled
    assert inference.semantic_rerank.call_count == int(enabled)
    container.query_items.assert_called_once()
    assert_dataset_summary(app)


def test_visible_error_no_stale_success(monkeypatch):
    _, inference = fake_services(monkeypatch)
    app = AppTest.from_file(str(APP)).run()
    app.text_input(key="user_query").set_value("rescue").run()
    app.button(key="full_text_ranking").click().run()
    assert len(app.table) == 1
    inference.semantic_rerank.side_effect = RuntimeError("private endpoint secret")
    app.checkbox(key="use_reranker").check().run()
    app.button(key="full_text_ranking").click().run()
    assert not app.exception
    assert len(app.error) == 1 and "Reranking failed" in app.error[0].value
    assert "private endpoint" not in app.error[0].value
    assert len(app.table) == 0
    assert_dataset_summary(app)


@pytest.mark.parametrize("phase", ["container", "embedding-client", "retrieval",
                                  "inference-client", "reranking", "table"])
@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
def test_failure_logged_once_with_original_traceback_not_browser(
        monkeypatch, caplog, phase, error_type):
    import pandas as pd

    embed_text = search_demo.embed_text
    container, inference = fake_services(monkeypatch)
    app = AppTest.from_file(str(APP)).run()
    app.text_input(key="user_query").set_value("rescue").run()
    app.button(key="full_text_ranking").click().run()
    assert len(app.table) == 1
    private = "https://private.invalid/?key=secret query=document-content"
    original = error_type(private)
    failure = Mock(side_effect=original)
    button = "full_text_ranking"
    if phase == "container":
        monkeypatch.setattr(search_demo, "get_container", failure)
    elif phase == "embedding-client":
        monkeypatch.setattr(search_demo, "embed_text", embed_text)
        monkeypatch.setattr(search_demo, "get_embedding_client", failure)
        button = "location_search"
    elif phase == "retrieval":
        container.query_items = failure
    elif phase == "inference-client":
        monkeypatch.setattr(search_demo, "get_inference_client", failure)
        app.checkbox(key="use_reranker").check().run()
    elif phase == "reranking":
        inference.semantic_rerank = failure
        app.checkbox(key="use_reranker").check().run()
    else:
        monkeypatch.setattr(pd, "DataFrame", failure)
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        app.button(key=button).click().run()
        app.run()  # Rendering again must not log the same failure twice.
    failure.assert_called_once()
    assert not app.exception and len(app.error) == 1 and not app.table
    assert "search_result" not in app.session_state
    assert "suggested_listings" not in app.session_state
    assert private not in app.error[0].value
    visible = "\n".join(item.value for item in [*app.main.markdown, *app.main.text])
    assert private not in visible and "Executed query:" not in visible
    assert "Applied" not in visible and "execution time:" not in visible
    records = [record for record in caplog.records if record.exc_info]
    assert len(records) == 1
    logged = records[0].exc_info[1]
    assert (logged.__cause__ if isinstance(logged, search_demo.SearchError) else logged) is original
    assert records[0].exc_info[2] is not None
    assert private in logging.Formatter().format(records[0])


def test_ui_any_keywords_and_diskann_selection(monkeypatch):
    container, _ = fake_services(monkeypatch)
    get_container = Mock(return_value=container)
    monkeypatch.setattr(search_demo, "get_container", get_container)
    app = AppTest.from_file(str(APP)).run()
    app.selectbox(key="index_selection").select("DiskANN & Full Text Search Index")
    app.radio(key="full_text_search_type").set_value("any keywords")
    app.text_input(key="user_query").set_value("orbital rescue").run()
    app.button(key="full_text_search").click().run()
    assert not app.exception and not app.error
    get_container.assert_called_once_with("search_diskann")
    assert "FullTextContainsAny" in container.query_items.call_args.args[0]
    assert_dataset_summary(app, container="search_diskann")


def test_missing_openai_visible(monkeypatch):
    fake_services(monkeypatch)
    monkeypatch.setattr(search_demo, "embed_text", Mock(side_effect=search_demo.SearchError(
        "Set AZURE_OPENAI_EMBEDDING_DEPLOYMENT for vector and hybrid search.")))
    app = AppTest.from_file(str(APP)).run()
    app.text_input(key="user_query").set_value("rescue").run()
    app.button(key="location_search").click().run()
    assert "AZURE_OPENAI_EMBEDDING_DEPLOYMENT" in app.error[0].value


@pytest.mark.parametrize("format,fields", [
    ("text", "Title and Description"), ("json", "Title only"),
    ("json", "Description only"), ("json", "Title and Description"),
])
@pytest.mark.parametrize("diagnostics", [False, True])
def test_advanced_ui_subset_details_and_off(monkeypatch, format, fields, diagnostics):
    _, inference = fake_services(monkeypatch)
    inference.semantic_rerank.return_value = {
        "scores": [{"index": 1, "score": 0.9,
                    "sentenceScores": [{"index": 7, "score": 0.75}]}]}
    app = AppTest.from_file(str(APP)).run()
    app.text_input(key="user_query").set_value("rescue")
    app.checkbox(key="use_reranker").check().run()
    app.selectbox(key="rerank_format").set_value(format).run()
    if format == "json":
        app.selectbox(key="rerank_fields").set_value(fields)
    app.number_input(key="rerank_top_k").set_value(1)
    app.checkbox(key="sentence_diagnostics").set_value(diagnostics).run()
    app.button(key="full_text_ranking").click().run()
    assert not app.exception and not app.error
    assert len(app.table) == 1 and len(app.table[0].value) == 1
    assert app.table[0].value.iloc[0]["id"] == "b"
    assert "sentence_scores" not in app.table[0].value.columns
    assert app.session_state.search_result.retrieved_count == 2
    payload = inference.semantic_rerank.call_args.args[0]
    assert payload["topK"] == 1
    assert (payload.get("documentType") == "json") is (format == "json")
    if format == "json":
        assert payload["targetPaths"] == {
            "Title only": "title", "Description only": "text",
            "Title and Description": "title,text"}[fields]
    assert ("returnSentenceScore" in payload) is diagnostics
    text = "\n".join(item.value for item in app.markdown)
    assert ("Service sentence index: 7; score: 0.75" in text) is diagnostics
    app.checkbox(key="use_reranker").uncheck().run()
    assert app.number_input(key="rerank_top_k").disabled
    app.button(key="full_text_ranking").click().run()
    assert len(app.table[0].value) == 2
    assert inference.semantic_rerank.call_count == 1
    assert not app.session_state.search_result.sentence_scores_requested
