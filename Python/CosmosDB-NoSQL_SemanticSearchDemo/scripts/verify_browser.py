"""Read-only real-browser matrix against apps already owned by the foreground launcher."""

import argparse
import logging
import math
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit
import re

logger = logging.getLogger(__name__)

# Targeted additions, not a Cartesian expansion of the baseline mode matrix.
ADVANCED_CASES = [
    ("text", "Title and Description", "title,text", 1, False),
    ("text", "Title and Description", "title,text", 3, True),
    ("json", "Title only", "title", 1, True),
    ("json", "Description only", "text", 3, True),
    ("json", "Title and Description", "title,text", 10, True),
    ("json", "Title and Description", "title,text", 3, False),
]


def check_result_counts(text, returned, k=None):
    match = re.search(r"Retrieved candidates: (\d+); returned results: (\d+)", text)
    assert match, "Candidate/returned count display missing."
    candidates, displayed = map(int, match.groups())
    assert 0 < candidates <= 10 and displayed == returned
    assert returned == (candidates if k is None else min(k, candidates))


def check_sentence_details(details):
    text = details.inner_text()
    if "not returned" in text:
        return
    values = re.findall(r"Service sentence index: (\d+); score: ([^\s]+)", text)
    assert values, "Sentence detail has neither numeric service values nor an absence message."
    assert all(int(index) >= 0 and math.isfinite(float(score)) for index, score in values)

def local_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise argparse.ArgumentTypeError("Use a loopback HTTP app URL without credentials or paths.")
    return value.rstrip("/")


def set_streamlit_checked(page, role, name, checked):
    control = page.get_by_role(role, name=name, exact=True)
    if control.is_checked() != checked:
        # Streamlit styles the input beneath its visible wrapping label.
        # Exercise the user's visible click target, never force the hidden input.
        control.locator("xpath=ancestor::label[1]").get_by_text(name, exact=True).click()
    assert control.is_checked() == checked, f"{name}: label click did not produce the requested checked state."


def wait_streamlit_ready(page):
    from playwright.sync_api import expect
    app = page.get_by_test_id("stApp")
    expect(app).to_have_attribute("data-test-connection-state", "CONNECTED", timeout=30_000)
    expect(app).to_have_attribute("data-test-script-state", "notRunning", timeout=30_000)


def wait_streamlit_results(page, k=None):
    """Success status precedes streamed table rendering. Await both completion gates."""
    from playwright.sync_api import expect
    expect(page.get_by_test_id("stApp")).to_have_attribute(
        "data-test-script-state", "notRunning", timeout=180_000)
    body = page.locator("body")
    pattern = re.compile(r"Retrieved candidates: (\d+); returned results: (\d+)")
    expect(body).to_contain_text(pattern, timeout=180_000)
    metadata = body.inner_text()
    match = pattern.search(metadata)
    assert match, "Candidate/returned count display missing after script completion."
    displayed = int(match.group(2))
    # Validate metadata against K before waiting. An incorrect service/result
    # cardinality is still an error, never a rendering fallback.
    check_result_counts(metadata, displayed, k)
    rows = page.locator("table tbody tr")
    expect(rows).to_have_count(displayed, timeout=180_000)
    returned = rows.count()
    check_result_counts(body.inner_text(), returned, k)
    return returned


def set_streamlit_selected(page, name, value):
    from playwright.sync_api import expect
    control = page.get_by_role("combobox", name=name, exact=True)
    widget = page.get_by_test_id("stSelectbox").filter(has=control)
    wait_streamlit_ready(page)
    expect(control).to_be_enabled()
    # The current react-aria combobox holds the selected display text. Clicking
    # its input only focuses it; the adjacent accessible Open button opens options.
    if control.input_value() != value:
        widget.get_by_role("button", name="Open", exact=True).click()
        page.get_by_role("option", name=value, exact=True).click(timeout=5000)
        wait_streamlit_ready(page)
    expect(control).to_have_value(value)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-dotnet", action="store_true")
    parser.add_argument("--matrix", choices=("all", "baseline", "advanced"), default="all",
                        help="Run all cases (default), only baseline, or only advanced cases.")
    parser.add_argument("--python-url", type=local_url, default="http://127.0.0.1:8501")
    parser.add_argument("--dotnet-url", type=local_url, default="http://127.0.0.1:8503")
    return parser.parse_args(argv)


def main():
    args = parse_args()
    if os.getenv("RUN_LIVE_TESTS") != "1":
        raise SystemExit("Set RUN_LIVE_TESTS=1. This browser matrix calls real Azure services.")
    from playwright.sync_api import Error as PlaywrightError, expect, sync_playwright

    private = Path(__file__).resolve().parents[1] / ".local/validation/movielens"
    private.mkdir(parents=True, exist_ok=True)
    modes = [
        ("Vector", "Similarity search", "true"),
        ("FullText", "Full text search", "true"),
        ("FullText", "Full text search", "false"),
        ("FullTextRank", "Full text ranking", "true"),
        ("Hybrid", "Hybrid search", "true"),
    ]
    indexes = (("qflat", "QFLAT & Full Text Search Index"),
               ("diskann", "DiskANN & Full Text Search Index"))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = None
        case, implementation = "startup", "browser"
        try:
            page = browser.new_page()
            page.set_default_timeout(180_000)
            for selector, index in (indexes if args.matrix != "advanced" else ()):
                for enabled in (False, True):
                    for mode, button, all_words in modes:
                        case = f"{selector}-{mode}-{all_words}-rerank-{enabled}"
                        implementation = "python"
                        page.goto(args.python_url)
                        expect(page.get_by_text("Default source corpus: MovieLens", exact=True)).to_be_visible()
                        expect(page.locator("body")).to_contain_text("4,489 source rows")
                        expected_id = ("movielens-4489-v1-" if mode == "FullText" and all_words == "false"
                                       else "movielens-4489-v1-0001-862")
                        page.get_by_role("combobox", name="Index", exact=True).click()
                        page.get_by_role("option", name=index, exact=True).click()
                        query = page.get_by_role("textbox", name="Search input", exact=True)
                        query.fill("Woody Buzz")
                        query.press("Enter")
                        set_streamlit_checked(page, "checkbox", "Use Semantic Reranker", enabled)
                        set_streamlit_checked(page, "radio",
                                              "all keywords" if all_words == "true" else "any keywords", True)
                        page.get_by_role("button", name=button, exact=True).click()
                        table = page.locator("table")
                        expect(table).to_contain_text(expected_id, timeout=180_000)
                        expect(page.get_by_text(
                            "Semantic reranking: " + ("✓ Applied" if enabled else "✗ Not applied"),
                            exact=True)).to_be_visible()
                        assert ("rerank_score" in table.inner_text()) is enabled
                        page.screenshot(path=str(private / f"python-{case}.png"))
                        print(f"PASS Python {case}", flush=True)
                        if not args.include_dotnet:
                            continue
                        implementation = "dotnet"
                        page.goto(args.dotnet_url)
                        expect(page.locator("#dataset-summary")).to_contain_text("4,489 source rows")
                        page.get_by_role("textbox", name="Search input", exact=True).fill("Woody Buzz")
                        page.locator("#Container").select_option(selector)
                        page.get_by_role("radio", name=(
                            "all keywords" if all_words == "true" else "any keywords"), exact=True).check()
                        page.locator("#Rerank").set_checked(enabled)
                        page.get_by_role("button", name=button, exact=True).click()
                        expect(page.locator("#results")).to_contain_text(
                            expected_id, timeout=180_000)
                        assert page.locator("#search-error").count() == 0
                        expect(page.locator("#result-status")).to_have_text(
                            "Reranked results" if enabled else "Retrieval results")
                        scores = page.locator(".rerank-score").all_text_contents()
                        assert scores
                        assert all(math.isfinite(float(score)) if enabled else score == "n/a"
                                   for score in scores)
                        page.screenshot(path=str(private / f"dotnet-{case}.png"))
                        print(f"PASS .NET {case}", flush=True)
            for selector, index in (indexes if args.matrix != "baseline" else ()):
                for format, fields, paths, k, diagnostics in ADVANCED_CASES:
                    case = f"advanced-{selector}-{format}-{paths}-{k}-sentences-{diagnostics}"
                    implementation = "python"
                    page.goto(args.python_url)
                    wait_streamlit_ready(page)
                    panel = page.get_by_text("Advanced reranking", exact=True)
                    expect(page.locator('details').filter(has=panel)).not_to_have_attribute("open", "")
                    panel.click()
                    expect(page.get_by_role("spinbutton", name="Rerank result limit", exact=True)).to_be_disabled()
                    set_streamlit_selected(page, "Index", index)
                    query = page.get_by_role("textbox", name="Search input", exact=True)
                    query.fill("Woody Buzz")
                    query.press("Enter")
                    expect(page.get_by_role("button", name="Similarity search", exact=True)).to_be_enabled()
                    wait_streamlit_ready(page)
                    set_streamlit_checked(page, "checkbox", "Use Semantic Reranker", True)
                    expect(page.get_by_role("combobox", name="Document format", exact=True)).to_be_enabled()
                    set_streamlit_selected(page, "Document format", format)
                    if format == "json":
                        expect(page.get_by_role("combobox", name="JSON fields", exact=True)).to_be_enabled()
                        set_streamlit_selected(page, "JSON fields", fields)
                    limit = page.get_by_role("spinbutton", name="Rerank result limit", exact=True)
                    limit.fill(str(k))
                    limit.press("Enter")
                    wait_streamlit_ready(page)
                    expect(limit).to_have_value(str(k))
                    set_streamlit_checked(page, "checkbox", "Sentence-score diagnostics", diagnostics)
                    wait_streamlit_ready(page)
                    expect(page.get_by_role("checkbox", name="Sentence-score diagnostics",
                                            exact=True)).to_be_checked(checked=diagnostics)
                    page.get_by_role("button", name="Similarity search", exact=True).click()
                    expect(page.get_by_text("Semantic reranking: ✓ Applied", exact=True)).to_be_visible(timeout=180_000)
                    returned = wait_streamlit_results(page, k)
                    assert page.get_by_test_id("stAlert").count() == 0
                    check_result_counts(page.locator("body").inner_text(), returned, k)
                    details = page.locator("details").filter(
                        has=page.locator("summary").filter(has_text="Sentence scores: result"))
                    expect(details).to_have_count(returned if diagnostics else 0, timeout=180_000)
                    if diagnostics:
                        details.first.locator("summary").click()
                        check_sentence_details(details.first)
                    page.screenshot(path=str(private / f"python-{case}.png"))
                    # Turning reranking off must ignore the retained advanced values.
                    set_streamlit_checked(page, "checkbox", "Use Semantic Reranker", False)
                    expect(limit).to_be_disabled()
                    page.get_by_role("button", name="Similarity search", exact=True).click()
                    expect(page.get_by_text("Semantic reranking: ✗ Not applied", exact=True)).to_be_visible(timeout=180_000)
                    returned = wait_streamlit_results(page)
                    assert page.get_by_test_id("stAlert").count() == 0
                    check_result_counts(page.locator("body").inner_text(), returned)
                    expect(details).to_have_count(0, timeout=180_000)
                    print(f"PASS Python {case} and off ignores options", flush=True)
                    if not args.include_dotnet:
                        continue
                    implementation = "dotnet"
                    page.goto(args.dotnet_url)
                    expect(page.locator("#advanced-reranking")).not_to_have_attribute("open", "")
                    page.locator("#advanced-reranking summary").click()
                    expect(page.locator("#RerankTopK")).to_be_disabled()
                    page.get_by_role("textbox", name="Search input", exact=True).fill("Woody Buzz")
                    page.locator("#Container").select_option(selector)
                    page.locator("#Rerank").set_checked(True)
                    page.locator("#DocumentFormat").select_option(format)
                    if format == "json":
                        page.locator("#TargetPaths").select_option(paths)
                    page.locator("#RerankTopK").fill(str(k))
                    page.locator("#ReturnSentenceScores").set_checked(diagnostics)
                    page.get_by_role("button", name="Similarity search", exact=True).click()
                    expect(page.locator("#result-status")).to_have_text("Reranked results", timeout=180_000)
                    assert page.locator("#search-error").count() == 0
                    returned = page.locator("#results tbody tr").count()
                    check_result_counts(page.locator("#candidate-count").inner_text(), returned, k)
                    details = page.locator(".sentence-scores")
                    assert details.count() == (returned if diagnostics else 0)
                    if diagnostics:
                        details.first.locator("summary").click()
                        check_sentence_details(details.first)
                    page.screenshot(path=str(private / f"dotnet-{case}.png"))
                    page.locator("#Rerank").set_checked(False)
                    expect(page.locator("#RerankTopK")).to_be_disabled()
                    page.get_by_role("button", name="Similarity search", exact=True).click()
                    expect(page.locator("#result-status")).to_have_text("Retrieval results", timeout=180_000)
                    expect(page.locator("#DocumentFormat")).to_have_value(format)
                    expect(page.locator("#TargetPaths")).to_have_value(paths)
                    expect(page.locator("#RerankTopK")).to_have_value(str(k))
                    expect(page.locator("#RerankTopK")).to_be_disabled()
                    expect(page.locator("#ReturnSentenceScores")).to_be_checked(checked=diagnostics)
                    check_result_counts(page.locator("#candidate-count").inner_text(),
                                        page.locator("#results tbody tr").count())
                    assert page.locator(".sentence-scores").count() == 0
                    print(f"PASS .NET {case} and off ignores options", flush=True)
        except (AssertionError, PlaywrightError, ValueError):
            if page is not None:
                failure_path = private / f"failure-{implementation}-{case}.png"
                try:
                    page.screenshot(path=str(failure_path), full_page=True, timeout=10_000)
                    print(f"FAIL {implementation} {case}; screenshot: {failure_path}", file=sys.stderr, flush=True)
                except (PlaywrightError, OSError) as capture_error:
                    logger.exception("Failure screenshot capture failed.")
                    print(f"Failure screenshot unavailable ({type(capture_error).__name__}); "
                          "preserving the original test failure.", file=sys.stderr, flush=True)
            raise
        finally:
            browser.close()
    print(f"PASS real browser matrix ({args.matrix}). "
          "No app processes were started or stopped; no data was written.")


if __name__ == "__main__":
    main()
