"""Court support: satisfy the Workshop execution gate the way the founder does.

Any Work an Agent Session claims takes an effect only after its coordinate
phase holds (universal_application._require_workshop_execution_gate): a plan
and research citing an actual capture, referencing that exact Work. The
founder records both in the Workshop, in process; the research carries one
file capture (capture_universal_workshop_file_source), so the server reads
the bytes and mints the source record itself.
"""
from pathlib import Path

from nodelang import commit_intent
import nodelang.universal_application as app


def _court_source(workspace_root, key):
    """A real file under the workspace root: this module's own source when it
    lies inside, else a small file the court writes into its temp workspace."""
    root = Path(workspace_root).resolve()
    here = Path(app.__file__).resolve()
    try:
        return here.relative_to(root).as_posix()
    except ValueError:
        written = root / ("court-gate-source-%s.txt" % key)
        written.write_text("Source the court's plan cites (%s).\n" % key, encoding="utf-8")
        return written.name


def open_execution_gate_in_graph(store, registry, work_root, key, context):
    """The same founder plan and captured research on a bare graph-held application."""
    workspace_root = Path(app.__file__).resolve().parents[1]
    founder = registry.authorization.subject_root
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="plan the Work"):
        source = app.capture_universal_workshop_file_source(
            store, registry, actor_root=founder, work_root=work_root,
            path=_court_source(workspace_root, key), workspace_root=workspace_root)
        for category, evidence in (("plan", ()), ("research", (source,))):
            app.append_universal_workshop_entry(
                store, registry, actor_root=founder,
                category_root=registry.workshop_category_roots[category],
                content="%s for %s" % (category, key),
                idempotency_key="court:gate:%s:%s" % (key, category),
                created_at="2026-09-25T10:00:00+00:00",
                reference_roots=(work_root,), evidence_roots=evidence,
                authentication_context=context)
    return source


def open_execution_gate(server, work_root, key):
    """Record the founder's plan and captured research for one Work."""
    path = _court_source(server.universal_workspace_root, key)
    for category, extra in (("plan", {}), ("research", {"capture": {"path": path}})):
        server.dispatch_universal_machine_route({
            "method": "POST", "path": "/api/universal/workshop", "body": {
                "category": category, "text": "%s for %s" % (category, key),
                "refs": [work_root], "evidence": [], "recipients": [],
                "reply_to": None, "idempotency_key": "court:gate:%s:%s" % (key, category),
                "created_at": "2026-09-25T10:00:00+00:00", **extra}})
