from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.live
APP = Path(__file__).resolve().parents[2] / "src/app/cosmos-app.py"


@pytest.mark.parametrize("index", ["QFLAT & Full Text Search Index",
                                  "DiskANN & Full Text Search Index"])
@pytest.mark.parametrize("button", ["full_text_search", "full_text_ranking"])
@pytest.mark.parametrize("enabled", [False, True])
def test_live_page_executes_search_and_reranking(loaded_containers, index, button, enabled):
    # AppTest runs the Streamlit page and its actual callbacks, not just HTTP health.
    app = AppTest.from_file(str(APP), default_timeout=180).run()
    assert not app.exception
    app.selectbox(key="index_selection").select(index)
    app.text_input(key="user_query").set_value("orbital rescue")
    app.checkbox(key="use_reranker").set_value(enabled)
    app.run()
    app.button(key=button).click().run(timeout=180)
    assert not app.exception
    assert not app.error, "Live UI search failed; inspect the visible error."
    assert len(app.table) == 1 and len(app.table[0].value) > 0
    table = app.table[0].value
    assert "synthetic-orbit-rescue" in table["id"].tolist()
    assert ("rerank_score" in table.columns) is enabled
    assert "title" in table.columns and "text" in table.columns
