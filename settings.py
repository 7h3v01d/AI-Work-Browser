"""
settings.py — persistent application settings backed by a JSON file.

Location: ~/.ai-work-browser/settings.json

The Settings class is the single store for all user preferences.
All keys have defaults defined in DEFAULTS.  Loading merges saved values
over defaults so that new keys added in future versions always exist.
"""

import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Pre-configured AI sites shown in the toolbar and settings dialog
# ---------------------------------------------------------------------------

KNOWN_SITES: dict[str, str] = {
    "Claude":  "https://claude.ai",
    "ChatGPT": "https://chatgpt.com",
    "Gemini":  "https://gemini.google.com",
}

DEFAULT_HOME_URL = "https://claude.ai"


# ---------------------------------------------------------------------------
# Defaults — every key that the app reads must have an entry here
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    # Navigation
    "home_url":            DEFAULT_HOME_URL,
    "last_url":            DEFAULT_HOME_URL,
    # Window geometry
    "window_x":            100,
    "window_y":            100,
    "window_width":        1280,
    "window_height":       860,
    # Display
    "compact_mode":        False,
    "wrap_long_lines":     False,
    # Collapse behaviour — read by make_collapse_js() at collapse time
    "keep_code_expanded":  True,
    "collapse_prose_only": False,
    # User customisation
    "user_stylesheet":     "",
    # Access control (empty = unrestricted)
    "allowed_domains":     [],
    # UI state
    "debug_panel_open":    False,
}


class Settings:
    """
    Thin wrapper around ~/.ai-work-browser/settings.json.

    Usage
    -----
        s = Settings()
        s.get("compact_mode")        -> bool
        s.set("compact_mode", True)  -> persists immediately
    """

    CONFIG_DIR  = Path.home() / ".ai-work-browser"
    CONFIG_FILE = CONFIG_DIR / "settings.json"

    def __init__(self) -> None:
        self._data: dict[str, Any] = dict(DEFAULTS)
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    def get(self, key: str, fallback: Any = None) -> Any:
        if fallback is not None:
            return self._data.get(key, fallback)
        return self._data.get(key, DEFAULTS.get(key))

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._save()

    def all(self) -> dict[str, Any]:
        return dict(self._data)

    def _load(self) -> None:
        if not self.CONFIG_FILE.exists():
            self._save()
            return
        try:
            with open(self.CONFIG_FILE, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            # Merge: new defaults for keys added since the file was written
            for key, default in DEFAULTS.items():
                self._data[key] = loaded.get(key, default)
            # Preserve any user-added extra keys
            for key, val in loaded.items():
                if key not in self._data:
                    self._data[key] = val
        except (json.JSONDecodeError, OSError):
            # Corrupt file — reset to defaults
            self._save()

    def _save(self) -> None:
        try:
            with open(self.CONFIG_FILE, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
        except OSError:
            pass  # Non-fatal; preferences won't persist this session
