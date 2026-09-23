"""Driver for tests/test_zero_idle_growth.py: one phase per process.

Run by the court with an explicit source root first on sys.path, so the old
graph is written by OLD source bytes and then opened by the NEW source bytes
under test ("old graph + new code": a fresh fixture built by the code under
test cannot fail this court). Nothing here touches an installed application,
the live graph, or any user state; every path is under the court's tmp dir.

  python zero_idle_growth_driver.py build-old <source> <state-dir>
  python zero_idle_growth_driver.py idle <source> <state-dir> <result.json>
  python zero_idle_growth_driver.py undo-old <source> <state-dir> <result.json>
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import traceback


MODE, SOURCE, STATE = sys.argv[1], Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
sys.path.insert(0, str(SOURCE))

from nodelang import universal_cell  # noqa: E402
from nodelang.application_server import ApplicationServer  # noqa: E402
from nodelang.cell_secret_keys import MemorySigningKeyProvider  # noqa: E402

try:  # absent in releases before the commit gate
    from nodelang import commit_intent
except ImportError:
    commit_intent = None

GRAPH = STATE / "graph.sqlite3"
INTERVAL_SECONDS = 3400.0  # beyond the presence lease, inside the browser renewal lead
INTERVALS = 10


def keys():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"r" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"s" * 32)
    return provider


def pipe_keys():
    return MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"t" * 32)


def counts():
    connection = sqlite3.connect(
        "file:%s?mode=ro" % GRAPH.as_posix(), uri=True, timeout=30
    )
    try:
        return list(connection.execute(
            "SELECT (SELECT MAX(revision) FROM revisions), "
            "(SELECT COUNT(*) FROM cell_versions), "
            "(SELECT COUNT(*) FROM current_cells)"
        ).fetchone())
    finally:
        connection.close()


def cells_at(revision):
    connection = sqlite3.connect(
        "file:%s?mode=ro" % GRAPH.as_posix(), uri=True, timeout=30
    )
    try:
        return connection.execute(
            "SELECT COUNT(*) FROM cell_versions WHERE revision = ?", (revision,)
        ).fetchone()[0]
    finally:
        connection.close()


def user_action(reason):
    if commit_intent is None:
        return contextlib.nullcontext()
    return commit_intent.declare(
        commit_intent.USER_ACTION, actor="founder", reason=reason
    )


def open_server(**extra):
    return ApplicationServer(
        universal_state_path=GRAPH,
        universal_key_provider=keys(),
        universal_workspace_root=STATE,
        **extra,
    )


COMMITS = []


def trace_commits(phase):
    original = universal_cell.CellStore.commit

    def traced(self, expected_revision, *, create=(), replace=(), precommit_guard=None):
        create, replace = tuple(create), tuple(replace)
        before = self._revision
        revision = original(
            self, expected_revision, create=create, replace=replace,
            precommit_guard=precommit_guard,
        )
        if revision != before:
            frames = [
                "%s:%s" % (Path(frame.filename).name, frame.name)
                for frame in traceback.extract_stack()[:-1]
                if "nodelang" in frame.filename
                and "universal_cell" not in frame.filename
            ][-3:]
            COMMITS.append({
                "phase": phase[0], "cells": len(create) + len(replace),
                "where": " < ".join(reversed(frames)),
            })
        return revision

    universal_cell.CellStore.commit = traced


def canvas_position(server):
    registry = server.universal_registry
    root = registry.visible_roots[0]
    position = registry.position_properties[root]
    return (
        root,
        position["position_x"].value_root,
        position["position_y"].value_root,
    )


def read_position(server, x_root, y_root):
    store = server.universal_store
    return [store.read(x_root).atom.decode(), store.read(y_root).atom.decode()]


def build_old():
    from nodelang.universal_application import move_universal_root
    STATE.mkdir(parents=True, exist_ok=True)
    server = open_server()
    try:
        # One ordinary user edit, recorded by the OLD release's change history.
        root, x_root, y_root = canvas_position(server)
        original = read_position(server, x_root, y_root)
        revision = move_universal_root(
            server.universal_store, server.universal_registry, root, 431.0, 287.0
        )
        edit = {
            "root": root, "x_root": x_root, "y_root": y_root,
            "original": original, "moved": read_position(server, x_root, y_root),
            "revision": revision,
        }
    finally:
        server.close()
    edit["cells"] = cells_at(edit["revision"])
    (STATE / "old-edit.json").write_text(json.dumps(edit), encoding="utf-8")
    # One ordinary restart of the old release, as an installed graph has.
    server = open_server()
    server.close()
    print(json.dumps({"built": counts(), "edit": edit}))


class FakeClock:
    """Wall time moves only when the court advances it."""

    def __init__(self):
        self.offset = 0.0
        self._real = time.time

    def __call__(self):
        return self._real() + self.offset


def b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def enroll_baboom(server, descriptor_path):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils
    from nodelang.application_machine_transport import (
        UniversalRuntimeClient, runtime_device_proof_payload,
    )
    from nodelang.cell_cloud_sessions import device_root_for_thumbprint
    from nodelang.cell_device_custody import register_device_custody
    from nodelang.cell_device_keys import DeviceProofKeyReference, PLATFORM_PROVIDER
    from nodelang.universal_application import (
        bind_universal_runtime_agent_body_device_custody,
    )
    from nodelang.universal_cell import Cell, NULL_CELL_ID

    key = ec.generate_private_key(ec.SECP256R1())
    numbers = key.public_key().public_numbers()
    public_jwk = {
        "crv": "P-256", "kty": "EC",
        "x": b64url(numbers.x.to_bytes(32, "big")),
        "y": b64url(numbers.y.to_bytes(32, "big")),
    }
    thumbprint = b64url(hashlib.sha256(json.dumps(
        public_jwk, sort_keys=True, separators=(",", ":")
    ).encode("ascii")).digest())
    reference = DeviceProofKeyReference(
        "court-runtime-device", PLATFORM_PROVIDER, "ES256", thumbprint,
        public_jwk, True,
    )
    with user_action("bind the BABOOM device"):
        store = server.universal_store
        store.commit(store.revision, create=(Cell(
            device_root_for_thumbprint(thumbprint), NULL_CELL_ID, NULL_CELL_ID,
            ("device-proof-key-thumbprint:" + thumbprint).encode("ascii"),
        ),))
        custody_root, _ = register_device_custody(
            store, server.universal_registry.device_custody_protocol, reference
        )
        bind_universal_runtime_agent_body_device_custody(
            store, server.universal_registry, runtime="baboom",
            custody_root=custody_root,
        )
    external = "founder-desktop-baboom"

    def credential(challenge):
        payload = runtime_device_proof_payload(
            runtime_id=challenge["runtime_id"], runtime=challenge["runtime"],
            external_session_id=external, challenge_id=challenge["challenge_id"],
            nonce=challenge["nonce"],
        )
        left, right = utils.decode_dss_signature(key.sign(
            hashlib.sha256(payload).digest(),
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        ))
        return {
            "challenge_id": challenge["challenge_id"],
            "custody_root": custody_root,
            "signature": b64url(left.to_bytes(32, "big") + right.to_bytes(32, "big")),
        }

    client = UniversalRuntimeClient(descriptor_path, pipe_keys())
    client.bind_agent_session(
        runtime="baboom", external_session_id=external,
        device_credential_provider=credential,
    )
    return client


def trusted_desktop_peer():
    """The launcher's own pipe peer, as the Desktop renewal presents it."""
    from nodelang import application_machine_transport as transport
    from nodelang import application_server as application
    peer = transport.MachinePipePeer(
        os.getpid(), 100.0, str(Path(sys.executable).resolve()),
        (sys.executable, str(SOURCE / "launch_archhub_test.py")), str(SOURCE),
    )
    transport._observe_machine_process = lambda pid: peer if pid == peer.pid else None
    application._verified_machine_pipe_peer = lambda request: peer


def desktop_renewal(server, sequence):
    """The launcher's renewal; the window then loads the one-use handoff."""
    from urllib.parse import parse_qs, urlsplit
    result = server._dispatch_verified_machine_route({
        "runtime_id": "zero-idle-court", "request_id": "renewal-%04d" % sequence,
        "method": "POST", "path": "/api/universal/browser-handoff",
        "body": {}, "session": {},
    })
    handoff = parse_qs(urlsplit(result["document_url"]).query)["bootstrap"][0]
    if not server._consume_browser_bootstrap(handoff):
        raise RuntimeError("browser handoff was not accepted")
    return result


def session_start_receipt(server, client, sequence):
    """The brain hook's session-start compliance receipt for this session."""
    registry = server.universal_registry
    fingerprint = server._machine_session_surface_values(
        server.universal_store.snapshot(), client.agent_session_root
    )["session fingerprint"]
    return client.request("POST", "/api/universal/deliberation", {
        "space": registry.brain_control_ledger_root,
        "category": registry.brain_control_category_roots["compliance-event"],
        "summary": "Runtime Agent Session wiring",
        "payload": {
            "operation": "brain.hook_session_start",
            "session_fingerprint": fingerprint,
            "entry_count": 0, "entries": [],
            "secret_ref_count": 0, "secret_ref_hashes": [],
            "cwd_sha256": hashlib.sha256(b"court-cwd").hexdigest(),
            "git_remote_sha256": hashlib.sha256(b"court-remote").hexdigest(),
        },
        "idempotency_key": "zero-idle-session-start-%04d" % sequence,
        "created_at": None,
    })


def browser_canvas(server):
    from email.message import Message
    from io import BytesIO
    from urllib.parse import urlsplit
    handler = object.__new__(server.httpd.RequestHandlerClass)
    handler.server = server.httpd
    handler.path, handler.command = "/api/universal/canvas", "GET"
    handler.request_version = "HTTP/1.1"
    handler.requestline = "GET /api/universal/canvas HTTP/1.1"
    handler.headers = Message()
    handler.headers["Host"] = urlsplit(server.public_url).netloc
    handler.headers["Cookie"] = "ArchHub-Session=" + server.browser_session_token
    handler.rfile, handler.wfile = BytesIO(), BytesIO()
    handler.do_GET()
    status = int(handler.wfile.getvalue().split(b" ", 2)[1])
    if status != 200:
        raise RuntimeError("browser canvas read returned %d" % status)


def idle(result_path):
    phase = ["open"]
    trace_commits(phase)
    clock = FakeClock()
    time.time = clock
    trusted_desktop_peer()
    descriptor = STATE / "runtime.json"
    result = {"source": str(SOURCE), "old": counts()}

    def running():
        server = open_server(
            enable_machine_transport=True,
            machine_descriptor_path=descriptor,
            machine_key_provider=pipe_keys(),
            machine_session_lifetime_seconds=86_400.0,
        )
        return server.start()

    server = running()
    try:
        result["opened"] = counts()
        # The founder was here once: BABOOM enrolled and reported, the brain
        # hook recorded its session start, and the window read its canvas.
        # Everything after the baseline is idle.
        phase[0] = "warm"
        baboom = enroll_baboom(server, descriptor)
        signal = hashlib.sha256(b"zero-idle-court").hexdigest()
        baboom.renew_runtime_presence()
        baboom.record_baboom_activity(app="Revit")
        baboom.record_baboom_steward_signal(
            fingerprint=signal, source="zero-idle court", summary="Nothing changed."
        )
        session_start_receipt(server, baboom, 0)
        desktop_renewal(server, 0)
        browser_canvas(server)
        baboom.request("GET", "/api/universal/work", {})
        result["baseline"] = counts()
        result["intervals"] = []
        for interval in range(1, INTERVALS + 1):
            phase[0] = "interval-%d" % interval
            clock.offset += INTERVAL_SECONDS
            baboom.renew_agent_session()
            baboom.renew_runtime_presence()
            baboom.record_baboom_activity(app="Revit")
            baboom.record_baboom_steward_signal(
                fingerprint=signal, source="zero-idle court",
                summary="Nothing changed.",
            )
            session_start_receipt(server, baboom, interval)
            desktop_renewal(server, interval)
            baboom.request("GET", "/api/universal/work", {})
            browser_canvas(server)
            result["intervals"].append(counts())
    finally:
        phase[0] = "close"
        server.close()
    result["closed"] = counts()
    for restart in (1, 2):
        phase[0] = "restart-%d" % restart
        clock.offset += INTERVAL_SECONDS
        server = running()
        server.close()
        result["restart_%d" % restart] = counts()
    result["commits"] = [item for item in COMMITS if item["phase"] != "open"]
    result["open_commits"] = [item for item in COMMITS if item["phase"] == "open"]
    Path(result_path).write_text(json.dumps(result, indent=1), encoding="utf-8")


def undo_old(result_path):
    from nodelang.universal_application import (
        move_universal_root, redo_universal_change, undo_universal_change,
    )
    edit = json.loads((STATE / "old-edit.json").read_text(encoding="utf-8"))
    result = {"old_edit": edit}
    server = open_server()
    try:
        store, registry = server.universal_store, server.universal_registry
        position = lambda: read_position(server, edit["x_root"], edit["y_root"])
        result["opened"] = position()
        with user_action("undo the old release's edit"):
            undo_universal_change(store, registry)
        result["after_old_undo"] = position()
        with user_action("redo the old release's edit"):
            redo_universal_change(store, registry)
        result["after_old_redo"] = position()
        with user_action("a new edit"):
            revision = move_universal_root(
                store, registry, edit["root"], 512.0, 128.0
            )
        result["new_edit"] = {"revision": revision, "position": position()}
        with user_action("undo the new edit"):
            undo_universal_change(store, registry)
        result["after_new_undo"] = position()
        with user_action("redo the new edit"):
            redo_universal_change(store, registry)
        result["after_new_redo"] = position()
    finally:
        server.close()
    result["new_edit"]["cells"] = cells_at(result["new_edit"]["revision"])
    Path(result_path).write_text(json.dumps(result, indent=1), encoding="utf-8")


if __name__ == "__main__":
    if MODE == "build-old":
        build_old()
    elif MODE == "idle":
        idle(sys.argv[4])
    elif MODE == "undo-old":
        undo_old(sys.argv[4])
    else:
        raise SystemExit("unknown phase " + MODE)