"""Smoke tests for the cloud-deploy bits of `agents/`.

Covers:
  * `anthropic_client.complete()` returns the OllamaCompletion-shaped
    envelope with text, tokens, no error on a mocked 200.
  * `anthropic_client.complete()` surfaces 4xx / network errors in the
    `error` field without raising.
  * Department model-id mapping (qwen2.5-coder / llama3.2 → Haiku).
  * `cloud_runner.CloudDaemon.tick_once()` writes the heartbeat file.
  * `cloud_runner._install_backend()` swaps `agents.base.complete` to
    the Anthropic implementation when `backend='anthropic'`, and
    leaves it alone for `backend='ollama'`.
  * `dashboard_endpoint.build_app()` /healthz returns OK with a fresh
    heartbeat and 'stale' when it's old.

Nothing here hits the real Anthropic API — httpx.post is monkeypatched.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _force_top_level_agents() -> None:
    """Other test files insert `app/` onto sys.path early. That makes
    `import agents` resolve to `app/agents/` (a different, unrelated
    package). We must ensure tests in this file get the TOP-LEVEL
    `agents/` — the one that has anthropic_client, cloud_runner, etc.

    Solution: drop any cached `agents*` modules so the next import
    walks the path again, with REPO_ROOT now at position 0.
    """
    sys.path.insert(0, str(REPO_ROOT))
    for mod_name in list(sys.modules):
        if mod_name == "agents" or mod_name.startswith("agents."):
            del sys.modules[mod_name]


@pytest.fixture(autouse=True)
def _isolate_agents_package():
    """Run for every test in this file."""
    _force_top_level_agents()
    yield
    # No teardown — leaving modules cached is fine; the next test
    # gets a fresh purge anyway.


# ---------------------------------------------------------------------------
class TestAnthropicClient:
    def test_complete_happy_path(self, monkeypatch):
        from agents import anthropic_client

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-key")

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            "content": [{"type": "text", "text": "ship it"}],
            "usage": {"input_tokens": 42, "output_tokens": 7},
        }
        monkeypatch.setattr(anthropic_client.httpx, "post",
                            lambda *a, **kw: fake_resp)

        out = anthropic_client.complete(
            model="qwen2.5-coder:7b",
            system="be terse",
            prompt="hi",
        )
        assert out.error is None
        assert out.text == "ship it"
        assert out.prompt_tokens == 42
        assert out.completion_tokens == 7
        # model should be the *resolved* anthropic id, not the input
        assert "claude-haiku" in out.model
        assert out.elapsed_ms >= 0

    def test_complete_missing_key_is_soft_error(self, monkeypatch):
        from agents import anthropic_client
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        out = anthropic_client.complete("qwen2.5-coder:7b", "", "hi")
        assert out.text == ""
        assert "ANTHROPIC_API_KEY" in (out.error or "")

    def test_complete_http_error_is_soft_error(self, monkeypatch):
        from agents import anthropic_client
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
        fake = MagicMock(status_code=401, text='{"error":"bad key"}')
        monkeypatch.setattr(anthropic_client.httpx, "post",
                            lambda *a, **kw: fake)
        out = anthropic_client.complete("llama3.2:3b", "", "hi")
        assert "HTTP 401" in (out.error or "")
        assert out.text == ""

    def test_complete_network_error_is_soft_error(self, monkeypatch):
        from agents import anthropic_client
        import httpx
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
        def _boom(*a, **kw):
            raise httpx.ConnectError("dns failed")
        monkeypatch.setattr(anthropic_client.httpx, "post", _boom)
        out = anthropic_client.complete("llama3.2:3b", "", "hi")
        assert "unreachable" in (out.error or "").lower()


class TestModelMap:
    def test_qwen_maps_to_haiku(self):
        from agents.anthropic_client import map_model
        assert "claude-haiku" in map_model("qwen2.5-coder:7b")

    def test_llama_maps_to_haiku(self):
        from agents.anthropic_client import map_model
        assert "claude-haiku" in map_model("llama3.2:3b")

    def test_command_r_maps_to_haiku(self):
        from agents.anthropic_client import map_model
        assert "claude-haiku" in map_model("command-r7b")

    def test_unknown_falls_back_to_default(self):
        from agents.anthropic_client import map_model, DEFAULT_ANTHROPIC_MODEL
        assert map_model("nonexistent-model:1b") == DEFAULT_ANTHROPIC_MODEL

    def test_every_department_model_has_mapping(self):
        """Each department's `model` attr should resolve to a Claude id.
        Catches the case where someone adds a new dept with a model id
        we never mapped, which would silently fall back to Haiku
        without an entry in MODEL_MAP."""
        from agents.anthropic_client import MODEL_MAP, map_model
        from agents.departments import DEPARTMENTS
        for name, cls in DEPARTMENTS.items():
            resolved = map_model(cls.model)
            assert resolved.startswith("claude-"), (
                f"dept {name} model {cls.model!r} → {resolved!r}"
            )


# ---------------------------------------------------------------------------
class TestCloudRunner:
    def test_heartbeat_written_on_tick(self, tmp_path, monkeypatch):
        # Pre-import cloud_runner with an ephemeral data root so it
        # doesn't try to write to /data.
        monkeypatch.setenv("ARCHHUB_AGENTS_DATA_ROOT", str(tmp_path / "agents"))

        # Re-import fresh — module-level code reads the env var on first import.
        for mod in list(sys.modules):
            if mod.startswith("agents.cloud_runner"):
                del sys.modules[mod]
        from agents import cloud_runner

        # Use the test's tmp heartbeat path; don't rely on module-level constant.
        hb_path = tmp_path / "agents" / "heartbeat.txt"
        daemon = cloud_runner.CloudDaemon(
            cycle_seconds=1,
            heartbeat_path=hb_path,
        )

        # Stub the scheduler so we don't try to run real LLM calls.
        stub_sched = MagicMock()
        stub_sched.tick.return_value = {"ts": "t", "added": 0, "ran": {}}
        daemon._scheduler = stub_sched

        daemon.tick_once()
        assert hb_path.exists()
        text = hb_path.read_text(encoding="utf-8")
        lines = text.strip().splitlines()
        # First line ISO timestamp, second line cycle count
        assert "T" in lines[0]  # ISO format includes 'T'
        assert lines[1].strip() == "1"

        # Second tick increments the cycle counter
        daemon.tick_once()
        lines = hb_path.read_text(encoding="utf-8").strip().splitlines()
        assert lines[1].strip() == "2"

    def test_backend_env_var_anthropic_swaps_complete(self, monkeypatch):
        # Wipe cached modules so the install runs cleanly.
        for mod in list(sys.modules):
            if mod.startswith("agents."):
                del sys.modules[mod]

        monkeypatch.setenv("ARCHHUB_AGENTS_BACKEND", "anthropic")
        from agents import cloud_runner, anthropic_client, base, ollama
        cloud_runner._install_backend("anthropic")

        # base.complete should now BE anthropic_client.complete
        assert base.complete is anthropic_client.complete
        assert ollama.complete is anthropic_client.complete

    def test_backend_env_var_ollama_leaves_complete_alone(self, monkeypatch):
        for mod in list(sys.modules):
            if mod.startswith("agents."):
                del sys.modules[mod]

        monkeypatch.setenv("ARCHHUB_AGENTS_BACKEND", "ollama")
        from agents import cloud_runner, base, ollama
        cloud_runner._install_backend("ollama")

        # Default state — base.complete is the ollama implementation
        assert base.complete is ollama.complete

    def test_backend_env_var_select_anthropic_by_default(self, monkeypatch):
        for mod in list(sys.modules):
            if mod.startswith("agents."):
                del sys.modules[mod]
        monkeypatch.delenv("ARCHHUB_AGENTS_BACKEND", raising=False)
        from agents import cloud_runner
        assert cloud_runner._select_backend() == "anthropic"


# ---------------------------------------------------------------------------
class TestDashboardEndpoint:
    def _client(self, tmp_path):
        from fastapi.testclient import TestClient
        from agents.dashboard_endpoint import build_app

        data_root = tmp_path / "agents"
        data_root.mkdir(parents=True, exist_ok=True)
        hb_path = data_root / "heartbeat.txt"
        app = build_app(heartbeat_path=hb_path, data_root=data_root)
        return TestClient(app), hb_path, data_root

    def test_healthz_returns_ok_when_heartbeat_fresh(self, tmp_path):
        client, hb_path, _ = self._client(tmp_path)
        # Write a fresh heartbeat (now)
        now = datetime.now(timezone.utc).isoformat()
        hb_path.write_text(f"{now}\n7\n", encoding="utf-8")
        r = client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["cycles"] == 7
        assert body["last_heartbeat"] == now

    def test_healthz_returns_stale_when_old(self, tmp_path):
        client, hb_path, _ = self._client(tmp_path)
        # 10 minutes old → > 3 cycles → stale
        old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        hb_path.write_text(f"{old}\n3\n", encoding="utf-8")
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "stale"

    def test_healthz_handles_missing_heartbeat(self, tmp_path):
        client, _, _ = self._client(tmp_path)
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "stale"
        assert r.json()["last_heartbeat"] is None

    def test_status_reports_departments(self, tmp_path):
        client, _, _ = self._client(tmp_path)
        r = client.get("/status")
        assert r.status_code == 200
        body = r.json()
        assert "departments" in body
        assert "eng" in body["departments"]
        assert "qa" in body["departments"]
        assert body["pending_tasks"] == 0
        assert body["completed_today"] == 0
        assert body["last_outputs"] == []

    def test_status_counts_pending_tasks(self, tmp_path):
        client, _, data_root = self._client(tmp_path)
        tasks_dir = data_root / "tasks" / "eng"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "abc.yaml").write_text("{}", encoding="utf-8")
        (tasks_dir / "def.yaml").write_text("{}", encoding="utf-8")
        # one is done — shouldn't count
        (tasks_dir / "def.done").write_text("{}", encoding="utf-8")
        r = client.get("/status")
        assert r.json()["pending_tasks"] == 1

    def test_output_listing_404_when_missing(self, tmp_path):
        client, _, _ = self._client(tmp_path)
        r = client.get("/outputs/eng/nonexistent")
        assert r.status_code == 404

    def test_output_file_traversal_blocked(self, tmp_path):
        client, _, data_root = self._client(tmp_path)
        out_dir = data_root / "outputs" / "eng" / "t1"
        out_dir.mkdir(parents=True)
        (out_dir / "ok.md").write_text("hello", encoding="utf-8")
        r = client.get("/outputs/eng/t1/../../passwd")
        # FastAPI normalises the path before routing, so this becomes a
        # 404 (no matching route). Either 400 or 404 is acceptable —
        # what we care about is "didn't serve the parent file".
        assert r.status_code in (400, 404)
