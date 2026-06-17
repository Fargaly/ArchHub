"""Server-side SANDBOXED re-execution — the verifier that re-runs a claimed
result OFF the claimant's process and ATTESTS to it.

────────────────────────────────────────────────────────────────────────────
WHY THIS EXISTS (ROMA slice 4 / BRV-05 / AgDR-0054 CRITICAL #3)
────────────────────────────────────────────────────────────────────────────
`court_harness.convene_court` is an *in-process* jury: it runs the artifact
probes (py_compile / pytest / file_exists) inside the SAME Python interpreter
that the contributor's loop is running in. That is the bus-factor-one /
self-attestation hole the method warns about:

  * A claimant controls its own interpreter. It can monkeypatch
    `subprocess.run`, replace `court_harness._BUILTIN_PROBES`, stub
    `py_compile_probe`, or hand `convene_court` a pre-cooked `extra_probes`
    that returns `passed=True` for an artifact that does not exist. The
    in-process verdict is only as trustworthy as the process that produced it.
  * There is no portable proof, AFTER the fact, that a "green" was produced by
    an independent, untampered verifier rather than forged by the claimant.

This module closes both holes with the two things the leaf names:

  1. A real OUT-OF-PROCESS verify path — the artifact gate is re-executed in a
     FRESH `sys.executable` subprocess (a clean interpreter the claimant has
     not imported into, monkeypatched, or otherwise tampered with). The probe
     code that runs is `court_harness`'s OWN deterministic probe, imported
     cleanly in the child. Re-execution off the claimant's box is what catches
     a *faked artifact* (the child looks at the real disk, not the claimant's
     stubbed functions).

  2. The ATTESTATION it returns — a typed `VerifyAttestation` carrying the
     verdict, the gate it checked, the verifier's identity/host/pid, the child
     subprocess pid + exit code (proof the work happened in a *different*
     process), a timestamp, and an HMAC-SHA256 SIGNATURE over the canonical
     payload using a SERVER-HELD key (an `op://` reference resolved at call
     time — NEVER an inlined secret). A claimant cannot forge the signature
     (it does not hold the key) and cannot reproduce a green it did not earn
     (the child re-checks reality). `verify_attestation` re-derives the HMAC
     and REJECTS a forged or tampered attestation — the mechanical form of
     "a contributor 'green' is re-checked server-side and a forged one
     rejected."

This is ADDITIVE and ONE-SYSTEM: it reuses `court_harness`'s probes + lenses
and `roma`'s tree ledger; it does not mint a parallel court. The in-process
`convene_court` stays as the fast local pre-check; `server_side_verify` is the
authoritative, off-the-claimant, signed re-check the server (the brain daemon,
or a CI runner) runs before a leaf is allowed to count.

SAFETY / HONESTY FLOOR (ANTI-LIE, MAKE-IT-REAL):
  * A gate that genuinely cannot be re-executed off-process (a `cdp` live-DOM
    gate needs the running app; a `manual` gate needs the founder) returns an
    HONEST typed result with `applied=False` and `reexecuted=False` — it is
    NOT silently greened and it does NOT raise NotImplementedError.
  * A subprocess that fails to spawn / times out / returns garbage REFUTES
    fail-closed (an unverifiable artifact is never green), with the child's
    stderr carried in the attestation for diagnosis.
  * No network in the default path. The signing key resolves through the same
    `secret_resolver` every other secret uses; with no key configured the
    attestation is still produced and still re-executed off-process, but marked
    `signed=False` so a caller can require a signature in trusted deployments.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .court_harness import (
    COURT_VERSION,
    LensVerdict,
    ProbeResult,
    lens_diligence,
    lens_independence,
)

VERIFY_VERSION = "roma-server-verify-v1"

# Default reference for the server's attestation-signing key. Resolved at
# call time via secret_resolver (op CLI → keyring → OP_* env). NEVER inline a
# key here — this is only the *reference*. In a trusted server deployment the
# founder sets this (or BRAIN_VERIFY_SIGNING_KEY) so attestations are signed.
DEFAULT_SIGNING_KEY_REF = "op://archhub/roma-verify/signing_key"

# Gate kinds that can be honestly re-executed in a clean subprocess: they are
# pure functions of (gate_spec, real disk). `cdp` (live app) and `manual`
# (founder) cannot — they get an honest applied=False, never a fake green.
_REEXECUTABLE_GATE_KINDS = ("py_compile", "file_exists", "pytest")

# Hard ceiling so a wedged child can never block the verifier forever.
_SUBPROCESS_TIMEOUT_S = 120.0


# ─────────────────────────── attestation type ──────────────────────────


@dataclass
class VerifyAttestation:
    """Signed record that a leaf's gate was re-executed OFF the claimant's box.

    The signature binds every field that matters (node, verdict, gate,
    evidence, verifier identity, child pid/exit, timestamp). A claimant that
    flips `green` True or swaps the `evidence_ref` invalidates the signature;
    `verify_attestation` catches it.
    """
    node_id: str
    verdict: str                        # "green" | "red" | "needs_root"
    green: bool
    gate_kind: str
    reexecuted: bool                    # was the artifact gate run off-process?
    executed_off_claimant: bool        # child pid differs from this process?
    claimed_by: Optional[str]
    judged_by: str
    verifier_host: str                  # hostname of the verifying server
    verifier_pid: int                   # the verifier (parent) process pid
    subprocess_pid: Optional[int]       # the child that ran the gate (proof)
    subprocess_returncode: Optional[int]
    evidence_ref: Optional[str]
    reason: str
    ts: float
    lenses: list[dict[str, Any]] = field(default_factory=list)
    verify_version: str = VERIFY_VERSION
    court_version: str = COURT_VERSION
    signed: bool = False
    signature: Optional[str] = None     # hex HMAC-SHA256 over the payload
    child_stderr: str = ""              # carried when the child failed

    # Fields NOT covered by the signature (they are derived/transport-only).
    _UNSIGNED_FIELDS = ("signature", "signed")

    def signing_payload(self) -> str:
        """Canonical, stable JSON of every signed field (sorted keys)."""
        d = {k: v for k, v in asdict(self).items()
             if k not in self._UNSIGNED_FIELDS and not k.startswith("_")}
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def to_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        return d


# ─────────────────────── out-of-process gate runner ────────────────────


# The child program. It imports court_harness FRESH (the claimant cannot have
# tampered with the child's import) and runs the SINGLE named probe against the
# real disk, emitting the ProbeResult as JSON on a sentinel-fenced line so the
# parent can parse it even if the probe prints to stdout. The child also prints
# its own os.getpid() so the parent can PROVE the work ran in a different
# process. `cwd` for pytest is taken from the gate/context like the in-process
# path. `repo_root` is injected on sys.path so `personal_brain` imports in any
# subprocess working dir.
_CHILD_SENTINEL = "__ROMA_VERIFY_RESULT__"

_CHILD_PROGRAM = r"""
import json, os, sys
_SENTINEL = "{sentinel}"
def _emit(obj):
    obj["child_pid"] = os.getpid()
    sys.stdout.write(_SENTINEL + json.dumps(obj) + _SENTINEL + "\n")
    sys.stdout.flush()
try:
    payload = json.loads(sys.stdin.read() or "{{}}")
    for p in payload.get("sys_path", []):
        if p and p not in sys.path:
            sys.path.insert(0, p)
    gate_kind = payload.get("gate_kind")
    gate_spec = payload.get("gate_spec") or {{}}
    context = payload.get("context") or {{}}
    from personal_brain.court_harness import _BUILTIN_PROBES
    runner = _BUILTIN_PROBES.get(gate_kind)
    if runner is None:
        _emit({{"ok": False, "error": "no builtin probe for gate_kind %r" % gate_kind}})
    else:
        res = runner(gate_spec, context)
        _emit({{"ok": True, "passed": bool(res.passed), "applied": bool(res.applied),
               "detail": res.detail, "evidence_ref": res.evidence_ref}})
except Exception as ex:  # the child fails closed; the parent refutes on it
    _emit({{"ok": False, "error": "%s: %s" % (type(ex).__name__, ex)}})
"""


@dataclass
class _SubprocessProbe:
    """Parsed outcome of the off-process gate run + the proof it was off-box."""
    result: ProbeResult
    child_pid: Optional[int]
    returncode: Optional[int]
    stderr: str
    spawned: bool                       # did a child process actually start?


def _repo_root_on_path() -> list[str]:
    """sys.path entries the child needs to import `personal_brain` regardless
    of its working directory. The package dir's parent (…/src) is the anchor."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # …/src
    paths = [here]
    # Carry the parent's sys.path too so editable installs / namespace pkgs
    # resolve identically in the child (no surprise import drift).
    for p in sys.path:
        if p and p not in paths:
            paths.append(p)
    return paths


def run_artifact_gate_subprocess(
    *,
    gate_kind: str,
    gate_spec: dict[str, Any],
    context: Optional[dict[str, Any]] = None,
    python_exe: Optional[str] = None,
    timeout: float = _SUBPROCESS_TIMEOUT_S,
) -> _SubprocessProbe:
    """Re-execute ONE artifact gate in a FRESH subprocess (off the claimant's
    interpreter) and return the result + proof of out-of-process execution.

    The child imports `court_harness` cleanly and runs the SAME deterministic
    probe the in-process court would — but in an interpreter the claimant did
    not touch, looking at the REAL disk. This is what makes a faked artifact
    impossible to pass: the claimant's monkeypatches do not exist in the child.

    Honest typed results (never raise, never fabricate):
      * gate_kind not re-executable off-process (cdp/manual/unknown) →
        ProbeResult(applied=False), spawned=False.
      * child fails to spawn / times out / emits no parseable result →
        ProbeResult(passed=False) (fail-closed), with stderr carried.
    """
    ctx = dict(context or {})
    if gate_kind not in _REEXECUTABLE_GATE_KINDS:
        return _SubprocessProbe(
            result=ProbeResult(
                passed=False, applied=False,
                detail=(f"gate_kind '{gate_kind}' is not re-executable "
                        "off-process (needs the live app or the founder)"),
            ),
            child_pid=None, returncode=None, stderr="", spawned=False,
        )

    exe = python_exe or sys.executable
    if not exe:
        return _SubprocessProbe(
            result=ProbeResult(passed=False, detail="no python interpreter to spawn"),
            child_pid=None, returncode=None, stderr="", spawned=False,
        )

    program = _CHILD_PROGRAM.format(sentinel=_CHILD_SENTINEL)
    stdin_payload = json.dumps({
        "gate_kind": gate_kind,
        "gate_spec": gate_spec,
        "context": {k: v for k, v in ctx.items() if k in ("repo_root", "cwd")},
        "sys_path": _repo_root_on_path(),
    })
    creationflags = (subprocess.CREATE_NO_WINDOW
                     if sys.platform == "win32" else 0)
    try:
        proc = subprocess.run(
            [exe, "-I", "-c", program],   # -I: isolated; ignore claimant env/site
            input=stdin_payload,
            capture_output=True, text=True, timeout=timeout,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as ex:
        return _SubprocessProbe(
            result=ProbeResult(passed=False,
                               detail=f"verify subprocess timed out after {timeout}s"),
            child_pid=None, returncode=None, stderr=str(ex)[:400], spawned=True,
        )
    except (OSError, ValueError) as ex:
        return _SubprocessProbe(
            result=ProbeResult(passed=False,
                               detail=f"verify subprocess failed to spawn: {ex}"),
            child_pid=None, returncode=None, stderr=str(ex)[:400], spawned=False,
        )

    parsed = _parse_child_output(proc.stdout)
    if parsed is None:
        tail = (proc.stderr or proc.stdout or "").strip()[-400:]
        return _SubprocessProbe(
            result=ProbeResult(
                passed=False,
                detail="verify subprocess produced no parseable result "
                       f"(rc={proc.returncode})"),
            child_pid=None, returncode=proc.returncode, stderr=tail, spawned=True,
        )
    if not parsed.get("ok"):
        return _SubprocessProbe(
            result=ProbeResult(passed=False,
                               detail=f"child error: {parsed.get('error', '?')}"),
            child_pid=parsed.get("child_pid"), returncode=proc.returncode,
            stderr=(proc.stderr or "").strip()[-400:], spawned=True,
        )
    res = ProbeResult(
        passed=bool(parsed.get("passed")),
        applied=bool(parsed.get("applied", True)),
        detail=str(parsed.get("detail", "")),
        evidence_ref=parsed.get("evidence_ref"),
    )
    return _SubprocessProbe(
        result=res, child_pid=parsed.get("child_pid"),
        returncode=proc.returncode, stderr=(proc.stderr or "").strip()[-400:],
        spawned=True,
    )


def _parse_child_output(stdout: str) -> Optional[dict[str, Any]]:
    """Extract the sentinel-fenced JSON the child emitted, tolerating any other
    stdout noise (a probe may print). Returns None when no fenced result."""
    if not stdout or _CHILD_SENTINEL not in stdout:
        return None
    try:
        # last fenced block wins (defensive against repeats)
        chunks = stdout.split(_CHILD_SENTINEL)
        # chunks: [pre, json, post, (json, post)...] — JSON blocks at odd idx
        for i in range(len(chunks) - 2, 0, -2):
            blob = chunks[i].strip()
            if blob:
                return json.loads(blob)
    except (ValueError, IndexError):
        return None
    return None


# ─────────────────────── signing / attestation ─────────────────────────


def _resolve_signing_key(signing_key_ref: Optional[str]) -> Optional[bytes]:
    """Resolve the attestation-signing key as bytes, or None when unconfigured.

    Order: explicit env BRAIN_VERIFY_SIGNING_KEY (raw key, dev/CI) →
    `secret_resolver.resolve_secret(ref)` (op CLI → keyring → OP_* env).
    NEVER returns an inlined constant; None means "no key, attestation is
    produced but unsigned."
    """
    raw = os.environ.get("BRAIN_VERIFY_SIGNING_KEY")
    if raw and raw.strip():
        return raw.strip().encode("utf-8")
    ref = signing_key_ref or DEFAULT_SIGNING_KEY_REF
    try:
        from .secret_resolver import resolve_secret
        val = resolve_secret(ref)
    except Exception:
        val = None
    if val and val.strip() and val.strip() != ref:
        return val.strip().encode("utf-8")
    return None


def _sign(att: VerifyAttestation, key: Optional[bytes]) -> None:
    """Stamp the attestation's HMAC-SHA256 signature in place (no-op w/o key)."""
    if not key:
        att.signed = False
        att.signature = None
        return
    mac = hmac.new(key, att.signing_payload().encode("utf-8"), hashlib.sha256)
    att.signature = mac.hexdigest()
    att.signed = True


def verify_attestation(
    att: VerifyAttestation,
    *,
    signing_key_ref: Optional[str] = None,
    require_signed: bool = True,
) -> tuple[bool, str]:
    """Re-check an attestation server-side: is it AUTHENTIC + UNTAMPERED?

    This is the gate that REJECTS a forged contributor green. It does NOT trust
    the attestation's own `green`/`verdict`; it recomputes the HMAC over the
    signed payload with the server key and compares (constant-time). A claimant
    that fabricated an attestation (no key) or flipped any signed field (verdict,
    evidence_ref, subprocess_pid, …) fails here.

    Returns (ok, reason). When `require_signed` is False, an unsigned
    attestation is accepted ONLY if the deployment has no key configured (dev) —
    if a key IS configured, an unsigned attestation is always rejected (a
    claimant cannot downgrade to unsigned to dodge the check).
    """
    key = _resolve_signing_key(signing_key_ref)
    if att.signature is None or not att.signed:
        if key is not None:
            return False, ("attestation is unsigned but a server signing key "
                           "is configured — refused (no unsigned downgrade)")
        if require_signed:
            return False, ("attestation is unsigned and require_signed=True "
                           "(configure BRAIN_VERIFY_SIGNING_KEY / op ref)")
        return True, "unsigned attestation accepted (no server key configured)"
    if key is None:
        return False, ("attestation carries a signature but the server has no "
                       "key to verify it — refused fail-closed")
    expected = hmac.new(
        key, att.signing_payload().encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, att.signature):
        return False, ("SIGNATURE MISMATCH — attestation was forged or tampered "
                       "(a signed field was altered after signing)")
    return True, "attestation signature valid (authentic + untampered)"


# ─────────────────────── the server-side verifier ──────────────────────


def server_side_verify(
    *,
    node_id: str,
    gate_kind: str,
    gate_spec: dict[str, Any],
    claimed_by: Optional[str],
    judged_by: str = "roma-server-verifier",
    context: Optional[dict[str, Any]] = None,
    require_diligence: bool = False,
    signing_key_ref: Optional[str] = None,
    python_exe: Optional[str] = None,
) -> VerifyAttestation:
    """Re-run + attest a leaf's gate OFF the claimant's process.

    The authoritative, server-side counterpart to `court_harness.convene_court`.
    Difference that matters for BRV-05: the ARTIFACT lens is re-executed in a
    FRESH subprocess (the claimant's interpreter tampering does not reach it),
    and the result is wrapped in a SIGNED `VerifyAttestation` that a forged
    green cannot reproduce.

    Aggregation policy mirrors `convene_court` exactly (so the server and the
    local pre-check agree on the rules — ONE-SYSTEM):
      * any applicable lens refuted → red,
      * no applicable artifact lens (manual / non-reexecutable) → needs_root,
      * require_diligence but no executor evidence → red,
      * else → green.

    The verdict is then SIGNED. Even a `needs_root`/`red` attestation is signed
    so a claimant cannot strip a red and claim there was no verdict.
    """
    ctx = dict(context or {})

    # 1) ARTIFACT lens — RE-EXECUTED OFF-PROCESS (the whole point).
    sub = run_artifact_gate_subprocess(
        gate_kind=gate_kind, gate_spec=gate_spec, context=ctx,
        python_exe=python_exe,
    )
    res = sub.result
    if not res.applied:
        art = LensVerdict(lens="artifact", refuted=False, applied=False,
                          detail=res.detail, evidence_ref=res.evidence_ref)
    else:
        art = LensVerdict(lens="artifact", refuted=not res.passed, applied=True,
                          detail=res.detail, evidence_ref=res.evidence_ref)

    # 2) DILIGENCE + 3) INDEPENDENCE — pure data checks (no artifact to tamper),
    #    reuse the court's own lenses verbatim (ONE-SYSTEM, no parallel logic).
    dil = lens_diligence(context=ctx)
    ind = lens_independence(claimed_by=claimed_by, judged_by=judged_by,
                            artifact_lens=art)
    lenses = [art, dil, ind]

    applied = [l for l in lenses if l.applied]
    refuters = [l for l in applied if l.refuted]

    # proof the artifact gate ran in a DIFFERENT process than this verifier.
    executed_off = bool(
        sub.spawned and sub.child_pid is not None
        and sub.child_pid != os.getpid()
    )

    if refuters:
        verdict = "red"
        green = False
        reason = "REFUTED (server re-exec): " + " || ".join(
            f"[{l.lens}] {l.detail}" for l in refuters)
    elif not art.applied:
        verdict = "needs_root"
        green = False
        reason = ("no off-process-checkable artifact gate on this leaf — the "
                  "server refuses to green an unverifiable leaf; it escalates "
                  "to the founder (root)")
    elif require_diligence and not dil.applied:
        verdict = "red"
        green = False
        reason = ("require_diligence=True but no executor evidence to judge — "
                  "show the work before a server green")
    else:
        verdict = "green"
        green = True
        reason = ("FAILED TO REFUTE on the real artifact, re-executed "
                  f"off-process (child pid {sub.child_pid}, rc "
                  f"{sub.returncode}): " + "; ".join(
                      f"[{l.lens}] {l.detail}" for l in applied))

    att = VerifyAttestation(
        node_id=node_id,
        verdict=verdict,
        green=green,
        gate_kind=gate_kind,
        reexecuted=bool(sub.spawned and res.applied),
        executed_off_claimant=executed_off,
        claimed_by=claimed_by,
        judged_by=judged_by,
        verifier_host=socket.gethostname(),
        verifier_pid=os.getpid(),
        subprocess_pid=sub.child_pid,
        subprocess_returncode=sub.returncode,
        evidence_ref=art.evidence_ref,
        reason=reason,
        ts=time.time(),
        lenses=[l.to_dict() for l in lenses],
        child_stderr=sub.stderr,
    )
    _sign(att, _resolve_signing_key(signing_key_ref))
    return att
