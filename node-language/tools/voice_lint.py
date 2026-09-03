#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""voice_lint.py — the voice/microcopy lint, drawn straight from the design
language sheet (studio-language.jsx §11 "Voice & microcopy").

WHAT IT ENFORCES (the spec, verbatim from §11)
----------------------------------------------
ArchHub speaks like a senior architect, not an excited intern. §11 codifies six
voice rules and six DO/DON'T pairs. Three of those rules are mechanically
checkable on a string, so this lint catches them on every user-facing string in
the repo:

  1. NO PICTOGRAPHIC EMOJI        — §11 rule 04 "No emoji". DON'T pair:
                                     "Successfully completed your task! 🎉"
  2. NO EXCLAMATION POINTS in UI  — §11 rule 04 "No exclamation points".
                                     DON'T pairs: "Oops! …", "…went wrong."
  3. NO HYPE / FORBIDDEN WORDS    — §11 rules 01-03 ("calm", "concrete", "owns
                                     the craft") + the DON'T pairs:
                                       successfully  (rule 01 — no celebration)
                                       amazing       ("Generating amazing …")
                                       oops          ("Oops! Something …")
                                       seamless      (hype)
                                       powerful      (hype)
                                       generate      ("Generating … content")
                                       produce       (rule 03 — drawings, not
                                                      "outputs"/"produce")
                                       effortless    (hype)
                                       revolutionary (hype)

THE ONE HARD DISTINCTION — emoji vs. iconography
------------------------------------------------
§11 bans pictographic EMOJI. §08 ("Iconography") makes a drafted glyph set part
of the language: ⌬ ◇ ⌗ ⌭ ✎ ▤ ¶ ⇄ ↗ ⚡ ◐ ☰ ⌕ ↻ ⌫ ⌘ ⇧ ↵ ● ★ ✦ and the
typographic marks · — … that pervade mono labels. Several of those BMP glyphs
(e.g. ⚡ U+26A1, ✎ U+270E) sit one codepoint away from real emoji
(✅ U+2705, ✨ U+2728). A blanket BMP range would false-flag the design system.

So emoji detection is precise, not a range sweep:
  * every char in the supplementary pictographic planes (U+1F000–U+1FAFF,
    plus the legacy Misc-Symbols/Dingbat emoji that default to emoji
    presentation) is flagged;
  * a curated BMP pictograph set (✅ ❌ ✨ ⭐ ✔ ☑ ✖ …) is flagged;
  * any char followed by the emoji-presentation selector U+FE0F is flagged;
  * the §08 ICON_ALLOW glyph set is NEVER flagged — iconography is the language,
    so a design glyph wins even if it overlaps an emoji default.

Plus a project ALLOWLIST file (tools/voice_lint_allow.txt) for the legit
exceptions every real codebase needs (a string that must say "generate" because
it names an external API verb, a deliberate "!" in a regex example, etc.).

SCOPE — what counts as "user-facing"
------------------------------------
  * JSX  (.jsx/.tsx/.js under app/web_ui): the text a user reads — JSX element
    text nodes, and the human-copy attributes label / role / title / placeholder
    / aria-label / alt / tooltip / subtitle / sub / heading. Identifiers,
    imports, css values, prop *keys*, and data plumbing are NOT scanned.
  * PY   (user-message strings): string literals that are clearly shown to a
    user — args to a small set of user-message sinks (show_message, set_status,
    QMessageBox.*, toast, notify, st.error/info/warning/success, logger at
    user-facing level when the string reads as copy). Code comments,
    docstrings, identifiers, log keys, and dict keys are NOT scanned.

This deliberately under-reaches rather than over-reaches: a voice lint that
screams on every `def generate_node()` is noise and gets disabled. It flags
COPY, with an allowlist for the rest.

CLI CONTRACT
------------
    python tools/voice_lint.py [PATH ...]      # default: app/web_ui (jsx)
    python tools/voice_lint.py --all           # jsx + the py user-message sinks
    python tools/voice_lint.py --json          # machine-readable findings
    python tools/voice_lint.py --advisory      # always exit 0 (report only)
    python tools/voice_lint.py --strict        # exit 1 on any finding (gate)

Exit codes:
    0   clean, OR --advisory (report printed, never blocks)
    1   >=1 finding and --strict
    2   usage / path error

The repo wires this ADVISORY-FIRST in CI (.github/workflows/voice-lint.yml):
it reports findings as a job summary but does NOT fail the build yet, so the
voice bar becomes visible without breaking anyone mid-flight. Flip to --strict
when the copy is clean.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set, Tuple

# Make stdout UTF-8 even on a cp1252 Windows console — the lint prints glyphs.
try:  # pragma: no cover - environment dependent
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

# ───────────────────────────────────────────────────────────────────────────
# THE RULES (from studio-language.jsx §11)
# ───────────────────────────────────────────────────────────────────────────

#: §11 DON'T pairs + voice rules 01-03. Matched case-insensitively as whole
#: words. "generate"/"generating", "produce"/"produces"/"producing" etc. are all
#: caught via a word-stem boundary match (see _WORD_RE).
BANNED_WORDS: Tuple[str, ...] = (
    "successfully",
    "amazing",
    "oops",
    "seamless",
    "powerful",
    "generate",
    "produce",
    "effortless",
    "revolutionary",
)

# Whole-word (stem) matcher: "generate" also catches generates/generating/
# generated; "produce" catches produces/producing/produced; "amazing" is matched
# as-is. We anchor on a word boundary at the start and allow common inflections
# at the end so "regenerate"/"reproduce" inside an identifier do NOT match (the
# leading boundary requires the stem to begin the word).
_WORD_RE = {
    w: re.compile(r"(?<![A-Za-z])" + re.escape(w) + r"(?:s|d|r|rs|ng)?(?![A-Za-z])", re.IGNORECASE)
    for w in BANNED_WORDS
}
# "generate" -> generate/generates/generated/generating handled specially below
_STEM_RE = {
    "generate": re.compile(r"(?<![A-Za-z])generat(?:e|es|ed|ing|or|ors)(?![A-Za-z])", re.IGNORECASE),
    "produce": re.compile(r"(?<![A-Za-z])produc(?:e|es|ed|ing|tion)(?![A-Za-z])", re.IGNORECASE),
}

#: §08 ICONOGRAPHY — the drafted glyph set is part of the language and must
#: NEVER be flagged as emoji. Pulled from §08's 16-icon set + the palette /
#: command-palette glyphs + the typographic marks used in mono labels.
ICON_ALLOW: Set[str] = set(
    "·—…‹›«»‘’“”–"          # typographic marks (mono labels, body copy)
    "←↑→↓↔↕↗↖↘↙↵↩↪⇄⇅⇆⇧⇪↻↺"  # arrows (nav, keys, heal ↻)
    "●○◐◑◒◓◔◕■□▢▣▤▥▦▧▨▩▪▫"  # geometric (status dots, fills)
    "◆◇◈◊⬡⬢⬠"               # diamonds / hex (node glyphs)
    "★☆✦✧✶✷✸✹❉❋"            # stars (skill glyph in §08 is a 5-point star path)
    "⌘⌥⌦⌫⇥⎋⏎⌃⇪"            # mac key glyphs (keyboard map §10)
    "⌬⌭⌗⌕⌯⌖⌰⍿"             # misc-technical drafting glyphs (§08 node icons)
    "✎✏✐✑✒"                # pencils (annotate icon §08)
    "¶§†‡※‖"                # editorial marks (text node §08)
    "☰☱☲☳☴☵☶☷"              # trigram bars (menu / palette §13)
)
# A couple of glyphs that ARE in the §08/§13 design but default to emoji
# presentation. They are language, not decoration — allowlist them explicitly so
# the precise emoji detector below does not flag them.
ICON_ALLOW |= set("⚡◦‣⁃")  # ⚡ U+26A1 used as the "restart connector" glyph (§13)

#: BMP pictographs that are unambiguously decorative emoji (NOT in §08). Flagged
#: when they appear in copy. Curated so it never overlaps ICON_ALLOW.
BMP_EMOJI: Set[str] = set(
    "✅❌✔✖☑☒✗✘"      # checkmarks / crosses (emoji-presentation)
    "✨⭐🌟"            # sparkle / glowing star (≠ §08 ★ outline star)
    "❤♥💔❣"            # hearts
    "☀☁☂☃☄"            # weather emoji
    "☎☏✆"              # telephones
    "✊✋✌👌👍👎👊"      # hands (BMP + early SMP)
    "♻♿⚠⛔⛅⛄⛎"         # warning / signs (⚠ default-emoji)
    "☺☹😀"             # faces
    "♨⚓⚔⚕⚖⚗⚘⚰⚱"      # misc emoji-default symbols
)
# Remove any accidental overlap with the icon allowlist — iconography wins.
BMP_EMOJI -= ICON_ALLOW

_VS16 = "️"   # emoji-presentation selector
_ZWJ = "‍"    # zero-width joiner (emoji sequences)


def _is_emoji_char(ch: str) -> bool:
    """True iff *ch* is a pictographic emoji we should flag.

    Precise, not a blanket range: supplementary pictographic planes + a curated
    BMP set + the regional-indicator letters. The §08 ICON_ALLOW glyphs are
    excluded first, so iconography is never mistaken for emoji.
    """
    if ch in ICON_ALLOW:
        return False
    cp = ord(ch)
    # Supplementary pictographic planes: emoji, symbols & pictographs,
    # transport, supplemental symbols, symbols-and-pictographs-extended-A.
    if 0x1F000 <= cp <= 0x1FAFF:
        return True
    # Regional indicator symbols (flag sequences) U+1F1E6–U+1F1FF.
    if 0x1F1E6 <= cp <= 0x1F1FF:
        return True
    # Curated BMP decorative emoji.
    if ch in BMP_EMOJI:
        return True
    # Skin-tone modifiers / keycap combining are part of a sequence; flag them
    # so a sequence is reported once at its base.
    if cp in (0x20E3,):  # combining enclosing keycap
        return True
    return False


def _find_emoji(text: str) -> List[Tuple[int, str]]:
    """Return (col, glyph) for each emoji run. A VS16/ZWJ-joined sequence after
    a flagged base is folded into one finding (reported at the base)."""
    out: List[Tuple[int, str]] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        # A base char carrying VS16 is emoji even if its base is BMP-default-text
        # (e.g. "❄️"). Check the pair.
        nxt = text[i + 1] if i + 1 < n else ""
        if _is_emoji_char(ch) or (nxt == _VS16 and ch not in ICON_ALLOW and not ch.isspace() and not ch.isalnum()):
            start = i
            run = ch
            i += 1
            # absorb VS16 / ZWJ / modifiers / following emoji in the sequence
            while i < n and (text[i] in (_VS16, _ZWJ) or _is_emoji_char(text[i]) or 0x1F3FB <= ord(text[i]) <= 0x1F3FF):
                run += text[i]
                i += 1
            out.append((start, run))
        else:
            i += 1
    return out


@dataclass
class Finding:
    path: str
    line: int
    col: int
    kind: str          # "emoji" | "exclamation" | "banned-word"
    detail: str        # the offending glyph / word
    snippet: str       # the user-facing string it came from (trimmed)

    def fmt(self) -> str:
        return f"{self.path}:{self.line}:{self.col}: {self.kind}: {self.detail}  |  {self.snippet}"


# ───────────────────────────────────────────────────────────────────────────
# STRING EXTRACTION
# ───────────────────────────────────────────────────────────────────────────

#: JSX attributes that hold human-readable copy (vs. data/ids/handlers).
JSX_COPY_ATTRS = (
    "label", "role", "title", "placeholder", "aria-label", "ariaLabel",
    "alt", "tooltip", "subtitle", "sub", "heading", "header", "caption",
    "description", "hint", "message", "msg", "text", "summary", "name",
)

# attr="..."  or  attr='...'  or  attr={'...'} / {"..."}
_JSX_ATTR_RE = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in JSX_COPY_ATTRS) + r")\s*=\s*"
    r"(?:"
    r"\"([^\"]*)\""          # attr="..."
    r"|'([^']*)'"            # attr='...'
    r"|\{\s*['\"]([^'\"]*)['\"]\s*\}"   # attr={'...'} / {"..."}
    r")"
)

# JSX element text:  >  some text  <   (between tags, no braces/other-tags
# inside). Newlines ARE allowed in the capture because JSX is conventionally
# formatted as `<div>\n  text\n</div>`. The capture is then split per line and
# each line must independently pass `_looks_like_copy` (single-line + no JS/CSS
# tokens) — so genuine multi-line-formatted copy survives while a block that
# merely happens to span `>` … `<` across JavaScript (`d2 > x; if (a) y <`) is
# rejected line-by-line as non-copy.
_JSX_TEXT_RE = re.compile(r">([^<>{}]*[A-Za-z][^<>{}]*)<")

# A bare quoted string in an array of copy (e.g. the §11 rule lists). We only
# scan single/double-quoted string literals that READ like a sentence: contain a
# space and start with a letter — this keeps ids / classNames / paths out.
_JSX_LITERAL_RE = re.compile(r"(?<![A-Za-z0-9_])'([^'\n]{3,})'|(?<![A-Za-z0-9_])\"([^\"\n]{3,})\"")

# Python user-message sinks: the call name immediately preceding a string arg.
_PY_SINK_RE = re.compile(
    r"\b("
    r"show_message|showMessage|set_status|setStatus|set_state|status_message|"
    r"toast|notify|notification|alert|popup|"
    r"QMessageBox\.\w+|QMessageBox|"
    r"st\.error|st\.info|st\.warning|st\.success|st\.write|st\.markdown|st\.toast|"
    r"setText|set_text|setPlaceholderText|setToolTip|setWindowTitle|"
    r"flash|emit_user|user_error|user_message"
    r")\s*\(",
)
# A Python string literal (single/double, incl. f-strings), non-greedy, no
# embedded newline. We scan only the literal that follows a sink on the same or
# next physical line.
_PY_STR_RE = re.compile(r"[frbu]{0,2}(?:\"([^\"\\\n]*(?:\\.[^\"\\\n]*)*)\"|'([^'\\\n]*(?:\\.[^'\\\n]*)*)')")


# Tokens that betray JS/CSS source rather than human copy. A `.jsx` file is
# mostly JavaScript, so the `>...<` text regex and bare-literal regex can capture
# code fragments (`if (!best || d2 > x)`, `animation-duration:0.001ms!important`).
# Anything carrying one of these is NOT copy — reject it so the lint stays signal.
_CODE_TOKENS = (
    ";", "=>", "||", "&&", "===", "!==", "!=", "==", "++", "--",
    "){", "})", "/>", "</", "*::", "!important", "React.", "return ",
    "const ", "let ", "var ", "function", ".map(", ".filter(", ".includes(",
    ".push(", ".slice(", ".length", "=>", "?.", "??", "()", "{}",
)
_CODE_TOKEN_RE = re.compile("|".join(re.escape(t) for t in dict.fromkeys(_CODE_TOKENS)))


def _looks_like_copy(s: str) -> bool:
    """Heuristic: a human sentence/phrase, not an id/path/css/format/JS token."""
    s = s.strip()
    if len(s) < 3:
        return False
    if "\n" in s:                                    # copy is single-line
        return False
    if not re.search(r"[A-Za-z]", s):
        return False
    if _CODE_TOKEN_RE.search(s):                     # JS / CSS fragment, not copy
        return False
    # reject obvious non-copy: paths, css, urls, identifiers, format specifiers
    if re.fullmatch(r"[A-Za-z0-9_.\-/]+", s):       # foo.bar / a-b / path/seg
        return False
    if re.fullmatch(r"[#.]?[A-Za-z0-9_\- ]+", s) and "  " not in s and " " not in s:
        return False
    if s.startswith(("http://", "https://", "/", "./", "../", "data:", "rgba(", "rgb(", "#")):
        return False
    if re.fullmatch(r"[0-9A-Fa-f]{3,8}", s):        # hex color body
        return False
    return True


def extract_jsx_strings(text: str) -> List[Tuple[int, int, str]]:
    """Return (line, col, string) tuples of user-facing copy in JSX source."""
    out: List[Tuple[int, int, str]] = []

    def line_col(pos: int) -> Tuple[int, int]:
        line = text.count("\n", 0, pos) + 1
        col = pos - (text.rfind("\n", 0, pos))
        return line, col

    for m in _JSX_ATTR_RE.finditer(text):
        val = next(g for g in m.groups()[1:] if g is not None)
        if val.strip():
            ln, co = line_col(m.start(2) if m.group(2) is not None else m.start())
            out.append((ln, co, val))

    for m in _JSX_TEXT_RE.finditer(text):
        block = m.group(1)
        # Split the captured block into physical lines; keep only the lines that
        # read as copy (single-line + no JS/CSS tokens). This lets conventionally
        # formatted `<div>\n  Copy here\n</div>` through while rejecting blocks
        # that span JavaScript across `>` … `<`.
        base = m.start(1)
        offset = 0
        for piece in block.split("\n"):
            stripped = piece.strip()
            if stripped and _looks_like_copy(stripped):
                # column of the stripped text within the source
                lead = len(piece) - len(piece.lstrip())
                ln, co = line_col(base + offset + lead)
                out.append((ln, co, stripped))
            offset += len(piece) + 1  # +1 for the consumed "\n"

    for m in _JSX_LITERAL_RE.finditer(text):
        val = m.group(1) if m.group(1) is not None else m.group(2)
        if val and _looks_like_copy(val):
            ln, co = line_col(m.start())
            out.append((ln, co, val))

    return out


def extract_py_strings(text: str) -> List[Tuple[int, int, str]]:
    """Return (line, col, string) of strings passed to user-message sinks."""
    out: List[Tuple[int, int, str]] = []
    for sm in _PY_SINK_RE.finditer(text):
        # Look at the slice right after the '(' for the first string literal.
        tail = text[sm.end(): sm.end() + 600]
        m = _PY_STR_RE.search(tail)
        if not m:
            continue
        # Must be the FIRST argument-ish token (no other '(' call before it that
        # would mean the string belongs to a nested call). Cheap guard: reject if
        # a ';' or newline-with-dedent appears before the string.
        pre = tail[: m.start()]
        if pre.count("(") > pre.count(")"):
            # string is inside a nested call's args, still user-facing-ish; keep.
            pass
        val = m.group(1) if m.group(1) is not None else m.group(2)
        if val is None:
            continue
        try:
            decoded = bytes(val, "utf-8").decode("unicode_escape")
        except Exception:
            decoded = val
        if not decoded.strip():
            continue
        pos = sm.end() + m.start()
        line = text.count("\n", 0, pos) + 1
        col = pos - (text.rfind("\n", 0, pos))
        out.append((line, col, decoded))
    return out


# ───────────────────────────────────────────────────────────────────────────
# THE CHECKS
# ───────────────────────────────────────────────────────────────────────────

def _allowlist_hit(allow: Set[str], snippet: str, detail: str) -> bool:
    """A finding is suppressed if its exact snippet OR a line of the form
    'detail|snippet-substring' is in the allowlist. Two allowlist grammars:
      * a whole copy string, verbatim  -> suppresses ALL findings in it
      * 'kind:detail'  (e.g. 'banned-word:generate') -> suppresses that detail
        everywhere (use sparingly)
    """
    s = snippet.strip()
    if s in allow:
        return True
    if detail and (detail in allow):
        return True
    return False


def lint_string(snippet: str) -> List[Tuple[str, str, int]]:
    """Run the three checks on one user-facing string.

    Returns list of (kind, detail, col_offset_within_snippet).
    """
    findings: List[Tuple[str, str, int]] = []

    # 1) emoji
    for off, glyph in _find_emoji(snippet):
        findings.append(("emoji", glyph, off))

    # 2) exclamation points in UI copy.
    # Only sentence-punctuation "!" counts — not the JS negation operator
    # (`!foo`, `!(`, `!important`) or comparison (`!=`, `!==`). A copy bang
    # terminates a word/clause: the char before it is a letter / digit / closing
    # quote-or-paren / sentence punctuation, and the char after it is NOT '='.
    for m in re.finditer(r"!", snippet):
        i = m.start()
        if snippet[i:i + 10].lower() == "!important":   # CSS, not copy
            continue
        after = snippet[i + 1] if i + 1 < len(snippet) else ""
        if after == "=":                       # != / !==  (comparison)
            continue
        before = snippet[i - 1] if i > 0 else ""
        # JS unary negation: `!` with no word before it, negating an identifier
        # or sub-expression (`!s`, `!(a)`, `!long`). Not copy.
        if before in ("", " ", "(", "[", "{", "!", "&", "|", "=", ",", ";", "<", ">", ":", "?"):
            continue
        # copy bang: preceded by something word-like
        if before.isalnum() or before in ('"', "'", ")", ".", "…", "%", "”", "’"):
            findings.append(("exclamation", "!", i))

    # 3) banned / hype words
    seen_spans: List[Tuple[int, int]] = []
    for w, rx in {**_WORD_RE, **_STEM_RE}.items():
        for m in rx.finditer(snippet):
            span = (m.start(), m.end())
            if span in seen_spans:
                continue
            seen_spans.append(span)
            findings.append(("banned-word", m.group(0).lower(), m.start()))

    return findings


def lint_file(path: Path, allow: Set[str]) -> List[Finding]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    suffix = path.suffix.lower()
    if suffix in (".jsx", ".tsx", ".js"):
        strings = extract_jsx_strings(text)
    elif suffix == ".py":
        strings = extract_py_strings(text)
    else:
        return []

    findings: List[Finding] = []
    for line, col, snippet in strings:
        for kind, detail, off in lint_string(snippet):
            if _allowlist_hit(allow, snippet, f"{kind}:{detail}"):
                continue
            if _allowlist_hit(allow, snippet, detail):
                continue
            trimmed = snippet.strip()
            if len(trimmed) > 90:
                trimmed = trimmed[:87] + "…"
            findings.append(Finding(
                path=str(path),
                line=line,
                col=col + off,
                kind=kind,
                detail=detail,
                snippet=trimmed,
            ))
    return findings


# ───────────────────────────────────────────────────────────────────────────
# ALLOWLIST + FILE DISCOVERY
# ───────────────────────────────────────────────────────────────────────────

DEFAULT_ALLOW_FILE = Path(__file__).resolve().parent / "voice_lint_allow.txt"


def load_allowlist(path: Optional[Path] = None) -> Set[str]:
    """Load the allowlist. Blank lines and lines starting with '#' are ignored.
    Each remaining line is either a verbatim copy string (suppresses all
    findings in it) or a 'kind:detail' token (suppresses that detail)."""
    p = path or DEFAULT_ALLOW_FILE
    allow: Set[str] = set()
    if p.exists():
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            allow.add(line.strip())
    return allow


_DEFAULT_JSX_ROOT = Path("app") / "web_ui"
_PY_DEFAULT_GLOBS = ("app/**/*.py",)


def discover(paths: Sequence[str], include_py: bool) -> List[Path]:
    out: List[Path] = []
    roots = [Path(p) for p in paths] if paths else None
    if roots:
        for r in roots:
            if r.is_file():
                out.append(r)
            elif r.is_dir():
                out.extend(sorted(r.rglob("*.jsx")))
                out.extend(sorted(r.rglob("*.tsx")))
                if include_py:
                    out.extend(sorted(r.rglob("*.py")))
    else:
        # default scope: the JSX UI
        if _DEFAULT_JSX_ROOT.is_dir():
            out.extend(sorted(_DEFAULT_JSX_ROOT.rglob("*.jsx")))
            out.extend(sorted(_DEFAULT_JSX_ROOT.rglob("*.tsx")))
        if include_py:
            for g in _PY_DEFAULT_GLOBS:
                out.extend(sorted(Path(".").glob(g)))
    # de-dup, stable
    seen: Set[str] = set()
    uniq: List[Path] = []
    for p in out:
        k = str(p.resolve())
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


# ───────────────────────────────────────────────────────────────────────────
# CLI
# ───────────────────────────────────────────────────────────────────────────

def run(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="voice_lint",
        description="ArchHub voice/microcopy lint (studio-language §11).",
    )
    ap.add_argument("paths", nargs="*", help="files/dirs to scan (default: app/web_ui)")
    ap.add_argument("--all", action="store_true", help="also scan py user-message sinks")
    ap.add_argument("--json", action="store_true", help="machine-readable findings")
    ap.add_argument("--advisory", action="store_true", help="report only; always exit 0")
    ap.add_argument("--strict", action="store_true", help="exit 1 on any finding")
    ap.add_argument("--allow", type=str, default=None, help="path to allowlist file")
    args = ap.parse_args(argv)

    allow = load_allowlist(Path(args.allow) if args.allow else None)
    files = discover(args.paths, include_py=args.all)

    if args.paths:
        missing = [p for p in args.paths if not Path(p).exists()]
        if missing:
            sys.stderr.write("voice_lint: path(s) not found: " + ", ".join(missing) + "\n")
            return 2

    all_findings: List[Finding] = []
    for f in files:
        all_findings.extend(lint_file(f, allow))

    if args.json:
        print(json.dumps([asdict(x) for x in all_findings], ensure_ascii=False, indent=2))
    else:
        if all_findings:
            by_kind = {}
            for x in all_findings:
                by_kind[x.kind] = by_kind.get(x.kind, 0) + 1
            for x in all_findings:
                print(x.fmt())
            summary = ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items()))
            print(f"\nvoice_lint: {len(all_findings)} finding(s) across {len(files)} file(s) [{summary}]")
        else:
            print(f"voice_lint: clean — 0 findings across {len(files)} file(s).")

    if args.advisory:
        return 0
    if all_findings and args.strict:
        return 1
    # default (neither flag): behave as advisory-report, exit 0 unless strict.
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
