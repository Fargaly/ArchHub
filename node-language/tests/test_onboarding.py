"""First-run onboarding tests.

Covers:
  * first_run gating — needs_onboarding flips False when ANY of:
      (a) first_run_complete flag set
      (b) a provider API key is present
      (c) Ollama is reachable on :11434
  * mark_complete / reset roundtrip
  * ollama_installer.detect three-state probe
  * OnboardingDialog instantiates without spinning up Qt event loop
  * Vocabulary check — no "Ollama" / "API key" / "model" in the
    visible Stage labels surfaced to the user
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    import sys as _sys
    return QApplication.instance() or QApplication(_sys.argv)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    # Redirect LOCALAPPDATA so we never touch the user's real
    # secrets_store. first_run reads its flag through secrets_store.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


# ---------------------------------------------------------------------------
class TestFirstRunGating:
    def _stub_provider_keys(self, monkeypatch, present: list[str]):
        import first_run as fr
        def fake_load(p):
            return "sk-stub" if p in present else None
        monkeypatch.setattr(
            "secrets_store.load_api_key", fake_load, raising=False,
        )

    def _stub_ollama(self, monkeypatch, reachable: bool):
        import first_run as fr
        monkeypatch.setattr(fr, "_ollama_reachable", lambda: reachable)

    def _stub_flag(self, monkeypatch, flag: bool):
        import first_run as fr
        monkeypatch.setattr(fr, "_flag", lambda key: flag)

    def test_needs_onboarding_when_nothing_configured(self, monkeypatch):
        self._stub_flag(monkeypatch, False)
        self._stub_provider_keys(monkeypatch, [])
        self._stub_ollama(monkeypatch, False)
        from first_run import needs_onboarding
        assert needs_onboarding() is True

    def test_skipped_when_api_key_set(self, monkeypatch):
        self._stub_flag(monkeypatch, False)
        self._stub_provider_keys(monkeypatch, ["anthropic"])
        self._stub_ollama(monkeypatch, False)
        from first_run import needs_onboarding
        assert needs_onboarding() is False

    def test_skipped_when_ollama_running(self, monkeypatch):
        self._stub_flag(monkeypatch, False)
        self._stub_provider_keys(monkeypatch, [])
        self._stub_ollama(monkeypatch, True)
        from first_run import needs_onboarding
        assert needs_onboarding() is False

    def test_skipped_when_flag_set(self, monkeypatch):
        self._stub_flag(monkeypatch, True)
        self._stub_provider_keys(monkeypatch, [])
        self._stub_ollama(monkeypatch, False)
        from first_run import needs_onboarding
        assert needs_onboarding() is False

    def test_mark_complete_then_reset(self):
        from first_run import mark_complete, reset
        from secrets_store import load_setting
        mark_complete()
        assert bool(load_setting("first_run_complete")) is True
        reset()
        assert bool(load_setting("first_run_complete")) is False


# ---------------------------------------------------------------------------
class TestOllamaDetect:
    def test_returns_running_when_port_open(self, monkeypatch):
        import ollama_installer as oi
        monkeypatch.setattr(oi, "_is_running", lambda: True)
        assert oi.detect() == "running"

    def test_returns_installed_not_running_when_exe_present(self, monkeypatch):
        import ollama_installer as oi
        monkeypatch.setattr(oi, "_is_running", lambda: False)
        monkeypatch.setattr(oi, "_is_installed_not_running", lambda: True)
        assert oi.detect() == "installed_not_running"

    def test_returns_absent_when_nothing(self, monkeypatch):
        import ollama_installer as oi
        monkeypatch.setattr(oi, "_is_running", lambda: False)
        monkeypatch.setattr(oi, "_is_installed_not_running", lambda: False)
        assert oi.detect() == "absent"


# ---------------------------------------------------------------------------
class TestVocabulary:
    """Surface labels the user sees must not contain jargon."""

    JARGON = ("ollama", "api key", "endpoint", "daemon", "service "
                                                          "url", "json")

    def test_stage_labels_are_plain_english(self):
        from onboarding_dialog import _STAGE_LABEL
        for stage, label in _STAGE_LABEL.items():
            lo = label.lower()
            for forbidden in self.JARGON:
                assert forbidden not in lo, (
                    f"Stage label for {stage!r} contains jargon: "
                    f"{label!r} (matched {forbidden!r})"
                )

    def test_dialog_subtitle_avoids_ollama(self, qapp):
        from onboarding_dialog import OnboardingDialog
        from PyQt6.QtWidgets import QLabel
        dlg = OnboardingDialog()
        try:
            texts = [lab.text().lower() for lab in dlg.findChildren(QLabel)]
            joined = " ".join(texts)
            assert "ollama" not in joined
            assert "api key" not in joined
        finally:
            dlg.deleteLater()


# ---------------------------------------------------------------------------
class TestDialogAssembly:
    def test_instantiates_without_running_event_loop(self, qapp):
        from onboarding_dialog import OnboardingDialog
        dlg = OnboardingDialog()
        # Setup button, ghost buttons, progress frame all exist.
        assert dlg.btn_setup is not None
        assert dlg.btn_have_account is not None
        assert dlg.btn_skip is not None
        assert dlg.progress_frame is not None
        # Progress hidden until user clicks setup.
        assert dlg.progress_frame.isVisible() is False
        dlg.deleteLater()

    def test_primary_button_label_promises_setup(self, qapp):
        from onboarding_dialog import OnboardingDialog
        dlg = OnboardingDialog()
        try:
            assert "set up" in dlg.btn_setup.text().lower()
            assert "ai" in dlg.btn_setup.text().lower()
        finally:
            dlg.deleteLater()
