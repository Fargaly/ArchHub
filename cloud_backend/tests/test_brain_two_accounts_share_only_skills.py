"""Court: two accounts, the real cloud: a published skill reaches another member
only after the founder review, and a client fact never reaches the server.

Founder order 2026-09-29 (sign in -> personal brain -> Community Brain), as
corrected in review: sharing is an explicit publish, the founder reviews in the
cloud, and what a member pulls lands quarantined. Every byte the server wrote
is searched for the client fact and the plain fact.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nodelang import app_brain, brain_cloud_runner  # noqa: E402
from nodelang.cell_brain_community import quarantine  # noqa: E402
from nodelang.cell_catalog import bootstrap_assembly_protocol  # noqa: E402
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore  # noqa: E402

SKILL = "Dimension stairs riser-first"
CLIENT = r"From 20.CLIENTS\22.BBC4: the client wants sheet A-101 moved to rev C"
PLAIN = "Our office rounds door widths to 900 mm"


@pytest.fixture
def client(tmp_path):
    import main
    with TestClient(main.app) as c:
        yield c


class Account:
    def __init__(self, client, tmp_path, name):
        import auth
        import db
        self.email = name + "@studio.test"
        user = db.get_or_create_user(self.email)
        auth.provision_brain(user["id"])
        self.headers = {"Authorization": "Bearer " + db.issue_token(user["id"])}
        self.appdata = tmp_path / ("appdata-" + name)
        (self.appdata / "ArchHub" / "brain").mkdir(parents=True)
        (self.appdata / "ArchHub" / "brain" / "cloud.json").write_text(
            json.dumps({"email": self.email, "token": "court"}), encoding="utf-8")
        self.store = CellStore()
        protocol = bootstrap_assembly_protocol(self.store)
        owner = "app:court:owner-" + name
        self.store.commit(self.store.snapshot().revision, create=(Cell(owner, NULL_CELL_ID, NULL_CELL_ID, b"owner"),))
        self.registry = SimpleNamespace(authorization=SimpleNamespace(subject_root=owner), assembly_protocol=protocol)
        self.client = client

    def __enter__(self):
        app_brain.bind(self.store, self.registry)
        return self

    def __exit__(self, *_):
        app_brain.unbind(self.store)

    def sync(self):
        def post(payload):
            answer = self.client.post("/v1/brain/sync", headers=self.headers, json=payload)
            assert answer.status_code == 200, answer.text
            return answer.json()
        return brain_cloud_runner.sync_now(appdata=self.appdata, post=post)


def _admit_all(client):
    import db
    founder = {"Authorization": "Bearer " + db.issue_token(db.get_or_create_user("founder@example.test")["id"])}
    for item in client.get("/founder/api/community/pending", headers=founder).json()["pending"]:
        assert client.post("/founder/api/community/judge", headers=founder, json={
            "community_id": item["community_id"], "id": item["fragment_id"], "hlc": item["hlc"],
            "admit": True}).status_code == 200


def test_a_published_skill_crosses_after_review_and_a_client_fact_never_leaves(client, tmp_path):
    a = Account(client, tmp_path, "member-a")
    b = Account(client, tmp_path, "member-b")
    with a:
        app_brain.write([{"op": "add", "fragment": {"id": i, "kind": "fact", "text": t}}
                         for i, t in (("a-skill", SKILL), ("a-client", CLIENT), ("a-plain", PLAIN))])
        assert app_brain.publish("a-skill")["published"] is True
        assert app_brain.publish("a-client")["ok"] is False
        sent = a.sync()
        assert sent["ok"] is True and sent["shared"] == 1, sent
    with b:
        assert b.sync()["quarantined"] == 0
    assert quarantine(b.store.snapshot()) == (), "an unreviewed item was pulled"

    _admit_all(client)
    with b:
        assert b.sync()["quarantined"] == 1
    assert [entry.claim for entry in quarantine(b.store.snapshot())] == [SKILL]

    server = b"".join(p.read_bytes() for p in tmp_path.rglob("*")
                      if p.is_file() and "appdata-" not in str(p))
    assert SKILL.encode("utf-8") in server, "the skill must have reached the Community Brain"
    assert b"22.BBC4" not in server and b"sheet A-101" not in server, "a client fact reached the server"
    assert PLAIN.encode("utf-8") not in server, "a sealed fact reached the server"


def test_a_second_pass_changes_nothing(client, tmp_path):
    a = Account(client, tmp_path, "again-a")
    b = Account(client, tmp_path, "again-b")
    with a:
        app_brain.write([{"op": "add", "fragment": {"id": "a-skill", "kind": "practice", "text": SKILL}}])
        app_brain.publish("a-skill")
        a.sync()
        again = a.sync()
    assert again["shared"] == 0 and again["pushed"] == 0, again
    _admit_all(client)
    with b:
        b.sync()
        assert b.sync()["quarantined"] == 0
    assert len(quarantine(b.store.snapshot())) == 1


def test_signed_out_a_pass_does_nothing(client, tmp_path):
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    store.commit(store.snapshot().revision, create=(Cell("app:court:o", NULL_CELL_ID, NULL_CELL_ID, b"owner"),))
    app_brain.bind(store, SimpleNamespace(authorization=SimpleNamespace(subject_root="app:court:o"),
                                          assembly_protocol=protocol))
    try:
        assert brain_cloud_runner.sync_now(appdata=tmp_path / "nobody", post=None) == {
            "ok": False, "reason": "signed out"}
    finally:
        app_brain.unbind(store)


def test_only_the_application_turns_the_runner_on():
    source = (ROOT / "nodelang" / "application_server.py").read_text(encoding="utf-8")
    assert "enable_brain_cloud_sync=False," in source
    assert "if enable_brain_cloud_sync:" in source and "brain_cloud_runner.stop()" in source
    assert "enable_brain_cloud_sync=True," in (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")