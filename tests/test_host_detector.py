"""host_detector tests — v1.4.

The detector probes 10 hosts (lmstudio / antigravity / outlook / teams
/ word / excel / powerpoint / photoshop / illustrator / indesign).

These tests pin the shape returned by every probe and verify the
"missing" path works clean without any host actually running. No real
processes touched, no COM connections opened — everything's mocked.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture(autouse=True)
def _clear_host_cache():
    """Each test starts with a clean cache so probes re-run."""
    try:
        from host_detector import _CACHE
        _CACHE.clear()
    except Exception:
        pass
    yield
    try:
        from host_detector import _CACHE
        _CACHE.clear()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helpers — emulate the "nothing running, no COM available" scenario.
def _all_missing_mocks():
    """Returns a list of patches you `with` to simulate nothing live."""
    return [
        patch("host_detector._find_process", return_value=None),
        patch("host_detector._com_get_active",
               return_value=(None, "Operation unavailable")),
        patch("host_detector._tcp_open", return_value=False),
        patch.dict("os.environ", {}, clear=False),
    ]


def _shape_ok(result: dict, *, allowed_status=None) -> None:
    """Assert the canonical probe shape: status / version / note / detail."""
    assert isinstance(result, dict)
    assert "status" in result
    assert "version" in result
    assert "note" in result
    assert "detail" in result
    assert isinstance(result["version"], str)
    assert isinstance(result["note"], str)
    assert isinstance(result["detail"], dict)
    allowed = allowed_status or {"live", "missing", "unavailable"}
    assert result["status"] in allowed, \
        f"unexpected status {result['status']!r}, expected one of {allowed}"


# ---------------------------------------------------------------------------
class TestShape:
    """Pin the shape every probe returns."""

    @pytest.mark.parametrize("probe_name", [
        "probe_lmstudio", "probe_antigravity", "probe_outlook",
        "probe_teams", "probe_word", "probe_excel", "probe_powerpoint",
        "probe_photoshop", "probe_illustrator", "probe_indesign",
    ])
    def test_probe_returns_canonical_shape_when_nothing_running(
            self, probe_name):
        """With nothing live and no COM, every probe returns the
        canonical {status, version, note, detail} dict."""
        import host_detector
        host_detector._CACHE.clear()
        probe = getattr(host_detector, probe_name)
        with patch("host_detector._find_process", return_value=None), \
             patch("host_detector._com_get_active",
                    return_value=(None, "Operation unavailable")), \
             patch("host_detector._tcp_open", return_value=False), \
             patch("host_detector._http_json", return_value=None):
            r = probe()
        _shape_ok(r)

    @pytest.mark.parametrize("probe_name", [
        "probe_lmstudio", "probe_antigravity", "probe_outlook",
        "probe_teams", "probe_word", "probe_excel", "probe_powerpoint",
        "probe_photoshop", "probe_illustrator", "probe_indesign",
    ])
    def test_probe_never_crashes_on_pywin32_missing(self, probe_name):
        """Each probe survives pywin32 not being installed."""
        import host_detector
        host_detector._CACHE.clear()
        probe = getattr(host_detector, probe_name)
        with patch("host_detector._find_process", return_value=None), \
             patch("host_detector._com_get_active",
                    return_value=(None, "pywin32 not installed")), \
             patch("host_detector._tcp_open", return_value=False), \
             patch("host_detector._http_json", return_value=None):
            r = probe()
        _shape_ok(r)


# ---------------------------------------------------------------------------
class TestMissingPath:
    """Verify each probe correctly reports 'missing' when host is down."""

    def test_lmstudio_missing_when_port_closed(self):
        import host_detector
        host_detector._CACHE.clear()
        with patch("host_detector._tcp_open", return_value=False):
            r = host_detector.probe_lmstudio()
        assert r["status"] == "missing"
        assert "not running" in r["note"].lower()

    def test_antigravity_missing_when_process_absent(self):
        import host_detector
        host_detector._CACHE.clear()
        with patch("host_detector._find_process", return_value=None):
            r = host_detector.probe_antigravity()
        assert r["status"] == "missing"
        assert "not running" in r["note"].lower()

    def test_outlook_missing_when_no_com_and_no_process(self):
        import host_detector
        host_detector._CACHE.clear()
        with patch("host_detector._com_get_active",
                    return_value=(None, "Operation unavailable")), \
             patch("host_detector._find_process", return_value=None):
            r = host_detector.probe_outlook()
        assert r["status"] == "missing"

    def test_teams_missing_when_no_proc_no_graph(self, monkeypatch):
        import host_detector
        host_detector._CACHE.clear()
        monkeypatch.delenv("MS_GRAPH_TOKEN", raising=False)
        with patch("host_detector._find_process", return_value=None):
            r = host_detector.probe_teams()
        assert r["status"] == "missing"

    @pytest.mark.parametrize("probe_name,proc_needles", [
        ("probe_word",        ["winword"]),
        ("probe_excel",       ["excel"]),
        ("probe_powerpoint",  ["powerpnt"]),
        ("probe_photoshop",   ["photoshop"]),
        ("probe_illustrator", ["illustrator"]),
        ("probe_indesign",    ["indesign"]),
    ])
    def test_office_adobe_missing_path(self, probe_name, proc_needles):
        import host_detector
        host_detector._CACHE.clear()
        probe = getattr(host_detector, probe_name)
        with patch("host_detector._com_get_active",
                    return_value=(None, "Operation unavailable")), \
             patch("host_detector._find_process", return_value=None):
            r = probe()
        assert r["status"] == "missing"


# ---------------------------------------------------------------------------
class TestLivePath:
    """Probes flip to 'live' when their detection signal is present."""

    def test_outlook_live_via_com(self):
        import host_detector
        host_detector._CACHE.clear()

        class _FakeApp:
            Version = "16.0.0.1234"
        with patch("host_detector._com_get_active",
                    return_value=(_FakeApp(), "")):
            r = host_detector.probe_outlook()
        assert r["status"] == "live"
        assert r["version"] == "16.0.0.1234"

    def test_outlook_live_via_process_when_com_unavailable(self):
        """Process running but COM unreachable (e.g. New Outlook UWP)
        — we still report live."""
        import host_detector
        host_detector._CACHE.clear()
        with patch("host_detector._com_get_active",
                    return_value=(None, "Operation unavailable")), \
             patch("host_detector._find_process",
                    return_value={"name": "outlook.exe", "pid": 1234,
                                   "exe": "C:/outlook.exe"}):
            r = host_detector.probe_outlook()
        assert r["status"] == "live"

    def test_teams_live_via_process(self):
        import host_detector
        host_detector._CACHE.clear()
        with patch("host_detector._find_process",
                    return_value={"name": "ms-teams.exe", "pid": 5,
                                   "exe": ""}):
            r = host_detector.probe_teams()
        assert r["status"] == "live"

    def test_teams_live_via_graph_token_only(self, monkeypatch):
        import host_detector
        host_detector._CACHE.clear()
        monkeypatch.setenv("MS_GRAPH_TOKEN", "fake-token-123")
        with patch("host_detector._find_process", return_value=None):
            r = host_detector.probe_teams()
        assert r["status"] == "live"
        assert "graph" in r["note"].lower()

    def test_excel_live_via_com(self):
        import host_detector
        host_detector._CACHE.clear()

        class _FakeApp:
            Version = "16.0"
        with patch("host_detector._com_get_active",
                    return_value=(_FakeApp(), "")):
            r = host_detector.probe_excel()
        assert r["status"] == "live"
        assert r["version"] == "16.0"

    def test_lmstudio_live_when_port_open(self):
        import host_detector
        host_detector._CACHE.clear()
        fake = {"data": [{"id": "qwen3.6"}]}
        with patch("host_detector._tcp_open", return_value=True), \
             patch("host_detector._http_json", return_value=fake):
            r = host_detector.probe_lmstudio()
        assert r["status"] == "live"

    def test_antigravity_live_when_process_running(self):
        import host_detector
        host_detector._CACHE.clear()
        with patch("host_detector._find_process",
                    return_value={"name": "antigravity.exe", "pid": 99,
                                   "exe": ""}):
            r = host_detector.probe_antigravity()
        assert r["status"] == "live"


# ---------------------------------------------------------------------------
class TestUnavailablePath:
    """When pywin32 is missing AND no process matches, mark unavailable."""

    @pytest.mark.parametrize("probe_name", [
        "probe_word", "probe_excel", "probe_powerpoint",
        "probe_photoshop", "probe_illustrator", "probe_indesign",
    ])
    def test_unavailable_when_pywin32_missing_and_no_proc(self, probe_name):
        import host_detector
        host_detector._CACHE.clear()
        probe = getattr(host_detector, probe_name)
        with patch("host_detector._com_get_active",
                    return_value=(None, "pywin32 not installed")), \
             patch("host_detector._find_process", return_value=None):
            r = probe()
        assert r["status"] == "unavailable"


# ---------------------------------------------------------------------------
class TestCacheTTL:
    """Cache prevents redundant probes inside the 25s window."""

    def test_cache_hits_within_ttl(self):
        from host_detector import probe_antigravity, _CACHE
        _CACHE.clear()
        with patch("host_detector._find_process",
                    return_value=None) as mock_find:
            probe_antigravity()
            probe_antigravity()
            probe_antigravity()
        # Cached after first call.
        assert mock_find.call_count == 1
        assert "antigravity" in _CACHE

    def test_force_bypasses_cache(self):
        from host_detector import detect_all_hosts, _CACHE
        with patch("host_detector._find_process", return_value=None), \
             patch("host_detector._com_get_active",
                    return_value=(None, "no")), \
             patch("host_detector._tcp_open", return_value=False), \
             patch("host_detector._http_json", return_value=None):
            detect_all_hosts()
            assert len(_CACHE) > 0
            detect_all_hosts(force=True)
            # Cache was cleared mid-call; should be re-populated again.
            assert len(_CACHE) > 0


# ---------------------------------------------------------------------------
class TestDetectAllHosts:
    """Top-level aggregator returns a dict for every prober."""

    def test_returns_dict_for_every_host(self):
        from host_detector import detect_all_hosts, PROBERS, _CACHE
        _CACHE.clear()
        with patch("host_detector._find_process", return_value=None), \
             patch("host_detector._com_get_active",
                    return_value=(None, "Operation unavailable")), \
             patch("host_detector._tcp_open", return_value=False), \
             patch("host_detector._http_json", return_value=None):
            r = detect_all_hosts(force=True)
        # Every prober represented.
        for hid in PROBERS:
            assert hid in r, f"missing host {hid}"
            _shape_ok(r[hid])

    def test_live_hosts_helper_returns_subset(self):
        from host_detector import live_hosts, _CACHE
        _CACHE.clear()
        with patch("host_detector._find_process", return_value=None), \
             patch("host_detector._com_get_active",
                    return_value=(None, "no")), \
             patch("host_detector._tcp_open", return_value=False), \
             patch("host_detector._http_json", return_value=None):
            r = live_hosts()
        assert isinstance(r, list)
        assert r == []  # Nothing live with all-missing mocks.

    def test_detect_all_survives_bad_probe(self):
        """A probe that raises must NOT crash detect_all_hosts."""
        from host_detector import detect_all_hosts, _CACHE
        _CACHE.clear()
        # Force one probe to crash by stubbing _find_process to raise.
        # Other probes that use _com_get_active will still succeed.
        with patch("host_detector._find_process",
                    side_effect=RuntimeError("boom")), \
             patch("host_detector._com_get_active",
                    return_value=(None, "no")), \
             patch("host_detector._tcp_open", return_value=False), \
             patch("host_detector._http_json", return_value=None):
            r = detect_all_hosts(force=True)
        # Should still have entries for every host.
        assert len(r) == 10
        for hid, info in r.items():
            _shape_ok(info)


# ---------------------------------------------------------------------------
class TestDisplayLabel:
    def test_known_hosts_have_short_names(self):
        from host_detector import display_label
        assert display_label("outlook") == "Outlook"
        assert display_label("teams") == "Microsoft Teams"
        assert display_label("lmstudio") == "LM Studio"
        assert display_label("photoshop") == "Photoshop"

    def test_unknown_host_title_cased(self):
        from host_detector import display_label
        assert display_label("unknown_app") == "Unknown_App"


# ---------------------------------------------------------------------------
class TestBridgeIntegration:
    """The bridge slot get_all_hosts should JSON-encode the detector
    output cleanly."""

    def test_get_all_hosts_returns_valid_json(self):
        import json
        from host_detector import detect_all_hosts, _CACHE
        _CACHE.clear()
        with patch("host_detector._find_process", return_value=None), \
             patch("host_detector._com_get_active",
                    return_value=(None, "no")), \
             patch("host_detector._tcp_open", return_value=False), \
             patch("host_detector._http_json", return_value=None):
            data = detect_all_hosts(force=True)
        # Round-trip through json — what the bridge does.
        encoded = json.dumps(data, default=str)
        decoded = json.loads(encoded)
        assert isinstance(decoded, dict)
        for hid, info in decoded.items():
            _shape_ok(info)
