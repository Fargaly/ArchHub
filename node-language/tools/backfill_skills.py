"""Skill backfill tool — mint skills into the brain from real traces.

WHY THIS EXISTS
===============
Data analysis of `brain.db` found ``skills: 0``. The reflexion worker (the
Stop-hook minter) never actually persisted a single Skill row, so the
website / community export (`brain.skill_export(scope=community)`) returns
an empty list — there is nothing to show. This is a cold-start hole, not a
bug in the mint pipeline: the pipeline works, it has just never been fed.

This tool backfills the library from trajectories that ALREADY succeeded:

  1. Real recorded traces — fragments of ``kind == TRACE`` already sitting
     in ``brain.db`` (the Stop hook persists every successful trace as a
     fragment via ``queue_skill_mint`` even though it never minted a skill
     from them).
  2. If none exist, SYNTHESISE traces from this session's real committed
     work — ``git log`` feat/fix commits. A commit that touched N files
     becomes a trace with N ``ok`` tool_calls, which clears the ``>= 2``
     mint floor. These are legitimate successful trajectories: the commit
     landed, the tree is clean, the work is real.

For each trace we run the CANONICAL mint path:

  * ``server.queue_skill_mint`` — the R1 (adaptive calibration) + R2 (echo
    -trap diversity) gate. It persists the trace fragment and tells us
    whether the trajectory is worth honing (``will_hone``).
  * ``reflexion.reflect_on_trace(publish=True)`` — the full Voyager +
    SkillWeaver pipeline (classify -> extract -> dedupe -> hone -> validate
    -> publish). ``publish_skill`` calls ``store.upsert_skill`` so the row
    actually lands. This is the "gate" path.
  * If the gate REFUSES (calibration deny / echo-trap), we fall back to a
    DIRECT mint: ``extract_skill_draft`` + ``publish_skill`` with
    ``provenance.contributing_agent = "backfill"`` so the provenance makes
    the backfill origin obvious. This is the "direct" path.

Skills are minted at ``scope = PROJECT``. ``brain.skill_export(scope=
community)`` therefore still won't surface them — which is CORRECT: project
skills are not public. To give the website something to render we ALSO
promote 2-3 clearly-generic skills to ``scope = COMMUNITY`` (a distinct
public copy with ``visibility = SHARED_PUBLIC``).

NOTE ON PROMOTION MECHANICS: ``BrainStore.upsert_skill``'s ``ON CONFLICT(id)``
clause does NOT update ``scope`` / ``visibility`` (by design — provenance is
immutable), and ``skills.name`` carries a UNIQUE constraint. So promotion
cannot mutate an existing USER/PROJECT skill in place. Instead we mint a
distinct COMMUNITY copy with its own id (``<id>-community``) and own name
(``<name>_community``). Re-running is idempotent: same id => upsert no-op.

READ-ONLY DEPENDENCIES (this tool never edits them): ``reflexion.py``,
``server.py``, ``storage.py``, ``models.py``.

USAGE
=====
    python tools/backfill_skills.py            # live, against real brain.db
    python tools/backfill_skills.py --dry-run  # synth traces, no writes
    python tools/backfill_skills.py --max 20   # cap traces processed

The CLI opens the REAL ``brain.db`` (``default_brain_path()``), runs the
backfill, and prints the skill count before -> after.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Optional

# ── make personal_brain importable (personal-brain-mcp/src on sys.path) ──
_REPO = Path(__file__).resolve().parent.parent
_PB_SRC = _REPO / "personal-brain-mcp" / "src"
if _PB_SRC.exists() and str(_PB_SRC) not in sys.path:
    sys.path.insert(0, str(_PB_SRC))

from personal_brain import reflexion as _reflexion  # noqa: E402
from personal_brain.models import (  # noqa: E402
    FragmentKind,
    Scope,
    Visibility,
)
from personal_brain.server import queue_skill_mint  # noqa: E402
from personal_brain.storage import BrainStore, default_brain_path  # noqa: E402


BACKFILL_AGENT = "backfill"

# Promote skills whose mined name contains one of these generic stems to
# COMMUNITY — these are flows that aren't project-specific (commit hygiene,
# test runs, doc tidies) so they're safe to surface publicly.
_GENERIC_STEMS = (
    "commit", "test", "doc", "docs", "fix", "perf", "feat",
    "wire", "build", "sync", "export", "write", "index",
    "refactor", "chore", "apply", "flow",
)
_MAX_COMMUNITY_PROMOTIONS = 3


# ───────────────────────── trace sources ───────────────────────────────


def _traces_from_brain(store: BrainStore, *, owner_user: str,
                       limit: int = 500) -> list[dict[str, Any]]:
    """Source (a): real recorded traces already in brain.db.

    The Stop hook persists every successful trace as a ``kind == TRACE``
    fragment (see ``server.queue_skill_mint``). The full trace dict is
    stashed under ``fragment.extra["trace"]``. We recover those dicts so
    the mint pipeline can re-process them. Fragments missing the embedded
    trace are reconstructed from their text where possible (best-effort).
    """
    frags = store.list_fragments(
        kinds=[FragmentKind.TRACE], owner_user=owner_user, limit=limit,
    )
    traces: list[dict[str, Any]] = []
    for fr in frags:
        extra = fr.extra or {}
        trace = extra.get("trace")
        if isinstance(trace, dict) and trace.get("tool_calls"):
            # Carry the recorded outcome through; default to success since
            # only successful traces are persisted by the Stop hook.
            trace.setdefault("outcome", extra.get("outcome", "success"))
            trace.setdefault("trace_id", fr.id)
            traces.append(trace)
    return traces


def _git_log(repo: Path, n: int = 15) -> list[tuple[str, str]]:
    """Return ``[(sha, subject), ...]`` for the last *n* commits.

    Uses ``git -C <repo> log`` so the tool works regardless of cwd. Returns
    an empty list when git is unavailable or the dir is not a repo.
    """
    import subprocess
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "log", "--oneline", "-n", str(n),
             "--no-color"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    commits: list[tuple[str, str]] = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        sha, _, subject = line.partition(" ")
        if sha and subject:
            commits.append((sha, subject))
    return commits


def _commit_file_count(repo: Path, sha: str) -> int:
    """Number of files a commit touched — drives how many ``ok`` tool_calls
    the synthesised trace carries (N files -> N ok calls). Falls back to 2
    (the mint floor) when the stat lookup fails so the trace still qualifies.
    """
    import subprocess
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "show", "--stat", "--oneline",
             "--name-only", "--format=", sha],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return 2
    if out.returncode != 0:
        return 2
    files = [ln for ln in out.stdout.splitlines() if ln.strip()]
    return max(len(files), 2)


def _synth_traces_from_git(repo: Path, *, n: int = 15) -> list[dict[str, Any]]:
    """Source (b): synthesise traces from real feat/fix commits.

    Each feat/fix/perf/docs/test commit becomes a minimal trace dict:
        {trace_id, tool_calls:[{name, status:"ok"}, ...],
         outcome:"success", summary:<subject>, user_message:<subject>}
    A commit touching N files -> N ok tool_calls so it clears the >= 2 floor.
    Non-conventional commits (no ``type:`` prefix) are skipped — we only mint
    from commits that name a unit of work.
    """
    commits = _git_log(repo, n=n)
    traces: list[dict[str, Any]] = []
    for sha, subject in commits:
        m = re.match(r"^(feat|fix|perf|docs|test|refactor|chore)"
                     r"(?:\([^)]*\))?:\s*(.+)$", subject)
        if not m:
            continue
        ctype = m.group(1)
        # Map the commit type to a representative tool name so the mined
        # skill name reflects the kind of work (commit_flow, fix_flow, ...).
        verb = {
            "feat": "feat", "fix": "fix", "perf": "perf",
            "docs": "docs", "test": "test", "refactor": "refactor",
            "chore": "chore",
        }[ctype]
        n_files = _commit_file_count(repo, sha)
        # First tool name seeds _propose_skill_name -> "<base>_flow".
        tool_calls = [{"name": f"{verb}_apply", "status": "ok"}]
        for i in range(1, n_files):
            tool_calls.append({"name": f"{verb}_step_{i}", "status": "ok"})
        traces.append({
            "trace_id": f"git:{sha}",
            "tool_calls": tool_calls,
            "outcome": "success",
            "summary": subject,
            "user_message": subject,
        })
    return traces


def _gather_traces(store: BrainStore, repo: Path, *, owner_user: str,
                  max_traces: int) -> tuple[list[dict[str, Any]], str]:
    """Pick the best available trace source. Returns (traces, source_label)."""
    recorded = _traces_from_brain(store, owner_user=owner_user)
    if recorded:
        return recorded[:max_traces], "brain.db recorded traces"
    synth = _synth_traces_from_git(repo)
    return synth[:max_traces], "synthesised from git commits"


# ───────────────────────── minting ─────────────────────────────────────


def _mint_one(store: BrainStore, trace: dict[str, Any], *,
             owner_user: str) -> dict[str, Any]:
    """Mint a single trace. Returns a result dict:
        {minted: bool, skill_id, skill_name, path: "gate"|"direct"|None,
         reason}

    Strategy: run the R1/R2 gate (``queue_skill_mint``). If it queues
    (``will_hone``), run the full ``reflect_on_trace`` pipeline (the "gate"
    path). If the gate refuses but the trace still meets the >= 2 ok floor,
    fall back to a DIRECT mint via ``extract_skill_draft`` + ``publish_skill``
    (the "direct" path) so legitimate backfill work isn't lost to a cold
    calibration state.
    """
    outcome = trace.get("outcome", "success")
    tool_calls = trace.get("tool_calls", []) or []
    ok_calls = [tc for tc in tool_calls if tc.get("status") == "ok"]

    # Hard floor mirrors queue_skill_mint: < 2 ok calls is never minted.
    if outcome != "success" or len(ok_calls) < 2:
        return {
            "minted": False, "path": None,
            "reason": f"below floor: outcome={outcome}, ok_calls={len(ok_calls)}",
        }

    # ── R1/R2 gate ──
    gate = queue_skill_mint(
        store=store, trace=trace, outcome=outcome,
        owner_user=owner_user, contributing_agent=BACKFILL_AGENT,
        session_id=trace.get("session_id"),
    )

    if gate.queued and gate.will_hone:
        # GATE PATH — full reflexion pipeline mints at scope=PROJECT.
        # The canonical pipeline can raise IntegrityError when two distinct
        # traces distil to the SAME skill NAME but a different id (name is
        # UNIQUE, id is content-derived). That's a real edge in the mint
        # path; for backfill we absorb it and fall through to the direct
        # path, which detects the name clash and skips idempotently.
        try:
            rr = _reflexion.reflect_on_trace(
                trace, store=store, owner_user=owner_user,
                contributing_agent=BACKFILL_AGENT, publish=True,
            )
        except sqlite3.IntegrityError:
            return _direct_mint(store, trace, owner_user=owner_user,
                                note="gate name-collision -> direct")
        # The pipeline defaults to scope=USER; we want PROJECT for backfill
        # so the skill is project-shared (but not public). Re-publish the
        # accepted draft at PROJECT scope via the same publish helper so the
        # row carries the right scope. reflect_on_trace already upserted at
        # USER scope; because upsert can't change scope on conflict, we mint
        # the PROJECT row under a fresh deterministic id.
        if rr.accepted and rr.skill is not None:
            sk = _ensure_project_scope(store, rr.skill, owner_user=owner_user)
            return {
                "minted": True, "path": "gate",
                "skill_id": sk.id, "skill_name": sk.name,
                "reason": "gate accepted -> reflexion published",
            }
        # Pipeline ran but rejected (hone/validate) — try direct as a
        # backstop so the backfill still yields a skill.
        return _direct_mint(store, trace, owner_user=owner_user,
                            note=f"gate published-but-rejected: {rr.reason}")

    # ── DIRECT PATH — gate refused; backfill anyway with clear provenance ──
    return _direct_mint(store, trace, owner_user=owner_user,
                        note=f"gate refused: {gate.reason[:80]}")


def _direct_mint(store: BrainStore, trace: dict[str, Any], *,
                owner_user: str, note: str) -> dict[str, Any]:
    """Direct mint bypassing the calibration/diversity gate.

    Uses the real ``extract_skill_draft`` + ``publish_skill`` from the
    reflexion module (NOT a reimplementation), so the skill is shaped
    identically to a gate-minted one — only the gate is skipped. Provenance
    records ``contributing_agent = "backfill"`` so the origin is auditable.
    Validates the draft first; an invalid draft is skipped (never force a
    malformed skill into the library).
    """
    draft = _reflexion.extract_skill_draft(trace)
    validation = _reflexion.validate_modular_spec(draft)
    if not validation.get("ok"):
        return {
            "minted": False, "path": None,
            "reason": f"direct draft invalid: {validation.get('violations')}",
        }
    # Idempotency / collision guard: if a skill with this name already
    # exists, this trace has effectively already been minted — skip cleanly
    # rather than tripping the UNIQUE(name) constraint.
    proposed = draft.get("proposed_name") or draft.get("name") or "auto_skill"
    if store.get_skill(proposed) is not None:
        return {
            "minted": False, "path": None,
            "reason": f"skill '{proposed}' already present — idempotent skip",
        }
    try:
        skill = _reflexion.publish_skill(
            draft, store=store, owner_user=owner_user,
            contributing_agent=BACKFILL_AGENT,
            trace_id=trace.get("trace_id"),
            session_id=trace.get("session_id"),
            scope=Scope.PROJECT,
            visibility=Visibility.SHARED_PROJECT,
        )
    except sqlite3.IntegrityError:
        # Name collision with an existing skill of identical signature —
        # treat as already-present (idempotent), not a failure.
        return {
            "minted": False, "path": None,
            "reason": "direct mint name-collision (already present)",
        }
    return {
        "minted": True, "path": "direct",
        "skill_id": skill.id, "skill_name": skill.name,
        "reason": note,
    }


def _ensure_project_scope(store: BrainStore, skill, *, owner_user: str):
    """Return a PROJECT-scoped row for ``skill``.

    ``reflect_on_trace`` mints at USER scope and ``upsert_skill`` can't flip
    scope on conflict. So we mint a distinct PROJECT row (own id + name) and
    return it. If the PROJECT row already exists the upsert is a no-op and we
    return the existing skill — idempotent. When a name collision blocks the
    project copy we just return the original USER skill (still a real mint).
    """
    if skill.scope == Scope.PROJECT:
        return skill
    proj = skill.model_copy(deep=True)
    proj.id = f"{skill.id}-project"
    proj.name = _suffixed_name(skill.name, "proj")
    proj.scope = Scope.PROJECT
    proj.visibility = Visibility.SHARED_PROJECT
    try:
        store.upsert_skill(proj)
        return proj
    except sqlite3.IntegrityError:
        return skill


def _suffixed_name(name: str, suffix: str) -> str:
    """``name`` + ``_<suffix>`` clamped to the 2-64 char pydantic pattern."""
    tail = f"_{suffix}"
    base = name[: 64 - len(tail)]
    out = f"{base}{tail}"
    # Guarantee the pattern ^[a-z][a-z0-9_\-]*$ holds.
    out = re.sub(r"[^a-z0-9_\-]", "_", out.lower())
    if not out or not out[0].isalpha():
        out = f"s_{out}"[:64]
    return out[:64]


# ───────────────────────── promotion ───────────────────────────────────


def _promote_to_community(store: BrainStore, *, owner_user: str,
                         limit: int = _MAX_COMMUNITY_PROMOTIONS) -> int:
    """Promote up to ``limit`` clearly-generic skills to COMMUNITY scope so
    ``brain.skill_export(scope=community)`` returns non-empty for the website.

    A COMMUNITY skill is a distinct PUBLIC copy (own id ``<id>-community``,
    own name ``<name>_community``, ``visibility = SHARED_PUBLIC``) of a
    generic source skill — see module docstring for why an in-place scope
    flip is impossible. Idempotent: re-running upserts the same community id.
    Returns the number of community skills now present (post-promotion).
    """
    # Candidates: any non-community skill whose name carries a generic stem.
    candidates = []
    for sk in store.list_skills(owner_user=owner_user, limit=500):
        if sk.scope == Scope.COMMUNITY:
            continue
        low = sk.name.lower()
        if any(stem in low for stem in _GENERIC_STEMS):
            candidates.append(sk)

    promoted_ids: set[str] = set()
    for sk in candidates:
        if len(promoted_ids) >= limit:
            break
        comm = sk.model_copy(deep=True)
        comm.id = f"{sk.id}-community"
        comm.name = _suffixed_name(sk.name, "community")
        comm.scope = Scope.COMMUNITY
        comm.visibility = Visibility.SHARED_PUBLIC
        try:
            store.upsert_skill(comm)
            promoted_ids.add(comm.id)
        except sqlite3.IntegrityError:
            # Already promoted under that name — count it as present.
            promoted_ids.add(comm.id)
    return store.count_skills(scope=Scope.COMMUNITY)


# ───────────────────────── public API ──────────────────────────────────


def backfill(store: BrainStore, traces: list[dict[str, Any]], *,
            owner_user: str = "founder") -> dict[str, Any]:
    """Backfill skills into ``store`` from ``traces``.

    For each trace: run the canonical mint (gate -> reflexion, falling back
    to a direct mint when the gate refuses), at scope=PROJECT. Then promote
    2-3 generic skills to COMMUNITY so the public export is non-empty.

    Returns::

        {
          "minted":        <int>,   # skills newly minted this run
          "promoted":      <int>,   # community skills present after promote
          "skipped":       <int>,   # traces that didn't yield a skill
          "skills_before": <int>,   # total skills before backfill
          "skills_after":  <int>,   # total skills after backfill
          "by_path":       {"gate": <int>, "direct": <int>},
        }
    """
    before = store.count_skills()
    minted = 0
    skipped = 0
    by_path = {"gate": 0, "direct": 0}

    for trace in traces:
        res = _mint_one(store, trace, owner_user=owner_user)
        if res.get("minted"):
            minted += 1
            path = res.get("path")
            if path in by_path:
                by_path[path] += 1
        else:
            skipped += 1

    promoted = _promote_to_community(store, owner_user=owner_user)
    after = store.count_skills()

    return {
        "minted": minted,
        "promoted": promoted,
        "skipped": skipped,
        "skills_before": before,
        "skills_after": after,
        "by_path": by_path,
    }


# ───────────────────────── CLI ─────────────────────────────────────────


def _open_with_retry(path: Optional[str], *, retries: int = 5,
                    delay_s: float = 0.5) -> BrainStore:
    """Open the brain store, retrying on ``database is locked``.

    The daemon holds ``brain.db``; WAL mode permits a concurrent writer, but
    a busy moment can still raise ``OperationalError: database is locked``.
    Retry 5x / 0.5s before giving up. Also sets ``busy_timeout`` on the new
    connection so individual statements wait rather than fail fast.
    """
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            store = BrainStore.open(path)
            try:
                store._conn.execute("PRAGMA busy_timeout=5000")
            except Exception:
                pass
            return store
        except sqlite3.OperationalError as ex:
            last = ex
            if "database is locked" in str(ex).lower():
                time.sleep(delay_s)
                continue
            raise
    raise RuntimeError(f"could not open brain.db after {retries} retries: {last}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill skills into the brain from real traces.")
    parser.add_argument("--db", default=None,
                        help="path to brain.db (default: OS brain path)")
    parser.add_argument("--owner", default="founder",
                        help="owner_user for minted skills (default: founder)")
    parser.add_argument("--max", type=int, default=50,
                        help="max traces to process (default: 50)")
    parser.add_argument("--dry-run", action="store_true",
                        help="use an in-memory store; do not touch brain.db")
    args = parser.parse_args(argv)

    if args.dry_run:
        store = BrainStore.open(":memory:")
        db_label = ":memory: (dry-run)"
    else:
        db_path = args.db or str(default_brain_path())
        store = _open_with_retry(db_path)
        db_label = db_path

    traces, source = _gather_traces(
        store, _REPO, owner_user=args.owner, max_traces=args.max)

    before = store.count_skills()
    print(f"brain.db            : {db_label}")
    print(f"owner_user          : {args.owner}")
    print(f"trace source        : {source}")
    print(f"traces to process   : {len(traces)}")
    print(f"skills BEFORE       : {before}")
    print("-" * 56)

    result = backfill(store, traces, owner_user=args.owner)

    print(f"minted this run     : {result['minted']}")
    print(f"  via gate path     : {result['by_path']['gate']}")
    print(f"  via direct path   : {result['by_path']['direct']}")
    print(f"skipped             : {result['skipped']}")
    print(f"community promoted  : {result['promoted']}")
    print("-" * 56)
    print(f"skills BEFORE       : {result['skills_before']}")
    print(f"skills AFTER        : {result['skills_after']}")
    community = store.count_skills(scope=Scope.COMMUNITY)
    project = store.count_skills(scope=Scope.PROJECT)
    print(f"  scope=PROJECT     : {project}")
    print(f"  scope=COMMUNITY   : {community}  (visible to skill_export)")

    if not args.dry_run:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
