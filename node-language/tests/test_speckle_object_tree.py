"""Speckle object-tree send + receive — CON-03 and CON-05.

These two gaps were the difference between "the canvas can talk to a cloud
Speckle server about *versions*" and "the canvas can actually push/pull real
*geometry*":

  CON-03 — `speckle.send` only re-committed an existing object hash; there was
           no way to upload a freshly-built object tree, so "Send objects"
           could never push canvas geometry. Fix: a `speckle.create_object`
           op (and `speckle.send(objects=...)`) that serializes a specklepy
           `Base` tree with specklepy's OWN content hash and POSTs the whole
           batch to `/objects/<projectId>`.

  CON-05 — `speckle.receive` fetched only the ROOT object and reported
           `totalChildrenCount` but never walked the detached child refs, so
           any real (chunked / detached) model came back truncated to its
           root. Fix: when `totalChildrenCount > 0` the receiver walks the
           detached descendants via GraphQL `children` (paginated) and
           returns them resolved.

All HTTP is mocked at `urllib.request.urlopen` — the same seam the rest of the
connector suite mocks. The object hash is NEVER asserted against a hand-rolled
value: we let specklepy compute it and only assert the connector commits/uses
exactly that hash.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from connectors import speckle_connector as sc  # noqa: E402

# specklepy is the canonical serializer (the spec mandates we import its hash,
# not reimplement). If it's genuinely absent the object-tree ops can't run, so
# the whole module is skipped honestly rather than faked.
specklepy = pytest.importorskip("specklepy")
from specklepy.objects.base import Base  # noqa: E402

UO = "urllib.request.urlopen"


# ---------------------------------------------------------------------------
# urlopen doubles
# ---------------------------------------------------------------------------
def _resp(body):
    """One mocked urlopen context manager yielding `body`."""
    if isinstance(body, (dict, list)):
        raw = json.dumps(body).encode("utf-8")
    elif isinstance(body, bytes):
        raw = body
    else:
        raw = str(body).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = raw
    hdrs = MagicMock()
    hdrs.get.side_effect = lambda k, d=None: None
    resp.headers = hdrs
    cm = MagicMock()
    cm.__enter__ = lambda _s: resp
    cm.__exit__ = lambda _s, *_a: False
    return cm


def _sequence(*bodies):
    """A urlopen side_effect that records each request URL + yields bodies
    in order. Returns (side_effect_callable, recorded_requests_list)."""
    it = iter([_resp(b) for b in bodies])
    recorded: list = []

    def _next(req, *_a, **_k):
        recorded.append(req)
        return next(it)

    return _next, recorded


def _decode_upload_batch(req) -> list:
    """Pull the gzipped JSON object-array back out of a multipart upload."""
    body = req.data
    assert b"batch-1" in body, "upload must use the multipart batch part"
    start = body.find(b"\r\n\r\n") + 4
    end = body.rfind(b"\r\n----")
    gz = body[start:end]
    return json.loads(gzip.decompress(gz).decode("utf-8"))


def _sample_tree() -> tuple[Base, Base, Base]:
    """A small detached tree: root -> @walls[wall -> @child]."""
    root = Base()
    root.name = "canvas"
    wall = Base()
    wall.height = 3000.0
    child = Base()
    child.tag = "stud"
    wall["@child"] = child
    root["@walls"] = [wall]
    return root, wall, child


# ===========================================================================
# CON-03 — speckle.create_object / speckle.send upload an object tree
#   selector: -k "speckle and (upload or create_object)"
# ===========================================================================
class TestSpeckleUploadCreateObject:

    def test_speckle_create_object_uploads_tree_and_returns_specklepy_hash(
            self):
        """A mocked POST to /objects/<pid> returns a hash `send` commits.

        The hash MUST equal specklepy's own serialization of the same tree —
        proving we import the hash, never reinvent it — and the uploaded
        batch must contain every object in the tree (root + descendants).
        """
        root, _wall, _child = _sample_tree()

        # Independently compute what specklepy says the root hash + object set
        # are, so the assertion is anchored to specklepy, not to our code.
        from specklepy.serialization.base_object_serializer import (
            BaseObjectSerializer,
        )
        from specklepy.transports.memory import MemoryTransport
        mem = MemoryTransport()
        expected_id, _ = BaseObjectSerializer(
            write_transports=[mem]).write_json(root)
        expected_count = len(mem.objects)
        assert expected_count >= 3  # root + wall + child all detached

        side_effect, recorded = _sequence(b"")  # upload returns empty 200
        with patch.object(sc, "_load_token", return_value="tok"), \
                patch(UO, side_effect=side_effect):
            r = sc._op_create_object(project_id="p_tower", objects=root)

        assert r.ok is True, r.error
        # The returned id is specklepy's OWN content hash.
        assert r.value["id"] == expected_id
        assert r.value["object_id"] == expected_id
        assert r.value["object_count"] == expected_count

        # Exactly one POST, to the object endpoint, carrying the whole tree.
        assert len(recorded) == 1
        req = recorded[0]
        assert req.full_url.endswith("/objects/p_tower")
        assert req.method == "POST"
        uploaded = _decode_upload_batch(req)
        uploaded_ids = {o.get("id") for o in uploaded}
        assert expected_id in uploaded_ids
        assert len(uploaded_ids) == expected_count

    def test_speckle_send_uploads_objects_then_commits_that_hash(self):
        """`speckle.send(objects=...)` is the canvas "Send objects" path:
        upload the tree, then commit a version referencing the uploaded
        root hash. Two round-trips: POST /objects/<pid>, then the version
        mutation to /graphql referencing the SAME hash."""
        root, _wall, _child = _sample_tree()

        from specklepy.serialization.base_object_serializer import (
            BaseObjectSerializer,
        )
        from specklepy.transports.memory import MemoryTransport
        expected_id, _ = BaseObjectSerializer(
            write_transports=[MemoryTransport()]).write_json(root)

        version_ok = {"data": {"versionMutations": {"create": {
            "id": "v_new", "message": "Issued",
            "referencedObject": expected_id,
            "createdAt": "2026-06-17T00:00:00Z"}}}}
        side_effect, recorded = _sequence(b"", version_ok)
        with patch.object(sc, "_load_token", return_value="tok"), \
                patch(UO, side_effect=side_effect):
            r = sc._op_send(project_id="p_tower", model_id="m_arch",
                            objects=root, message="Issued")

        assert r.ok is True, r.error
        assert r.value["id"] == "v_new"
        assert r.value["referenced_object"] == expected_id
        assert r.value["uploaded_objects"] >= 3

        # call 1 = upload, call 2 = version mutation referencing our hash.
        assert recorded[0].full_url.endswith("/objects/p_tower")
        assert recorded[1].full_url.endswith("/graphql")
        gql_body = json.loads(recorded[1].data.decode("utf-8"))
        assert gql_body["variables"]["input"]["objectId"] == expected_id
        assert gql_body["variables"]["input"]["projectId"] == "p_tower"

    def test_speckle_send_still_accepts_existing_object_id(self):
        """Back-compat: with no `objects`, `send` references an existing
        hash and commits without any upload (one round-trip, /graphql)."""
        version_ok = {"data": {"versionMutations": {"create": {
            "id": "v_ref", "message": "ref",
            "referencedObject": "deadbeef", "createdAt": "t"}}}}
        side_effect, recorded = _sequence(version_ok)
        with patch.object(sc, "_load_token", return_value="tok"), \
                patch(UO, side_effect=side_effect):
            r = sc._op_send(project_id="p_tower", model_id="m_arch",
                            object_id="deadbeef")
        assert r.ok is True, r.error
        assert r.value["id"] == "v_ref"
        assert len(recorded) == 1
        assert recorded[0].full_url.endswith("/graphql")

    def test_speckle_send_without_objects_or_id_fails_cleanly(self):
        with patch.object(sc, "_load_token", return_value="tok"):
            r = sc._op_send(project_id="p_tower", model_id="m_arch")
        assert r.ok is False
        assert "objects" in r.error and "object_id" in r.error

    def test_speckle_create_object_op_is_registered_and_destructive(self):
        conn = sc.SpeckleConnector()
        op = conn.op("speckle.create_object")
        assert op is not None
        assert op.destructive is True
        assert {p.id for p in op.inputs} >= {"project_id", "objects"}


# ===========================================================================
# CON-05 — speckle.receive dereferences detached children
#   selector: -k speckle_receive_children
# ===========================================================================
class TestSpeckleReceiveChildren:

    def _root_payload(self, tcc):
        return {"data": {"project": {"object": {
            "id": "OID", "speckleType": "Base",
            "totalChildrenCount": tcc,
            "data": {"name": "root", "@walls": [{"referencedId": "c1"}]}}}}}

    def _children_page(self, objects, cursor):
        return {"data": {"project": {"object": {
            "id": "OID", "totalChildrenCount": 3,
            "children": {"totalCount": 3, "cursor": cursor,
                         "objects": objects}}}}}

    def test_speckle_receive_children_dereferences_detached_tree(self):
        """A mocked object with totalChildrenCount>0 triggers child fetches
        and returns the resolved children — not just the root."""
        root = self._root_payload(3)
        page1 = self._children_page(
            [{"id": "c1", "data": {"h": 1}},
             {"id": "c2", "data": {"h": 2}}], cursor="cur2")
        page2 = self._children_page(
            [{"id": "c3", "data": {"h": 3}}], cursor=None)
        side_effect, recorded = _sequence(root, page1, page2)
        with patch.object(sc, "_load_token", return_value="tok"), \
                patch(UO, side_effect=side_effect):
            r = sc._op_receive(project_id="p_tower", object_id="OID")

        assert r.ok is True, r.error
        assert r.value["total_children_count"] == 3
        # The whole tree came back, not just the root.
        assert r.value["children_count"] == 3
        assert set(r.value["children"].keys()) == {"c1", "c2", "c3"}
        # Flat root+children map.
        assert set(r.value["objects"].keys()) == {"OID", "c1", "c2", "c3"}
        # Root fetch + 2 child pages (pagination followed the cursor).
        assert len(recorded) == 3

    def test_speckle_receive_children_skipped_when_no_children(self):
        """A leaf object (totalChildrenCount == 0) does NOT trigger a child
        walk — a single round-trip, root only."""
        root = self._root_payload(0)
        side_effect, recorded = _sequence(root)
        with patch.object(sc, "_load_token", return_value="tok"), \
                patch(UO, side_effect=side_effect):
            r = sc._op_receive(project_id="p_tower", object_id="OID")
        assert r.ok is True, r.error
        assert r.value["total_children_count"] == 0
        assert "children" not in r.value  # no dereference attempted
        assert len(recorded) == 1

    def test_speckle_receive_children_can_be_disabled(self):
        """`dereference=False` keeps the cheap root-only peek even when the
        object has children."""
        root = self._root_payload(3)
        side_effect, recorded = _sequence(root)
        with patch.object(sc, "_load_token", return_value="tok"), \
                patch(UO, side_effect=side_effect):
            r = sc._op_receive(project_id="p_tower", object_id="OID",
                               dereference=False)
        assert r.ok is True, r.error
        assert r.value["total_children_count"] == 3
        assert "children" not in r.value
        assert len(recorded) == 1  # no child fetch

    def test_speckle_receive_children_propagates_child_fetch_error(self):
        """If the child walk fails, the whole receive fails honestly —
        it does not silently return a truncated tree as success."""
        root = self._root_payload(2)
        gql_err = {"errors": [{"message": "boom",
                               "extensions": {"code": "INTERNAL"}}]}
        side_effect, _recorded = _sequence(root, gql_err)
        with patch.object(sc, "_load_token", return_value="tok"), \
                patch(UO, side_effect=side_effect):
            r = sc._op_receive(project_id="p_tower", object_id="OID")
        assert r.ok is False
        assert "boom" in r.error
