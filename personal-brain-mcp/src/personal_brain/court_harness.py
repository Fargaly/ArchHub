"""ROMA external COURT — the jury that must FAIL-TO-REFUTE a leaf on the REAL
artifact before it goes GREEN.

The method (`01.ECHO/METHOD_finish_everything.html`): a leaf does NOT turn
green because its executor says so. An EXTERNAL, anti-tamper court attempts to
REFUTE the leaf against the real artifact; only when it fails to refute does the
leaf go green. This is the mechanical form of the ANTI-LIE mandate
("code compiles + tests pass ≠ done") and the NEVER-REWARD-SHORT rule
(Dr. MAMR): the bar is *verified-complete*, never *short*.

Design mirrors `reflexion.validate_skill_against_trace` — a REAL deterministic
check (a pure function of (claim, artifact)), NOT a seed coin-flip — and the
CDP live-DOM harness shape from `tools/_verify_live_now.py` /
`tools/_verify_google_cta.py`. The "never reward short" pre-green gate is the
brain's own `diligence.evaluate_diligence` (the same policy `brain.enforce_
diligence` + the Stop hook enforce), so the court holds a leaf to the SAME bar
every client is held to.

────────────────────────────────────────────────────────────────────────────
THREE DIVERSE LENSES (a jury, not one judge)
────────────────────────────────────────────────────────────────────────────
The court refutes through three INDEPENDENT lenses, each a different kind of
evidence. A leaf goes green only when the jury's policy is satisfied (default:
unanimous among the lenses that APPLY, and at least one lens must actually
apply — silence is never green):

  1. ARTIFACT  — does the real artifact EXIST + satisfy the leaf predicate?
                 (py_compile a module, a file exists + matches a regex, a
                 pytest selector passes, a CDP DOM probe returns truthy.)
  2. DILIGENCE — never-reward-short. Runs `evaluate_diligence` over the
                 executor's closing claim + touched files + proof signals;
                 a "block" verdict (claim-without-proof, deferral language,
                 leftover markers) REFUTES the leaf. This is the anti-laziness
                 gate wired as a juror.
  3. INDEPENDENCE — anti-tamper. The juror identity MUST differ from the
                 executor that claimed the leaf (no self-certification), and
                 the artifact must be NAMED + REACHABLE (not "trust me"). A
                 leaf whose only evidence is the claimant's own word is refuted.

Each lens returns a `LensVerdict(refuted: bool, ...)`. `convene_court`
aggregates them into a `CourtVerdict`. "Fail to refute" (no applicable lens
refuted, ≥1 applied) == green.

SAFETY: pure + injectable. The artifact probes (py_compile / pytest / cdp) run
through small, injectable runners so tests stay hermetic and the live brain DB
is never touched. No network in the default path; the CDP lens is only invoked
when a leaf's `gate_kind == "cdp"` and a runner is provided.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


COURT_VERSION = "roma-court-v1"

# A lens runner is (gate_spec, context) -> (refuted, detail, evidence_ref).
# Injectable so the orchestrator/tests can stub the real-world probes.
ProbeRunner = Callable[[dict[str, Any], dict[str, Any]], "ProbeResult"]


@dataclass
class ProbeResult:
    """Raw outcome of a single artifact probe."""
    passed: bool                 # did the real artifact satisfy the predicate?
    applied: bool = True         # did this probe actually run / apply?
    detail: str = ""
    evidence_ref: Optional[str] = None  # path / DOM snippet / pytest line


@dataclass
class LensVerdict:
    lens: str                    # "artifact" | "diligence" | "independence"
    refuted: bool                # True == this lens REFUTES the leaf
    applied: bool                # False == lens not applicable to this leaf
    detail: str = ""
    evidence_ref: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CourtVerdict:
    """The jury's aggregated decision on one leaf."""
    node_id: str
    green: bool                  # True == failed-to-refute == may go GREEN
    verdict: str                 # "green" | "red" | "needs_root"
    lenses: list[LensVerdict] = field(default_factory=list)
    judged_by: str = "roma-court"
    reason: str = ""
    court_version: str = COURT_VERSION

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["lenses"] = [l.to_dict() for l in self.lenses]
        return d


# ─────────────────────────── artifact probes ───────────────────────────


def py_compile_probe(gate_spec: dict[str, Any], context: dict[str, Any]) -> ProbeResult:
    """REAL check: byte-compile a Python file. gate_spec={'path': '<file.py>'}.
    Mirrors the encode-safety floor ("every new module must py_compile")."""
    raw = gate_spec.get("path") or gate_spec.get("file")
    if not raw:
        return ProbeResult(passed=False, applied=False,
                           detail="py_compile gate has no 'path'")
    path = Path(raw)
    if not path.is_absolute():
        base = context.get("repo_root") or context.get("cwd")
        if base:
            path = Path(base) / raw
    if not path.exists():
        return ProbeResult(passed=False, detail=f"file does not exist: {path}",
                           evidence_ref=str(path))
    proc = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        capture_output=True, text=True,
    )
    ok = proc.returncode == 0
    return ProbeResult(
        passed=ok,
        detail=("py_compile OK" if ok else (proc.stderr or "py_compile failed").strip()[:400]),
        evidence_ref=str(path),
    )


def file_exists_probe(gate_spec: dict[str, Any], context: dict[str, Any]) -> ProbeResult:
    """REAL check: a file exists and (optionally) its text contains a marker /
    matches a regex. gate_spec={'path','contains'?|'regex'?}."""
    import re
    raw = gate_spec.get("path") or gate_spec.get("file")
    if not raw:
        return ProbeResult(passed=False, applied=False, detail="no 'path'")
    path = Path(raw)
    if not path.is_absolute():
        base = context.get("repo_root") or context.get("cwd")
        if base:
            path = Path(base) / raw
    if not path.exists():
        return ProbeResult(passed=False, detail=f"missing: {path}", evidence_ref=str(path))
    contains = gate_spec.get("contains")
    regex = gate_spec.get("regex")
    if contains or regex:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as ex:
            return ProbeResult(passed=False, detail=f"unreadable: {ex}", evidence_ref=str(path))
        if contains and contains not in text:
            return ProbeResult(passed=False, detail=f"'{contains}' not in {path.name}",
                               evidence_ref=str(path))
        if regex and not re.search(regex, text):
            return ProbeResult(passed=False, detail=f"/{regex}/ no match in {path.name}",
                               evidence_ref=str(path))
    return ProbeResult(passed=True, detail=f"exists{' + matched' if (contains or regex) else ''}",
                       evidence_ref=str(path))


def pytest_probe(gate_spec: dict[str, Any], context: dict[str, Any]) -> ProbeResult:
    """REAL check: run a pytest selector; pass iff exit 0. gate_spec=
    {'selector': 'tests/test_x.py::test_y', 'cwd'?}. The test suite IS the
    gate — same as the ArchHub pytest gate referenced in the encode brief."""
    selector = gate_spec.get("selector") or gate_spec.get("node_id")
    if not selector:
        return ProbeResult(passed=False, applied=False, detail="no pytest 'selector'")
    cwd = gate_spec.get("cwd") or context.get("repo_root") or context.get("cwd")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(selector), "-q", "-x"],
        capture_output=True, text=True, cwd=cwd,
    )
    ok = proc.returncode == 0
    tail = (proc.stdout or proc.stderr or "").strip().splitlines()[-3:]
    return ProbeResult(passed=ok, detail=" | ".join(tail)[:400], evidence_ref=str(selector))


# Registry of built-in artifact probes by gate_kind. "cdp" and any custom
# kind must be supplied by the caller via `extra_probes` (the CDP live-DOM
# probe needs a running app + websocket-client; it is NOT run in unit tests).
_BUILTIN_PROBES: dict[str, ProbeRunner] = {
    "py_compile": py_compile_probe,
    "file_exists": file_exists_probe,
    "pytest": pytest_probe,
}


# ─────────────────────────── the three lenses ──────────────────────────


def lens_artifact(
    *,
    gate_kind: str,
    gate_spec: dict[str, Any],
    context: dict[str, Any],
    extra_probes: Optional[dict[str, ProbeRunner]] = None,
) -> LensVerdict:
    """Lens 1 — does the REAL artifact satisfy the leaf predicate?"""
    probes = dict(_BUILTIN_PROBES)
    if extra_probes:
        probes.update(extra_probes)
    if gate_kind in ("manual", ""):
        # No machine gate declared — this lens cannot apply. A leaf with NO
        # machine-checkable predicate is the thing ROMA bans; `convene_court`
        # turns an all-inapplicable artifact lens into needs_root, never green.
        return LensVerdict(lens="artifact", refuted=False, applied=False,
                           detail="no machine gate (manual leaf)")
    runner = probes.get(gate_kind)
    if runner is None:
        return LensVerdict(lens="artifact", refuted=True, applied=True,
                           detail=f"no probe registered for gate_kind '{gate_kind}'")
    try:
        res = runner(gate_spec, context)
    except Exception as ex:  # a crashing probe REFUTES (fail-closed on the artifact)
        return LensVerdict(lens="artifact", refuted=True, applied=True,
                           detail=f"probe error: {type(ex).__name__}: {ex}")
    if not res.applied:
        return LensVerdict(lens="artifact", refuted=False, applied=False, detail=res.detail)
    return LensVerdict(
        lens="artifact",
        refuted=not res.passed,
        applied=True,
        detail=res.detail,
        evidence_ref=res.evidence_ref,
    )


def lens_diligence(*, context: dict[str, Any]) -> LensVerdict:
    """Lens 2 — NEVER REWARD SHORT. Run the brain's anti-laziness policy over
    the executor's closing evidence. A `block` verdict REFUTES the leaf.

    context['evidence'] = {last_message, touched_files?, file_contents?,
    session_signals?} — the SAME shape `brain.enforce_diligence` consumes."""
    ev = context.get("evidence")
    if not isinstance(ev, dict) or not ev.get("last_message"):
        # No closing evidence → diligence cannot apply (the artifact + the
        # independence lenses still must pass). Not a refutation by itself.
        return LensVerdict(lens="diligence", refuted=False, applied=False,
                           detail="no executor evidence to judge")
    try:
        from .diligence import evaluate_diligence
        verdict = evaluate_diligence(
            last_message=ev.get("last_message", ""),
            touched_files=ev.get("touched_files"),
            file_contents=ev.get("file_contents"),
            session_signals=ev.get("session_signals"),
        )
    except Exception as ex:
        # Fail-OPEN on the gate's OWN error (never brick the court) — mirrors
        # the Stop hook's fail-open-on-self-error contract.
        return LensVerdict(lens="diligence", refuted=False, applied=False,
                           detail=f"diligence gate error (fail-open): {ex}")
    blocked = verdict.verdict == "block"
    return LensVerdict(
        lens="diligence",
        refuted=blocked,
        applied=True,
        detail=(verdict.reason_text()[:400] if blocked else "diligence: no laziness signal"),
    )


def lens_independence(
    *,
    claimed_by: Optional[str],
    judged_by: str,
    artifact_lens: LensVerdict,
) -> LensVerdict:
    """Lens 3 — ANTI-TAMPER. The court identity must differ from the executor
    that claimed the leaf (no self-certification), and the green must be backed
    by a NAMED artifact (an evidence_ref), not the claimant's word alone."""
    if claimed_by and judged_by and judged_by == claimed_by:
        return LensVerdict(
            lens="independence", refuted=True, applied=True,
            detail=(f"self-certification: judge '{judged_by}' == executor "
                    f"'{claimed_by}' (the court must be independent)"),
        )
    # The green must rest on real evidence: the artifact lens must have APPLIED
    # and produced an evidence_ref. (Diligence alone is necessary-not-sufficient.)
    if artifact_lens.applied and not artifact_lens.evidence_ref and not artifact_lens.refuted:
        return LensVerdict(
            lens="independence", refuted=True, applied=True,
            detail="no named artifact evidence_ref backing the pass (trust-me green refused)",
        )
    return LensVerdict(lens="independence", refuted=False, applied=True,
                       detail="independent judge + named artifact")


# ─────────────────────────── convene the jury ──────────────────────────


def convene_court(
    *,
    node_id: str,
    gate_kind: str,
    gate_spec: dict[str, Any],
    claimed_by: Optional[str],
    judged_by: str = "roma-court",
    context: Optional[dict[str, Any]] = None,
    extra_probes: Optional[dict[str, ProbeRunner]] = None,
    require_diligence: bool = False,
) -> CourtVerdict:
    """Run the three lenses over one leaf and aggregate to a CourtVerdict.

    Policy (the jury rule):
      * Any APPLICABLE lens that REFUTES → verdict = "red" (re-work / re-decompose).
      * NO applicable artifact lens (a manual leaf with no machine gate) →
        verdict = "needs_root" (escalate to the founder; ROMA never greens an
        unverifiable leaf). This is the decomposition-floor escape.
      * `require_diligence=True` makes the diligence lens MANDATORY: if it does
        not apply (no executor evidence), the leaf is "red" (you must show the
        work) — the strict never-reward-short setting.
      * Otherwise (≥1 lens applied, none refuted) → "green" — failed to refute.

    Returns the CourtVerdict; the orchestrator feeds (green→set_verdict green,
    red→set_verdict red, needs_root→set_verdict needs_root)."""
    ctx = dict(context or {})

    art = lens_artifact(gate_kind=gate_kind, gate_spec=gate_spec, context=ctx,
                        extra_probes=extra_probes)
    dil = lens_diligence(context=ctx)
    ind = lens_independence(claimed_by=claimed_by, judged_by=judged_by,
                            artifact_lens=art)
    lenses = [art, dil, ind]

    applied = [l for l in lenses if l.applied]
    refuters = [l for l in applied if l.refuted]

    # 1) Any applicable lens refuted → RED.
    if refuters:
        reason = "REFUTED: " + " || ".join(f"[{l.lens}] {l.detail}" for l in refuters)
        return CourtVerdict(node_id=node_id, green=False, verdict="red",
                            lenses=lenses, judged_by=judged_by, reason=reason)

    # 2) No machine gate applied → cannot verify → escalate to founder.
    if not art.applied:
        return CourtVerdict(
            node_id=node_id, green=False, verdict="needs_root", lenses=lenses,
            judged_by=judged_by,
            reason=("no machine-checkable artifact gate on this leaf — ROMA "
                    "refuses to green an unverifiable leaf; split it into "
                    "machine-checkable children or the founder (root) decides"),
        )

    # 3) Strict never-reward-short: diligence must have actually applied.
    if require_diligence and not dil.applied:
        return CourtVerdict(
            node_id=node_id, green=False, verdict="red", lenses=lenses,
            judged_by=judged_by,
            reason=("require_diligence=True but no executor evidence to judge — "
                    "show the work (closing claim + proof signals) before green"),
        )

    # 4) Failed to refute, ≥1 lens applied → GREEN.
    return CourtVerdict(
        node_id=node_id, green=True, verdict="green", lenses=lenses,
        judged_by=judged_by,
        reason="FAILED TO REFUTE on the real artifact: " + "; ".join(
            f"[{l.lens}] {l.detail}" for l in applied
        ),
    )


# ─────────────────────────── CDP live-DOM lens (opt-in) ─────────────────


def make_cdp_probe(cdp_url: str = "http://127.0.0.1:9223") -> ProbeRunner:
    """Build a CDP live-DOM artifact probe (opt-in; needs a running ArchHub +
    websocket-client). Mirrors `tools/_verify_live_now.py`: it reads what the
    RUNNING canvas actually renders — not the disk.

    gate_spec for a cdp leaf:
        {'expression': '<JS that returns truthy when the leaf is satisfied>',
         'await_promise'?: bool, 'timeout'?: float}

    The JS runs via Runtime.evaluate(returnByValue) against the live page; the
    leaf passes iff the expression returns a truthy value. This makes the court
    gate on the REAL artifact (live DOM), the DEFINITION-OF-SHIPPED bar."""
    import json as _json
    import time as _time
    import urllib.request as _ureq

    def _probe(gate_spec: dict[str, Any], context: dict[str, Any]) -> ProbeResult:
        expr = gate_spec.get("expression")
        if not expr:
            return ProbeResult(passed=False, applied=False,
                               detail="cdp gate has no 'expression'")
        try:
            import websocket  # type: ignore  # websocket-client
        except ImportError:
            return ProbeResult(passed=False, applied=False,
                               detail="websocket-client not installed (cdp lens skipped)")
        base = context.get("cdp_url") or cdp_url
        try:
            with _ureq.urlopen(f"{base}/json", timeout=10) as r:
                tabs = _json.loads(r.read())
            tab = next((t for t in tabs
                        if "ArchHub" in (t.get("title") or "") or t.get("type") == "page"),
                       tabs[0] if tabs else None)
            if tab is None:
                return ProbeResult(passed=False, detail="no CDP tab found")
            ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=15,
                                             skip_utf8_validation=True)
        except Exception as ex:
            return ProbeResult(passed=False, applied=False,
                               detail=f"CDP connect failed (live app down?): {ex}")
        try:
            _id = 0

            def _call(method: str, params: dict, timeout: float) -> dict:
                nonlocal _id
                _id += 1
                ws.send(_json.dumps({"id": _id, "method": method, "params": params}))
                ws.settimeout(timeout)
                deadline = _time.time() + timeout
                while _time.time() < deadline:
                    try:
                        obj = _json.loads(ws.recv())
                    except Exception:
                        continue
                    if obj.get("id") == _id:
                        if "error" in obj:
                            raise RuntimeError(obj["error"])
                        return obj.get("result", {})
                raise TimeoutError(f"{method} no reply")

            _call("Runtime.enable", {}, 15.0)
            res = _call("Runtime.evaluate", {
                "expression": expr,
                "awaitPromise": bool(gate_spec.get("await_promise", False)),
                "returnByValue": True,
            }, float(gate_spec.get("timeout", 20.0)))
            if res.get("exceptionDetails"):
                return ProbeResult(passed=False, detail=f"JS exc: {res['exceptionDetails']}")
            value = res.get("result", {}).get("value")
            return ProbeResult(passed=bool(value),
                               detail=f"live DOM eval → {value!r}",
                               evidence_ref=f"cdp:{base}")
        finally:
            try:
                ws.close()
            except Exception:
                pass

    return _probe
