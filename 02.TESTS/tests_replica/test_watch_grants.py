"""Court: Invite to watch (nodelang/watch_grants.py) against a fake cloud with the agreed contract.

Two disposable viewer accounts, disposable registered project folders and saved sessions; no network,
no production account, no send. The fake cloud enforces what the real one must: owner-only writes,
grantee-only reads, expiry, revocation and the 30 s staleness rule.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nodelang import watch_grants as watch
from nodelang.settings_owner import CloudRouteUnavailable

OWNER, VIEWER1, VIEWER2 = "owner@example.test", "viewer.one@example.test", "viewer.two@example.test"
# Free text an owner could type or an engine could return; none of it may reach a watcher.
MARKERS = ["C:\\Users\\someone", "\\\\server\\share", "client-name-marker", "token-name-marker", "person@office.example",
           "Issue C for the client", "internal plan marker", "root-confidential-marker", "private-result-marker"]


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class FakeCloud:
    """The agreed /v1/watch-grants + /v1/watching contract, per calling account."""

    def __init__(self, clock):
        self.clock, self.grants, self.projections, self.seq, self.on_post, self.puts = clock, {}, {}, 0, None, []

    def as_account(self, email):
        def call(method, path, body=None, **_):
            return self.handle(email, method, path, body)
        return call

    def handle(self, caller, method, path, body):
        now = self.clock()
        if path == "/v1/watch-grants" and method == "GET":
            return {"ok": True, "grants": [dict(g) for g in self.grants.values() if g["owner"] == caller]}
        if path == "/v1/watch-grants" and method == "POST":
            if body["grantee_email"] == caller:
                raise ValueError("Cloud backend refused (HTTP 400).")
            self.seq += 1
            grant = {"id": "grant-%04d-abcdef" % self.seq, "owner": caller, "session_id": body["session_id"],
                     "grantee_email": body["grantee_email"], "expires_at": body["expires_at"], "revoked_at": None}
            self.grants[grant["id"]] = grant
            if self.on_post:
                self.on_post(grant)  # something changes while the grant is being created
            return {"ok": True, "grant": dict(grant)}
        if path.startswith("/v1/watch-grants/"):
            parts = path.split("/")
            grant = self.grants.get(parts[3])
            if grant is None or grant["owner"] != caller:
                raise ValueError("Cloud backend refused (HTTP 403).")
            if method == "DELETE" and len(parts) == 4:
                grant["revoked_at"] = now.isoformat()
                self.projections.pop(grant["id"], None)
                return {"ok": True, "grant": dict(grant)}
            if method == "PUT" and parts[4:] == ["projection"]:
                if grant["revoked_at"] or not self._live(grant, now):
                    raise ValueError("Cloud backend refused (HTTP 410).")
                if body.get("session_id") != grant["session_id"] or body.get("privacy") != "Internal":
                    raise ValueError("Cloud backend refused (HTTP 409).")
                self.puts.append((caller, grant["id"], "heartbeat" if body.get("heartbeat") else "projection"))
                held = self.projections.get(grant["id"], {})
                self.projections[grant["id"]] = {"projection": body.get("projection", held.get("projection")), "updated_at": now}
                return {"ok": True}
        if path == "/v1/watching" and method == "GET":  # 542e: exactly five fields, unexpired and unrevoked only
            return {"ok": True, "grants": [
                {"id": g["id"], "session_id": g["session_id"], "expires_at": g["expires_at"], "revoked_at": None,
                 "updated_at": self.projections[g["id"]]["updated_at"].isoformat() if g["id"] in self.projections else None}
                for g in self.grants.values() if g["grantee_email"] == caller and not g["revoked_at"] and self._live(g, now)]}
        if path.startswith("/v1/watching/") and method == "GET":
            grant = self.grants.get(path.split("/")[3])
            held = grant and self.projections.get(grant["id"])
            if (grant is None or grant["grantee_email"] != caller or grant["revoked_at"] or not self._live(grant, now)
                    or held is None or (now - held["updated_at"]).total_seconds() > 30):
                raise watch.WatchEnded("This shared session cannot be shown now.")  # cloud_call's opaque 410
            return {"ok": True, "projection": held["projection"], "updated_at": held["updated_at"].isoformat()}
        raise ValueError("Cloud backend refused (HTTP 405).")

    @staticmethod
    def _live(grant, now):
        return not grant["expires_at"] or datetime.fromisoformat(grant["expires_at"]) > now


def _document(identity, root_id):
    nodes = []
    for i in range(6):
        nodes.append({"id": "%s-n%d" % (identity, i), "type": "revit.read_views" if i % 2 else "made.up.engine",
                      "title": MARKERS[i % len(MARKERS)],
                      "params": {"path": MARKERS[0] + "\\model.rvt", "key": MARKERS[3]},
                      "position": {"x": i * 100.0, "y": 0.0},
                      "result": {"status": ["Done", "Error", "Running", "weird", "Done", "Waiting for approval"][i],
                                 "error": MARKERS[4] if i == 1 else None,
                                 "rows": [[MARKERS[1], MARKERS[2]]] * i, "count": i * 3, "note": MARKERS[8]}})
    nodes.append({"id": "NorthLobby", "type": "revit.read_views", "position": {"x": 1, "y": 1}, "result": {"status": "Done"}})
    return {"format": "archhub", "version": 1, "id": identity, "title": MARKERS[5],
            "nodes": nodes, "wires": [{"id": "w1", "from": {"node": nodes[0]["id"], "socket": "out"},
                                       "to": {"node": nodes[1]["id"], "socket": "in"}}],
            "groups": [{"id": "g", "title": MARKERS[6], "children": [nodes[0]["id"], nodes[1]["id"]]}],
            "notes": [{"id": "note", "text": MARKERS[6]}], "viewport": {"x": 0, "y": 0, "zoom": 1},
            "properties": {"project": root_id, "taskContext": {"plan": MARKERS[6]}, "settings": {"x": MARKERS[7]}}}


@pytest.fixture
def world(tmp_path):
    clock = Clock()
    cloud = FakeCloud(clock)
    root = tmp_path / "Projects" / "P-001"
    root.mkdir(parents=True)
    paths = {}
    for name in ("A", "B"):
        paths[name] = root / ("Session %s.archhub" % name)
        paths[name].write_text(json.dumps(_document("doc-" + name, "root-internal")), encoding="utf-8")
    outside = tmp_path / "Downloads" / "Session B copy.archhub"
    outside.parent.mkdir()
    outside.write_text(json.dumps(_document("doc-B", "root-internal")), encoding="utf-8")
    sessions = tmp_path / "sessions"  # the app's own Home task folder, outside every project root
    sessions.mkdir()
    home = _document("doc-H", "")
    home["properties"].pop("project")
    home["properties"]["taskContext"] = {"task": "t-home", "workspace": "root-internal"}
    paths["H"] = sessions / "Home task.archhub"
    paths["H"].write_text(json.dumps(home), encoding="utf-8")
    bound = {"t-home": str(paths["H"])}  # the Workshop task row's own session_path
    roots = {"root-internal": {"root_id": "root-internal", "path": str(root)}}
    policies = {"root-internal": "Internal"}
    prefs = {}

    def workspace(identity):
        if identity not in roots:
            raise ValueError("This workspace is no longer registered. Refresh Account settings.")
        return roots[identity]

    owner = watch.WatchGrants(
        cloud=cloud.as_account(OWNER), account=lambda: {"email": OWNER, "user_id": "u-owner"},
        workspace=workspace, policy=lambda identity: policies.get(identity),
        read_prefs=lambda: dict(prefs), save_prefs=prefs.update,
        labels=lambda: {"revit.read_views": "Read views"},
        read_document=lambda path: json.loads(Path(path).read_text(encoding="utf-8")), clock=clock,
        sessions=lambda: sessions, task_session=bound.get)
    return {"clock": clock, "cloud": cloud, "owner": owner, "paths": paths, "outside": outside,
            "policies": policies, "prefs": prefs, "sessions": sessions, "bound": bound}


def test_a_home_task_session_is_eligible_only_as_its_tasks_own_file_with_an_assigned_project(world):
    owner, cloud, paths, sessions, bound = world["owner"], world["cloud"], world["paths"], world["sessions"], world["bound"]
    grant_id = owner.invite(str(paths["H"]), VIEWER1, "1h")["grant"]["id"]
    assert cloud.grants[grant_id]["session_id"] == "doc-H"
    assert cloud.handle(VIEWER1, "GET", "/v1/watching/" + grant_id, None)["projection"]["schema"] == "archhub-watch/v1"
    world["policies"]["root-internal"] = "Confidential"
    with pytest.raises(ValueError, match="Internal"):
        owner.invite(str(paths["H"]), VIEWER2, "1h")
    world["policies"]["root-internal"] = "Internal"
    home = json.loads(paths["H"].read_text(encoding="utf-8"))

    def saved(name, task, context, identity, **props):
        doc = json.loads(json.dumps(home))
        doc["id"], doc["properties"]["taskContext"] = identity, {"task": task, **context}
        doc["properties"].update(props)
        target = sessions / name
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(doc), encoding="utf-8")
        return str(target)

    beside = saved("Unrelated beside.archhub", "t-home", {"workspace": "root-internal"}, "doc-X")  # claims t-home's project
    with pytest.raises(ValueError, match="own session"):
        owner.invite(beside, VIEWER2, "1h")
    bound["t-legacy"] = saved("Legacy.archhub", "t-legacy", {"project": "P-001"}, "doc-L")  # legacy label only
    with pytest.raises(ValueError, match="Choose a project"):
        owner.invite(bound["t-legacy"], VIEWER2, "1h")
    bound["t-cleared"] = saved("Cleared.archhub", "t-cleared", {"workspace": "root-internal"}, "doc-C", project="")
    with pytest.raises(ValueError, match="Choose a project"):  # an explicitly cleared project wins over the held workspace
        owner.invite(bound["t-cleared"], VIEWER2, "1h")
    bound["t-gone"] = saved("Unregistered.archhub", "t-gone", {"workspace": "root-gone"}, "doc-U")
    with pytest.raises(ValueError, match="no longer registered"):
        owner.invite(bound["t-gone"], VIEWER2, "1h")
    bound["t-nested"] = saved("sub/Nested.archhub", "t-nested", {"workspace": "root-internal"}, "doc-N")
    with pytest.raises(ValueError, match="registered project folder"):  # only the sessions folder itself
        owner.invite(bound["t-nested"], VIEWER2, "1h")
    assert {g["session_id"] for g in cloud.grants.values()} == {"doc-H"}


@pytest.fixture(autouse=True)
def _fresh_digests():
    getattr(watch, "_DIGESTS", {}).clear()
    yield
    getattr(watch, "_DIGESTS", {}).clear()


def test_the_projection_carries_no_free_text_from_the_session():
    view = watch.project(_document("doc-B", "root-internal"), {"revit.read_views": "Read views"})
    body = json.dumps(view)
    for marker in MARKERS + ["NorthLobby", "doc-B-n"]:
        assert marker not in body, marker
    assert [n["id"] for n in view["nodes"]] == ["n%d" % i for i in range(7)], "every node id is opaque"
    assert {n["engine"] for n in view["nodes"]} == {"revit.read_views", "step"}
    assert {n["label"] for n in view["nodes"]} == {"Read views", "Step"}
    assert [n["status"] for n in view["nodes"]] == ["done", "failed", "running", "unknown", "done", "approval", "done"]
    assert view["nodes"][1]["result"] == {"error": True, "items": 1, "count": 3}
    assert view["wires"] == [["n0", "n1"]] and view["groups"] == [{"children": ["n0", "n1"]}]


def test_invite_grants_only_the_right_clicked_session_to_that_viewer(world):
    owner, cloud, paths = world["owner"], world["cloud"], world["paths"]
    answer = owner.invite(str(paths["B"]), VIEWER1, "1h")  # A stays selected; B was right-clicked
    grant = cloud.grants[answer["grant"]["id"]]
    assert grant["session_id"] == "doc-B" and grant["grantee_email"] == VIEWER1 and grant["owner"] == OWNER
    seen = cloud.handle(VIEWER1, "GET", "/v1/watching/" + grant["id"], None)["projection"]
    assert seen == watch.project(json.loads(paths["B"].read_text(encoding="utf-8")), {"revit.read_views": "Read views"})
    assert [g for g in cloud.grants.values() if g["session_id"] == "doc-A"] == []
    with pytest.raises(ValueError):
        cloud.handle(VIEWER2, "GET", "/v1/watching/" + grant["id"], None)  # another account
    for method in ("PUT", "DELETE", "POST"):
        with pytest.raises(ValueError):  # a watcher has no write path: not run, edit, approve or revoke
            cloud.handle(VIEWER1, method, "/v1/watch-grants/%s/projection" % grant["id"], {"projection": {}})


def test_stop_revokes_and_the_relay_no_longer_pushes(world):
    owner, cloud = world["owner"], world["cloud"]
    grant_id = owner.invite(str(world["paths"]["B"]), VIEWER1, "stop")["grant"]["id"]
    assert owner.push() == {grant_id: "heartbeat"}
    owner.stop(grant_id)
    with pytest.raises(ValueError):
        cloud.handle(VIEWER1, "GET", "/v1/watching/" + grant_id, None)
    assert owner.push() == {} and world["prefs"]["watchSessions"] == {}


def test_until_i_stop_is_live_only_while_the_app_pushes(world):
    owner, cloud, clock = world["owner"], world["cloud"], world["clock"]
    grant_id = owner.invite(str(world["paths"]["B"]), VIEWER1, "stop")["grant"]["id"]
    clock.now += timedelta(seconds=31)  # app closed: no push for more than 30 s
    with pytest.raises(ValueError):
        cloud.handle(VIEWER1, "GET", "/v1/watching/" + grant_id, None)
    owner.push()  # app back: a heartbeat makes it live again
    assert cloud.handle(VIEWER1, "GET", "/v1/watching/" + grant_id, None)["projection"]["schema"] == "archhub-watch/v1"


def test_expiry_ends_watching(world):
    owner, cloud, clock = world["owner"], world["cloud"], world["clock"]
    grant_id = owner.invite(str(world["paths"]["B"]), VIEWER2, "1h")["grant"]["id"]
    clock.now += timedelta(minutes=59)
    owner.push()
    assert cloud.handle(VIEWER2, "GET", "/v1/watching/" + grant_id, None)
    clock.now += timedelta(minutes=2)
    assert owner.push() == {}
    with pytest.raises(ValueError):
        cloud.handle(VIEWER2, "GET", "/v1/watching/" + grant_id, None)


@pytest.mark.parametrize("tier", ["Confidential", "Secret", None, "public"])
def test_only_internal_work_can_be_shared(world, tier):
    world["policies"]["root-internal"] = tier
    with pytest.raises(ValueError, match="Internal"):
        world["owner"].invite(str(world["paths"]["B"]), VIEWER1, "1h")
    assert world["cloud"].grants == {}


def test_a_privacy_downgrade_stops_an_active_share(world):
    owner, cloud = world["owner"], world["cloud"]
    grant_id = owner.invite(str(world["paths"]["B"]), VIEWER1, "stop")["grant"]["id"]
    world["policies"]["root-internal"] = "Confidential"
    assert owner.push()[grant_id].startswith("stopped:")
    assert cloud.grants[grant_id]["revoked_at"]
    with pytest.raises(ValueError):
        cloud.handle(VIEWER1, "GET", "/v1/watching/" + grant_id, None)


def test_paths_outside_the_registered_root_and_bad_input_refuse(world):
    owner = world["owner"]
    with pytest.raises(ValueError, match="outside its project folder"):
        owner.invite(str(world["outside"]), VIEWER1, "1h")
    with pytest.raises(ValueError, match="email"):
        owner.invite(str(world["paths"]["B"]), "not an email", "1h")
    with pytest.raises(ValueError, match="someone else"):
        owner.invite(str(world["paths"]["B"]), OWNER, "1h")
    with pytest.raises(ValueError, match="ends"):
        owner.invite(str(world["paths"]["B"]), VIEWER1, "forever")
    assert world["cloud"].grants == {}


def test_a_cloud_without_the_routes_keeps_the_menu_disabled(world):
    def missing(*_args, **_kwargs):
        raise CloudRouteUnavailable("Cloud feature unavailable.")
    world["owner"].cloud = missing
    assert world["owner"].capability() == {"capability": False, "reason": watch.UNAVAILABLE, "grants": []}


def test_the_relay_skips_the_cloud_when_nothing_is_shared(tmp_path):
    account = tmp_path / "account.json"
    assert watch.has_local_shares(account) is False
    account.write_text(json.dumps({"account:u": {"watchSessions": {}}}), encoding="utf-8")
    assert watch.has_local_shares(account) is False
    account.write_text(json.dumps({"account:u": {"watchSessions": {"grant-1": {"path": "x", "session_id": "d"}}}}), encoding="utf-8")
    assert watch.has_local_shares(account) is True


def test_a_privacy_change_while_the_grant_is_created_shares_nothing(world):
    owner, cloud = world["owner"], world["cloud"]
    cloud.on_post = lambda grant: world["policies"].__setitem__("root-internal", "Confidential")
    with pytest.raises(ValueError, match="Internal"):
        owner.invite(str(world["paths"]["B"]), VIEWER1, "stop")
    (grant,) = cloud.grants.values()
    assert grant["revoked_at"] and cloud.puts == [] and cloud.projections == {}
    assert not world["prefs"].get("watchSessions")


def test_an_account_switch_while_inviting_shares_nothing(world):
    owner, cloud = world["owner"], world["cloud"]
    accounts = iter([{"email": OWNER, "user_id": "u-owner"}, {"email": "other@example.test", "user_id": "u-other"}])
    owner.account = lambda: next(accounts)
    with pytest.raises(ValueError, match="account changed"):
        owner.invite(str(world["paths"]["B"]), VIEWER1, "stop")
    (grant,) = cloud.grants.values()
    assert grant["revoked_at"] and cloud.puts == []


def test_two_real_relay_cycles_send_a_projection_then_a_heartbeat_and_an_account_switch_starts_over(tmp_path, monkeypatch):
    """CloudRelay.push_watch through the real Settings owner and account preferences file, twice, then a switch."""
    from nodelang import cloud_relay
    from nodelang.settings_owner import AccountFiles, SettingsOwner
    state = tmp_path / "state"
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(state))
    root = tmp_path / "Projects" / "P-001"
    root.mkdir(parents=True)
    (state / "settings").mkdir(parents=True, exist_ok=True)
    (state / "settings" / "workspaces.json").write_text(json.dumps({"roots": [{"root_id": "root-internal", "path": str(root)}]}), encoding="utf-8")
    session = root / "Session B.archhub"
    session.write_text(json.dumps({"format": "archhub", "version": 1, "id": "doc-B", "title": "B", "groups": [], "notes": [],
        "nodes": [{"id": "NorthLobby", "type": "revit.read_views", "params": {}, "position": {"x": 0, "y": 0}, "result": {"status": "Done"}}],
        "wires": [], "viewport": {"x": 0, "y": 0, "zoom": 1}, "properties": {"project": "root-internal"}}), encoding="utf-8")
    clock = Clock()
    fake, who = FakeCloud(clock), {"email": OWNER, "user_id": "u-owner"}

    def cloud(method, path, body=None, **_):
        return dict(who, ok=True) if path == "/v1/me" else fake.handle(who["email"], method, path, body)

    account_file = state / "settings" / "account.json"
    owner = SettingsOwner(AccountFiles(account_file), cloud=cloud, dependencies=object())
    owner.setWorkspaceRules("root-internal", {"privacy": "Internal"})
    grant_id = owner.inviteWatcher(str(session), VIEWER1, "stop")["grant"]["id"]
    assert fake.puts == [(OWNER, grant_id, "projection")]
    watch._DIGESTS.clear()  # a new app process: the relay has never pushed this grant
    relay = cloud_relay.CloudRelay(base_url="https://cloud.example.test", token="fixture", respond=lambda _t: {},
                                   execute=lambda _t: {}, consent=lambda: True,
                                   watch_pusher=cloud_relay._watch_pusher(state, cloud=cloud))
    assert relay.push_watch() == {grant_id: "projection"}
    assert relay.push_watch() == {grant_id: "heartbeat"}, "digest continuity across the relay's fresh owner objects"
    who.update(email="other@example.test", user_id="u-other")  # account switch in the app
    assert relay.push_watch() == {}, "another account never pushes or heartbeats this owner's grant"
    who.update(email=OWNER, user_id="u-owner")
    assert relay.push_watch() == {grant_id: "heartbeat"}
    assert [p[2] for p in fake.puts] == ["projection", "projection", "heartbeat", "heartbeat"]
    assert "NorthLobby" not in json.dumps([held["projection"] for held in fake.projections.values()])

def test_labels_and_projection_never_load_user_skills_or_read_unrelated_files(tmp_path, monkeypatch):
    """A saved Canvas titled 'Local QA Diagram' elsewhere must never name a watched skill node."""
    import builtins
    import pathlib
    import importlib
    session_files = importlib.import_module("nodelang.session_files")
    importlib.import_module("nodelang.library_engines")  # imported before file reads are forbidden
    unrelated = tmp_path / "Sessions" / "Local QA Diagram.archhub"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text(json.dumps({"format": "archhub", "version": 1, "id": "doc-qa", "title": "Local QA Diagram",
                                     "nodes": [], "wires": [], "groups": [], "notes": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}),
                         encoding="utf-8")
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path / "state"))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a watch projection loaded skills or read a file")
    monkeypatch.setattr(session_files, "load_skills", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(pathlib.Path, "read_text", forbidden)
    monkeypatch.setattr(pathlib.Path, "read_bytes", forbidden)
    labels = watch.engine_labels()
    document = {"format": "archhub", "version": 1, "id": "doc-B", "title": "B", "groups": [], "notes": [], "wires": [],
                "nodes": [{"id": "s1", "type": "skill", "params": {"name": "Local QA Diagram"}, "position": {"x": 0, "y": 0}},
                          {"id": "s2", "type": "skill.wrap", "params": {}, "position": {"x": 1, "y": 0}}],
                "viewport": {"x": 0, "y": 0, "zoom": 1}}
    poisoned = dict(labels, skill="Local QA Diagram")  # even a label table carrying a user title cannot name a skill
    view = watch.project(document, poisoned)
    monkeypatch.undo()
    assert "skill" not in labels and "skill.wrap" not in labels
    assert labels, "product labels come from the static Library tables"
    assert [(n["engine"], n["label"]) for n in view["nodes"]] == [("skill", "Skill"), ("skill", "Skill")]
    assert "Local QA Diagram" not in json.dumps(view) and "Local QA Diagram" not in json.dumps(labels)

def test_the_task_binding_lookup_reads_the_workshop_strictly_read_only(tmp_path):
    import sqlite3
    import time as clock_time
    from nodelang import workshop_tasks
    database = tmp_path / "workshop" / "messages.sqlite3"
    assert workshop_tasks.bound_session_path("t-a", database) is None and not database.parent.exists()  # absent: nothing created
    database.parent.mkdir()
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE other(x)")
    assert workshop_tasks.bound_session_path("t-a", database) is None  # no task table
    with sqlite3.connect(database) as db:
        db.execute(workshop_tasks.SCHEMA)
        have = {row[1] for row in db.execute("PRAGMA table_info(workshop_tasks)")}
        for column in workshop_tasks.COLUMNS:
            if column not in have:
                db.execute("ALTER TABLE workshop_tasks ADD COLUMN %s" % column)
        now = clock_time.time()
        db.execute("INSERT INTO workshop_tasks(id,title,status,created_by,created_at,updated_at,session_path,revision) "
                   "VALUES('t-a','A','open','founder',?,?,?,0)", (now, now, str(tmp_path / "A.archhub")))
        # Unrelated B: an expired claim that settling would reopen as interrupted.
        db.execute("INSERT INTO workshop_tasks(id,title,status,owner,owner_label,lease_until,created_by,created_at,updated_at,"
                   "session_path,revision,write_open) VALUES('t-b','B','claimed','agent:x','X',?,'founder',?,?,?,0,0)",
                   (now - 3600, now, now, str(tmp_path / "B.archhub")))
    before = database.read_bytes()
    row_b = lambda: sqlite3.connect(database).execute(
        "SELECT status,owner,lease_until,revision,outcome FROM workshop_tasks WHERE id='t-b'").fetchone()
    held_b = row_b()
    assert workshop_tasks.bound_session_path("t-a", database) == str(tmp_path / "A.archhub")
    assert workshop_tasks.bound_session_path("t-missing", database) is None
    assert row_b() == held_b and held_b[0] == "claimed" and held_b[3] == 0 and held_b[4] is None
    assert database.read_bytes() == before
    assert sorted(p.name for p in database.parent.iterdir()) == ["messages.sqlite3"]  # no journal, wal or shm left


def _viewer(world, email):
    return watch.WatchGrants(
        cloud=world["cloud"].as_account(email), account=lambda: {"email": email, "user_id": "u-" + email},
        workspace=lambda identity: (_ for _ in ()).throw(ValueError("not registered")), policy=lambda identity: None,
        read_prefs=dict, save_prefs=lambda values: None, labels=lambda: {"revit.read_views": "Read views"},
        read_document=lambda path: (_ for _ in ()).throw(AssertionError("a watcher never reads a file")), clock=world["clock"])


def test_the_recipient_lists_watches_and_sees_paused_and_ended_states(world):
    owner, clock = world["owner"], world["clock"]
    one, two = _viewer(world, VIEWER1), _viewer(world, VIEWER2)
    assert one.watching() == {"capability": True, "reason": "", "watching": []}
    grant_id = owner.invite(str(world["paths"]["B"]), VIEWER1, "1h")["grant"]["id"]
    listed = one.watching()["watching"]
    assert [row["id"] for row in listed] == [grant_id] and listed[0]["state"] == "shared" and listed[0]["expires"]
    assert set(json.dumps(listed)) and "doc-B" not in json.dumps(listed)  # no session identity reaches the list
    assert two.watching()["watching"] == []  # another account sees nothing
    live = one.view(grant_id)
    expected = watch.project(json.loads(world["paths"]["B"].read_text(encoding="utf-8")), {"revit.read_views": "Read views"})
    assert live["state"] == "live" and live["projection"]["nodes"] == [
        {k: v for k, v in n.items() if k != "engine"} for n in expected["nodes"]]
    assert live["projection"]["wires"] == expected["wires"] and live["updated"] and live["pollMs"] == watch.WATCH_NODE["params"]["poll_ms"]
    assert two.view(grant_id)["state"] == "ended"  # wrong recipient: the same opaque answer, and not in that list
    clock.now += timedelta(seconds=31)  # owner app closed
    paused = one.view(grant_id)
    assert paused["state"] == "paused" and paused["pollMs"] == watch.WATCH_NODE["params"]["poll_ms"]
    owner.push()
    assert one.view(grant_id)["state"] == "live"
    owner.stop(grant_id)  # revoked
    assert one.view(grant_id) == {"state": "ended", "message": "Watching has ended."} and one.watching()["watching"] == []
    expiring = owner.invite(str(world["paths"]["B"]), VIEWER2, "1h")["grant"]["id"]
    clock.now += timedelta(minutes=61)  # expired
    assert two.view(expiring)["state"] == "ended" and two.watching()["watching"] == []


def test_the_recipient_revalidates_every_field_and_rederives_labels():
    hostile = {"schema": "archhub-watch/v1", "title": MARKERS[2], "nodes": [
        {"id": "n0", "engine": "revit.read_views", "label": MARKERS[5], "status": "done", "title": MARKERS[0],
         "position": {"x": 1, "y": 2}, "result": {"error": True, "items": 3, "rows": [[MARKERS[1]]], "message": MARKERS[4]}},
        {"id": "n1", "engine": "skill.mine", "label": MARKERS[6], "status": "<script>"},
        {"id": MARKERS[3], "engine": "revit.read_views", "status": "done"},
        {"id": "n0", "engine": "x", "status": "done"},
        {"id": "n2", "engine": MARKERS[7], "label": MARKERS[8], "status": "running", "position": {"x": "1", "y": 2}}],
        "wires": [["n0", "n1"], ["n0", MARKERS[3]], "n0-n2"], "groups": [{"children": ["n0", MARKERS[2]], "title": MARKERS[6]}]}
    clean = watch.clean_projection(hostile, {"revit.read_views": "Read views"})
    body = json.dumps(clean)
    for marker in MARKERS:
        assert marker not in body, marker
    assert clean["nodes"] == [
        {"id": "n0", "label": "Read views", "status": "done", "position": {"x": 1, "y": 2}, "result": {"error": True, "items": 3}},
        {"id": "n1", "label": "Skill", "status": "unknown"},
        {"id": "n2", "label": "Step", "status": "running"}]
    assert clean["wires"] == [["n0", "n1"]] and clean["groups"] == [{"children": ["n0"]}]
    for broken in (None, {}, {"schema": "other", "nodes": []}, {"schema": "archhub-watch/v1", "nodes": "x"}):
        with pytest.raises(ValueError):
            watch.clean_projection(broken, {})


def test_the_recipient_without_routes_is_unavailable(world):
    def missing(*_args, **_kwargs):
        raise CloudRouteUnavailable("Cloud feature unavailable.")
    viewer = _viewer(world, VIEWER1)
    viewer.cloud = missing
    assert viewer.watching() == {"capability": False, "reason": watch.UNAVAILABLE, "watching": []}
