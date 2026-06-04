"""Dedicated tests for the personal (USER-scope) cross-device cloud sync.

PersonalCloudSync + cloud_config shipped with ZERO dedicated tests (flagged by
the cross-device-sync verify, founder 2026-06-02). This closes that gap:

  1. cloud_config resolution (missing/corrupt/empty file -> signed-out without
     raising; env overrides file; token-only file -> default url).
  2. tick() inert when signed-out (no token -> inert, ok, no errors, no network).
  3. tick() degrades on a dead cloud (network error -> ok False, error_count++,
     logged) and preserves the local USER fragment.
  4. The secret-redaction guarantee: a bare secret never reaches the outbound
     payload; op:// references survive verbatim.
  5. Round-trip apply: a merged fact + skill are written with USER scope+owner,
     and a second tick is idempotent (applied 0).

No worker threads are started (tick() is driven synchronously); stores are
closed. conftest autouse fixtures drain _SUPERVISORS + sever real LLM keys.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pytest

from personal_brain import personal_cloud_sync as P
from personal_brain.cloud_config import (
    DEFAULT_CLOUD_BASE_URL,
    CloudConfig,
    load_cloud_config,
)
from personal_brain.models import (
    Confidence,
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Visibility,
)
from personal_brain.storage import BrainStore


def _store() -> BrainStore:
    return BrainStore.open(":memory:")


def _user_fragment(fid: str, text: str, owner: str = "u_test") -> Fragment:
    return Fragment(
        id=fid, kind=FragmentKind.FACT, text=text,
        scope=Scope.USER, visibility=Visibility.PRIVATE, owner_user=owner,
        confidence=Confidence.EXTRACTED,
        provenance=Provenance(
            contributing_agent="test", contributing_user=owner,
            created_at=datetime.now(timezone.utc),
        ),
    )


@pytest.fixture(autouse=True)
def _isolate_cloud_env(monkeypatch):
    """Personal-sync config reads ARCHHUB_CLOUD_URL/TOKEN from env — clear them
    so each test's file/default resolution is deterministic + hermetic."""
    monkeypatch.delenv("ARCHHUB_CLOUD_URL", raising=False)
    monkeypatch.delenv("ARCHHUB_CLOUD_TOKEN", raising=False)
    yield


# ─────────────────── 1. cloud_config resolution ─────────────────────

def test_missing_file_is_signed_out(tmp_path):
    cfg = load_cloud_config(tmp_path / "nope.json")
    assert cfg.is_signed_in is False
    assert cfg.token == ""
    assert cfg.base_url == DEFAULT_CLOUD_BASE_URL


def test_corrupt_file_is_signed_out_without_raising(tmp_path):
    p = tmp_path / "cloud.json"
    p.write_text("{ this is not json", encoding="utf-8")
    cfg = load_cloud_config(p)  # must NOT raise
    assert cfg.is_signed_in is False


def test_empty_file_is_signed_out(tmp_path):
    p = tmp_path / "cloud.json"
    p.write_text("{}", encoding="utf-8")
    assert load_cloud_config(p).is_signed_in is False


def test_token_only_file_yields_default_url(tmp_path):
    p = tmp_path / "cloud.json"
    p.write_text(json.dumps({"token": "tok-abc"}), encoding="utf-8")
    cfg = load_cloud_config(p)
    assert cfg.is_signed_in is True
    assert cfg.token == "tok-abc"
    assert cfg.base_url == DEFAULT_CLOUD_BASE_URL
    assert cfg.url_source == "default"


def test_env_overrides_file(tmp_path, monkeypatch):
    p = tmp_path / "cloud.json"
    p.write_text(json.dumps({"token": "file-tok",
                             "cloud_base_url": "http://from-file"}), encoding="utf-8")
    monkeypatch.setenv("ARCHHUB_CLOUD_TOKEN", "env-tok")
    monkeypatch.setenv("ARCHHUB_CLOUD_URL", "http://from-env")
    cfg = load_cloud_config(p)
    assert cfg.token == "env-tok" and cfg.token_source == "env"
    assert cfg.base_url == "http://from-env" and cfg.url_source == "env"


# ─────────────────── 2. inert when signed-out ───────────────────────

def test_tick_is_inert_without_token(tmp_path):
    s = _store()
    try:
        sync = P.PersonalCloudSync(
            s, owner_user="u_test",
            config_loader=lambda: load_cloud_config(tmp_path / "cloud.json"),
        )
        t0 = time.perf_counter()
        res = sync.tick()
        assert res.inert is True
        assert res.ok is True
        assert sync._error_count == 0
        assert (time.perf_counter() - t0) < 1.0  # no network
    finally:
        s.close()


# ─────────────────── 3. degrade on dead cloud ───────────────────────

def test_tick_degrades_on_dead_cloud_and_preserves_local(tmp_path):
    s = _store()
    try:
        s.write_fragment(_user_fragment("local1", "my local fact", owner="u_test"))
        logs: list[str] = []
        cfg = CloudConfig(token="tok", base_url="http://127.0.0.1:1")  # dead port
        sync = P.PersonalCloudSync(
            s, owner_user="u_test", config=cfg,
            http_timeout_s=2.0, logger=logs.append,
        )
        res = sync.tick()
        assert res.ok is False
        assert res.inert is False
        assert res.error
        assert sync._error_count == 1
        assert any(("degraded" in m.lower()) or ("network" in m.lower()) for m in logs), logs
        # local data untouched by a failed sync
        assert s.get_fragment("local1") is not None
    finally:
        s.close()


# ─────────────────── 4. secret never leaves ─────────────────────────

def test_secret_never_in_outbound_payload(monkeypatch):
    s = _store()
    try:
        # Split prefix from body so the SOURCE has no contiguous provider-format
        # token (GitHub push-protection); the joined value is byte-identical.
        SECRET = "sk-ant-api03-" + "ABCDEFGHIJKLMNOP1234567890qrstuvWX"
        REF = "op://vault/openai/key"
        s.write_fragment(_user_fragment("hassecret", f"prod key is {SECRET} use it"))
        s.write_fragment(_user_fragment("hasref", f"resolve via {REF} at runtime"))

        captured: dict = {}

        def fake_post(url, payload, headers, *, timeout_s):
            captured["payload"] = payload
            return {"accepted": 0, "rejected": [],
                    "merged": {"fragments": [], "new_hlc": ""}, "new_hlc": ""}

        monkeypatch.setattr(P, "_http_post_json", fake_post)
        sync = P.PersonalCloudSync(
            s, owner_user="u_test",
            config=CloudConfig(token="tok", base_url="http://cloud.test"),
        )
        sync.tick()

        blob = json.dumps(captured["payload"])
        assert SECRET not in blob, "raw secret leaked into the outbound payload"
        assert REF in blob, "op:// reference must survive verbatim"
    finally:
        s.close()


# ─────────────────── 5. round-trip apply + idempotency ──────────────

def test_apply_merged_writes_user_scope_and_is_idempotent(monkeypatch):
    s = _store()
    owner = "u_test"
    try:
        remote_frag = {
            "id": "r_fact", "kind": "fact", "text": "a fact from another device",
            "hlc": "0000000000000002.deadbeef",
        }
        skill_payload = {
            "id": "r_skill",
            "name": "remote_skill",
            "description": (
                "A remote personal skill pulled from the cloud during cross-device "
                "sync; exists only to verify _apply_merged reconstructs skills with "
                "USER scope and the signed-in owner."
            ),
            "body": "Step 1: do the thing. Step 2: confirm it worked.",
            "triggers": ["when converging devices"],
            "owner_user": owner,
            "provenance": {
                "contributing_agent": "test", "contributing_user": owner,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        remote_skill = {
            "id": "r_skill", "kind": "skill",
            "hlc": "0000000000000003.cafebabe",
            "extra": {"skill": skill_payload},
        }

        def fake_post(url, payload, headers, *, timeout_s):
            return {
                "accepted": len(payload["delta"]["fragments"]),
                "rejected": [],
                "merged": {"fragments": [remote_frag, remote_skill],
                           "new_hlc": "0000000000000003.cafebabe"},
                "new_hlc": "0000000000000003.cafebabe",
            }

        monkeypatch.setattr(P, "_http_post_json", fake_post)
        sync = P.PersonalCloudSync(
            s, owner_user=owner,
            config=CloudConfig(token="tok", base_url="http://cloud.test"),
        )

        r1 = sync.tick()
        assert r1.ok is True
        assert r1.applied_to_local == 2, r1

        got = s.get_fragment("r_fact")
        assert got is not None
        assert got.scope == Scope.USER
        assert got.owner_user == owner

        skill = s.get_skill("r_skill")
        assert skill is not None
        assert skill.scope == Scope.USER
        assert skill.owner_user == owner

        # second tick: same merged response, nothing new written
        r2 = sync.tick()
        assert r2.applied_to_local == 0, "apply must be idempotent"
    finally:
        s.close()
