"""APP-10 — AutoCAD meta-connector returns a TYPED result, never raises.

origin/main: `generate_acad_plugin` was a one-line stub —
    raise NotImplementedError("AutoCAD meta-connector contract pending.")
so the "one master connector per host" promise threw for AutoCAD while the
Revit path shipped.

The fix implements `generate_acad_plugin` as a real LLM-driven generator
mirroring `generate_revit_addin` (real AutoCAD connector contract, validated,
content-hash cached) AND degrades honestly: when generation genuinely can't
proceed (no router / empty model output / validation failure) it returns a
typed `UnavailableConnector` — never an exception.

These tests go RED on origin/main (NotImplementedError) and GREEN with the
fix. The cache dir is redirected to a tmp path so the tests are hermetic.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import meta_connector  # noqa: E402
from meta_connector import (  # noqa: E402
    generate_acad_plugin,
    GeneratedSource,
)


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    """Redirect the generated-source cache to a tmp dir so tests don't
    write into the repo's payload/_generated/."""
    monkeypatch.setattr(meta_connector, "_cache_dir", lambda: tmp_path)
    return tmp_path


class _Resp:
    def __init__(self, text, model="fake-model"):
        self.text = text
        self.model = model


class _FakeRouter:
    """Stand-in for LLMRouter — returns a scripted completion text."""

    def __init__(self, text):
        self._text = text
        self.calls = 0

    def complete(self, history, model, on_chunk, on_tool_invocation):
        self.calls += 1
        return _Resp(self._text)


_VALID_PLUGIN = """\
### FILE: ArchHubAcad.csproj
<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>
<TargetFramework>net8.0-windows</TargetFramework></PropertyGroup></Project>
### FILE: Connector.cs
using Autodesk.AutoCAD.Runtime;
using System.Net;
[assembly: ExtensionApplication(typeof(ArchHub.Connector))]
namespace ArchHub {
  public class Connector : IExtensionApplication {
    HttpListener _listener;
    public void Initialize() {
      // bind http://localhost:48885/ and walk forward to 48899
      _listener = new HttpListener();
      _listener.Prefixes.Add("http://localhost:48885/");
      _listener.Start();
    }
    public void Terminate() { _listener?.Stop(); }
  }
}
"""


# ─── the core gate: never NotImplementedError ────────────────────────


def test_acad_no_router_returns_typed_unavailable_not_raise():
    """The exact origin/main failure: this used to raise
    NotImplementedError. Now it returns a typed UnavailableConnector."""
    result = generate_acad_plugin("2025", None)   # no router
    # Did NOT raise — and the result is the honest typed unavailable.
    assert result.ok is False
    assert result.reason == "no_router"
    assert result.host == "acad"
    assert result.version == "2025"
    assert result.detail                       # plain-English explanation
    assert result.fallback                     # names the offline source dir


def test_acad_never_raises_notimplemented_for_any_year():
    """No supported AutoCAD year throws — the whole point of APP-10."""
    for year in ("2024", "2025", "2026"):
        try:
            r = generate_acad_plugin(year, None)
        except NotImplementedError:                # pragma: no cover
            pytest.fail(f"generate_acad_plugin({year}) raised "
                        f"NotImplementedError — the APP-10 stub is back")
        assert r.ok is False                       # no router → unavailable
        assert r.reason == "no_router"


# ─── real generation path ────────────────────────────────────────────


def test_acad_valid_generation_returns_source():
    """A model that emits a contract-compliant plug-in yields a real
    GeneratedSource with the .cs + .csproj files."""
    router = _FakeRouter(_VALID_PLUGIN)
    r = generate_acad_plugin("2025", router, force_regenerate=True)
    assert isinstance(r, GeneratedSource)
    assert r.host == "acad"
    assert r.version == "2025"
    assert any(p.endswith(".cs") for p in r.files)
    assert any(p.endswith(".csproj") for p in r.files)
    assert r.cache_path is not None
    assert router.calls == 1


def test_acad_generation_is_cached():
    """A second (non-forced) call hits the cache — no router needed."""
    router = _FakeRouter(_VALID_PLUGIN)
    first = generate_acad_plugin("2025", router, force_regenerate=True)
    assert isinstance(first, GeneratedSource)
    # Now WITHOUT a router and without force — must come from cache.
    second = generate_acad_plugin("2025", None)
    assert isinstance(second, GeneratedSource)
    assert second.model == "cached"
    assert second.files.keys() == first.files.keys()


# ─── honest-degrade paths (still no raise) ───────────────────────────


def test_acad_empty_generation_is_typed_unavailable():
    """Model returns prose with no `### FILE:` headers → typed unavailable."""
    r = generate_acad_plugin("2024",
                             _FakeRouter("Sorry, I can't do that."),
                             force_regenerate=True)
    assert r.ok is False
    assert r.reason == "empty_generation"
    assert r.fallback


def test_acad_validation_failure_is_typed_unavailable():
    """Files present but missing the AutoCAD contract tokens
    (IExtensionApplication / HttpListener / 48885) → typed unavailable,
    not a raise and not a falsely-successful GeneratedSource."""
    bad = ("### FILE: X.csproj\n<Project/>\n"
           "### FILE: X.cs\npublic class Nope {}\n")
    r = generate_acad_plugin("2026", _FakeRouter(bad), force_regenerate=True)
    assert r.ok is False
    assert r.reason == "validation_failed"
    assert "contract" in r.detail.lower()


def test_acad_contract_targets_correct_dotnet_per_year():
    """The contract pins net48 for <=2024 and net8 for >=2025 (it's the
    runtime AutoCAD loads). The version is interpolated into the prompt."""
    # 2024 prompt embeds the version; the contract body names both targets.
    assert "net48" in meta_connector.CONNECTOR_CONTRACT_ACAD
    assert "net8.0-windows" in meta_connector.CONNECTOR_CONTRACT_ACAD
    assert "IExtensionApplication" in meta_connector.CONNECTOR_CONTRACT_ACAD
    assert "48885" in meta_connector.CONNECTOR_CONTRACT_ACAD
