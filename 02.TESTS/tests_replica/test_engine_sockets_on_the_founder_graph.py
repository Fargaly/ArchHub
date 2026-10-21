"""An OLD graph opened by NEW code: its engine sockets accept a wire.

A fresh fixture built by the code under test cannot carry the read-only
sockets older builds placed, so this court opens a copy of a real graph
(ARCHHUB_OLD_GRAPH_COPY, taken with the sqlite backup API from a mode=ro
source, never the founder's own file) through the ApplicationServer boot
that runs the admitted migration. Its signing keys come from a copy too
(ARCHHUB_OLD_GRAPH_KEYS). Without both the court is skipped, and says so.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from nodelang import commit_intent
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider
from nodelang.universal_application import (
    connect_universal_roots,
    project_universal_canvas,
    set_universal_scope,
)

GRAPH = os.environ.get("ARCHHUB_OLD_GRAPH_COPY", "")
KEYS = os.environ.get("ARCHHUB_OLD_GRAPH_KEYS", "")

pytestmark = pytest.mark.skipif(
    not (GRAPH and KEYS and Path(GRAPH).is_file() and Path(KEYS).is_file()),
    reason="needs ARCHHUB_OLD_GRAPH_COPY and ARCHHUB_OLD_GRAPH_KEYS",
)


def counts():
    with sqlite3.connect("file:%s?mode=ro" % Path(GRAPH).as_posix(), uri=True) as db:
        return tuple(db.execute(query).fetchone()[0] for query in (
            "select max(revision) from revisions",
            "select count(*) from cell_versions",
            "select count(*) from current_cells",
        ))


def boot(tmp):
    return ApplicationServer(
        universal_state_path=Path(GRAPH),
        universal_key_provider=WindowsDpapiSigningKeyProvider(Path(KEYS)),
        universal_workspace_root=tmp,
    )


def sockets(node, side):
    return [port for port in node["ports"]
            if port["id"].startswith("app:pipeline-interface:") and port["side"] == side]


def test_an_old_graph_boots_once_into_connectable_sockets_and_wires_engine_out_to_engine_in(tmp_path):
    before = counts()
    boot(tmp_path).close()
    migrated = counts()
    server = boot(tmp_path)
    try:
        # The second boot finds nothing left to release and publishes nothing.
        assert counts() == migrated, "the second boot published a revision"
        store, registry = server.universal_store, server.universal_registry
        projection = project_universal_canvas(store, registry)
        engines = [node for node in projection["nodes"] if sockets(node, "source")]
        if len(engines) < 2:
            with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="open the top canvas"):
                set_universal_scope(store, registry, None)
            projection = project_universal_canvas(store, registry)
            engines = [node for node in projection["nodes"] if sockets(node, "source")]
        assert len(engines) >= 2, "the old graph holds no two visible engine cards"
        for node in engines:
            for port in sockets(node, "source") + sockets(node, "target"):
                assert port["read_only"] is False and port["connectable"] is True, port["id"]
        wired = {(wire["source"], wire["target"]) for wire in projection["wires"]}
        fed = {wire.get("target_interface") for wire in projection["wires"]}
        by_title = {node["label"]: node for node in engines}
        preferred = [(by_title.get("Sketch Lines"), by_title.get("Revit Walls"))]
        pairs = preferred + [(a, b) for a in engines for b in engines if a is not b]
        source, target = next(
            (a, b) for a, b in pairs
            if a and b and (a["id"], b["id"]) not in wired
            and sockets(b, "target")[0]["id"] not in fed
        )
        with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="draw one wire"):
            wire_root, _ = connect_universal_roots(
                store, registry, source["id"], target["id"],
                source_interface=sockets(source, "source")[0]["id"],
                target_interface=sockets(target, "target")[0]["id"],
            )
        assert any(wire["id"] == wire_root
                   for wire in project_universal_canvas(store, registry)["wires"])
        print("old graph %s -> migrated %s -> wired %s: %s -> %s" % (
            before, migrated, counts(), source["label"], target["label"]))
    finally:
        server.close()
