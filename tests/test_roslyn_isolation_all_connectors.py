"""AgDR-0025 — Subprocess csc.exe Roslyn isolation across ALL .NET connectors.

These tests pin the .NET source layout (Python can read the .cs/.csproj
text but can't compile them here) and the docs.  The actual compile +
deploy happens via `app/auto_build.py` invoked by the user / installer.

Comment text is allowed to MENTION the legacy APIs (Microsoft.CodeAnalysis,
CSharpScript.RunAsync) — what's banned is actual `using` directives and
real call sites.  Tests below check for the usage shapes, not bare names.
"""
from __future__ import annotations

import re
from pathlib import Path


SOURCES = Path(__file__).resolve().parents[1] / "payload" / "sources"
DOCS = Path(__file__).resolve().parents[1] / "docs"


def _strip_cs_comments(src: str) -> str:
    """Remove // line comments + /* block */ comments so substring
    matches don't false-positive on prose."""
    # /* ... */ block (greedy, multi-line).
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    # // single-line.
    src = re.sub(r"//[^\n]*", "", src)
    return src


# ─── 1. shared ScriptCompiler exists + has the canonical pieces ─────


def test_shared_script_compiler_exists():
    p = SOURCES / "shared" / "ScriptCompiler.cs"
    assert p.exists(), "shared ScriptCompiler.cs must exist for every connector to link"
    raw = p.read_text(encoding="utf-8")
    code = _strip_cs_comments(raw)
    # No in-process Roslyn usage (using directive or real call).
    assert "using Microsoft.CodeAnalysis" not in code
    assert "CSharpScript.RunAsync(" not in code
    # The csc probe order (env var → Framework → VS BuildTools).
    assert "ARCHHUB_CSC_PATH" in code
    assert "Framework64" in code
    assert "BuildTools" in code
    # The compile cache.
    assert "archhub-csc-cache" in code
    assert "SHA256" in code
    # Honest failure modes.
    assert "csc_missing" in code
    assert "compile_error" in code
    # Wrapper template emits Entry.Run + a result local.
    assert "public static object Run" in code
    assert "ctx.result = result" in code


def test_shared_script_compiler_namespace_is_archhub_shared():
    """`<Link>`-ing into each connector csproj only works if the
    namespace is consistent across consumers."""
    code = _strip_cs_comments(
        (SOURCES / "shared" / "ScriptCompiler.cs").read_text(encoding="utf-8"))
    assert "namespace ArchHub.Shared" in code


# ─── 2. revit_mcp uses ScriptCompiler, no in-process Roslyn ────────


def test_revit_core_csproj_links_shared_and_drops_roslyn():
    """AgDR-0027 — Core (not shim) owns ScriptCompiler now."""
    p = SOURCES / "revit_mcp_core" / "RevitMCPCore.csproj"
    src = p.read_text(encoding="utf-8")
    assert '<Compile Include="..\\shared\\ScriptCompiler.cs"' in src
    code = _strip_cs_comments(src)
    assert 'PackageReference Include="Microsoft.CodeAnalysis' not in code
    # Shim's csproj should NOT include Microsoft.CodeAnalysis package
    # references either.
    shim_src = (SOURCES / "revit_mcp" / "RevitMCP.csproj").read_text(encoding="utf-8")
    assert 'PackageReference Include="Microsoft.CodeAnalysis' not in _strip_cs_comments(shim_src)


def test_revit_core_uses_script_compiler():
    """AgDR-0027 — RunCSharpScript moved into Core (RevitMCPCore.cs).
    The shim's RevitEventHandler is now just a UI-thread work pump."""
    p = SOURCES / "revit_mcp_core" / "RevitMCPCore.cs"
    code = _strip_cs_comments(p.read_text(encoding="utf-8"))
    # Old in-process API gone.
    assert "using Microsoft.CodeAnalysis" not in code
    assert "CSharpScript.RunAsync(" not in code
    assert "ScriptOptions" not in code
    # New subprocess-csc API in use.
    assert "using ArchHub.Shared;" in code
    assert "ScriptCompiler.CompileAndRun" in code
    assert "subprocess_csc" in code
    # The shim's event handler must NOT touch ScriptCompiler.
    shim_eh = (SOURCES / "revit_mcp" / "RevitEventHandler.cs").read_text(encoding="utf-8")
    assert "ScriptCompiler" not in _strip_cs_comments(shim_eh)


def test_revit_core_ping_advertises_subprocess_csc():
    """/ping moved into Core's HTTP routing."""
    p = SOURCES / "revit_mcp_core" / "RevitMCPCore.cs"
    code = _strip_cs_comments(p.read_text(encoding="utf-8"))
    assert "subprocess_csc" in code
    assert "csc_status" in code


# ─── 3. acad_mcp parity ────────────────────────────────────────────


def test_acad_csproj_links_shared_and_drops_roslyn():
    p = SOURCES / "acad_mcp" / "AcadMCP.csproj"
    src = p.read_text(encoding="utf-8")
    assert '<Compile Include="..\\shared\\ScriptCompiler.cs"' in src
    code = _strip_cs_comments(src)
    assert 'PackageReference Include="Microsoft.CodeAnalysis' not in code


def test_acad_app_uses_script_compiler():
    p = SOURCES / "acad_mcp" / "AcadMCPApp.cs"
    raw = p.read_text(encoding="utf-8")
    code = _strip_cs_comments(raw)
    assert "using Microsoft.CodeAnalysis" not in code
    assert "CSharpScript.RunAsync(" not in code
    assert "ScriptOptions" not in code
    assert "using ArchHub.Shared;" in code
    assert "ScriptCompiler.CompileAndRun" in code
    assert "subprocess_csc" in code  # ping reports the modern compiler


# ─── 4. AgDR-0025 doc + AgDR-0023 superseded marker ─────────────────


def test_agdr_0025_exists():
    p = DOCS / "agdr" / "AgDR-0025-roslyn-isolation-all-connectors.md"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "status: approved" in text
    # Scope is BROADER than AgDR-0023 — covers all connectors.
    assert "RevitMCP" in text and "AcadMCP" in text
    # Names the shared file path.
    assert "shared/ScriptCompiler.cs" in text
    # Acceptance criteria call out csc + no FileLoadException.
    assert "subprocess_csc" in text
    assert "FileLoadException" in text


def test_agdr_0023_marked_superseded():
    p = DOCS / "agdr" / "AgDR-0023-revitmcp-roslyn-isolation.md"
    text = p.read_text(encoding="utf-8")
    assert "status: superseded by AgDR-0025" in text


# ─── 5. cross-cutting: no real in-process Roslyn anywhere ──────────


def test_no_connector_uses_in_process_roslyn():
    """Sweep every .cs file under payload/sources/.  None may import
    Microsoft.CodeAnalysis or call CSharpScript.RunAsync.  This is the
    founder's "shouldn't happen with OTHER connectors" guarantee turned
    into a regression guard."""
    for cs in SOURCES.rglob("*.cs"):
        # Skip generated/obj output.
        if "obj" in cs.parts or "bin" in cs.parts:
            continue
        raw = cs.read_text(encoding="utf-8", errors="ignore")
        code = _strip_cs_comments(raw)
        assert "using Microsoft.CodeAnalysis" not in code, \
            f"{cs} still imports in-process Roslyn"
        assert "CSharpScript.RunAsync(" not in code, \
            f"{cs} still calls CSharpScript.RunAsync — must use ScriptCompiler"
