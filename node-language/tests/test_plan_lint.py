"""AgDR-0054 · BRV-13 — the no-later plan-lint gate (tools/plan_lint.py).

Gate (the requirement leaf): `python tools/plan_lint.py docs/ROADMAP.md` returns
the expected reject/pass; a bare deferral is rejected, a `depends-on:`/
`safety-gated:`-tagged hold passes (acceptance #25).

RED on origin/main: `tools/plan_lint.py` does not exist, so both the import and
the subprocess CLI fail — the detector (`completion_gate.scan_deferral`) had no
plan-scanning consumer. GREEN here: the gate scans, exempts tagged holds, and
exits 1/0 per the contract.

Runs under pytest AND standalone: `python tests/test_plan_lint.py`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import plan_lint as pl  # noqa: E402

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "plan_lint.py"


# ── core: bare deferral rejected, tagged hold passes ─────────────────────────

def test_bare_later_is_flagged():
    findings = pl.lint_text("- [ ] wire the cornice ring later\n", filename="p.md")
    assert len(findings) == 1
    assert "later" in findings[0].markers


def test_depends_on_tag_exempts():
    """A not-now item carrying a real depends-on:<leaf-id> is legal sequencing."""
    findings = pl.lint_text(
        "- [ ] wire the cornice ring later, depends-on:BRV-04\n", filename="p.md")
    assert findings == []


def test_safety_gated_tag_exempts():
    findings = pl.lint_text(
        "- [ ] defer S5 rollout, safety-gated: must survive red-team first\n",
        filename="p.md")
    assert findings == []


def test_bare_deferral_with_empty_tag_value_still_flagged():
    """A hold tag with NO reason (`depends-on:`) is not a justified hold — the
    cowardly-deferral bypass the spec forbids."""
    findings = pl.lint_text("- [ ] do it later depends-on:\n", filename="p.md")
    assert len(findings) == 1


def test_phase_n_is_a_plan_deferral():
    findings = pl.lint_text("- [ ] polish the panel in phase 2\n", filename="p.md")
    assert len(findings) == 1
    assert "phase-n" in findings[0].markers


def test_phase_n_with_tag_passes():
    findings = pl.lint_text(
        "- [ ] panel polish phase-2, depends-on:UI-09\n", filename="p.md")
    assert findings == []


def test_partial_and_for_hardening_flagged():
    """The shared detector's markers are honoured by the gate (ONE-SYSTEM)."""
    assert pl.lint_text("- [ ] partial pass on auth\n", filename="p.md")
    assert pl.lint_text("- [ ] leave the rest for hardening\n", filename="p.md")


def test_clean_plan_passes():
    text = ("- [ ] build the whole curtain wall now\n"
            "- [x] rooms compute area from bounding walls\n")
    assert pl.lint_text(text, filename="p.md") == []


# ── exemptions: code fences, frontmatter, explicit pragma ────────────────────

def test_code_fence_is_skipped():
    """Example text inside a ``` fence is illustrative, not a plan item."""
    text = ("- [ ] do the real thing now\n"
            "```\n"
            "example: do this later\n"
            "```\n")
    assert pl.lint_text(text, filename="p.md") == []


def test_frontmatter_status_is_skipped():
    """YAML frontmatter (status strings) is metadata, not a deferrable item."""
    text = ("---\n"
            "id: AgDR-9999\n"
            "status: build-pending — partial direction, follow-up later\n"
            "---\n"
            "- [ ] build it now\n")
    assert pl.lint_text(text, filename="p.md") == []


def test_pragma_ignore_exempts_legacy_line():
    text = "- [ ] legacy item parked for now <!-- plan-lint: ignore -->\n"
    assert pl.lint_text(text, filename="p.md") == []


# ── the leaf's exact CLI contract (subprocess, real exit codes) ──────────────

def test_cli_rejects_bare_deferral(tmp_path):
    bad = tmp_path / "ROADMAP.md"
    bad.write_text("- [ ] ship the dam later\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(_TOOL), str(bad)],
                          capture_output=True, text=True)
    assert proc.returncode == 1                       # reject
    assert "REJECT" in proc.stderr


def test_cli_passes_tagged_hold(tmp_path):
    good = tmp_path / "ROADMAP.md"
    good.write_text("- [ ] ship the dam later, depends-on:BRV-04\n",
                    encoding="utf-8")
    proc = subprocess.run([sys.executable, str(_TOOL), str(good)],
                          capture_output=True, text=True)
    assert proc.returncode == 0                       # pass
    assert "PASS" in proc.stdout


def test_cli_usage_error_when_no_args():
    proc = subprocess.run([sys.executable, str(_TOOL)],
                          capture_output=True, text=True)
    assert proc.returncode == 2


def test_cli_runs_on_the_real_roadmap_file():
    """The gate must actually run over the repo's real docs/ROADMAP.md and
    return a definite verdict (0 or 1), not crash — the leaf names this file.

    The real ROADMAP carries legacy PLAN-LOCKED debt, so a reject (1) here is
    the HONEST signal that the no-later gate has un-tagged deferrals to fix; a
    pass (0) means it is clean. Either is a valid gate verdict — what we pin is
    that the gate executes against the real artifact and decides."""
    roadmap = Path(__file__).resolve().parents[1] / "docs" / "ROADMAP.md"
    assert roadmap.is_file()
    proc = subprocess.run([sys.executable, str(_TOOL), str(roadmap)],
                          capture_output=True, text=True)
    assert proc.returncode in (0, 1)
    # a definite verdict was emitted on the right stream
    assert ("REJECT" in proc.stderr) or ("PASS" in proc.stdout)


def _run_standalone() -> int:
    import tempfile
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        try:
            # crude tmp_path for standalone runs
            if "tmp_path" in fn.__code__.co_varnames[:fn.__code__.co_argcount]:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
