# -*- coding: utf-8 -*-
"""Tests for tools/voice_lint.py — the voice/microcopy lint (studio-language §11).

Runnable under pytest AND as a bare script (`python tests/test_voice_lint.py`).
The module is loaded by ABSOLUTE PATH via importlib (registered in sys.modules so
its @dataclass resolves), so collection never depends on cwd / package layout.

RED -> GREEN contract (the proof this lane ships):
  * RED   — with tools/voice_lint.py ABSENT, `_load_voice_lint()` raises and every
            test errors (import-time failure). The lint cannot pass before it
            exists. (Demonstrated in-session via `git stash` of the tool.)
  * RED   — `test_catches_planted_violation` FAILS if the tool does not flag a
            planted §11 violation (emoji / exclamation / banned word).
  * GREEN — once the tool exists and is correct: clean §11-compliant copy yields
            ZERO findings, and the planted violations are all caught.
"""
import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[1]
_TOOL = _REPO / "tools" / "voice_lint.py"


def _load_voice_lint():
    """Import tools/voice_lint.py by absolute path. Raises if the file is
    absent (that absence IS the RED state before the tool is built)."""
    if not _TOOL.exists():
        raise ModuleNotFoundError(
            f"voice_lint not built yet: {_TOOL} (RED — build the tool to go GREEN)"
        )
    spec = importlib.util.spec_from_file_location("archhub_voice_lint_under_test", str(_TOOL))
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so the module's @dataclass can resolve its own module.
    sys.modules["archhub_voice_lint_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


vl = _load_voice_lint()


# ── §11 DON'T pairs — every one MUST be flagged ────────────────────────────

# (string, expected-kind-present)
DONT = [
    ("Successfully completed your task! \U0001F389", "emoji"),         # 🎉
    ("Successfully completed your task! \U0001F389", "exclamation"),
    ("Successfully completed your task! \U0001F389", "banned-word"),   # successfully
    ("Oops! Something went wrong.", "exclamation"),
    ("Oops! Something went wrong.", "banned-word"),                    # oops
    ("Generating amazing content for you…", "banned-word"),       # generate + amazing
    ("Unlock advanced workflows with Premium.", None),                 # (not a §11 word; sanity)
    ("A seamless, effortless, revolutionary experience", "banned-word"),
    ("This will produce the outputs", "banned-word"),                 # produce
    ("Powerful new features", "banned-word"),                          # powerful
]


def test_catches_planted_violation():
    """The tool flags planted §11 violations. RED if any expected kind is missed."""
    for text, expected_kind in DONT:
        kinds = {k for k, _, _ in vl.lint_string(text)}
        if expected_kind is None:
            continue
        assert expected_kind in kinds, (
            f"voice_lint MISSED a planted {expected_kind!r} in {text!r}; got {kinds}"
        )


def test_each_banned_word_is_caught():
    """Every word in the §11 banned list is detected in a simple sentence."""
    for w in vl.BANNED_WORDS:
        sentence = f"We will {w} the thing for you"
        kinds_details = [(k, d) for k, d, _ in vl.lint_string(sentence)]
        assert any(k == "banned-word" for k, _ in kinds_details), (
            f"banned word {w!r} not caught in {sentence!r}: {kinds_details}"
        )


def test_emoji_is_caught():
    """Pictographic emoji (BMP + supplementary) are flagged."""
    for ch in ("\U0001F389", "\U0001F680", "\U0001F4A1", "\U0001F525", "✅", "❌", "✨"):
        kinds = {k for k, _, _ in vl.lint_string(f"Done {ch} now")}
        assert "emoji" in kinds, f"emoji {ch!r} (U+{ord(ch):05X}) not flagged"


def test_exclamation_is_caught():
    for text in ("Done!", "Ready already!", "Welcome to ArchHub!"):
        kinds = {k for k, _, _ in vl.lint_string(text)}
        assert "exclamation" in kinds, f"exclamation in {text!r} not flagged"


# ── §11 DO copy + §08 iconography — every one MUST be CLEAN ─────────────────

CLEAN = [
    # §11 DO column — calm, concrete, no hype:
    "Dimensioned 47 walls in active view.",
    "Revit dropped — reconnecting on :7331.",
    "Save this as a Skill — 3 clicks, JSON.",
    "$0.024 for that run. 4.2k tokens.",
    "Ready in 1.8s.",
    "Click Heal to retry the handshake.",
    "Connected · Ready · Fresh · Synced",
    "Couldn't reach Revit · Handshake timed out",
    # §08 / §13 iconography — drafted glyphs are the language, NOT emoji:
    "Restart connector ⚡",     # ⚡ restart glyph (§13)
    "Toggle theme ◐",          # ◐ half circle
    "Run skill ↗",             # ↗ arrow
    "Heal now ↻",              # ↻ heal arrow
    "arch ⌬ node ◇ chain",  # ⌬ ◇ drafting glyphs (§08)
    "section ticks · mono",    # · middle dot
]


def test_clean_copy_has_no_findings():
    """§11-compliant copy and §08 iconography produce ZERO findings."""
    for text in CLEAN:
        findings = vl.lint_string(text)
        assert findings == [], f"false positive on clean copy {text!r}: {findings}"


def test_iconography_not_mistaken_for_emoji():
    """The §08 drafted glyph set must never be flagged as emoji — this is the
    one hard distinction the spec draws (§08 iconography vs §11 'no emoji')."""
    design_glyphs = "⌬◇⌗⌭✎▤¶⇄↗⚡◐☰⌕↻⌫⌘⇧↵●★✦"
    for g in design_glyphs:
        kinds = {k for k, _, _ in vl.lint_string(f"label {g} here")}
        assert "emoji" not in kinds, f"design glyph U+{ord(g):05X} {g!r} wrongly flagged as emoji"


# ── extraction + file-level + allowlist ────────────────────────────────────

def test_jsx_extraction_finds_copy_attrs_and_text():
    jsx = (
        "const X = () => (\n"
        "  <div label='Generating now'>\n"
        "    Successfully done!\n"
        "    <span title='all good'>plain</span>\n"
        "  </div>\n"
        ");\n"
    )
    strings = [s for _, _, s in vl.extract_jsx_strings(jsx)]
    assert any("Generating now" in s for s in strings)
    assert any("Successfully done" in s for s in strings)


def test_jsx_extraction_ignores_js_operators():
    """JS negation / comparison operators inside a .jsx must NOT surface as copy
    exclamations (the root cause of the noisy-lint failure mode)."""
    jsx = (
        "const a = () => {\n"
        "  if (!s) return null;\n"
        "  const shown = open || !long ? s : s.slice(0, N);\n"
        "  return x !== y;\n"
        "};\n"
    )
    findings = []
    for _, _, s in vl.extract_jsx_strings(jsx):
        findings.extend(vl.lint_string(s))
    excls = [f for f in findings if f[0] == "exclamation"]
    assert excls == [], f"JS operators wrongly flagged as copy exclamations: {excls}"


def test_lint_file_on_planted_jsx(tmp_path):
    p = tmp_path / "planted.jsx"
    p.write_text(
        "const C = () => (<button label='Generate amazing thing!'>Oops \U0001F389</button>);\n",
        encoding="utf-8",
    )
    findings = vl.lint_file(p, allow=set())
    kinds = {f.kind for f in findings}
    assert "banned-word" in kinds
    assert "exclamation" in kinds
    assert "emoji" in kinds


def test_lint_file_clean_jsx(tmp_path):
    p = tmp_path / "clean.jsx"
    p.write_text(
        "const C = () => (<button label='Run skill'>Dimensioned 47 walls.</button>);\n",
        encoding="utf-8",
    )
    assert vl.lint_file(p, allow=set()) == []


def test_allowlist_suppresses_verbatim(tmp_path):
    p = tmp_path / "x.jsx"
    p.write_text("const C = () => (<div label='Generate node'>ok</div>);\n", encoding="utf-8")
    # Without allowlist: flagged.
    assert any(f.kind == "banned-word" for f in vl.lint_file(p, allow=set()))
    # With the exact copy string allowlisted: suppressed.
    assert vl.lint_file(p, allow={"Generate node"}) == []


def test_allowlist_suppresses_kind_detail(tmp_path):
    p = tmp_path / "y.jsx"
    p.write_text("const C = () => (<div label='Generate node'>ok</div>);\n", encoding="utf-8")
    # 'banned-word:generate' token suppresses that detail everywhere.
    findings = vl.lint_file(p, allow={"banned-word:generate"})
    assert findings == []


def test_real_repo_jsx_scans_without_error():
    """Smoke: scanning the real UI dir runs end-to-end (MAKE-IT-REAL). It may
    return findings (advisory) — the contract here is that it does not crash and
    returns a list of Finding objects with the expected shape."""
    ui = _REPO / "app" / "web_ui"
    if not ui.is_dir():
        return
    files = vl.discover([str(ui)], include_py=False)
    assert files, "expected at least one jsx file under app/web_ui"
    total = 0
    for f in files:
        for finding in vl.lint_file(f, allow=set()):
            assert finding.kind in ("emoji", "exclamation", "banned-word")
            assert isinstance(finding.line, int) and finding.line >= 1
            total += 1
    # No assertion on count — advisory. Just proves the pipeline runs on reality.


if __name__ == "__main__":
    tests = [
        ("catches_planted_violation", test_catches_planted_violation),
        ("each_banned_word_is_caught", test_each_banned_word_is_caught),
        ("emoji_is_caught", test_emoji_is_caught),
        ("exclamation_is_caught", test_exclamation_is_caught),
        ("clean_copy_has_no_findings", test_clean_copy_has_no_findings),
        ("iconography_not_mistaken_for_emoji", test_iconography_not_mistaken_for_emoji),
        ("jsx_extraction_finds_copy", test_jsx_extraction_finds_copy_attrs_and_text),
        ("jsx_extraction_ignores_js_operators", test_jsx_extraction_ignores_js_operators),
        ("real_repo_jsx_scans_without_error", test_real_repo_jsx_scans_without_error),
    ]
    import tempfile

    def _with_tmp(fn):
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))

    tmp_tests = [
        ("lint_file_on_planted_jsx", test_lint_file_on_planted_jsx),
        ("lint_file_clean_jsx", test_lint_file_clean_jsx),
        ("allowlist_suppresses_verbatim", test_allowlist_suppresses_verbatim),
        ("allowlist_suppresses_kind_detail", test_allowlist_suppresses_kind_detail),
    ]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS", name)
        except AssertionError as ex:
            failures += 1
            print("FAIL", name, "-", ex)
        except Exception as ex:  # pragma: no cover
            failures += 1
            print("FAIL", name, "- error:", repr(ex))
    for name, fn in tmp_tests:
        try:
            _with_tmp(fn)
            print("PASS", name)
        except AssertionError as ex:
            failures += 1
            print("FAIL", name, "-", ex)
        except Exception as ex:  # pragma: no cover
            failures += 1
            print("FAIL", name, "- error:", repr(ex))
    total = len(tests) + len(tmp_tests)
    print(f"SUMMARY: {total - failures} passed, {failures} failed")
    sys.exit(1 if failures else 0)
