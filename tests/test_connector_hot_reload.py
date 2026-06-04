"""AgDR-0027 — connector hot-reload structural tests.

Pins:
  - shared ICoreEntryPoint + CoreLoader exist
  - RevitMCP split into stable shim + hot-reloadable Core
  - shim has NO HTTP listener or /exec code (lives in Core)
  - Core implements ICoreEntryPoint + exposes a /reload route
  - Core's reload trigger wires back to the shim
  - AgDR-0027 doc exists
"""
from __future__ import annotations

import re
from pathlib import Path


SOURCES = Path(__file__).resolve().parents[1] / "payload" / "sources"
DOCS = Path(__file__).resolve().parents[1] / "docs"


def _strip_cs_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


# ─── 1. shared hot-reload contract ──────────────────────────────────


def test_shared_placeholder_present():
    """AgDR-0027 v2 — interface-based ABI scrapped (broke type identity
    across <Link>'d assemblies).  Replaced with reflection + BCL
    delegates.  Placeholder file kept so csproj <Link> entries don't
    error."""
    p = SOURCES / "shared" / "ICoreEntryPoint.cs"
    assert p.exists()
    code = _strip_cs_comments(p.read_text(encoding="utf-8"))
    # No public interface — that was the original bug.
    assert "interface ICoreEntryPoint" not in code
    assert "interface IWorkQueue" not in code
    # File still declares the namespace so it compiles cleanly.
    assert "namespace ArchHub.Shared" in code


def test_core_loader_uses_collectible_alc_and_reflection_abi():
    p = SOURCES / "shared" / "CoreLoader.cs"
    assert p.exists()
    code = _strip_cs_comments(p.read_text(encoding="utf-8"))
    # net8 path uses collectible ALC.
    assert "AssemblyLoadContext" in code
    assert "isCollectible: true" in code
    assert ".Unload()" in code
    # Reflection-based discovery (binds CoreEntry by NAME, not interface).
    assert 't.Name == "CoreEntry"' in code
    assert 'GetMethod("Start")' in code
    assert 'GetMethod("Stop")' in code
    # No interface checks remain (the original bug).
    assert "IsAssignableFrom" not in code
    # File sha256 helper for /reload cache keys.
    assert "Sha256OfFile" in code
    # Submit delegate uses BCL types only — single runtime identity.
    assert "Func<Func<object, string>, Task<string>>" in code


# ─── 2. shim is small + has no /exec or HTTP server ────────────────


def test_revit_shim_has_no_http_server_or_exec():
    """Shim must NOT carry the HTTP listener or /exec.  Those live
    in Core so a hot-swap is meaningful."""
    p = SOURCES / "revit_mcp" / "RevitMCPApp.cs"
    code = _strip_cs_comments(p.read_text(encoding="utf-8"))
    # No HttpListener instantiation in the shim.
    assert "new HttpListener" not in code
    # No /exec route handling.
    assert '"/exec"' not in code
    # No ScriptCompiler usage in the shim.
    assert "ScriptCompiler.CompileAndRun" not in code


def test_revit_shim_uses_core_loader_and_wires_reload_trigger():
    p = SOURCES / "revit_mcp" / "RevitMCPApp.cs"
    code = _strip_cs_comments(p.read_text(encoding="utf-8"))
    # Loads RevitMCPCore.dll via shared CoreLoader.
    assert "CoreLoader" in code
    assert "RevitMCPCore.dll" in code
    # Wires the reload-trigger delegate so Core can ask shim to swap.
    # (Property name set by CoreLoader via reflection — see CoreLoader.)
    assert "reloadTrigger" in code
    assert "_loader.Unload()" in code


def test_revit_shim_csproj_links_shared_loader_not_compiler():
    p = SOURCES / "revit_mcp" / "RevitMCP.csproj"
    src = p.read_text(encoding="utf-8")
    # Shim links the loader + contract.
    assert "ICoreEntryPoint.cs" in src
    assert "CoreLoader.cs" in src
    # Shim does NOT link ScriptCompiler — that lives in Core.
    assert "ScriptCompiler.cs" not in src


# ─── 3. Core implements ICoreEntryPoint + /reload route ────────────


def test_revit_core_csproj_links_contract_and_compiler():
    p = SOURCES / "revit_mcp_core" / "RevitMCPCore.csproj"
    assert p.exists()
    src = p.read_text(encoding="utf-8")
    assert "ICoreEntryPoint.cs" in src
    assert "ScriptCompiler.cs" in src


def test_revit_core_exposes_corentry_reflection_abi():
    """AgDR-0027 v2 — CoreEntry is discovered by NAME via reflection,
    not by interface implementation.  Required signature: Start(submit,
    log, hostInfo)→int, Stop(), ReloadTriggerForShim settable property."""
    p = SOURCES / "revit_mcp_core" / "RevitMCPCore.cs"
    assert p.exists()
    code = _strip_cs_comments(p.read_text(encoding="utf-8"))
    # No interface — bug-prone in <Link>'d source layout.
    assert "class CoreEntry" in code
    assert ": ICoreEntryPoint" not in code
    # Reflection-discoverable signatures.
    assert "public int Start(" in code
    assert "public void Stop()" in code
    assert "ReloadTriggerForShim" in code
    # BCL-only parameter types so identity is stable.
    assert "Func<Func<object, string>, Task<string>>" in code


def test_revit_core_exposes_reload_route():
    code = _strip_cs_comments(
        (SOURCES / "revit_mcp_core" / "RevitMCPCore.cs").read_text(encoding="utf-8"))
    # /reload is wired in the route switch.
    assert '"/reload"' in code
    # Reports core_sha + hot_reload flag in /ping.
    assert "core_sha" in code
    assert "hot_reload" in code


def test_revit_core_uses_script_compiler_with_core_namespace():
    code = _strip_cs_comments(
        (SOURCES / "revit_mcp_core" / "RevitMCPCore.cs").read_text(encoding="utf-8"))
    # Script wrapper binds to RevitMCPCore.ScriptContext (NOT
    # RevitMCP.ScriptContext from the old monolithic build).
    assert "global::RevitMCPCore.ScriptContext" in code
    assert "ScriptCompiler.CompileAndRun" in code


# ─── 4. AgDR-0027 doc ──────────────────────────────────────────────


def test_agdr_0027_exists():
    p = DOCS / "agdr" / "AgDR-0027-connector-hot-reload.md"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "status: executed" in text
    assert "AssemblyLoadContext" in text
    assert "ICoreEntryPoint" in text
    # Acceptance: no Revit restart for future updates.
    assert "No Revit restart" in text or "no Revit restart" in text
