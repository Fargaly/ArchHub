"""Bridge theme store speaks the founder-signed BRANDED vocabulary.

The defect (jury LENS 1, 2026-06-04): `bridge.set_theme` / `get_theme`
only knew the legacy `dark` / `light` / `system` slots, so the SystemTab
dropdown's branded ids (Forge / Blueprint / Vellum) were rejected by the
bridge — the dialog's best-effort set_theme/get_theme calls were swallowed
no-ops against an outdated store, and the two surfaces (dialog + store)
spoke two different vocabularies.

The fix (ONE-SYSTEM): the bridge theme store is now native-branded.
  * set_theme accepts the branded ids (case-insensitive) and persists them
    branded; it STILL accepts the legacy ids for back-compat, mapping each
    to its branded slot on the way in.
  * get_theme FOLDS any legacy value still on disk to its branded slot on
    read (dark/system/auto -> forge, light -> vellum), so an old store
    upgrades transparently with no migration step.
  * An unknown id is rejected on write (store unchanged) and folds to the
    signed default (forge) on read — never raises.

These tests pin that contract against the REAL ArchHubBridge instance and
its on-disk theme.json (redirected to a tmp %LOCALAPPDATA% so the user's
real store is never touched).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import bridge as _bridge_module  # noqa: E402


@pytest.fixture
def tmp_appdata(tmp_path, monkeypatch):
    """Redirect LOCALAPPDATA + USERPROFILE so theme.json writes land in a
    throwaway dir, never the user's real %LOCALAPPDATA%/ArchHub."""
    appdata = tmp_path / "appdata"
    home = tmp_path / "home"
    appdata.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    monkeypatch.setenv("USERPROFILE", str(home))
    return {"appdata": appdata, "home": home}


@pytest.fixture
def bridge_inst():
    return _bridge_module.ArchHubBridge()


def _theme_file(appdata: Path) -> Path:
    return appdata / "ArchHub" / "theme.json"


def _seed_theme_json(appdata: Path, raw_value) -> Path:
    """Write a theme.json with an arbitrary stored value (simulating a
    value persisted by an older build / older caller)."""
    p = _theme_file(appdata)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"theme": raw_value}, indent=2), encoding="utf-8")
    return p


# ── branded round-trips ───────────────────────────────────────────────

def test_branded_blueprint_round_trips(tmp_appdata, bridge_inst):
    out = json.loads(bridge_inst.set_theme("blueprint"))
    assert out["ok"] is True
    assert out["theme"] == "blueprint"
    assert json.loads(bridge_inst.get_theme())["theme"] == "blueprint"


def test_branded_set_is_case_insensitive(tmp_appdata, bridge_inst):
    """set_theme('Forge') (mixed case) persists + reads back as 'forge'."""
    out = json.loads(bridge_inst.set_theme("Forge"))
    assert out["ok"] is True
    assert out["theme"] == "forge"
    assert json.loads(bridge_inst.get_theme())["theme"] == "forge"
    # The on-disk value is the canonical branded id, not the cased input.
    stored = json.loads(_theme_file(tmp_appdata["appdata"]).read_text("utf-8"))
    assert stored["theme"] == "forge"


def test_vellum_round_trips(tmp_appdata, bridge_inst):
    assert json.loads(bridge_inst.set_theme("vellum"))["theme"] == "vellum"
    assert json.loads(bridge_inst.get_theme())["theme"] == "vellum"


# ── legacy folds on read ──────────────────────────────────────────────

def test_legacy_dark_folds_to_forge_on_read(tmp_appdata, bridge_inst):
    """A store left holding the legacy 'dark' resolves to branded forge."""
    _seed_theme_json(tmp_appdata["appdata"], "dark")
    assert json.loads(bridge_inst.get_theme())["theme"] == "forge"


def test_legacy_light_folds_to_vellum_on_read(tmp_appdata, bridge_inst):
    _seed_theme_json(tmp_appdata["appdata"], "light")
    assert json.loads(bridge_inst.get_theme())["theme"] == "vellum"


def test_legacy_system_folds_to_forge_on_read(tmp_appdata, bridge_inst):
    _seed_theme_json(tmp_appdata["appdata"], "system")
    assert json.loads(bridge_inst.get_theme())["theme"] == "forge"


# ── legacy still accepted on write (back-compat, mapped to branded) ───

def test_legacy_light_write_persists_branded_vellum(tmp_appdata, bridge_inst):
    """A legacy caller passing 'light' is accepted, but the store keeps
    the branded slot — one vocabulary on disk."""
    out = json.loads(bridge_inst.set_theme("light"))
    assert out["ok"] is True
    assert out["theme"] == "vellum"
    assert json.loads(bridge_inst.get_theme())["theme"] == "vellum"


def test_legacy_system_write_persists_branded_forge(tmp_appdata, bridge_inst):
    out = json.loads(bridge_inst.set_theme("system"))
    assert out["ok"] is True
    assert out["theme"] == "forge"


# ── unknown values are safe ───────────────────────────────────────────

def test_unknown_write_rejected_without_raising(tmp_appdata, bridge_inst):
    """An unknown id is rejected (error envelope, never an exception) and
    the store is left unchanged."""
    bridge_inst.set_theme("blueprint")  # establish a known value
    out = json.loads(bridge_inst.set_theme("rainbow"))
    assert "error" in out
    # Store unchanged by the rejected write.
    assert json.loads(bridge_inst.get_theme())["theme"] == "blueprint"


def test_unknown_stored_value_folds_to_default_on_read(tmp_appdata, bridge_inst):
    """A garbage value somehow on disk folds to the signed default (forge)
    on read rather than raising or leaking the garbage."""
    _seed_theme_json(tmp_appdata["appdata"], "chartreuse")
    assert json.loads(bridge_inst.get_theme())["theme"] == "forge"


def test_missing_store_defaults_to_forge(tmp_appdata, bridge_inst):
    """No theme.json at all -> the signed branded default."""
    assert not _theme_file(tmp_appdata["appdata"]).exists()
    assert json.loads(bridge_inst.get_theme())["theme"] == "forge"


def test_corrupt_store_defaults_to_forge(tmp_appdata, bridge_inst):
    """Unparseable theme.json -> signed default, never an exception."""
    p = _theme_file(tmp_appdata["appdata"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ this is not json", encoding="utf-8")
    assert json.loads(bridge_inst.get_theme())["theme"] == "forge"
