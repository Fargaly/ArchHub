"""Tests for ArchHubBridge library_* slots.

Five JSX-facing bridge slots back the Composer panel + Library browser:
- library_search
- library_list_node_types
- library_inspect
- library_create_node_type
- library_delete_node_type

Bootstrap on first call seeds the in-process library from
library_seeds.PRIMITIVE_SEEDS so the JSX side never sees an empty library
on first run. Persistence path is redirected via tmp_appdata so test runs
never touch the real %LOCALAPPDATA%/ArchHub/library/registry.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

import bridge as _bridge_module  # noqa: E402
import library as _lib  # noqa: E402
import library_persistence as _lp  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_library(tmp_path, monkeypatch):
    """Redirect the persistence root so library_persistence writes go to tmp.
    Reset the in-process library before + after every test.

    BOTH LOCALAPPDATA *and* XDG_DATA_HOME must be redirected:
    library_persistence.default_registry_path() reads LOCALAPPDATA on Windows
    but XDG_DATA_HOME (fallback ~/.local/share) on POSIX. Patching only
    LOCALAPPDATA left the POSIX runners (Linux/macOS CI) writing this file's
    seeded+created node-types to the REAL shared ~/.local/share registry.json,
    which then leaked into later test files: ArchHubBridge's deferred-boot
    thread does library.load_from_disk() whenever that file exists, so
    test_library_end_to_end::test_cold_restart saw 16 leaked entries
    re-hydrated under it (`assert 16 == 0`). Redirect both env vars AND delete
    the registry file on teardown so nothing escapes this test's tmp dir.
    """
    appdata = tmp_path / "appdata"
    appdata.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    monkeypatch.setenv("XDG_DATA_HOME", str(appdata))
    _lib.reset_registry()
    yield
    _lib.reset_registry()
    # Belt-and-braces: drop any registry file this test persisted so it can
    # never leak onto a shared path for a later test file.
    try:
        _lp.delete_registry_file()
    except Exception:
        pass


@pytest.fixture
def bridge_inst():
    # defer_boot=False: this file drives the library slots synchronously and
    # must NOT race the archhub-deferred-boot daemon thread mutating the
    # shared library._REGISTRY out from under the assertions.
    b = _bridge_module.ArchHubBridge(defer_boot=False)
    # Force the bootstrap flag off so each test exercises seed-on-first-call.
    if hasattr(b, "_lib_booted"):
        delattr(b, "_lib_booted")
    return b


def _modular_spec(type_name: str = "demo.bridge_test") -> dict:
    return {
        "type": type_name,
        "display_name": "Demo Bridge Test",
        "category": "shape",
        "inputs": [],
        "outputs": [{"name": "value", "port_type": "any"}],
        "config_schema": {"properties": {"x": {"type": "string"}}},
        "description": (
            "A modular node used to exercise the library bridge slots. "
            "Has a single typed output and a parameterised config schema."
        ),
        "examples": [
            {"input": {}, "output": {"value": "x"}, "note": "happy"},
        ],
        "side_effects": "pure",
    }


# ---------------------------------------------------------------------------
# Bootstrap


def test_first_call_seeds_library(bridge_inst):
    # Fresh registry, fresh bridge → calling any library slot should
    # auto-seed via library_seeds.PRIMITIVE_SEEDS.
    raw = bridge_inst.library_list_node_types("")
    payload = json.loads(raw)
    assert "items" in payload
    assert payload["count"] >= 5  # at least the 5 seeded primitives.
    types = {item["type"] for item in payload["items"]}
    for required in ("data.constant", "input.parameter", "connector.run",
                     "watch.preview", "output.parameter"):
        assert required in types, f"missing seed: {required}"


def test_bootstrap_is_idempotent(bridge_inst):
    # Calling list twice should not double-seed.
    bridge_inst.library_list_node_types("")
    n_first = _lib.registry_size()
    bridge_inst.library_list_node_types("")
    n_second = _lib.registry_size()
    assert n_first == n_second


# ---------------------------------------------------------------------------
# library_search


def test_search_returns_hits_for_seeded_intent(bridge_inst):
    raw = bridge_inst.library_search("constant", "", 8)
    payload = json.loads(raw)
    assert "results" in payload
    assert payload["count"] >= 1
    assert any(r["type"] == "data.constant" for r in payload["results"])


def test_search_no_match_returns_empty(bridge_inst):
    raw = bridge_inst.library_search("octopus-tentacle-protocol", "", 8)
    payload = json.loads(raw)
    assert payload["results"] == []
    assert payload["count"] == 0


def test_search_with_category_filter(bridge_inst):
    raw = bridge_inst.library_search("constant", "input", 8)
    payload = json.loads(raw)
    # data.constant has category=input — should match with boost.
    assert payload["count"] >= 1


def test_search_respects_limit(bridge_inst):
    raw = bridge_inst.library_search("connector", "", 1)
    payload = json.loads(raw)
    assert payload["count"] <= 1


def test_search_handles_empty_intent(bridge_inst):
    raw = bridge_inst.library_search("", "", 8)
    payload = json.loads(raw)
    assert payload["results"] == []
    assert payload["count"] == 0


# ---------------------------------------------------------------------------
# library_list_node_types


def test_list_filtered_by_category(bridge_inst):
    raw = bridge_inst.library_list_node_types("input")
    payload = json.loads(raw)
    assert payload["count"] >= 2  # data.constant + input.parameter
    assert all(item["category"] == "input" for item in payload["items"])


def test_list_unknown_category_returns_empty(bridge_inst):
    raw = bridge_inst.library_list_node_types("nonexistent_category")
    payload = json.loads(raw)
    assert payload["items"] == []
    assert payload["count"] == 0


# ---------------------------------------------------------------------------
# library_inspect


def test_inspect_known_type_returns_spec(bridge_inst):
    raw = bridge_inst.library_inspect("connector.run")
    payload = json.loads(raw)
    assert "spec" in payload
    assert payload["spec"]["type"] == "connector.run"
    assert payload["spec"]["side_effects"] == "host_write"
    # host_write tier → must have ≥2 examples per AgDR-0014.
    assert len(payload["spec"]["examples"]) >= 2


def test_inspect_unknown_type_returns_error_code(bridge_inst):
    raw = bridge_inst.library_inspect("never.registered")
    payload = json.loads(raw)
    assert "error" in payload
    assert payload["code"] == "unknown_type"


def test_inspect_strips_whitespace(bridge_inst):
    raw = bridge_inst.library_inspect("  data.constant  ")
    payload = json.loads(raw)
    assert "spec" in payload
    assert payload["spec"]["type"] == "data.constant"


# ---------------------------------------------------------------------------
# library_create_node_type


def test_create_modular_spec_succeeds_and_persists(bridge_inst, tmp_path):
    bridge_inst.library_list_node_types("")  # trigger seed bootstrap first
    raw = bridge_inst.library_create_node_type(json.dumps(_modular_spec()))
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["registered"] is True
    assert payload["type"] == "demo.bridge_test"

    # Persistence — file should exist on disk under the redirected LOCALAPPDATA.
    p = _lp.default_registry_path()
    assert p.exists()
    with open(p) as fh:
        on_disk = json.load(fh)
    assert "demo.bridge_test" in on_disk["entries"]


def test_create_non_modular_returns_violations(bridge_inst):
    raw = bridge_inst.library_create_node_type(json.dumps({"type": "x"}))
    payload = json.loads(raw)
    assert "error" in payload
    assert "violations" in payload
    assert len(payload["violations"]) >= 3


def test_create_duplicate_returns_error_code(bridge_inst):
    bridge_inst.library_create_node_type(json.dumps(_modular_spec()))
    raw = bridge_inst.library_create_node_type(json.dumps(_modular_spec()))
    payload = json.loads(raw)
    assert "error" in payload
    assert payload["code"] == "duplicate_type"


def test_create_invalid_json_returns_error(bridge_inst):
    raw = bridge_inst.library_create_node_type("not { valid json")
    payload = json.loads(raw)
    assert "error" in payload


def test_create_non_object_payload_returns_error(bridge_inst):
    raw = bridge_inst.library_create_node_type(json.dumps([1, 2, 3]))
    payload = json.loads(raw)
    assert "error" in payload
    assert "JSON object" in payload["error"]


# ---------------------------------------------------------------------------
# library_delete_node_type


def test_delete_known_type_succeeds_and_persists(bridge_inst):
    # Seed + create something deletable.
    bridge_inst.library_create_node_type(json.dumps(_modular_spec()))
    raw = bridge_inst.library_delete_node_type("demo.bridge_test")
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["id"] == "demo.bridge_test"

    # Subsequent inspect should miss.
    raw2 = bridge_inst.library_inspect("demo.bridge_test")
    payload2 = json.loads(raw2)
    assert payload2.get("code") == "unknown_type"


def test_delete_unknown_returns_error_code(bridge_inst):
    raw = bridge_inst.library_delete_node_type("never.registered")
    payload = json.loads(raw)
    assert "error" in payload
    assert payload["code"] == "unknown_type"


# ---------------------------------------------------------------------------
# Persistence integration


def test_bootstrap_loads_from_disk_when_present(bridge_inst):
    # Pre-populate the registry-on-disk to simulate "user already used
    # ArchHub before". Boot should hydrate from disk, not re-seed.
    spec = _modular_spec("from.disk")
    _lib.create_node_type(spec)
    _lib.save_to_disk()
    _lib.reset_registry()
    assert _lib.registry_size() == 0

    # Reset bootstrap flag so next call performs boot.
    if hasattr(bridge_inst, "_lib_booted"):
        delattr(bridge_inst, "_lib_booted")

    raw = bridge_inst.library_list_node_types("")
    payload = json.loads(raw)
    types = {item["type"] for item in payload["items"]}
    assert "from.disk" in types
    # When loaded from disk, the seed routine is skipped — so the 5
    # primitives are NOT also present (disk wins as the source of truth).
    assert "data.constant" not in types
