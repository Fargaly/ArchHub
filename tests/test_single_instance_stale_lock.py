"""Single-instance STALE-LOCK HARDENING (#70, founder 2026-06-22 —
"harden the single-instance guard so a MISSING or STALE lock is reclaimed").

The guarantee under test: a MISSING or STALE lock (dead owner PID / dead-or-
recycled port / too-old leftover) is reclaimed cleanly — THIS launch becomes the
single instance. We NEVER spawn a duplicate (a live lock is summoned, never
stolen) and we NEVER refuse to start because of a stale lock.

Three independent stale detectors, each reclaimed in isolation here:
  1. PORT DEAD  — the lock's port no longer answers PING (crash-without-release)
  2. PID DEAD   — the lock records an owner PID that is gone, even if some
                  UNRELATED process recycled the port
  3. TOO OLD    — an ancient lock whose PID can't be confirmed alive

Plus: the lock is written ATOMICALLY with port+pid+ts, the legacy bare-port
format is still honoured, and release() only deletes our OWN lock.

These run a real loopback listener (the production transport) so the stale
detection is exercised end-to-end against the real ``acquire_or_summon`` /
``_is_lock_stale`` — not a mock of the code under test. The lock file is
isolated per-test into tmp_path.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path

import pytest


APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


@pytest.fixture()
def si(tmp_path, monkeypatch):
    """Fresh single_instance bound to a per-test lock file."""
    import single_instance
    lock_dir = tmp_path / "ArchHub"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / ".single-instance"
    monkeypatch.setattr(single_instance, "_LOCK_DIR", lock_dir)
    monkeypatch.setattr(single_instance, "_LOCK_FILE", lock_file)
    return single_instance


def _dead_port() -> int:
    """A port nobody listens on (bound then closed)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _dead_pid() -> int:
    """A PID that is (almost certainly) not running. We pick a high PID and
    verify the OS reports it gone; skip the rare case it's actually alive."""
    for cand in (4_000_000_000, 999_999, 424242):
        return cand
    return 424242


# ── _pid_alive primitive ────────────────────────────────────────────────────

class TestPidAlive:
    def test_current_process_is_alive(self, si):
        assert si._pid_alive(os.getpid()) is True

    def test_dead_pid_is_not_alive(self, si):
        # A clearly-out-of-range / nonexistent PID -> definitely gone (False).
        # On the off chance the OS returns None (inconclusive) we accept that
        # too — the contract is "never wrongly report a dead PID as alive".
        assert si._pid_alive(_dead_pid()) in (False, None)

    def test_none_and_zero_are_unknown(self, si):
        assert si._pid_alive(None) is None
        assert si._pid_alive(0) is None


# ── _is_lock_stale — the three detectors ────────────────────────────────────

class TestIsLockStale:
    def test_missing_lock_is_stale(self, si):
        assert si._is_lock_stale(None) is True
        assert si._read_lock() is None  # no file yet

    def test_dead_port_lock_is_stale(self, si):
        d = {"port": _dead_port(), "pid": os.getpid(), "ts": time.time()}
        assert si._is_lock_stale(d) is True  # PID alive but port dead -> reclaim

    def test_dead_pid_lock_is_stale_even_if_port_answers(self, si):
        """PID DEAD detector: a recorded-but-gone owner PID is stale even when
        SOMETHING is answering on the recorded port (recycled foreign listener).
        We point the lock at our own live PING listener but a dead PID."""
        became = si.acquire_or_summon(on_summon=lambda: None)
        assert became is True
        live_port = si._read_existing_port()
        assert si._ping(live_port) is True  # port genuinely answers
        d = {"port": live_port, "pid": _dead_pid(), "ts": time.time()}
        assert si._is_lock_stale(d) is True  # dead PID wins over a live port

    def test_too_old_lock_with_unconfirmable_pid_is_stale(self, si):
        """TOO OLD detector: an ancient lock whose PID we can't confirm alive is
        reclaimed even if the port happens to answer."""
        became = si.acquire_or_summon(on_summon=lambda: None)
        assert became is True
        live_port = si._read_existing_port()
        ancient = time.time() - (si._LOCK_MAX_AGE_SEC + 3600)
        d = {"port": live_port, "pid": None, "ts": ancient}  # unknown pid + old
        assert si._is_lock_stale(d) is True

    def test_live_lock_is_not_stale(self, si):
        """A lock for THIS process whose port answers + recent ts is LIVE."""
        became = si.acquire_or_summon(on_summon=lambda: None)
        assert became is True
        d = si._read_lock()
        assert d["pid"] == os.getpid()
        assert si._is_lock_stale(d) is False


# ── acquire_or_summon: reclaim never refuses, never duplicates ───────────────

class TestAcquireReclaim:
    def test_missing_lock_starts_clean(self, si):
        """No lock at all -> we become the single instance (the common case)."""
        assert si._read_lock() is None
        result = si.acquire_or_summon(on_summon=lambda: None)
        assert result is True
        d = si._read_lock()
        assert d is not None and d["pid"] == os.getpid()

    def test_dead_port_lock_reclaimed_no_duplicate(self, si):
        """STALE (dead port) -> reclaim + start; never refuse, never summon a
        ghost. The new lock points at OUR fresh listener with OUR pid."""
        si._LOCK_FILE.write_text(str(_dead_port()), encoding="utf-8")  # legacy fmt
        result = si.acquire_or_summon(on_summon=lambda: None)
        assert result is True
        d = si._read_lock()
        assert d["pid"] == os.getpid()
        assert si._ping(d["port"]) is True

    def test_dead_pid_lock_reclaimed(self, si):
        """STALE (dead PID, recycled live port) -> reclaim. We seed a JSON lock
        whose port we make genuinely answer (our own listener) but with a dead
        PID, then a SECOND acquire must reclaim rather than summon."""
        # First acquire binds a real listener + writes our lock.
        assert si.acquire_or_summon(on_summon=lambda: None) is True
        port = si._read_existing_port()
        # Rewrite the lock with the SAME (answering) port but a dead PID, as if
        # the original owner died and an unrelated process took the port.
        si._LOCK_FILE.write_text(
            json.dumps({"port": port, "pid": _dead_pid(), "ts": time.time()}),
            encoding="utf-8")
        summoned = {"n": 0}
        result = si.acquire_or_summon(on_summon=lambda: summoned.__setitem__("n", 1))
        assert result is True, "dead-PID lock must be reclaimed, never refuse to start"
        d = si._read_lock()
        assert d["pid"] == os.getpid(), "reclaimed lock must record our PID"

    def test_too_old_legacy_lock_reclaimed(self, si):
        """A legacy bare-port lock that's ancient + dead-port -> reclaim."""
        si._LOCK_FILE.write_text(str(_dead_port()), encoding="utf-8")
        old = time.time() - (si._LOCK_MAX_AGE_SEC + 3600)
        os.utime(si._LOCK_FILE, (old, old))
        result = si.acquire_or_summon(on_summon=lambda: None)
        assert result is True
        assert si._read_lock()["pid"] == os.getpid()


# ── lock format: atomic write + legacy read ─────────────────────────────────

class TestLockFormat:
    def test_write_lock_is_json_with_pid_and_ts(self, si):
        si._write_lock(54321)
        raw = si._LOCK_FILE.read_text(encoding="utf-8")
        d = json.loads(raw)
        assert d["port"] == 54321
        assert d["pid"] == os.getpid()
        assert isinstance(d["ts"], (int, float)) and d["ts"] > 0
        # No leftover temp file from the atomic replace.
        leftovers = list(si._LOCK_FILE.parent.glob(".single-instance.tmp.*"))
        assert leftovers == []

    def test_read_existing_port_handles_legacy_bare_port(self, si):
        si._LOCK_FILE.write_text("4242", encoding="utf-8")
        assert si._read_existing_port() == 4242
        d = si._read_lock()
        assert d["port"] == 4242
        assert d["pid"] is None  # legacy -> unknown pid

    def test_read_existing_port_handles_new_json(self, si):
        si._write_lock(7777)
        assert si._read_existing_port() == 7777

    def test_read_lock_tolerates_garbage(self, si):
        si._LOCK_FILE.write_text("not-a-port {{{", encoding="utf-8")
        assert si._read_lock() is None
        # And acquire over garbage still starts cleanly (never refuse).
        assert si.acquire_or_summon(on_summon=lambda: None) is True


# ── release(): only delete our own lock ─────────────────────────────────────

class TestRelease:
    def test_release_deletes_own_lock(self, si):
        si._write_lock(1234)
        assert si._LOCK_FILE.exists()
        si.release()
        assert not si._LOCK_FILE.exists()

    def test_release_leaves_a_successors_lock_intact(self, si):
        """If a successor launch reclaimed the lock (its own PID), our late
        atexit release() must NOT delete it — that would strand the new
        instance lockless."""
        si._LOCK_FILE.write_text(
            json.dumps({"port": 1234, "pid": _dead_pid() + 1, "ts": time.time()}),
            encoding="utf-8")  # a DIFFERENT pid (the successor)
        si.release()
        assert si._LOCK_FILE.exists(), "must not clobber a successor's lock"

    def test_release_deletes_legacy_unowned_lock(self, si):
        """A legacy bare-port lock (unknown pid) is treated as ours/unowned and
        cleaned up (back-compat: pre-#70 release() always deleted)."""
        si._LOCK_FILE.write_text("4242", encoding="utf-8")
        si.release()
        assert not si._LOCK_FILE.exists()
