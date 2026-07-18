"""
page_injection.py — all injected JavaScript and CSS strings.

Kept entirely separate from Python UI logic so that selectors and
heuristics can be tuned independently as target sites evolve.

Architecture
------------
MESSAGE_SELECTORS   Single source of truth for per-site CSS selectors.
                    Used by make_collapse_js() and make_debug_info_js().
                    There is no second copy inside JS strings.

COMPACT_CSS         Injected <style> block.  Never touches code blocks.

make_collapse_js()  Builds the collapse IIFE with settings baked in as
                    JS literals.  This is the correct way to pass Python
                    settings into JS — not via runtime argument tricks.

EXPAND_ALL_JS       Restores collapsed messages by un-hiding original
                    DOM nodes.  Does not reconstruct innerHTML.

COPY_PLAIN_TEXT_JS  Copies selection as plain text.  Returns the text
                    string so Python can use QApplication.clipboard()
                    as a fallback.

WRAP_CODE_ON_JS /   Two separate IIFEs — no parameterised function
WRAP_CODE_OFF_JS    that Python would need to call with arguments.

make_debug_info_js() Probes the live page using the same selector list
                    as the collapse script.

Safe collapse strategy (React-compatible)
-----------------------------------------
The collapse system NEVER writes to msg.innerHTML.
Instead:
  1. An .aiwb-overlay <div> is inserted as the first child of the
     message container.
  2. Other direct children are hidden via CSS class (.aiwb-hidden-child),
     keeping the real nodes in the DOM.
  3. React's reconciler can still reconcile those hidden nodes normally.
  4. Expand = remove overlay, remove the CSS class.  No HTML rebuilding.
"""

import json


# ---------------------------------------------------------------------------
# Single source of truth: per-site message container selectors
# ---------------------------------------------------------------------------
# Keys are substrings matched against window.location.host.
# Values are ordered lists tried most-specific-first.
#
# HOW TO UPDATE WHEN A SITE CHANGES
#   Open the debug panel → "Run debug info".
#   It shows how many elements each selector currently matches.
#   Update the relevant list here; make_collapse_js() and
#   make_debug_info_js() both pick up the change automatically.

MESSAGE_SELECTORS: dict[str, list[str]] = {
    "claude.ai": [
        '[data-testid="conversation-turn"]',
        ".font-claude-message",
        ".human-turn",
        ".ai-turn",
    ],
    "chatgpt.com": [
        "[data-message-id]",
        "article[data-scroll-anchor]",
        ".group.w-full",
    ],
    "gemini.google.com": [
        "message-content",
        "model-response",
        "user-query",
        ".conversation-container .turn",
    ],
}

# Flat de-duplicated list for embedding in JS (site-specific first, then generic)
_ALL_SELECTORS: list[str] = []
_seen: set[str] = set()
for _sels in MESSAGE_SELECTORS.values():
    for _s in _sels:
        if _s not in _seen:
            _ALL_SELECTORS.append(_s)
            _seen.add(_s)
for _s in [
    '[class*="message-container"]',
    '[class*="MessageContainer"]',
    '[class*="chat-message"]',
    '[class*="ChatMessage"]',
]:
    if _s not in _seen:
        _ALL_SELECTORS.append(_s)
        _seen.add(_s)

_SELECTORS_JS: str = json.dumps(_ALL_SELECTORS)   # safe JS array literal


# ---------------------------------------------------------------------------
# Compact mode CSS
# ---------------------------------------------------------------------------
# Rules:
#   MAY:  reduce padding, shrink avatars, hide decorative elements,
#         suppress animations.
#   MUST NOT: alter pre/code whitespace, font, indentation, or visibility.
#   MUST NOT: collapse markdown structural elements (h1-h6, blockquote, li).

COMPACT_CSS = """
/* ── AI Work Browser — Compact Mode ─────────────────────────────── */

[class*="avatar"], [class*="Avatar"] {
    width: 20px !important; height: 20px !important;
}

[data-testid="conversation-turn"],
[data-message-id],
.group.w-full,
message-content, model-response, user-query {
    padding-top:    6px !important;
    padding-bottom: 6px !important;
}

p  { margin-top: 4px !important; margin-bottom: 4px !important; }
ul { margin-top: 4px !important; margin-bottom: 4px !important; }
ol { margin-top: 4px !important; margin-bottom: 4px !important; }

[class*="sidebar"], [class*="Sidebar"],
[aria-label="Conversation sidebar"] { display: none !important; }

[class*="thinking-indicator"], [class*="ThinkingIndicator"],
[data-testid="typing-indicator"] { display: none !important; }

*, *::before, *::after {
    animation-duration:  0.01ms !important;
    transition-duration: 0.01ms !important;
}

/* ── Code block preservation — overrides everything above ─────── */
pre, pre *, code, code * {
    font-family:   "Consolas","JetBrains Mono","Fira Code",
                   "Source Code Pro","Courier New",monospace !important;
    white-space:   pre         !important;
    word-break:    normal      !important;
    overflow-wrap: normal      !important;
    tab-size:      4           !important;
    padding-top:   revert      !important;
    padding-bottom:revert      !important;
    margin-top:    revert      !important;
    margin-bottom: revert      !important;
}

/* ── Markdown hierarchy must stay readable ────────────────────── */
h1 { font-size:1.4em  !important; margin:8px 0 4px !important; }
h2 { font-size:1.25em !important; margin:6px 0 4px !important; }
h3 { font-size:1.1em  !important; margin:4px 0 3px !important; }

blockquote {
    border-left:  3px solid #555 !important;
    padding-left: 10px           !important;
    margin-left:  4px            !important;
    color:        inherit        !important;
}
"""

INJECT_COMPACT_CSS_JS: str = """
(function() {
    var ID = 'aiwb-compact-css';
    if (document.getElementById(ID)) return;
    var s   = document.createElement('style');
    s.id    = ID;
    s.textContent = %s;
    document.head.appendChild(s);
    console.log('[AIWB] Compact CSS injected.');
})();
""" % json.dumps(COMPACT_CSS)

REMOVE_COMPACT_CSS_JS: str = """
(function() {
    var el = document.getElementById('aiwb-compact-css');
    if (el) { el.remove(); console.log('[AIWB] Compact CSS removed.'); }
})();
"""


# ---------------------------------------------------------------------------
# Wrap long code lines — two self-contained IIFEs
# ---------------------------------------------------------------------------
# Having two named constants avoids the previous bug where Python was
# expected to interpolate a boolean into a JS function-call expression.

WRAP_CODE_ON_JS: str = """
(function() {
    document.querySelectorAll('pre, code').forEach(function(el) {
        el.style.whiteSpace = 'pre-wrap';
        el.style.wordBreak  = 'break-all';
    });
    console.log('[AIWB] Code wrap: ON');
})();
"""

WRAP_CODE_OFF_JS: str = """
(function() {
    document.querySelectorAll('pre, code').forEach(function(el) {
        el.style.whiteSpace = 'pre';
        el.style.wordBreak  = 'normal';
    });
    console.log('[AIWB] Code wrap: OFF');
})();
"""


# ---------------------------------------------------------------------------
# make_collapse_js
# ---------------------------------------------------------------------------

def make_collapse_js(keep_code_expanded: bool, collapse_prose_only: bool) -> str:
    """
    Return a complete, self-contained collapse IIFE with settings baked in.

    Parameters
    ----------
    keep_code_expanded
        When True, <pre> blocks inside a collapsed message remain visible.
        The overlay still shows a summary bar, but code is not hidden.

    collapse_prose_only
        When True, only non-<pre> direct children are hidden.
        Equivalent to keep_code_expanded but also suppresses code
        placeholders in the overlay (since code is always visible).

    Both flags may be True simultaneously.
    """
    keep_code_js   = "true"  if keep_code_expanded else "false"
    prose_only_js  = "true"  if collapse_prose_only else "false"

    return r"""
(function() {
    var KEEP_RECENT    = 4;
    var KEEP_CODE      = """ + keep_code_js + r""";
    var PROSE_ONLY     = """ + prose_only_js + r""";
    var ATTR           = 'data-aiwb-collapsed';
    var HIDDEN_CLS     = 'aiwb-hidden-child';
    var OVERLAY_CLS    = 'aiwb-overlay';
    var SELECTORS      = """ + _SELECTORS_JS + r""";

    // ── Inject helper CSS once ────────────────────────────────────────────
    if (!document.getElementById('aiwb-collapse-css')) {
        var s = document.createElement('style');
        s.id  = 'aiwb-collapse-css';
        s.textContent = '\n' + [
            '.' + HIDDEN_CLS + ' { display: none !important; }',
            '.aiwb-overlay {'
                + 'box-sizing:border-box; width:100%;'
                + 'border:1px solid #3a3a3a; border-radius:4px;'
                + 'background:#242424; font-family:system-ui,sans-serif;'
                + 'font-size:12px; overflow:hidden; margin:2px 0; }',
            '.aiwb-overlay-bar { display:flex; align-items:center;'
                + 'padding:4px 10px; gap:8px; color:#888; }',
            '.aiwb-expand-btn { margin-left:auto; background:#3c3c3c;'
                + 'border:1px solid #555; border-radius:3px;'
                + 'color:#ccc; cursor:pointer; font-size:11px; padding:2px 8px; }',
            '.aiwb-expand-btn:hover { background:#4a4a4a; }',
            '.aiwb-code-ph { border-top:1px solid #2e3a2e; padding:4px 12px;'
                + 'font-family:monospace; font-size:11px; color:#7c9cbf;'
                + 'display:flex; align-items:center; gap:8px; background:#1a1a2e; }',
            '.aiwb-show-btn { background:#264f78; border:1px solid #3a7abf;'
                + 'border-radius:3px; color:#c8d8e8; cursor:pointer;'
                + 'font-size:11px; padding:2px 7px; }',
        ].join('\n');
        document.head.appendChild(s);
    }

    // ── 1. Find message containers ────────────────────────────────────────
    function findMessages() {
        for (var i = 0; i < SELECTORS.length; i++) {
            try {
                var nodes = document.querySelectorAll(SELECTORS[i]);
                if (nodes.length > 1) return Array.from(nodes);
            } catch(e) {}
        }
        // Generic heuristic: sibling divs with substantial text
        var candidates = Array.from(document.querySelectorAll('div')).filter(function(el) {
            return el.children.length > 0
                && el.textContent.trim().length > 120
                && el.parentElement
                && el.parentElement.children.length > 2;
        });
        return candidates.filter(function(el) {
            return !candidates.some(function(o) { return o !== el && o.contains(el); });
        });
    }

    // ── 2. Describe a <pre> block ─────────────────────────────────────────
    function describeCode(pre) {
        var code  = pre.querySelector('code') || pre;
        var text  = code.textContent || '';
        var lines = text.split('\n').length;
        var lang  = '';
        var cls   = (code.className || '') + ' ' + (pre.className || '');
        var m     = cls.match(/(?:language-|lang-)([\w+-]+)/i);
        if (m) lang = m[1];
        if (!lang) {
            if      (/def |import |class /.test(text))            lang = 'Python';
            else if (/function |const |let |var /.test(text))     lang = 'JavaScript';
            else if (/[\s\S]*"[^"]+":\s/.test(text))              lang = 'JSON';
            else if (/SELECT|INSERT|FROM|WHERE/i.test(text))      lang = 'SQL';
            else if (/<\/[a-z]+>/.test(text))                     lang = 'HTML';
            else if (/Traceback|Error:/m.test(text))              lang = 'Traceback';
            else if (/^\$\s|^>\s/.test(text))                     lang = 'Shell';
            else                                                   lang = 'Code';
        }
        return { el: pre, lines: lines, lang: lang };
    }

    // ── 3. Collapse one message ───────────────────────────────────────────
    function collapseMessage(msg) {
        if (msg.getAttribute(ATTR) === 'true') return;

        var children  = Array.from(msg.children);
        var pres      = Array.from(msg.querySelectorAll('pre'));
        var codeDescs = pres.map(describeCode);

        // Prose preview (from non-pre text)
        var preview = '';
        for (var i = 0; i < children.length; i++) {
            var ch = children[i];
            if (ch.tagName && ch.tagName.toLowerCase() !== 'pre') {
                preview += (preview ? ' ' : '') + ch.textContent.replace(/\s+/g, ' ').trim();
                if (preview.length > 100) { preview = preview.slice(0, 100) + '\u2026'; break; }
            }
        }
        if (!preview) {
            var all = msg.textContent.replace(/\s+/g, ' ').trim();
            preview = all.length > 100 ? all.slice(0, 100) + '\u2026' : all;
        }

        // Build overlay
        var overlay = document.createElement('div');
        overlay.className = OVERLAY_CLS;

        var bar       = document.createElement('div');
        bar.className = 'aiwb-overlay-bar';

        var lbl = document.createElement('span');
        lbl.textContent  = '\u25b6 collapsed';
        lbl.style.cssText = 'color:#555; font-size:11px; white-space:nowrap;';

        var pvw = document.createElement('span');
        pvw.textContent  = preview;
        pvw.style.cssText = 'flex:1; overflow:hidden; text-overflow:ellipsis;'
                          + 'white-space:nowrap; color:#777;';

        var expBtn       = document.createElement('button');
        expBtn.className = 'aiwb-expand-btn';
        expBtn.textContent = 'Expand';

        bar.appendChild(lbl);
        bar.appendChild(pvw);
        bar.appendChild(expBtn);
        overlay.appendChild(bar);

        // Code placeholders — only shown when code is actually going to be hidden
        if (!KEEP_CODE && !PROSE_ONLY) {
            codeDescs.forEach(function(cb) {
                var ph     = document.createElement('div');
                ph.className = 'aiwb-code-ph';

                var phLbl  = document.createElement('span');
                phLbl.textContent = '\uD83D\uDCC4 [' + cb.lang + ' \u2014 ' + cb.lines + ' lines]';

                var showBtn       = document.createElement('button');
                showBtn.className = 'aiwb-show-btn';
                showBtn.textContent = 'Show';
                (function(preEl, btn) {
                    btn.addEventListener('click', function(e) {
                        e.stopPropagation();
                        var hidden = preEl.style.display === 'none';
                        preEl.style.display = hidden ? '' : 'none';
                        btn.textContent     = hidden ? 'Hide' : 'Show';
                    });
                })(cb.el, showBtn);

                ph.appendChild(phLbl);
                ph.appendChild(showBtn);
                overlay.appendChild(ph);
            });
        }

        // Expand handler — remove overlay, unhide children
        expBtn.addEventListener('click', function() {
            if (overlay.parentNode === msg) msg.removeChild(overlay);
            Array.from(msg.children).forEach(function(c) {
                c.classList.remove(HIDDEN_CLS);
                c.style.display = '';
            });
            msg.removeAttribute(ATTR);
        });

        msg.insertBefore(overlay, msg.firstChild);
        msg.setAttribute(ATTR, 'true');

        // Hide children according to settings
        children.forEach(function(ch) {
            var isCode = ch.tagName && ch.tagName.toLowerCase() === 'pre';
            var hide   = (PROSE_ONLY || KEEP_CODE) ? !isCode : true;
            if (hide) ch.classList.add(HIDDEN_CLS);
        });
    }

    // ── 4. Main ───────────────────────────────────────────────────────────
    var msgs = findMessages();
    if (msgs.length <= KEEP_RECENT) {
        console.log('[AIWB] Not enough messages to collapse (' + msgs.length + ')');
        return;
    }
    var toCollapse = msgs.slice(0, msgs.length - KEEP_RECENT);
    toCollapse.forEach(function(m) { collapseMessage(m); });
    console.log('[AIWB] Collapsed ' + toCollapse.length + ' of ' + msgs.length + ' messages.');
})();
"""


# ---------------------------------------------------------------------------
# Expand all
# ---------------------------------------------------------------------------

EXPAND_ALL_JS: str = """
(function() {
    var ATTR    = 'data-aiwb-collapsed';
    var HIDDEN  = 'aiwb-hidden-child';
    var count   = 0;

    document.querySelectorAll('[' + ATTR + '="true"]').forEach(function(msg) {
        var overlay = msg.querySelector('.aiwb-overlay');
        if (overlay) msg.removeChild(overlay);

        Array.from(msg.children).forEach(function(ch) {
            ch.classList.remove(HIDDEN);
            ch.style.display = '';
        });

        msg.removeAttribute(ATTR);
        count++;
    });

    // Also restore any individually peek-toggled pre elements
    document.querySelectorAll('pre').forEach(function(pre) {
        if (pre.style.display === 'none') pre.style.display = '';
    });

    console.log('[AIWB] Expanded ' + count + ' messages.');
})();
"""


# ---------------------------------------------------------------------------
# Copy selection as plain text
# ---------------------------------------------------------------------------
# Returns the text string so Python can use QApplication.clipboard()
# as a fallback when navigator.clipboard is blocked.

COPY_PLAIN_TEXT_JS: str = r"""
(function() {
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed) {
        console.log('[AIWB] copy: no selection');
        return null;
    }

    var container = document.createElement('div');
    container.appendChild(sel.getRangeAt(0).cloneContents());

    // <br> → newline before textContent strips the tags
    container.querySelectorAll('br').forEach(function(br) {
        br.replaceWith('\n');
    });

    // Block elements get a trailing newline
    ['p','div','li','tr','pre','blockquote',
     'h1','h2','h3','h4','h5','h6'].forEach(function(tag) {
        container.querySelectorAll(tag).forEach(function(el) {
            el.insertAdjacentText('afterend', '\n');
        });
    });

    var text = (container.textContent || container.innerText || '')
                   .replace(/\n{3,}/g, '\n\n')
                   .trim();

    navigator.clipboard.writeText(text).then(function() {
        console.log('[AIWB] Clipboard write OK (' + text.length + ' chars)');
    }).catch(function(err) {
        console.warn('[AIWB] Clipboard API unavailable: ' + err);
    });

    // Return text so Python can use Qt clipboard as fallback
    return text;
})();
"""


# ---------------------------------------------------------------------------
# User stylesheet injection
# ---------------------------------------------------------------------------

def make_user_stylesheet_js(css_text: str) -> str:
    """Return a JS IIFE that injects css_text as an overriding <style>."""
    safe = json.dumps(css_text)   # handles all escaping correctly
    return """
(function() {
    var ID = 'aiwb-user-css';
    var el = document.getElementById(ID);
    if (!el) {
        el = document.createElement('style');
        el.id = ID;
        document.head.appendChild(el);
    }
    el.textContent = %s;
    console.log('[AIWB] User stylesheet applied.');
})();
""" % safe


REMOVE_USER_STYLESHEET_JS: str = """
(function() {
    var el = document.getElementById('aiwb-user-css');
    if (el) { el.remove(); console.log('[AIWB] User stylesheet removed.'); }
})();
"""


# ---------------------------------------------------------------------------
# Extract page as text
# ---------------------------------------------------------------------------

EXTRACT_TEXT_JS: str = r"""
(function() {
    function extractNode(node, out) {
        if (node.nodeType === Node.TEXT_NODE) { out.push(node.textContent); return; }
        if (node.nodeType !== Node.ELEMENT_NODE) return;
        var tag = node.tagName.toLowerCase();
        if (tag === 'script' || tag === 'style' || tag === 'noscript') return;
        if (tag === 'pre') {
            out.push('\n```\n');
            out.push(node.textContent);
            out.push('\n```\n');
            return;
        }
        if (tag === 'h1' || tag === 'h2' || tag === 'h3' || tag === 'h4') out.push('\n\n');
        for (var i = 0; i < node.childNodes.length; i++) extractNode(node.childNodes[i], out);
        var blocks = ['p','div','li','br','tr','blockquote','h1','h2','h3','h4','h5','h6'];
        if (blocks.indexOf(tag) >= 0) out.push('\n');
    }
    var parts = [];
    extractNode(document.body, parts);
    return parts.join('').replace(/\n{3,}/g, '\n\n').trim();
})();
"""


# ---------------------------------------------------------------------------
# Debug info
# ---------------------------------------------------------------------------

def make_debug_info_js() -> str:
    """
    Return a JS IIFE that probes the page using the same selector list
    as make_collapse_js().  Output is a JSON string received via callback.
    """
    return """
(function() {
    var SELECTORS = %s;
    var results   = {};
    SELECTORS.forEach(function(s) {
        try { results[s] = document.querySelectorAll(s).length; }
        catch(e) { results[s] = 'error'; }
    });
    return JSON.stringify({
        url:        window.location.href,
        pre_count:  document.querySelectorAll('pre').length,
        code_count: document.querySelectorAll('code').length,
        collapsed:  document.querySelectorAll('[data-aiwb-collapsed="true"]').length,
        selectors:  results
    }, null, 2);
})();
""" % _SELECTORS_JS
