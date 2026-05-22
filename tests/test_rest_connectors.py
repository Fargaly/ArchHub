"""Tests for the REST / API connector cluster.

Covers the four host connectors built against `connectors.base`:
Speckle, Notion, Dropbox, Microsoft Teams.

Design constraints honoured:
  * Runs fully OFFLINE — `urllib.request.urlopen` is mocked everywhere;
    no test ever opens a socket.
  * Runs with NO tokens configured — `_load_token` is mocked to None
    (for the unauthorized-probe tests) or to a fake token (for the
    HTTP-mocked happy paths).
  * Asserts the op sets each connector exposes.
  * Asserts `probe()` returns 'unauthorized' cleanly when no token.
  * Asserts response parsing against small, realistic recorded fixture
    payloads (declared inline below).
  * Asserts all four connectors `register()` onto the base registry.

The mock surface: every connector module calls `urllib.request.urlopen`.
`_mock_urlopen` returns a context-manager double whose `.read()` yields
recorded JSON; `_mock_http_error` raises `urllib.error.HTTPError`.
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

from connectors import (  # noqa: E402
    dropbox_connector,
    notion_connector,
    speckle_connector,
    teams_connector,
)
from connectors import base as connectors_base  # noqa: E402


# ===========================================================================
# HTTP mock helpers
# ===========================================================================
def _mock_urlopen(payload, *, status: int = 200, headers: dict | None = None):
    """Build a context-manager double that yields a response object.

    `payload` may be a dict/list (JSON-encoded) or raw bytes (used for
    Dropbox content downloads).
    """
    if isinstance(payload, (dict, list)):
        body = json.dumps(payload).encode("utf-8")
    elif isinstance(payload, bytes):
        body = payload
    else:
        body = str(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    hdrs = MagicMock()
    hdrs.get.side_effect = lambda k, d=None: (headers or {}).get(k, d)
    resp.headers = hdrs
    cm = MagicMock()
    cm.__enter__ = lambda self_: resp
    cm.__exit__ = lambda self_, *a: False
    return cm


def _mock_http_error(code: int, body: str = ""):
    """Build a urllib HTTPError for a given status code."""
    return urllib.error.HTTPError(
        url="https://example.test", code=code, msg="err",
        hdrs=None, fp=io.BytesIO(body.encode("utf-8")),
    )


def _seq_urlopen(*payloads):
    """A side_effect callable yielding one mocked response per call —
    for testing pagination across multiple HTTP round-trips."""
    cms = [_mock_urlopen(p) if not isinstance(p, BaseException) else p
           for p in payloads]
    it = iter(cms)

    def _next(*_a, **_k):
        nxt = next(it)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt
    return _next


UO = "urllib.request.urlopen"


# ===========================================================================
# Recorded fixture payloads — small but realistic API responses.
# ===========================================================================
SPECKLE_ACTIVE_USER = {
    "data": {"activeUser": {"id": "u_abc", "name": "Aaliyah Khan",
                            "email": "aaliyah@studio.test"}}
}
SPECKLE_PROJECTS = {
    "data": {"activeUser": {"projects": {
        "totalCount": 2,
        "items": [
            {"id": "p_tower", "name": "Tower A", "description": "Central",
             "visibility": "PRIVATE", "updatedAt": "2026-05-10T09:00:00Z",
             "models": {"totalCount": 4}},
            {"id": "p_annex", "name": "Annex", "description": "",
             "visibility": "PUBLIC", "updatedAt": "2026-05-12T11:00:00Z",
             "models": {"totalCount": 1}},
        ],
    }}}
}
SPECKLE_MODELS = {
    "data": {"project": {
        "id": "p_tower", "name": "Tower A",
        "models": {"totalCount": 1, "items": [
            {"id": "m_arch", "name": "architecture", "description": "L01-L20",
             "updatedAt": "2026-05-10T09:00:00Z",
             "versions": {"totalCount": 7}},
        ]},
    }}
}
SPECKLE_VERSIONS = {
    "data": {"project": {"model": {
        "id": "m_arch", "name": "architecture",
        "versions": {"totalCount": 1, "items": [
            {"id": "v_001", "message": "Issued for coordination",
             "referencedObject": "obj_deadbeef",
             "createdAt": "2026-05-10T09:00:00Z",
             "sourceApplication": "Revit",
             "authorUser": {"id": "u_abc", "name": "Aaliyah Khan"}},
        ]},
    }}}
}
SPECKLE_OBJECT = {
    "data": {"project": {"object": {
        "id": "obj_deadbeef", "speckleType": "Base",
        "totalChildrenCount": 128,
        "data": {"name": "root", "elements": []},
    }}}
}
SPECKLE_VERSION_REF = {
    "data": {"project": {"version": {
        "id": "v_001", "referencedObject": "obj_deadbeef"}}}
}
SPECKLE_SEND_OK = {
    "data": {"versionMutations": {"create": {
        "id": "v_new", "message": "Pushed from ArchHub",
        "referencedObject": "obj_deadbeef",
        "createdAt": "2026-05-15T12:00:00Z"}}}
}
SPECKLE_GQL_AUTH_ERROR = {
    "errors": [{"message": "Your token is not valid.",
                "extensions": {"code": "FORBIDDEN"}}]
}

NOTION_ME = {
    "object": "user", "id": "bot_123", "name": "ArchHub Bot",
    "type": "bot",
    "bot": {"workspace_name": "Studio Wiki"},
}
NOTION_SEARCH = {
    "object": "list",
    "results": [
        {"object": "page", "id": "pg_1",
         "url": "https://notion.so/pg_1",
         "last_edited_time": "2026-05-10T09:00:00.000Z",
         "properties": {"Name": {"type": "title",
                                 "title": [{"plain_text": "Kickoff notes"}]}}},
        {"object": "database", "id": "db_1",
         "url": "https://notion.so/db_1",
         "last_edited_time": "2026-05-11T09:00:00.000Z",
         "title": [{"plain_text": "Project Tracker"}],
         "properties": {"Name": {}, "Status": {}}},
    ],
    "has_more": False, "next_cursor": None,
}
NOTION_DATABASES = {
    "object": "list",
    "results": [
        {"object": "database", "id": "db_1",
         "url": "https://notion.so/db_1",
         "last_edited_time": "2026-05-11T09:00:00.000Z",
         "title": [{"plain_text": "Project Tracker"}],
         "properties": {"Name": {}, "Status": {}, "Owner": {}}},
    ],
    "has_more": False, "next_cursor": None,
}
NOTION_QUERY = {
    "object": "list",
    "results": [
        {"object": "page", "id": "row_1",
         "url": "https://notion.so/row_1",
         "created_time": "2026-05-01T09:00:00.000Z",
         "last_edited_time": "2026-05-10T09:00:00.000Z",
         "archived": False,
         "properties": {
             "Name": {"type": "title",
                      "title": [{"plain_text": "Design Development"}]},
             "Status": {"type": "status",
                        "status": {"name": "In progress"}},
             "Budget": {"type": "number", "number": 48000},
             "Tags": {"type": "multi_select",
                      "multi_select": [{"name": "phase-2"},
                                       {"name": "priority"}]},
         }},
    ],
    "has_more": False, "next_cursor": None,
}
NOTION_PAGE = {
    "object": "page", "id": "pg_1", "url": "https://notion.so/pg_1",
    "created_time": "2026-05-01T09:00:00.000Z",
    "last_edited_time": "2026-05-10T09:00:00.000Z",
    "archived": False,
    "properties": {"Name": {"type": "title",
                            "title": [{"plain_text": "Kickoff notes"}]}},
}
NOTION_CREATED = {
    "object": "page", "id": "pg_new", "url": "https://notion.so/pg_new",
    "created_time": "2026-05-15T12:00:00.000Z",
    "last_edited_time": "2026-05-15T12:00:00.000Z",
    "archived": False,
    "properties": {"Name": {"type": "title",
                            "title": [{"plain_text": "New site visit"}]}},
}
NOTION_APPEND_OK = {
    "object": "list",
    "results": [{"object": "block", "id": "blk_1", "type": "paragraph"}],
}

DROPBOX_ACCOUNT = {
    "account_id": "dbid:acc_1",
    "name": {"display_name": "Studio Ops"},
    "email": "ops@studio.test",
}
DROPBOX_LIST_FOLDER = {
    "entries": [
        {".tag": "folder", "name": "Drawings", "id": "id:f1",
         "path_display": "/Project/Drawings",
         "path_lower": "/project/drawings"},
        {".tag": "file", "name": "site-plan.pdf", "id": "id:x1",
         "path_display": "/Project/site-plan.pdf",
         "path_lower": "/project/site-plan.pdf",
         "size": 880123, "server_modified": "2026-05-10T09:00:00Z",
         "rev": "0a1b2c", "content_hash": "abcd"},
    ],
    "has_more": False, "cursor": "cur_end",
}
DROPBOX_METADATA = {
    ".tag": "file", "name": "site-plan.pdf", "id": "id:x1",
    "path_display": "/Project/site-plan.pdf",
    "path_lower": "/project/site-plan.pdf",
    "size": 880123, "server_modified": "2026-05-10T09:00:00Z",
    "rev": "0a1b2c", "content_hash": "abcd",
}
DROPBOX_REVISIONS = {
    "is_deleted": False,
    "entries": [
        {"rev": "0a1b2c", "name": "site-plan.pdf", "size": 880123,
         "server_modified": "2026-05-10T09:00:00Z", "content_hash": "abcd"},
        {"rev": "0099aa", "name": "site-plan.pdf", "size": 870000,
         "server_modified": "2026-05-01T09:00:00Z", "content_hash": "ef01"},
    ],
}
DROPBOX_UPLOAD_OK = {
    ".tag": "file", "name": "notes.txt", "id": "id:up1",
    "path_display": "/Project/notes.txt",
    "path_lower": "/project/notes.txt",
    "size": 11, "server_modified": "2026-05-15T12:00:00Z", "rev": "ff00",
}
DROPBOX_SHARED_LINK = {
    "url": "https://www.dropbox.com/s/abc/site-plan.pdf?dl=0",
    "name": "site-plan.pdf",
    "path_lower": "/project/site-plan.pdf",
    "link_permissions": {"resolved_visibility": {".tag": "public"}},
}

TEAMS_ME = {
    "id": "user_1", "displayName": "Priya Anand",
    "userPrincipalName": "priya@studio.test",
}
TEAMS_JOINED = {
    "value": [
        {"id": "team_1", "displayName": "Tower A Project",
         "description": "Coordination"},
        {"id": "team_2", "displayName": "Studio Wide", "description": ""},
    ],
}
TEAMS_CHANNELS = {
    "value": [
        {"id": "ch_1", "displayName": "General",
         "description": "", "membershipType": "standard",
         "webUrl": "https://teams.microsoft.com/l/channel/ch_1"},
        {"id": "ch_2", "displayName": "Structure",
         "description": "SE coordination", "membershipType": "standard",
         "webUrl": "https://teams.microsoft.com/l/channel/ch_2"},
    ],
}
TEAMS_MESSAGES = {
    "value": [
        {"id": "msg_1", "createdDateTime": "2026-05-14T08:00:00Z",
         "lastModifiedDateTime": "2026-05-14T08:00:00Z",
         "importance": "normal", "messageType": "message",
         "from": {"user": {"displayName": "Priya Anand"}},
         "body": {"contentType": "html",
                  "content": "<p>Latest set is <b>up</b>.</p>"},
         "webUrl": "https://teams.microsoft.com/msg_1"},
    ],
}
TEAMS_EVENTS = {
    "value": [
        {"id": "evt_1", "subject": "Design review",
         "start": {"dateTime": "2026-05-16T14:00:00.0000000"},
         "end": {"dateTime": "2026-05-16T15:00:00.0000000"},
         "organizer": {"emailAddress": {"name": "Priya Anand",
                                        "address": "priya@studio.test"}},
         "isOnlineMeeting": True,
         "onlineMeeting": {"joinUrl": "https://teams.microsoft.com/join/x"},
         "webLink": "https://outlook.office365.com/evt_1"},
    ],
}
TEAMS_POST_OK = {
    "id": "msg_new", "createdDateTime": "2026-05-15T12:00:00Z",
    "webUrl": "https://teams.microsoft.com/msg_new",
}


# ===========================================================================
# 1. Registration — all four connectors land on the base registry.
# ===========================================================================
class TestRegistration:
    def test_all_four_register(self):
        connectors_base.load_all_connectors()
        for host in ("speckle", "notion", "dropbox", "teams"):
            assert connectors_base.get(host) is not None, \
                f"{host} connector did not register"

    def test_hosts_and_mechanism(self):
        pairs = [
            (speckle_connector.SpeckleConnector, "speckle"),
            (notion_connector.NotionConnector, "notion"),
            (dropbox_connector.DropboxConnector, "dropbox"),
            (teams_connector.TeamsConnector, "teams"),
        ]
        for cls, host in pairs:
            inst = cls()
            assert inst.host == host
            assert inst.mechanism == "rest"
            assert inst.display_name

    def test_registry_instances_are_correct_type(self):
        connectors_base.load_all_connectors()
        assert isinstance(connectors_base.get("speckle"),
                          speckle_connector.SpeckleConnector)
        assert isinstance(connectors_base.get("notion"),
                          notion_connector.NotionConnector)
        assert isinstance(connectors_base.get("dropbox"),
                          dropbox_connector.DropboxConnector)
        assert isinstance(connectors_base.get("teams"),
                          teams_connector.TeamsConnector)


# ===========================================================================
# 2. Op sets — each connector exposes exactly the expected operations.
# ===========================================================================
class TestOpSets:
    def test_speckle_op_set(self):
        ops = {o.op_id for o in speckle_connector.SpeckleConnector().ops()}
        assert ops == {
            "speckle.list_projects", "speckle.list_models",
            "speckle.list_versions", "speckle.receive", "speckle.send",
        }

    def test_notion_op_set(self):
        ops = {o.op_id for o in notion_connector.NotionConnector().ops()}
        assert ops == {
            "notion.search", "notion.list_databases",
            "notion.query_database", "notion.get_page",
            "notion.create_page", "notion.update_page",
            "notion.append_blocks",
        }

    def test_dropbox_op_set(self):
        ops = {o.op_id for o in dropbox_connector.DropboxConnector().ops()}
        assert ops == {
            "dropbox.list_folder", "dropbox.get_metadata",
            "dropbox.list_revisions", "dropbox.download",
            "dropbox.upload", "dropbox.create_shared_link",
        }

    def test_teams_op_set(self):
        ops = {o.op_id for o in teams_connector.TeamsConnector().ops()}
        assert ops == {
            "teams.list_teams", "teams.list_channels",
            "teams.list_messages", "teams.list_meetings",
            "teams.post_message",
        }

    def test_destructive_ops_flagged(self):
        """Write operations must carry destructive=True; reads must not."""
        expected_destructive = {
            "speckle.send", "notion.create_page", "notion.update_page",
            "notion.append_blocks", "dropbox.upload",
            "dropbox.create_shared_link", "teams.post_message",
        }
        for conn in (speckle_connector.SpeckleConnector(),
                     notion_connector.NotionConnector(),
                     dropbox_connector.DropboxConnector(),
                     teams_connector.TeamsConnector()):
            for o in conn.ops():
                if o.op_id in expected_destructive:
                    assert o.destructive is True and o.kind == "action", \
                        f"{o.op_id} should be a destructive action"
                else:
                    assert o.destructive is False and o.kind == "read", \
                        f"{o.op_id} should be a non-destructive read"

    def test_every_op_has_an_implementation(self):
        """No op may ship as a stub — fn must be wired."""
        for conn in (speckle_connector.SpeckleConnector(),
                     notion_connector.NotionConnector(),
                     dropbox_connector.DropboxConnector(),
                     teams_connector.TeamsConnector()):
            for o in conn.ops():
                assert callable(o.fn), f"{o.op_id} has no fn"

    def test_op_lookup_by_id(self):
        conn = speckle_connector.SpeckleConnector()
        assert conn.op("speckle.send") is not None
        assert conn.op("speckle.nonexistent") is None


# ===========================================================================
# 3. probe() honesty — no token => unauthorized, cleanly, never raising.
# ===========================================================================
class TestProbeUnauthorized:
    """With no token, probe() must return status 'unauthorized' and a
    note pointing the user at Settings — not raise, not hit the network."""

    def test_speckle_probe_unauthorized(self):
        with patch.object(speckle_connector, "_load_token",
                          return_value=None):
            p = speckle_connector.SpeckleConnector().probe()
        assert p["status"] == "unauthorized"
        assert "token" in p["note"].lower()
        assert "settings" in p["note"].lower()

    def test_notion_probe_unauthorized(self):
        with patch.object(notion_connector, "_load_token",
                          return_value=None):
            p = notion_connector.NotionConnector().probe()
        assert p["status"] == "unauthorized"
        assert "token" in p["note"].lower()

    def test_dropbox_probe_unauthorized(self):
        with patch.object(dropbox_connector, "_load_token",
                          return_value=None):
            p = dropbox_connector.DropboxConnector().probe()
        assert p["status"] == "unauthorized"
        assert "token" in p["note"].lower()

    def test_teams_probe_unauthorized(self):
        with patch.object(teams_connector, "_load_token",
                          return_value=None):
            p = teams_connector.TeamsConnector().probe()
        assert p["status"] == "unauthorized"
        assert "token" in p["note"].lower()

    def test_probe_unauthorized_makes_no_http_call(self):
        """The unauthorized branch must short-circuit before urlopen."""
        with patch.object(speckle_connector, "_load_token",
                          return_value=None), \
             patch(UO) as uo:
            speckle_connector.SpeckleConnector().probe()
            uo.assert_not_called()

    def test_to_dict_never_raises_without_token(self):
        """Connector.to_dict() calls probe(); must stay safe offline."""
        for conn, mod in (
            (speckle_connector.SpeckleConnector(), speckle_connector),
            (notion_connector.NotionConnector(), notion_connector),
            (dropbox_connector.DropboxConnector(), dropbox_connector),
            (teams_connector.TeamsConnector(), teams_connector),
        ):
            with patch.object(mod, "_load_token", return_value=None):
                d = conn.to_dict()
            assert d["status"] == "unauthorized"
            assert isinstance(d["ops"], list) and d["ops"]


# ===========================================================================
# 4. probe() live + missing — real lightweight auth-check call.
# ===========================================================================
class TestProbeLiveAndMissing:
    def test_speckle_probe_live(self):
        with patch.object(speckle_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(SPECKLE_ACTIVE_USER)):
            p = speckle_connector.SpeckleConnector().probe()
        assert p["status"] == "live"
        assert "Aaliyah Khan" in p["note"]

    def test_speckle_probe_missing_on_network_error(self):
        with patch.object(speckle_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, side_effect=urllib.error.URLError("no route")):
            p = speckle_connector.SpeckleConnector().probe()
        assert p["status"] == "missing"
        assert "network" in p["note"].lower()

    def test_speckle_probe_unauthorized_on_gql_auth_error(self):
        """A GraphQL FORBIDDEN error (HTTP 200 body) => missing/unauth,
        never a crash."""
        with patch.object(speckle_connector, "_load_token",
                          return_value="bad"), \
             patch(UO, return_value=_mock_urlopen(SPECKLE_GQL_AUTH_ERROR)):
            p = speckle_connector.SpeckleConnector().probe()
        assert p["status"] in ("missing", "unauthorized")
        assert "token" in p["note"].lower()

    def test_notion_probe_live(self):
        with patch.object(notion_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(NOTION_ME)):
            p = notion_connector.NotionConnector().probe()
        assert p["status"] == "live"
        assert "ArchHub Bot" in p["note"]

    def test_notion_probe_unauthorized_on_401(self):
        with patch.object(notion_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, side_effect=_mock_http_error(401, "unauthorized")):
            p = notion_connector.NotionConnector().probe()
        assert p["status"] == "unauthorized"

    def test_dropbox_probe_live(self):
        with patch.object(dropbox_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(DROPBOX_ACCOUNT)):
            p = dropbox_connector.DropboxConnector().probe()
        assert p["status"] == "live"
        assert "Studio Ops" in p["note"]

    def test_dropbox_probe_missing_on_500(self):
        with patch.object(dropbox_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, side_effect=_mock_http_error(500, "boom")):
            p = dropbox_connector.DropboxConnector().probe()
        assert p["status"] == "missing"

    def test_teams_probe_live(self):
        with patch.object(teams_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(TEAMS_ME)):
            p = teams_connector.TeamsConnector().probe()
        assert p["status"] == "live"
        assert "Priya Anand" in p["note"]

    def test_teams_probe_unauthorized_on_401(self):
        with patch.object(teams_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, side_effect=_mock_http_error(401, "expired")):
            p = teams_connector.TeamsConnector().probe()
        assert p["status"] == "unauthorized"


# ===========================================================================
# 5. Speckle — response parsing against recorded fixtures.
# ===========================================================================
class TestSpeckleOps:
    def _run(self, op_id, **params):
        conn = speckle_connector.SpeckleConnector()
        return conn.op(op_id).run(**params)

    def test_list_projects_parses_streams(self):
        with patch.object(speckle_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(SPECKLE_PROJECTS)):
            r = self._run("speckle.list_projects", limit=10)
        assert r.ok is True
        assert isinstance(r.value, list) and len(r.value) == 2
        assert r.value[0]["id"] == "p_tower"
        assert r.value[0]["name"] == "Tower A"
        assert r.value[0]["model_count"] == 4

    def test_list_models_parses_branches(self):
        with patch.object(speckle_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(SPECKLE_MODELS)):
            r = self._run("speckle.list_models", project_id="p_tower")
        assert r.ok is True
        assert len(r.value) == 1
        assert r.value[0]["id"] == "m_arch"
        assert r.value[0]["version_count"] == 7

    def test_list_versions_parses_commits(self):
        with patch.object(speckle_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(SPECKLE_VERSIONS)):
            r = self._run("speckle.list_versions", project_id="p_tower",
                          model_id="m_arch")
        assert r.ok is True
        assert len(r.value) == 1
        assert r.value[0]["id"] == "v_001"
        assert r.value[0]["referenced_object"] == "obj_deadbeef"
        assert r.value[0]["author"] == "Aaliyah Khan"

    def test_receive_by_object_id(self):
        with patch.object(speckle_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(SPECKLE_OBJECT)):
            r = self._run("speckle.receive", project_id="p_tower",
                          object_id="obj_deadbeef")
        assert r.ok is True
        assert r.value["id"] == "obj_deadbeef"
        assert r.value["total_children_count"] == 128

    def test_receive_by_version_id_resolves_object(self):
        """version_id => first resolve referencedObject, then fetch it.
        Two sequential HTTP calls — both mocked."""
        with patch.object(speckle_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, side_effect=_seq_urlopen(SPECKLE_VERSION_REF,
                                                SPECKLE_OBJECT)):
            r = self._run("speckle.receive", project_id="p_tower",
                          version_id="v_001")
        assert r.ok is True
        assert r.value["id"] == "obj_deadbeef"

    def test_receive_requires_object_or_version(self):
        with patch.object(speckle_connector, "_load_token",
                          return_value="tok"):
            r = self._run("speckle.receive", project_id="p_tower")
        assert r.ok is False
        assert "object_id or version_id" in r.error

    def test_send_creates_version(self):
        with patch.object(speckle_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(SPECKLE_SEND_OK)):
            r = self._run("speckle.send", project_id="p_tower",
                          model_id="m_arch", object_id="obj_deadbeef",
                          message="Issued")
        assert r.ok is True
        assert r.value["id"] == "v_new"

    def test_send_requires_object_id(self):
        with patch.object(speckle_connector, "_load_token",
                          return_value="tok"):
            r = self._run("speckle.send", project_id="p_tower",
                          model_id="m_arch")
        assert r.ok is False
        assert "object_id" in r.error

    def test_list_projects_no_token_fails_cleanly(self):
        with patch.object(speckle_connector, "_load_token",
                          return_value=None):
            r = self._run("speckle.list_projects")
        assert r.ok is False
        assert "token" in r.error.lower()

    def test_list_models_401_message(self):
        with patch.object(speckle_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, side_effect=_mock_http_error(401, "nope")):
            r = self._run("speckle.list_models", project_id="p_tower")
        assert r.ok is False
        assert "401" in r.error and "token" in r.error.lower()

    def test_run_never_raises_on_unexpected_exception(self):
        """ConnectorOp.run wraps everything — a urlopen blowing up with a
        non-HTTP error still yields a clean failed OpResult."""
        with patch.object(speckle_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, side_effect=ValueError("kaboom")):
            r = self._run("speckle.list_projects")
        assert r.ok is False
        assert r.error


# ===========================================================================
# 6. Notion — response parsing against recorded fixtures.
# ===========================================================================
class TestNotionOps:
    def _run(self, op_id, **params):
        conn = notion_connector.NotionConnector()
        return conn.op(op_id).run(**params)

    def test_search_parses_pages_and_databases(self):
        with patch.object(notion_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(NOTION_SEARCH)):
            r = self._run("notion.search", query="project")
        assert r.ok is True
        assert len(r.value) == 2
        titles = {x["title"] for x in r.value}
        assert "Kickoff notes" in titles
        assert "Project Tracker" in titles

    def test_list_databases_parses(self):
        with patch.object(notion_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(NOTION_DATABASES)):
            r = self._run("notion.list_databases")
        assert r.ok is True
        assert len(r.value) == 1
        assert r.value[0]["title"] == "Project Tracker"
        assert "Status" in r.value[0]["property_names"]

    def test_query_database_simplifies_rows(self):
        with patch.object(notion_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(NOTION_QUERY)):
            r = self._run("notion.query_database", database_id="db_1")
        assert r.ok is True
        assert len(r.value) == 1
        row = r.value[0]
        assert row["title"] == "Design Development"
        assert row["properties"]["Status"] == "In progress"
        assert row["properties"]["Budget"] == 48000
        assert row["properties"]["Tags"] == ["phase-2", "priority"]

    def test_query_database_requires_id(self):
        with patch.object(notion_connector, "_load_token",
                          return_value="tok"):
            r = self._run("notion.query_database")
        assert r.ok is False
        assert "database_id" in r.error

    def test_query_database_rejects_bad_filter(self):
        with patch.object(notion_connector, "_load_token",
                          return_value="tok"):
            r = self._run("notion.query_database", database_id="db_1",
                          filter="not-json")
        assert r.ok is False
        assert "filter" in r.error.lower()

    def test_query_database_accepts_dict_filter(self):
        """A dict filter is passed straight through — and the body sent
        to Notion carries it."""
        captured = {}

        def _capture(req, *a, **k):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _mock_urlopen(NOTION_QUERY)

        flt = {"property": "Status", "status": {"equals": "In progress"}}
        with patch.object(notion_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, side_effect=_capture):
            r = self._run("notion.query_database", database_id="db_1",
                          filter=flt)
        assert r.ok is True
        assert captured["body"]["filter"] == flt

    def test_get_page_parses(self):
        with patch.object(notion_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(NOTION_PAGE)):
            r = self._run("notion.get_page", page_id="pg_1")
        assert r.ok is True
        assert r.value["id"] == "pg_1"
        assert r.value["title"] == "Kickoff notes"

    def test_create_page_writes(self):
        with patch.object(notion_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(NOTION_CREATED)):
            r = self._run("notion.create_page", parent_id="db_1",
                          title="New site visit")
        assert r.ok is True
        assert r.value["id"] == "pg_new"

    def test_create_page_requires_parent(self):
        with patch.object(notion_connector, "_load_token",
                          return_value="tok"):
            r = self._run("notion.create_page", title="x")
        assert r.ok is False
        assert "parent_id" in r.error

    def test_update_page_requires_something_to_change(self):
        with patch.object(notion_connector, "_load_token",
                          return_value="tok"):
            r = self._run("notion.update_page", page_id="pg_1")
        assert r.ok is False

    def test_append_blocks_from_text(self):
        with patch.object(notion_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(NOTION_APPEND_OK)):
            r = self._run("notion.append_blocks", block_id="pg_1",
                          text="A new note")
        assert r.ok is True
        assert r.value["appended"] == 1

    def test_notion_404_explains_sharing(self):
        """Notion 404 often means 'not shared with the integration' —
        the message must say so."""
        with patch.object(notion_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, side_effect=_mock_http_error(
                 404, json.dumps({"message": "Could not find database"}))):
            r = self._run("notion.query_database", database_id="db_x")
        assert r.ok is False
        assert "shared" in r.error.lower() or "404" in r.error

    def test_notion_429_retries_then_succeeds(self):
        """First call 429, retry succeeds — one transparent backoff."""
        with patch.object(notion_connector, "_load_token",
                          return_value="tok"), \
             patch.object(notion_connector.time, "sleep"), \
             patch(UO, side_effect=_seq_urlopen(
                 _mock_http_error(429, "slow down"),
                 NOTION_SEARCH)):
            r = self._run("notion.search", query="x")
        assert r.ok is True
        assert len(r.value) == 2

    def test_search_no_token_fails_cleanly(self):
        with patch.object(notion_connector, "_load_token",
                          return_value=None):
            r = self._run("notion.search")
        assert r.ok is False
        assert "token" in r.error.lower()


# ===========================================================================
# 7. Dropbox — response parsing against recorded fixtures.
# ===========================================================================
class TestDropboxOps:
    def _run(self, op_id, **params):
        conn = dropbox_connector.DropboxConnector()
        return conn.op(op_id).run(**params)

    def test_list_folder_parses_entries(self):
        with patch.object(dropbox_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(DROPBOX_LIST_FOLDER)):
            r = self._run("dropbox.list_folder", path="/Project")
        assert r.ok is True
        assert len(r.value) == 2
        kinds = {e["type"] for e in r.value}
        assert kinds == {"folder", "file"}
        filerec = next(e for e in r.value if e["type"] == "file")
        assert filerec["name"] == "site-plan.pdf"
        assert filerec["size"] == 880123

    def test_list_folder_normalises_root(self):
        """An empty/'/' path must be sent to Dropbox as '' (root)."""
        captured = {}

        def _capture(req, *a, **k):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _mock_urlopen(DROPBOX_LIST_FOLDER)

        with patch.object(dropbox_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, side_effect=_capture):
            self._run("dropbox.list_folder", path="/")
        assert captured["body"]["path"] == ""

    def test_get_metadata_parses(self):
        with patch.object(dropbox_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(DROPBOX_METADATA)):
            r = self._run("dropbox.get_metadata",
                          path="/Project/site-plan.pdf")
        assert r.ok is True
        assert r.value["type"] == "file"
        assert r.value["rev"] == "0a1b2c"

    def test_get_metadata_rejects_root(self):
        with patch.object(dropbox_connector, "_load_token",
                          return_value="tok"):
            r = self._run("dropbox.get_metadata", path="")
        assert r.ok is False
        assert "path" in r.error.lower()

    def test_list_revisions_parses(self):
        with patch.object(dropbox_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(DROPBOX_REVISIONS)):
            r = self._run("dropbox.list_revisions",
                          path="/Project/site-plan.pdf")
        assert r.ok is True
        assert len(r.value["revisions"]) == 2
        assert r.value["revisions"][0]["rev"] == "0a1b2c"

    def test_download_returns_base64(self):
        """download is a content-endpoint call; the body bytes come back
        base64-encoded with metadata from the result header."""
        raw = b"%PDF-1.7 fake bytes"
        meta_hdr = json.dumps({"name": "site-plan.pdf", "size": len(raw),
                               "rev": "0a1b2c",
                               "path_display": "/Project/site-plan.pdf"})
        with patch.object(dropbox_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(
                 raw, headers={"Dropbox-API-Result": meta_hdr})):
            r = self._run("dropbox.download",
                          path="/Project/site-plan.pdf")
        assert r.ok is True
        import base64 as _b64
        assert _b64.b64decode(r.value["content_base64"]) == raw
        assert r.value["name"] == "site-plan.pdf"

    def test_upload_writes_text(self):
        with patch.object(dropbox_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(DROPBOX_UPLOAD_OK)):
            r = self._run("dropbox.upload", path="/Project/notes.txt",
                          text="hello world")
        assert r.ok is True
        assert r.value["name"] == "notes.txt"

    def test_upload_requires_content(self):
        with patch.object(dropbox_connector, "_load_token",
                          return_value="tok"):
            r = self._run("dropbox.upload", path="/Project/notes.txt")
        assert r.ok is False
        assert "content" in r.error.lower() or "text" in r.error.lower()

    def test_upload_rejects_bad_base64(self):
        with patch.object(dropbox_connector, "_load_token",
                          return_value="tok"):
            r = self._run("dropbox.upload", path="/x.bin",
                          content_base64="!!!not base64!!!")
        assert r.ok is False
        assert "base64" in r.error.lower()

    def test_create_shared_link_parses(self):
        with patch.object(dropbox_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(DROPBOX_SHARED_LINK)):
            r = self._run("dropbox.create_shared_link",
                          path="/Project/site-plan.pdf")
        assert r.ok is True
        assert r.value["url"].startswith("https://www.dropbox.com/")

    def test_create_shared_link_handles_existing_409(self):
        """409 shared_link_already_exists => fall back to listing the
        existing link, still ok."""
        existing = {"links": [{"url": "https://www.dropbox.com/s/e/x",
                               "name": "site-plan.pdf",
                               "path_lower": "/project/site-plan.pdf"}]}
        with patch.object(dropbox_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, side_effect=_seq_urlopen(
                 _mock_http_error(409, json.dumps(
                     {"error_summary": "shared_link_already_exists/"})),
                 existing)):
            r = self._run("dropbox.create_shared_link",
                          path="/Project/site-plan.pdf")
        assert r.ok is True
        assert r.value["existing"] is True

    def test_dropbox_401_message(self):
        with patch.object(dropbox_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, side_effect=_mock_http_error(401, "bad token")):
            r = self._run("dropbox.list_folder", path="/Project")
        assert r.ok is False
        assert "401" in r.error and "token" in r.error.lower()

    def test_list_folder_no_token_fails_cleanly(self):
        with patch.object(dropbox_connector, "_load_token",
                          return_value=None):
            r = self._run("dropbox.list_folder")
        assert r.ok is False
        assert "token" in r.error.lower()


# ===========================================================================
# 8. Teams — response parsing against recorded fixtures.
# ===========================================================================
class TestTeamsOps:
    def _run(self, op_id, **params):
        conn = teams_connector.TeamsConnector()
        return conn.op(op_id).run(**params)

    def test_list_teams_parses(self):
        with patch.object(teams_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(TEAMS_JOINED)):
            r = self._run("teams.list_teams")
        assert r.ok is True
        assert len(r.value) == 2
        assert r.value[0]["id"] == "team_1"
        assert r.value[0]["name"] == "Tower A Project"

    def test_list_channels_parses(self):
        with patch.object(teams_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(TEAMS_CHANNELS)):
            r = self._run("teams.list_channels", team_id="team_1")
        assert r.ok is True
        assert len(r.value) == 2
        assert r.value[1]["name"] == "Structure"

    def test_list_channels_requires_team_id(self):
        with patch.object(teams_connector, "_load_token",
                          return_value="tok"):
            r = self._run("teams.list_channels")
        assert r.ok is False
        assert "team_id" in r.error

    def test_list_messages_parses_and_strips_html(self):
        with patch.object(teams_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(TEAMS_MESSAGES)):
            r = self._run("teams.list_messages", team_id="team_1",
                          channel_id="ch_1")
        assert r.ok is True
        assert len(r.value) == 1
        msg = r.value[0]
        assert msg["from"] == "Priya Anand"
        # HTML body must be flattened to plain text.
        assert msg["text"] == "Latest set is up."
        assert "<" not in msg["text"]

    def test_list_messages_requires_channel_id(self):
        with patch.object(teams_connector, "_load_token",
                          return_value="tok"):
            r = self._run("teams.list_messages", team_id="team_1")
        assert r.ok is False
        assert "channel_id" in r.error

    def test_list_meetings_parses(self):
        with patch.object(teams_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(TEAMS_EVENTS)):
            r = self._run("teams.list_meetings")
        assert r.ok is True
        assert len(r.value) == 1
        evt = r.value[0]
        assert evt["subject"] == "Design review"
        assert evt["is_online_meeting"] is True
        assert evt["join_url"].startswith("https://teams.microsoft.com/")

    def test_post_message_writes(self):
        with patch.object(teams_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(TEAMS_POST_OK)):
            r = self._run("teams.post_message", team_id="team_1",
                          channel_id="ch_1", text="Latest set posted")
        assert r.ok is True
        assert r.value["id"] == "msg_new"

    def test_post_message_requires_text(self):
        with patch.object(teams_connector, "_load_token",
                          return_value="tok"):
            r = self._run("teams.post_message", team_id="team_1",
                          channel_id="ch_1", text="")
        assert r.ok is False
        assert "text" in r.error.lower()

    def test_teams_403_explains_scope(self):
        """A 403 must point the user at the missing delegated scope."""
        with patch.object(teams_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, side_effect=_mock_http_error(
                 403, json.dumps({"error": {"message": "Forbidden"}}))):
            r = self._run("teams.list_messages", team_id="team_1",
                          channel_id="ch_1")
        assert r.ok is False
        assert "scope" in r.error.lower() or "403" in r.error

    def test_teams_paginates_odata_nextlink(self):
        """list_teams must follow @odata.nextLink across pages."""
        page1 = {"value": [{"id": "team_1", "displayName": "A"}],
                 "@odata.nextLink":
                     "https://graph.microsoft.com/v1.0/me/joinedTeams"
                     "?$skiptoken=X"}
        page2 = {"value": [{"id": "team_2", "displayName": "B"}]}
        with patch.object(teams_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, side_effect=_seq_urlopen(page1, page2)):
            r = self._run("teams.list_teams")
        assert r.ok is True
        assert {t["id"] for t in r.value} == {"team_1", "team_2"}

    def test_list_teams_no_token_fails_cleanly(self):
        with patch.object(teams_connector, "_load_token",
                          return_value=None):
            r = self._run("teams.list_teams")
        assert r.ok is False
        assert "token" in r.error.lower()


# ===========================================================================
# 9. Cross-cutting — run_op resolution through the base registry.
# ===========================================================================
class TestRunOpIntegration:
    def test_run_op_resolves_and_runs(self):
        """connectors.base.run_op must route an op_id to the right
        connector — exercised offline with a mocked HTTP layer."""
        connectors_base.load_all_connectors()
        with patch.object(notion_connector, "_load_token",
                          return_value="tok"), \
             patch(UO, return_value=_mock_urlopen(NOTION_SEARCH)):
            r = connectors_base.run_op("notion.search", query="x")
        assert r.ok is True
        assert r.op_id == "notion.search"

    def test_run_op_unknown_host_fails_cleanly(self):
        r = connectors_base.run_op("nosuchhost.doit")
        assert r.ok is False
        assert "no connector" in r.error.lower()
