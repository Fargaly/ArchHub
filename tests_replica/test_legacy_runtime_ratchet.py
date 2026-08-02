"""Shrink-only court for the typed-node compatibility runtime.

The compatibility store still exists while its website and migration workflows
are consumed by the universal Cell graph.  New dependencies are forbidden and
each existing method-level dependency may only decrease.
"""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path


BASELINE = {
    ("owner.registry", "do_POST"): 2,
    ("owner.store", "do_GET"): 2,
    ("owner.store", "do_POST"): 5,
    ("self.registry", "__init__"): 1,
    ("self.registry", "_live_loop"): 2,
    ("self.registry", "execute_command"): 6,
    ("self.registry", "project_runtime_state"): 4,
    ("self.registry", "refresh_live_state"): 1,
    ("self.store", "__init__"): 1,
    ("self.store", "_history_entries"): 1,
    ("self.store", "_live_loop"): 7,
    ("self.store", "_redo_user_transaction"): 1,
    ("self.store", "_undo_user_transaction"): 1,
    ("self.store", "execute_command"): 72,
    ("self.store", "flush_snapshot"): 2,
    ("self.store", "project_runtime_state"): 6,
    ("self.store", "refresh_live_state"): 6,
}


def _dependencies() -> Counter[tuple[str, str]]:
    path = Path(__file__).resolve().parents[1] / "nodelang" / "application_server.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    result: Counter[tuple[str, str]] = Counter()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Attribute)
            and node.attr in {"store", "registry"}
            and isinstance(node.value, ast.Name)
            and node.value.id in {"self", "owner"}
        ):
            continue
        current = node
        function = "<module>"
        owner_class = None
        while current in parents:
            current = parents[current]
            if (
                function == "<module>"
                and isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef))
            ):
                function = current.name
            elif (
                isinstance(current, ast.ClassDef)
                and current.name == "ApplicationServer"
            ):
                owner_class = current.name
                break
        if owner_class != "ApplicationServer":
            continue
        result[("%s.%s" % (node.value.id, node.attr), function)] += 1
    return result


def test_legacy_runtime_dependencies_can_only_shrink():
    observed = _dependencies()

    assert set(observed) <= set(BASELINE)
    assert all(observed[key] <= maximum for key, maximum in BASELINE.items())
    assert sum(observed.values()) <= sum(BASELINE.values()) == 120


def test_normal_server_launch_does_not_construct_or_watch_legacy_runtime(
    monkeypatch,
):
    import nodelang.application_server as application_server

    def forbidden_legacy_module(*_args, **_kwargs):
        raise AssertionError("normal launch loaded the typed-node runtime")

    monkeypatch.setattr(
        application_server,
        "_legacy_application_module",
        forbidden_legacy_module,
    )
    server = application_server.ApplicationServer(live_watch=True).start()
    try:
        assert server.store is None
        assert server.registry is None
        assert server._live_thread is None
        assert server._snapshot_thread is None
        state = server.project_runtime_state(
            authentication_context=(
                server.universal_registry.authorization.session.context()
            )
        )
        assert state["legacy_parallel_runtime"] is False
        assert state["legacy_runtime_status"] == "not instantiated"
        assert "legacy" not in state
    finally:
        server.close()
