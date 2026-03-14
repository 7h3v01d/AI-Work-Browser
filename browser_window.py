"""
browser_window.py — main application window.

Contains:
  BrowserWindow     QMainWindow — the whole app.
  WebView           QWebEngineView with persistent profile + OAuth support.
  DebugPanel        Collapsible JS console log panel.
  SettingsDialog    Settings editor.

All JS/CSS strings live in page_injection.py.
All persistence lives in settings.py.
This file is pure Qt wiring.

Settings → runtime wiring
--------------------------
compact_mode       Injected CSS on every load, toggled live.
wrap_long_lines    Applied independently of compact mode on every load
                   and when settings change.
keep_code_expanded Passed into make_collapse_js() at collapse time.
collapse_prose_only Passed into make_collapse_js() at collapse time.
user_stylesheet    Re-applied on every load and on settings save.

PyCentricStudio porting notes
------------------------------
Replace QMainWindow with your panel base class.
WebView and DebugPanel are self-contained widgets.
Pass an external Settings instance or let BrowserWindow construct one.
"""

from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QUrl, QSize, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QKeySequence, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QToolBar,
    QLineEdit, QPushButton, QLabel, QStatusBar, QSplitter,
    QTextEdit, QFileDialog, QMessageBox, QDialog, QFormLayout,
    QCheckBox, QComboBox, QDialogButtonBox, QApplication, QToolButton,
    QMenu, QSizePolicy,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import (
    QWebEngineProfile, QWebEnginePage, QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)

from settings import Settings, KNOWN_SITES
import page_injection as PI


# ---------------------------------------------------------------------------
# Request interceptor — strip sec-ch-ua client-hint headers
# ---------------------------------------------------------------------------
# Google's sign-in page uses these headers to detect non-standard Chromium
# embedders.  Stripping them is a best-effort mitigation that has worked in
# some configurations, but Google may still block embedded sign-in regardless.
# See README § "Signing in with Google" for the reliable workflow.

class ClientHintInterceptor(QWebEngineUrlRequestInterceptor):
    _STRIP = [
        b"sec-ch-ua",
        b"sec-ch-ua-mobile",
        b"sec-ch-ua-platform",
        b"sec-ch-ua-platform-version",
        b"sec-ch-ua-full-version-list",
        b"sec-ch-ua-arch",
        b"sec-ch-ua-model",
        b"sec-ch-ua-wow64",
    ]

    def interceptRequest(self, info) -> None:
        for header in self._STRIP:
            info.setHttpHeader(header, b"")


# ---------------------------------------------------------------------------
# Custom page — routes JS console output to DebugPanel
# ---------------------------------------------------------------------------

class DebugCapturePage(QWebEnginePage):
    """
    Subclass of QWebEnginePage that:
      - forwards console.log / warn / error to the DebugPanel via a signal
      - handles OAuth popup windows (createWindow) so Google SSO works
    """

    console_message = Signal(str)

    def javaScriptConsoleMessage(self, level, message, line, source) -> None:
        names = {
            QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel:    "INFO",
            QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel: "WARN",
            QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:   "ERROR",
        }
        text = f"[JS {names.get(level, 'LOG')}] {message}"
        if source:
            text += f"  ({source}:{line})"
        self.console_message.emit(text)

    def createWindow(self, win_type) -> QWebEnginePage:
        """
        Handle window.open() calls — required for Google OAuth popup flows.

        The popup uses the same QWebEngineProfile as the main view, so any
        cookies the popup page sets are visible to subsequent requests made
        through this profile.  Whether Google actually completes the sign-in
        flow in an embedded context is not guaranteed — see README §
        "Signing in with Google".
        """
        popup = _OAuthPopup(self.profile())
        popup.show()
        # Keep a Python reference; Qt parent ownership alone isn't enough
        # because popup has no parent widget.
        if not hasattr(self, "_popups"):
            self._popups = []
        self._popups.append(popup)
        popup.destroyed.connect(
            lambda: self._popups.remove(popup) if popup in self._popups else None
        )
        return popup.page()


# ---------------------------------------------------------------------------
# OAuth popup helper
# ---------------------------------------------------------------------------

class _OAuthPopup(QWebEngineView):
    """
    Minimal window for OAuth popups.  Auto-closes when Google redirects
    back to the requesting site (i.e. login complete).
    """

    def __init__(self, profile: QWebEngineProfile, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sign in")
        self.resize(520, 640)
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.WindowCloseButtonHint
        )
        page = QWebEnginePage(profile, self)
        self.setPage(page)
        self.urlChanged.connect(self._check_done)

    @Slot(QUrl)
    def _check_done(self, url: QUrl) -> None:
        host = url.host().lower()
        if host and "google.com" not in host and "accounts." not in host:
            QTimer.singleShot(800, self.close)


# ---------------------------------------------------------------------------
# WebView
# ---------------------------------------------------------------------------

class WebView(QWebEngineView):
    """
    Embedded browser with:
      - persistent profile (cookies, localStorage, cache)
      - sec-ch-ua header stripping (best-effort Google SSO mitigation)
      - JS console routed to DebugPanel
    """

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings

        self._profile = QWebEngineProfile("ai_work_browser", self)
        self._profile.setPersistentStoragePath(str(Settings.CONFIG_DIR / "profile"))
        self._profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
        )
        self._profile.setCachePath(str(Settings.CONFIG_DIR / "cache"))
        self._profile.setHttpUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

        # Must be set before any page is created
        self._interceptor = ClientHintInterceptor()
        self._profile.setUrlRequestInterceptor(self._interceptor)

        self._page = DebugCapturePage(self._profile, self)
        self.setPage(self._page)

        ws = self._page.settings()
        ws.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled,          True)
        ws.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled,        True)
        ws.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,   True)
        ws.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled,      True)
        ws.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled,               True)
        ws.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)

    @property
    def debug_page(self) -> DebugCapturePage:
        return self._page

    def run_js(self, script: str, callback=None) -> None:
        if callback:
            self._page.runJavaScript(script, callback)
        else:
            self._page.runJavaScript(script)


# ---------------------------------------------------------------------------
# Debug panel
# ---------------------------------------------------------------------------

class DebugPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(26)
        header.setStyleSheet("background:#1a1a1a; border-top:1px solid #3a3a3a;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(8, 0, 8, 0)
        title = QLabel("Debug / Injection Log")
        title.setStyleSheet("color:#888; font-size:11px;")
        hl.addWidget(title)
        hl.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedSize(44, 18)
        clear_btn.setStyleSheet(
            "font-size:10px; padding:1px 4px; background:#2a2a2a; border:1px solid #444;"
        )
        hl.addWidget(clear_btn)
        layout.addWidget(header)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(130)
        self._log.setFont(QFont("Consolas", 10))
        layout.addWidget(self._log)

        clear_btn.clicked.connect(self._log.clear)

    def append(self, text: str) -> None:
        self._log.append(text)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self._settings = settings

        layout = QVBoxLayout(self)
        form   = QFormLayout()

        # Home URL
        self._home_combo = QComboBox()
        self._home_combo.setEditable(True)
        for name, url in KNOWN_SITES.items():
            self._home_combo.addItem(f"{name}  ({url})", url)
        current = settings.get("home_url")
        idx = self._home_combo.findData(current)
        if idx >= 0:
            self._home_combo.setCurrentIndex(idx)
        else:
            self._home_combo.setCurrentText(current)
        form.addRow("Home URL:", self._home_combo)

        # User stylesheet
        ss_row = QHBoxLayout()
        self._ss_path = QLineEdit(settings.get("user_stylesheet", ""))
        self._ss_path.setPlaceholderText("Optional path to a .css file")
        ss_browse = QPushButton("Browse…")
        ss_browse.clicked.connect(self._browse_css)
        ss_row.addWidget(self._ss_path)
        ss_row.addWidget(ss_browse)
        form.addRow("User stylesheet:", ss_row)

        # Collapse / code settings
        self._keep_code_cb = QCheckBox("Keep code blocks visible when collapsing")
        self._keep_code_cb.setChecked(settings.get("keep_code_expanded", True))
        form.addRow("", self._keep_code_cb)

        self._prose_only_cb = QCheckBox("Collapse prose only (code always visible)")
        self._prose_only_cb.setChecked(settings.get("collapse_prose_only", False))
        form.addRow("", self._prose_only_cb)

        self._wrap_cb = QCheckBox("Wrap long code lines")
        self._wrap_cb.setChecked(settings.get("wrap_long_lines", False))
        form.addRow("", self._wrap_cb)

        layout.addLayout(form)

        note = QLabel(f"Settings file: {Settings.CONFIG_FILE}")
        note.setStyleSheet("color:#666; font-size:10px;")
        layout.addWidget(note)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save_and_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _browse_css(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select CSS file", str(Path.home()), "CSS files (*.css);;All files (*)"
        )
        if path:
            self._ss_path.setText(path)

    def _save_and_accept(self) -> None:
        url = self._home_combo.currentData() or self._home_combo.currentText()
        self._settings.set("home_url",            url.strip())
        self._settings.set("user_stylesheet",     self._ss_path.text().strip())
        self._settings.set("keep_code_expanded",  self._keep_code_cb.isChecked())
        self._settings.set("collapse_prose_only", self._prose_only_cb.isChecked())
        self._settings.set("wrap_long_lines",     self._wrap_cb.isChecked())
        self.accept()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class BrowserWindow(QMainWindow):
    """
    Single-window AI Work Browser.

    Settings → runtime mapping
    --------------------------
    compact_mode       toggled via toolbar button; re-applied on every load
    wrap_long_lines    applied on every load and after settings dialog save
    keep_code_expanded read at collapse time via make_collapse_js()
    collapse_prose_only read at collapse time via make_collapse_js()
    user_stylesheet    re-applied on every load and after settings dialog save
    """

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._settings    = settings
        self._compact_mode = settings.get("compact_mode", False)

        self.setWindowTitle("AI Work Browser")
        self._restore_geometry()

        # Central layout
        central = QWidget()
        self.setCentralWidget(central)
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        self._splitter = QSplitter(Qt.Orientation.Vertical)
        vbox.addWidget(self._splitter)

        self._browser = WebView(settings)
        self._splitter.addWidget(self._browser)

        self._debug_panel = DebugPanel()
        self._splitter.addWidget(self._debug_panel)

        self._browser.debug_page.console_message.connect(self._debug_panel.append)

        debug_open = settings.get("debug_panel_open", False)
        self._debug_panel.setVisible(debug_open)
        self._splitter.setSizes([700, 150] if debug_open else [1, 0])

        self._build_toolbar()

        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Ready")

        self._browser.urlChanged.connect(self._on_url_changed)
        self._browser.loadStarted.connect(lambda: self._status.showMessage("Loading…"))
        self._browser.loadFinished.connect(self._on_load_finished)
        self._browser.titleChanged.connect(
            lambda t: self.setWindowTitle(
                f"{t} — AI Work Browser" if t else "AI Work Browser"
            )
        )

        self._setup_shortcuts()

        start_url = settings.get("last_url") or settings.get("home_url")
        self._navigate(start_url)

        if self._compact_mode:
            QTimer.singleShot(2000, self._apply_persistent_injections)

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> None:
        tb = QToolBar("Navigation")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(tb)

        def tbtn(label: str, tip: str, slot) -> QToolButton:
            b = QToolButton()
            b.setText(label)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            return b

        tb.addWidget(tbtn("◀", "Back (Alt+Left)",     self._browser.back))
        tb.addWidget(tbtn("▶", "Forward (Alt+Right)",  self._browser.forward))
        tb.addWidget(tbtn("↺", "Reload (F5)",          self._browser.reload))
        tb.addWidget(tbtn("⌂", "Go home",              self._go_home))
        tb.addSeparator()

        for name, url in KNOWN_SITES.items():
            b = tbtn(name, f"Open {url}", lambda checked=False, u=url: self._navigate(u))
            b.setFixedWidth(70)
            tb.addWidget(b)
        tb.addSeparator()

        self._url_bar = QLineEdit()
        self._url_bar.setPlaceholderText("Enter URL or paste link…")
        self._url_bar.returnPressed.connect(self._on_url_bar_enter)
        self._url_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        tb.addWidget(self._url_bar)
        tb.addSeparator()

        self._compact_btn = QToolButton()
        self._compact_btn.setText("Compact")
        self._compact_btn.setToolTip(
            "Toggle compact mode — reduces padding, preserves code and markdown"
        )
        self._compact_btn.setCheckable(True)
        self._compact_btn.setChecked(self._compact_mode)
        self._compact_btn.clicked.connect(self._toggle_compact_mode)
        tb.addWidget(self._compact_btn)

        tb.addWidget(tbtn("Collapse↑",  "Collapse older messages (Ctrl+Shift+K)",
                          self._collapse_older))
        tb.addWidget(tbtn("Expand all", "Expand all collapsed messages (Ctrl+Shift+E)",
                          self._expand_all))
        tb.addSeparator()

        util_btn = QToolButton()
        util_btn.setText("⋯")
        util_btn.setToolTip("More actions")
        util_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(util_btn)
        menu.addAction("Copy selection as plain text",
                       self._copy_plain_text, QKeySequence("Ctrl+Shift+C"))
        menu.addAction("Save page as text…",    self._save_page_text)
        menu.addAction("Save page as HTML…",    self._save_page_html)
        menu.addSeparator()
        menu.addAction("Open current page in system browser", self._open_external)
        menu.addAction("Sign in via system browser…",         self._open_login_in_browser)
        menu.addSeparator()
        menu.addAction("Settings…",             self._open_settings)
        menu.addAction("Toggle debug panel",    self._toggle_debug_panel)
        menu.addAction("Run debug info",        self._run_debug_info)
        util_btn.setMenu(menu)
        tb.addWidget(util_btn)

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------

    def _setup_shortcuts(self) -> None:
        for seq, slot in [
            ("F5",           self._browser.reload),
            ("Ctrl+R",       self._browser.reload),
            ("Alt+Left",     self._browser.back),
            ("Alt+Right",    self._browser.forward),
            ("Ctrl+L",       self._url_bar.setFocus),
            ("Ctrl+Shift+C", self._copy_plain_text),
            ("Ctrl+Shift+K", self._collapse_older),
            ("Ctrl+Shift+E", self._expand_all),
            ("Ctrl+Shift+M", self._toggle_compact_mode),
            ("Ctrl+Shift+D", self._toggle_debug_panel),
            ("Escape",       self._url_bar.clearFocus),
        ]:
            a = QAction(self)
            a.setShortcut(QKeySequence(seq))
            a.triggered.connect(slot)
            self.addAction(a)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _navigate(self, url: str) -> None:
        if not url:
            return
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        self._browser.setUrl(QUrl(url))

    def _go_home(self) -> None:
        self._navigate(self._settings.get("home_url"))

    def _on_url_bar_enter(self) -> None:
        self._navigate(self._url_bar.text().strip())

    @Slot(QUrl)
    def _on_url_changed(self, url: QUrl) -> None:
        text = url.toString()
        self._url_bar.setText(text)
        self._settings.set("last_url", text)

        allowed = self._settings.get("allowed_domains", [])
        if allowed:
            host = url.host().lower()
            if not any(d.lower() in host for d in allowed):
                self._status.showMessage(f"Domain not in allowlist: {host}", 4000)

    @Slot(bool)
    def _on_load_finished(self, ok: bool) -> None:
        self._status.showMessage("Loaded" if ok else "Load failed", 3000)
        if ok:
            self._apply_persistent_injections()

    # ------------------------------------------------------------------
    # Persistent injections — applied on every successful page load
    # and whenever relevant settings change.
    # ------------------------------------------------------------------

    def _apply_persistent_injections(self) -> None:
        """
        Re-apply all CSS/JS that should be active on the current page.
        Called after every successful load and after settings are saved.
        Idempotent: all injections check for an existing element before
        adding another.
        """
        # Compact CSS
        if self._compact_mode:
            self._browser.run_js(PI.INJECT_COMPACT_CSS_JS)
        else:
            self._browser.run_js(PI.REMOVE_COMPACT_CSS_JS)

        # Wrap long lines — independent of compact mode
        wrap = self._settings.get("wrap_long_lines", False)
        self._browser.run_js(PI.WRAP_CODE_ON_JS if wrap else PI.WRAP_CODE_OFF_JS)

        # User stylesheet
        ss_path = self._settings.get("user_stylesheet", "")
        if ss_path and Path(ss_path).exists():
            try:
                css = Path(ss_path).read_text(encoding="utf-8")
                self._browser.run_js(PI.make_user_stylesheet_js(css))
            except OSError:
                pass
        elif not ss_path:
            self._browser.run_js(PI.REMOVE_USER_STYLESHEET_JS)

    # ------------------------------------------------------------------
    # Compact mode
    # ------------------------------------------------------------------

    def _toggle_compact_mode(self) -> None:
        self._compact_mode = not self._compact_mode
        self._compact_btn.setChecked(self._compact_mode)
        self._settings.set("compact_mode", self._compact_mode)
        # Apply immediately without waiting for next load
        if self._compact_mode:
            self._browser.run_js(PI.INJECT_COMPACT_CSS_JS)
        else:
            self._browser.run_js(PI.REMOVE_COMPACT_CSS_JS)
        self._status.showMessage(
            "Compact mode ON" if self._compact_mode else "Compact mode OFF", 2000
        )

    # ------------------------------------------------------------------
    # Collapse / expand
    # ------------------------------------------------------------------

    def _collapse_older(self) -> None:
        keep_code   = self._settings.get("keep_code_expanded",  True)
        prose_only  = self._settings.get("collapse_prose_only", False)
        js = PI.make_collapse_js(keep_code, prose_only)
        self._browser.run_js(js)
        self._status.showMessage("Older messages collapsed", 2000)

    def _expand_all(self) -> None:
        self._browser.run_js(PI.EXPAND_ALL_JS)
        self._status.showMessage("All messages expanded", 2000)

    # ------------------------------------------------------------------
    # Copy / save
    # ------------------------------------------------------------------

    def _copy_plain_text(self) -> None:
        """
        Copy current selection as plain text.

        Primary path: navigator.clipboard.writeText() via injected JS.
        Fallback: JS returns the text string; Python writes it via
                  QApplication.clipboard() if the JS clipboard call failed.
        """
        def _qt_fallback(text: str | None) -> None:
            if text:
                # Qt-side clipboard write — works even when the page's
                # Permissions-Policy blocks navigator.clipboard
                QApplication.clipboard().setText(text)
                self._status.showMessage(
                    f"Copied {len(text)} chars as plain text", 2000
                )
            else:
                self._status.showMessage("Nothing selected to copy", 2000)

        self._browser.run_js(PI.COPY_PLAIN_TEXT_JS, _qt_fallback)

    def _save_page_text(self) -> None:
        def receive(result: str | None) -> None:
            if not result:
                self._status.showMessage("Nothing to save", 2000)
                return
            path, _ = QFileDialog.getSaveFileName(
                self, "Save as text",
                str(Path.home() / "conversation.txt"),
                "Text files (*.txt);;All files (*)"
            )
            if path:
                try:
                    Path(path).write_text(result, encoding="utf-8")
                    self._status.showMessage(f"Saved: {path}", 3000)
                except OSError as e:
                    QMessageBox.warning(self, "Save failed", str(e))
        self._browser.run_js(PI.EXTRACT_TEXT_JS, receive)

    def _save_page_html(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save as HTML",
            str(Path.home() / "conversation.html"),
            "HTML files (*.html);;All files (*)"
        )
        if not path:
            return
        def receive(html: str) -> None:
            if html:
                try:
                    Path(path).write_text(html, encoding="utf-8")
                    self._status.showMessage(f"Saved HTML: {path}", 3000)
                except OSError as e:
                    QMessageBox.warning(self, "Save failed", str(e))
        self._browser.page().toHtml(receive)

    # ------------------------------------------------------------------
    # External browser
    # ------------------------------------------------------------------

    def _open_external(self) -> None:
        QDesktopServices.openUrl(self._browser.url())

    def _open_login_in_browser(self) -> None:
        """
        Open the login page for the current site in the system browser.

        This is the recommended workflow when Google (or any other provider)
        blocks sign-in inside the embedded browser.

        What this does:
          Opens the site's root URL (not the current page URL) in your
          default browser — Chrome, Firefox, Safari, etc. — where Google
          sign-in works normally.

        What this does NOT do:
          It does not transfer your session back into this app automatically.
          Cookies set in your system browser belong to that browser's profile
          and are not shared with this app's embedded profile. They are
          completely separate stores.

        After signing in via the system browser:
          Return to this app and reload the page (F5). If the site uses a
          session that is independent of the Google token (e.g. the site
          issued its own cookie after the OAuth flow), you will need to sign
          in again inside the embedded browser. For sites that persistently
          block embedded sign-in, use the system browser for the working
          session and this app for reading/copying from existing conversations.
        """
        # Determine the site root from the current URL
        current = self._browser.url()
        host    = current.host()

        # Try to find a known site root; fall back to the current page's root
        login_url: str | None = None
        for site_url in KNOWN_SITES.values():
            parsed = urlparse(site_url)
            if parsed.hostname and parsed.hostname in host:
                login_url = site_url
                break
        if not login_url:
            login_url = f"{current.scheme()}://{host}/"

        msg = QMessageBox(self)
        msg.setWindowTitle("Sign in via system browser")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(
            f"<b>Opening login page in your system browser:</b><br>{login_url}"
        )
        msg.setInformativeText(
            "Sign in there normally, then return to this app.<br><br>"
            "<b>Note:</b> Completing sign-in in your system browser does "
            "<em>not</em> automatically log you in here. The two browsers "
            "have separate cookie stores. You may still need to sign in "
            "again inside this app, or use Google's email/password option "
            "if it is offered as an alternative to the Google button."
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel
        )
        msg.setDefaultButton(QMessageBox.StandardButton.Open)

        if msg.exec() == QMessageBox.StandardButton.Open:
            QDesktopServices.openUrl(QUrl(login_url))

    # ------------------------------------------------------------------
    # Debug panel
    # ------------------------------------------------------------------

    def _toggle_debug_panel(self) -> None:
        visible = not self._debug_panel.isVisible()
        self._debug_panel.setVisible(visible)
        self._splitter.setSizes([600, 150] if visible else [1, 0])
        self._settings.set("debug_panel_open", visible)

    def _run_debug_info(self) -> None:
        def show(result: str | None) -> None:
            self._debug_panel.setVisible(True)
            self._splitter.setSizes([600, 150])
            self._debug_panel.append("=== Debug Info ===")
            self._debug_panel.append(str(result))
        self._browser.run_js(PI.make_debug_info_js(), show)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._settings, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._status.showMessage("Settings saved", 2000)
            # Re-apply all persistent injections immediately so changes
            # (wrap_long_lines, user stylesheet, compact mode) take effect
            # without requiring a page reload.
            self._apply_persistent_injections()

    # ------------------------------------------------------------------
    # Window geometry
    # ------------------------------------------------------------------

    def _restore_geometry(self) -> None:
        self.setGeometry(
            self._settings.get("window_x",      100),
            self._settings.get("window_y",      100),
            self._settings.get("window_width",  1280),
            self._settings.get("window_height", 860),
        )

    def closeEvent(self, event) -> None:
        geo = self.geometry()
        self._settings.set("window_x",         geo.x())
        self._settings.set("window_y",         geo.y())
        self._settings.set("window_width",     geo.width())
        self._settings.set("window_height",    geo.height())
        self._settings.set("compact_mode",     self._compact_mode)
        self._settings.set("debug_panel_open", self._debug_panel.isVisible())
        super().closeEvent(event)
