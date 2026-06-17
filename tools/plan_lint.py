"""plan_lint.py — the NO-LATER plan-lint gate (AgDR-0054 acceptance #25, BRV-13).

THE GAP THIS CLOSES. `completion_gate.scan_deferral()` is the pure deferral
DETECTOR, but on origin/main **nothing runs it over the plans** — its only
consumers are the composer agent and the ai.plan planner (turn-time), never a
pre-commit/CI scan of `docs/ROADMAP.md` + `docs/agdr/*`. So "no 'later' as a
legal state" (AgDR-0054 §332-335) had a detector and no enforcer: a cowardly
deferral could land in a plan unchallenged. This file is the enforcer.

The rule (AgDR-0054 §335 / acceptance #25, verbatim): a roadmap/AgDR/task item
with **bare deferral language** ("later / phase-2 / follow-up / partial /
for-hardening / nice-to-have / TODO(later) …") and **no** machine-checkable
justified-hold tag is REJECTED. A not-now item is legal ONLY when it carries
`depends-on:<leaf-id>` or `safety-gated:<reason>` on the same line — legitimate
sequencing survives because it states a reason; cowardly deferral cannot exist
on paper.

ONE-SYSTEM. The core detector is `completion_gate.scan_deferral` (the SAME regex
every other surface uses) — this gate does NOT re-mint it. plan_lint adds only
(a) the line-level justified-hold exemption the docstring of `scan_deferral`
itself points to ("a legitimate not-now item must be a STRUCTURED gate … not a
word in a reply" — in a plan, the structured gate is the inline tag), and (b)
the plan-specific `phase-N` deferral marker named in §335 that is meaningless in
a chat reply. Code-fence / frontmatter / explicit-pragma lines are skipped so
the gate lints PLAN ITEMS, not prose that merely quotes the banned words (e.g.
the AgDR section that *defines* the rule).

CLI contract:
    python tools/plan_lint.py docs/ROADMAP.md [docs/agdr/AgDR-XXXX.md ...]
    exit 0  -> clean (no untagged deferral) — the "pass"
    exit 1  -> >=1 untagged deferral; offending file:line:marker printed — "reject"
    exit 2  -> usage / file-not-found error
A pre-commit hook passes the staged plan files; CI passes the same set. Both
reject the commit/merge on exit 1, so the net catches every committer (Claude
Code · Codex · Gemini · composer · humans) — it runs on the repo, not in an
agent that could skip it (AgDR-0054 §337-339).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

# ONE-SYSTEM: reuse the shared deferral detector. tools/ is this file's dir, so a
# sibling import works whether run as `python tools/plan_lint.py` or imported.
_TOOLS = str(Path(__file__).resolve().parent)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import completion_gate as cg  # noqa: E402

# A justified hold (AgDR-0054 §335): `depends-on:<leaf-id>` or
# `safety-gated:<reason>`. Accept hyphen or underscore and a `:` separator; the
# tag must carry a non-empty value (a bare `depends-on:` is not a reason).
_HOLD_TAG = re.compile(
    r"(?i)\b(depends[\s_-]?on|safety[\s_-]?gated)\s*:\s*\S+"
)

# Plan-specific deferral marker named in §335 but NOT in the shared chat-time
# detector: parking work in a future "phase 2 / phase-3 / phase N". (The shared
# `scan_deferral` already owns later/follow-up/partial/for-hardening/nice-to-
# have/TODO/FIXME/defer/punt/"I'll …".)
_PHASE_DEFERRAL = re.compile(r"(?i)\bphase[\s-]?\d+\b")

# Explicit per-line escape valve for legacy debt / meta lines that quote the
# banned words while DEFINING the rule (not deferring work). Honest + auditable:
# a reviewer sees the pragma in the diff; it is not a silent global skip.
_PRAGMA_IGNORE = re.compile(r"(?i)(?:<!--\s*)?plan-lint:\s*(?:ignore|ok|allow)")


@dataclass
class Finding:
    file: str
    line_no: int
    markers: List[str]
    text: str

    def __str__(self) -> str:
        snippet = self.text.strip()
        if len(snippet) > 100:
            snippet = snippet[:97] + "..."
        return (f"{self.file}:{self.line_no}: bare deferral "
                f"{self.markers} (no depends-on:/safety-gated: tag) -> {snippet!r}")


def line_markers(line: str) -> List[str]:
    """Deferral markers on this line via the SHARED detector + the plan-specific
    phase-N marker. Empty list iff the line carries no bare deferral."""
    markers = list(cg.scan_deferral(line))
    if _PHASE_DEFERRAL.search(line):
        markers.append("phase-n")
    return sorted(set(markers))


def line_is_exempt(line: str) -> bool:
    """A deferral line is legal iff it carries a justified-hold tag (or an
    explicit plan-lint pragma). This is the §335 exemption made machine-checkable
    at plan-time — the structured-gate equivalent `scan_deferral`'s own docstring
    demands."""
    return bool(_HOLD_TAG.search(line) or _PRAGMA_IGNORE.search(line))


def lint_text(text: str, *, filename: str = "<text>") -> List[Finding]:
    """Return every untagged-deferral Finding in `text`.

    Skips fenced code blocks (``` … ```), YAML frontmatter (the leading
    `--- … ---` block), and lines bearing an explicit pragma — so the gate lints
    PLAN ITEMS, not prose/metadata that merely mentions the banned vocabulary.
    """
    findings: List[Finding] = []
    in_fence = False
    in_frontmatter = False
    lines = text.splitlines()
    for i, raw in enumerate(lines, start=1):
        stripped = raw.strip()

        # YAML frontmatter: a leading `---` on line 1 opens it; the next `---`
        # closes it. Frontmatter is metadata (status strings), not plan items.
        if i == 1 and stripped == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            continue

        # Fenced code blocks (``` or ~~~) — example/illustrative text.
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        markers = line_markers(raw)
        if markers and not line_is_exempt(raw):
            findings.append(Finding(file=filename, line_no=i,
                                    markers=markers, text=raw))
    return findings


def lint_file(path: Path) -> List[Finding]:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")  # tolerate BOM
    return lint_text(text, filename=str(path))


def lint_paths(paths: Sequence[Path]) -> List[Finding]:
    out: List[Finding] = []
    for p in paths:
        out.extend(lint_file(p))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        sys.stderr.write(
            "usage: python tools/plan_lint.py <plan-file> [<plan-file> ...]\n"
            "  scans docs/ROADMAP.md + docs/agdr/* for bare deferral with no\n"
            "  depends-on:/safety-gated: tag. exit 1 = reject, 0 = pass.\n"
        )
        return 2

    paths: List[Path] = []
    for a in args:
        p = Path(a)
        if not p.is_file():
            sys.stderr.write(f"[plan-lint] not a file: {a}\n")
            return 2
        paths.append(p)

    findings = lint_paths(paths)
    if findings:
        sys.stderr.write(
            f"[plan-lint] REJECT — {len(findings)} untagged deferral(s); "
            f"tag each with depends-on:<leaf-id> or safety-gated:<reason>, "
            f"or do the work now (AgDR-0054 §335 — no 'later' as a legal state):\n"
        )
        for f in findings:
            sys.stderr.write(f"  {f}\n")
        return 1

    names = ", ".join(p.name for p in paths)
    sys.stdout.write(f"[plan-lint] PASS — no untagged deferral in {names}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
