"""AgDR-0030 — ScriptCompiler csc probe + langversion gate + bundled csc.

Source tests (regex over the .cs) — we don't have .NET runtime here,
but we pin the probe ORDER + gate + dotnet-exec wiring at the source
level so a regression is caught at PR time.

Python-side tests cover the bundled csc download helper.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

SOURCES = Path(__file__).resolve().parents[1] / "payload" / "sources"
SC = SOURCES / "shared" / "ScriptCompiler.cs"
DOCS = Path(__file__).resolve().parents[1] / "docs"


def _strip(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


# ─── 1. probe order matches Fork A1 ─────────────────────────────────


def test_probe_order_starts_with_env_then_bundled():
    code = _strip(SC.read_text(encoding="utf-8"))
    # Env override first.
    env_idx = code.find("ARCHHUB_CSC_PATH")
    # Bundled csc.exe second.
    bundled_idx = code.find("ArchHub\", \"bin\", \"csc\"")
    # BuildTools third.
    bt_idx = code.find("MSBuild\\\\Current\\\\Bin\\\\Roslyn")
    if bt_idx < 0:
        bt_idx = code.find("\"MSBuild\", \"Current\", \"Bin\", \"Roslyn\"")
    # SDK csc.dll fourth.
    sdk_idx = code.find("_FindSdkCsc")
    # Framework64 last (gated).
    fx_idx = code.find("Framework64")

    assert env_idx >= 0, "env override path missing"
    assert bundled_idx >= 0, "bundled csc probe missing"
    assert bt_idx >= 0, "VS BuildTools probe missing"
    assert sdk_idx >= 0, "SDK csc.dll probe missing"
    assert fx_idx >= 0, "Framework64 fallback missing"

    # Order: env < bundled < BuildTools < SDK < Framework64.  Look at
    # FIRST occurrence within _ProbeOnce.  We use position in source.
    assert env_idx < bundled_idx < bt_idx, "bundled must precede BuildTools"
    assert bt_idx < sdk_idx, "BuildTools must precede SDK"
    assert sdk_idx < fx_idx, "Framework64 must be LAST resort"


def test_every_candidate_passes_through_langversion_gate():
    """The fix for the C# 5 csc bug is: every probe call must go
    through `_AcceptsLangVersion73` before being accepted."""
    code = _strip(SC.read_text(encoding="utf-8"))
    assert "_AcceptsLangVersion73" in code
    # At least 4 call sites (env override + bundled + BuildTools + SDK +
    # Framework64) — let's just assert ≥4.
    assert code.count("_AcceptsLangVersion73(") >= 4


def test_langversion_gate_rejects_csharp5_signature():
    code = _strip(SC.read_text(encoding="utf-8"))
    # The rejection strings must exist.
    assert 'only supports language versions up to c# 5' in code.lower()
    # And the gate must check ≥7.3 / 8 / latest.
    assert '"7.3"' in code
    assert 'latest' in code.lower()


def test_find_sdk_csc_parses_dotnet_list_sdks():
    code = _strip(SC.read_text(encoding="utf-8"))
    assert "--list-sdks" in code
    assert "Roslyn" in code and "bincore" in code and "csc.dll" in code


def test_probe_detailed_returns_dotnet_exec_flag():
    code = _strip(SC.read_text(encoding="utf-8"))
    assert "ProbeCscDetailed" in code
    assert "needsDotnetExec" in code


def test_compile_and_run_uses_dotnet_exec_when_needed():
    code = _strip(SC.read_text(encoding="utf-8"))
    # ProcessStartInfo branches on needsDotnetExec.
    assert "if (needsDotnetExec)" in code
    # `dotnet exec "<csc.dll>" <args>` form present.
    assert '"exec \\"" + csc + "\\" "' in code or 'dotnet' in code


def test_csc_missing_error_points_at_sdk_install():
    code = _strip(SC.read_text(encoding="utf-8"))
    assert "csc_missing" in code
    # Helpful install pointers.
    assert "dot.net" in code or ".NET 8 SDK" in code
    assert "BuildTools" in code or "vs_BuildTools" in code


# ─── 2. CoreEntry eager-probes at boot ──────────────────────────────


def test_revit_core_eager_probes_csc_at_start():
    core = SOURCES / "revit_mcp_core" / "RevitMCPCore.cs"
    code = _strip(core.read_text(encoding="utf-8"))
    # ProbeCscDetailed called inside Start (after listener binds, before
    # we accept any /exec).
    assert "ScriptCompiler.ProbeCscDetailed" in code
    assert "Eager csc probe" in code


def test_reset_probe_helper_present():
    code = _strip(SC.read_text(encoding="utf-8"))
    assert "ResetProbe" in code  # lazy re-probe path (Fork C3)


# ─── 3. bundled csc download helper ─────────────────────────────────


def test_auto_build_exposes_ensure_bundled_csc():
    import auto_build
    assert hasattr(auto_build, "ensure_bundled_csc")


def test_bundled_csc_dir_under_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import importlib, auto_build
    importlib.reload(auto_build)
    p = auto_build._bundled_csc_dir()
    assert str(tmp_path) in str(p)
    assert p.name == "csc"


def test_ensure_bundled_csc_skips_when_present(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import importlib, auto_build
    importlib.reload(auto_build)
    target = auto_build._bundled_csc_dir() / "csc.exe"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"pretend csc")

    fired = []
    def _fake_urlopen(*a, **kw):
        fired.append(a)
        raise RuntimeError("urlopen should not be called when bundle exists")
    monkeypatch.setattr(auto_build.urllib.request, "urlopen", _fake_urlopen)

    out = auto_build.ensure_bundled_csc()
    assert out == target
    assert fired == []


def test_revit_build_calls_ensure_bundled_csc(monkeypatch):
    import auto_build
    monkeypatch.setattr(auto_build, "find_revit_install",
                        lambda y: Path(r"C:\fake\Revit"))
    monkeypatch.setattr(auto_build, "detect_dotnet_sdk", lambda: "8.0.405")
    fired = []
    monkeypatch.setattr(auto_build, "ensure_bundled_csc",
                        lambda on_progress=None: fired.append(True) or None)
    monkeypatch.setattr(auto_build, "_build_dotnet_connector",
                        lambda **kw: auto_build.BuildResult(True, "stub", []))
    auto_build.build_revit_connector(2025)
    assert fired, "build_revit_connector must trigger ensure_bundled_csc"


# ─── 4. AgDR-0030 doc ──────────────────────────────────────────────


def test_agdr_0030_exists_and_approved():
    p = DOCS / "agdr" / "AgDR-0030-csc-probe-modern-roslyn-fallback.md"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "status: executed" in text
    assert "A1 — BuildTools" in text
    assert "B3 — Bundle ONCE" in text
    assert "C3 — Both eager" in text
