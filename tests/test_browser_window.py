"""
Tests for browser_window.py.

These exercise real PySide6/QtWebEngine widgets (offscreen platform, no
sandbox — see conftest.py) rather than mocking Qt away, so we're testing
actual wiring, not a re-description of it. Where a test would otherwise
depend on a real network fetch completing (page content, real conversation
DOM, etc.) we instead monkeypatch WebView.run_js / QFileDialog / QTimer to
capture what BrowserWindow *asked* to happen, which is what these unit
tests care about — page_injection_integration.py already proves the JS
itself behaves correctly against a real DOM.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QUrl, Qt
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

import page_injection as PI
from browser_window import (
    BrowserWindow,
    ClientHintInterceptor,
    SettingsDialog,
    _OAuthPopup,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _capture_run_js(window):
    """Patch window._browser.run_js to record calls instead of touching a page."""
    calls = []

    def fake_run_js(script, callback=None):
        calls.append(script)
        if callback is not None:
            callback(None)

    window._browser.run_js = fake_run_js
    return calls


@pytest.fixture
def window(qtbot, settings):
    win = BrowserWindow(settings)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    yield win
    win.close()


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def test_navigate_adds_https_scheme_when_missing(window):
    window._navigate("example.org/some/path")
    assert window._browser.url().toString() == "https://example.org/some/path"


def test_navigate_preserves_explicit_http_scheme(window):
    window._navigate("http://example.org")
    assert window._browser.url().toString().startswith("http://example.org")


def test_navigate_preserves_explicit_https_scheme(window):
    window._navigate("https://example.org")
    assert window._browser.url().toString().startswith("https://example.org")


def test_navigate_with_empty_string_is_a_no_op(window):
    before = window._browser.url()
    window._navigate("")
    assert window._browser.url() == before


def test_go_home_navigates_to_settings_home_url(window, settings):
    settings.set("home_url", "https://chatgpt.com")
    window._go_home()
    assert window._browser.url().toString().rstrip("/") == "https://chatgpt.com"


def test_url_bar_enter_navigates_to_typed_text(window):
    window._url_bar.setText("gemini.google.com")
    window._on_url_bar_enter()
    assert window._browser.url().host() == "gemini.google.com"


# ---------------------------------------------------------------------------
# URL change handling / allowed_domains
# ---------------------------------------------------------------------------

def test_on_url_changed_updates_url_bar_and_last_url_setting(window, settings):
    window._on_url_changed(QUrl("https://claude.ai/chat/abc"))
    assert window._url_bar.text() == "https://claude.ai/chat/abc"
    assert settings.get("last_url") == "https://claude.ai/chat/abc"


def test_on_url_changed_with_no_allowlist_shows_no_warning(window, settings):
    settings.set("allowed_domains", [])
    window._status.clearMessage()
    window._on_url_changed(QUrl("https://anything.example.com"))
    assert "not in allowlist" not in window._status.currentMessage()


def test_on_url_changed_warns_for_disallowed_domain(window, settings):
    settings.set("allowed_domains", ["claude.ai"])
    window._on_url_changed(QUrl("https://evil.example.com"))
    assert "not in allowlist" in window._status.currentMessage()
    assert "evil.example.com" in window._status.currentMessage()


def test_on_url_changed_allows_matching_domain(window, settings):
    settings.set("allowed_domains", ["claude.ai"])
    window._status.clearMessage()
    window._on_url_changed(QUrl("https://claude.ai/chat"))
    assert "not in allowlist" not in window._status.currentMessage()


# ---------------------------------------------------------------------------
# Compact mode
# ---------------------------------------------------------------------------

def test_toggle_compact_mode_flips_state_and_persists(window, settings):
    calls = _capture_run_js(window)
    initial = window._compact_mode

    window._toggle_compact_mode()
    assert window._compact_mode is (not initial)
    assert window._compact_btn.isChecked() is (not initial)
    assert settings.get("compact_mode") is (not initial)
    assert calls[-1] == (PI.INJECT_COMPACT_CSS_JS if window._compact_mode else PI.REMOVE_COMPACT_CSS_JS)

    window._toggle_compact_mode()
    assert window._compact_mode is initial
    assert calls[-1] == (PI.INJECT_COMPACT_CSS_JS if window._compact_mode else PI.REMOVE_COMPACT_CSS_JS)


# ---------------------------------------------------------------------------
# Collapse / expand
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("keep_code,prose_only", [(True, False), (False, False), (False, True)])
def test_collapse_older_runs_make_collapse_js_with_current_settings(
    window, settings, keep_code, prose_only
):
    settings.set("keep_code_expanded", keep_code)
    settings.set("collapse_prose_only", prose_only)
    calls = _capture_run_js(window)

    window._collapse_older()

    assert calls == [PI.make_collapse_js(keep_code, prose_only)]
    assert window._status.currentMessage() == "Older messages collapsed"


def test_expand_all_runs_expand_all_js(window):
    calls = _capture_run_js(window)
    window._expand_all()
    assert calls == [PI.EXPAND_ALL_JS]
    assert window._status.currentMessage() == "All messages expanded"


# ---------------------------------------------------------------------------
# Copy plain text
# ---------------------------------------------------------------------------

def test_copy_plain_text_writes_to_qt_clipboard_when_js_returns_text(window):
    def fake_run_js(script, callback=None):
        assert script == PI.COPY_PLAIN_TEXT_JS
        callback("hello clipboard")

    window._browser.run_js = fake_run_js
    window._copy_plain_text()

    assert QApplication.clipboard().text() == "hello clipboard"
    assert "Copied 15 chars" in window._status.currentMessage()


def test_copy_plain_text_shows_message_when_nothing_selected(window):
    def fake_run_js(script, callback=None):
        callback(None)

    window._browser.run_js = fake_run_js
    window._copy_plain_text()
    assert window._status.currentMessage() == "Nothing selected to copy"


# ---------------------------------------------------------------------------
# Save page as text / HTML
# ---------------------------------------------------------------------------

def test_save_page_text_writes_extracted_text_to_disk(window, tmp_path, monkeypatch):
    target = tmp_path / "out.txt"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "")
    )

    def fake_run_js(script, callback=None):
        assert script == PI.EXTRACT_TEXT_JS
        callback("some extracted text")

    window._browser.run_js = fake_run_js
    window._save_page_text()

    assert target.read_text(encoding="utf-8") == "some extracted text"
    assert "Saved:" in window._status.currentMessage()


def test_save_page_text_with_nothing_extracted_does_not_open_dialog(window, monkeypatch):
    opened = []
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: opened.append(1) or ("x", "")
    )

    def fake_run_js(script, callback=None):
        callback(None)

    window._browser.run_js = fake_run_js
    window._save_page_text()

    assert opened == []
    assert window._status.currentMessage() == "Nothing to save"


def test_save_page_text_user_cancels_dialog_does_not_write(window, tmp_path, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))

    def fake_run_js(script, callback=None):
        callback("some text")

    window._browser.run_js = fake_run_js
    window._save_page_text()  # should not raise

    written_files = [p for p in tmp_path.iterdir() if p.is_file()]
    assert written_files == []


def test_save_page_html_writes_page_html_to_disk(window, tmp_path, monkeypatch):
    target = tmp_path / "out.html"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "")
    )
    monkeypatch.setattr(
        window._browser.page(), "toHtml", lambda cb: cb("<html>hi</html>")
    )

    window._save_page_html()

    assert target.read_text(encoding="utf-8") == "<html>hi</html>"
    assert "Saved HTML:" in window._status.currentMessage()


# ---------------------------------------------------------------------------
# Debug panel
# ---------------------------------------------------------------------------

def test_toggle_debug_panel_shows_and_persists_setting(window, settings):
    was_visible = window._debug_panel.isVisible()
    window._toggle_debug_panel()
    assert window._debug_panel.isVisible() is (not was_visible)
    assert settings.get("debug_panel_open") is (not was_visible)


def test_run_debug_info_shows_panel_and_logs_result(window):
    def fake_run_js(script, callback=None):
        callback('{"pre_count": 0}')

    window._browser.run_js = fake_run_js
    window._run_debug_info()

    assert window._debug_panel.isVisible() is True
    log_text = window._debug_panel._log.toPlainText()
    assert "Debug Info" in log_text
    assert '"pre_count": 0' in log_text


# ---------------------------------------------------------------------------
# Persistent injections
# ---------------------------------------------------------------------------

def test_apply_persistent_injections_wrap_on(window, settings):
    settings.set("wrap_long_lines", True)
    calls = _capture_run_js(window)
    window._apply_persistent_injections()
    assert PI.WRAP_CODE_ON_JS in calls
    assert PI.WRAP_CODE_OFF_JS not in calls


def test_apply_persistent_injections_wrap_off(window, settings):
    settings.set("wrap_long_lines", False)
    calls = _capture_run_js(window)
    window._apply_persistent_injections()
    assert PI.WRAP_CODE_OFF_JS in calls
    assert PI.WRAP_CODE_ON_JS not in calls


def test_apply_persistent_injections_applies_user_stylesheet_file(window, settings, tmp_path):
    css_file = tmp_path / "custom.css"
    css_file.write_text("body { color: red; }", encoding="utf-8")
    settings.set("user_stylesheet", str(css_file))

    calls = _capture_run_js(window)
    window._apply_persistent_injections()

    expected = PI.make_user_stylesheet_js("body { color: red; }")
    assert expected in calls


def test_apply_persistent_injections_removes_stylesheet_when_path_cleared(window, settings):
    settings.set("user_stylesheet", "")
    calls = _capture_run_js(window)
    window._apply_persistent_injections()
    assert PI.REMOVE_USER_STYLESHEET_JS in calls


def test_apply_persistent_injections_skips_missing_stylesheet_file(window, settings, tmp_path):
    missing = tmp_path / "does_not_exist.css"
    settings.set("user_stylesheet", str(missing))
    calls = _capture_run_js(window)
    window._apply_persistent_injections()
    # Should neither crash nor emit a stylesheet-application call for a
    # nonexistent path, and shouldn't fall into the REMOVE branch either
    # (that only triggers when the setting is empty).
    assert not any("aiwb-user-css" in c and "el.textContent" in c for c in calls)


# ---------------------------------------------------------------------------
# Settings dialog wiring
# ---------------------------------------------------------------------------

def test_open_settings_reapplies_injections_on_accept(window, monkeypatch):
    monkeypatch.setattr(SettingsDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    called = []
    window._apply_persistent_injections = lambda: called.append(True)

    window._open_settings()

    assert called == [True]
    assert window._status.currentMessage() == "Settings saved"


def test_open_settings_does_not_reapply_on_reject(window, monkeypatch):
    monkeypatch.setattr(SettingsDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    called = []
    window._apply_persistent_injections = lambda: called.append(True)

    window._open_settings()

    assert called == []


def test_settings_dialog_save_and_accept_writes_all_fields(qtbot, settings):
    dlg = SettingsDialog(settings)
    qtbot.addWidget(dlg)

    gemini_index = dlg._home_combo.findData("https://gemini.google.com")
    assert gemini_index >= 0
    dlg._home_combo.setCurrentIndex(gemini_index)
    dlg._ss_path.setText("/tmp/my.css")
    dlg._keep_code_cb.setChecked(False)
    dlg._prose_only_cb.setChecked(True)
    dlg._wrap_cb.setChecked(True)

    dlg._save_and_accept()

    assert settings.get("home_url") == "https://gemini.google.com"
    assert settings.get("user_stylesheet") == "/tmp/my.css"
    assert settings.get("keep_code_expanded") is False
    assert settings.get("collapse_prose_only") is True
    assert settings.get("wrap_long_lines") is True


def test_settings_dialog_browse_css_sets_path(qtbot, settings, monkeypatch, tmp_path):
    css = tmp_path / "picked.css"
    css.write_text("body{}", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(css), ""))

    dlg = SettingsDialog(settings)
    qtbot.addWidget(dlg)
    dlg._browse_css()

    assert dlg._ss_path.text() == str(css)


# ---------------------------------------------------------------------------
# Window geometry persistence
# ---------------------------------------------------------------------------

def test_close_event_persists_geometry_and_state(window, settings):
    window.setGeometry(11, 22, 900, 700)
    window._compact_mode = True
    window._debug_panel.setVisible(True)

    window.close()

    assert settings.get("window_x") == 11
    assert settings.get("window_y") == 22
    assert settings.get("window_width") == 900
    assert settings.get("window_height") == 700
    assert settings.get("compact_mode") is True
    assert settings.get("debug_panel_open") is True


def test_restore_geometry_uses_saved_settings(qtbot, make_settings):
    s = make_settings(
        home_url="https://example.com",
        last_url="https://example.com",
        window_x=5, window_y=6, window_width=640, window_height=480,
    )
    win = BrowserWindow(s)
    qtbot.addWidget(win)
    geo = win.geometry()
    assert (geo.x(), geo.y(), geo.width(), geo.height()) == (5, 6, 640, 480)
    win.close()


# ---------------------------------------------------------------------------
# ClientHintInterceptor
# ---------------------------------------------------------------------------

class _FakeRequestInfo:
    def __init__(self):
        self.headers = {}

    def setHttpHeader(self, name, value):
        self.headers[name] = value


def test_client_hint_interceptor_strips_all_sec_ch_ua_headers():
    interceptor = ClientHintInterceptor()
    info = _FakeRequestInfo()

    interceptor.interceptRequest(info)

    for header in ClientHintInterceptor._STRIP:
        assert info.headers[header] == b""


# ---------------------------------------------------------------------------
# OAuth popup
# ---------------------------------------------------------------------------

def test_oauth_popup_schedules_close_for_non_google_redirect(qtbot, monkeypatch):
    from PySide6.QtWebEngineCore import QWebEngineProfile

    scheduled = []
    monkeypatch.setattr(
        "browser_window.QTimer.singleShot",
        lambda delay, fn: scheduled.append((delay, fn)),
    )

    popup = _OAuthPopup(QWebEngineProfile.defaultProfile())
    qtbot.addWidget(popup)

    popup._check_done(QUrl("https://myapp.example.com/done"))

    assert len(scheduled) == 1
    delay, fn = scheduled[0]
    assert delay == 800
    assert fn == popup.close


def test_oauth_popup_does_not_close_while_on_google_domain(qtbot, monkeypatch):
    from PySide6.QtWebEngineCore import QWebEngineProfile

    scheduled = []
    monkeypatch.setattr(
        "browser_window.QTimer.singleShot",
        lambda delay, fn: scheduled.append((delay, fn)),
    )

    popup = _OAuthPopup(QWebEngineProfile.defaultProfile())
    qtbot.addWidget(popup)

    popup._check_done(QUrl("https://accounts.google.com/o/oauth2/auth"))

    assert scheduled == []


# ---------------------------------------------------------------------------
# Login-in-system-browser dialog
# ---------------------------------------------------------------------------

def test_open_login_in_browser_uses_known_site_root(window, monkeypatch):
    window._navigate("https://claude.ai/chat/some-conversation")

    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Cancel
    )
    opened = []
    monkeypatch.setattr(
        "browser_window.QDesktopServices.openUrl", lambda url: opened.append(url.toString())
    )

    window._open_login_in_browser()
    # User cancelled -> nothing should have been opened.
    assert opened == []


def test_open_login_in_browser_opens_url_when_confirmed(window, monkeypatch):
    window._navigate("https://claude.ai/chat/some-conversation")

    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Open
    )
    opened = []
    monkeypatch.setattr(
        "browser_window.QDesktopServices.openUrl", lambda url: opened.append(url.toString())
    )

    window._open_login_in_browser()
    assert opened == ["https://claude.ai"]
