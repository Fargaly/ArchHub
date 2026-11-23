from datetime import datetime, timezone
import json
import time

from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def watch():
    import db
    import main
    client = TestClient(main.app)
    actors = {}
    for name in ("owner", "alice", "bob"):
        email = name + "@watch-qa.example.test"
        user = db.get_or_create_user(email)
        actors[name] = (email, {"Authorization": "Bearer " + db.issue_token(user["id"])})
    def call(method, path, who=None, **kw):
        return client.request(method, "/v1/" + path, headers=actors[who][1] if who else {}, **kw)
    def invite(who="alice", **kw):
        body = dict(session_id="doc-B", session_file_id="doc-B", grantee_email=actors[who][0], expires_at=None)
        return call("POST", "watch-grants", "owner", json={**body, **kw})
    yield call, invite
    client.close()


def projection():
    return {"schema": "archhub-watch/v1", "nodes": [
        {"id": "n0", "engine": "step", "label": "Step", "status": "done",
         "position": {"x": -7.5, "y": 2}, "result": {"count": 3.15, "items": 2}},
        {"id": "n1", "engine": "skill", "label": "Skill", "status": "failed", "result": {"error": True}}],
        "wires": [["n0", "n1"]], "groups": [{"children": ["n0", "n1"]}]}


def test_account_isolation_discovery_and_lifecycle(watch, monkeypatch):
    import db
    import watch_grants as wg
    from types import SimpleNamespace
    now = [int(time.time())]
    monkeypatch.setattr(wg, "time", SimpleNamespace(time=lambda: now[0]))
    call, invite = watch
    assert call("GET", "watching").status_code == 401
    assert call("GET", "watch-grants").status_code == 401
    assert invite("owner").status_code == 400
    assert invite(session_file_id="doc-C").status_code == 400
    assert invite(grantee_email="nobody@watch-qa.example.test").status_code == 400
    assert invite(expires_at="2020-01-01T00:00:00Z").status_code == 400
    alice = invite().json()["grant"]
    bob = invite("bob", expires_at=datetime.fromtimestamp(now[0]+60, timezone.utc).isoformat()).json()["grant"]
    gid = alice["id"]
    url, push = "watching/"+gid, "watch-grants/"+gid+"/projection"
    def list_for(who):
        return call("GET", "watching", who).json()["grants"]
    assert list_for("owner") == []
    for name, g in (("alice", alice), ("bob", bob)):
        assert list_for(name) == [{"id":g["id"], "session_id":"doc-B", "expires_at":g["expires_at"],
                                  "revoked_at":None, "updated_at":None}]
        assert call("GET", "watch-grants", name).json()["grants"] == []
    assert {g["id"] for g in call("GET", "watch-grants", "owner").json()["grants"]} == {gid, bob["id"]}
    body = {"privacy":"Internal", "session_id":"doc-B"}
    full = {**body, "projection":projection()}
    beat = {**body, "heartbeat":True}
    for method, path in (("GET",url), ("PUT",push), ("DELETE","watch-grants/"+gid), ("POST","watch-grants")):
        assert call(method, path, json=full).status_code == 401
    assert call("PUT", push, "owner", json=beat).status_code == 410
    assert call("PUT", push, "alice", json=full).status_code == 403
    assert call("DELETE", "watch-grants/"+gid, "bob").status_code == 403
    assert call("PUT", push, "owner", json={**full, "session_id":"doc-C"}).status_code == 409
    assert call("PUT", push, "owner", json=full).is_success
    result = call("GET", url, "alice")
    assert result.json() == {"ok":True, "projection":projection(),
                             "updated_at":datetime.fromtimestamp(now[0], timezone.utc).isoformat()}
    assert alice["created_at"] == result.json()["updated_at"]
    assert result.headers["cache-control"] == "no-store" and list_for("alice")[0]["updated_at"]
    for who in ("owner", "bob"):
        denied = call("GET", url, who)
        assert denied.status_code == 410 and denied.json() == call("GET","watching/missing",who).json()
    now[0] += 30
    assert call("GET",url,"alice").is_success
    now[0] += .01
    assert call("GET",url,"alice").status_code == 410
    assert call("PUT",push,"owner",json=beat).is_success
    assert call("GET",url,"alice").json()["projection"] == result.json()["projection"]
    assert call("PUT","watch-grants/"+bob["id"]+"/projection","owner",json=full).is_success
    now[0] += 30
    assert list_for("bob") == []
    assert call("GET","watching/"+bob["id"],"bob").status_code == 410
    for _ in range(2):
        assert call("DELETE","watch-grants/"+gid,"owner").json()["grant"]["revoked_at"]
    assert list_for("alice") == [] and call("GET",url,"alice").status_code == 410
    assert call("PUT",push,"owner",json=full).status_code == 410
    with db.connect() as con:
        assert con.execute("SELECT count(*) FROM watch_grants WHERE projection IS NOT NULL").fetchone()[0] == 0


def test_projection_whitelist_and_heartbeat(watch):
    import db
    import watch_grants as wg
    call, invite = watch
    gid = invite().json()["grant"]["id"]
    push, url = "watch-grants/"+gid+"/projection", "watching/"+gid
    def send(**changes):
        return call("PUT", push, "owner", json={"session_id":"doc-B", "privacy":"Internal", **changes})
    base = projection()
    engine, label = next((e,l) for e,l in wg.labels().items() if e not in ("step","skill"))
    base["nodes"][0].update(engine=engine,label=label)
    for key, bad in (("notes",["private"]), ("parameters",{}), ("schema","other"),
                     ("groups",[{"children":["n0"],"title":"private"}]), ("groups",[{"children":["n77"]}]),
                     ("wires",[["n0","original-id"]])):
        assert send(projection={**base,key:bad}).status_code == 400
    for change in ({"id":"original-id"}, {"label":"private"}, {"engine":"skill.private"},
                   {"status":"private"}, {"result":{"error":"private"}}, {"result":{"items":True}},
                   {"result":{"count":False}}, {"position":{"x":1e12,"y":1}}, {"params":{}}):
        assert send(projection={**base,"nodes":[{**base["nodes"][0],**change}]}).status_code == 400
    assert call("PUT",push,"owner",content=b" " * (256 * 1024 + 1)).status_code == 413
    assert send(heartbeat=1).status_code == 400
    assert send(heartbeat=True, projection=base).status_code == 400
    assert send(projection=base, owner="other").status_code == 400
    assert send(projection=base).is_success
    assert call("GET",url,"alice").json()["projection"] == base
    with db.connect() as con:
        con.execute("UPDATE watch_grants SET projection=? WHERE id=?", (json.dumps({"private":"text"}),gid))
    assert send(heartbeat=True).status_code == 410
    assert call("GET",url,"alice").status_code == 410
    assert send(projection=base).is_success
    assert send(heartbeat=True,privacy="Confidential").status_code == 409
    assert call("GET",url,"alice").status_code == 410
    assert send(projection=base).status_code == 410


def test_retry_one_grant_one_stop_and_fresh_reinvitation(watch, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from types import SimpleNamespace
    import db
    import watch_grants as wg

    call, invite = watch
    now = [int(time.time())]
    monkeypatch.setattr(wg, "time", SimpleNamespace(time=lambda: now[0]))
    def ends(seconds):
        return datetime.fromtimestamp(now[0] + seconds, timezone.utc).isoformat()
    barrier = Barrier(4)
    def concurrent_create(_):
        barrier.wait(timeout=10)
        r = invite(expires_at=ends(60))
        assert r.status_code == 200
        return r.json()["grant"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        grants = list(pool.map(concurrent_create, range(4)))
    assert all(g == grants[0] for g in grants)
    gid = grants[0]["id"]
    assert invite().json()["grant"] == grants[0]
    body = {"session_id":"doc-B", "privacy":"Internal", "projection":projection()}
    assert call("PUT","watch-grants/"+gid+"/projection","owner",json=body).is_success
    initial = call("GET","watching/"+gid,"alice").json()
    now[0] += 3
    narrowed = invite(expires_at=ends(15)).json()["grant"]
    assert narrowed["id"] == gid and narrowed["updated_at"] == initial["updated_at"]
    assert narrowed["expires_at"] == ends(15)
    assert invite(expires_at=ends(99)).json()["grant"] == narrowed
    assert [g["id"] for g in call("GET","watching","alice").json()["grants"]] == [gid]
    assert len(call("GET","watch-grants","owner").json()["grants"]) == 1
    assert call("DELETE","watch-grants/"+gid,"owner").is_success
    assert call("GET","watching","alice").json()["grants"] == []
    assert call("GET","watching/"+gid,"alice").status_code == 410

    new = invite(expires_at=ends(5)).json()["grant"]
    assert new["id"] != gid and new["updated_at"] is None
    assert call("DELETE","watch-grants/"+gid,"owner").is_success
    assert [g["id"] for g in call("GET","watching","alice").json()["grants"]] == [new["id"]]
    now[0] += 5
    renewed = invite().json()["grant"]
    assert renewed["id"] not in (gid, new["id"]) and renewed["updated_at"] is None
    assert call("GET","watching/"+new["id"],"alice").status_code == 410
    assert [g["id"] for g in call("GET","watching","alice").json()["grants"]] == [renewed["id"]]
    with db.connect() as con:
        assert con.execute("SELECT count(*) FROM watch_grants").fetchone()[0] == 3
