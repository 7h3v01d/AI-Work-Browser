"""
Integration tests that actually run the JavaScript from page_injection.py
inside a real (headless, offscreen) QWebEnginePage.

These are slower than the structural tests in test_page_injection.py but
they catch a whole class of bug the structural tests can't: JS syntax
errors, wrong selector logic, and behaviour that only shows up once the
script actually touches a DOM.
"""

import json

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEnginePage

import page_injection as PI


SAMPLE_CONVERSATION_HTML = """
<!DOCTYPE html>
<html><head></head><body>
{turns}
</body></html>
"""


def _turn(i, with_code=False):
    code = (
        f'<pre><code class="language-python">def f_{i}():\n    return {i}\n'
        f"</code></pre>" if with_code else ""
    )
    return (
        f'<div data-testid="conversation-turn">'
        f"<p>This is message number {i} with some prose content.</p>"
        f"{code}"
        f"</div>"
    )


def run_js(qtbot, page, script, timeout=8000):
    """Run script on page and block (via qtbot) until the async result arrives."""
    box = {}

    def _cb(result):
        box["value"] = result
        box["done"] = True

    page.runJavaScript(script, _cb)
    # NOTE: box.get("done") returns None before the callback fires, and
    # pytest-qt's waitUntil treats a bare `None` result as "condition
    # already satisfied" (its assert-style usage). Force an explicit
    # True/False so it actually waits for the callback.
    qtbot.waitUntil(lambda: bool(box.get("done")), timeout=timeout)
    return box["value"]


@pytest.fixture
def page(qapp, qtbot):
    pg = QWebEnginePage()
    loaded = {"ok": None}

    def _on_load(ok):
        loaded["ok"] = ok

    pg.loadFinished.connect(_on_load)
    return pg, loaded


def _load_html(qtbot, page_and_flag, html):
    pg, loaded = page_and_flag
    loaded["ok"] = None
    pg.setHtml(html, QUrl("https://claude.ai/"))
    qtbot.waitUntil(lambda: loaded["ok"] is not None, timeout=8000)
    assert loaded["ok"] is True
    return pg


def test_compact_css_injection_adds_style_element_once(qtbot, page):
    pg = _load_html(qtbot, page, SAMPLE_CONVERSATION_HTML.format(turns=_turn(0)))

    run_js(qtbot, pg, PI.INJECT_COMPACT_CSS_JS)
    count_after_first = run_js(
        qtbot, pg, "document.querySelectorAll('#aiwb-compact-css').length"
    )
    assert count_after_first == 1

    # Re-running must be idempotent (guarded by `if (document.getElementById(ID)) return;`)
    run_js(qtbot, pg, PI.INJECT_COMPACT_CSS_JS)
    count_after_second = run_js(
        qtbot, pg, "document.querySelectorAll('#aiwb-compact-css').length"
    )
    assert count_after_second == 1

    run_js(qtbot, pg, PI.REMOVE_COMPACT_CSS_JS)
    count_after_remove = run_js(
        qtbot, pg, "document.querySelectorAll('#aiwb-compact-css').length"
    )
    assert count_after_remove == 0


def test_wrap_code_toggles_inline_style_on_pre_and_code(qtbot, page):
    pg = _load_html(
        qtbot, page, SAMPLE_CONVERSATION_HTML.format(turns=_turn(0, with_code=True))
    )

    run_js(qtbot, pg, PI.WRAP_CODE_ON_JS)
    white_space = run_js(
        qtbot, pg, "document.querySelector('pre').style.whiteSpace"
    )
    assert white_space == "pre-wrap"

    run_js(qtbot, pg, PI.WRAP_CODE_OFF_JS)
    white_space_off = run_js(
        qtbot, pg, "document.querySelector('pre').style.whiteSpace"
    )
    assert white_space_off == "pre"


def test_collapse_then_expand_round_trip(qtbot, page):
    # 6 turns, KEEP_RECENT is hard-coded to 4 in make_collapse_js -> 2 collapsed.
    turns = "".join(_turn(i) for i in range(6))
    pg = _load_html(qtbot, page, SAMPLE_CONVERSATION_HTML.format(turns=turns))

    run_js(qtbot, pg, PI.make_collapse_js(keep_code_expanded=True, collapse_prose_only=False))
    collapsed_count = run_js(
        qtbot, pg, "document.querySelectorAll('[data-aiwb-collapsed=\"true\"]').length"
    )
    assert collapsed_count == 2

    overlay_count = run_js(qtbot, pg, "document.querySelectorAll('.aiwb-overlay').length")
    assert overlay_count == 2

    run_js(qtbot, pg, PI.EXPAND_ALL_JS)
    collapsed_after_expand = run_js(
        qtbot, pg, "document.querySelectorAll('[data-aiwb-collapsed=\"true\"]').length"
    )
    assert collapsed_after_expand == 0
    overlay_after_expand = run_js(qtbot, pg, "document.querySelectorAll('.aiwb-overlay').length")
    assert overlay_after_expand == 0


def test_collapse_keeps_code_visible_when_keep_code_expanded(qtbot, page):
    turns = "".join(_turn(i, with_code=True) for i in range(6))
    pg = _load_html(qtbot, page, SAMPLE_CONVERSATION_HTML.format(turns=turns))

    run_js(qtbot, pg, PI.make_collapse_js(keep_code_expanded=True, collapse_prose_only=False))
    # No "Show" placeholder buttons should have been created, and the
    # <pre> elements inside collapsed messages must not carry the
    # hidden-child class.
    placeholder_count = run_js(qtbot, pg, "document.querySelectorAll('.aiwb-code-ph').length")
    assert placeholder_count == 0

    hidden_pre_count = run_js(
        qtbot, pg, "document.querySelectorAll('pre.aiwb-hidden-child').length"
    )
    assert hidden_pre_count == 0


def test_collapse_hides_code_and_adds_placeholder_when_not_keeping_code(qtbot, page):
    turns = "".join(_turn(i, with_code=True) for i in range(6))
    pg = _load_html(qtbot, page, SAMPLE_CONVERSATION_HTML.format(turns=turns))

    run_js(qtbot, pg, PI.make_collapse_js(keep_code_expanded=False, collapse_prose_only=False))
    placeholder_count = run_js(qtbot, pg, "document.querySelectorAll('.aiwb-code-ph').length")
    assert placeholder_count == 2  # one per collapsed message


def test_user_stylesheet_injection_and_removal(qtbot, page):
    pg = _load_html(qtbot, page, SAMPLE_CONVERSATION_HTML.format(turns=_turn(0)))
    css = 'body { background-color: rgb(1, 2, 3); }'

    run_js(qtbot, pg, PI.make_user_stylesheet_js(css))
    applied_text = run_js(qtbot, pg, "document.getElementById('aiwb-user-css').textContent")
    assert applied_text == css

    run_js(qtbot, pg, PI.REMOVE_USER_STYLESHEET_JS)
    exists_after_remove = run_js(qtbot, pg, "!!document.getElementById('aiwb-user-css')")
    assert exists_after_remove is False


def test_extract_text_js_includes_prose_and_fenced_code(qtbot, page):
    pg = _load_html(
        qtbot, page, SAMPLE_CONVERSATION_HTML.format(turns=_turn(1, with_code=True))
    )
    text = run_js(qtbot, pg, PI.EXTRACT_TEXT_JS)
    assert "message number 1" in text
    assert "```" in text
    assert "def f_1" in text


def test_copy_plain_text_js_is_valid_js_and_returns_selected_text(qtbot, page):
    # Regression test: COPY_PLAIN_TEXT_JS/EXTRACT_TEXT_JS contain literal
    # '\n' inside single-quoted JS string replacements (e.g. br.replaceWith('\n')).
    # If those Python string literals are ever accidentally de-raw'd, Python
    # turns '\n' into a real newline *character* embedded inside the JS
    # source, which breaks the single-quoted JS string literal (unterminated
    # string) and makes the whole IIFE throw instead of running. Actually
    # executing the script against a live page is the only way to catch that.
    pg = _load_html(
        qtbot, page,
        SAMPLE_CONVERSATION_HTML.format(turns="<p id='target'>Hello world</p>"),
    )

    # No selection yet -> script must parse fine and return a falsy result,
    # not throw (a SyntaxError would surface as a Qt-side null/failed
    # runJavaScript call rather than a clean value here).
    result_no_selection = run_js(qtbot, pg, PI.COPY_PLAIN_TEXT_JS)
    assert not result_no_selection

    # Now make a real selection and confirm the returned text is correct,
    # which only happens if the script both parsed *and* ran correctly.
    select_script = """
    (function() {
        var el = document.getElementById('target');
        var range = document.createRange();
        range.selectNodeContents(el);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
    })();
    """
    run_js(qtbot, pg, select_script)
    result_with_selection = run_js(qtbot, pg, PI.COPY_PLAIN_TEXT_JS)
    assert result_with_selection == "Hello world"


def test_debug_info_js_reports_selector_hit_counts_as_json(qtbot, page):
    turns = "".join(_turn(i) for i in range(3))
    pg = _load_html(qtbot, page, SAMPLE_CONVERSATION_HTML.format(turns=turns))
    raw = run_js(qtbot, pg, PI.make_debug_info_js())
    info = json.loads(raw)
    assert info["selectors"]['[data-testid="conversation-turn"]'] == 3
    assert info["pre_count"] == 0
