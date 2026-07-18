"""
Structural / string-level tests for page_injection.py.

These don't execute the generated JavaScript (see
test_page_injection_integration.py for that) — they verify that the
Python side builds the *right* strings: correct selectors embedded,
correct boolean literals, correct JSON-escaping of user-controlled
text, and no accidental regressions in the constants that the rest of
the app depends on by name.
"""

import json

import page_injection as PI


# ---------------------------------------------------------------------------
# MESSAGE_SELECTORS / _ALL_SELECTORS
# ---------------------------------------------------------------------------

def test_message_selectors_has_entry_for_each_known_site():
    for site in ("claude.ai", "chatgpt.com", "gemini.google.com"):
        assert site in PI.MESSAGE_SELECTORS
        assert isinstance(PI.MESSAGE_SELECTORS[site], list)
        assert len(PI.MESSAGE_SELECTORS[site]) > 0
        assert all(isinstance(sel, str) and sel for sel in PI.MESSAGE_SELECTORS[site])


def test_all_selectors_is_deduplicated():
    assert len(PI._ALL_SELECTORS) == len(set(PI._ALL_SELECTORS))


def test_all_selectors_contains_every_site_specific_selector_in_order():
    flat = []
    for sels in PI.MESSAGE_SELECTORS.values():
        for s in sels:
            if s not in flat:
                flat.append(s)
    assert PI._ALL_SELECTORS[: len(flat)] == flat


def test_all_selectors_appends_generic_fallbacks_last():
    generic = [
        '[class*="message-container"]',
        '[class*="MessageContainer"]',
        '[class*="chat-message"]',
        '[class*="ChatMessage"]',
    ]
    for g in generic:
        assert g in PI._ALL_SELECTORS


def test_selectors_js_is_exact_json_of_all_selectors():
    assert PI._SELECTORS_JS == json.dumps(PI._ALL_SELECTORS)
    assert json.loads(PI._SELECTORS_JS) == PI._ALL_SELECTORS


# ---------------------------------------------------------------------------
# Compact CSS
# ---------------------------------------------------------------------------

def test_compact_css_never_touches_code_whitespace_rules():
    assert "white-space:   pre         !important" in PI.COMPACT_CSS
    assert "word-break:    normal" in PI.COMPACT_CSS


def test_compact_css_preserves_markdown_headings_and_blockquotes():
    for tag in ("h1", "h2", "h3", "blockquote"):
        assert f"{tag} {{" in PI.COMPACT_CSS or f"{tag}{{" in PI.COMPACT_CSS


def test_inject_compact_css_js_embeds_the_css_as_json_and_is_idempotent():
    assert json.dumps(PI.COMPACT_CSS) in PI.INJECT_COMPACT_CSS_JS
    assert "aiwb-compact-css" in PI.INJECT_COMPACT_CSS_JS
    assert "if (document.getElementById(ID)) return;" in PI.INJECT_COMPACT_CSS_JS


def test_remove_compact_css_js_targets_same_id():
    assert "aiwb-compact-css" in PI.REMOVE_COMPACT_CSS_JS
    assert ".remove()" in PI.REMOVE_COMPACT_CSS_JS


# ---------------------------------------------------------------------------
# Wrap code lines
# ---------------------------------------------------------------------------

def test_wrap_code_on_sets_pre_wrap_and_break_all():
    assert "pre-wrap" in PI.WRAP_CODE_ON_JS
    assert "break-all" in PI.WRAP_CODE_ON_JS


def test_wrap_code_off_restores_pre_and_normal():
    assert "'pre'" in PI.WRAP_CODE_OFF_JS
    assert "'normal'" in PI.WRAP_CODE_OFF_JS


# ---------------------------------------------------------------------------
# make_collapse_js
# ---------------------------------------------------------------------------

def test_make_collapse_js_embeds_boolean_flags_correctly():
    js_tt = PI.make_collapse_js(keep_code_expanded=True, collapse_prose_only=True)
    assert "KEEP_CODE      = true;" in js_tt
    assert "PROSE_ONLY     = true;" in js_tt

    js_ff = PI.make_collapse_js(keep_code_expanded=False, collapse_prose_only=False)
    assert "KEEP_CODE      = false;" in js_ff
    assert "PROSE_ONLY     = false;" in js_ff

    js_tf = PI.make_collapse_js(keep_code_expanded=True, collapse_prose_only=False)
    assert "KEEP_CODE      = true;" in js_tf
    assert "PROSE_ONLY     = false;" in js_tf


def test_make_collapse_js_embeds_selectors_and_keep_recent():
    js = PI.make_collapse_js(True, False)
    assert PI._SELECTORS_JS in js
    assert "KEEP_RECENT    = 4;" in js


def test_make_collapse_js_defines_expand_and_collapse_helpers():
    js = PI.make_collapse_js(True, False)
    for marker in ("function collapseMessage", "function findMessages", "function describeCode"):
        assert marker in js


# ---------------------------------------------------------------------------
# Expand all
# ---------------------------------------------------------------------------

def test_expand_all_js_targets_collapsed_attr_and_hidden_class():
    assert "data-aiwb-collapsed" in PI.EXPAND_ALL_JS
    assert "aiwb-hidden-child" in PI.EXPAND_ALL_JS


# ---------------------------------------------------------------------------
# Copy plain text
# ---------------------------------------------------------------------------

def test_copy_plain_text_js_uses_clipboard_api_and_handles_empty_selection():
    assert "navigator.clipboard.writeText" in PI.COPY_PLAIN_TEXT_JS
    assert "sel.isCollapsed" in PI.COPY_PLAIN_TEXT_JS


def test_copy_plain_text_js_inserts_newlines_for_block_elements():
    for tag in ("p", "li", "pre", "blockquote"):
        assert f"'{tag}'" in PI.COPY_PLAIN_TEXT_JS


# ---------------------------------------------------------------------------
# User stylesheet injection
# ---------------------------------------------------------------------------

def test_make_user_stylesheet_js_escapes_arbitrary_css_safely():
    tricky_css = '''body::after { content: "quote's \\ backslash \n newline"; }'''
    js = PI.make_user_stylesheet_js(tricky_css)
    # The css must appear as a properly-escaped JSON string literal, not
    # spliced in raw (which would break out of the JS string).
    assert json.dumps(tricky_css) in js
    assert "aiwb-user-css" in js


def test_make_user_stylesheet_js_reuses_existing_style_element():
    js = PI.make_user_stylesheet_js(".x { color: red; }")
    assert "var el = document.getElementById(ID);" in js
    assert "if (!el) {" in js


def test_remove_user_stylesheet_js_targets_same_id():
    assert "aiwb-user-css" in PI.REMOVE_USER_STYLESHEET_JS


# ---------------------------------------------------------------------------
# Extract text
# ---------------------------------------------------------------------------

def test_extract_text_js_wraps_pre_blocks_in_code_fences():
    assert "```" in PI.EXTRACT_TEXT_JS


def test_extract_text_js_skips_script_style_noscript():
    assert "script" in PI.EXTRACT_TEXT_JS
    assert "noscript" in PI.EXTRACT_TEXT_JS


# ---------------------------------------------------------------------------
# Debug info
# ---------------------------------------------------------------------------

def test_make_debug_info_js_embeds_selectors_and_expected_keys():
    js = PI.make_debug_info_js()
    assert PI._SELECTORS_JS in js
    for key in ("url", "pre_count", "code_count", "collapsed", "selectors"):
        assert f"{key}:" in js
