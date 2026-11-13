import ast
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, Mock
from types import ModuleType
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("verify_browser", ROOT / "scripts/verify_browser.py")
browser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(browser)


@pytest.mark.parametrize("role,name,initial,target", [
    ("radio", "any keywords", False, True),
    ("checkbox", "Use Semantic Reranker", False, True),
    ("checkbox", "Use Semantic Reranker", True, False),
])
def test_styled_controls_click_visible_associated_text(role, name, initial, target):
    page = Mock()
    control = page.get_by_role.return_value
    control.is_checked.return_value = initial
    text = control.locator.return_value.get_by_text.return_value
    text.click.side_effect = lambda: setattr(control.is_checked, "return_value", target)

    browser.set_streamlit_checked(page, role, name, target)

    page.get_by_role.assert_called_once_with(role, name=name, exact=True)
    control.locator.assert_called_once_with("xpath=ancestor::label[1]")
    control.locator.return_value.get_by_text.assert_called_once_with(name, exact=True)
    text.click.assert_called_once_with()
    control.check.assert_not_called()
    control.set_checked.assert_not_called()
    assert control.is_checked.call_count == 2


def test_matching_state_is_not_toggled():
    page = Mock()
    page.get_by_role.return_value.is_checked.return_value = True
    browser.set_streamlit_checked(page, "radio", "all keywords", True)
    page.get_by_role.return_value.locator.assert_not_called()


def test_label_click_must_actually_change_input_state():
    page = Mock()
    page.get_by_role.return_value.is_checked.return_value = False
    with pytest.raises(AssertionError, match="checked state"):
        browser.set_streamlit_checked(page, "radio", "any keywords", True)


def test_advanced_matrix_and_count_contract():
    assert {case[0] for case in browser.ADVANCED_CASES} == {"text", "json"}
    assert {case[2] for case in browser.ADVANCED_CASES if case[0] == "json"} == {
        "title", "text", "title,text"}
    assert {case[3] for case in browser.ADVANCED_CASES} == {1, 3, 10}
    assert {case[4] for case in browser.ADVANCED_CASES} == {False, True}
    browser.check_result_counts("Retrieved candidates: 2; returned results: 2", 2, 10)
    browser.check_result_counts("Retrieved candidates: 3; returned results: 1", 1, 1)
    browser.check_result_counts("Retrieved candidates: 3; returned results: 3", 3)
    with pytest.raises(AssertionError):
        browser.check_result_counts("Retrieved candidates: 3; returned results: 3", 3, 1)
    with pytest.raises(AssertionError):
        browser.check_result_counts("Retrieved candidates: 4489; returned results: 4489", 4489)


@pytest.mark.parametrize("k", [1, 10, None])
@pytest.mark.parametrize("finish_render", [False, True])
def test_visible_success_waits_for_script_and_exact_rendered_rows(monkeypatch, k, finish_render):
    displayed = 10 if k is None else min(k, 10)
    # Success status is already visible, while the script runs and the table
    # has no rows. Neither of those intermediate states is a completed result.
    state = {"running": True, "rows": 0, "waited_for_rows": False}
    events = ["success status visible"]
    page = Mock(spec_set=["get_by_test_id", "locator"])
    app = object()
    body = Mock(spec_set=["inner_text"])
    body.inner_text.return_value = (
        f"Semantic reranking: Applied\nRetrieved candidates: 10; returned results: {displayed}")
    rows = Mock(spec_set=["count"])
    page.get_by_test_id.return_value = app
    page.locator.side_effect = {"body": body, "table tbody tr": rows}.__getitem__

    def snapshot_count():
        assert not state["running"] and state["waited_for_rows"], "Premature row snapshot"
        events.append("row snapshot")
        return state["rows"]

    rows.count.side_effect = snapshot_count

    class Assertions:
        def __init__(self, locator):
            self.locator = locator

        def to_have_attribute(self, name, value, *, timeout):
            assert self.locator is app
            assert (name, value, timeout) == ("data-test-script-state", "notRunning", 180_000)
            events.append("script completed")
            state["running"] = False

        def to_contain_text(self, pattern, *, timeout):
            assert self.locator is body and timeout == 180_000
            assert not state["running"] and pattern.search(body.inner_text())
            events.append("metadata visible")

        def to_have_count(self, expected, *, timeout):
            assert self.locator is rows and timeout == 180_000 and expected == displayed
            assert not state["running"] and state["rows"] == 0
            events.append("wait for exact rows")
            state["waited_for_rows"] = True
            if not finish_render:
                raise AssertionError("table did not finish rendering")
            state["rows"] = expected

    api = ModuleType("playwright.sync_api")
    api.expect = Assertions
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)
    if finish_render:
        assert browser.wait_streamlit_results(page, k) == displayed
        assert events == ["success status visible", "script completed", "metadata visible",
                          "wait for exact rows", "row snapshot"]
    else:
        with pytest.raises(AssertionError, match="table did not finish rendering"):
            browser.wait_streamlit_results(page, k)
        rows.count.assert_not_called()


@pytest.mark.parametrize("matrix", ["all", "baseline", "advanced"])
def test_matrix_selector(matrix):
    args = browser.parse_args(["--matrix", matrix, "--include-dotnet"])
    assert args.matrix == matrix and args.include_dotnet
    assert browser.parse_args([]).matrix == "all"


def test_razor_uses_named_search_buttons_and_native_radios():
    source = (ROOT / "scripts/verify_browser.py").read_text(encoding="utf-8")
    assert 'page.locator("#Mode")' not in source
    assert 'page.locator("#AllKeywords").select_option' not in source
    assert 'name="Search", exact=True' not in source
    assert 'page.locator("#Query")' not in source
    assert 'name="Similarity search", exact=True).click()' in source
    assert '"all keywords" if all_words == "true" else "any keywords"), exact=True).check()' in source


def test_advanced_completion_assertions_have_explicit_service_deadlines():
    # Playwright's expect timeout is independent of page.set_default_timeout.
    # Inspect the actual call sites so an unconfigured assertion cannot hide
    # behind mocked browser timing.
    expected = {
        "Semantic reranking: ✓ Applied", "Semantic reranking: ✗ Not applied",
        "Reranked results", "Retrieval results",
    }
    found = set()
    tree = ast.parse((ROOT / "scripts/verify_browser.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        label = None
        if node.func.attr == "to_have_text" and node.args and isinstance(node.args[0], ast.Constant):
            label = node.args[0].value
        elif node.func.attr == "to_be_visible":
            assertion = node.func.value
            if isinstance(assertion, ast.Call) and assertion.args:
                locator = assertion.args[0]
                if (isinstance(locator, ast.Call) and isinstance(locator.func, ast.Attribute)
                        and locator.func.attr == "get_by_text" and locator.args
                        and isinstance(locator.args[0], ast.Constant)):
                    label = locator.args[0].value
        if label in expected:
            deadlines = [kw.value for kw in node.keywords if kw.arg == "timeout"]
            assert len(deadlines) == 1, f"{label}: missing explicit service deadline"
            assert ast.literal_eval(deadlines[0]) == 180_000
            found.add(label)
    assert found == expected


def selectbox_fakes(monkeypatch, value):
    class PopupTimeout(Exception):
        pass

    api = ModuleType("playwright.sync_api")
    api.TimeoutError = PopupTimeout
    api.expect = Mock()
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)
    ready = Mock()
    monkeypatch.setattr(browser, "wait_streamlit_ready", ready)
    page = Mock(spec_set=["get_by_role", "get_by_test_id", "wait_for_timeout"])
    control = Mock(spec_set=["input_value", "click"])
    control.click.side_effect = AssertionError("Clicking the input only focuses it.")
    option, opener = Mock(spec_set=["click"]), Mock(spec_set=["click"])
    selectbox = Mock(spec_set=["get_by_role"])
    selectbox.get_by_role.return_value = opener
    widgets = Mock(spec_set=["filter"])
    widgets.filter.return_value = selectbox
    page.get_by_test_id.return_value = widgets
    page.get_by_role.side_effect = lambda role, **kwargs: control if role == "combobox" else option
    control.input_value.return_value = value

    def assert_value(expected):
        assert control.input_value() == expected, "wrong selection"

    api.expect.return_value.to_have_value.side_effect = assert_value
    return page, control, option, opener, api, ready


def test_current_selectbox_value_is_asserted_without_opening_popup(monkeypatch):
    page, control, option, opener, api, ready = selectbox_fakes(monkeypatch, "text")
    browser.set_streamlit_selected(page, "Document format", "text")
    control.click.assert_not_called()
    opener.click.assert_not_called()
    option.click.assert_not_called()
    api.expect.return_value.to_have_value.assert_called_once_with("text")
    ready.assert_called()


def test_selectbox_opens_accessible_button_and_asserts_native_value(monkeypatch):
    page, control, option, opener, api, ready = selectbox_fakes(monkeypatch, "text")
    events = []
    ready.side_effect = lambda *args: events.append("ready")
    opener.click.side_effect = lambda: events.append("open")

    def choose(**kwargs):
        events.append("select")
        control.input_value.return_value = "json"

    option.click.side_effect = choose
    browser.set_streamlit_selected(page, "Document format", "json")
    assert events == ["ready", "open", "select", "ready"]
    page.get_by_role.assert_any_call("combobox", name="Document format", exact=True)
    page.get_by_role.assert_any_call("option", name="json", exact=True)
    page.get_by_test_id.return_value.filter.assert_called_once_with(has=control)
    page.get_by_test_id.return_value.filter.return_value.get_by_role.assert_called_once_with(
        "button", name="Open", exact=True)
    opener.click.assert_called_once_with()
    option.click.assert_called_once_with(timeout=5000)
    control.click.assert_not_called()
    api.expect.return_value.to_have_value.assert_called_once_with("json")
    page.wait_for_timeout.assert_not_called()


def test_selectbox_timeout_is_not_retried_or_hidden(monkeypatch):
    page, _, option, opener, api, _ = selectbox_fakes(monkeypatch, "text")
    option.click.side_effect = api.TimeoutError("original option timeout")
    with pytest.raises(api.TimeoutError, match="original option timeout"):
        browser.set_streamlit_selected(page, "Document format", "json")
    opener.click.assert_called_once_with()
    option.click.assert_called_once_with(timeout=5000)
    api.expect.return_value.to_have_value.assert_not_called()


def test_wrong_selected_value_still_fails(monkeypatch):
    page, _, _, _, api, _ = selectbox_fakes(monkeypatch, "text")
    with pytest.raises(AssertionError, match="wrong selection"):
        browser.set_streamlit_selected(page, "Document format", "json")


@pytest.mark.parametrize("matrix,case", [
    ("all", "qflat-Vector-true-rerank-False"),
    ("advanced", "advanced-qflat-text-title,text-1-sentences-False"),
])
@pytest.mark.parametrize("capture_fails", [False, True])
def test_failure_capture_preserves_original_error(
        tmp_path, monkeypatch, caplog, capture_fails, matrix, case):
    class BrowserError(Exception):
        pass

    api = ModuleType("playwright.sync_api")
    api.Error = BrowserError
    api.expect = Mock()
    api.sync_playwright = MagicMock()
    instance = api.sync_playwright.return_value.__enter__.return_value.chromium.launch.return_value
    page = instance.new_page.return_value
    original = AssertionError("original browser failure")
    page.goto.side_effect = original
    capture_error = BrowserError("capture failed")
    if capture_fails:
        page.screenshot.side_effect = capture_error
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)
    monkeypatch.setattr(browser, "__file__", str(tmp_path / "scripts/verify_browser.py"))
    monkeypatch.setattr(sys, "argv", ["verify_browser.py", "--matrix", matrix])
    monkeypatch.setenv("RUN_LIVE_TESTS", "1")

    with pytest.raises(AssertionError, match="original browser failure") as caught:
        browser.main()

    assert caught.value is original
    records = [record for record in caplog.records if record.exc_info]
    assert len(records) == int(capture_fails)
    if capture_fails:
        assert records[0].exc_info[1] is capture_error
        assert records[0].exc_info[2] is not None
    page.screenshot.assert_called_once_with(
        path=str(tmp_path / ".local/validation/movielens/"
                 f"failure-python-{case}.png"),
        full_page=True, timeout=10_000)
    instance.close.assert_called_once_with()
