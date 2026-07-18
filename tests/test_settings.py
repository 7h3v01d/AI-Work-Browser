"""
Tests for settings.py — the persistent JSON-backed settings store.

No Qt / GUI dependency at all: these tests only need an isolated
CONFIG_DIR (see conftest.isolated_settings_cls) and are fast.
"""

import json

import pytest

from settings import DEFAULTS, KNOWN_SITES, DEFAULT_HOME_URL


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

def test_known_sites_contains_expected_entries():
    assert KNOWN_SITES["Claude"] == "https://claude.ai"
    assert KNOWN_SITES["ChatGPT"] == "https://chatgpt.com"
    assert KNOWN_SITES["Gemini"] == "https://gemini.google.com"


def test_default_home_url_is_a_known_site():
    assert DEFAULT_HOME_URL in KNOWN_SITES.values()


# ---------------------------------------------------------------------------
# Construction / defaults
# ---------------------------------------------------------------------------

def test_fresh_instance_matches_every_default(isolated_settings_cls):
    s = isolated_settings_cls()
    for key, value in DEFAULTS.items():
        assert s.get(key) == value


def test_construction_creates_config_dir_and_file(isolated_settings_cls):
    s = isolated_settings_cls()
    assert s.CONFIG_DIR.is_dir()
    assert s.CONFIG_FILE.is_file()
    on_disk = json.loads(s.CONFIG_FILE.read_text())
    assert on_disk == DEFAULTS


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------

def test_get_unknown_key_with_no_fallback_returns_none(isolated_settings_cls):
    s = isolated_settings_cls()
    assert s.get("totally_made_up_key") is None


def test_get_unknown_key_uses_provided_fallback(isolated_settings_cls):
    s = isolated_settings_cls()
    assert s.get("totally_made_up_key", "fallback") == "fallback"


def test_get_unknown_key_with_falsy_but_not_none_fallback(isolated_settings_cls):
    # Regression test for the `if fallback is not None` branch in get():
    # False/0/"" fallbacks must still be honoured, not treated as "no fallback".
    s = isolated_settings_cls()
    assert s.get("totally_made_up_key", False) is False
    assert s.get("totally_made_up_key", 0) == 0
    assert s.get("totally_made_up_key", "") == ""


def test_get_known_key_ignores_fallback(isolated_settings_cls):
    s = isolated_settings_cls()
    s.set("compact_mode", True)
    assert s.get("compact_mode", False) is True


# ---------------------------------------------------------------------------
# set() / persistence across instances
# ---------------------------------------------------------------------------

def test_set_persists_across_new_instance(isolated_settings_cls):
    s1 = isolated_settings_cls()
    s1.set("compact_mode", True)
    s1.set("home_url", "https://gemini.google.com")

    s2 = isolated_settings_cls()
    assert s2.get("compact_mode") is True
    assert s2.get("home_url") == "https://gemini.google.com"


def test_set_writes_valid_json_immediately(isolated_settings_cls):
    s = isolated_settings_cls()
    s.set("allowed_domains", ["claude.ai", "chatgpt.com"])
    on_disk = json.loads(s.CONFIG_FILE.read_text())
    assert on_disk["allowed_domains"] == ["claude.ai", "chatgpt.com"]


# ---------------------------------------------------------------------------
# all()
# ---------------------------------------------------------------------------

def test_all_returns_a_copy_not_the_live_dict(isolated_settings_cls):
    s = isolated_settings_cls()
    snapshot = s.all()
    snapshot["compact_mode"] = "mutated"
    assert s.get("compact_mode") is DEFAULTS["compact_mode"]


def test_all_contains_every_default_key(isolated_settings_cls):
    s = isolated_settings_cls()
    all_settings = s.all()
    for key in DEFAULTS:
        assert key in all_settings


# ---------------------------------------------------------------------------
# Loading / migration behaviour
# ---------------------------------------------------------------------------

def test_loading_fills_in_defaults_for_keys_missing_from_disk(isolated_settings_cls):
    cfg_dir = isolated_settings_cls.CONFIG_DIR
    cfg_dir.mkdir(parents=True, exist_ok=True)
    old_file = {"home_url": "https://chatgpt.com"}  # simulate an old version's file
    isolated_settings_cls.CONFIG_FILE.write_text(json.dumps(old_file))

    s = isolated_settings_cls()
    assert s.get("home_url") == "https://chatgpt.com"          # preserved
    assert s.get("compact_mode") == DEFAULTS["compact_mode"]    # backfilled


def test_loading_preserves_unknown_extra_keys_from_disk(isolated_settings_cls):
    cfg_dir = isolated_settings_cls.CONFIG_DIR
    cfg_dir.mkdir(parents=True, exist_ok=True)
    on_disk = dict(DEFAULTS)
    on_disk["some_future_key"] = "kept-for-forward-compat"
    isolated_settings_cls.CONFIG_FILE.write_text(json.dumps(on_disk))

    s = isolated_settings_cls()
    assert s.get("some_future_key") == "kept-for-forward-compat"
    assert s.all()["some_future_key"] == "kept-for-forward-compat"


def test_corrupt_json_file_resets_to_defaults(isolated_settings_cls):
    cfg_dir = isolated_settings_cls.CONFIG_DIR
    cfg_dir.mkdir(parents=True, exist_ok=True)
    isolated_settings_cls.CONFIG_FILE.write_text("{ this is not valid json ][")

    s = isolated_settings_cls()
    assert s.all() == DEFAULTS
    # And the corrupt file should have been overwritten with valid JSON.
    assert json.loads(isolated_settings_cls.CONFIG_FILE.read_text()) == DEFAULTS


def test_missing_file_is_created_with_defaults(isolated_settings_cls):
    assert not isolated_settings_cls.CONFIG_FILE.exists()
    s = isolated_settings_cls()
    assert isolated_settings_cls.CONFIG_FILE.exists()
    assert s.all() == DEFAULTS


# ---------------------------------------------------------------------------
# Save failure is non-fatal
# ---------------------------------------------------------------------------

def test_save_failure_does_not_raise(isolated_settings_cls, tmp_path):
    s = isolated_settings_cls()
    # Point CONFIG_FILE at a directory so opening it for writing raises
    # OSError (IsADirectoryError), exercising the `except OSError: pass`
    # branch in _save() without needing to monkeypatch builtins.open.
    bogus_path = tmp_path / "settings_is_actually_a_dir"
    bogus_path.mkdir()
    s.CONFIG_FILE = bogus_path

    # Should not raise despite the write failing.
    s.set("compact_mode", True)
    assert s.get("compact_mode") is True  # in-memory value still updated
