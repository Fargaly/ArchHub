"""R2: exercise relay selection against recorded public OpenRouter metadata."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import httpx
import pytest

import config


@pytest.fixture
def catalogue(monkeypatch):
    payload = json.loads((Path(__file__).parent / "fixtures" /
                          "openrouter-models-2026-11-07.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(config, "_OPENROUTER_FREE_CACHE", {"at": 0, "models": ()})
    monkeypatch.setattr(config.httpx, "get", lambda *a, **kw:
                        httpx.Response(200, json=payload))
    return payload


def test_recorded_pool_prioritizes_curated_text_tools(catalogue, monkeypatch):
    pool = config.openrouter_free_models(force_refresh=True)
    assert pool[:5] == config.RELAY_PREFERRED_MODELS
    assert pool.index("liquid/lfm-3-1.7b:free") > 4
    assert "openrouter/free" not in pool
    assert not any("lyria" in slug for slug in pool)
    rows = {row["id"]: row for row in catalogue["data"]}
    assert set(pool) <= rows.keys()
    assert set(config._OPENROUTER_FREE_MODELS_DEFAULT) <= rows.keys()
    assert all("tools" in rows[slug]["supported_parameters"] for slug in pool)
    monkeypatch.setattr(config, "FREE_PROVIDER_API_KEY", "")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "fixture-key")
    assert config.select_free_model()["model"] == pool[0]


def test_remainder_sorted_by_total_size_and_independent_of_api_order(catalogue):
    pool = config.openrouter_free_models(force_refresh=True)
    catalogue["data"].reverse()
    assert config.openrouter_free_models(force_refresh=True) == pool
    known_sizes = ["google/gemma-4-31b-it:free",
                   "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
                   "xingchen-agi/xing4.0-29b-a4b:free",
                   "google/gemma-4-26b-a4b-it:free",
                   "liquid/lfm-2.5-2.6b:free", "liquid/lfm-3-1.7b:free"]
    assert [slug for slug in pool if slug in known_sizes] == known_sizes


@pytest.mark.parametrize("changes", [
    {"supported_parameters": []},
    {"architecture": {"input_modalities": ["audio"], "output_modalities": ["text"]}},
    {"architecture": {"input_modalities": ["text"], "output_modalities": ["audio"]}},
    {"pricing": {"prompt": "0", "completion": "0.01"}},
    {"architecture": None},
    {"supported_parameters": 1},
    {"architecture": {"input_modalities": "text", "output_modalities": ["text"]}},
])
def test_curated_model_must_still_qualify(catalogue, changes):
    head = config.RELAY_PREFERRED_MODELS[0]
    next(row for row in catalogue["data"] if row["id"] == head).update(changes)
    assert head not in config.openrouter_free_models(force_refresh=True)


def test_offline_fallback_is_desktop_source(monkeypatch):
    from nodelang import model_router
    monkeypatch.setattr(config.httpx, "get", lambda *a, **kw: httpx.Response(503))
    monkeypatch.setattr(config, "_OPENROUTER_FREE_CACHE", {"at": 0, "models": ()})
    assert config.openrouter_free_models(force_refresh=True) == model_router._OPENROUTER_FREE_MODELS_DEFAULT


def test_container_import_uses_same_shared_file(tmp_path):
    backend = Path(config.__file__).parent
    shutil.copy2(backend / "config.py", tmp_path)
    shared = Path(__file__).resolve().parents[3] / "01.APP/nodelang/openrouter_defaults.py"
    shutil.copy2(shared, tmp_path)
    result = subprocess.run([sys.executable, "-I", "-c",
                             "import sys; sys.path.insert(0, sys.argv[1]); import config; "
                             "assert config.OPENROUTER_FREE_MODELS == config._OPENROUTER_FREE_MODELS_DEFAULT",
                             str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
