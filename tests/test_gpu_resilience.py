"""GPU-RESILIENCE — the app must NEVER be left blank, on ANY machine.

Root cause this suite pins (founder: "the app wedges on GPU under real load"):

  • app/main.py forced hardware-GPU Chromium flags on every machine and the ONLY
    software fallback was the ARCHHUB_VERIFY_NO_GPU *debug* toggle — there was no
    production self-heal, so a machine whose GPU wedges / composites to software
    rendered a blank canvas with no recovery.
  • app/web_shell.py did a bare ``setUrl`` with NO ``renderProcessTerminated`` and
    NO ``loadFinished(False)`` handler — when the renderer (GPU compositor)
    crashed or the page failed to load, the QWebEngineView went white and stayed
    white.

The real fix (the thing this test gates):

  1. A PER-MACHINE persisted ``use_software_render`` marker is the REAL mechanism
     (replacing the env-var band-aid). When present, boot appends ``--disable-gpu``
     so the canvas composites on the CPU and renders instead of going blank. GPU
     stays the default for machines that work.
  2. web_shell connects ``renderProcessTerminated`` -> reload ONCE; a second crash
     within ~8s -> persist the marker + relaunch on software.
  3. web_shell connects ``loadFinished(False)`` -> reload ONCE.

RED on origin/main (none of the helpers / handlers exist there); GREEN on the
GPU-RESILIENCE branch. Proven RED->GREEN via ``git stash`` — see the PR body.

These are machine-checkable gates (ROMA rule 2): they run against the REAL
``main`` helpers and a REAL ``WebShell`` (constructed offscreen), not a mock of
the code under test. ``LOCALAPPDATA`` is isolated per-test by the suite conftest,
so the marker file lands in a throwaway dir and never touches the dev machine.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


# ──────────────────────────────────────────────────────────────────────────
# (1) marker set -> --disable-gpu applied  (the REAL mechanism in app/main.py)
# ──────────────────────────────────────────────────────────────────────────
class TestSoftwareRenderMarker:
    def _fresh_flags(self, monkeypatch):
        """Reset the Chromium flag env to the production GPU set so each test
        observes the append in isolation."""
        monkeypatch.setenv(
            "QTWEBENGINE_CHROMIUM_FLAGS",
            "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-zero-copy",
        )
        monkeypatch.delenv("ARCHHUB_FORCE_SOFTWARE_RENDER", raising=False)
        monkeypatch.delenv("ARCHHUB_VERIFY_NO_GPU", raising=False)

    def test_helpers_exist(self):
        """The real mechanism must be present (RED on main: AttributeError)."""
        import main
        for name in ("software_render_marker_path", "software_render_enabled",
                     "persist_software_render_marker", "_apply_software_render_marker"):
            assert hasattr(main, name), f"main.{name} missing — env-var band-aid not replaced"

    def test_no_marker_means_gpu_default(self, monkeypatch):
        """A machine that never failed has no marker -> GPU stays the default,
        the production flag string is byte-for-byte unchanged."""
        import main
        self._fresh_flags(monkeypatch)
        assert main.software_render_enabled() is False
        before = os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]
        main._apply_software_render_marker()
        assert os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] == before
        assert "--disable-gpu" not in os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]

    def test_marker_set_applies_disable_gpu(self, monkeypatch):
        """THE core gate: marker present -> --disable-gpu applied at boot."""
        import main
        self._fresh_flags(monkeypatch)
        # Persist the per-machine marker (isolated LOCALAPPDATA via conftest).
        assert main.persist_software_render_marker(reason="test") is True
        assert main.software_render_marker_path().exists()
        assert main.software_render_enabled() is True

        main._apply_software_render_marker()
        flags = os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]
        assert "--disable-gpu" in flags, "marker must cause --disable-gpu to be applied"
        # Existing GPU flags are preserved (additive, not a replacement of the str).
        assert "--ignore-gpu-blocklist" in flags

    def test_apply_is_idempotent(self, monkeypatch):
        """Re-applying never duplicates the flag (Chromium parses it once but we
        must not corrupt the string across the verify-toggle + marker paths)."""
        import main
        self._fresh_flags(monkeypatch)
        main.persist_software_render_marker(reason="test")
        main._apply_software_render_marker()
        main._apply_software_render_marker()
        assert os.environ["QTWEBENGINE_CHROMIUM_FLAGS"].count("--disable-gpu") == 1

    def test_force_env_enables_without_file(self, monkeypatch):
        """ARCHHUB_FORCE_SOFTWARE_RENDER pins software for THIS launch even with
        no marker file — used by web_shell's relaunch child."""
        import main
        self._fresh_flags(monkeypatch)
        assert main.software_render_enabled() is False
        monkeypatch.setenv("ARCHHUB_FORCE_SOFTWARE_RENDER", "1")
        assert main.software_render_enabled() is True
        main._apply_software_render_marker()
        assert "--disable-gpu" in os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]

    def test_marker_path_tracks_localappdata(self, monkeypatch):
        """The marker is per-machine config under %LOCALAPPDATA%/ArchHub — the
        same root secrets_store + logging use — so it survives launches."""
        import main
        p = main.software_render_marker_path()
        assert p.name == "use_software_render"
        assert p.parent.name == "ArchHub"
        # conftest set LOCALAPPDATA to the per-test tmp dir.
        assert str(p).startswith(os.environ["LOCALAPPDATA"])


# ──────────────────────────────────────────────────────────────────────────
# (1b) AUTO-RECOVERY — a software-render pin is NOT permanent.
# Founder 2026-06-19 "returned to be slow again": 2 TRANSIENT GPU crashes pinned
# software render forever (the marker had no expiry) -> the machine was stuck
# slow. The pin must expire after a backoff (growing with consecutive failures)
# and retry GPU; a genuinely broken GPU re-pins on its next crash.
# RED on the permanent-marker version: an aged marker still returns True.
# ──────────────────────────────────────────────────────────────────────────
class TestSoftwareRenderAutoRecovery:
    def _fresh(self, monkeypatch):
        monkeypatch.delenv("ARCHHUB_FORCE_SOFTWARE_RENDER", raising=False)
        monkeypatch.delenv("ARCHHUB_VERIFY_NO_GPU", raising=False)

    def test_fresh_marker_within_cooldown_pins(self, monkeypatch):
        """A just-written marker is within its backoff window -> still pinned."""
        import main
        self._fresh(monkeypatch)
        assert main.persist_software_render_marker(reason="transient") is True
        assert main.software_render_enabled() is True

    def test_expired_marker_retries_gpu_and_clears(self, monkeypatch):
        """A marker older than its backoff -> enabled() False (retry GPU) AND the
        marker is cleared so the retry is clean."""
        import json
        import time
        import main
        self._fresh(monkeypatch)
        main.persist_software_render_marker(reason="transient")   # fails=1 -> 1h
        p = main.software_render_marker_path()
        d = json.loads(p.read_text(encoding="utf-8"))
        d["ts"] = time.time() - (2 * 3600)                        # 2h ago > 1h
        p.write_text(json.dumps(d), encoding="utf-8")
        assert main.software_render_enabled() is False, "expired pin must retry GPU"
        assert not p.exists(), "expired marker must be cleared for a clean GPU retry"

    def test_consecutive_failures_increment_and_back_off(self, monkeypatch):
        """Repeated crashes increment the fail count -> longer backoff (a truly
        broken GPU isn't retried constantly / blank-flashing)."""
        import json
        import time
        import main
        self._fresh(monkeypatch)
        main.persist_software_render_marker(reason="c1")
        main.persist_software_render_marker(reason="c2")
        main.persist_software_render_marker(reason="c3")
        d = json.loads(main.software_render_marker_path().read_text(encoding="utf-8"))
        assert d["fails"] == 3, "consecutive pins must increment the failure count"
        d["ts"] = time.time() - (2 * 3600)                        # 2h < 24h (fails=3)
        main.software_render_marker_path().write_text(json.dumps(d), encoding="utf-8")
        assert main.software_render_enabled() is True, "high-fail pin holds through a short age"

    def test_legacy_plaintext_marker_auto_recovers(self, monkeypatch):
        """An old plain-text marker (pre-recovery) is treated as one failure dated
        by mtime and also auto-recovers once its window elapses."""
        import os as _os
        import time
        import main
        self._fresh(monkeypatch)
        p = main.software_render_marker_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("software-render pinned on 2026-06-19\nreason: legacy\n", encoding="utf-8")
        old = time.time() - (2 * 3600)
        _os.utime(p, (old, old))
        assert main.software_render_enabled() is False, "old legacy marker must auto-recover"


# ──────────────────────────────────────────────────────────────────────────
# WebShell crash-recovery handler LOGIC  (real handler methods, no render proc)
#
# These call the ACTUAL WebShell handler methods. The instance is built with
# ``__new__`` (so __init__ does NOT spin up a real QtWebEngine render process,
# which segfaults at interpreter exit in-process — the suite's standing reason
# WebEngine is otherwise only exercised via a subprocess, see
# tests/test_ui_cdp_smoke.py). The methods under test only touch counter
# attributes + ``self.view.reload()`` / a relaunch, so a stub view captures all
# observable behaviour deterministically — a real renderer crash is not
# reproducible in CI. The fact that these handlers are actually CONNECTED to the
# live page's signals is proven separately by TestWebShellSignalsWired below,
# which constructs the real WebShell in a subprocess.
# ──────────────────────────────────────────────────────────────────────────
def _webengine_available() -> bool:
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        return True
    except Exception:
        return False


requires_webengine = pytest.mark.skipif(
    not _webengine_available(), reason="PyQt6-WebEngine not available")


class _StubView:
    """Records reload() calls so handler behaviour is deterministic without
    relying on a real (non-reproducible) renderer crash in CI."""
    def __init__(self):
        self.reload_calls = 0

    def reload(self):
        self.reload_calls += 1


def _make_shell():
    """A WebShell instance whose REAL handler methods are bound, without
    constructing the QtWebEngine render process. Counter attributes are
    initialised exactly as the real ``__init__`` does."""
    from web_shell import WebShell
    shell = WebShell.__new__(WebShell)
    shell.view = _StubView()
    shell._render_crash_count = 0
    shell._first_crash_ts = 0.0
    shell._load_fail_reloaded = False
    shell._gpu_recovery_done = False
    shell._html_path = Path("index.html")
    return shell


@requires_webengine
class TestRenderProcessTerminatedHandler:
    def test_handler_method_exists(self):
        """RED on main: WebShell has no _on_render_process_terminated."""
        from web_shell import WebShell
        assert hasattr(WebShell, "_on_render_process_terminated")

    def test_first_crash_reloads_once(self):
        """First abnormal crash -> reload exactly once (no escalation yet)."""
        from PyQt6.QtWebEngineCore import QWebEnginePage
        shell = _make_shell()
        shell._on_render_process_terminated(
            QWebEnginePage.RenderProcessTerminationStatus.CrashedTerminationStatus, 159)
        assert shell.view.reload_calls == 1
        assert shell._gpu_recovery_done is False  # not escalated on 1st crash

    def test_normal_termination_ignored(self):
        """A clean shutdown (NormalTerminationStatus) is NOT a crash — no reload,
        no marker, no escalation (avoid false-positive software pinning)."""
        from PyQt6.QtWebEngineCore import QWebEnginePage
        shell = _make_shell()
        shell._on_render_process_terminated(
            QWebEnginePage.RenderProcessTerminationStatus.NormalTerminationStatus, 0)
        assert shell.view.reload_calls == 0
        assert shell._render_crash_count == 0

    def test_second_fast_crash_pins_software_and_relaunches(self, monkeypatch):
        """Two crashes within ~8s -> persist software marker + relaunch on
        software, instead of crash-looping on the bad GPU."""
        import main
        from PyQt6.QtWebEngineCore import QWebEnginePage
        shell = _make_shell()

        relaunched = {"called": False}
        import subprocess
        monkeypatch.setattr(subprocess, "Popen",
                            lambda *a, **k: relaunched.__setitem__("called", True))
        from PyQt6.QtWidgets import QApplication
        monkeypatch.setattr(QApplication, "quit", lambda self: None, raising=False)

        crashed = QWebEnginePage.RenderProcessTerminationStatus.CrashedTerminationStatus
        shell._on_render_process_terminated(crashed, 159)   # 1st -> reload
        shell._on_render_process_terminated(crashed, 159)   # 2nd fast -> escalate

        assert shell.view.reload_calls == 1, "2nd fast crash should escalate, not reload again"
        assert shell._gpu_recovery_done is True
        assert main.software_render_marker_path().exists(), \
            "second fast crash must persist the per-machine software marker"
        assert relaunched["called"] is True, "must relaunch on software render"

    def test_slow_second_crash_does_not_pin(self, monkeypatch):
        """A second crash LONG after the first (outside the ~8s window) is not
        treated as a wedged GPU — it reloads again rather than pinning software,
        so a single bad page much later doesn't strand a healthy GPU machine."""
        import main, time
        from PyQt6.QtWebEngineCore import QWebEnginePage
        shell = _make_shell()
        crashed = QWebEnginePage.RenderProcessTerminationStatus.CrashedTerminationStatus
        shell._on_render_process_terminated(crashed, 159)   # 1st -> reload
        shell._first_crash_ts = time.monotonic() - 60.0      # pretend long ago
        shell._on_render_process_terminated(crashed, 159)   # slow 2nd -> reload, no pin
        assert shell.view.reload_calls == 2
        assert shell._gpu_recovery_done is False
        assert not main.software_render_marker_path().exists()


@requires_webengine
class TestLoadFinishedHandler:
    def test_handler_method_exists(self):
        """RED on main: WebShell has no _on_load_finished."""
        from web_shell import WebShell
        assert hasattr(WebShell, "_on_load_finished")

    def test_load_failure_reloads_once(self):
        """loadFinished(False) -> reload exactly once; a second failure does NOT
        reload again (no infinite reload loop on a page that can't load)."""
        shell = _make_shell()
        shell._on_load_finished(False)
        assert shell.view.reload_calls == 1
        shell._on_load_finished(False)
        assert shell.view.reload_calls == 1, "must not loop on repeated load failure"

    def test_healthy_load_resets_retry(self):
        """A healthy load (ok=True) resets the one-shot guard so a LATER,
        unrelated failure gets its own fresh single retry."""
        shell = _make_shell()
        shell._on_load_finished(False)      # fail -> reload (1)
        shell._on_load_finished(True)       # heal -> reset guard
        assert shell._load_fail_reloaded is False
        shell._on_load_finished(False)      # later fail -> reload again (2)
        assert shell.view.reload_calls == 2

    def test_healthy_load_resets_crash_counters(self):
        """A healthy load also clears the render-crash counters so a recovered
        surface doesn't carry a stale crash count into a future incident."""
        shell = _make_shell()
        shell._render_crash_count = 1
        shell._first_crash_ts = 123.0
        shell._on_load_finished(True)
        assert shell._render_crash_count == 0
        assert shell._first_crash_ts == 0.0


# ──────────────────────────────────────────────────────────────────────────
# WebShell signals ARE wired on the live page  (real construction, subprocess)
#
# Proves the handlers are actually CONNECTED to the real QWebEnginePage signals
# (not merely defined). Construction happens in a SUBPROCESS that prints the
# signal receiver counts then ``os._exit(0)`` — the standard suite pattern for
# touching a real QtWebEngine render process without the in-process at-exit
# segfault. RED on main: the subprocess prints receiver counts of 0 and never
# emits RESILIENCE_WIRED_OK.
# ──────────────────────────────────────────────────────────────────────────
_WIRED_SUBPROCESS = r'''
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("ARCHHUB_NO_SELF_HEAL", "1")
os.environ.setdefault("ARCHHUB_MEMORY_STANDALONE", "1")
sys.path.insert(0, APP_ROOT)
from unittest.mock import MagicMock
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget
from PyQt6.QtCore import QCoreApplication, Qt
app = QApplication.instance() or QApplication(sys.argv)
try:
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
except Exception:
    pass
# Neutralise only the unrelated brain boot-thread (it races teardown); the
# GPU-resilience wiring under test is untouched.
import bridge as _b
_Real = _b.ArchHubBridge
class _Quiet(_Real):
    def __init__(self, *a, **k):
        k.setdefault("defer_boot", False)
        k.setdefault("auto_extract_memory", False)
        super().__init__(*a, **k)
_b.ArchHubBridge = _Quiet
cw = QMainWindow(); cw.setCentralWidget(QWidget())
from web_shell import WebShell
sh = WebShell(chat_widget=cw, router=MagicMock(), manager=MagicMock(), tools=MagicMock())
pg = sh.view.page()
rpt = pg.receivers(pg.renderProcessTerminated)
lf = pg.receivers(pg.loadFinished)
print("RPT_RECEIVERS=%d" % rpt)
print("LF_RECEIVERS=%d" % lf)
if (rpt >= 1 and lf >= 1
        and hasattr(sh, "_on_render_process_terminated")
        and hasattr(sh, "_on_load_finished")):
    print("RESILIENCE_WIRED_OK")
sys.stdout.flush()
os._exit(0)
'''


@requires_webengine
class TestWebShellSignalsWired:
    def test_render_and_load_signals_connected_on_real_shell(self, tmp_path):
        """(2)+(3): construct the REAL WebShell and prove both signals have a
        receiver. RED on main: receiver counts are 0, no RESILIENCE_WIRED_OK."""
        import subprocess
        script = ('APP_ROOT = %r\n' % str(APP_ROOT)) + _WIRED_SUBPROCESS
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["LOCALAPPDATA"] = str(tmp_path)
        env["APPDATA"] = str(tmp_path)
        env.setdefault("ARCHHUB_NO_SELF_HEAL", "1")
        # Carry the PARENT interpreter's full import path to the child so it
        # resolves the EXACT same PyQt6 (incl. user site-packages). A bare
        # ``python -c`` spawned from inside pytest can otherwise miss user
        # site-packages and pick up a namespace PyQt6 whose Qt DLLs won't load.
        env["PYTHONPATH"] = os.pathsep.join([str(APP_ROOT)] + sys.path)
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=180, env=env,
        )
        out = proc.stdout
        assert "RESILIENCE_WIRED_OK" in out, (
            "real WebShell did not wire renderProcessTerminated + loadFinished.\n"
            f"stdout:\n{out}\nstderr tail:\n{proc.stderr[-1500:]}"
        )
        # Belt-and-braces: explicit non-zero receiver counts.
        assert "RPT_RECEIVERS=0" not in out, "renderProcessTerminated has no receiver"
        assert "LF_RECEIVERS=0" not in out, "loadFinished has no receiver"
