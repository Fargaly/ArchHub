"""MAKE-IT-REAL (founder 2026-05-31): connect the users DB to the brain.

Two gaps closed, asserted here against REAL behavior (not "code imports"):

  1. Provision-at-login — exchange_code now provisions a per-user cloud
     brain replica + records the link on users.brain_id. Before this, signup
     only created a `users` row; the replica appeared lazily on first sync
     and brain_id did not exist. These tests assert:
       (a) after register→exchange, users.brain_id is non-null (= users.id),
       (b) BrainReplica.open(user_id) finds/created the replica dir,
       (c) /v1/me for that token returns user_id (desktop binds local brain),
       (d) a returning user (second login) does NOT duplicate or error,
       (e) the migration backfills existing users' brain_id.
     The RED-without-the-fix proof lives in TestProvisionIsLoadBearing.

  2. Fly persistence — DATABASE_URL + the replicas root resolve UNDER /data
     when running on Fly (FLY_APP_NAME / DATA_DIR), and under ./ +
     cloud_backend/data/replicas locally. TestFlyPersistencePaths asserts
     both ways so a redeploy on Fly can't wipe the DB/replicas and the local
     dev/test box is never pushed onto /data.
"""
from __future__ import annotations

import base64
import hashlib
import importlib
import os
import secrets
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def replicas_root(tmp_path, monkeypatch):
    """Isolate the per-user replica root under tmp (mirrors the brain-sync
    endpoint tests) so provisioning never scribbles under
    cloud_backend/data/replicas on the dev box."""
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


def _pkce_pair():
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _stub_email(monkeypatch):
    async def fake_send(**kw):
        return True
    import email_sender
    monkeypatch.setattr(email_sender, "send_magic_link", fake_send)


def _code_for(user_id: str) -> str:
    import db
    with db.connect() as con:
        row = con.execute(
            "SELECT code FROM codes WHERE user_id = ? "
            "ORDER BY rowid DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return row["code"]


def _register_and_exchange(client, monkeypatch, email):
    """Full register→exchange via the PKCE (desktop) path. Returns
    (user_row_before_exchange_id, token, exchange_payload)."""
    _stub_email(monkeypatch)
    import db
    verifier, challenge = _pkce_pair()
    r = client.post("/v1/auth/register",
                    json={"email": email, "code_challenge": challenge})
    assert r.status_code == 202, r.text
    u = db.get_user_by_email(email)
    code = _code_for(u["id"])
    r2 = client.post("/v1/auth/exchange",
                     json={"code": code, "code_verifier": verifier})
    assert r2.status_code == 200, r2.text
    return u["id"], r2.json()["token"], r2.json()


# ===========================================================================
# 1. Schema + migration
# ===========================================================================
class TestBrainIdColumnAndMigration:
    def test_users_table_has_brain_id_column(self):
        import db
        with db.connect() as con:
            cols = {r["name"] for r in con.execute(
                "PRAGMA table_info(users)").fetchall()}
        assert "brain_id" in cols

    def test_migration_backfills_existing_users(self):
        """An existing user whose brain_id is NULL (a pre-MAKE-IT-REAL row)
        is backfilled to brain_id = id by init_schema. Idempotent: re-running
        doesn't change an already-set value."""
        import db
        u = db.get_or_create_user("backfill@studio.com")
        # Force the row back to the pre-migration state (brain_id NULL).
        with db.connect() as con:
            con.execute("UPDATE users SET brain_id = NULL WHERE id = ?",
                        (u["id"],))
        assert db.get_user(u["id"])["brain_id"] is None
        # Re-run the migration → brain_id backfilled to the user id.
        db.init_schema()
        assert db.get_user(u["id"])["brain_id"] == u["id"]

    def test_set_user_brain_id_is_idempotent(self):
        import db
        u = db.get_or_create_user("setbid@studio.com")
        db.set_user_brain_id(u["id"], u["id"])
        assert db.get_user(u["id"])["brain_id"] == u["id"]
        # Second call with the same value is a no-op (no error, no churn).
        db.set_user_brain_id(u["id"], u["id"])
        assert db.get_user(u["id"])["brain_id"] == u["id"]


# ===========================================================================
# 2. Provision-at-login (the core MAKE-IT-REAL behavior)
# ===========================================================================
class TestProvisionAtLogin:
    def test_exchange_sets_brain_id_and_creates_replica(
            self, client, monkeypatch, replicas_root):
        """register→exchange → (a) users.brain_id non-null (= id),
        (b) the per-user replica dir + brain.db exist on disk."""
        import db
        import brain_replica
        uid, token, payload = _register_and_exchange(
            client, monkeypatch, "prov-a@studio.com")

        # (a) brain_id recorded on the users row, equal to the user id.
        row = db.get_user(uid)
        assert row["brain_id"] is not None
        assert row["brain_id"] == uid

        # (b) the replica directory + brain.db were created by open().
        user_dir = replicas_root / uid
        assert user_dir.exists(), "replica dir must exist after first login"
        assert (user_dir / "brain.db").exists(), "brain.db must exist"

        # And BrainReplica.open finds the SAME replica (idempotent open).
        replica = brain_replica.BrainReplica.open(uid)
        assert replica.user_id == uid
        assert replica.db_path == user_dir / "brain.db"

    def test_me_returns_user_id(self, client, monkeypatch):
        """The desktop needs users.id from /v1/me to bind its local brain to
        the account. Confirm /v1/me surfaces user_id (and brain_id)."""
        uid, token, _ = _register_and_exchange(
            client, monkeypatch, "prov-me@studio.com")
        r = client.get("/v1/me",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user_id"] == uid
        assert body["brain_id"] == uid
        # Existing fields still present (additive change).
        assert body["email"] == "prov-me@studio.com"
        assert body["plan"] == "trial"

    def test_returning_user_does_not_duplicate(
            self, client, monkeypatch, replicas_root):
        """A second login for the same email re-opens the existing replica
        without erroring or minting a second directory; brain_id stays put."""
        import db
        _stub_email(monkeypatch)
        verifier, challenge = _pkce_pair()
        email = "prov-return@studio.com"

        # First login.
        client.post("/v1/auth/register",
                    json={"email": email, "code_challenge": challenge})
        uid = db.get_user_by_email(email)["id"]
        code1 = _code_for(uid)
        client.post("/v1/auth/exchange",
                    json={"code": code1, "code_verifier": verifier})
        assert db.get_user(uid)["brain_id"] == uid
        assert (replicas_root / uid).exists()

        # Second login (returning user).
        client.post("/v1/auth/register",
                    json={"email": email, "code_challenge": challenge})
        code2 = _code_for(uid)
        r2 = client.post("/v1/auth/exchange",
                         json={"code": code2, "code_verifier": verifier})
        assert r2.status_code == 200

        # Same user id, same brain_id, exactly ONE replica dir for them.
        assert db.get_user_by_email(email)["id"] == uid
        assert db.get_user(uid)["brain_id"] == uid
        matching = [p for p in replicas_root.iterdir() if p.name == uid]
        assert len(matching) == 1

    def test_provision_brain_helper_is_idempotent(
            self, replicas_root):
        """auth.provision_brain called twice for one user → same brain_id,
        one replica dir, no exception."""
        import auth
        import db
        u = db.get_or_create_user("prov-helper@studio.com")
        bid1 = auth.provision_brain(u["id"])
        bid2 = auth.provision_brain(u["id"])
        assert bid1 == u["id"]
        assert bid2 == u["id"]
        assert db.get_user(u["id"])["brain_id"] == u["id"]
        matching = [p for p in replicas_root.iterdir() if p.name == u["id"]]
        assert len(matching) == 1


# ===========================================================================
# 3. RED-without-the-fix proof
# ===========================================================================
class TestProvisionIsLoadBearing:
    """Prove the brain_id assertion in TestProvisionAtLogin actually depends
    on the provision call inside exchange_code — i.e. it would FAIL if the
    provisioning were removed.

    We can't comment out source in a test, so we simulate "the provision
    call is gone" by neutering auth.provision_brain to a no-op, then run the
    same register→exchange and assert that brain_id is now NOT set + the
    replica dir is NOT created. If exchange_code provisioned via some OTHER
    path (or the assertion were vacuous), this test would fail — so its
    passing demonstrates the provision call is the load-bearing wire.
    """

    def test_brain_id_unset_when_provision_neutered(
            self, client, monkeypatch, replicas_root):
        import db
        import auth

        # Neuter the provisioning the same way deleting the call would: no
        # replica created, brain_id never stamped at exchange time.
        monkeypatch.setattr(auth, "provision_brain", lambda user_id: None)

        _stub_email(monkeypatch)
        verifier, challenge = _pkce_pair()
        email = "prov-red@studio.com"
        client.post("/v1/auth/register",
                    json={"email": email, "code_challenge": challenge})
        uid = db.get_user_by_email(email)["id"]
        # Defensive: clear any brain_id the get_or_create path might carry
        # (it doesn't set one, but make the precondition explicit).
        with db.connect() as con:
            con.execute("UPDATE users SET brain_id = NULL WHERE id = ?",
                        (uid,))
        code = _code_for(uid)
        r = client.post("/v1/auth/exchange",
                        json={"code": code, "code_verifier": verifier})
        assert r.status_code == 200, r.text  # sign-in still works...

        # ...but WITHOUT provisioning, brain_id stays NULL + no replica dir.
        assert db.get_user(uid)["brain_id"] is None, (
            "brain_id must be NULL when provision is neutered — proves the "
            "green test depends on the provision call")
        assert not (replicas_root / uid).exists(), (
            "no replica dir should exist when provision is neutered")

    def test_same_flow_with_provision_intact_sets_brain_id(
            self, client, monkeypatch, replicas_root):
        """Control: the identical flow WITH provisioning intact sets brain_id
        + creates the dir — the pair of tests brackets the behavior."""
        import db
        uid, _, _ = _register_and_exchange(
            client, monkeypatch, "prov-green@studio.com")
        assert db.get_user(uid)["brain_id"] == uid
        assert (replicas_root / uid).exists()


# ===========================================================================
# 4. Fly persistence path resolution
# ===========================================================================
class TestFlyPersistencePaths:
    """DATABASE_URL + replicas root must live under /data on Fly and under
    ./ + cloud_backend/data/replicas locally. Reloads config under different
    env to assert the resolution both ways.

    NOTE: these tests reload `config` with custom env; the autouse
    _isolate_db conftest fixture re-points DATABASE_URL afterward for other
    tests, but we restore via monkeypatch's automatic teardown + a final
    reload so nothing leaks.
    """

    @staticmethod
    def _norm(p) -> str:
        return str(p).replace("\\", "/")

    def _reload_config(self, monkeypatch, env: dict):
        # Clear every var that participates in resolution, then set the ones
        # this scenario wants.
        for k in ("FLY_APP_NAME", "FLY_MACHINE_ID", "DATA_DIR",
                  "DATABASE_URL", "REPLICAS_ROOT", "ENV"):
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        import config
        importlib.reload(config)
        return config

    def test_local_paths_when_no_fly_env(self, monkeypatch):
        cfg = self._reload_config(monkeypatch, {})
        try:
            assert cfg.DATABASE_URL == "./archhub_cloud.db"
            # Replicas under cloud_backend/data/replicas.
            assert self._norm(cfg.REPLICAS_ROOT).endswith(
                "cloud_backend/data/replicas")
            # DATA_DIR is the backend dir locally, never /data.
            assert self._norm(cfg.DATA_DIR) != "/data"
        finally:
            importlib.reload(cfg)

    def test_fly_paths_under_data_volume(self, monkeypatch):
        cfg = self._reload_config(monkeypatch,
                                  {"FLY_APP_NAME": "archhub-cloud"})
        try:
            assert self._norm(cfg.DATABASE_URL) == "/data/archhub_cloud.db"
            assert self._norm(cfg.REPLICAS_ROOT) == "/data/replicas"
            assert self._norm(cfg.DATA_DIR) == "/data"
        finally:
            importlib.reload(cfg)

    def test_fly_machine_id_also_triggers_data_volume(self, monkeypatch):
        """Either Fly env var is sufficient (machines that expose only
        FLY_MACHINE_ID still persist to /data)."""
        cfg = self._reload_config(monkeypatch,
                                  {"FLY_MACHINE_ID": "abc123"})
        try:
            assert self._norm(cfg.DATABASE_URL) == "/data/archhub_cloud.db"
            assert self._norm(cfg.REPLICAS_ROOT) == "/data/replicas"
        finally:
            importlib.reload(cfg)

    def test_explicit_data_dir_overrides(self, monkeypatch):
        """DATA_DIR points the persistent dir anywhere (used for a custom
        mount) even without Fly env."""
        cfg = self._reload_config(monkeypatch,
                                  {"DATA_DIR": "/mnt/persist"})
        try:
            assert self._norm(cfg.DATABASE_URL) == "/mnt/persist/archhub_cloud.db"
            assert self._norm(cfg.REPLICAS_ROOT) == "/mnt/persist/replicas"
        finally:
            importlib.reload(cfg)

    def test_explicit_database_url_wins_even_on_fly(self, monkeypatch):
        """An operator-set DATABASE_URL always wins (the test-suite relies on
        this precedence too)."""
        cfg = self._reload_config(monkeypatch, {
            "FLY_APP_NAME": "archhub-cloud",
            "DATABASE_URL": "/data/custom-name.db",
        })
        try:
            assert self._norm(cfg.DATABASE_URL) == "/data/custom-name.db"
        finally:
            importlib.reload(cfg)
