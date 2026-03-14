# AI Work Browser

A minimal desktop browser for long, code-heavy AI chat conversations.
Built with Python 3.11 + PySide6 + QtWebEngine.

---

## What it is

A focused productivity wrapper — a thin browser shell around Claude,
ChatGPT, Gemini, and similar sites.  
It is **not** a general-purpose browser, not a memory system, not a
summarisation platform.

Its only goal: make long AI coding conversations less painful to work in.

---

## What it does

| Feature | Detail |
|---|---|
| Embedded browser | Full QtWebEngine — JS, cookies, localStorage, all modern CSS work |
| Persistent sessions | Login state stored in `~/.ai-work-browser/profile/` — for sites that allow sign-in in an embedded browser |
| Quick-launch buttons | One-click to open Claude, ChatGPT, or Gemini |
| Collapse older messages | Keeps last 4 messages expanded; hides the rest behind a summary bar |
| Code block behaviour (collapse) | Configurable: keep code visible, show placeholder, or hide |
| Expand all | Restores every collapsed message instantly |
| Compact mode | Reduces padding/animations without touching code blocks or markdown |
| Wrap long code lines | Toggle: `pre-wrap` / `pre` on all `<pre>` and `<code>` elements |
| Copy as plain text | `Ctrl+Shift+C` — strips HTML, preserves indentation; Qt fallback if clipboard API is blocked |
| Save page as text | Extracts readable text with code fenced in triple-backticks |
| Save page as HTML | Full DOM snapshot |
| Open current page in system browser | Hands current URL to default browser |
| Sign in via system browser… | Opens the site root in your default browser with a clear explanation of what it does and does not do |
| User stylesheet | Point at any `.css` file; re-injected on every page load |
| Debug panel | Shows JS `console.log` output from all injected scripts |
| Settings | `~/.ai-work-browser/settings.json` — human-readable JSON |

---

## Requirements

- Python 3.11+
- PySide6 ≥ 6.6.0 (bundles QtWebEngine / Chromium — no separate install)
- Linux, macOS, or Windows

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

On first launch the browser opens `https://claude.ai`.  
Change this in **⋯ → Settings → Home URL**.

---

## Signing in with Google

**This is a known platform limitation, not a solvable bug.**

Google actively blocks OAuth sign-in flows inside embedded Chromium browsers,
including QtWebEngine. This is Google's deliberate policy — they detect
non-standard Chromium embedders and refuse to show the sign-in screen, or
show a warning and block the flow.

The app includes two best-effort mitigations:

- **`ClientHintInterceptor`** strips the `sec-ch-ua` request headers that
  Google uses to identify the embedder. This sometimes bypasses the block.
- **Popup window handling** (`createWindow`) opens the OAuth popup in a
  separate window using the same embedded profile, so cookies set during
  sign-in are visible to subsequent requests in the embedded browser.

**These mitigations are best-effort. They may work, or they may not.**
Google has tightened this check repeatedly and may tighten it again.

### What to do when Google sign-in is blocked

**Step 1 — Try the embedded flow first.**  
Go to the site (ChatGPT, Gemini, etc.) and attempt Google sign-in.
It sometimes works.

**Step 2 — If blocked, use ⋯ → Sign in via system browser…**  
This opens the site's login page in your default browser (Chrome, Firefox,
etc.) where Google sign-in works normally. The dialog explains what it does.

> **Important:** completing sign-in in your system browser does **not**
> automatically log you in here. The embedded browser and your system browser
> have completely separate cookie stores. There is no session transfer.

**Step 3 — Return to this app and try signing in again.**  
After signing in via the system browser, come back to this app and try again.
Some sites issue their own session cookie after a first Google OAuth and will
offer alternative sign-in options (email/password, magic link) on subsequent
visits. These often work in embedded browsers even when the Google button does
not.

**Step 4 — If sign-in remains blocked, accept the constraint.**  
For sites that consistently refuse embedded Google sign-in, the practical
options are:

- Use your system browser for the working session. This app is most useful
  once you are signed in — for reading, copying, and managing long
  conversations.
- Check whether the site offers a non-Google sign-in option. Many do.

### Why not just copy the system browser profile?

Copying Chrome or Firefox cookie data into the embedded profile is possible
in principle but is not implemented. It requires locating the correct profile
directory, copying the right database files, and handling OS-level cookie
encryption (Chrome encrypts cookies on macOS and Windows). This is fragile,
version-dependent, and outside the scope of this tool.

---

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `F5` / `Ctrl+R` | Reload |
| `Alt+Left` | Back |
| `Alt+Right` | Forward |
| `Ctrl+L` | Focus address bar |
| `Ctrl+Shift+C` | Copy selection as plain text |
| `Ctrl+Shift+K` | Collapse older messages |
| `Ctrl+Shift+E` | Expand all messages |
| `Ctrl+Shift+M` | Toggle compact mode |
| `Ctrl+Shift+D` | Toggle debug panel |

---

## How collapse works

### The safe collapse strategy

The collapse system **never writes to `innerHTML`** of live message nodes.
Instead, it:

1. Inserts a `.aiwb-overlay` `<div>` as the first child of the message container.
2. Adds a CSS class (`.aiwb-hidden-child`) to the other direct children — they
   stay in the DOM, they are just `display: none`.
3. React's virtual DOM reconciler can still reconcile those hidden nodes.
   No fiber state is destroyed.
4. Expanding removes the overlay element and the CSS class.
   No HTML reconstruction happens.

This is why the old approach (storing `innerHTML` in a data attribute and
restoring it on expand) was fragile: React-rendered sites would either crash
or re-render over the top of the restored HTML.

### Collapse settings

| Setting | Effect |
|---|---|
| Keep code blocks visible | `<pre>` children of a collapsed message are **not** given the hide class. Code stays on screen; only prose is hidden. |
| Collapse prose only | Same as above, but also suppresses the code placeholder badges in the overlay. |
| Both off (default) | All children are hidden. The overlay shows placeholder badges for each code block with a **Show** button that toggles the real `<pre>` element. |

These settings are read at collapse time, so changing them in Settings and
pressing **Collapse↑** again takes immediate effect.

---

## How selectors work

The collapse script needs to know which elements on the page are message
containers. There is a single source of truth: `MESSAGE_SELECTORS` in
`page_injection.py`. The `make_collapse_js()` and `make_debug_info_js()`
functions both read from this dict — there is no duplication to keep in sync.

```python
MESSAGE_SELECTORS: dict[str, list[str]] = {
    "claude.ai": [
        '[data-testid="conversation-turn"]',
        ".font-claude-message",
        ...
    ],
    "chatgpt.com": [
        "[data-message-id]",
        "article[data-scroll-anchor]",
        ...
    ],
    ...
}
```

The JS tries each selector in order and uses the first one that returns more
than one element. If none match, it falls back to a DOM heuristic.

**These selectors will need maintenance.** AI chat sites update their HTML
structure regularly. When collapse stops working:

1. Open **⋯ → Toggle debug panel**.
2. Click **⋯ → Run debug info**.
3. The debug panel shows a JSON object with a `selectors` key — how many
   elements each selector currently matches.
4. Find the correct new selector using browser dev tools on the target site.
5. Update `MESSAGE_SELECTORS` in `page_injection.py` for the relevant site.

No other files need to change.

---

## File layout

```
ai-work-browser/
├── main.py            Entry point, QApplication, base stylesheet
├── browser_window.py  Main window, toolbar, all Qt wiring
│                      Settings → runtime mapping lives here
├── page_injection.py  All JS and CSS strings
│                      MESSAGE_SELECTORS — single source of truth
│                      make_collapse_js() — settings baked in at call time
│                      WRAP_CODE_ON/OFF_JS — two separate IIFEs (no args)
├── settings.py        JSON persistence, DEFAULTS, KNOWN_SITES
├── requirements.txt
└── README.md
```

### Settings → runtime wiring

| Setting key | Where it takes effect |
|---|---|
| `compact_mode` | Toggled live; re-applied on every page load via `_apply_persistent_injections()` |
| `wrap_long_lines` | Applied on every load and after settings dialog save — independent of compact mode |
| `keep_code_expanded` | Read by `make_collapse_js()` at collapse time |
| `collapse_prose_only` | Read by `make_collapse_js()` at collapse time |
| `user_stylesheet` | Re-applied on every load and on settings save |

### PyCentricStudio porting

1. Replace `QMainWindow` in `browser_window.py` with your panel base class.
2. `WebView` and `DebugPanel` are self-contained widgets — drop into any layout.
3. Pass in an external `Settings` instance or let `BrowserWindow` construct one.

---

## Settings file

Located at: `~/.ai-work-browser/settings.json`

```json
{
  "home_url":            "https://claude.ai",
  "last_url":            "https://claude.ai",
  "window_x":            100,
  "window_y":            100,
  "window_width":        1280,
  "window_height":       860,
  "compact_mode":        false,
  "wrap_long_lines":     false,
  "keep_code_expanded":  true,
  "collapse_prose_only": false,
  "user_stylesheet":     "",
  "allowed_domains":     [],
  "debug_panel_open":    false
}
```

`allowed_domains`: if non-empty, navigating to a domain not on the list
shows a warning in the status bar. Does not block navigation.

---

## Known limitations

1. **Performance ceiling** — This is still a full Chromium engine. A
   500-message conversation is a large DOM. Collapse reduces scroll cost
   noticeably but cannot eliminate it.

2. **Selector drift** — AI sites update their HTML regularly. The CSS
   selectors in `MESSAGE_SELECTORS` require occasional maintenance.
   See *How selectors work* above.

3. **Shadow DOM** — Some AI sites render code blocks inside shadow DOM or
   custom elements. `querySelectorAll` cannot reach inside these from an
   injected script. Collapse placeholders may not show code line counts
   for these blocks; the code itself will still be visible if
   `keep_code_expanded` is on.

4. **Clipboard API permissions** — `navigator.clipboard.writeText()` may
   be blocked by the page's `Permissions-Policy`. The copy action has a
   Qt-side fallback: the JS returns the text string and Python writes it
   via `QApplication.clipboard()`, which bypasses the page permission.

5. **Google sign-in** — Google actively blocks OAuth flows in embedded
   Chromium browsers as deliberate policy. The app includes best-effort
   mitigations but these are not reliable and may stop working at any time.
   See *Signing in with Google* above for the realistic workflow.

6. **No cross-browser session sharing** — The embedded profile's cookie
   store is completely separate from your system browser. Signing into a
   site in Chrome does not sign you into this app, and vice versa.

7. **macOS Gatekeeper** — Unsigned Python apps may require:
   `xattr -rd com.apple.quarantine .venv`

8. **Blank window on Linux Mesa** — If the window is white/black, add to
   the top of `main.py`:
   ```python
   import os
   os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
   ```

---

## Honest disclaimer

This tool is a pragmatic wrapper, not a magical fix.

It cannot eliminate the performance cost of extremely large web app DOMs.
It depends on the target site's HTML structure in ways that require occasional
maintenance.
It cannot reliably bypass Google's embedded browser sign-in restrictions.
It is a usability improvement for conversations you are already signed into,
not a replacement for a native client or a full browser session.

---

## Suggested v2 improvements

- Per-site selector overrides in a user-editable YAML/TOML file, so
  selector updates don't require editing Python.
- Injected "Copy" button on each `<pre>` block.
- Scroll-to-latest-message button.
- Session-aware conversation export: auto-save page text to a dated `.md`
  on close.
- Multiple tabs via `QTabWidget` sharing one profile.
- PyCentricStudio registered panel integration.
