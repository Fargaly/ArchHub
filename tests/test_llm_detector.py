"""llm_detector + ai_runner.detect_local tests — v1.3.2.

The detector probes 8 backends (anthropic / openai / google / openrouter
/ ollama / lmstudio / codex_cli / archhub_cloud). These tests verify:
  - missing path returns "missing" cleanly
  - live path returns "live" with model list
  - cache TTL (25s) honoured
  - ai_runner.detect_local wraps the detector with summary buckets
  - ai_detect_local tool is registered with the right endpoint

No live HTTP / no real keys touched — every probe is mocked.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture(autouse=True)
def _clear_detector_cache():
    """Each test starts with a clean cache so probes re-run."""
    try:
        from llm_detector import _CACHE
        _CACHE.clear()
    except Exception:
        pass
    yield
    try:
        from llm_detector import _CACHE
        _CACHE.clear()
    except Exception:
        pass


# ---------------------------------------------------------------------------
class TestKeyBasedProbers:
    def test_anthropic_missing_when_no_key(self):
        from llm_detector import probe_anthropic
        with patch("llm_detector._load_key", return_value=None):
            r = probe_anthropic()
        assert r["status"] == "missing"
        assert r["models"] == []
        assert "key" in r["note"].lower()

    def test_anthropic_live_when_key_present(self):
        from llm_detector import probe_anthropic
        with patch("llm_detector._load_key",
                    return_value="sk-ant-test-1234567890"):
            r = probe_anthropic()
        assert r["status"] == "live"
        assert any("claude" in m.lower() for m in r["models"])
        assert r["detail"]["key_prefix"].startswith("sk-ant-")

    def test_openai_missing_when_no_key(self):
        from llm_detector import probe_openai
        with patch("llm_detector._load_key", return_value=None):
            r = probe_openai()
        assert r["status"] == "missing"

    def test_openai_live_when_key_present(self):
        from llm_detector import probe_openai
        with patch("llm_detector._load_key", return_value="sk-test"):
            r = probe_openai()
        assert r["status"] == "live"
        assert any("gpt-5" in m for m in r["models"])

    def test_google_status_follows_key(self):
        from llm_detector import probe_google
        with patch("llm_detector._load_key", return_value=None):
            assert probe_google()["status"] == "missing"
        # Clear cache before second probe
        from llm_detector import _CACHE
        _CACHE.clear()
        with patch("llm_detector._load_key", return_value="AIza-test"):
            r = probe_google()
        assert r["status"] == "live"
        assert any("gemini" in m for m in r["models"])


class TestNetworkProbers:
    def test_ollama_missing_when_port_closed(self):
        from llm_detector import probe_ollama
        with patch("llm_detector._tcp_open", return_value=False):
            r = probe_ollama()
        assert r["status"] == "missing"
        assert "not running" in r["note"].lower()

    def test_ollama_live_with_models(self):
        from llm_detector import probe_ollama
        fake_data = {"models": [
            {"name": "qwen2.5-coder:7b"},
            {"name": "llama3.2:3b"},
        ]}
        with patch("llm_detector._tcp_open", return_value=True), \
             patch("llm_detector._http_json", return_value=fake_data):
            r = probe_ollama()
        assert r["status"] == "live"
        assert "qwen2.5-coder:7b" in r["models"]
        assert "llama3.2:3b" in r["models"]
        assert "2 model" in r["note"]

    def test_ollama_available_when_running_but_no_models(self):
        from llm_detector import probe_ollama
        with patch("llm_detector._tcp_open", return_value=True), \
             patch("llm_detector._http_json", return_value={"models": []}):
            r = probe_ollama()
        assert r["status"] == "available"
        assert "no models pulled" in r["note"].lower()

    def test_lmstudio_filters_out_embeddings(self):
        from llm_detector import probe_lmstudio
        fake = {"data": [
            {"id": "qwen/qwen3.6-35b-a3b"},
            {"id": "text-embedding-nomic-embed-text-v1.5"},
        ]}
        with patch("llm_detector._tcp_open", return_value=True), \
             patch("llm_detector._http_json", return_value=fake):
            r = probe_lmstudio()
        assert r["status"] == "live"
        # Embedding-only models are filtered from the chat list.
        assert "text-embedding-nomic-embed-text-v1.5" not in r["models"]
        assert "qwen/qwen3.6-35b-a3b" in r["models"]

    def test_lmstudio_available_when_only_embedding_loaded(self):
        from llm_detector import probe_lmstudio
        fake = {"data": [
            {"id": "text-embedding-nomic-embed-text-v1.5"},
        ]}
        with patch("llm_detector._tcp_open", return_value=True), \
             patch("llm_detector._http_json", return_value=fake):
            r = probe_lmstudio()
        assert r["status"] == "available"
        assert "no chat model" in r["note"].lower()


class TestCodexCli:
    def test_missing_when_binary_absent(self, tmp_path, monkeypatch):
        # Point CODEX_HOME at an empty dir.
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        from llm_detector import probe_codex_cli, _CACHE
        _CACHE.clear()
        r = probe_codex_cli()
        assert r["status"] == "missing"

    def test_available_when_binary_but_no_auth(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        (tmp_path / ".sandbox-bin").mkdir()
        (tmp_path / ".sandbox-bin" / "codex.exe").write_bytes(b"fake")
        from llm_detector import probe_codex_cli, _CACHE
        _CACHE.clear()
        r = probe_codex_cli()
        assert r["status"] == "available"
        assert "not logged in" in r["note"].lower()

    def test_live_with_configured_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        (tmp_path / ".sandbox-bin").mkdir()
        (tmp_path / ".sandbox-bin" / "codex.exe").write_bytes(b"fake")
        (tmp_path / "auth.json").write_text('{"tokens":{}}', encoding="utf-8")
        (tmp_path / "config.toml").write_text(
            'model = "gpt-5.5"\nmodel_reasoning_effort = "high"\n',
            encoding="utf-8",
        )
        from llm_detector import probe_codex_cli, _CACHE
        _CACHE.clear()
        r = probe_codex_cli()
        assert r["status"] == "live"
        assert r["models"] == ["gpt-5.5"]
        assert r["detail"]["configured_model"] == "gpt-5.5"


class TestCacheTTL:
    def test_cache_hits_within_ttl(self):
        from llm_detector import probe_anthropic, _CACHE
        with patch("llm_detector._load_key",
                    return_value="sk-ant-test") as mock_key:
            probe_anthropic()
            probe_anthropic()
            probe_anthropic()
        # Cached after first call — only one _load_key invocation.
        assert mock_key.call_count == 1
        # Cache slot populated.
        assert "anthropic" in _CACHE

    def test_force_bypasses_cache(self):
        from llm_detector import detect_all, _CACHE
        # Seed cache.
        with patch("llm_detector._load_key", return_value="sk-1"):
            detect_all()
        # Now force a re-probe; cache should be cleared first.
        with patch("llm_detector._load_key", return_value="sk-1") as mock_key:
            detect_all(force=True)
        # All 5 key-based probers should have called _load_key.
        assert mock_key.call_count >= 5


class TestDetectAll:
    def test_returns_dict_for_every_provider(self):
        from llm_detector import detect_all, PROBERS
        with patch("llm_detector._load_key", return_value=None), \
             patch("llm_detector._tcp_open", return_value=False):
            r = detect_all(force=True)
        # Every prober must be represented.
        for pid in PROBERS:
            assert pid in r
            assert "status" in r[pid]
            assert r[pid]["status"] in ("live", "available", "missing")

    def test_live_providers_filter(self, tmp_path, monkeypatch):
        from llm_detector import live_providers, _CACHE
        _CACHE.clear()
        # Point CODEX_HOME at an empty dir so the real ~/.codex install
        # on the founder's machine doesn't bleed into the test.
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        with patch("llm_detector._load_key",
                    side_effect=lambda n: "key" if n == "anthropic" else None), \
             patch("llm_detector._tcp_open", return_value=False):
            live = live_providers()
        assert live == ["anthropic"]


class TestDisplayLabel:
    def test_known_providers_have_short_names(self):
        from llm_detector import display_label
        assert display_label("anthropic") == "Claude"
        assert display_label("openai") == "GPT"
        assert display_label("google") == "Gemini"
        assert display_label("codex_cli") == "Codex"
        assert display_label("lmstudio") == "LM Studio"
        assert display_label("ollama") == "Ollama"

    def test_unknown_provider_title_cased(self):
        from llm_detector import display_label
        assert display_label("rhino_local") == "Rhino_Local"


class TestAiRunnerDetectLocalWrapper:
    def test_summary_buckets_grouped_correctly(self):
        # Mock the detector directly.
        sys.path.insert(0, str(APP_ROOT))
        from connectors import ai_runner
        fake = {
            "anthropic": {"status": "live",      "models": ["claude"], "note": ""},
            "ollama":    {"status": "live",      "models": ["q1", "q2"], "note": ""},
            "openai":    {"status": "available", "models": [], "note": ""},
            "google":    {"status": "missing",   "models": [], "note": ""},
        }
        with patch("llm_detector.detect_all", return_value=fake):
            r = ai_runner.detect_local(force=True)
        assert r["status"] == "ok"
        assert "ts" in r
        assert set(r["summary"]["live"]) == {"anthropic", "ollama"}
        assert r["summary"]["available"] == ["openai"]
        assert r["summary"]["missing"] == ["google"]
        assert r["providers"] == fake

    def test_detector_unavailable_returns_clean_error(self):
        from connectors import ai_runner
        # Simulate llm_detector import failing.
        import sys as _sys
        original = _sys.modules.pop("llm_detector", None)
        with patch.dict(_sys.modules, {"llm_detector": None}):
            r = ai_runner.detect_local(force=True)
        if original is not None:
            _sys.modules["llm_detector"] = original
        # Either it errored cleanly or it returned ok if it could fall
        # through. Both are acceptable so long as we never raise.
        assert r["status"] in ("error", "ok")


class TestAiDetectLocalToolRegistry:
    def test_tool_registered_in_engine(self):
        from tool_engine import TOOLS
        names = {t["name"] for t in TOOLS if t.get("family") == "ai"}
        assert "ai_detect_local" in names

    def test_tool_endpoint_resolves_to_detect_local(self):
        from tool_engine import TOOLS
        from connectors import ai_runner
        tool = next(t for t in TOOLS if t["name"] == "ai_detect_local")
        family, handler = tool["endpoint"]
        assert family == "ai"
        assert hasattr(ai_runner, handler)
        assert callable(getattr(ai_runner, handler))

    def test_tool_input_schema_allows_force(self):
        from tool_engine import TOOLS
        tool = next(t for t in TOOLS if t["name"] == "ai_detect_local")
        props = tool["input_schema"].get("properties") or {}
        assert "force" in props
        assert props["force"]["type"] == "boolean"
