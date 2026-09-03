"""Brain liveness + graceful degradation — solves R3.

Three nested resilience loops:

  Inner (per-call)        — Circuit breaker. Hard fails (conn-refused)
                            trip instantly; soft fails (timeout) trip on
                            threshold. Half-open probe on reset_timeout.
  Middle (per-process)    — Watchdog. Pings /livez; on N consecutive
                            failures, calls supervisor callback (e.g.,
                            restart daemon via subprocess.Popen).
  Outer (per-OS)          — systemd/launchd/Service Manager (already in
                            service.py from Slice 25). Enforces
                            WatchdogSec=15s.

Plus the WRITE JOURNAL — every brain.write hits a local append-only
NDJSON file BEFORE the network. On daemon recovery, the journal is
drained into the brain store. Means no writes lost during outage.

Plus user-visible STATUS callbacks for the status-bar pill (live /
degraded / offline) and one-time toasts on transitions.

References:
  • Circuit Breaker — Nygard "Release It!" 2007 / Fowler
  • AWS Reliability Pillar — REL05-BP01 graceful degradation
  • Kubernetes — /livez vs /readyz vs /healthz
  • Erlang OTP — supervisor with restart intensity bound
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


# ─────────────────────── status callback type ──────────────────────────


StatusCallback = Callable[[str, dict[str, Any]], None]
"""Signature: callback(state, details) → None.
state ∈ {"live", "degraded", "offline", "recovered"}.
details has keys like reason, last_error, ts."""


def _noop_status(state: str, details: dict[str, Any]) -> None:
    pass


# ─────────────────────── circuit breaker ───────────────────────────────


@dataclass
class BreakerConfig:
    threshold: int = 3
    reset_timeout_s: float = 5.0
    soft_failure_window_s: float = 60.0
    # On hard-fail (conn-refused) trip instantly regardless of threshold
    hard_fail_trip: bool = True


@dataclass
class BreakerState:
    state: str = "closed"  # closed | open | half_open
    failures: int = 0
    last_fail_ts: float = 0.0
    last_success_ts: float = 0.0
    state_changed_ts: float = 0.0
    half_open_probes_used: int = 0


class CircuitBreaker:
    """Per-call breaker around any callable. Distinguishes hard failures
    (conn-refused / DNS / network unreachable) from soft (timeout /
    transient 5xx)."""

    def __init__(
        self,
        *,
        config: Optional[BreakerConfig] = None,
        on_status: Optional[StatusCallback] = None,
    ):
        self.cfg = config or BreakerConfig()
        self._state = BreakerState()
        self._lock = threading.Lock()
        self._on_status = on_status or _noop_status

    @property
    def state(self) -> str:
        return self._state.state

    def call(self, fn: Callable, *args, **kwargs):
        """Invoke `fn` through the breaker. Raises BreakerOpen if blocked."""
        now = time.time()
        with self._lock:
            if self._state.state == "open":
                if now - self._state.state_changed_ts > self.cfg.reset_timeout_s:
                    self._state.state = "half_open"
                    self._state.state_changed_ts = now
                    self._state.half_open_probes_used = 0
                else:
                    raise BreakerOpen(
                        f"breaker open since {now - self._state.state_changed_ts:.1f}s"
                    )

        try:
            result = fn(*args, **kwargs)
        except (
            ConnectionRefusedError, ConnectionResetError, socket.gaierror,
            urllib.error.URLError,
        ) as e:
            self._record_failure(now, hard=True, exc=e)
            raise
        except (TimeoutError, urllib.error.HTTPError, socket.timeout) as e:
            self._record_failure(now, hard=False, exc=e)
            raise
        except Exception as e:
            # Unknown — treat as soft
            self._record_failure(now, hard=False, exc=e)
            raise

        # Success
        self._record_success(now)
        return result

    def _record_success(self, ts: float) -> None:
        with self._lock:
            self._state.last_success_ts = ts
            prev_state = self._state.state
            self._state.failures = 0
            self._state.state = "closed"
            if prev_state != "closed":
                self._state.state_changed_ts = ts
                self._fire_status(
                    "recovered" if prev_state == "open" else "live",
                    {"prev_state": prev_state, "ts": ts},
                )

    def _record_failure(
        self, ts: float, *, hard: bool, exc: BaseException,
    ) -> None:
        with self._lock:
            self._state.failures += 1
            self._state.last_fail_ts = ts
            should_trip = False
            if hard and self.cfg.hard_fail_trip:
                should_trip = True
            elif self._state.failures >= self.cfg.threshold:
                should_trip = True
            if should_trip and self._state.state != "open":
                prev = self._state.state
                self._state.state = "open"
                self._state.state_changed_ts = ts
                self._fire_status("degraded" if prev == "closed" else "offline",
                                   {"reason": str(exc),
                                    "hard": hard, "failures": self._state.failures,
                                    "ts": ts})

    def _fire_status(self, state: str, details: dict[str, Any]) -> None:
        try:
            self._on_status(state, details)
        except Exception:
            pass

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state.state,
                "failures": self._state.failures,
                "last_fail_ts": self._state.last_fail_ts,
                "last_success_ts": self._state.last_success_ts,
                "state_changed_ts": self._state.state_changed_ts,
            }


class BreakerOpen(Exception):
    """Raised when the breaker is open and refuses to invoke the wrapped
    callable. Callers should fall through to the journal / cached path."""


# ─────────────────────── write journal ─────────────────────────────────


class WriteJournal:
    """Append-only NDJSON of pending brain.write ops. Survives daemon
    crashes; drains into the brain on recovery."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, op: dict[str, Any]) -> None:
        line = json.dumps(op, default=str) + "\n"
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass

    def drain(self) -> list[dict[str, Any]]:
        """Read all pending ops + clear the file atomically. Returns the
        list of ops in append order."""
        with self._lock:
            if not self.path.exists():
                return []
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    lines = f.read().splitlines()
            except OSError:
                return []
            ops: list[dict[str, Any]] = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    ops.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            # Rotate the file (truncate by replacing with empty)
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", delete=False,
                    dir=str(self.path.parent),
                    prefix=self.path.name + ".",
                    suffix=".tmp",
                ) as f:
                    tmp_name = f.name
                os.replace(tmp_name, self.path)
            except OSError:
                pass
            return ops

    def pending_count(self) -> int:
        if not self.path.exists():
            return 0
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except OSError:
            return 0


# ─────────────────────── watchdog ──────────────────────────────────────


@dataclass
class WatchdogConfig:
    livez_url: str = "http://127.0.0.1:8473/healthz"
    heartbeat_s: float = 5.0
    failure_threshold: int = 3
    max_restart_intensity: int = 5
    restart_window_s: float = 60.0
    timeout_s: float = 2.0


class Watchdog:
    """Pings `/livez` on a schedule. On `failure_threshold` consecutive
    failures, calls `respawn_fn`. Bounded by `max_restart_intensity` per
    `restart_window_s` to prevent fork bombs."""

    def __init__(
        self,
        respawn_fn: Optional[Callable[[], None]] = None,
        *,
        config: Optional[WatchdogConfig] = None,
        on_status: Optional[StatusCallback] = None,
    ):
        self.cfg = config or WatchdogConfig()
        self.respawn_fn = respawn_fn or (lambda: None)
        self._on_status = on_status or _noop_status
        self._restart_times: list[float] = []
        self._consec_failures = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="brain-watchdog", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            ok = self._probe()
            if ok:
                if self._consec_failures > 0:
                    self._on_status("live", {"recovered_from": self._consec_failures})
                self._consec_failures = 0
            else:
                self._consec_failures += 1
                if self._consec_failures >= self.cfg.failure_threshold:
                    self._maybe_respawn()
            time.sleep(self.cfg.heartbeat_s)

    def _probe(self) -> bool:
        try:
            req = urllib.request.Request(self.cfg.livez_url, method="GET")
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as r:
                return r.status == 200
        except Exception:
            return False

    def _maybe_respawn(self) -> None:
        now = time.time()
        # Drop old restarts outside window
        self._restart_times = [
            t for t in self._restart_times
            if now - t < self.cfg.restart_window_s
        ]
        if len(self._restart_times) >= self.cfg.max_restart_intensity:
            self._on_status("offline", {
                "reason": "max restart intensity hit",
                "restarts": len(self._restart_times),
                "window_s": self.cfg.restart_window_s,
            })
            self._running = False  # stop trying
            return
        self._restart_times.append(now)
        self._on_status("degraded", {"reason": "respawn attempt",
                                       "attempt": len(self._restart_times)})
        try:
            self.respawn_fn()
        except Exception as ex:
            self._on_status("offline", {"reason": f"respawn failed: {ex}"})


def default_respawn() -> None:
    """Fork a fresh personal-brain daemon process. Detaches so it survives
    parent exit."""
    cmd = [
        os.environ.get("BRAIN_CMD", "personal-brain"),
        "--http",
        os.environ.get("BRAIN_PORT", "8473"),
    ]
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        # Fallback: try `python -m personal_brain.server --http 8473`
        import sys
        subprocess.Popen(
            [sys.executable, "-m", "personal_brain.server",
              "--http", os.environ.get("BRAIN_PORT", "8473")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )


# ─────────────────────── resilient brain client wrapper ────────────────


class ResilientBrainClient:
    """Wraps any brain HTTP client with:
      • circuit breaker on every call
      • write journal: brain.write hits journal BEFORE network
      • status callbacks on every state transition
      • cached last context (cheap fallback during outage)
    """

    def __init__(
        self,
        inner_client: Any,
        *,
        journal_path: str | Path,
        on_status: Optional[StatusCallback] = None,
        breaker_config: Optional[BreakerConfig] = None,
    ):
        self.inner = inner_client
        self.journal = WriteJournal(journal_path)
        self.breaker = CircuitBreaker(
            config=breaker_config, on_status=on_status,
        )
        self._cached_context: Optional[dict[str, Any]] = None

    def context(self, prompt: str, **kwargs) -> Optional[dict[str, Any]]:
        try:
            resp = self.breaker.call(self.inner.context, prompt, **kwargs)
            if resp is not None:
                self._cached_context = resp
            return resp
        except BreakerOpen:
            return self._cached_context  # serve last known good
        except (
            ConnectionRefusedError, ConnectionResetError,
            TimeoutError, urllib.error.URLError, OSError,
        ):
            return self._cached_context  # serve last known good

    def write(self, ops: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        # ALWAYS journal first — durability before network
        for op in ops:
            self.journal.append(op)
        try:
            resp = self.breaker.call(self.inner.write, ops)
            return resp
        except BreakerOpen:
            return {"ops_applied": 0, "journaled": len(ops),
                    "journal_pending": self.journal.pending_count()}
        except (
            ConnectionRefusedError, ConnectionResetError,
            TimeoutError, urllib.error.URLError, OSError,
        ) as ex:
            # Transport-level failure — breaker already updated by the
            # internal except clause. Caller gets a non-raising response;
            # the write is durable in the journal.
            return {"ops_applied": 0, "journaled": len(ops),
                    "journal_pending": self.journal.pending_count(),
                    "error": str(ex)}

    def replay_journal(self) -> int:
        """Call on recovery. Drains the journal into the live brain.
        Attempts a half-open probe if the breaker was open past its
        reset timeout. Returns number of ops replayed (or 0 if still
        unable to reach the daemon)."""
        pending = self.journal.drain()
        if not pending:
            return 0
        try:
            self.breaker.call(self.inner.write, pending)
            return len(pending)
        except (BreakerOpen, ConnectionRefusedError, ConnectionResetError,
                 TimeoutError, urllib.error.URLError, OSError):
            # Re-journal what we couldn't send
            for op in pending:
                self.journal.append(op)
            return 0

    def skill_mint(self, trace: dict[str, Any], **kwargs):
        try:
            return self.breaker.call(self.inner.skill_mint, trace, **kwargs)
        except (BreakerOpen, ConnectionRefusedError, ConnectionResetError,
                 TimeoutError, urllib.error.URLError, OSError):
            return None

    def wiring_announce(self, *args, **kwargs):
        try:
            return self.breaker.call(self.inner.wiring_announce, *args, **kwargs)
        except (BreakerOpen, ConnectionRefusedError, ConnectionResetError,
                 TimeoutError, urllib.error.URLError, OSError):
            return None

    def status(self) -> dict[str, Any]:
        return {
            "breaker": self.breaker.status(),
            "journal_pending": self.journal.pending_count(),
            "has_cached_context": self._cached_context is not None,
        }
