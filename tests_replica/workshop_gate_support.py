"""Court support: satisfy the Workshop execution gate the way the founder does.

Any Work an Agent Session claims takes an effect only after its coordinate
phase holds (universal_application._require_workshop_execution_gate): a plan
and research with captured source evidence, referencing that exact Work. The
founder records both in the Workshop, in process; the source is content
captured in the graph as a registered value graph.
"""
from nodelang import commit_intent
from nodelang.cell_value_graph import build_value_graph


def open_execution_gate_in_graph(store, registry, work_root, key, context):
    """The same founder plan and research on a bare graph-held application."""
    from nodelang.universal_application import append_universal_workshop_entry
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="plan the Work"):
        source, _revision = build_value_graph(
            store, registry.value_graph_protocol,
            {"source": "court", "key": key, "text": "Source the court's plan cites."},
            root_id="court:gate-source:" + key)
        for category, evidence in (("plan", ()), ("research", (source,))):
            append_universal_workshop_entry(
                store, registry, actor_root=registry.authorization.subject_root,
                category_root=registry.workshop_category_roots[category],
                content="%s for %s" % (category, key),
                idempotency_key="court:gate:%s:%s" % (key, category),
                created_at="2026-09-25T10:00:00+00:00",
                reference_roots=(work_root,), evidence_roots=evidence,
                authentication_context=context)
    return source


def open_execution_gate(server, work_root, key):
    """Record the founder's plan and source-backed research for one Work."""
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="capture a source"):
        source, _revision = build_value_graph(
            server.universal_store, server.universal_registry.value_graph_protocol,
            {"source": "court", "key": key, "text": "Source the court's plan cites."},
            root_id="court:gate-source:" + key)
    for category, evidence in (("plan", []), ("research", [source])):
        server.dispatch_universal_machine_route({
            "method": "POST", "path": "/api/universal/workshop", "body": {
                "category": category, "text": "%s for %s" % (category, key),
                "refs": [work_root], "evidence": evidence, "recipients": [],
                "reply_to": None, "idempotency_key": "court:gate:%s:%s" % (key, category),
                "created_at": "2026-09-25T10:00:00+00:00"}})
    return source
