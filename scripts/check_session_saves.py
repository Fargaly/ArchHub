"""Pre-commit / CI guardrail — find unsafe save_session() calls.

The "sessions are empty after restart" bug class was caused by
chat_window calling `save_session(self.session, name)` without
messages=self.history. The chat conversation lives in history, not
in Session, so the saved payload was always empty.

This script walks every Python file in the repo and fails when it
finds:

  • A `save_session(...)` call that DOESN'T include `messages=` as a
    keyword argument.
  • A `save_session(...)` call positional-argument count that suggests
    an old-style invocation pattern.

Whitelisted call sites:
  • app/session_io.py — the definition itself + internal helpers
  • Tests that explicitly verify the EmptySessionError path

Returns non-zero exit code on any unsafe call so a pre-commit hook
can refuse the commit. Wire in:

    .git/hooks/pre-commit:
        python scripts/check_session_saves.py || exit 1

or as a GitHub Action step:

    - run: python scripts/check_session_saves.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
# Files that are allowed to omit messages= because they DEFINE the
# function, test the rejection path, or use Session-only saves
# legitimately (Skills runner — parametric workflow output, no chat
# history).
ALLOWED = {
    REPO_ROOT / "app" / "session_io.py",
    REPO_ROOT / "tests" / "test_session_cleanup.py",
    REPO_ROOT / "tests" / "test_session_history.py",
    REPO_ROOT / "tests" / "test_session_save_contract.py",
    REPO_ROOT / "scripts" / "check_session_saves.py",
}

# Directory names that are not part of THIS working tree's source and
# must be skipped wholesale during the walk.
#   • Build / dependency noise (venv, __pycache__, …).
#   • Nested git worktrees: .claude/ holds agent worktrees parked on
#     OTHER, often older commits; .git is git's own store.
_SKIP_DIR_NAMES = {
    "__pycache__", "site-packages", "venv", ".venv",
    "build", "dist", ".claude", ".git",
}
# Sibling-worktree directory PREFIXES. The dispatcher parks parallel-lane
# worktrees next to the repo (and, when the guard runs from a worktree,
# inside a shared parent) under names like `_cx`, `_codex`, `_ag`,
# `_rel*`, `_fix*`, `_con*`, `_cc*`, `_fin*`. Those are different
# revisions of this repo — scanning their (often pre-fix) test files made
# the guardrail + its meta-test false-fail (2026-06-18). A worktree dir
# name always begins with one of these, so a prefix match catches every
# numbered variant (`_fix1`, `_cx_sessions`, …) without listing each.
_WORKTREE_PREFIXES = (
    "_cx", "_codex", "_ag", "_rel", "_fix", "_con", "_cc", "_fin",
)


def _is_skipped_part(name: str) -> bool:
    """True if a single path component marks a tree we must not scan —
    build noise, a nested checkout, or a sibling-lane worktree."""
    if name in _SKIP_DIR_NAMES:
        return True
    return any(name.startswith(p) for p in _WORKTREE_PREFIXES)


class SaveSessionVisitor(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.unsafe: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        callee = node.func
        name = ""
        if isinstance(callee, ast.Name):
            name = callee.id
        elif isinstance(callee, ast.Attribute):
            name = callee.attr
        if name == "save_session":
            kw_names = {kw.arg for kw in node.keywords if kw.arg}
            if "messages" not in kw_names:
                # Save the line for the report.
                src = ast.unparse(node)
                self.unsafe.append((node.lineno, src[:120]))
        self.generic_visit(node)


def scan_file(path: Path) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"),
                          filename=str(path))
    except SyntaxError:
        return []
    v = SaveSessionVisitor(path)
    v.visit(tree)
    return v.unsafe


def _walk_repo_py() -> list[Path]:
    """Every *.py in THIS working tree, with build noise, nested
    checkouts, and sibling-lane worktrees pruned out (see
    _is_skipped_part). The single source of the file set so the scan and
    the 'scanned N files' count can never drift.

    Only path components BELOW REPO_ROOT are tested — REPO_ROOT's own
    ancestors (which may themselves sit under a `_fin/…` worktree-staging
    parent) must never trip the prefix match, or the guard would skip its
    entire own tree."""
    out: list[Path] = []
    for py in REPO_ROOT.rglob("*.py"):
        try:
            rel_parts = py.relative_to(REPO_ROOT).parts
        except ValueError:
            rel_parts = py.parts
        if any(_is_skipped_part(part) for part in rel_parts):
            continue
        out.append(py)
    return out


def main() -> int:
    bad: list[tuple[Path, int, str]] = []
    scanned = _walk_repo_py()
    allowed_resolved = {p.resolve() for p in ALLOWED}
    for py in scanned:
        if py.resolve() in allowed_resolved:
            continue
        unsafe = scan_file(py)
        for lineno, src in unsafe:
            bad.append((py, lineno, src))

    if not bad:
        print(f"OK — every save_session() call passes messages=. "
              f"Scanned {len(scanned)} files.")
        return 0

    print("UNSAFE save_session() calls found:\n")
    for path, lineno, src in bad:
        rel = path.relative_to(REPO_ROOT)
        print(f"  {rel}:{lineno}: {src}")
    print()
    print(
        "Every save_session() must include messages=self.history (or\n"
        "an equivalent message list) — otherwise the file written is\n"
        "an empty stub that re-loads as a blank chat. This is the bug\n"
        "class that destroyed pre-v1.0 saved sessions.\n"
        "\n"
        "If you legitimately need to save a parameter-only Session\n"
        "(e.g. a Skills runner output with no chat content), add the\n"
        "file path to ALLOWED in scripts/check_session_saves.py and\n"
        "leave a comment explaining why."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
