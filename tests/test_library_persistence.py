"""Tests for app/library_persistence.py + library.{save_to_disk,load_from_disk}.

The library must survive a restart. Atomic writes prevent half-file
corruption. Corrupt / shape-mismatched entries drop silently — the library
boots clean, no exception.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import library  # noqa: E402
import library_persistence  # noqa: E402
from library import (  # noqa: E402
    create_node_type,
    inspect,
    load_from_disk,
    reset_registry,
    registry_size,
    save_to_disk,
)
from library_seeds import seed_library  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_registry():
    reset_registry()
    yield
    reset_registry()


@pytest.fixture
def tmp_path_registry(tmp_path: Path) -> Path:
    return tmp_path / "library" / "registry.json"


def _spec(type_name: str = "demo.persist", **overrides) -> dict:
    base = {
        "type": type_name,
        "display_name": "Demo Persist",
        "category": "shape",
        "inputs": [],
        "outputs": [{"name": "value", "port_type": "any"}],
        "config_schema": {"properties": {"x": {"type": "string"}}},
        "description": (
            "A demo node used to test persistence. Round-trips through "
            "JSON disk storage and back into the registry."
        ),
        "examples": [
            {"input": {}, "output": {"value": "x"}, "note": "happy"},
        ],
        "side_effects": "pure",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# default_registry_path


def test_default_registry_path_returns_path():
    p = library_persistence.default_registry_path()
    assert isinstance(p, Path)
    assert p.name == "registry.json"
    assert "ArchHub" in str(p)
    assert "library" in str(p)


# ---------------------------------------------------------------------------
# save / load round-trip


def test_save_creates_parent_directories(tmp_path_registry: Path):
    create_node_type(_spec())
    written = save_to_disk(tmp_path_registry)
    assert written == tmp_path_registry
    assert tmp_path_registry.exists()
    assert tmp_path_registry.parent.is_dir()


def test_save_then_load_round_trip(tmp_path_registry: Path):
    create_node_type(_spec("a.alpha"))
    create_node_type(_spec("b.bravo"))
    save_to_disk(tmp_path_registry)

    reset_registry()
    assert registry_size() == 0
    loaded = load_from_disk(tmp_path_registry)
    assert loaded == 2
    assert registry_size() == 2

    # Spec data is preserved.
    assert inspect("a.alpha")["type"] == "a.alpha"
    assert inspect("b.bravo")["type"] == "b.bravo"


def test_save_overwrites_existing_file(tmp_path_registry: Path):
    create_node_type(_spec("a.x"))
    save_to_disk(tmp_path_registry)
    first_mtime = tmp_path_registry.stat().st_mtime_ns

    # Mutate registry and re-save.
    create_node_type(_spec("b.y"))
    save_to_disk(tmp_path_registry)
    second_mtime = tmp_path_registry.stat().st_mtime_ns

    # The new file replaced the old one (atomic via os.replace).
    assert second_mtime >= first_mtime
    with open(tmp_path_registry) as fh:
        payload = json.load(fh)
    assert payload["count"] == 2
    assert set(payload["entries"].keys()) == {"a.x", "b.y"}


def test_save_is_atomic_no_tmp_left_behind(tmp_path_registry: Path):
    create_node_type(_spec())
    save_to_disk(tmp_path_registry)
    tmp_file = tmp_path_registry.with_suffix(
        tmp_path_registry.suffix + ".tmp"
    )
    # After os.replace, the tmp file is gone.
    assert not tmp_file.exists()
    assert tmp_path_registry.exists()


# ---------------------------------------------------------------------------
# load behaviour — missing / corrupt files


def test_load_missing_file_returns_empty(tmp_path_registry: Path):
    # File doesn't exist yet.
    assert not tmp_path_registry.exists()
    loaded = library_persistence.load(tmp_path_registry)
    assert loaded == {}


def test_load_empty_file_returns_empty(tmp_path_registry: Path):
    tmp_path_registry.parent.mkdir(parents=True, exist_ok=True)
    tmp_path_registry.write_text("", encoding="utf-8")
    loaded = library_persistence.load(tmp_path_registry)
    assert loaded == {}


def test_load_invalid_json_returns_empty(tmp_path_registry: Path):
    tmp_path_registry.parent.mkdir(parents=True, exist_ok=True)
    tmp_path_registry.write_text("not { valid json", encoding="utf-8")
    loaded = library_persistence.load(tmp_path_registry)
    assert loaded == {}


def test_load_unexpected_top_level_shape_returns_empty(tmp_path_registry: Path):
    tmp_path_registry.parent.mkdir(parents=True, exist_ok=True)
    # Top level should be a dict; an array is the wrong shape.
    tmp_path_registry.write_text("[1, 2, 3]", encoding="utf-8")
    loaded = library_persistence.load(tmp_path_registry)
    assert loaded == {}


def test_load_missing_entries_key_returns_empty(tmp_path_registry: Path):
    tmp_path_registry.parent.mkdir(parents=True, exist_ok=True)
    tmp_path_registry.write_text(
        '{"version": 1, "count": 0}', encoding="utf-8",
    )
    loaded = library_persistence.load(tmp_path_registry)
    assert loaded == {}


def test_load_filters_mismatched_type_key(tmp_path_registry: Path):
    """A disk entry whose key doesn't match its inner `type` field is
    dropped. Defensive against partial corruption.
    """
    tmp_path_registry.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "count": 2,
        "entries": {
            "a.real": _spec("a.real"),
            "wrong.key": _spec("different.type"),  # key/type mismatch
        },
    }
    tmp_path_registry.write_text(json.dumps(payload), encoding="utf-8")
    loaded = library_persistence.load(tmp_path_registry)
    assert "a.real" in loaded
    assert "wrong.key" not in loaded
    assert len(loaded) == 1


# ---------------------------------------------------------------------------
# load_from_disk — re-validation


def test_load_from_disk_drops_non_modular_entries(tmp_path_registry: Path):
    """An entry on disk that no longer satisfies ModularNodeSpec (e.g. an
    old format predating AgDR-0014 token changes) is silently dropped.
    The library boots clean — the user's other entries are unaffected.
    """
    tmp_path_registry.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "count": 2,
        "entries": {
            "a.modern": _spec("a.modern"),
            "b.legacy": {
                # Pre-AgDR-0014: uses removed `category=transform`.
                "type": "b.legacy",
                "display_name": "Legacy",
                "category": "transform",  # no longer in enum
                "inputs": [],
                "outputs": [{"name": "v", "port_type": "any"}],
                "config_schema": {"properties": {"x": {"type": "string"}}},
                "description": "x" * 80,
                "examples": [{"input": {}, "output": {}}],
                "side_effects": "pure",
            },
        },
    }
    tmp_path_registry.write_text(json.dumps(payload), encoding="utf-8")
    accepted = load_from_disk(tmp_path_registry)
    # Only the modern entry is registered.
    assert accepted == 1
    assert registry_size() == 1
    assert "a.modern" in library.list_node_types.__globals__["_REGISTRY"]


def test_load_from_disk_overwrites_in_process_entries(tmp_path_registry: Path):
    """If an entry exists in both the in-process registry AND on disk,
    disk wins (disk is the source of truth on cold boot).
    """
    # Set up a different version in process.
    create_node_type(_spec("a.x", display_name="In Process"))

    # Write a different spec to disk.
    on_disk = _spec("a.x", display_name="On Disk")
    tmp_path_registry.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "count": 1, "entries": {"a.x": on_disk}}
    tmp_path_registry.write_text(json.dumps(payload), encoding="utf-8")

    load_from_disk(tmp_path_registry)
    # Disk version won.
    assert inspect("a.x")["display_name"] == "On Disk"


# ---------------------------------------------------------------------------
# delete_registry_file


def test_delete_registry_file_when_present(tmp_path_registry: Path):
    create_node_type(_spec())
    save_to_disk(tmp_path_registry)
    assert tmp_path_registry.exists()
    assert library_persistence.delete_registry_file(tmp_path_registry) is True
    assert not tmp_path_registry.exists()


def test_delete_registry_file_when_absent(tmp_path_registry: Path):
    assert library_persistence.delete_registry_file(tmp_path_registry) is False


# ---------------------------------------------------------------------------
# Seeded library round-trip


def test_seeded_library_saves_and_loads(tmp_path_registry: Path):
    seed_library()
    expected = registry_size()
    save_to_disk(tmp_path_registry)

    reset_registry()
    assert registry_size() == 0

    accepted = load_from_disk(tmp_path_registry)
    assert accepted == expected
    assert registry_size() == expected
    # Connector.run (host_write — 2 examples required) survives the
    # round-trip via the side_effects tier validator.
    inspect("connector.run")
