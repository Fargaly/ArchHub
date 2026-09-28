"""Load named top-level functions from launch_archhub_test.py into a sandbox.

The launcher is a script: importing it boots the application. Courts that
must exercise its real attach and cockpit functions compile only those
functions, from the launcher's own source, over the globals the court
supplies. Nothing else in the launcher runs.
"""
from __future__ import annotations

import ast
from pathlib import Path

LAUNCHER_PATH = Path(__file__).resolve().parents[1] / "launch_archhub_test.py"


def source() -> str:
    return LAUNCHER_PATH.read_text(encoding="utf-8")


def tree() -> ast.Module:
    return ast.parse(source(), filename=str(LAUNCHER_PATH))


def load(*names: str, **namespace) -> dict:
    """Compile the named launcher functions over ``namespace`` and return it."""
    module = tree()
    found = [node for node in module.body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    missing = set(names) - {node.name for node in found}
    assert not missing, "launcher functions missing: %s" % sorted(missing)
    code = compile(ast.Module(body=found, type_ignores=[]), str(LAUNCHER_PATH), "exec")
    exec(code, namespace)
    return namespace


def ancestors(target_test) -> list:
    """The chain of nodes enclosing the first node ``target_test`` accepts."""
    module = tree()

    def walk(node, chain):
        for child in ast.iter_child_nodes(node):
            if target_test(child):
                return chain + [node]
            got = walk(child, chain + [node])
            if got is not None:
                return got
        return None

    return walk(module, []) or []


class Stop:
    """A stop event that never sleeps: wait() returns at once."""

    def __init__(self):
        self.flag = False
        self.waits = []

    def wait(self, seconds=None):
        self.waits.append(seconds)
        return self.flag

    def is_set(self):
        return self.flag

    def set(self):
        self.flag = True


class Attachment:
    """The GUI-thread receiver: records the host it is handed."""

    def __init__(self):
        self.pending_host = None
        self.landed = []
        outer = self

        class _Signal:
            def emit(self, host):
                outer.landed.append(host)

        self.ready = _Signal()


class ScriptedHost:
    """A prepared BABOOM host whose connect() follows a script of outcomes."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.connects = 0
        self.stopped = False

    def connect(self):
        self.connects += 1
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, BaseException):
            raise outcome

    def stop(self, timeout_seconds=None):
        self.stopped = True


def run_attach(monkeypatch, outcomes):
    """Run the launcher's real _keep_attaching; return (prepared kwargs, attachment, hosts, stop)."""
    from nodelang import baboom_attach

    prepared, hosts = [], []

    def prepare(server, **kwargs):
        prepared.append(kwargs)
        host = ScriptedHost(outcomes)
        hosts.append(host)
        return host

    monkeypatch.setattr(baboom_attach, "prepare_baboom_host", prepare)
    attachment = Attachment()
    stop = Stop()
    namespace = load(
        "_keep_attaching",
        _baboom_startup_choice=lambda: "on", _baboom_stop=stop, _baboom_off_reason=None,
        server=object(), state_dir=Path("state"), descriptor_path=Path("descriptor"),
        machine_key_provider=object(), _baboom_attachment=attachment,
    )
    namespace["_keep_attaching"]()
    return prepared, attachment, hosts, stop