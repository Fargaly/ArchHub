#!/usr/bin/env python3
r"""safety_court_gate — the FAIL-CLOSED safety-axis gate for the git hooks.

ROOT CAUSE THIS CORRECTS
------------------------
Every existing safety control in this repo is either advisory rule-text the
executor self-grades, or a gate with a self-held off-switch
(`ARCHHUB_ALLOW_CS_EDIT=1`, the brain-gate's warn-default + fail-open,
`--no-verify`). The ONLY mechanically-blocking control (the Stop hook) scores
COMPLETION, never SAFETY. This module is the missing fail-closed SAFETY gate.

WHAT IT DOES
------------
Given a set of changed paths + their ADDED diff lines (computed for a commit via
`git diff --cached`, or for a push via the pushed commit range), it:

  1. CLASSIFIES the change into risky SAFETY classes:
       - main         : the push/commit targets main/master
       - cs           : touches payload/sources/**/*.cs (the brokers)
       - secret       : an ADDED line matches a credential-format literal
       - ui_theme     : touches the UI theme strand (studio-lm.jsx theme block /
                        accent tokens / __archhubSetTheme) — the class behind the
                        2026-06-04 "app stranded in blue" failure
       - failurelog_open : touches a file named in an OPEN docs/FAILURE_LOG.md entry
  2. If NO risky class fires -> exit 0 (a normal feature-branch commit/push with
     no .cs / secret / theme / main / open-failure file passes UNTOUCHED).
  3. If ANY risky class fires -> convenes the REAL ROMA court
     (personal_brain.court_harness.convene_court via an isolated, dedicated
     BrainStore) over one machine-checkable leaf PER fired class, judged by an
     identity DIFFERENT from the executor (no self-certification), and BLOCKS
     (exit 2) unless the court returns a FULL GREEN SWEEP.

FAIL CLOSED — the inversion of the brain-gate bug
-------------------------------------------------
On ANYTHING uncertain the gate BLOCKS, never allows:
  * a risky class fired but the court could not be imported / run  -> BLOCK
  * the court returned red OR needs_root for any class             -> BLOCK
  * git plumbing failed so the diff is unknown while a ref is risky-> BLOCK
  * an internal error in this script while a risky class is in play-> BLOCK
The only way past a fired class is: the court GREENs every class-leaf, OR the
FOUNDER authorises via the un-forgeable founder-secret (tools/founder_secret.py).
There is NO agent-settable env that turns this gate off.

USAGE (from the hooks)
----------------------
  commit:  python tools/safety_court_gate.py --mode commit
  push:    python tools/safety_court_gate.py --mode push \
               --branch <local_ref> --range <remote_sha>..<local_sha>
  (a fresh-branch push passes --range <local_sha> with --first-push; the gate
   then scopes to the genuinely-new commits via `git rev-list <local_sha>
   --not --remotes` and PASSES when that set is empty)

Exit: 0 = allowed (no risky class, or court fully green, or founder-authorised)
      2 = BLOCKED (a risky class fired and was not cleared)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

_REPO = Path(__file__).resolve().parent.parent
_BRAIN_SRC = _REPO / "personal-brain-mcp" / "src"

# ── risky-class patterns ────────────────────────────────────────────────

_CS_GLOB_RE = re.compile(r"(^|/)payload/sources/.+\.cs$", re.IGNORECASE)

# UI theme strand: the file + the specific theme machinery. Touching
# studio-lm.jsx alone is NOT enough (that would gate all UI work); we require a
# theme-relevant ADDED line, OR a change to a theme asset. The accent hex tokens
# and the theme setter are the load-bearing surface (studio-lm.jsx:26/35/62).
_UI_THEME_FILE_RE = re.compile(r"(^|/)app/web_ui/studio-lm\.jsx$", re.IGNORECASE)
_UI_THEME_LINE_RE = re.compile(
    r"(__archhubSetTheme|__archhubGetTheme|data-theme|_themeBlock|"
    r"\baccent\s*:|\baccentSoft\b|\baccentDim\b|\baccentHi\b|"
    r"archhub\.theme|FORGE|BLUEPRINT|VELLUM)",
)

# Credential-format literals. Each is a high-precision pattern for a real secret
# shape. We scan ONLY added lines (see _added_lines) so pre-existing fixtures
# never trip a new commit.
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("github_pat", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("github_fine_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("generic_bearer_secret", re.compile(
        r"(?i)(?:api[_-]?key|secret|token|passwd|password)\s*[:=]\s*['\"][A-Za-z0-9/+_\-]{24,}['\"]")),
]

# Well-known PUBLIC example tokens that appear in docs/tests and are NOT real
# secrets — exempt so redaction-test fixtures + AWS's canonical example don't
# false-block. (These are published by the vendors as non-secret examples.)
_SECRET_ALLOWLIST_SUBSTR = (
    "AKIAIOSFODNN7EXAMPLE",          # AWS's documented example access key id
    "wJalrXUtnFEMI/K7MDENG",         # AWS's documented example secret (prefix)
    "AKIA1234567890ABCDEF",          # obvious placeholder in our redaction tests
    "sk-1234567890abcdef1234",       # obvious placeholder in our redaction tests
    "sk-ABCDEFGHIJKLMNOP1234567890",  # obvious placeholder in our redaction tests
)

# Paths whose ADDED secret-format lines are legitimate (redaction-test fixtures
# whose WHOLE PURPOSE is to carry credential-shaped strings). Kept tight: only
# the redaction/secret test fixtures, never product code under app/ or payload/.
_SECRET_PATH_EXEMPT_RE = re.compile(
    r"(test_.*redact|redaction|test_acl|test_secret|/tests?/).*\.(py|txt|json|md)$",
    re.IGNORECASE,
)


# ── git plumbing (fail-closed: a plumbing failure while risky -> block) ──


def _git(args: list[str]) -> tuple[int, str]:
    # Read bytes + decode UTF-8 with replacement so a .cs / binary-ish blob with
    # bytes outside the locale codepage (cp1252 on Windows) can NEVER crash the
    # gate with a UnicodeDecodeError. (text=True would use the locale codec.)
    try:
        proc = subprocess.run(["git", *args], capture_output=True,
                              cwd=str(_REPO), timeout=30)
        return proc.returncode, proc.stdout.decode("utf-8", errors="replace")
    except Exception:
        return 1, ""


def _staged_paths() -> tuple[Optional[list[str]], bool]:
    """(paths, ok). ok=False signals a git failure → caller fails closed."""
    rc, out = _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    if rc != 0:
        return None, False
    return [ln.strip() for ln in out.splitlines() if ln.strip()], True


def _range_paths(rng: str) -> tuple[Optional[list[str]], bool]:
    rc, out = _git(["diff", "--name-only", "--diff-filter=ACMR", rng])
    if rc != 0:
        return None, False
    return [ln.strip() for ln in out.splitlines() if ln.strip()], True


def _new_branch_commits(local_sha: str) -> tuple[Optional[list[str]], bool]:
    """The commits a brand-new-branch push genuinely ADDS: reachable from
    local_sha but NOT on ANY remote-tracking ref (`git rev-list <local_sha>
    --not --remotes`). Returns (commit_shas, ok); ok=False on a git failure →
    caller FAILS CLOSED.

    JURY 2026-06-04 (FLAW 2): the prior `-200 <local_sha>` scope walked the last
    200 commits of HISTORY (which include historical broker .cs + main/theme
    commits), so a clean .py first-push off origin/main re-scanned and WRONGLY
    blocked. Scoping to `--not --remotes` makes the inspected set EXACTLY the
    new commits — an empty set for a branch that adds nothing, so it passes."""
    rc, out = _git(["rev-list", local_sha, "--not", "--remotes"])
    if rc != 0:
        return None, False
    commits = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return commits, True


def _first_push_paths(local_sha: str) -> tuple[Optional[list[str]], bool]:
    """Changed paths across ONLY the genuinely-new commits of a first push.
    FAIL CLOSED on a git error. An empty new-commit set → no paths (pass)."""
    commits, ok = _new_branch_commits(local_sha)
    if not ok:
        return None, False
    if not commits:
        return [], True  # nothing genuinely new — no risky paths to inspect
    # --no-walk: each LISTED commit's own diff, never its ancestry. Never call
    # this with an empty commit list (that would default to HEAD and re-scan it).
    rc, out = _git(["log", "--no-walk", "--name-only", "--pretty=format:",
                    *commits, "--diff-filter=ACMR"])
    if rc != 0:
        return None, False
    seen = []
    for ln in out.splitlines():
        ln = ln.strip()
        if ln and ln not in seen:
            seen.append(ln)
    return seen, True


def _first_push_added_lines(local_sha: str) -> tuple[dict[str, list[str]], bool]:
    """{path: [added lines]} across ONLY the genuinely-new commits of a first
    push (same scope as _first_push_paths). FAIL CLOSED on a git error; an empty
    new-commit set → empty map (no added lines to judge → no secret/theme class).

    Uses `git log --no-walk -p --unified=0` so each new commit contributes its
    OWN patch — the correct disjoint-commit analogue of a `remote..local` diff,
    not a diff against an arbitrary parent."""
    commits, ok = _new_branch_commits(local_sha)
    if not ok:
        return {}, False
    if not commits:
        return {}, True
    rc, out = _git(["log", "--no-walk", "-p", "--unified=0", "--pretty=format:",
                    *commits, "--diff-filter=ACMR"])
    if rc != 0:
        return {}, False
    return _parse_added_from_diff(out), True


def _parse_added_from_diff(out: str) -> dict[str, list[str]]:
    """Shared unified-diff '+'-line parser (used by range + first-push paths)."""
    result: dict[str, list[str]] = {}
    cur: Optional[str] = None
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            cur = line[len("+++ b/"):].strip()
            result.setdefault(cur, [])
        elif line.startswith("+++ "):
            cur = None
        elif line.startswith("+") and not line.startswith("+++") and cur:
            result[cur].append(line[1:])
    return result


def _added_lines(paths_scope: str) -> tuple[dict[str, list[str]], bool]:
    """Map {path: [added lines]} for the unified diff of `paths_scope`
    ('--cached' or a range). Only '+' lines (not '+++'). ok=False on git fail.
    (For a brand-new branch use _first_push_added_lines, which scopes to the
    genuinely-new commits.)"""
    if paths_scope == "--cached":
        rc, out = _git(["diff", "--cached", "--unified=0", "--diff-filter=ACMR"])
    else:
        rc, out = _git(["diff", "--unified=0", "--diff-filter=ACMR", paths_scope])
    if rc != 0:
        return {}, False
    return _parse_added_from_diff(out), True


# ── FAILURE_LOG open-class parse (currently read by nothing) ─────────────


def open_failurelog_tokens() -> set[str]:
    """Parse docs/FAILURE_LOG.md and return file-path-ish tokens named inside
    any entry whose `- **status**:` is NOT `closed` (open / partially-closed /
    pending count as OPEN). These are the files the founder flagged as not-yet-
    resolved; touching one is a risky class until the entry is closed.

    Best-effort + fail-closed-friendly: on a read/parse miss returns an empty
    set (no false class), but the CALLER treats "could not read FAILURE_LOG
    while a diff is in play" conservatively (see classify)."""
    path = _REPO / "docs" / "FAILURE_LOG.md"
    tokens: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return tokens
    # split into per-entry blocks on the "### " headers
    blocks = re.split(r"(?m)^### ", text)
    path_re = re.compile(r"[A-Za-z0-9_./\-]+\.(?:py|jsx?|cs|md|html|ps1|cjs|sql|json|toml|yml|yaml)")
    for block in blocks:
        m = re.search(r"(?im)^\s*-\s*\*\*status\*\*\s*:\s*([a-z\- ]+)", block)
        if not m:
            continue
        status = m.group(1).strip().lower()
        if status.startswith("closed"):
            continue  # resolved — not a risky class
        # OPEN-ish entry: collect every file-path-shaped token it names.
        for tok in path_re.findall(block):
            norm = tok.replace("\\", "/").lstrip("./").lower()
            # ignore bare doc self-references + the log itself
            if norm.endswith("failure_log.md"):
                continue
            tokens.add(norm)
    return tokens


# ── classification ──────────────────────────────────────────────────────


def _norm(p: str) -> str:
    return p.strip().replace("\\", "/").lstrip("./")


def classify(
    *,
    paths: list[str],
    added: dict[str, list[str]],
    targets_main: bool,
    failurelog_ok: bool,
    failurelog_tokens: set[str],
) -> dict[str, Any]:
    """Return {classes: {name: [evidence...]}, ...}. A class with a non-empty
    evidence list is FIRED."""
    classes: dict[str, list[str]] = {}

    if targets_main:
        classes.setdefault("main", []).append("push/commit targets main/master")

    for p in paths:
        n = _norm(p)
        if _CS_GLOB_RE.search(n):
            classes.setdefault("cs", []).append(n)

    # UI theme strand: studio-lm.jsx touched AND a theme-relevant added line,
    # OR any other web_ui theme asset path.
    for p in paths:
        n = _norm(p)
        if _UI_THEME_FILE_RE.search(n):
            lines = added.get(p) or added.get(n) or []
            if any(_UI_THEME_LINE_RE.search(ln) for ln in lines):
                classes.setdefault("ui_theme", []).append(
                    f"{n} (theme token / setter touched)")
            elif not added:
                # We couldn't read added lines (git plumbing) but the theme file
                # is in the changeset → fail-closed: treat as fired.
                classes.setdefault("ui_theme", []).append(
                    f"{n} (added-lines unavailable — fail-closed)")

    # Secret literals: scan ONLY added lines; skip exempt fixture paths +
    # allowlisted example tokens.
    for p, lines in added.items():
        n = _norm(p)
        if _SECRET_PATH_EXEMPT_RE.search(n):
            continue
        for ln in lines:
            if any(sub in ln for sub in _SECRET_ALLOWLIST_SUBSTR):
                continue
            for label, pat in _SECRET_PATTERNS:
                if pat.search(ln):
                    classes.setdefault("secret", []).append(
                        f"{n}: {label} literal in an added line")
                    break

    # FAILURE_LOG open-class: a touched path is named in an OPEN entry.
    if not failurelog_ok:
        # We could not read the log but there IS a changeset → fail-closed:
        # we cannot prove the change is clear of an open failure, so flag it.
        if paths:
            classes.setdefault("failurelog_open", []).append(
                "FAILURE_LOG unreadable while files changed — fail-closed")
    else:
        for p in paths:
            n = _norm(p).lower()
            base = n.rsplit("/", 1)[-1]
            for tok in failurelog_tokens:
                if n == tok or n.endswith("/" + tok) or base == tok.rsplit("/", 1)[-1]:
                    classes.setdefault("failurelog_open", []).append(
                        f"{n} is named in an OPEN FAILURE_LOG entry ({tok})")
                    break

    return {"classes": classes}


# ── the real ROMA court over the fired classes ──────────────────────────


def _court_leaf_specs(classes: dict[str, list[str]],
                      scope: str) -> list[dict[str, Any]]:
    """One machine-checkable leaf per fired class. The gate's job is to PROVE,
    on the real artifact, that the risky change is actually safe — and for these
    classes the honest answer is that NO local machine probe can prove safety
    (a .cs broker edit's safety = founder sign-off + rebuild+CDP; a main push's
    safety = PR + CI; a secret's safety = it must not exist). So each leaf is a
    'manual' (no auto-machine-gate) leaf → the court returns NEEDS_ROOT → the
    gate BLOCKS and escalates to the founder. This is the correct fail-closed
    shape: a risky class cannot self-clear; only the founder-secret bypass or a
    genuine green (e.g. a future CDP/CI probe wired as gate_kind) clears it."""
    specs: list[dict[str, Any]] = []
    for name, evidence in classes.items():
        specs.append({
            "title": f"[{name}] {scope}: {evidence[0] if evidence else name}",
            "gate_kind": "manual",
            "gate_spec": {},
        })
    return specs


def run_court_over_classes(classes: dict[str, list[str]], *, scope: str) -> dict[str, Any]:
    """Convene the REAL court (isolated store) over the fired classes. Returns
    {ok_to_proceed: bool, detail: str}. ok_to_proceed is True ONLY on a full
    green sweep — which, for manual safety leaves, NEVER happens (they land
    needs_root). FAIL-CLOSED: any import/run error → ok_to_proceed False."""
    if str(_BRAIN_SRC) not in sys.path:
        sys.path.insert(0, str(_BRAIN_SRC))
    try:
        from personal_brain.storage import BrainStore
        from personal_brain import requirement_tree as rt
        from personal_brain.court_harness import convene_court
    except Exception as ex:
        return {"ok_to_proceed": False,
                "detail": f"ROMA court unavailable ({type(ex).__name__}: {ex}) "
                          "— FAIL-CLOSED, cannot verify the risky change."}

    executor = "safety-gate-executor"
    court = "safety-gate-court"  # MUST differ from executor (anti-self-certify)

    tmpdir = Path(tempfile.mkdtemp(prefix="archhub_safety_court_"))
    db_path = tmpdir / "safety_court.db"
    try:
        store = BrainStore.open(str(db_path))
        tree = rt.create_root(store, title=f"safety gate · {scope}", owner_user="safety-gate")
        tid, rid = tree.tree_id, tree.root_id
        specs = _court_leaf_specs(classes, scope)
        if not specs:
            # Defensive: classify said something fired but we built no leaf →
            # fail-closed.
            return {"ok_to_proceed": False,
                    "detail": "internal: fired classes produced no court leaf — fail-closed"}
        rt.decompose(store, tree_id=tid, node_id=rid, children=specs)

        reloaded = rt.get_tree(store, tree_id=tid)
        assert reloaded is not None
        ctx = {"repo_root": str(_REPO), "cwd": str(_REPO)}
        verdicts: list[str] = []
        for leaf in reloaded.leaves():
            rt.claim_leaf(store, tree_id=tid, node_id=leaf.node_id, agent_id=executor)
            cv = convene_court(
                node_id=leaf.node_id, gate_kind=leaf.gate_kind,
                gate_spec=leaf.gate_spec, claimed_by=executor, judged_by=court,
                context=ctx,
            )
            evref = next((l.evidence_ref for l in cv.lenses if l.evidence_ref), None)
            rt.set_verdict(store, tree_id=tid, node_id=leaf.node_id,
                           verdict=cv.verdict, judged_by=court, evidence_ref=evref)
            verdicts.append(cv.verdict)

        final = rt.sweep(store, tree_id=tid)
        ok = bool(final.get("dry"))
        return {
            "ok_to_proceed": ok,
            "detail": (f"court sweep dry={final.get('dry')} "
                       f"needs_root={len(final.get('needs_root') or [])} "
                       f"verdicts={verdicts}"),
            "sweep": final,
        }
    except Exception as ex:
        return {"ok_to_proceed": False,
                "detail": f"court run error ({type(ex).__name__}: {ex}) — FAIL-CLOSED"}
    finally:
        try:
            for suffix in ("", "-wal", "-shm"):
                p = Path(str(db_path) + suffix)
                if p.exists():
                    p.unlink()
            tmpdir.rmdir()
        except Exception:
            pass


# ── founder bypass (un-forgeable) ───────────────────────────────────────


def _founder_authorised() -> bool:
    """The ONLY non-court way past a fired class: the un-forgeable founder
    secret. No agent-settable env honoured here."""
    try:
        if str(Path(__file__).resolve().parent) not in sys.path:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
        import founder_secret
        return founder_secret.is_authorised()
    except Exception:
        return False  # fail-closed: if we can't check, NOT authorised


# ── main ────────────────────────────────────────────────────────────────


def _print(msg: str) -> None:
    sys.stderr.write(f"[safety-court] {msg}\n")


def _branch_targets_main(branch_ref: Optional[str], mode: str) -> bool:
    """True if this commit/push lands on main/master. For commit mode we read
    the current HEAD branch; for push mode we read the pushed ref name."""
    name = (branch_ref or "").strip()
    if mode == "commit" and not name:
        rc, out = _git(["symbolic-ref", "--short", "HEAD"])
        name = out.strip() if rc == 0 else ""
    # normalise refs/heads/main, origin/main, main → leaf name
    leaf = name.replace("refs/heads/", "").replace("refs/remotes/", "")
    leaf = leaf.rsplit("/", 1)[-1] if "/" in leaf else leaf
    return leaf in ("main", "master")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="safety_court_gate")
    ap.add_argument("--mode", choices=["commit", "push"], required=True)
    ap.add_argument("--branch", default=None, help="pushed/target ref name")
    ap.add_argument("--range", dest="rng", default=None, help="<remote>..<local> for push")
    ap.add_argument("--first-push", action="store_true",
                    help="brand-new branch: --range carries just <local_sha>")
    args = ap.parse_args(argv)

    try:
        targets_main = _branch_targets_main(args.branch, args.mode)

        # Resolve the changeset (paths + added lines), fail-closed on git error.
        git_ok = True
        if args.mode == "commit":
            paths, ok1 = _staged_paths()
            added, ok2 = _added_lines("--cached")
            git_ok = ok1 and ok2
        else:
            if not args.rng:
                _print("push mode requires --range — FAIL-CLOSED.")
                # Can't know what's pushed; if it targets main that's already a
                # block, and even otherwise we cannot clear it.
                paths, added, git_ok = [], {}, False
            elif args.first_push:
                # Brand-new branch: scope BOTH paths and added-lines to the
                # commits genuinely new to this push (not against an arbitrary
                # parent of local_sha). _new_branch_commits = rev-list local_sha
                # --not --remotes; an empty set means nothing new → no class →
                # pass. (JURY 2026-06-04, FLAW 2.)
                paths, ok1 = _first_push_paths(args.rng)
                added, ok2 = _first_push_added_lines(args.rng)
                git_ok = ok1 and ok2
            else:
                paths, ok1 = _range_paths(args.rng)
                added, ok2 = _added_lines(args.rng)
                git_ok = ok1 and ok2

        paths = paths or []

        # FAILURE_LOG open tokens (read-by-nothing until now).
        fl_tokens = open_failurelog_tokens()
        failurelog_ok = True
        try:
            (_REPO / "docs" / "FAILURE_LOG.md").read_text(encoding="utf-8", errors="replace")
        except Exception:
            failurelog_ok = False

        result = classify(
            paths=paths, added=added, targets_main=targets_main,
            failurelog_ok=failurelog_ok, failurelog_tokens=fl_tokens,
        )
        classes = result["classes"]

        # If git plumbing failed AND there is any chance of a risky change,
        # fail-closed by synthesising a generic class so the court blocks.
        if not git_ok and not classes:
            classes = {"plumbing": ["git diff failed — cannot prove the change "
                                    "is clear of the risky classes (fail-closed)"]}

        if not classes:
            # No risky class — a normal feature-branch commit/push. PASS untouched.
            _print("no risky safety class in this change — allowing (feature-branch path).")
            return 0

        # A risky class fired. Founder may authorise via the un-forgeable secret.
        scope = f"{args.mode}:{(args.branch or 'HEAD')}"
        fired = ", ".join(sorted(classes.keys()))
        _print(f"RISKY CLASS(ES) FIRED: {fired}")
        for name, evid in classes.items():
            for e in evid[:4]:
                _print(f"  - [{name}] {e}")

        if _founder_authorised():
            _print("FOUNDER-SIGNOFF verified (un-forgeable secret matched) — "
                   "authorising this risky change. (Logged.)")
            return 0

        # No founder signoff → the court must FAIL TO REFUTE on the real
        # artifact. For safety classes with no machine-provable-safe gate this
        # lands needs_root → BLOCK.
        court = run_court_over_classes(classes, scope=scope)
        _print("court verdict: " + court["detail"])
        if court["ok_to_proceed"]:
            _print("court returned a FULL GREEN SWEEP — allowing.")
            return 0

        _print("═══════════════════════════════════════════════════════════════")
        _print("BLOCKED (fail-closed). A risky safety class is not cleared.")
        _print("Recovery:")
        _print("  - main:            push a FEATURE branch + open a PR (no direct main).")
        _print("  - cs:              founder edits/sign-off; set ARCHHUB_FOUNDER_SIGNOFF=<pass>.")
        _print("  - secret:          remove the credential literal from the added lines.")
        _print("  - ui_theme:        theme strand change needs founder design sign-off.")
        _print("  - failurelog_open: close the OPEN docs/FAILURE_LOG.md entry first.")
        _print("  - founder bypass:  ARCHHUB_FOUNDER_SIGNOFF=<passphrase> <git cmd>")
        _print("    (requires the founder's out-of-band digest; the agent cannot forge it)")
        _print("═══════════════════════════════════════════════════════════════")
        return 2

    except Exception as ex:
        # The gate's OWN error must FAIL CLOSED (the opposite of the brain-gate).
        _print(f"internal error ({type(ex).__name__}: {ex}) — FAIL-CLOSED, BLOCKING.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
