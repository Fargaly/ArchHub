"""Courts for the explicit, non-persistent BABOOM voice input adapter."""
from __future__ import annotations

import threading
import types

import pytest

from nodelang.baboom_native_voice import (
    BaboomVoiceCancelled,
    BaboomVoiceInput,
    BaboomVoiceTimeout,
    _WindowsSapiDictationBackend,
)


class _Backend:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def capture_once(self, *, cancel: threading.Event, timeout_seconds: float) -> str:
        self.calls += 1
        assert timeout_seconds == 20.0
        assert not cancel.is_set()
        return self.text


def test_voice_input_captures_one_explicit_utterance_and_retains_no_audio():
    backend = _Backend("  BABOOM,   brief me on ArchHub  ")
    voice = BaboomVoiceInput(backend_factory=lambda: backend)

    assert voice.capture_once(cancel=threading.Event()) == "BABOOM, brief me on ArchHub"
    assert backend.calls == 1


def test_voice_input_refuses_a_cancelled_capture_before_opening_the_backend():
    backend = _Backend("This must not be read")
    voice = BaboomVoiceInput(backend_factory=lambda: backend)
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(BaboomVoiceCancelled):
        voice.capture_once(cancel=cancel)

    assert backend.calls == 0


def test_voice_input_rejects_empty_recognition():
    voice = BaboomVoiceInput(backend_factory=lambda: _Backend("   "))

    with pytest.raises(BaboomVoiceTimeout):
        voice.capture_once(cancel=threading.Event())


def test_windows_sapi_backend_deactivates_dictation_after_one_callback(monkeypatch):
    class Grammar:
        def __init__(self) -> None:
            self.states: list[int] = []

        def DictationLoad(self) -> None:  # noqa: N802 - SAPI automation name
            return None

        def DictationSetState(self, state: int) -> None:  # noqa: N802
            self.states.append(state)

    class Result:
        class PhraseInfo:  # noqa: D106 - small COM-shaped fake
            @staticmethod
            def GetText() -> str:  # noqa: N802
                return "  review the Workshop plan  "

    class Context:
        def __init__(self, handler) -> None:
            self._handler = handler
            self.grammar = Grammar()

        @property
        def text(self) -> str:
            return self._handler.text

        def CreateGrammar(self):  # noqa: N802
            return self.grammar

    state: dict[str, object] = {}

    def dispatch_with_events(_progid, handler_type):
        handler = handler_type()
        context = Context(handler)
        state["context"] = context
        return context

    def pump_messages() -> None:
        context = state["context"]
        context._handler.OnRecognition(0, 0, 0, Result())

    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: state.setdefault("initialized", True)
    pythoncom.CoUninitialize = lambda: state.setdefault("uninitialized", True)
    pythoncom.PumpWaitingMessages = pump_messages
    client = types.ModuleType("win32com.client")
    client.DispatchWithEvents = dispatch_with_events
    win32com = types.ModuleType("win32com")
    win32com.client = client
    monkeypatch.setitem(__import__("sys").modules, "pythoncom", pythoncom)
    monkeypatch.setitem(__import__("sys").modules, "win32com", win32com)
    monkeypatch.setitem(__import__("sys").modules, "win32com.client", client)
    monkeypatch.setattr("nodelang.baboom_native_voice.sys.platform", "win32")

    text = _WindowsSapiDictationBackend().capture_once(
        cancel=threading.Event(), timeout_seconds=1.0
    )

    assert text == "  review the Workshop plan  "
    assert state["context"].grammar.states == [1, 0]
    assert state["initialized"] is True
    assert state["uninitialized"] is True
