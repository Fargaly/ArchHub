"""Court: every account is a member of the Community Brain from first sign-in.

Founder decision 2026-09-29: auto-join, shared by default. provision_brain
already runs at every exchange_code; it now also records the default community
membership that main._community_keys_for_user reads, so the first
/v1/brain/sync already carries the community key. Idempotent, and an empty
ARCHHUB_DEFAULT_COMMUNITY_ID turns it off.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture
def replicas_root(tmp_path, monkeypatch):
    import brain_replica
    root = tmp_path / "replicas"
    root.mkdir()
    monkeypatch.setattr(brain_replica, "DEFAULT_REPLICAS_ROOT", root)
    monkeypatch.delenv("ARCHHUB_DEFAULT_COMMUNITY_ID", raising=False)
    return root


def test_a_new_account_is_a_member_of_the_default_community(replicas_root):
    import auth
    import db
    import main
    user = db.get_or_create_user("community-join@studio.com")
    assert auth.provision_brain(user["id"]) == user["id"]
    assert main._community_keys_for_user(user) == ["archhub-community"]


def test_signing_in_again_keeps_one_membership(replicas_root):
    import auth
    import db
    user = db.get_or_create_user("community-again@studio.com")
    auth.provision_brain(user["id"])
    auth.provision_brain(user["id"])
    assert db.list_community_keys_for_user(user["id"]) == ["archhub-community"]


def test_an_empty_setting_turns_the_auto_join_off(replicas_root, monkeypatch):
    import auth
    import db
    monkeypatch.setenv("ARCHHUB_DEFAULT_COMMUNITY_ID", "")
    user = db.get_or_create_user("community-off@studio.com")
    assert auth.provision_brain(user["id"]) == user["id"]
    assert db.list_community_keys_for_user(user["id"]) == []

def test_turning_the_auto_join_off_ends_the_default_membership(replicas_root, monkeypatch):
    import auth
    import db
    user = db.get_or_create_user("community-leaves@studio.com")
    auth.provision_brain(user["id"])
    monkeypatch.setenv("ARCHHUB_DEFAULT_COMMUNITY_ID", "")
    auth.provision_brain(user["id"])
    assert db.list_community_keys_for_user(user["id"]) == []


def test_a_member_can_leave(replicas_root):
    import auth
    import db
    import main
    from fastapi.testclient import TestClient
    user = db.get_or_create_user("community-leave-route@studio.com")
    auth.provision_brain(user["id"])
    headers = {"Authorization": "Bearer " + db.issue_token(user["id"])}
    with TestClient(main.app) as client:
        left = client.post("/v1/community/leave", headers=headers, json={"community_id": "archhub-community"})
    assert left.status_code == 200 and left.json() == {"ok": True, "left": True}
    assert db.list_community_keys_for_user(user["id"]) == []

def test_leaving_sticks_across_sign_ins(replicas_root):
    import auth
    import db
    import main
    from fastapi.testclient import TestClient
    user = db.get_or_create_user("community-stays-out@studio.com")
    auth.provision_brain(user["id"])
    headers = {"Authorization": "Bearer " + db.issue_token(user["id"])}
    with TestClient(main.app) as client:
        assert client.post("/v1/community/leave", headers=headers,
                           json={"community_id": "archhub-community"}).status_code == 200
    auth.provision_brain(user["id"])
    auth.provision_brain(user["id"])
    assert db.list_community_keys_for_user(user["id"]) == []
