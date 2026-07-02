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

import hmac
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional


COURT_VERSION = "roma-court-v2"

# ─────────────────────────── identity + root token ──────────────────────
#
# AUDIT FIX (2026-07-02 forensic audit, defect 1): judged_by / claimed_by are
# free strings supplied by callers. Exact `==` let 'Exec-1' judge a leaf claimed
# by 'exec-1' (case-flip self-certification) and ' exec-1 ' (trailing space).
# EVERY identity comparison must go through this normalizer — both here and in
# requirement_tree.set_verdict (which imports it, ONE definition, ONE system).

ROOT_TOKEN_ENV = "ARCHHUB_ROOT_TOKEN"


def normalize_agent(ident: Optional[str]) -> str:
    """Canonical agent identity: strip + casefold. 'Exec-1' == ' exec-1 '."""
    return (ident or "").strip().casefold()


def root_token_ok(token: Optional[str]) -> bool:
    """True iff the environment holds a root token AND `token` matches it
    (constant-time compare). No env token configured → NOTHING authenticates:
    the root-override path is closed, never open-by-default."""
    expected = (os.environ.get(ROOT_TOKEN_ENV) or "").strip()
    supplied = (token or "").strip()
    if not expected or not supplied:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), supplied.encode("utf-8"))


# ─────────────────── juror weights + confidence soft-vote ───────────────
#
# Founder-authored spec (grand-map node selfext_juror_diversity, 2026-07-02):
# each lens carries a confidence 0..1; green requires (a) NO refuted lens —
# fail-closed absolute — AND (b) the confidence-weighted soft vote of the
# applied, non-refuted lenses to clear the threshold. Below threshold the
# court escalates (needs_root), it never guesses green.

LENS_WEIGHTS: dict[str, float] = {
    "artifact": 2.0,      # the primary evidence: the real artifact itself
    "diligence": 1.0,
    "independence": 1.0,
}
SOFT_VOTE_THRESHOLD = 0.7

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
    confidence: float = 1.0      # 0..1 — how strong this evidence is
    failure_mode: str = ""       # typed tag when the probe refutes ("" == none)


@dataclass
class LensVerdict:
    lens: str                    # "artifact" | "diligence" | "independence"
    refuted: bool                # True == this lens REFUTES the leaf
    applied: bool                # False == lens not applicable to this leaf
    detail: str = ""
    evidence_ref: Optional[str] = None
    confidence: float = 1.0      # 0..1 — feeds the weighted soft vote
    failure_mode: str = ""       # typed tag when refuted ("" == no failure)

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
#
# AUDIT FIX (defect 4, GATE-BINDING): the artifact lens never read the leaf's
# CLAIM — 'cure cancer' gated on C:/Windows/win.ini went green because win.ini
# exists. Pragmatic binding: when the caller supplies `leaf_created_at`
# (roma.judge_leaf / brain.tree_court pass the leaf's created_at), a target
# file whose mtime PREDATES the leaf's creation REFUTES — a pre-existing
# artifact cannot prove new work. Opt-out (`gate_spec['pre_existing_ok']=true`)
# is honoured ONLY on the root-token path (context['root_token'] must match
# env ARCHHUB_ROOT_TOKEN).


# Grace window for the mtime-vs-created_at compare. Filesystem timestamps and
# the wall clock come from different sources (FAT is 2 s granular; on NTFS the
# cached file time can trail GetSystemTimePreciseAsFileTime by ~1 ms — measured
# while un-rigging), so a file written a moment AFTER the leaf can stat a hair
# BEFORE it. 2 s cannot rescue a genuinely pre-existing artifact (minutes to
# years old) but stops the honest write-right-after-decompose path flapping red.
STALE_GRACE_SECONDS = 2.0


def _leaf_created_ts(context: dict[str, Any]) -> Optional[float]:
    """The leaf's creation instant as a POSIX timestamp, or None when the
    caller did not bind the gate to a leaf (no staleness check then)."""
    raw = context.get("leaf_created_at")
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, datetime):
        return raw.timestamp()
    try:
        return datetime.fromisoformat(str(raw)).timestamp()
    except Exception:
        return None


def _stale_artifact_reason(
    path: Path, gate_spec: dict[str, Any], context: dict[str, Any],
) -> Optional[str]:
    """Refutation reason when `path` pre-dates the leaf it claims to prove,
    else None. pre_existing_ok=true is honoured only with a valid root token."""
    ts = _leaf_created_ts(context)
    if ts is None:
        return None
    if gate_spec.get("pre_existing_ok") is True and (
        context.get("_root_token_ok") or root_token_ok(context.get("root_token"))
    ):
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError as ex:
        return f"cannot stat artifact {path}: {ex}"
    if mtime < ts - STALE_GRACE_SECONDS:
        return (
            f"pre-existing artifact refused: {path} was last modified BEFORE this "
            f"leaf was created (mtime={mtime:.3f} < leaf_created_at={ts:.3f}) — a "
            f"pre-existing file cannot prove new work. gate_spec.pre_existing_ok "
            f"is honoured only with the root token (env {ROOT_TOKEN_ENV})."
        )
    return None


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
    stale = _stale_artifact_reason(path, gate_spec, context)
    if stale:
        return ProbeResult(passed=False, detail=stale, evidence_ref=str(path),
                           failure_mode="stale_artifact")
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
    stale = _stale_artifact_reason(path, gate_spec, context)
    if stale:
        return ProbeResult(passed=False, detail=stale, evidence_ref=str(path),
                           failure_mode="stale_artifact")
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
                           detail=f"no probe registered for gate_kind '{gate_kind}'",
                           failure_mode="unknown_gate")
    try:
        res = runner(gate_spec, context)
    except Exception as ex:  # a crashing probe REFUTES (fail-closed on the artifact)
        return LensVerdict(lens="artifact", refuted=True, applied=True,
                           detail=f"probe error: {type(ex).__name__}: {ex}",
                           failure_mode="probe_error")
    if not res.applied:
        return LensVerdict(lens="artifact", refuted=False, applied=False, detail=res.detail)
    conf = res.confidence
    try:
        conf = min(1.0, max(0.0, float(conf)))
    except (TypeError, ValueError):
        conf = 0.0  # an unparseable confidence is NO confidence (fail-closed)
    return LensVerdict(
        lens="artifact",
        refuted=not res.passed,
        applied=True,
        detail=res.detail,
        evidence_ref=res.evidence_ref,
        confidence=conf,
        failure_mode=(res.failure_mode or "artifact_refuted") if not res.passed else "",
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
        failure_mode="never_reward_short" if blocked else "",
    )


def lens_independence(
    *,
    claimed_by: Optional[str],
    judged_by: str,
    artifact_lens: LensVerdict,
) -> LensVerdict:
    """Lens 3 — ANTI-TAMPER. The court identity must differ from the executor
    that claimed the leaf (no self-certification), and the green must be backed
    by a NAMED artifact (an evidence_ref), not the claimant's word alone.

    AUDIT FIXES: identities are NORMALIZED (strip+casefold) before comparison —
    'Exec-1' can no longer judge a leaf claimed by 'exec-1' (defect 1). An
    UNCLAIMED leaf has no executor to be independent OF, so this lens does not
    apply (defect 2) — convene_court's jury-of-one rule then escalates instead
    of greening on the artifact alone, and set_verdict independently refuses
    to green an unclaimed leaf."""
    claimer = normalize_agent(claimed_by)
    judge = normalize_agent(judged_by)
    if not claimer:
        return LensVerdict(
            lens="independence", refuted=False, applied=False,
            detail=("no claimed executor — independence cannot be established "
                    "on an unclaimed leaf (never a green by itself)"),
        )
    if judge and judge == claimer:
        return LensVerdict(
            lens="independence", refuted=True, applied=True,
            detail=(f"self-certification: judge '{judged_by}' == executor "
                    f"'{claimed_by}' after normalization (the court must be "
                    f"independent)"),
            failure_mode="self_certification",
        )
    # The green must rest on real evidence: the artifact lens must have APPLIED
    # and produced an evidence_ref. (Diligence alone is necessary-not-sufficient.)
    if artifact_lens.applied and not artifact_lens.evidence_ref and not artifact_lens.refuted:
        return LensVerdict(
            lens="independence", refuted=True, applied=True,
            detail="no named artifact evidence_ref backing the pass (trust-me green refused)",
            failure_mode="unnamed_evidence",
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
    leaf_created_at: Optional[Any] = None,
    leaf_title: str = "",
    leaf_predicate: str = "",
) -> CourtVerdict:
    """Run the three lenses over one leaf and aggregate to a CourtVerdict.

    Policy (the jury rule):
      * Any APPLICABLE lens that REFUTES → verdict = "red" — fail-closed
        ABSOLUTE, whatever the confidence numbers say.
      * NO applicable artifact lens (a manual leaf with no machine gate) →
        verdict = "needs_root" (escalate to the founder; ROMA never greens an
        unverifiable leaf). This is the decomposition-floor escape.
      * `require_diligence=True` makes the diligence lens MANDATORY: if it does
        not apply (no executor evidence), the leaf is "red" (you must show the
        work) — the strict never-reward-short setting.
      * JURY-OF-ONE (selfext_juror_diversity): on a machine-gated leaf, fewer
        than 2 APPLIED lenses (the artifact alone) → "needs_root" — a jury of
        one is not a jury, never green.
      * CONFIDENCE SOFT-VOTE: green additionally requires the confidence-
        weighted vote of the applied non-refuted lenses,
        sum(conf*weight)/sum(weights), to reach SOFT_VOTE_THRESHOLD; below →
        "needs_root".
      * Otherwise → "green" — failed to refute.

    GATE-BINDING: `leaf_created_at` (the leaf's creation instant — roma/tree
    callers pass it) binds file gates to the CLAIM: a target file whose mtime
    predates the leaf refutes (a pre-existing artifact cannot prove new work).
    `leaf_title` / `leaf_predicate` are recorded into the verdict reason so the
    evidence string names WHAT was allegedly proven.

    Returns the CourtVerdict; the orchestrator feeds (green→set_verdict green,
    red→set_verdict red, needs_root→set_verdict needs_root)."""
    ctx = dict(context or {})
    if leaf_created_at is not None:
        ctx["leaf_created_at"] = leaf_created_at
    ctx["_root_token_ok"] = root_token_ok(ctx.get("root_token"))

    leaf_tag = ""
    if leaf_title or leaf_predicate:
        leaf_tag = f" [leaf: title={leaf_title!r} predicate={leaf_predicate!r}]"

    art = lens_artifact(gate_kind=gate_kind, gate_spec=gate_spec, context=ctx,
                        extra_probes=extra_probes)
    dil = lens_diligence(context=ctx)
    ind = lens_independence(claimed_by=claimed_by, judged_by=judged_by,
                            artifact_lens=art)
    lenses = [art, dil, ind]

    applied = [l for l in lenses if l.applied]
    refuters = [l for l in applied if l.refuted]

    # 1) Any applicable lens refuted → RED (absolute; confidence never rescues).
    if refuters:
        reason = "REFUTED: " + " || ".join(
            f"[{l.lens}/{l.failure_mode or 'refuted'}] {l.detail}" for l in refuters
        ) + leaf_tag
        return CourtVerdict(node_id=node_id, green=False, verdict="red",
                            lenses=lenses, judged_by=judged_by, reason=reason)

    # 2) No machine gate applied → cannot verify → escalate to founder.
    if not art.applied:
        return CourtVerdict(
            node_id=node_id, green=False, verdict="needs_root", lenses=lenses,
            judged_by=judged_by,
            reason=("no machine-checkable artifact gate on this leaf — ROMA "
                    "refuses to green an unverifiable leaf; split it into "
                    "machine-checkable children or the founder (root) decides"
                    + leaf_tag),
        )

    # 3) Strict never-reward-short: diligence must have actually applied.
    if require_diligence and not dil.applied:
        return CourtVerdict(
            node_id=node_id, green=False, verdict="red", lenses=lenses,
            judged_by=judged_by,
            reason=("require_diligence=True but no executor evidence to judge — "
                    "show the work (closing claim + proof signals) before green"
                    + leaf_tag),
        )

    # 4) JURY-OF-ONE: a machine-gated leaf where only the artifact lens applied
    #    (e.g. an unclaimed leaf with no executor evidence) is NOT a jury —
    #    escalate, never green on a single juror.
    if len(applied) < 2:
        return CourtVerdict(
            node_id=node_id, green=False, verdict="needs_root", lenses=lenses,
            judged_by=judged_by,
            reason=(f"jury of one: only {len(applied)} lens applied "
                    f"({', '.join(l.lens for l in applied) or 'none'}) — the "
                    f"artifact alone is not a jury; claim the leaf + supply "
                    f"executor evidence, or the founder (root) decides" + leaf_tag),
        )

    # 5) CONFIDENCE SOFT-VOTE: weighted mean confidence of the applied,
    #    non-refuted lenses must clear the threshold.
    total_w = sum(LENS_WEIGHTS.get(l.lens, 1.0) for l in applied)
    score = (
        sum(l.confidence * LENS_WEIGHTS.get(l.lens, 1.0) for l in applied) / total_w
        if total_w > 0 else 0.0
    )
    if score < SOFT_VOTE_THRESHOLD:
        return CourtVerdict(
            node_id=node_id, green=False, verdict="needs_root", lenses=lenses,
            judged_by=judged_by,
            reason=(f"confidence soft-vote {score:.2f} < "
                    f"{SOFT_VOTE_THRESHOLD} — the jury is not confident enough "
                    f"to green; escalated to the founder" + leaf_tag),
        )

    # 6) Failed to refute, real jury, confident → GREEN.
    return CourtVerdict(
        node_id=node_id, green=True, verdict="green", lenses=lenses,
        judged_by=judged_by,
        reason=(f"FAILED TO REFUTE on the real artifact (soft-vote "
                f"{score:.2f}): " + "; ".join(
                    f"[{l.lens}] {l.detail}" for l in applied) + leaf_tag),
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


# ─────────────────── node_cooks live-runner probe (the engine rung) ─────────


# A value the artifact lens must REFUSE — an output port that came back as one
# of these is NOT a real cook, it is a shell. Mirrors the connector-honesty
# contract (an offline host yields a typed error / missing_dep, never a
# fabricated value) and the runner's degraded-passthrough (a bodyless node
# echoes None). The probe treats all three as a refutation, not a green.
_DEGRADED_STATUSES = frozenset({"error", "missing_dep", "upstream_error",
                                "degraded", "needs_root"})

# When a real cook reports it needs a live host / credential, the probe
# retries with a typed-mock seed and (on a real typed value) greens with this
# verdict tag instead of escalating — "cooks-with-mock" is still GREEN (the
# node's wiring + output shape are proven; only the live host is unavailable in
# the court sandbox). The orchestrator surfaces this tag on the verdict.
COOKS_WITH_MOCK = "cooks-with-mock"


def _type_matches(value: Any, declared: str) -> bool:
    """Does a cooked output VALUE match the node's DECLARED output port type?

    Declared is the library/runner port-type token (graph.PortType values:
    'string','number','boolean','list','object','any', plus the bridge/AI/AEC
    tokens). 'any' (or an unknown token) always matches — the type system is
    permissive by design (ANY ports accept anything). A concrete primitive
    token must match the Python type so a node that DECLARES a list but cooks a
    bare string is refuted (a shape lie). Non-primitive tokens (host/element/
    geometry/…) are structural — we accept any non-None, non-degraded value
    (the value-is-real check already ran)."""
    d = (declared or "any").strip().lower()
    if d in ("", "any"):
        return True
    if d == "string":
        return isinstance(value, str)
    if d == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if d == "boolean":
        return isinstance(value, bool)
    if d == "list":
        return isinstance(value, (list, tuple))
    if d in ("object", "json", "dict"):
        return isinstance(value, dict)
    # Bridge / AI / AEC / IO / geometry tokens are structural references — any
    # concrete (already non-None, non-degraded) value satisfies the contract.
    return True


def _is_degraded_output(outputs: Any) -> Optional[str]:
    """Return a refutation reason if a runner cook result is a degraded shell
    (error / missing_dep / upstream_error sentinel), else None. Mirrors the
    WorkflowRunner / connector-honesty sentinels so a fabricated/None/typed-
    error result can NEVER pass as a real cook."""
    if not isinstance(outputs, dict):
        return None
    status = str(outputs.get("status") or "").strip().lower()
    if status in _DEGRADED_STATUSES:
        return f"runner returned degraded status={status!r}: {outputs.get('error') or outputs.get('detail') or ''}".strip()
    if outputs.get("error") and "status" not in outputs:
        return f"runner returned an error dict: {outputs.get('error')}"
    return None


def make_node_cooks_probe(
    *,
    build_min_graph: Callable[[dict[str, Any]], dict[str, Any]],
    cook: Callable[[dict[str, Any], str, dict[str, Any]], Any],
    declared_output: Callable[[dict[str, Any]], tuple[str, str]],
    mock_cook: Optional[Callable[[dict[str, Any], str, dict[str, Any]], Any]] = None,
) -> ProbeRunner:
    """Build the `node_cooks` artifact probe — the ENGINE RUNG of self-extend.

    Unlike `registered_node` (which only asserts the minted type is registered
    + inspectable — a SHELL check), this probe proves the node actually WORKS:
    it builds a MINIMAL real graph (a typed seed/constant wired into the new
    node type), drives the REAL `app/workflows` runner (WorkflowRunner) on the
    REGISTERED type, and asserts the new node's declared OUTPUT PORT yields a
    value that is

      * NOT an error dict ({'error': ...}),
      * NOT a missing-dependency sentinel ({'status': 'missing_dep'}),
      * NOT the degraded passthrough-None (a bodyless shell echoes None),
      * and MATCHES the node's declared output port type (a list-declaring node
        that cooks a bare string is refuted — a shape lie).

    This is the DEFINITION-OF-SHIPPED bar expressed per node: observable real
    output on the real runner, not "the type is registered." It REUSES the
    existing runner (ONE-SYSTEM — no mock cook for the real path); the callables
    are injected so this module stays free of any `app/` import (the binding
    lives in agents.self_extend, mirroring the registered_node probe).

    Injected callables:
      build_min_graph(gate_spec) -> graph dict   — a typed seed wired to the node
      cook(graph, node_id, gate_spec)  -> outputs — drive WorkflowRunner.pull
      declared_output(gate_spec) -> (port_name, port_type) — from library.inspect
      mock_cook(graph, node_id, gate_spec) -> outputs  — OPTIONAL: re-cook with a
          typed-mock ctx (mock router / connector) when the real cook reports it
          needs a live host/credential; a real typed value here greens with the
          COOKS_WITH_MOCK tag rather than escalating to needs_root.

    gate_spec keys: {'type': '<minted type id>'} (+ anything the injected
    builders read). The probe is fail-CLOSED: any builder/cook exception or a
    non-existent type REFUTES (a crashing node is not a working node)."""

    def _probe(gate_spec: dict[str, Any], context: dict[str, Any]) -> ProbeResult:
        type_name = (gate_spec.get("type") or "").strip()
        if not type_name:
            return ProbeResult(passed=False, applied=False,
                               detail="node_cooks gate has no 'type'")
        try:
            port_name, port_type = declared_output(gate_spec)
        except Exception as ex:
            return ProbeResult(passed=False, applied=True,
                               detail=f"type '{type_name}' not registered / "
                                      f"no declared output: {ex}",
                               evidence_ref=f"node:{type_name}")
        if not port_name:
            return ProbeResult(passed=False, applied=True,
                               detail=f"type '{type_name}' declares no output port",
                               evidence_ref=f"node:{type_name}")
        try:
            graph = build_min_graph(gate_spec)
            outputs = cook(graph, type_name, gate_spec)
        except Exception as ex:
            return ProbeResult(passed=False, applied=True,
                               detail=f"real cook crashed: {type(ex).__name__}: {ex}",
                               evidence_ref=f"node:{type_name}")

        degraded = _is_degraded_output(outputs)
        used_mock = False
        # If the real cook needs a live host / credential, retry with a typed
        # mock seed/ctx so the node's wiring + output shape can still be proven.
        if (degraded and mock_cook is not None
                and isinstance(outputs, dict)
                and str(outputs.get("status") or "").lower()
                    in ("missing_dep", "error", "needs_root")):
            try:
                outputs = mock_cook(graph, type_name, gate_spec)
                used_mock = True
                degraded = _is_degraded_output(outputs)
            except Exception:
                pass  # keep the real degraded result → refute below

        if degraded:
            return ProbeResult(passed=False, applied=True, detail=degraded,
                               evidence_ref=f"node:{type_name}.{port_name}")

        # Pull the declared output port's value. A bodyless / shell node echoes
        # None on its output — the degraded-None refutation.
        value = outputs.get(port_name) if isinstance(outputs, dict) else outputs
        if value is None:
            return ProbeResult(
                passed=False, applied=True,
                detail=(f"declared output port '{port_name}' returned None "
                        "(degraded passthrough-None — the node did not cook a "
                        "real value)"),
                evidence_ref=f"node:{type_name}.{port_name}")

        if not _type_matches(value, port_type):
            return ProbeResult(
                passed=False, applied=True,
                detail=(f"output '{port_name}' cooked a {type(value).__name__} "
                        f"but the port declares type '{port_type}' (shape lie)"),
                evidence_ref=f"node:{type_name}.{port_name}")

        tag = f" [{COOKS_WITH_MOCK}]" if used_mock else ""
        return ProbeResult(
            passed=True, applied=True,
            detail=(f"node cooked a real {port_type or 'any'} on output "
                    f"'{port_name}'{tag}: {repr(value)[:120]}"),
            evidence_ref=f"node:{type_name}.{port_name}")

    return _probe


# ─────────────── ui_renders live-render probe (the UI RUNG) ──────────────
#
# The UI twin of make_node_cooks_probe. Where node_cooks drives the REAL runner
# on a minted node type, ui_renders launches an ISOLATED ArchHub (temp profile,
# NO_GPU, free CDP port, --no-dev-source-sync — per reference_isolated-cdp-verify-
# launch.md) and asserts, against the LIVE DOM, that an agent-authored widget
# (1) RENDERS + is VISIBLE, (2) did NOT blank the app (the shell still painted
# with the expected node/shell count — a JSX fault blanks EVERYTHING, this catches
# it), and (3) raised zero uncaught / React-error-boundary console errors. Green
# only if all three hold. This is the founder's guardrail expressed per-widget:
# free-form widget code is allowed, but it cannot ship if it breaks the app.
#
# This module stays free of any `app/` import: the actual isolated-instance launch
# + CDP eval lives in the binding (agents.self_extend._make_ui_renders_probe),
# injected here as `live_probe`. The probe shape mirrors node_cooks: fail-CLOSED
# (any launch/CDP/eval exception REFUTES — a widget that can't be proven to render
# safely is not a working widget).


def make_ui_renders_probe(
    *,
    live_probe: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
) -> ProbeRunner:
    """Build the `ui_renders` artifact probe — the UI RUNG of self-extend.

    Injected callable:
      live_probe(gate_spec, context) -> dict — launches the ISOLATED ArchHub,
        registers the widget, and runs the three CDP assertions. MUST return:
          {
            "rendered":   bool,   # widget element present + offsetParent!=null
            "app_alive":  bool,   # ANTI-BLANK: app root still painted (shell ok)
            "errors":     [..],   # uncaught / error-boundary console errors
            "detail":     str,    # human summary for the receipt
            "evidence_ref": str,  # e.g. "cdp:ui_widget:<id>"
            "applied":    bool?,  # False => env couldn't run (e.g. no app/CDP)
          }
        A live_probe that cannot run the live check (missing dep / launch
        failure it wants to treat as inconclusive) sets applied=False; the court
        then escalates rather than greening. Any EXCEPTION from live_probe is
        fail-closed → REFUTE.

    gate_spec keys: {'widget_id': '<sanitized id>', 'testid'?: '<dom testid>'}.
    Green requires rendered AND app_alive AND no errors."""

    def _probe(gate_spec: dict[str, Any], context: dict[str, Any]) -> ProbeResult:
        wid = (gate_spec.get("widget_id") or gate_spec.get("id") or "").strip()
        if not wid:
            return ProbeResult(passed=False, applied=False,
                               detail="ui_renders gate has no 'widget_id'")
        try:
            res = live_probe(gate_spec, context)
        except Exception as ex:  # fail-closed: an unprovable widget is refuted
            return ProbeResult(passed=False, applied=True,
                               detail=f"ui_renders live probe crashed: "
                                      f"{type(ex).__name__}: {ex}",
                               evidence_ref=f"ui_widget:{wid}")
        if not isinstance(res, dict):
            return ProbeResult(passed=False, applied=True,
                               detail="ui_renders live probe returned non-dict",
                               evidence_ref=f"ui_widget:{wid}")
        if res.get("applied") is False:
            # The live environment could not run the check (no app / no CDP /
            # missing websocket-client). Inconclusive — NOT a green, NOT a hard
            # refute; convene_court turns an inapplicable artifact lens into
            # needs_root (escalate to the founder), never a silent green.
            return ProbeResult(passed=False, applied=False,
                               detail=res.get("detail")
                                      or "ui_renders live check could not run "
                                         "(no running app / CDP)",
                               evidence_ref=res.get("evidence_ref")
                                            or f"ui_widget:{wid}")
        rendered = bool(res.get("rendered"))
        app_alive = bool(res.get("app_alive"))
        errors = res.get("errors") or []
        ev = res.get("evidence_ref") or f"cdp:ui_widget:{wid}"
        detail = res.get("detail") or ""
        # Green requires ALL THREE: widget visible, app NOT blanked, no errors.
        if not app_alive:
            return ProbeResult(passed=False, applied=True, evidence_ref=ev,
                               detail=("ANTI-BLANK FAIL: the app root did not "
                                       "stay painted after the widget rendered "
                                       "(a JSX fault blanked the shell). "
                                       + detail).strip())
        if errors:
            joined = "; ".join(str(e)[:140] for e in errors[:4])
            return ProbeResult(passed=False, applied=True, evidence_ref=ev,
                               detail=f"widget raised console/error-boundary "
                                      f"errors: {joined}")
        if not rendered:
            return ProbeResult(passed=False, applied=True, evidence_ref=ev,
                               detail=("widget element did not render / is not "
                                       "visible (offsetParent==null). "
                                       + detail).strip())
        return ProbeResult(passed=True, applied=True, evidence_ref=ev,
                           detail=("widget rendered + visible, app shell intact, "
                                   "zero console errors. " + detail).strip())

    return _probe
