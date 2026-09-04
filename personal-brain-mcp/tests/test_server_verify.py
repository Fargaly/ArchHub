"""BRV-05 — server-side SANDBOXED re-execution + attestation.

The leaf: the ROMA court runs IN-PROCESS on the contributing machine — there is
no server-side re-exec and no attestation, so a contributor's "green" is only
as trustworthy as the (possibly tampered) process that produced it
(bus-factor-one). These tests prove the fix:

  * `pytest -k server_side_verify` — a contributor "green" is RE-CHECKED
    server-side (in a fresh subprocess, off the claimant's interpreter) and a
    FORGED one is rejected.

RED on origin/main: `personal_brain.server_verify` does not exist (ImportError)
and `roma.server_verify_leaf` / the `brain.roma_server_verify` tool are absent.
GREEN on the branch: the off-process verifier re-executes the real gate, signs
the attestation, rejects forgeries, and resists in-process monkeypatch tamper.

Pure + deterministic + hermetic: the in-memory store only (live brain.db never
touched), no network. The artifact gate is re-executed in a real subprocess via
`sys.executable` — that IS the point (off the claimant's box), and it stays
hermetic because the gate target is this package's own __init__.py.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from personal_brain import court_harness as ch
from personal_brain import requirement_tree as rt
from personal_brain import roma
from personal_brain import secret_resolver as sr
from personal_brain import server as brain_server
from personal_brain import server_verify as sv
from personal_brain.storage import BrainStore


# A file that definitely exists + compiles — the real artifact for the gate.
_PKG_INIT = os.path.join(os.path.dirname(rt.__file__), "__init__.py")


@pytest.fixture()
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


@pytest.fixture()
def signing_key(monkeypatch):
    """A deterministic dev signing key via the SAME env path production uses
    (BRAIN_VERIFY_SIGNING_KEY → never an inlined constant)."""
    monkeypatch.setenv("BRAIN_VERIFY_SIGNING_KEY", "test-verify-key-DO-NOT-SHIP")
    return "test-verify-key-DO-NOT-SHIP"


# ───────────────── out-of-process re-execution (the core) ─────────────────


def test_verifier_uses_console_sibling_when_brain_runs_windowless(tmp_path):
    pythonw = tmp_path / "pythonw.exe"
    python = tmp_path / "python.exe"
    pythonw.write_bytes(b"")
    python.write_bytes(b"")

    assert sv._verifier_python_executable(str(pythonw)) == str(python)
    assert sv._verifier_python_executable(str(python)) == str(python)

    python.unlink()
    assert sv._verifier_python_executable(str(pythonw)) == str(pythonw)


def test_server_side_verify_reexecutes_real_gate_off_process(signing_key):
    """A green is produced ONLY after the gate is re-run in a DIFFERENT process
    (proof: child pid != this pid) and the attestation is signed + authentic."""
    att = sv.server_side_verify(
        node_id="n1", gate_kind="py_compile", gate_spec={"path": _PKG_INIT},
        claimed_by="exec-A", judged_by="server-X",
        context={"evidence": {"last_message": "done; wrote files",
                              "session_signals": {"wrote_files": True}}},
    )
    assert att.green is True and att.verdict == "green"
    assert att.reexecuted is True
    # the whole point of BRV-05: it ran OFF the claimant's process.
    assert att.executed_off_claimant is True
    assert att.subprocess_pid is not None and att.subprocess_pid != os.getpid()
    assert att.evidence_ref  # a named artifact backs the green
    assert att.signed is True and att.signature
    ok, reason = sv.verify_attestation(att)
    assert ok is True, reason


def test_server_side_verify_normalizes_grand_map_pytest_gate_without_shelling(
        signing_key, tmp_path):
    runtime = tmp_path / "runtime"
    tests = runtime / "tests"
    tests.mkdir(parents=True)
    target = tests / "test_generated_gate.py"
    target.write_text("def test_real_artifact():\n    assert 6 * 7 == 42\n", encoding="utf-8")
    shell_marker = tmp_path / "command-was-executed"

    att = sv.server_side_verify(
        node_id="grand-map-pytest",
        gate_kind="pytest",
        gate_spec={
            "path": "runtime/tests/test_generated_gate.py",
            "command": (
                "python -m pytest tests/test_generated_gate.py -q && "
                "python -c \"open(r'%s','w').write('unsafe')\"" % shell_marker
            ),
        },
        claimed_by="exec-A",
        judged_by="server-X",
        context={
            "repo_root": str(tmp_path),
            "evidence": {
                "last_message": "implemented the gate normalization and ran tests",
                "session_signals": {"ran_tests": True, "wrote_files": True},
            },
        },
    )

    assert att.green is True and att.reexecuted is True
    assert att.evidence_ref == "tests/test_generated_gate.py"
    assert Path(att.evidence_ref).as_posix() == "tests/test_generated_gate.py"
    assert shell_marker.exists() is False


def test_server_side_verify_executes_every_declared_pytest_selector_without_shelling(
        signing_key, tmp_path):
    runtime = tmp_path / "runtime"
    tests = runtime / "tests"
    tests.mkdir(parents=True)
    first = tests / "test_first.py"
    second = tests / "test_second.py"
    first.write_text("def test_first():\n    assert True\n", encoding="utf-8")
    second.write_text("def test_second():\n    assert False\n", encoding="utf-8")
    shell_marker = tmp_path / "selector-command-was-executed"
    gate = {
        "path": "runtime/tests/test_first.py",
        "selectors": ["tests/test_first.py", "tests/test_second.py"],
        "command": (
            "python -m pytest tests/test_first.py tests/test_second.py -q && "
            "python -c \"open(r'%s','w').write('unsafe')\"" % shell_marker
        ),
    }
    context = {
        "repo_root": str(tmp_path),
        "evidence": {
            "last_message": "ran the complete declared pytest selector list",
            "session_signals": {"ran_tests": True, "wrote_files": True},
        },
    }

    red = sv.server_side_verify(
        node_id="multi-selector-red", gate_kind="pytest", gate_spec=gate,
        claimed_by="exec-A", judged_by="server-X", context=context)
    assert red.green is False and red.verdict == "red"
    assert red.evidence_ref == "tests/test_first.py | tests/test_second.py"

    second.write_text("def test_second():\n    assert True\n", encoding="utf-8")
    green = sv.server_side_verify(
        node_id="multi-selector-green", gate_kind="pytest", gate_spec=gate,
        claimed_by="exec-A", judged_by="server-X", context=context)
    assert green.green is True and green.verdict == "green"
    assert green.evidence_ref == "tests/test_first.py | tests/test_second.py"
    assert shell_marker.exists() is False


def test_server_side_verify_refutes_missing_artifact(signing_key):
    """A claimed leaf whose artifact does not exist is refuted by the
    off-process re-exec (fail-closed), and the red is still attested."""
    att = sv.server_side_verify(
        node_id="n2", gate_kind="file_exists", gate_spec={"path": "/no/such/file.zzz"},
        claimed_by="exec-A", judged_by="server-X",
    )
    assert att.green is False and att.verdict == "red"
    assert att.reexecuted is True            # it DID re-execute (and saw reality)
    assert "missing" in att.reason or "REFUTED" in att.reason
    # even a red is signed, so a claimant can't strip the verdict undetectably.
    assert att.signed is True
    ok, _ = sv.verify_attestation(att)
    assert ok is True


def test_server_side_verify_rejects_forged_green(signing_key):
    """THE forged-green rejection: a claimant flips a refuted attestation to
    'green' after signing. verify_attestation catches the tamper."""
    forged = sv.server_side_verify(
        node_id="n3", gate_kind="file_exists", gate_spec={"path": "/nope.nope"},
        claimed_by="exec-A", judged_by="server-X",
    )
    assert forged.verdict == "red"           # honest verdict before tamper
    # tamper: forge a green by flipping the signed fields, keeping the old sig.
    forged.green = True
    forged.verdict = "green"
    ok, reason = sv.verify_attestation(forged)
    assert ok is False
    assert "MISMATCH" in reason or "forged" in reason.lower()


def test_server_side_verify_rejects_unsigned_fabrication(signing_key):
    """A claimant fabricates an attestation WITHOUT the server key (signed=False,
    signature=None) and claims green. With a key configured, an unsigned
    attestation is refused — no unsigned downgrade past the gate."""
    fabricated = sv.VerifyAttestation(
        node_id="n4", verdict="green", green=True, gate_kind="py_compile",
        reexecuted=True, executed_off_claimant=True, claimed_by="exec-A",
        judged_by="exec-A",  # also self-cert, but unsigned alone must fail
        verifier_host="attacker", verifier_pid=1, subprocess_pid=2,
        subprocess_returncode=0, evidence_ref="/whatever", reason="trust me",
        ts=0.0,
    )
    assert fabricated.signed is False and fabricated.signature is None
    ok, reason = sv.verify_attestation(fabricated)
    assert ok is False
    assert "unsigned" in reason.lower()


def test_server_verify_resists_in_process_monkeypatch_tamper(signing_key, monkeypatch):
    """ROOT-CAUSE proof: a claimant that monkeypatches the IN-PROCESS probe to
    fake a pass for a nonexistent file fools `convene_court` (same interpreter)
    but NOT the server verifier (re-executes in a clean child where the
    monkeypatch does not exist)."""
    def _fake_pass(gate_spec, context):
        return ch.ProbeResult(passed=True, detail="FAKED", evidence_ref=gate_spec.get("path"))

    # tamper ONLY this process's probe registry.
    monkeypatch.setitem(ch._BUILTIN_PROBES, "file_exists", _fake_pass)
    gate = dict(gate_kind="file_exists", gate_spec={"path": "/ghost/not/real.zzz"},
                claimed_by="exec-A", judged_by="court-X")
    ev = {"evidence": {"last_message": "done; wrote files",
                       "session_signals": {"wrote_files": True}}}

    # in-process court is FOOLED by the tamper:
    ip = ch.convene_court(node_id="n5", context=ev, **gate)
    assert ip.green is True  # demonstrates the bus-factor-one hole

    # server-side verifier CATCHES it (clean child, real disk):
    att = sv.server_side_verify(node_id="n5", context=ev, **gate)
    assert att.green is False and att.verdict == "red"


def test_server_side_verify_self_cert_refused_off_process(signing_key):
    """The independence lens still applies off-process: judge == claimant is
    refused even when the artifact re-executes clean."""
    att = sv.server_side_verify(
        node_id="n6", gate_kind="py_compile", gate_spec={"path": _PKG_INIT},
        claimed_by="exec-A", judged_by="exec-A",  # self-certification
    )
    assert att.green is False and att.verdict == "red"
    assert "self-cert" in att.reason.lower() or "independent" in att.reason.lower()


def test_non_reexecutable_gate_is_honest_not_faked(signing_key):
    """A cdp/manual gate cannot be re-executed off-process. It returns an HONEST
    needs_root (escalate to founder), never a fabricated green and never
    NotImplementedError."""
    att = sv.server_side_verify(
        node_id="n7", gate_kind="cdp", gate_spec={"expression": "true"},
        claimed_by="exec-A", judged_by="server-X",
    )
    assert att.green is False and att.verdict == "needs_root"
    assert att.reexecuted is False           # honestly did not re-execute


def test_unsigned_dev_brain_still_attests(monkeypatch):
    """With NO server key configured (dev), the attestation is still produced
    and STILL re-executed off-process — just marked signed=False so a trusted
    deployment can require signatures. No key is ever inlined."""
    monkeypatch.delenv("BRAIN_VERIFY_SIGNING_KEY", raising=False)
    # Point the op ref at something unresolvable so resolve_secret returns None.
    att = sv.server_side_verify(
        node_id="n8", gate_kind="py_compile", gate_spec={"path": _PKG_INIT},
        claimed_by="exec-A", judged_by="server-X",
        context={"evidence": {"last_message": "done; ran pytest",
                              "session_signals": {"ran_tests": True}}},
        signing_key_ref="op://nonexistent/nonexistent/nonexistent",
    )
    assert att.green is True                  # the artifact still re-checked real
    assert att.executed_off_claimant is True
    assert att.signed is False                # honest: unsigned in keyless dev
    ok, reason = sv.verify_attestation(
        att, signing_key_ref="op://nonexistent/nonexistent/nonexistent",
        require_signed=False,
    )
    assert ok is True and "no server key" in reason


# ───────────────── wired into the ROMA tree ledger ─────────────────


def test_server_verify_leaf_records_attested_verdict(store, signing_key):
    """server_verify_leaf re-checks a claimed leaf OFF-process and writes the
    attested verdict into the requirement tree (green on a real artifact)."""
    tree = roma.atomize(
        store, vision="v", owner_user="founder",
        decomposition=[{"title": "compiles", "gate_kind": "py_compile",
                        "gate_spec": {"path": _PKG_INIT}}])
    leaf = tree.leaves()[0]
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id, agent_id="exec-A")
    out = roma.server_verify_leaf(
        store, tree_id=tree.tree_id, node_id=leaf.node_id, judged_by="server-Z",
        context={"evidence": {"last_message": "done; wrote files",
                              "session_signals": {"wrote_files": True}}},
    )
    assert out["attestation"]["verdict"] == "green"
    assert out["attestation"]["executed_off_claimant"] is True
    assert out["authentic"] is True
    assert out["node"]["state"] == "green"


def test_server_verify_leaf_downgrades_unauthentic_green(store, signing_key, monkeypatch):
    """If the attestation a leaf produced cannot be authenticated, the recorded
    verdict is downgraded to red — the server never writes a green it can't
    itself authenticate (forgery-at-rest defense)."""
    tree = roma.atomize(
        store, vision="v", owner_user="founder",
        decomposition=[{"title": "compiles", "gate_kind": "py_compile",
                        "gate_spec": {"path": _PKG_INIT}}])
    leaf = tree.leaves()[0]
    rt.claim_leaf(store, tree_id=tree.tree_id, node_id=leaf.node_id, agent_id="exec-A")

    # Make verify_attestation return unauthentic for a green, simulating a
    # forged/tampered attestation reaching the recorder.
    real_verify = sv.verify_attestation
    monkeypatch.setattr(
        roma, "verify_attestation",
        lambda att, **kw: (False, "simulated forgery") if att.green else real_verify(att, **kw),
    )
    out = roma.server_verify_leaf(
        store, tree_id=tree.tree_id, node_id=leaf.node_id, judged_by="server-Z",
        context={"evidence": {"last_message": "done; wrote files",
                              "session_signals": {"wrote_files": True}}},
    )
    assert out["authentic"] is False
    assert out["node"]["state"] == "red"      # green downgraded — not recorded


def test_brain_roma_server_verify_tool_registered(store):
    """The off-process verifier is reachable as an additive MCP tool, and no
    existing handler is disturbed."""
    from personal_brain.server import build_server

    mcp = build_server(store=store, default_owner_user="founder")
    names = {t["name"] for t in mcp.list_tools()}
    assert "brain.roma_server_verify" in names
    # existing roma + core tools untouched
    assert {"brain.roma_judge", "brain.roma_sweep", "brain.health"} <= names


def test_court_signing_key_provisioning_uses_the_authoritative_ref(monkeypatch):
    observed = {}

    def fake_ensure(ref):
        observed["ref"] = ref
        return {
            "ok": True,
            "created": True,
            "ref": ref,
            "backend": "os_keyring",
        }

    monkeypatch.setattr(sr, "ensure_secret", fake_ensure)

    result = sv.ensure_court_signing_key()

    assert observed["ref"] == sv.DEFAULT_SIGNING_KEY_REF
    assert result == {
        "ok": True,
        "created": True,
        "ref": sv.DEFAULT_SIGNING_KEY_REF,
        "backend": "os_keyring",
    }
    assert "value" not in result
    assert "secret" not in result


def test_daemon_startup_ensures_court_key_without_logging_it(monkeypatch, capsys):
    calls = []

    class FakeServer:
        def run(self, **kwargs):
            calls.append(("run", kwargs))

    monkeypatch.setattr(
        sv,
        "ensure_court_signing_key",
        lambda: {
            "ok": True,
            "created": False,
            "ref": sv.DEFAULT_SIGNING_KEY_REF,
            "backend": "existing",
        },
    )
    monkeypatch.setattr(
        brain_server,
        "build_server",
        lambda **_kwargs: FakeServer(),
    )

    brain_server.main(["--http", "9843"])

    captured = capsys.readouterr()
    assert calls == [("run", {
        "transport": "http",
        "host": "127.0.0.1",
        "port": 9843,
        "stateless_http": True,
    })]
    assert "court signing capability READY" in captured.err
    assert sv.DEFAULT_SIGNING_KEY_REF in captured.err
    assert "BRAIN_VERIFY_SIGNING_KEY" not in captured.err


def test_server_verify_uses_bounded_declared_gate_timeout(
        signing_key, monkeypatch):
    observed = []

    def fake_subprocess(**kwargs):
        observed.append(kwargs["timeout"])
        return sv._SubprocessProbe(
            result=sv.ProbeResult(
                passed=True, applied=True, detail="verified",
                evidence_ref="pytest:verified"),
            child_pid=os.getpid() + 1,
            returncode=0,
            stderr="",
            spawned=True,
        )

    monkeypatch.setattr(sv, "run_artifact_gate_subprocess", fake_subprocess)

    cases = [
        ({"selector": "tests/test_x.py", "timeout_s": 600}, 600.0),
        ({"selector": "tests/test_x.py", "timeout_s": 99999}, 900.0),
        ({"selector": "tests/test_x.py", "timeout_s": 0}, 120.0),
        ({"selector": "tests/test_x.py", "timeout_s": "invalid"}, 120.0),
    ]
    for index, (gate_spec, expected) in enumerate(cases):
        att = sv.server_side_verify(
            node_id=f"timeout-{index}",
            gate_kind="pytest",
            gate_spec=gate_spec,
            claimed_by="agent-A",
            judged_by="court-B",
        )
        assert att.green is True
        assert observed[-1] == expected
