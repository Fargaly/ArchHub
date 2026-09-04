"""A community key named on the wire is a claim; a membership the cloud verified
from the owner's signed join-code is what gates the shared community replica."""
from __future__ import annotations

import base64
import json
import sys
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT.parent / "personal-brain-mcp" / "src"))

from community_join import REQUIRED, _payload_bytes, verify_join_code  # noqa: E402


def _envelope(community_id: str, *, ttl: float = 3600.0, priv: str | None = None, pub: str | None = None) -> tuple[str, str]:
    """A join-code exactly as the brain issues it (same payload bytes, same signer)."""
    from personal_brain.firm import _generate_keypair, _sign
    if priv is None:
        priv, pub = _generate_keypair()
    now = time.time()
    data = {"community_id": community_id, "name": "Court", "owner_pub": pub, "role": "member",
            "transport": {}, "issued_by": "owner-device", "issued_at": now,
            "expires_at": now + ttl, "nonce": uuid.uuid4().hex[:12]}
    assert set(data) == set(REQUIRED)
    payload = _payload_bytes(data)
    sig = _sign(priv, payload)
    return base64.urlsafe_b64encode(payload).decode() + "." + sig, pub


def test_verifier_accepts_the_brains_own_signature_and_rejects_tampering():
    env, pub = _envelope("c-1")
    payload, reason = verify_join_code(env)
    assert reason == "ok" and payload["community_id"] == "c-1" and payload["owner_pub"] == pub
    body, sig = env.split(".", 1)
    forged = json.loads(base64.urlsafe_b64decode(body.encode()))
    forged["community_id"] = "c-2"
    forged_env = base64.urlsafe_b64encode(json.dumps(forged, sort_keys=True, separators=(",", ":")).encode()).decode() + "." + sig
    assert verify_join_code(forged_env)[1] == "signature mismatch"
    expired, _ = _envelope("c-3", ttl=-5)
    assert verify_join_code(expired)[1] == "expired"
    assert verify_join_code("garbage")[0] is None


@pytest.fixture
def replicas_root(tmp_path, monkeypatch):
    import brain_replica
    root = tmp_path / "replicas"
    root.mkdir()
    monkeypatch.setattr(brain_replica, "DEFAULT_REPLICAS_ROOT", root)
    return root


@pytest.fixture
def client(replicas_root):
    import main
    with TestClient(main.app) as c:
        yield c


def _user(suffix):
    import db
    u = db.get_or_create_user(f"member+{suffix}-{uuid.uuid4().hex[:6]}@example.com")
    return u, {"Authorization": f"Bearer {db.issue_token(u['id'])}"}


def _community_fragment(community_id, text):
    # Same shape the desktop brain pushes: the community id rides in `extra`.
    return {"id": "frag-" + uuid.uuid4().hex[:8], "kind": "fact", "text": text, "scope": "community",
            "hlc": "0000000000000001.aaaaaaaa", "extra": {"community_id": community_id}}


def test_a_guessed_community_id_cannot_be_written_or_read(client):
    _, h = _user("stranger")
    r = client.post("/v1/brain/sync", headers=h, json={"delta": {"fragments": [_community_fragment("secret-club", "poison")]},
                                                       "community_keys": ["secret-club"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["community_keys"] == []
    assert any("not a member" in (x.get("reason") or "") for x in out["rejected"]), out["rejected"]


def test_a_verified_join_code_opens_the_community_for_that_user(client):
    env, _pub = _envelope("open-house")
    u1, h1 = _user("a")
    u2, h2 = _user("b")
    assert client.post("/v1/community/join", headers=h1, json={"envelope": env}).json()["community_keys"] == ["open-house"]
    assert client.post("/v1/community/join", headers=h2, json={"envelope": env}).json()["joined"] is True
    r = client.post("/v1/brain/sync", headers=h1, json={"delta": {"fragments": [_community_fragment("open-house", "hello members")]}})
    assert r.status_code == 200 and r.json()["community_keys"] == ["open-house"], r.text
    assert not r.json()["rejected"], r.json()["rejected"]
    r2 = client.post("/v1/brain/sync", headers=h2, json={"delta": {"fragments": []}})
    texts = json.dumps(r2.json().get("merged") or {})
    assert "hello members" in texts
    bad = client.post("/v1/community/join", headers=h2, json={"envelope": "nope"})
    assert bad.status_code == 400
