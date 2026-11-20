"""Behavioral tests for QUOTACONTINUITY: quota-resilient work handover, stalled reaping,
coordinator seat failover, and Retry-After / fallback model failover."""
from __future__ import annotations

import io
import json
import time
import urllib.error
from email.message import Message
from pathlib import Path

from nodelang import model_router, settings_owner, workshop_mailbox, workshop_tasks
from nodelang.session_files import read_document


def _open_history(tmp_path: Path):
    return workshop_mailbox.application_history(database=tmp_path / "workshop.sqlite")


def _fake_json_response(payload: dict):
    raw = json.dumps(payload).encode("utf-8")

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, n=-1):
            return raw

        @property
        def headers(self):
            return Message()

    return _Resp()


def test_release_persists_handover_and_second_agent_claims(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_STATE_DIR", str(tmp_path / "state"))
    with _open_history(tmp_path) as history:
        task = workshop_tasks.create(history, "Quota handover task", "agent-a")
        assert workshop_tasks.claim(history, task["id"], "agent-a", "Agent A", lease_seconds=120)

        handover = {
            "summary": "Implemented parser step 1",
            "next_step": "Wire validator in step 2",
            "files_touched": ["01.APP/nodelang/workshop_tasks.py"],
            "blocker": "Agent A hit 429 quota",
            "resume_prompt": "Continue from validator wiring",
            "updated_at": "2026-11-20T05:30:00Z",
        }
        assert workshop_tasks.release(history, task["id"], "agent-a", reason="quota", handover=handover)

        row = workshop_tasks.get(history, task["id"])
        assert row["status"] == "open"
        assert row["owner"] is None

        # Verify activity recorded reason="quota"
        act = history._db.execute(
            "SELECT actor, action, target, detail FROM workshop_activity WHERE action='release' AND target=?",
            (task["id"],),
        ).fetchone()
        assert act is not None
        assert act[0] == "agent-a"
        assert json.loads(act[3])["reason"] == "quota"

        # Second agent atomically claims and reads exact handover snapshot from .archhub
        assert workshop_tasks.claim(history, task["id"], "agent-b", "Agent B", lease_seconds=120)
        claimed = workshop_tasks.get(history, task["id"])
        assert claimed["owner"] == "agent-b"
        doc = read_document(claimed["session_path"])
        saved_handover = doc["properties"]["taskContext"]["handover"]
        assert saved_handover == handover


def test_reap_stalled_lease_expired_and_quota_exhausted_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_STATE_DIR", str(tmp_path / "state"))
    with _open_history(tmp_path) as history:
        t_expired = workshop_tasks.create(history, "Expired lease task", "agent-a")
        t_quota = workshop_tasks.create(history, "Quota exhausted task", "agent-b")
        assert workshop_tasks.claim(history, t_expired["id"], "agent-a", "Agent A", lease_seconds=60)
        assert workshop_tasks.claim(history, t_quota["id"], "agent-b", "Agent B", lease_seconds=300)

        # Force t_expired lease into the past
        past = time.time() - 10
        with history._transaction(write=True):
            history._db.execute(
                "UPDATE workshop_tasks SET lease_until=? WHERE id=?",
                (past, t_expired["id"]),
            )

        released = workshop_tasks.reap_stalled(
            history,
            now=time.time(),
            quota_fn=lambda owner: owner == "agent-b",
        )
        by_id = {item["id"]: item for item in released}
        assert set(by_id) == {t_expired["id"], t_quota["id"]}
        assert by_id[t_expired["id"]]["reason"] == "lease_expired"
        assert by_id[t_expired["id"]]["previous_owner"] == "agent-a"
        assert by_id[t_quota["id"]]["reason"] == "quota_exhausted"
        assert by_id[t_quota["id"]]["previous_owner"] == "agent-b"

        # Both tasks are open with no owner
        for tid in (t_expired["id"], t_quota["id"]):
            row = workshop_tasks.get(history, tid)
            assert row["status"] == "open"
            assert row["owner"] is None

        # Handover activity rows logged
        acts = history._db.execute(
            "SELECT target, detail FROM workshop_activity WHERE action='handover'"
        ).fetchall()
        assert len(acts) == 2

        # Idempotent on repeat call
        again = workshop_tasks.reap_stalled(
            history,
            now=time.time(),
            quota_fn=lambda owner: owner == "agent-b",
        )
        assert again == []


def test_seat_coordinator_failover_resolves_new_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_STATE_DIR", str(tmp_path / "state"))
    with _open_history(tmp_path) as history:
        declarations = [
            {"current": True, "runtime": "gemini", "session": "gemini-sess-1", "native_session_id": "gem-1", "agent": "Gemini"},
            {"current": True, "runtime": "codex", "session": "codex-sess-2", "native_session_id": "cdx-2", "agent": "Codex"},
        ]
        injection = workshop_mailbox.WorkshopInjection(owner="test", transport=None)

        # Agent A (Gemini) claims seat-coordinator
        assert workshop_tasks.claim_coordinator_seat(history, "gemini-sess-1", "Gemini", lease_seconds=120)
        # While live, Agent B cannot steal it
        assert not workshop_tasks.claim_coordinator_seat(history, "codex-sess-2", "Codex", lease_seconds=120)
        resolved_a = injection._coordinator(declarations, history=history)
        assert len(resolved_a) == 1 and resolved_a[0]["session"] == "gemini-sess-1"

        # Agent A releases on quota -> Agent B claims seat-coordinator
        assert workshop_tasks.release(history, workshop_tasks.COORDINATOR_SEAT_ID, "gemini-sess-1", reason="quota")
        assert workshop_tasks.claim_coordinator_seat(history, "codex-sess-2", "Codex", lease_seconds=120)
        resolved_b = injection._coordinator(declarations, history=history)
        assert len(resolved_b) == 1 and resolved_b[0]["session"] == "codex-sess-2"


def test_router_mixed_fallbacks_retry_after_and_failover(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_STATE_DIR", str(tmp_path / "state"))
    model_router._UNAVAILABLE_UNTIL.clear()

    # Settings owner allows ordered free + non-free fallback_models while keeping free_first=True
    defaults = settings_owner.read_router_settings()
    mixed = {
        **defaults,
        "free_first": True,
        "fallback_models": [
            "openrouter/qwen/qwen3-coder:free",
            "openrouter/openai/gpt-4o-mini",
        ],
    }
    checked = settings_owner._checked_router_settings(mixed)
    assert checked["free_first"] is True
    assert checked["fallback_models"] == [
        "openrouter/qwen/qwen3-coder:free",
        "openrouter/openai/gpt-4o-mini",
    ]

    # Route 1 returns HTTP 429 with Retry-After: 45; route 2 answers cleanly
    called_models: list[str] = []

    def fake_any_llm_chat(attempt, rows, **kwargs):
        called_models.append(attempt.model)
        if attempt.model == "qwen/qwen3-coder:free":
            hdrs = Message()
            hdrs["Retry-After"] = "45"
            raise urllib.error.HTTPError(
                attempt.url,
                429,
                "Too Many Requests",
                hdrs,
                io.BytesIO(b'{"error":{"message":"rate limited","code":429}}'),
            )
        return {
            "model": attempt.model,
            "choices": [{"finish_reason": "stop", "message": {"content": "ok from fallback"}}],
            "usage": {"total_tokens": 12},
        }

    monkeypatch.setattr(model_router, "_any_llm_chat", fake_any_llm_chat)

    result = model_router.route_chat(
        "openrouter/qwen/qwen3-coder:free",
        [{"role": "user", "content": "hello"}],
        free_only=False,
        fallback_routes=["openrouter/openai/gpt-4o-mini"],
        environ={"OPENROUTER_API_KEY": "sk-or-v1-" + "x" * 32},
    )
    assert result["text"] == "ok from fallback"
    assert called_models == ["qwen/qwen3-coder:free", "openai/gpt-4o-mini"]
    assert model_router._temporarily_unavailable("openrouter", "qwen/qwen3-coder:free")

    # Second call immediately skips the cooled-down route and hits the healthy fallback directly
    called_models.clear()
    result2 = model_router.route_chat(
        "openrouter/qwen/qwen3-coder:free",
        [{"role": "user", "content": "hello again"}],
        free_only=False,
        fallback_routes=["openrouter/openai/gpt-4o-mini"],
        environ={"OPENROUTER_API_KEY": "sk-or-v1-" + "x" * 32},
    )
    assert result2["text"] == "ok from fallback"
    assert called_models == ["openai/gpt-4o-mini"]


def test_reap_stalled_covers_declared_subtasks_coordinator_and_alive_fn(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_STATE_DIR", str(tmp_path / "state"))
    with _open_history(tmp_path) as history:
        now_iso = "2026-11-20T05:00:00Z"
        past = time.time() - 30
        # 1. subtask
        parent = workshop_tasks.create(history, "Parent Task", "agent-p")
        sub = workshop_tasks.create(history, "Subtask", "agent-sub", parent=parent["id"])
        assert workshop_tasks.claim(history, sub["id"], "agent-sub", "Agent Sub", lease_seconds=300)
        # 2. seat-coordinator
        assert workshop_tasks.claim_coordinator_seat(history, "agent-coord", "Coord", lease_seconds=60)
        # 3. declared-* task (inserted after claim_coordinator_seat so it is reaped by the call below)
        with history._transaction(write=True):
            history._db.execute(
                "INSERT INTO workshop_tasks(id, title, status, owner, owner_label, lease_until, created_by, created_at, updated_at) "
                "VALUES('declared-lane-1', 'Declared Lane', 'claimed', 'agent-dec', 'Agent Dec', ?, 'system', ?, ?)",
                (past, now_iso, now_iso),
            )
            history._db.execute(
                "UPDATE workshop_tasks SET lease_until=? WHERE id=?",
                (past, workshop_tasks.COORDINATOR_SEAT_ID),
            )

        released = workshop_tasks.reap_stalled(
            history,
            now=time.time(),
            alive_fn=lambda owner: owner != "agent-sub",
        )
        by_id = {item["id"]: item for item in released}
        assert "declared-lane-1" in by_id and by_id["declared-lane-1"]["reason"] == "lease_expired"
        assert sub["id"] in by_id and by_id[sub["id"]]["reason"] == "owner_dead"
        assert workshop_tasks.COORDINATOR_SEAT_ID in by_id and by_id[workshop_tasks.COORDINATOR_SEAT_ID]["reason"] == "lease_expired"

        for tid in ("declared-lane-1", sub["id"], workshop_tasks.COORDINATOR_SEAT_ID):
            row = workshop_tasks.get(history, tid)
            assert row["status"] == "open"
            assert row["owner"] is None


def test_composer_chat_mixed_fallbacks_cross_family_key_and_refused_failover(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_STATE_DIR", str(tmp_path / "state"))
    model_router._UNAVAILABLE_UNTIL.clear()

    defaults = settings_owner.read_router_settings()
    mixed_settings = {
        **defaults,
        "default_model": "openrouter/qwen/qwen3-coder:free",
        "free_first": True,
        "fallback_models": ["openai-api/gpt-4o-mini"],
    }
    monkeypatch.setattr(settings_owner, "read_router_settings", lambda: mixed_settings)
    monkeypatch.setattr(model_router, "request_profiles", lambda record: None)
    monkeypatch.setattr("nodelang.agent_budget.paused", lambda agent: False)

    seen_calls: list[tuple[str, str, str | None]] = []

    def fake_discover_key(family, **kwargs):
        return (f"key-for-{family}", "test")

    def fake_any_llm_chat(attempt, rows, **kwargs):
        seen_calls.append((attempt.family, attempt.model, kwargs.get("api_key")))
        if attempt.family == "openrouter":
            raise model_router.ModelRouteRefused("rate limited", reason_code="provider_rate_limited")
        return {
            "model": attempt.model,
            "choices": [{"finish_reason": "stop", "message": {"content": "answered by openai fallback"}}],
            "usage": {"total_tokens": 15},
        }

    monkeypatch.setattr(model_router, "discover_key", fake_discover_key)
    monkeypatch.setattr(model_router, "_any_llm_chat", fake_any_llm_chat)

    res = model_router.composer_chat({"prompt": "hi", "agent": "BABOOM"})
    assert res["ok"] is True
    assert res["answer"] == "answered by openai fallback"
    assert seen_calls == [
        ("openrouter", "qwen/qwen3-coder:free", "key-for-openrouter"),
        ("openai", "gpt-4o-mini", "key-for-openai"),
    ]


def test_release_handover_sanitizes_secrets_and_paths_and_rejects_invalid_before_release(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_STATE_DIR", str(tmp_path / "state"))
    with _open_history(tmp_path) as history:
        task = workshop_tasks.create(history, "Sanitize handover task", "agent-a")
        assert workshop_tasks.claim(history, task["id"], "agent-a", "Agent A", lease_seconds=120)

        # Invalid handover key must raise ValueError and leave task still claimed!
        import pytest
        with pytest.raises(ValueError):
            workshop_tasks.release(
                history,
                task["id"],
                "agent-a",
                reason="quota",
                handover={"unknown_field": "bad"},
            )
        still_claimed = workshop_tasks.get(history, task["id"])
        assert still_claimed["status"] == "claimed"
        assert still_claimed["owner"] == "agent-a"

        # Valid handover with secret + absolute path gets sanitized
        handover = {
            "summary": "Used key " + "sk-or-v1-" + ("1234567890abcdef" * 2) + " at C:\\Users\\fargaly\\secret.txt",
            "next_step": "Continue safely",
        }
        assert workshop_tasks.release(history, task["id"], "agent-a", reason="quota", handover=handover)
        doc = read_document(still_claimed["session_path"])
        saved = doc["properties"]["taskContext"]["handover"]
        assert ("sk-or-v1-" + ("1234567890abcdef" * 2)) not in saved["summary"]
        assert "C:\\Users\\fargaly\\secret.txt" not in saved["summary"]
        assert saved["next_step"] == "Continue safely"

