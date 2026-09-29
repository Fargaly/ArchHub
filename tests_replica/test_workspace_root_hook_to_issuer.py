"""End to end: the governance hooks' broker plans a root-bound write and the
application issues the permit through the real machine transport.

Isolated by injection, independently of the code under test: the broker gets an
in-process transport and a temporary pending folder; the registry files are court
files; the graph-current check is a court stand-in (tests_replica/conftest.py also
pins the live context to a refusal). Nothing reaches :8474 or a live key store.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import sys
from pathlib import Path

import pytest

from tests_replica.test_workspace_root_machine_permit import ROOT_GRANT, runtime  # noqa: F401
from tests_replica.test_workspace_root_write_admission import _entry, _registry


def _hooks_dir():
    configured = os.environ.get("ARCHHUB_GOVERNANCE_HOOKS", "").strip()
    if configured:
        return Path(configured)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "00.GOVERNANCE" / "hooks"
        if (candidate / "governed_write_broker.py").is_file():
            return candidate
    return None


@pytest.fixture()
def broker(monkeypatch):
    hooks = _hooks_dir()
    if hooks is None:
        pytest.skip("the governance hooks are not beside this tree")
    monkeypatch.syspath_prepend(str(hooks))
    for name in ("governed_write_broker", "cde_gate", "path_identity"):
        sys.modules.pop(name, None)
    return importlib.import_module("governed_write_broker")


PERMIT = "brain.universal_cde_write_permit"
RECEIPT = "brain.universal_cde_write_receipt"
CONTENT = "synthetic drawing, not client data"


def _transport(agent):
    def call(name, arguments, *, timeout=25.0):
        body = {key: value for key, value in arguments.items() if key not in {"vendor", "session_id"}}
        if name == PERMIT:
            return agent.issue_cde_write_permit(**body)
        if name == RECEIPT:
            return agent.consume_cde_write_permit(**body)
        raise AssertionError("unexpected authority call %s" % name)
    return call


def _event(folder, phase, tool_use="court-tool-use"):
    return {"hook_event_name": phase, "tool_name": "Write", "vendor": "codex",
            "session_id": "court-workspace-root", "tool_use_id": tool_use, "cwd": str(folder),
            "tool_input": {"file_path": str(folder / "drawings" / "synthetic.dwg"), "content": CONTENT}}


def _binding(broker, folder):
    import path_identity
    return {"id": "client-a", "path": str(folder), "identity": list(path_identity.identity(folder))}


def _prepare(broker, runtime, folder, binding):
    return broker.prepare_signed_write_event(
        _event(folder, "PreToolUse"), vendor="codex", workspace_root=folder,
        path_prefix="workspace-roots/client-a/", root_binding=binding,
        pending_root=runtime["tmp"] / "pending", transport=_transport(runtime["agent"]))


@pytest.mark.parametrize("runtime", [(ROOT_GRANT, ("codex",), True)], indirect=True)
def test_an_unchanged_registration_prepares_writes_and_settles_once(broker, runtime):
    folder = runtime["folder"]
    (folder / "drawings").mkdir()
    prepared = _prepare(broker, runtime, folder, _binding(broker, folder))
    assert prepared["allow"] is True, prepared
    target = folder / "drawings" / "synthetic.dwg"
    target.write_text(CONTENT, encoding="utf-8")  # the tool's write
    settled = broker.settle_signed_write_event(
        _event(folder, "PostToolUse"), vendor="codex", pending_root=runtime["tmp"] / "pending",
        transport=_transport(runtime["agent"]))
    assert settled["allow"] is True and settled["code"] == "signed_write_receipted", settled
    again = broker.settle_signed_write_event(
        _event(folder, "PostToolUse"), vendor="codex", pending_root=runtime["tmp"] / "pending",
        transport=_transport(runtime["agent"]))
    assert again["allow"] is False and again["code"] == "signed_write_pending_missing"
    assert hashlib.sha256(target.read_bytes()).hexdigest() == hashlib.sha256(CONTENT.encode()).hexdigest()


@pytest.mark.parametrize("runtime", [(ROOT_GRANT, ("codex",), True)], indirect=True)
def test_a_same_id_re_registration_before_issue_is_refused_before_any_write(broker, runtime):
    folder_a = runtime["folder"]
    (folder_a / "drawings").mkdir()
    planned = _binding(broker, folder_a)  # the hook loaded its registry: client-a -> A
    folder_b = runtime["tmp"] / "client-b-folder"
    folder_b.mkdir()
    # The owner re-registers client-a to B before the permit is issued.
    _registry(runtime["tmp"], runtime["key"], [_entry(folder_b, writers=("codex",))], revision=4)
    prepared = _prepare(broker, runtime, folder_a, planned)
    assert prepared["allow"] is False, prepared
    assert "different registration" in prepared["message"]
    assert not (folder_a / "drawings" / "synthetic.dwg").exists()
    assert not (folder_b / "drawings").exists()


@pytest.mark.parametrize("runtime", [(ROOT_GRANT, ("codex",), True)], indirect=True)
def test_an_unchanged_retry_reuses_its_permit_and_settles_once(broker, runtime):
    folder = runtime["folder"]
    (folder / "drawings").mkdir()
    binding = _binding(broker, folder)
    first = _prepare(broker, runtime, folder, binding)
    retry = _prepare(broker, runtime, folder, binding)  # the same invocation, retried
    assert first["allow"] is True and retry["allow"] is True, (first, retry)
    (folder / "drawings" / "synthetic.dwg").write_text(CONTENT, encoding="utf-8")
    settled = broker.settle_signed_write_event(
        _event(folder, "PostToolUse"), vendor="codex", pending_root=runtime["tmp"] / "pending",
        transport=_transport(runtime["agent"]))
    assert settled["code"] == "signed_write_receipted", settled


@pytest.mark.parametrize("runtime", [(ROOT_GRANT, ("codex",), True)], indirect=True)
def test_a_folder_replaced_at_the_same_spelling_refuses_the_cached_permit(broker, runtime):
    import shutil

    folder = runtime["folder"]
    (folder / "drawings").mkdir()
    assert _prepare(broker, runtime, folder, _binding(broker, folder))["allow"] is True
    shutil.rmtree(folder)  # replaced before the tool ran: same path, a new folder identity
    folder.mkdir()
    (folder / "drawings").mkdir()
    retry = _prepare(broker, runtime, folder, _binding(broker, folder))
    assert retry["allow"] is False and "different registration" in retry["message"], retry
    assert not (folder / "drawings" / "synthetic.dwg").exists()
