#!/usr/bin/env python3
"""brain_commit_gate — the "no-brain-on-commit" floor (AgDR-0050).

Codifies CLAUDE.md's BRAIN-FIRST clause —

    "PRs from contributors whose work shows no brain interaction (zero
     brain.write ops in trace ...) are reviewed with extra scrutiny —
     they're working without the shared memory + may be reinventing prior
     work."

— into a check that runs at commit time, the ONE layer every vendor (Claude
Code / Cursor / Codex / Antigravity / Gemini / a bare shell) shares.

WHAT IT DOES
------------
Given the staged file list (computed via `git diff --cached --name-only`, or
injected via --staged-file / stdin for testing), it:

  1. Decides whether the commit touches the live product surface — any staged
     path under ``app/`` or ``payload/``. If not → prints "skip", exit 0.
  2. If it does, queries the brain daemon (http://127.0.0.1:8473/mcp,
     overridable via $BRAIN_DAEMON_URL) BEST-EFFORT for a recent brain.write
     fragment whose provenance is plausibly tied to THIS repo / cwd within the
     last N minutes (default 120, via $ARCHHUB_BRAIN_COMMIT_GATE_WINDOW_MIN).
  3. Prints a clear verdict to stderr.

EXIT CONTRACT
-------------
  exit 0  = ok-or-warn  (the DEFAULT for every outcome except a confirmed block)
  exit 1  = block       (ONLY when $ARCHHUB_BRAIN_COMMIT_GATE == "block"
                         AND the brain was reachable AND no qualifying recent
                         fragment was found)

FAIL-OPEN IS ABSOLUTE
---------------------
Brain unreachable / daemon error / timeout / malformed response / a bug in this
script → print a notice, exit 0, in ALL modes. A fresh clone (no daemon, no
brain history) and CI are NEVER blocked by this floor. Default mode is "warn":
the gate only ever exits 1 when explicitly set to block.

DETECTION LIMITATION (honest, by design)
----------------------------------------
A git hook is a short-lived subprocess with NO session transcript and no proven
link between "this commit" and "a brain.write from the session that produced
it." There is therefore no way to PROVE a brain.write happened for this commit.
This gate is a best-effort recency + provenance HEURISTIC against the live
daemon's brain.browse surface (date-granularity recency; text/path match on
fragment text/headline/details/accessed-resources). It can false-positive and
false-negative — which is exactly why it WARNS by default and only blocks behind
an explicit opt-in.

Pure stdlib (urllib / json / subprocess). No third-party deps. The MCP
transport mirrors tools/brainwrap.py (same JSON-RPC tools/call envelope + SSE
`data:` parsing + fail-open) so it degrades identically.

WIRING IS OUT OF SCOPE OF AgDR-0050. This script does not touch .githooks/**.
Wiring it into .githooks/pre-commit is a separate, founder-approved step.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── configuration (all overridable via env, sane defaults) ──────────────────
DAEMON_URL = os.environ.get("BRAIN_DAEMON_URL", "http://127.0.0.1:8473/mcp")
GATE_MODE_ENV = "ARCHHUB_BRAIN_COMMIT_GATE"          # "warn" (default) | "block"
WINDOW_ENV = "ARCHHUB_BRAIN_COMMIT_GATE_WINDOW_MIN"  # int minutes, default 120
DEFAULT_WINDOW_MIN = 120
_TIMEOUT = 6  # seconds — a commit-time probe must be fast; on timeout, fail-open

# The product-surface prefixes that trigger the check (AgDR-0050 Option C1).
SURFACE_PREFIXES = ("app/", "payload/")

# Recency phrases brain.browse stamps on a fragment's `why` field when a
# fragment was touched/learned within the last ~7 days. Used as a coarse
# "recent" signal alongside the date check (the daemon does not expose
# minute-granularity timestamps through browse — see DETECTION LIMITATION).
_RECENT_WHY = ("used recently", "learned recently")


# ═══════════════════════════════════════════════════════════════════════════
#  MCP transport — mirrors tools/brainwrap.call_tool (stdlib, SSE, fail-open)
# ═══════════════════════════════════════════════════════════════════════════
def _parse_sse(raw: bytes) -> dict:
    """Pull the structuredContent / JSON text out of an MCP SSE response."""
    text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                obj = json.loads(line[5:].strip())
            except Exception:
                continue
            res = obj.get("result") or {}
            sc = res.get("structuredContent")
            if isinstance(sc, dict):
                return sc
            for c in res.get("content") or []:
                if c.get("type") == "text":
                    try:
                        return json.loads(c["text"])
                    except Exception:
                        pass
    return {}


def call_tool(name: str, arguments: dict[str, Any],
              *, timeout: Optional[float] = None) -> Optional[dict]:
    """POST a single MCP tools/call. Returns the structured result dict, or
    None on ANY failure (the caller treats None as 'brain unreachable')."""
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }).encode("utf-8")
    req = urllib.request.Request(
        DAEMON_URL, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or _TIMEOUT) as r:
            return _parse_sse(r.read())
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
#  staged-set + repo identity
# ═══════════════════════════════════════════════════════════════════════════
def _norm(p: str) -> str:
    """Normalise a path to forward slashes, no leading ./, lowercased for
    matching robustness across OSes."""
    return p.strip().replace("\\", "/").lstrip("./").lower()


def get_staged_files(explicit: Optional[list[str]] = None) -> list[str]:
    """The staged file list. Prefer an explicit list (tests / callers); else
    `git diff --cached --name-only`. Empty list on any git failure (treated as
    'nothing staged' → skip, never a crash)."""
    if explicit is not None:
        return [p for p in explicit if p.strip()]
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True, text=True, timeout=10,
        )
        return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


def touches_surface(staged: list[str]) -> list[str]:
    """Return the staged paths that fall under a product-surface prefix."""
    hits = []
    for p in staged:
        n = _norm(p)
        if any(n.startswith(pref) for pref in SURFACE_PREFIXES):
            hits.append(p.strip())
    return hits


def repo_identity() -> tuple[str, str]:
    """(repo_root_path_lower, repo_basename_lower) — best-effort, for matching
    fragment provenance against 'this repo'. Falls back to cwd."""
    root = ""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        root = out.stdout.strip()
    except Exception:
        root = ""
    if not root:
        root = os.getcwd()
    base = Path(root).name
    return _norm(root), base.lower()


# ═══════════════════════════════════════════════════════════════════════════
#  brain query + recency/provenance match  (Option A1, best-effort)
# ═══════════════════════════════════════════════════════════════════════════
def _window_minutes() -> int:
    try:
        v = int(os.environ.get(WINDOW_ENV, "") or DEFAULT_WINDOW_MIN)
        return v if v > 0 else DEFAULT_WINDOW_MIN
    except Exception:
        return DEFAULT_WINDOW_MIN


def _today_iso(generated_at: Optional[str]) -> str:
    """The daemon's 'today' (date only), from brain.browse `generated_at`;
    falls back to local UTC date."""
    if generated_at:
        s = str(generated_at)
        # tolerate full ISO timestamps — take the date portion
        if "T" in s:
            return s.split("T", 1)[0]
        if len(s) >= 10:
            return s[:10]
    return datetime.now(timezone.utc).date().isoformat()


def _card_text_blob(card: dict) -> str:
    """All searchable text on a browse card, lowercased, joined."""
    parts: list[str] = []
    for k in ("headline", "why"):
        v = card.get(k)
        if isinstance(v, str):
            parts.append(v)
    det = card.get("details") or {}
    for k in ("text", "subject", "object", "predicate"):
        v = det.get(k)
        if isinstance(v, str):
            parts.append(v)
    # accessed_resources (touched files) is the strongest repo tie when present
    for k in ("accessed_resources", "resources"):
        v = card.get(k) or det.get(k)
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
    return _norm(" ".join(parts))


def _card_is_recent(card: dict, today: str) -> bool:
    """Best-effort recency: dated today, OR `why` says recently used/learned.
    (browse exposes date-granularity only — see DETECTION LIMITATION.)"""
    last = card.get("last_used")
    if isinstance(last, str) and last[:10] == today:
        return True
    why = (card.get("why") or "")
    if isinstance(why, str) and any(p in why.lower() for p in _RECENT_WHY):
        return True
    return False


def _card_ties_to_repo(card: dict, repo_root: str, repo_base: str,
                       staged_norm: list[str]) -> bool:
    """Best-effort provenance tie: the card's text/provenance references this
    repo path, the repo basename, or one of the staged file paths."""
    blob = _card_text_blob(card)
    if not blob:
        return False
    if repo_root and repo_root in blob:
        return True
    if repo_base and repo_base in blob:
        return True
    for sp in staged_norm:
        # match on the path or its basename — fragments often name a file
        if sp and (sp in blob or Path(sp).name.lower() in blob):
            return True
    return False


def query_brain_for_recent_write(staged_surface: list[str]) -> dict[str, Any]:
    """Ask the live daemon (brain.browse) for a recent fragment tied to this
    repo/cwd. Returns a verdict dict:

        {"reachable": bool, "found": bool, "matched": <card|None>,
         "checked": <int cards>, "window_min": <int>}

    Never raises — any failure means reachable=False (→ caller fails open).
    """
    repo_root, repo_base = repo_identity()
    staged_norm = [_norm(p) for p in staged_surface]

    # Query terms: repo basename + the staged surface basenames, so the
    # semantic ranker surfaces fragments most likely tied to this work.
    terms = [repo_base] + [Path(p).name for p in staged_surface[:8]]
    query = " ".join(t for t in terms if t)

    res = call_tool("brain.browse", {"query": query}, timeout=_TIMEOUT)
    if not isinstance(res, dict) or not res.get("ok"):
        return {"reachable": False, "found": False, "matched": None,
                "checked": 0, "window_min": _window_minutes()}

    today = _today_iso(res.get("generated_at"))
    window = _window_minutes()

    # Consider both the semantic search hits and the salient top_of_mind cards.
    cards: list[dict] = []
    for key in ("search", "top_of_mind"):
        v = res.get(key)
        if isinstance(v, list):
            cards.extend(c for c in v if isinstance(c, dict))

    checked = 0
    for card in cards:
        checked += 1
        if not _card_is_recent(card, today):
            continue
        if _card_ties_to_repo(card, repo_root, repo_base, staged_norm):
            return {"reachable": True, "found": True, "matched": card,
                    "checked": checked, "window_min": window}

    return {"reachable": True, "found": False, "matched": None,
            "checked": checked, "window_min": window}


# ═══════════════════════════════════════════════════════════════════════════
#  the gate decision + verdict printing
# ═══════════════════════════════════════════════════════════════════════════
def _mode() -> str:
    m = (os.environ.get(GATE_MODE_ENV) or "warn").strip().lower()
    return m if m in ("warn", "block") else "warn"


def _say(msg: str) -> None:
    print(f"[brain-commit-gate] {msg}", file=sys.stderr)


def decide(staged: list[str]) -> int:
    """Run the gate. Returns the process exit code (0 = ok/warn, 1 = block)."""
    surface = touches_surface(staged)

    # (C) trigger scope — only app/ or payload/ commits are checked.
    if not surface:
        _say("skip — no app/ or payload/ paths staged; brain check not required.")
        return 0

    _say(f"checking {len(surface)} product-surface file(s): "
         f"{', '.join(surface[:6])}{' ...' if len(surface) > 6 else ''}")

    verdict = query_brain_for_recent_write(surface)

    # FAIL-OPEN: brain unreachable → never block, in any mode.
    if not verdict["reachable"]:
        _say("brain daemon unreachable (no response from "
             f"{DAEMON_URL}). FAIL-OPEN — not blocking. "
             "A fresh clone / CI with no brain is expected here.")
        return 0

    if verdict["found"]:
        card = verdict["matched"] or {}
        head = (card.get("headline") or card.get("id") or "?")
        if isinstance(head, str) and len(head) > 80:
            head = head[:77] + "..."
        _say("ok — recent brain interaction tied to this repo found "
             f"(e.g. \"{head}\"). BRAIN-FIRST satisfied (best-effort).")
        return 0

    # Reachable, but no qualifying recent fragment tied to this repo.
    mode = _mode()
    window = verdict["window_min"]
    base_msg = (
        f"no recent brain.write tied to this repo found "
        f"(checked {verdict['checked']} fragment(s), window ~{window} min). "
        "BRAIN-FIRST expects every session to connect to the brain "
        "(brain.health / brain.context / brain.write)."
    )
    if mode == "block":
        _say("BLOCKED — " + base_msg)
        _say("To proceed: connect to the brain this session and retry, "
             f"OR set {GATE_MODE_ENV}=warn for a one-off, "
             "OR (broken-hook emergency only) `git commit --no-verify`.")
        _say("NOTE: this is a best-effort heuristic (a git hook has no session "
             "transcript) — it can miss a real brain.write. That is why warn "
             "is the default mode.")
        return 1

    _say("WARNING — " + base_msg)
    _say(f"Proceeding (warn mode). Set {GATE_MODE_ENV}=block to make this a "
         "hard gate. Best-effort signal — may be a false negative.")
    return 0


# ═══════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════
def _read_stdin_paths() -> Optional[list[str]]:
    """When --stdin is given, read newline-separated staged paths from stdin."""
    try:
        data = sys.stdin.read()
    except Exception:
        return None
    if not data.strip():
        return []
    return [ln.strip() for ln in data.splitlines() if ln.strip()]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="brain_commit_gate",
        description="No-brain-on-commit floor (AgDR-0050). Warns by default; "
                    "blocks only when ARCHHUB_BRAIN_COMMIT_GATE=block. "
                    "Always fails open when the brain daemon is down.",
    )
    parser.add_argument(
        "--staged-file", action="append", default=None, metavar="PATH",
        help="Explicit staged path (repeatable). Overrides `git diff "
             "--cached`. Primarily for testing.",
    )
    parser.add_argument(
        "--stdin", action="store_true",
        help="Read newline-separated staged paths from stdin instead of git.",
    )
    args = parser.parse_args(argv)

    explicit: Optional[list[str]] = None
    if args.stdin:
        explicit = _read_stdin_paths()
    elif args.staged_file is not None:
        explicit = args.staged_file

    try:
        staged = get_staged_files(explicit)
        return decide(staged)
    except Exception as ex:
        # The gate's own bug must NEVER block a commit. Fail open, loudly.
        _say(f"internal error ({type(ex).__name__}: {ex}). FAIL-OPEN — "
             "not blocking.")
        return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
