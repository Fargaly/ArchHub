"""STR-07 — the source-of-truth working dir must have a real ignore policy.

The repo root doubles as the founder's working directory: the place every
loose artefact lands (agent/session transcripts, ad-hoc screenshots, founder
message dumps, zipped exports). Before this fix the top-level ``.gitignore``
existed but had no entry for several of those, so scratch like
``founder_msgs.txt``, ``_capture.png`` and ``bundle.zip`` was *trackable* and
silently crept into commits.

This test pins two things, both against the REAL ``.gitignore`` at the repo
root (resolved from this file's location, so it works in any worktree):

  1. The file exists and literally contains every required token. This mirrors
     the STR-07 gate predicate verbatim
     (``containing at least *.log, __pycache__/, .pytest_cache/,
     *.archhub-session.json, _*.png, founder_msgs.txt, *.zip, node_modules/``).
  2. ``git check-ignore`` actually ignores representative scratch files dropped
     AT the repo root — the behavioural proof that the patterns bite, not just
     that the strings are present. A real source file (``app/main.py`` path)
     must stay trackable so the policy isn't over-broad.

RED on origin/main: tokens ``*.archhub-session.json`` (bare), ``_*.png``,
``founder_msgs.txt`` and ``*.zip`` are absent → both the token assertion and
the ``git check-ignore`` behavioural assertion fail.
GREEN after the fix: the STR-07 ``.gitignore`` block adds them.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

# tests/ lives at the repo root, so parent-of-parent is the source-of-truth
# working dir whose ignore policy STR-07 governs.
REPO_ROOT = Path(__file__).resolve().parent.parent
GITIGNORE = REPO_ROOT / ".gitignore"

# Verbatim from the STR-07 gate: "containing at least ...".
REQUIRED_TOKENS = [
    "*.log",
    "__pycache__/",
    ".pytest_cache/",
    "*.archhub-session.json",
    "_*.png",
    "founder_msgs.txt",
    "*.zip",
    "node_modules/",
]

# Representative scratch files that MUST be ignored once the policy is real.
# Each maps to the token that should catch it.
SCRATCH_SAMPLES = [
    "founder_msgs.txt",
    "_capture.png",
    "export-bundle.zip",
    "run.archhub-session.json",
    "debug.log",
]


def _gitignore_lines() -> list[str]:
    text = GITIGNORE.read_text(encoding="utf-8", errors="replace")
    # A pattern line is one that is not blank and not a full-line comment.
    # (git only treats '#' as a comment at the START of a line.)
    return [
        ln.rstrip("\n")
        for ln in text.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]


def test_gitignore_exists_at_source_of_truth_root():
    assert GITIGNORE.is_file(), f"no .gitignore at source-of-truth root {REPO_ROOT}"


@pytest.mark.parametrize("token", REQUIRED_TOKENS)
def test_required_token_is_a_real_pattern_line(token: str):
    """Each required token appears as its OWN bare pattern line.

    Asserting against parsed pattern lines (not a substring of the whole file)
    guards against the trailing-inline-comment trap: git does not strip a
    ``*.zip  # note`` comment, so the pattern would be ``*.zip  # note`` and
    never match ``*.zip``. Requiring an exact line keeps every pattern live.
    """
    lines = _gitignore_lines()
    assert token in lines, (
        f"required ignore token {token!r} is not a bare pattern line in "
        f".gitignore (present lines containing it: "
        f"{[l for l in lines if token.strip('*/') in l]})"
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
@pytest.mark.parametrize("sample", SCRATCH_SAMPLES)
def test_scratch_file_is_actually_ignored(sample: str):
    """Behavioural proof: git resolves the pattern to an ignore for a file
    dropped at the repo root. This is what actually stops the junk being
    tracked — the string being present is necessary but not sufficient."""
    proc = subprocess.run(
        ["git", "check-ignore", sample],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    # exit 0 => the path IS ignored; exit 1 => NOT ignored.
    assert proc.returncode == 0, (
        f"{sample!r} is NOT ignored by .gitignore — scratch would get tracked "
        f"(git check-ignore rc={proc.returncode}, out={proc.stdout!r})"
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_real_source_stays_trackable():
    """The ignore policy must not be so broad it swallows real source. A normal
    Python file under app/ stays trackable (check-ignore exits non-zero)."""
    proc = subprocess.run(
        ["git", "check-ignore", "app/main.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0, (
        "app/main.py is being ignored — the .gitignore policy is over-broad "
        f"(git check-ignore matched: {proc.stdout!r})"
    )
