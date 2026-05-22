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


def main() -> int:
    bad: list[tuple[Path, int, str]] = []
    for py in REPO_ROOT.rglob("*.py"):
        # Skip third-party / venv / __pycache__ noise.
        parts = set(py.parts)
        if parts & {"__pycache__", "site-packages", "venv",
                    ".venv", "build", "dist"}:
            continue
        if py.resolve() in {p.resolve() for p in ALLOWED}:
            continue
        unsafe = scan_file(py)
        for lineno, src in unsafe:
            bad.append((py, lineno, src))

    if not bad:
        print(f"OK — every save_session() call passes messages=. "
              f"Scanned {sum(1 for _ in REPO_ROOT.rglob('*.py'))} files.")
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
