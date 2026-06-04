"""AgDR-0051 — ScriptCompiler BCL forwarder-facade cold-start refs.

Source-level guard (regex over the .cs — no .NET runtime in CI) pinning
the fix for the CS0012 cold-start hole: the lazy BCL facades
(System.Runtime / netstandard / mscorlib) must be force-added to csc's
/reference: list, resolved BY FILE from the runtime dir of
typeof(object), so a cold first /exec can't emit
"add a reference to assembly 'System.Runtime'".

A regression here = list_levels + Revit structured tools break again on
a cold Core, so these pin the mechanism at PR time.
"""
from __future__ import annotations

import re
from pathlib import Path

SOURCES = Path(__file__).resolve().parents[1] / "payload" / "sources"
SC = SOURCES / "shared" / "ScriptCompiler.cs"
DOCS = Path(__file__).resolve().parents[1] / "docs"


def _strip(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def test_bcl_facade_helper_present():
    code = _strip(SC.read_text(encoding="utf-8"))
    assert "_BclFacadeRefs" in code, "the facade-resolver helper is missing"
    # Resolved by FILE from the runtime dir of typeof(object) — that is
    # the dir that holds the facades regardless of lazy-load order.
    assert "typeof(object).Assembly.Location" in code
    assert "Path.GetDirectoryName" in code


def test_bcl_facade_helper_lists_the_critical_facades():
    code = _strip(SC.read_text(encoding="utf-8"))
    # The one CS0012 actually names, plus its required companions.
    for name in ("System.Runtime.dll", "netstandard.dll", "mscorlib.dll"):
        assert f'"{name}"' in code, f"facade {name} not force-referenced"


def test_bcl_facade_helper_excludes_private_corelib():
    """Referencing System.Private.CoreLib.dll ALONGSIDE the facades
    confuses csc about where System.Object lives (CS0518). It is always
    typeof(object).Assembly and already in the host GetAssemblies() list,
    so it must NOT be in the facade set."""
    code = _strip(SC.read_text(encoding="utf-8"))
    # It may appear in prose/strings, but must not be a quoted entry in
    # the facade name array. The array entries are quoted "*.dll".
    assert '"System.Private.CoreLib.dll"' not in code


def test_compile_and_run_merges_facades_additively():
    code = _strip(SC.read_text(encoding="utf-8"))
    # The merge is additive: starts from the caller's `references`, adds
    # the facades, de-dupes. Must NOT drop the caller's refs.
    assert "_BclFacadeRefs()" in code
    assert "merged.AddRange" in code or "AddRange(facades)" in code
    # De-dupe + existence filter preserved (AgDR-0031 semantics).
    assert "Distinct(StringComparer.OrdinalIgnoreCase)" in code
    assert "Where(File.Exists)" in code


def test_reference_loop_iterates_the_merged_list():
    """The /reference: response-file loop + the cache hash must iterate
    the MERGED list (`refs`), else the facades never reach csc."""
    code = _strip(SC.read_text(encoding="utf-8"))
    # The response-file loop writes /reference: for each entry of `refs`.
    assert re.search(r"foreach\s*\(\s*var\s+rf\s+in\s+refs\s*\)", code), \
        "response-file loop must iterate the merged `refs`, not `references`"
    # The cache hash is computed over `refs` so a cold/warm ref-set change
    # busts the cache correctly.
    assert re.search(r"Hash\([^)]*\brefs\b", code, flags=re.S)


def test_no_port_or_transaction_or_entrypoint_touched_by_fix():
    """Incident-safety guard: the AgDR-0051 fix is reference-list only.
    The shared compiler must not have grown port / transaction / HTTP
    surface (those belong to the per-connector Cores, never here)."""
    code = _strip(SC.read_text(encoding="utf-8"))
    for forbidden in ("HttpListener", "Transaction", "Prefixes.Add",
                      "48884", "48885", "48887"):
        assert forbidden not in code, (
            f"ScriptCompiler.cs must stay a pure compiler — found {forbidden!r}")


def test_agdr_0051_exists_and_executed():
    p = DOCS / "agdr" / "AgDR-0051-scriptcompiler-bcl-facade-cold-start-refs.md"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "status: executed" in text
    assert "System.Runtime" in text
    assert "CS0012" in text
    # Additive-only + incident-safety promise recorded.
    assert "ADDITIVE" in text.upper()
    assert "48885" in text  # the reverted-port incident referenced
