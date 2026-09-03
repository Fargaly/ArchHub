"""ROMA standing DISPATCHER — the loop that drains the requirement-tree on its
own: court-gated, FREE, and safe to leave running on the founder's machine.

This is the missing STANDING wrapper around the ROMA primitives. It is NOT a new
system — it is one thin loop over the EXISTING pieces (the ONE-SYSTEM mandate):

    requirement_tree  — the tree ledger (frontier / open_leaves / claim_leaf /
                        set_verdict), persisted additively in brain_meta. NOT
                        re-implemented here; imported.
    roma.judge_leaf   — convenes the EXISTING court (court_harness.convene_court,
                        3 lenses incl. anti-tamper independence) and records the
                        verdict. The dispatcher routes EVERY result through it so
                        a leaf goes GREEN only on a court-green verdict and only
                        when judged_by != claimed_by (anti-self-certify).
    proc_utils        — the shared TTL-cached process snapshot (process_names),
                        reused for "is the founder's ArchHub app in use right
                        now?" so the loop PAUSES while he is working
                        (off-while-in-app — the DONT-DISRUPT-THE-FOUNDER rule).
    free_fleet        — the FREE worker pool (codex/gemini/local subscription
                        CLIs, never a metered API). Imported DEFENSIVELY: if the
                        module is absent the routing step is a no-op so THIS lane
                        stands alone and still builds + tests.

────────────────────────────────────────────────────────────────────────────
THE FOUR SAFETY RAILS (load-bearing — see CLAUDE.md mandates)
────────────────────────────────────────────────────────────────────────────
  1. KILL-SWITCH FIRST. Every tick checks a kill-switch file BEFORE doing any
     work (default %LOCALAPPDATA%/ArchHub/dispatcher.stop). Present → the loop
     STOPS immediately (0 further iterations). `max_iterations` is the second
     bound. The founder can halt the daemon by touching one file.
  2. OFF-WHILE-IN-APP. When `idle_only` (default True), each tick PAUSES if the
     founder's ArchHub app is running (a python/pythonw bound to the install's
     `main.py`, detected via proc_utils' snapshot). It does NOT build over his
     session — the no-disrupt rule.
  3. COURT-GATED, FREE. A leaf is built by a FREE worker and then JUDGED by the
     EXISTING external court; `set_verdict` flips it GREEN only on a court-green
     verdict. `manual`-gated leaves are NEVER auto-built — they escalate
     (needs_root) to the founder. NO metered provider is reachable from this
     module: it imports no paid SDK and `cost_usd` is hard 0.0.
  4. PROPOSE-ONLY (P0). The loop NEVER force-pushes, NEVER merges to main, NEVER
     uses admin. It records build INTENT (a free worker may open a PR via its
     own gh path) but the actual merge stays a human/CI gate in v1. No
     destructive git from here.

SAFETY: pure-ish + injectable. The store, the kill-switch path, the fleet, the
court runner, the app-detector and the clock are all injectable so the loop is
hermetic under test (no real subprocess, no real brain.db, no sleeping). The
default wiring uses the real proc snapshot + the real court.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from . import requirement_tree as rt
from . import roma

if TYPE_CHECKING:  # typing only — no runtime import cycle / cost
    from .storage import BrainStore


# The dispatcher's identity as an executor/claimer. The COURT identity is
# distinct (DISPATCHER_COURT_ID) so judged_by != claimed_by always holds — the
# anti-self-certify anchor the court + set_verdict both re-check.
DISPATCHER_AGENT_ID = "roma-dispatcher"
DISPATCHER_COURT_ID = "roma-dispatcher-court"

# A leaf carrying NO machine gate is never auto-built — it escalates to the
# founder (ROMA "YOU = root"). These are the gate kinds that mean "no machine
# check on this leaf".
_MANUAL_GATE_KINDS = frozenset({"manual", ""})


def default_killswitch_path() -> Path:
    """%LOCALAPPDATA%/ArchHub/dispatcher.stop on Windows; an XDG-ish fallback
    elsewhere. Touch this file and the standing loop stops on its next tick."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ArchHub" / "dispatcher.stop"
    # POSIX / no-LOCALAPPDATA fallback, mirroring cloud_config's default-path style.
    return Path(os.path.expanduser("~")) / ".local" / "share" / "archhub" / "dispatcher.stop"


# ─────────────────────────── app-in-use detector ───────────────────────────


def app_in_use(install_root: Optional[str] = None) -> bool:
    """True iff the founder's ArchHub desktop app appears to be RUNNING.

    Reuses ``proc_utils.process_names()`` — the SAME shared TTL-cached snapshot
    every connector-health check uses — so the dispatcher adds no extra process
    enumeration cost. Detection is layered, strongest first:

      1. psutil cmdline (when available): a ``python``/``pythonw`` process whose
         command line includes the install's ``app/main.py`` (or just
         ``main.py`` under an ``app`` dir bound to ``install_root``). This is the
         precise "the app the founder launched" signal.
      2. proc_utils snapshot fallback: if psutil is unavailable we cannot read
         cmdlines, so we fall back to the image-name snapshot. We ONLY treat a
         bare ``pythonw.exe`` as the app when no install_root is given (best
         effort) — pythonw is the documented launcher (``pythonw app/main.py``).
         With an install_root and no psutil we conservatively return False (we
         can't confirm the binding, and a false "in use" would wedge the loop).

    Fail-OPEN to "not in use" on any detector error: a broken detector must
    NEVER permanently pause the loop (it just means the kill-switch + court are
    the remaining guards). Conversely the loop treats a True here as "pause",
    so the cost of a rare false-True is only a skipped tick.
    """
    root = (install_root or "").replace("\\", "/").rstrip("/").lower()

    # 1) Precise: psutil cmdline match.
    try:
        import psutil  # type: ignore

        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if "python" not in name:  # python.exe / pythonw.exe / python3
                    continue
                cmd = " ".join(proc.info.get("cmdline") or []).replace("\\", "/").lower()
                if "main.py" not in cmd:
                    continue
                # main.py launched as the app entrypoint (…/app/main.py). When an
                # install_root is supplied, require the cmdline to sit under it so
                # a DIFFERENT checkout's app doesn't count as the founder's.
                if "app/main.py" in cmd or "/main.py" in cmd or cmd.endswith("main.py"):
                    if root and root not in cmd:
                        continue
                    return True
            except Exception:
                continue
        # psutil worked but found no matching app process.
        return False
    except Exception:
        pass

    # 2) Fallback: proc_utils image-name snapshot (no cmdlines available).
    try:
        from proc_utils import process_names  # type: ignore

        names = process_names()
        if root:
            # Can't confirm the binding from image names alone → conservative.
            return False
        return any("pythonw" in n for n in names)
    except Exception:
        return False


# ─────────────────────────── free-worker routing ───────────────────────────


@dataclass
class WorkerOutcome:
    """What a FREE worker reports back after attempting a leaf. The dispatcher
    NEVER trusts ``built`` to flip a leaf green — only the court does. This just
    carries the closing evidence the court's diligence lens judges + the
    provider name for the FREE audit + the always-zero cost."""
    built: bool = False
    provider: str = ""                       # e.g. "codex" | "gemini" | "local"
    evidence: dict[str, Any] = field(default_factory=dict)  # {last_message, ...}
    cost_usd: float = 0.0                     # MUST be 0.0 — FREE only
    detail: str = ""


# A free worker is (leaf, context) -> WorkerOutcome. Injectable for tests; the
# default resolves free_fleet.run_worker at call time (defensive import).
FreeWorkerFn = Callable[["rt.ReqNode", dict[str, Any]], WorkerOutcome]


class MeteredProviderError(RuntimeError):
    """Raised if a worker/fleet ever reports a non-zero cost or a metered
    provider. The whole point of the dispatcher is FREE — a paid call is a
    hard error, not a silent charge."""


def _free_guard(outcome: WorkerOutcome) -> WorkerOutcome:
    """The money firewall. A worker outcome is allowed through ONLY if it is
    free: ``cost_usd`` must be exactly 0.0 (and never negative/NaN). Any other
    value is refused — the dispatcher never records a build that cost money."""
    cost = getattr(outcome, "cost_usd", 0.0)
    try:
        costf = float(cost)
    except Exception:
        costf = 1.0  # unparseable cost is treated as "not provably free" → refuse
    if costf != 0.0:
        raise MeteredProviderError(
            f"worker reported non-zero cost_usd={cost!r} from provider "
            f"'{getattr(outcome, 'provider', '?')}' — the dispatcher is FREE-only; "
            f"refusing to record a metered build"
        )
    return outcome


def _resolve_free_worker(fleet: Any) -> Optional[FreeWorkerFn]:
    """Resolve the FREE worker callable.

    Order:
      1. an explicit ``fleet`` (test/injection): a callable, or an object with a
         ``run_worker``/``run`` method.
      2. ``free_fleet.run_worker`` — the real FREE pool, imported DEFENSIVELY.
    Returns None when no free worker is reachable → the routing step no-ops and
    THIS lane still stands alone (the leaf is simply judged as-is by the court,
    which for an already-built artifact can still go green).
    """
    if fleet is not None:
        if callable(fleet):
            return fleet  # a bare run_worker(leaf, ctx) function
        for attr in ("run_worker", "run"):
            fn = getattr(fleet, attr, None)
            if callable(fn):
                return fn
    # Defensive import of the real free pool — absent today, so this no-ops and
    # the lane stands alone (the spec's requirement). When free_fleet lands it
    # is picked up with zero changes here.
    try:
        from . import free_fleet  # type: ignore
    except Exception:
        return None
    fn = getattr(free_fleet, "run_worker", None)
    return fn if callable(fn) else None


def _coerce_outcome(raw: Any) -> WorkerOutcome:
    """Normalise whatever a free worker returns into a WorkerOutcome (a worker
    may return a WorkerOutcome, a dict, or None for a no-op)."""
    if isinstance(raw, WorkerOutcome):
        return raw
    if isinstance(raw, dict):
        return WorkerOutcome(
            built=bool(raw.get("built", False)),
            provider=str(raw.get("provider", "")),
            evidence=raw.get("evidence") or {},
            cost_usd=float(raw.get("cost_usd", 0.0) or 0.0),
            detail=str(raw.get("detail", "")),
        )
    return WorkerOutcome()  # None / unknown → no-op outcome (still free)


# ─────────────────────────── status snapshot ───────────────────────────────


@dataclass
class DispatcherStatus:
    running: bool = False
    paused_reason: Optional[str] = None      # why the last tick did no build
    iterations: int = 0                      # ticks that actually ran a leaf
    leaves_greened: int = 0                  # court-green leaves recorded
    providers_used: list[str] = field(default_factory=list)  # FREE providers seen
    cost_usd: float = 0.0                     # ALWAYS 0.0 — FREE only
    killswitch: Optional[str] = None         # the kill-switch path in effect
    # Extra audit fields (additive — status() returns the spec keys + these):
    leaves_claimed: int = 0
    leaves_escalated: int = 0                 # manual/needs_root → founder
    stopped_reason: Optional[str] = None      # why run_standing returned

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "paused_reason": self.paused_reason,
            "iterations": self.iterations,
            "leaves_greened": self.leaves_greened,
            "providers_used": list(dict.fromkeys(self.providers_used)),  # de-dup, ordered
            "cost_usd": 0.0,  # hard-wired: the dispatcher never spends
            "killswitch": self.killswitch,
            "leaves_claimed": self.leaves_claimed,
            "leaves_escalated": self.leaves_escalated,
            "stopped_reason": self.stopped_reason,
        }


# A single module-level latest-status so a separate caller (an MCP status tool /
# a UI chip) can read what the loop is doing without holding the loop object.
_LATEST: DispatcherStatus = DispatcherStatus()


def status() -> dict[str, Any]:
    """The dispatcher's current/last snapshot:
    {running, paused_reason, iterations, leaves_greened, providers_used,
     cost_usd:0.0, killswitch, ...}. cost_usd is ALWAYS 0.0 (FREE-only)."""
    return _LATEST.to_dict()


# ─────────────────────────── the standing loop ─────────────────────────────


def _next_claimable_leaf(
    store: "BrainStore",
    *,
    tree_ids: Optional[list[str]],
) -> tuple[Optional[str], Optional[rt.ReqNode], list[rt.ReqNode]]:
    """Scan trees for the next BUILDABLE leaf + collect the manual leaves that
    must escalate.

    Returns (tree_id, leaf, escalate_leaves):
      * leaf = the first OPEN/RED leaf with a MACHINE gate (gate_kind not in
        {manual, ''}) — the only kind the dispatcher auto-builds.
      * escalate_leaves = OPEN/RED leaves whose gate_kind is manual (so the
        caller can mark them needs_root → the founder; NEVER auto-built).
    A leaf is pulled via the tree's own ``open_leaves`` frontier (so CLAIMED /
    GREEN / already-NEEDS_ROOT leaves are excluded)."""
    ids = tree_ids if tree_ids is not None else rt.list_trees(store)
    escalate: list[rt.ReqNode] = []
    for tid in ids:
        try:
            claimable = rt.open_leaves(store, tree_id=tid)
        except KeyError:
            continue
        for leaf in claimable:
            if leaf.gate_kind in _MANUAL_GATE_KINDS:
                escalate.append(leaf)
                continue
            return tid, leaf, escalate
    return None, None, escalate


def run_standing(
    *,
    store: Optional["BrainStore"] = None,
    max_iterations: Optional[int] = None,
    idle_only: bool = True,
    killswitch_path: Optional[str] = None,
    fleet: Any = None,
    tree_ids: Optional[list[str]] = None,
    install_root: Optional[str] = None,
    poll_seconds: float = 30.0,
    judged_by: str = DISPATCHER_COURT_ID,
    agent_id: str = DISPATCHER_AGENT_ID,
    require_diligence: bool = False,
    # ── injection seams (tests/daemon) — all default to the REAL wiring ──
    app_in_use_fn: Optional[Callable[[], bool]] = None,
    court_fn: Optional[Callable[..., dict[str, Any]]] = None,
    sleep_fn: Optional[Callable[[float], None]] = None,
    on_tick: Optional[Callable[[DispatcherStatus], None]] = None,
) -> dict[str, Any]:
    """Run the standing dispatcher loop until the kill-switch fires, the
    iteration cap is hit, or the buildable frontier is dry.

    Each TICK, in order:
      1. KILL-SWITCH — if the kill-switch file exists → STOP immediately (the
         loop returns; 0 further iterations). Checked FIRST, before any work.
      2. CAP — if ``max_iterations`` is reached → STOP.
      3. IDLE GATE — if ``idle_only`` and the founder's ArchHub app is in use →
         PAUSE this tick (no claim, no build); sleep ``poll_seconds`` and re-check
         (off-while-in-app). With ``max_iterations`` set, a paused tick still
         counts toward the cap so a test/daemon can bound a paused run.
      4. PULL — the next OPEN/RED leaf with a MACHINE gate (manual leaves are
         escalated to needs_root → the founder, NEVER auto-built). Dry frontier
         (no buildable leaf, nothing to escalate) → STOP.
      5. CLAIM — claim the leaf as ``agent_id`` (the executor identity).
      6. BUILD (FREE) — route to the free worker (free_fleet.run_worker or the
         injected fleet); a missing fleet no-ops (lane stands alone). The money
         firewall refuses any non-zero-cost outcome.
      7. COURT — judge the leaf through the EXISTING court (roma.judge_leaf →
         court_harness.convene_court + set_verdict). The leaf goes GREEN only on
         a court-green verdict, and only because judged_by != claimed_by.
      8. RECORD — bump counters; loop.

    Returns the final ``status()`` dict (cost_usd always 0.0). Updates the
    module-level snapshot every tick so an external reader sees live progress.

    NEVER force-pushes / merges / uses admin (P0). The loop only PROPOSES — the
    actual merge to main stays a human/CI gate in v1.
    """
    global _LATEST

    if store is None:
        # The real daemon wiring: open the brain store at its OS-appropriate
        # per-user path (BrainStore.open() with no arg resolves
        # storage.default_brain_path() — %APPDATA%/ArchHub/brain/brain.db on
        # Windows). Kept lazy so importing this module costs nothing and tests
        # always inject a :memory: store.
        from .storage import BrainStore

        store = BrainStore.open()

    ks_path = Path(killswitch_path) if killswitch_path else default_killswitch_path()
    _app_in_use = app_in_use_fn or (lambda: app_in_use(install_root))
    _court = court_fn or _default_court_fn(store)
    _sleep = sleep_fn or time.sleep

    st = DispatcherStatus(running=True, killswitch=str(ks_path))
    _LATEST = st

    def _killed() -> bool:
        try:
            return ks_path.exists()
        except Exception:
            return False  # an unreadable path is not a kill signal (fail-open)

    tick = 0
    try:
        while True:
            # 1) KILL-SWITCH FIRST — before ANY work, before counting a tick.
            if _killed():
                st.stopped_reason = "killswitch"
                st.paused_reason = "killswitch"
                break

            # 2) CAP.
            if max_iterations is not None and tick >= max_iterations:
                st.stopped_reason = "max_iterations"
                break
            tick += 1

            # 3) IDLE GATE — off-while-in-app.
            if idle_only:
                try:
                    in_use = bool(_app_in_use())
                except Exception:
                    in_use = False  # detector error must never wedge the loop
                if in_use:
                    st.paused_reason = "app_in_use"
                    if on_tick:
                        on_tick(st)
                    # Paused: no claim, no build. Re-check after a poll. The cap
                    # already advanced so a bounded run can't spin forever.
                    if max_iterations is not None and tick >= max_iterations:
                        st.stopped_reason = "max_iterations"
                        break
                    _sleep(poll_seconds)
                    continue

            # 4) PULL the next buildable leaf (+ collect manual escalations).
            tid, leaf, escalate = _next_claimable_leaf(store, tree_ids=tree_ids)

            # Escalate manual leaves to the founder (needs_root) — NEVER built.
            for m in escalate:
                _escalate_to_root(store, tree_id=_tree_of(store, m, tree_ids),
                                  node=m, judged_by=judged_by, st=st)

            if leaf is None or tid is None:
                # Dry buildable frontier. If we escalated this tick, that WAS
                # progress (the founder now has work); otherwise nothing to do.
                st.stopped_reason = "frontier_dry"
                st.paused_reason = None if escalate else "frontier_dry"
                if on_tick:
                    on_tick(st)
                break

            st.paused_reason = None

            # 5) CLAIM (executor identity; the court identity differs).
            try:
                rt.claim_leaf(store, tree_id=tid, node_id=leaf.node_id, agent_id=agent_id)
            except (KeyError, ValueError):
                # Lost the race / already claimed / no longer a claimable leaf —
                # skip to the next tick (another worker has it).
                if on_tick:
                    on_tick(st)
                continue
            st.leaves_claimed += 1

            # 6) BUILD on a FREE worker (no-op if no fleet → lane stands alone).
            ctx: dict[str, Any] = {
                "executor_id": agent_id,
                "install_root": install_root,
                "tree_id": tid,
                "node_id": leaf.node_id,
            }
            outcome = _run_free_worker(fleet, leaf, ctx)
            if outcome.provider:
                st.providers_used.append(outcome.provider)
            if outcome.evidence:
                ctx["evidence"] = outcome.evidence

            # 7) COURT — the EXISTING jury decides green; set_verdict flips it
            # only on green AND only because judged_by != claimed_by.
            try:
                result = _court(tree_id=tid, node_id=leaf.node_id,
                                judged_by=judged_by, context=ctx,
                                require_diligence=require_diligence)
            except Exception as ex:
                # A court error never crashes the standing loop — treat as a
                # non-green tick and move on (the leaf stays CLAIMED/its prior
                # state; a later tick or the founder can revisit).
                st.paused_reason = f"court_error: {type(ex).__name__}"
                if on_tick:
                    on_tick(st)
                continue

            verdict = ((result or {}).get("court") or {}).get("verdict")
            if verdict == "green":
                st.leaves_greened += 1
            elif verdict == "needs_root":
                st.leaves_escalated += 1

            # 8) RECORD this completed build tick.
            st.iterations += 1
            if on_tick:
                on_tick(st)
    finally:
        st.running = False
        _LATEST = st

    return st.to_dict()


# ─────────────────────────── internal helpers ──────────────────────────────


def _default_court_fn(store: "BrainStore") -> Callable[..., dict[str, Any]]:
    """The real court path: roma.judge_leaf, which convenes
    court_harness.convene_court (3 lenses: artifact / diligence / independence)
    and records the verdict via set_verdict. This is the ONE-SYSTEM reuse — the
    dispatcher does NOT re-implement judging."""

    def _judge(*, tree_id: str, node_id: str, judged_by: str,
               context: dict[str, Any], require_diligence: bool) -> dict[str, Any]:
        return roma.judge_leaf(
            store, tree_id=tree_id, node_id=node_id, judged_by=judged_by,
            context=context, require_diligence=require_diligence,
        )

    return _judge


def _run_free_worker(fleet: Any, leaf: "rt.ReqNode", ctx: dict[str, Any]) -> WorkerOutcome:
    """Resolve + invoke the FREE worker, passing every outcome through the money
    firewall. A missing worker or a worker error degrades to a no-op outcome
    (still free) so the lane stands alone and the court still judges the leaf."""
    worker = _resolve_free_worker(fleet)
    if worker is None:
        return WorkerOutcome(detail="no free worker reachable (lane stands alone)")
    try:
        raw = worker(leaf, ctx)
        return _free_guard(_coerce_outcome(raw))
    except MeteredProviderError as ex:
        # The money firewall fired: a worker tried to charge. REFUSE it (drop
        # its evidence) and continue free — a paid call must never crash the
        # standing loop NOR be recorded. The leaf is then judged with no FREE
        # evidence, so a metered build can never green it.
        return WorkerOutcome(detail=f"REFUSED metered build (FREE-only): {ex}")
    except Exception as ex:
        return WorkerOutcome(detail=f"free worker error: {type(ex).__name__}: {ex}")


def _tree_of(store: "BrainStore", node: "rt.ReqNode",
             tree_ids: Optional[list[str]]) -> str:
    """Find which tree a frontier node belongs to (frontier nodes don't carry
    their tree id). Scans the candidate tree ids for one containing the node."""
    ids = tree_ids if tree_ids is not None else rt.list_trees(store)
    for tid in ids:
        tree = rt.get_tree(store, tree_id=tid)
        if tree is not None and node.node_id in tree.nodes:
            return tid
    return ids[0] if ids else ""


def _escalate_to_root(store: "BrainStore", *, tree_id: str, node: "rt.ReqNode",
                      judged_by: str, st: DispatcherStatus) -> None:
    """Mark a MANUAL leaf needs_root (escalate to the founder) — NEVER auto-built.

    Routed through the SAME set_verdict the court uses (one system). A
    needs_root verdict carries no green, bumps no re-work, and reserves the leaf
    for the founder (ROMA "YOU = root"). Idempotent-ish: a leaf already
    NEEDS_ROOT is excluded by the open_leaves frontier, so this only fires once."""
    if not tree_id:
        return
    try:
        rt.set_verdict(store, tree_id=tree_id, node_id=node.node_id,
                       verdict="needs_root", judged_by=judged_by,
                       evidence_ref="manual leaf — no machine gate; founder decides")
        st.leaves_escalated += 1
    except (KeyError, ValueError):
        pass
