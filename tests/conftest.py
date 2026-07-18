"""
conftest.py — shared pytest fixtures for the AI Work Browser test suite.

Key responsibilities
---------------------
1. Force Qt into headless ("offscreen") mode and disable the Chromium
   sandbox *before* PySide6 is ever imported, so the full GUI (including
   QtWebEngine) can be exercised in a CI / container environment with no
   display and no --no-sandbox privileges.
2. Put the project root on sys.path so `import settings`,
   `import page_injection`, `import browser_window` work the same way
   they do when main.py runs them.
3. Provide isolated Settings instances backed by a tmp_path config dir,
   so tests never touch (or depend on) a real ~/.ai-work-browser.
"""

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Must happen before any PySide6 / QtWebEngine import anywhere in the suite.
# ---------------------------------------------------------------------------
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest  # noqa: E402


@pytest.fixture
def isolated_settings_cls(tmp_path, monkeypatch):
    """The Settings *class*, patched so every instance reads/writes tmp_path."""
    from settings import Settings

    cfg_dir = tmp_path / ".ai-work-browser"
    monkeypatch.setattr(Settings, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(Settings, "CONFIG_FILE", cfg_dir / "settings.json")
    return Settings


@pytest.fixture
def make_settings(isolated_settings_cls):
    """Factory: build a fresh, isolated Settings instance with optional overrides."""

    def _make(**overrides):
        s = isolated_settings_cls()
        for key, value in overrides.items():
            s.set(key, value)
        return s

    return _make


@pytest.fixture
def settings(make_settings):
    """A single isolated Settings instance, pointed at about:blank so
    BrowserWindow tests never attempt a real network navigation."""
    return make_settings(home_url="https://example.com", last_url="https://example.com")
