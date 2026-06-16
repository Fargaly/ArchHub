"""Speckle object-creation / upload path — CON-03.

Before this slice the Speckle connector's `speckle.send` could ONLY
re-commit an object hash that already lived on the server: `_op_send`
required `object_id` and there was NO path to actually upload (create) an
object tree. `speckle.receive` could pull objects down, but nothing could
push a fresh tree up — a half-duplex connector.

This suite gates the real fix:
  * `speckle.create_object` exists and uploads an object batch to the
    REST endpoint `POST <server>/objects/<projectId>`, returning the
    root object's content-addressed hash.
  * `speckle.send` accepts a raw `objects` tree, UPLOADS it, then commits
    the resulting hash (full send), while still honouring a pre-existing
    `object_id` for back-compat.

The Speckle server (HTTP) is mocked: `urllib.request.urlopen` is patched
to record every request and to answer the object-upload POST + the commit
GraphQL mutation. No network, no token, no Docker.

On origin/main (pre-fix) `speckle.create_object` does not exist and
`_op_send` rejects a call that has `objects` but no `object_id`, so the
upload/create_object tests below go RED. After the fix they go GREEN.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import urllib.error
import zlib
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import connectors.speckle_connector as sc  # noqa: E402
from connectors.base import run_op  # noqa: E402


PID = "proj123"
MID = "model456"


# ---------------------------------------------------------------------------
# Mock plumbing — a fake Speckle HTTP server over urllib.
# ---------------------------------------------------------------------------
class _FakeResp:
    """A minimal context-manager response like urlopen returns."""

    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _decode_request(req):
    """Pull (url, method, headers, body-bytes) out of a urllib Request."""
    url = req.full_url
    method = req.get_method()
    headers = {k.lower(): v for k, v in (req.header_items() or [])}
    data = req.data
    if data is not None and not isinstance(data, (bytes, bytearray)):
        data = bytes(data)
    return url, method, headers, data


def _extract_uploaded_objects(body: bytes) -> list:
    """Decode the gzipped multipart object batch the connector uploads.

    The connector sends ONE multipart file part whose payload is a
    gzip-compressed JSON array of objects (exactly specklepy's shape). We
    pull the gzip member out of the multipart envelope and inflate it.
    """
    # The gzip stream starts with the magic bytes 0x1f 0x8b. Find them and
    # inflate from there. A zlib decompressor with wbits=31 (gzip) stops
    # cleanly at the member end and leaves the trailing multipart boundary
    # bytes in `.unused_data` — unlike gzip.decompress, which errors on the
    # trailing `\r\n--boundary--`.
    idx = body.find(b"\x1f\x8b")
    assert idx != -1, "no gzip member found in multipart upload body"
    dec = zlib.decompressobj(wbits=31)
    raw = dec.decompress(body[idx:])
    raw += dec.flush()
    return json.loads(raw.decode("utf-8"))


class FakeSpeckle:
    """Records requests + answers object-upload POSTs and GraphQL."""

    def __init__(self):
        self.requests: list[dict] = []
        self.uploaded_batches: list[list] = []

    def urlopen(self, req, timeout=None):
        url, method, headers, data = _decode_request(req)
        entry = {"url": url, "method": method, "headers": headers,
                 "data": data}
        self.requests.append(entry)

        # --- object upload: POST <server>/objects/<projectId> -----------
        if "/objects/" in url and method == "POST":
            objs = _extract_uploaded_objects(data)
            self.uploaded_batches.append(objs)
            # Speckle's object endpoint returns 201 with a tiny text body.
            return _FakeResp(b"", status=201)

        # --- GraphQL: the commit mutation (and anything else) -----------
        if url.endswith("/graphql") and method == "POST":
            payload = json.loads(data.decode("utf-8"))
            q = payload.get("query") or ""
            if "versionMutations" in q:
                referenced = (payload.get("variables") or {}) \
                    .get("input", {}).get("objectId")
                body = json.dumps({
                    "data": {"versionMutations": {"create": {
                        "id": "ver-aaaa1111",
                        "message": "Pushed from ArchHub",
                        "referencedObject": referenced,
                        "createdAt": "2026-06-16T00:00:00Z",
                    }}}
                }).encode("utf-8")
                return _FakeResp(body, status=200)
            # Default empty GraphQL OK.
            return _FakeResp(json.dumps({"data": {}}).encode("utf-8"))

        raise AssertionError(f"unexpected request: {method} {url}")


@pytest.fixture
def fake_speckle(monkeypatch):
    fs = FakeSpeckle()
    # Token gate: pretend a PAT is configured.
    monkeypatch.setattr(sc, "_load_token", lambda: "fake-pat-token")
    # Stable server URL so we can assert on the path.
    monkeypatch.setattr(sc, "_server_url",
                        lambda: "https://speckle.example.com")
    # Route ALL HTTP through the fake server.
    monkeypatch.setattr(sc.urllib.request, "urlopen", fs.urlopen)
    return fs


def _expected_root_hash(obj: dict) -> str:
    """The content-addressed id the connector should compute for `obj`
    (sans any id placeholder) — sha256(canonical-json)[:32]."""
    body = {k: v for k, v in obj.items() if k != "id"}
    canonical = json.dumps(body, separators=(",", ":"), sort_keys=True,
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# 1. The create_object op exists with the right shape.
# ---------------------------------------------------------------------------
def test_speckle_create_object_op_registered():
    from connectors.base import all_connectors
    speckle = next(c for c in all_connectors() if c.host == "speckle")
    op = next((o for o in speckle.ops()
               if o.op_id == "speckle.create_object"), None)
    assert op is not None, "speckle.create_object op is missing"
    assert op.kind == "action"
    assert op.destructive is True
    param_ids = {p.id for p in op.inputs}
    assert "objects" in param_ids
    assert "project_id" in param_ids


# ---------------------------------------------------------------------------
# 2. create_object uploads the tree and returns the root hash.
# ---------------------------------------------------------------------------
def test_speckle_create_object_uploads_tree_returns_hash(fake_speckle):
    obj = {"speckle_type": "Base", "name": "Wall-1", "height": 3000}
    res = run_op("speckle.create_object", project_id=PID, objects=obj)
    assert res.ok, res.error

    # The object batch hit the REST upload endpoint for THIS project.
    upload_reqs = [r for r in fake_speckle.requests
                   if "/objects/" in r["url"] and r["method"] == "POST"]
    assert len(upload_reqs) == 1, "expected exactly one object upload POST"
    assert upload_reqs[0]["url"].endswith(f"/objects/{PID}")
    assert "bearer" in upload_reqs[0]["headers"].get("authorization",
                                                     "").lower()

    # The returned hash is the content-addressed id of the root object.
    expected = _expected_root_hash(obj)
    assert res.value["object_id"] == expected
    assert res.value["root_id"] == expected
    assert res.value["count"] == 1

    # And the uploaded object actually carries that id (content-addressed).
    uploaded = fake_speckle.uploaded_batches[0]
    assert uploaded[0]["id"] == expected


def test_speckle_create_object_uploads_a_list_of_objects(fake_speckle):
    objs = [
        {"speckle_type": "Collection", "name": "root"},
        {"speckle_type": "Base", "name": "child"},
    ]
    res = run_op("speckle.create_object", project_id=PID, objects=objs)
    assert res.ok, res.error
    assert res.value["count"] == 2
    assert fake_speckle.uploaded_batches[0][0]["name"] == "root"
    # Root hash is the FIRST object's content id.
    assert res.value["root_id"] == _expected_root_hash(objs[0])


def test_speckle_create_object_accepts_json_string(fake_speckle):
    obj = {"speckle_type": "Base", "v": 7}
    res = run_op("speckle.create_object", project_id=PID,
                 objects=json.dumps(obj))
    assert res.ok, res.error
    assert res.value["root_id"] == _expected_root_hash(obj)


# ---------------------------------------------------------------------------
# 3. send UPLOADS an object tree, then commits the returned hash.
#    (This is the core gap: "speckle.send uploads no object tree".)
# ---------------------------------------------------------------------------
def test_speckle_send_uploads_object_tree_then_commits(fake_speckle):
    obj = {"speckle_type": "Base", "name": "Mass", "volume": 1234}
    res = run_op("speckle.send", project_id=PID, model_id=MID, objects=obj)
    assert res.ok, res.error

    # (a) the object tree was uploaded to /objects/<pid> ...
    upload_reqs = [r for r in fake_speckle.requests
                   if "/objects/" in r["url"] and r["method"] == "POST"]
    assert len(upload_reqs) == 1, "send did not upload the object tree"
    assert upload_reqs[0]["url"].endswith(f"/objects/{PID}")

    # (b) ... and the commit referenced the uploaded root hash.
    expected = _expected_root_hash(obj)
    graphql_reqs = [r for r in fake_speckle.requests
                    if r["url"].endswith("/graphql")]
    assert graphql_reqs, "no GraphQL commit was sent"
    commit_payload = json.loads(graphql_reqs[-1]["data"].decode("utf-8"))
    sent_object_id = (commit_payload["variables"]["input"]["objectId"])
    assert sent_object_id == expected, \
        "commit must reference the freshly-uploaded object hash"

    # (c) the result advertises the upload + the committed object.
    assert res.value["uploaded"] is True
    assert res.value["uploaded_count"] == 1
    assert res.value["object_id"] == expected
    assert res.value["referenced_object"] == expected
    assert res.value["id"] == "ver-aaaa1111"


def test_speckle_send_existing_hash_skips_upload(fake_speckle):
    """Back-compat: passing object_id commits WITHOUT any upload POST."""
    res = run_op("speckle.send", project_id=PID, model_id=MID,
                 object_id="deadbeefcafe0000deadbeefcafe0000")
    assert res.ok, res.error
    upload_reqs = [r for r in fake_speckle.requests
                   if "/objects/" in r["url"] and r["method"] == "POST"]
    assert upload_reqs == [], "object_id path must not upload anything"
    assert res.value["uploaded"] is False
    assert res.value["referenced_object"] == \
        "deadbeefcafe0000deadbeefcafe0000"


def test_speckle_send_requires_object_or_objects(fake_speckle):
    """With neither object_id nor objects, send fails cleanly (no HTTP)."""
    res = run_op("speckle.send", project_id=PID, model_id=MID)
    assert not res.ok
    assert "object_id" in res.error or "objects" in res.error
    assert fake_speckle.requests == [], "must not touch the network"


# ---------------------------------------------------------------------------
# 4. Upload failures surface honestly (never fabricated success).
# ---------------------------------------------------------------------------
def test_speckle_create_object_surfaces_http_error(monkeypatch):
    monkeypatch.setattr(sc, "_load_token", lambda: "fake-pat-token")
    monkeypatch.setattr(sc, "_server_url",
                        lambda: "https://speckle.example.com")

    def _boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden",
                                     hdrs=None, fp=io.BytesIO(b""))

    monkeypatch.setattr(sc.urllib.request, "urlopen", _boom)
    res = run_op("speckle.create_object", project_id=PID,
                 objects={"speckle_type": "Base"})
    assert not res.ok
    assert "403" in res.error or "denied" in res.error.lower()


def test_speckle_create_object_rejects_bad_payload(fake_speckle):
    res = run_op("speckle.create_object", project_id=PID, objects=12345)
    assert not res.ok
    assert "object" in res.error.lower()
    # Nothing should have been uploaded for an invalid payload.
    assert fake_speckle.uploaded_batches == []
