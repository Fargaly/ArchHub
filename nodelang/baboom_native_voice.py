"""Explicit, non-persistent Windows speech input for the BABOOM projection.

This is a physical adapter only.  It owns no Cell state, starts no background
listener, and never stores audio.  A caller must explicitly invoke one capture
and decides what to do with the returned text.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import sys
import threading
import time
from typing import Protocol


class BaboomVoiceError(RuntimeError):
    """Voice input could not produce one founder-requested utterance."""


class BaboomVoiceCancelled(BaboomVoiceError):
    """The founder cancelled the active, one-utterance capture."""


class BaboomVoiceUnavailable(BaboomVoiceError):
    """The host has no usable Windows speech-recognition runtime."""


class BaboomVoiceTimeout(BaboomVoiceError):
    """The explicitly requested capture ended without a recognition result."""


class _VoiceBackend(Protocol):
    def capture_once(
        self,
        *,
        cancel: threading.Event,
        timeout_seconds: float,
    ) -> str: ...


@dataclass(frozen=True)
class BaboomVoiceInput:
    """One explicit voice capture entry point; no listening exists before it."""

    timeout_seconds: float = 20.0
    backend_factory: Callable[[], _VoiceBackend] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.timeout_seconds, float) or not 1.0 <= self.timeout_seconds <= 60.0:
            raise ValueError("BABOOM voice timeout must be between one and sixty seconds")
        if self.backend_factory is not None and not callable(self.backend_factory):
            raise ValueError("BABOOM voice backend factory is invalid")

    def capture_once(self, *, cancel: threading.Event) -> str:
        """Capture one utterance after an explicit UI action and discard audio."""
        if not isinstance(cancel, threading.Event):
            raise ValueError("BABOOM voice cancel signal is invalid")
        if cancel.is_set():
            raise BaboomVoiceCancelled("Voice capture was cancelled")
        factory = self.backend_factory or _WindowsSapiDictationBackend
        text = factory().capture_once(cancel=cancel, timeout_seconds=self.timeout_seconds)
        compact = " ".join(text.split())
        if cancel.is_set():
            raise BaboomVoiceCancelled("Voice capture was cancelled")
        if not compact:
            raise BaboomVoiceTimeout("No speech was recognized")
        return compact[:1_000]


class _WindowsSapiDictationBackend:
    """Run one bounded dictation grammar through the shared Windows recognizer."""

    _DICTATION_ACTIVE = 1
    _DICTATION_INACTIVE = 0
    _POLL_SECONDS = 0.05

    def capture_once(
        self,
        *,
        cancel: threading.Event,
        timeout_seconds: float,
    ) -> str:
        if sys.platform != "win32":
            raise BaboomVoiceUnavailable("Windows speech input is unavailable on this device")
        try:
            import pythoncom
            import win32com.client
        except ImportError as exc:  # pragma: no cover - host packaging boundary
            raise BaboomVoiceUnavailable("Windows speech input is not installed") from exc

        pythoncom.CoInitialize()
        grammar = None
        try:
            class RecognitionEvents:
                text = ""

                def OnRecognition(self, _stream, _position, _kind, result) -> None:  # noqa: N802
                    phrase = result.PhraseInfo.GetText()
                    if isinstance(phrase, str) and phrase.strip():
                        self.text = phrase

            context = win32com.client.DispatchWithEvents(
                "SAPI.SpSharedRecoContext", RecognitionEvents
            )
            grammar = context.CreateGrammar()
            grammar.DictationLoad()
            grammar.DictationSetState(self._DICTATION_ACTIVE)
            deadline = time.monotonic() + timeout_seconds
            while not cancel.is_set() and not context.text and time.monotonic() < deadline:
                pythoncom.PumpWaitingMessages()
                time.sleep(self._POLL_SECONDS)
            if cancel.is_set():
                raise BaboomVoiceCancelled("Voice capture was cancelled")
            if not context.text:
                raise BaboomVoiceTimeout("No speech was recognized before the timeout")
            return context.text
        except BaboomVoiceError:
            raise
        except Exception as exc:  # pragma: no cover - depends on Windows speech setup
            raise BaboomVoiceUnavailable("Windows speech recognition is unavailable") from exc
        finally:
            if grammar is not None:
                try:
                    grammar.DictationSetState(self._DICTATION_INACTIVE)
                except Exception:
                    pass
            pythoncom.CoUninitialize()


__all__ = [
    "BaboomVoiceCancelled",
    "BaboomVoiceError",
    "BaboomVoiceInput",
    "BaboomVoiceTimeout",
    "BaboomVoiceUnavailable",
]
