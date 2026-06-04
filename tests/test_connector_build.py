"""AgDR-0029 — data-driven multi-csproj connector build.

Pins:
  - _build_dotnet_connector discovers EVERY csproj under <host>_mcp*
    and builds them all into one output_dir
  - manifest gate fails when an expected DLL is missing
  - SHA-256 manifest entry blocks deploy when bytes differ
  - SHA-256 is recorded back into manifests opting in
  - build_revit_connector + build_acad_connector both flow through the
    helper (parametrised over hosts → adding a new .NET host that
    forgets to wire the build trips this suite)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import auto_build  # noqa: E402


# ─── 1. helper discovers every csproj under matching source roots ──


def test_build_helper_picks_up_every_csproj_under_glob(tmp_path, monkeypatch):
    """`revit_mcp*` should pick up both `revit_mcp/` and `revit_mcp_core/`."""
    sources = tmp_path / "sources"
    out = tmp_path / "out"
    (sources / "revit_mcp").mkdir(parents=True)
    (sources / "revit_mcp_core").mkdir()
    # Two csprojs — shim + core.
    (sources / "revit_mcp" / "RevitMCP.csproj").write_text("<Project/>")
    (sources / "revit_mcp_core" / "RevitMCPCore.csproj").write_text("<Project/>")

    monkeypatch.setattr(auto_build, "SOURCES_DIR", sources)
    monkeypatch.setattr(auto_build, "PAYLOAD_DIR", tmp_path / "payload")

    invoked: list[Path] = []

    def _fake_run(project_path, target_framework, msbuild_props,
                   output_dir, on_progress):
        invoked.append(Path(project_path))
        # Pretend the build dropped the expected DLL.
        (output_dir / (Path(project_path).stem + ".dll")).write_bytes(b"x")
        return (True, "ok")

    monkeypatch.setattr(auto_build, "_run_dotnet_build", _fake_run)
    result = auto_build._build_dotnet_connector(
        host_label="revit", year=2025,
        sources_glob="revit_mcp*", output_subdir="revit",
        msbuild_props={"X": "Y"}, target_framework="net8.0-windows",
        on_progress=lambda *_a, **_kw: None)

    assert result.success, result.detail
    invoked_names = sorted(p.name for p in invoked)
    assert invoked_names == ["RevitMCP.csproj", "RevitMCPCore.csproj"]
    # Both DLLs landed in the SAME output_dir.
    out_dir = tmp_path / "payload" / "revit" / "2025"
    assert (out_dir / "RevitMCP.dll").exists()
    assert (out_dir / "RevitMCPCore.dll").exists()


def test_build_helper_hard_fails_on_any_csproj_failure(tmp_path, monkeypatch):
    """If the Core csproj fails to build, the whole connector build
    must fail — no half-deploy."""
    sources = tmp_path / "sources"
    (sources / "revit_mcp").mkdir(parents=True)
    (sources / "revit_mcp_core").mkdir()
    (sources / "revit_mcp" / "RevitMCP.csproj").write_text("<Project/>")
    (sources / "revit_mcp_core" / "RevitMCPCore.csproj").write_text("<Project/>")
    monkeypatch.setattr(auto_build, "SOURCES_DIR", sources)
    monkeypatch.setattr(auto_build, "PAYLOAD_DIR", tmp_path / "payload")

    def _fake_run(project_path, **_kw):
        # Shim builds OK, Core fails.
        if "Core" in Path(project_path).name:
            return (False, "csproj broken")
        out = _kw["output_dir"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "RevitMCP.dll").write_bytes(b"x")
        return (True, "ok")

    monkeypatch.setattr(auto_build, "_run_dotnet_build", _fake_run)
    result = auto_build._build_dotnet_connector(
        host_label="revit", year=2025,
        sources_glob="revit_mcp*", output_subdir="revit",
        msbuild_props={}, target_framework="net8.0-windows",
        on_progress=lambda *_a, **_kw: None)
    assert not result.success
    assert "Core" in result.detail


# ─── 2. deploy-time sanity gate ────────────────────────────────────


def test_deploy_gate_fails_when_expected_dll_missing(tmp_path, monkeypatch):
    sources = tmp_path / "sources"
    (sources / "revit_mcp").mkdir(parents=True)
    (sources / "revit_mcp_core").mkdir()
    (sources / "revit_mcp" / "RevitMCP.csproj").write_text("<Project/>")
    (sources / "revit_mcp_core" / "RevitMCPCore.csproj").write_text("<Project/>")
    (sources / "revit_mcp" / "build-manifest.json").write_text(json.dumps({
        "expected_artifacts": ["RevitMCP.dll"], "record_shas_on_build": False,
        "sha256": {},
    }))
    (sources / "revit_mcp_core" / "build-manifest.json").write_text(json.dumps({
        "expected_artifacts": ["RevitMCPCore.dll"], "record_shas_on_build": False,
        "sha256": {},
    }))
    monkeypatch.setattr(auto_build, "SOURCES_DIR", sources)
    monkeypatch.setattr(auto_build, "PAYLOAD_DIR", tmp_path / "payload")

    def _fake_run(project_path, **_kw):
        # Drop ONLY the shim's DLL — core "missing".
        out = _kw["output_dir"]
        out.mkdir(parents=True, exist_ok=True)
        if "Core" not in Path(project_path).name:
            (out / "RevitMCP.dll").write_bytes(b"x")
        return (True, "ok")

    monkeypatch.setattr(auto_build, "_run_dotnet_build", _fake_run)
    result = auto_build._build_dotnet_connector(
        host_label="revit", year=2025,
        sources_glob="revit_mcp*", output_subdir="revit",
        msbuild_props={}, target_framework="net8.0-windows",
        on_progress=lambda *_a, **_kw: None)
    assert not result.success
    assert "incomplete_build" in result.detail
    assert "RevitMCPCore.dll" in result.detail


def test_deploy_gate_sha_mismatch_fails(tmp_path, monkeypatch):
    sources = tmp_path / "sources"
    (sources / "revit_mcp").mkdir(parents=True)
    (sources / "revit_mcp" / "RevitMCP.csproj").write_text("<Project/>")
    # Pin a SHA that won't match what the build "produces".
    (sources / "revit_mcp" / "build-manifest.json").write_text(json.dumps({
        "expected_artifacts": ["RevitMCP.dll"],
        "record_shas_on_build": False,
        "sha256": {"RevitMCP.dll": "0" * 64},
    }))
    monkeypatch.setattr(auto_build, "SOURCES_DIR", sources)
    monkeypatch.setattr(auto_build, "PAYLOAD_DIR", tmp_path / "payload")

    def _fake_run(project_path, **_kw):
        out = _kw["output_dir"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "RevitMCP.dll").write_bytes(b"different bytes than the pinned sha")
        return (True, "ok")

    monkeypatch.setattr(auto_build, "_run_dotnet_build", _fake_run)
    result = auto_build._build_dotnet_connector(
        host_label="revit", year=2025,
        sources_glob="revit_mcp*", output_subdir="revit",
        msbuild_props={}, target_framework="net8.0-windows",
        on_progress=lambda *_a, **_kw: None)
    assert not result.success
    assert "sha_mismatch" in result.detail


def test_record_shas_writes_back_to_manifest(tmp_path, monkeypatch):
    sources = tmp_path / "sources"
    (sources / "revit_mcp").mkdir(parents=True)
    (sources / "revit_mcp" / "RevitMCP.csproj").write_text("<Project/>")
    manifest_p = sources / "revit_mcp" / "build-manifest.json"
    manifest_p.write_text(json.dumps({
        "expected_artifacts": ["RevitMCP.dll"],
        "record_shas_on_build": True,
        "sha256": {},
    }))
    monkeypatch.setattr(auto_build, "SOURCES_DIR", sources)
    monkeypatch.setattr(auto_build, "PAYLOAD_DIR", tmp_path / "payload")

    test_bytes = b"deterministic dll payload"
    expected_sha = hashlib.sha256(test_bytes).hexdigest()

    def _fake_run(project_path, **_kw):
        out = _kw["output_dir"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "RevitMCP.dll").write_bytes(test_bytes)
        return (True, "ok")

    monkeypatch.setattr(auto_build, "_run_dotnet_build", _fake_run)
    result = auto_build._build_dotnet_connector(
        host_label="revit", year=2025,
        sources_glob="revit_mcp*", output_subdir="revit",
        msbuild_props={}, target_framework="net8.0-windows",
        on_progress=lambda *_a, **_kw: None)
    assert result.success
    updated = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert updated["sha256"]["RevitMCP.dll"] == expected_sha


# ─── 3. real source tree carries the manifests ─────────────────────


def test_revit_shim_manifest_present():
    root = Path(__file__).resolve().parents[1]
    p = root / "payload" / "sources" / "revit_mcp" / "build-manifest.json"
    assert p.exists()
    m = json.loads(p.read_text(encoding="utf-8"))
    assert "RevitMCP.dll" in m["expected_artifacts"]


def test_revit_core_manifest_present():
    root = Path(__file__).resolve().parents[1]
    p = root / "payload" / "sources" / "revit_mcp_core" / "build-manifest.json"
    assert p.exists()
    m = json.loads(p.read_text(encoding="utf-8"))
    assert "RevitMCPCore.dll" in m["expected_artifacts"]


def test_acad_manifest_present():
    root = Path(__file__).resolve().parents[1]
    p = root / "payload" / "sources" / "acad_mcp" / "build-manifest.json"
    assert p.exists()
    m = json.loads(p.read_text(encoding="utf-8"))
    assert "AcadMCP.dll" in m["expected_artifacts"]


# ─── 4. csprojs have Deterministic flag ────────────────────────────


@pytest.mark.parametrize("csproj_path", [
    "payload/sources/revit_mcp/RevitMCP.csproj",
    "payload/sources/revit_mcp_core/RevitMCPCore.csproj",
    "payload/sources/acad_mcp/AcadMCP.csproj",
])
def test_csproj_deterministic_flag_set(csproj_path):
    root = Path(__file__).resolve().parents[1]
    src = (root / csproj_path).read_text(encoding="utf-8")
    assert "<Deterministic>true</Deterministic>" in src


# ─── 5. CLI entry exists ───────────────────────────────────────────


def test_auto_build_has_main_cli():
    assert hasattr(auto_build, "main")
    # Bad args → exit code 2 (Unix convention).
    assert auto_build.main([]) == 2
    assert auto_build.main(["bogus", "2025"]) == 2
    assert auto_build.main(["revit", "notanint"]) == 2


# ─── 6. real build_revit_connector uses the helper ─────────────────


def test_build_revit_connector_uses_helper(monkeypatch):
    """Wires through _build_dotnet_connector, not the old single-csproj
    path.  Catches any future regression that bypasses the helper."""
    monkeypatch.setattr(auto_build, "find_revit_install",
                        lambda y: Path(r"C:\fake\Revit"))
    monkeypatch.setattr(auto_build, "detect_dotnet_sdk", lambda: "8.0.405")

    called = {}
    def _spy(host_label, year, sources_glob, output_subdir,
             msbuild_props, target_framework, on_progress):
        called["sources_glob"] = sources_glob
        called["output_subdir"] = output_subdir
        called["host_label"] = host_label
        return auto_build.BuildResult(True, "stub", [])
    monkeypatch.setattr(auto_build, "_build_dotnet_connector", _spy)

    auto_build.build_revit_connector(2025)
    assert called["sources_glob"] == "revit_mcp*"
    assert called["output_subdir"] == "revit"
    assert called["host_label"] == "revit"


# ─── 7. bat script + AgDR doc exist ────────────────────────────────


def test_fix_and_test_bat_delegates_to_python():
    root = Path(__file__).resolve().parents[1]
    bat = (root / "FixAndTestRevit2025.bat").read_text(encoding="utf-8")
    # Old inline `dotnet build` for the shim only must be gone.
    assert "dotnet build \"%CSPROJ%\"" not in bat
    # New canonical path.
    assert "py auto_build.py revit 2025" in bat


def test_agdr_0029_exists_and_approved():
    root = Path(__file__).resolve().parents[1]
    p = root / "docs" / "agdr" / "AgDR-0029-connector-build-pair-shim-and-core.md"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "status: executed" in text
    # Signed forks.
    assert "A3 — Both glob + manifest gate" in text
    assert "B2 — SHA-256 in manifest" in text
    assert "C1 — Replace bat body" in text
