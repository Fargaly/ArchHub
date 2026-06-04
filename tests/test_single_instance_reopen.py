"""reopen=latest root-fix tests for single_instance + dev_source_sync.

Covers (founder, 2026-06-04 "tackle this from the roots"):
  * the QUIT command path in _serve_forever (BYE ack + on_quit fired)
  * the needs_sync-gated summon decision in acquire_or_summon
      - should_supersede True  -> QUIT old instance, this launch takes over
      - should_supersede False -> SUMMON exactly as before (no new code)
  * graceful degrade: no predicate / predicate raises -> today's behaviour
  * quit times out / old instance never releases -> fall back to SUMMON
  * dev_source_sync.has_new_source + force_sync_now gating
  * NO infinite loop: superseding launch binds a fresh port + returns True once

These run a real loopback listener (the production transport) so the wire
protocol is exercised end-to-end, with monkeypatching only to make the
gated branches deterministic + fast.
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest


APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


# --------------------------------------------------------------------------
# Helpers: isolate the lock file per test + run a controllable fake server.
# --------------------------------------------------------------------------

@pytest.fixture()
def si(tmp_path, monkeypatch):
    """Fresh single_instance module bound to a per-test lock file."""
    import single_instance

    lock_dir = tmp_path / "ArchHub"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / ".single-instance"
    monkeypatch.setattr(single_instance, "_LOCK_DIR", lock_dir)
    monkeypatch.setattr(single_instance, "_LOCK_FILE", lock_file)
    return single_instance


class _FakeInstance:
    """A minimal stand-in for a running ArchHub: a loopback listener that
    answers PING with PONG, SHOW with OK, and QUIT with BYE — optionally
    stopping (releasing) after QUIT so the lock frees, mirroring the real
    graceful-shutdown tail."""

    def __init__(self, lock_file: Path, *, release_on_quit: bool = True):
        self.lock_file = lock_file
        self.release_on_quit = release_on_quit
        self.saw_show = False
        self.saw_quit = False
        self.show_event = threading.Event()
        self.quit_event = threading.Event()
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file.write_text(str(self.port), encoding="utf-8")
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        self._sock.settimeout(0.25)
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(1.0)
                    data = conn.recv(64)
                except Exception:
                    continue
                if data.startswith(b"PING"):
                    try:
                        conn.sendall(b"PONG\n")
                    except Exception:
                        pass
                elif data.startswith(b"SHOW"):
                    self.saw_show = True
                    try:
                        conn.sendall(b"OK\n")
                    except Exception:
                        pass
                    self.show_event.set()
                elif data.startswith(b"QUIT"):
                    self.saw_quit = True
                    try:
                        conn.sendall(b"BYE\n")
                    except Exception:
                        pass
                    self.quit_event.set()
                    if self.release_on_quit:
                        # Mimic the real shutdown tail: release the lock and
                        # stop answering. Do it after this response returns.
                        self._release_and_stop()
                        return

    def _release_and_stop(self):
        self._stop.set()
        try:
            self.lock_file.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            self._sock.close()
        except Exception:
            pass

    def stop(self):
        self._release_and_stop()


# --------------------------------------------------------------------------
# 1) QUIT command path in _serve_forever
# --------------------------------------------------------------------------

def test_serve_forever_quit_acks_bye_and_fires_on_quit(si):
    """A QUIT sent to a real acquire_or_summon listener gets BYE and triggers
    the on_quit callback (the graceful-quit marshaller in production)."""
    quit_fired = threading.Event()

    became_listener = si.acquire_or_summon(
        on_summon=lambda: None,
        on_quit=lambda: quit_fired.set(),
    )
    assert became_listener is True
    port = si._read_existing_port()
    assert port is not None

    # Send QUIT directly on the wire; expect BYE.
    with socket.create_connection(("127.0.0.1", port), timeout=2.0) as s:
        s.settimeout(2.0)
        s.sendall(b"QUIT\n")
        ack = s.recv(64)
    assert ack.startswith(b"BYE")
    assert quit_fired.wait(timeout=2.0) is True


def test_serve_forever_still_answers_ping_and_show(si):
    """The new QUIT branch must not regress PING/SHOW."""
    show_fired = threading.Event()
    si.acquire_or_summon(on_summon=lambda: show_fired.set())
    port = si._read_existing_port()
    assert si._ping(port) is True
    assert si._summon(port) is True
    assert show_fired.wait(timeout=2.0) is True


# --------------------------------------------------------------------------
# 2) needs_sync-gated decision in acquire_or_summon
# --------------------------------------------------------------------------

def test_supersede_true_quits_old_and_takes_over(si):
    """should_supersede True + an old instance that releases on QUIT ->
    the old instance receives QUIT and this launch becomes the new listener
    (binds a fresh port, returns True). This is reopen=latest."""
    old = _FakeInstance(si._LOCK_FILE, release_on_quit=True)
    try:
        result = si.acquire_or_summon(
            on_summon=lambda: None,
            should_supersede=lambda: True,
        )
        assert old.quit_event.wait(timeout=2.0) is True
        assert old.saw_show is False  # we did NOT summon
        assert result is True  # we took over -> caller continues into startup
        # Lock now points at OUR fresh listener, not the old port.
        new_port = si._read_existing_port()
        assert new_port is not None
        assert new_port != old.port
        assert si._ping(new_port) is True
    finally:
        old.stop()


def test_supersede_false_summons_like_today(si):
    """should_supersede False (no new code) -> SUMMON the running instance
    and return False (this launch exits), exactly today's behaviour."""
    old = _FakeInstance(si._LOCK_FILE, release_on_quit=True)
    try:
        result = si.acquire_or_summon(
            on_summon=lambda: None,
            should_supersede=lambda: False,
        )
        assert result is False  # second launch exits
        assert old.show_event.wait(timeout=2.0) is True  # we summoned
        assert old.saw_quit is False  # we did NOT quit it
        # Lock still points at the old instance.
        assert si._read_existing_port() == old.port
    finally:
        old.stop()


def test_no_predicate_summons_like_today(si):
    """No should_supersede passed (existing callers) -> summon + exit. This
    proves the param is additive + backward compatible."""
    old = _FakeInstance(si._LOCK_FILE, release_on_quit=True)
    try:
        result = si.acquire_or_summon(on_summon=lambda: None)
        assert result is False
        assert old.show_event.wait(timeout=2.0) is True
        assert old.saw_quit is False
    finally:
        old.stop()


# --------------------------------------------------------------------------
# 3) Graceful degrade
# --------------------------------------------------------------------------

def test_predicate_raises_falls_back_to_summon(si):
    """should_supersede that raises must NOT crash startup — it degrades to
    summon-and-exit (today's behaviour)."""
    old = _FakeInstance(si._LOCK_FILE, release_on_quit=True)

    def boom():
        raise RuntimeError("predicate exploded")

    try:
        result = si.acquire_or_summon(
            on_summon=lambda: None,
            should_supersede=boom,
        )
        assert result is False  # summoned + exiting, not crashed
        assert old.show_event.wait(timeout=2.0) is True
    finally:
        old.stop()


def test_supersede_true_but_quit_times_out_falls_back_to_summon(si, monkeypatch):
    """should_supersede True but the old instance NEVER releases on QUIT ->
    _quit times out -> we degrade to SUMMON (founder gets the old window,
    i.e. exactly today) instead of hanging or force-killing."""
    old = _FakeInstance(si._LOCK_FILE, release_on_quit=False)

    # Keep the test fast: stub _quit's wait to a tiny bounded deadline by
    # patching time only inside single_instance is fragile; instead call
    # acquire_or_summon with a short-circuit _quit that reflects "couldn't".
    real_quit = si._quit

    def fast_quit(port, timeout=4.0):
        return real_quit(port, timeout=0.6)  # bounded, will fail to release

    monkeypatch.setattr(si, "_quit", fast_quit)

    try:
        result = si.acquire_or_summon(
            on_summon=lambda: None,
            should_supersede=lambda: True,
        )
        assert result is False  # didn't release -> we summoned + exit
        assert old.quit_event.wait(timeout=2.0) is True  # we asked it to quit
        assert old.show_event.wait(timeout=2.0) is True  # then summoned
        # Lock still the old instance (we never stole it).
        assert si._read_existing_port() == old.port
    finally:
        old.stop()


def test_no_instance_running_binds_fresh_regardless_of_predicate(si):
    """No running instance (no lock) -> bind fresh + return True, whether or
    not a predicate is supplied. should_supersede is only consulted when an
    instance is actually alive."""
    result = si.acquire_or_summon(
        on_summon=lambda: None,
        should_supersede=lambda: True,
    )
    assert result is True
    assert si._read_existing_port() is not None


def test_stale_lock_is_stolen_not_superseded(si):
    """A stale lock (port nobody answers) -> stolen + fresh bind, never a
    QUIT/summon. Covers the crash-without-release case the plan relies on."""
    # Write a lock pointing at a definitely-dead port.
    dead = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    dead.bind(("127.0.0.1", 0))
    dead_port = dead.getsockname()[1]
    dead.close()  # now nothing listens there
    si._LOCK_FILE.write_text(str(dead_port), encoding="utf-8")

    result = si.acquire_or_summon(
        on_summon=lambda: None,
        should_supersede=lambda: True,
    )
    assert result is True
    new_port = si._read_existing_port()
    assert new_port is not None
    assert new_port != dead_port


# --------------------------------------------------------------------------
# 4) quit_existing public helper
# --------------------------------------------------------------------------

def test_quit_existing_returns_true_when_none_running(si):
    assert si._read_existing_port() is None
    assert si.quit_existing() is True


def test_quit_existing_quits_a_running_instance(si):
    old = _FakeInstance(si._LOCK_FILE, release_on_quit=True)
    try:
        assert si.quit_existing(timeout=3.0) is True
        assert old.quit_event.wait(timeout=2.0) is True
    finally:
        old.stop()


def test_quit_existing_false_when_instance_wont_release(si):
    old = _FakeInstance(si._LOCK_FILE, release_on_quit=False)
    try:
        assert si.quit_existing(timeout=0.8) is False
    finally:
        old.stop()


# --------------------------------------------------------------------------
# 5) NO infinite loop — the supersede path takes over exactly once.
# --------------------------------------------------------------------------

def test_supersede_does_not_loop(si):
    """After superseding, a SUBSEQUENT acquire on the same lock with the same
    True predicate would quit US — but a single acquire_or_summon call returns
    exactly once and binds one port. (The relaunch-once guard lives in
    dev_source_sync via --no-dev-source-sync; here we assert the lock op is a
    single take-over, not a spin.)"""
    old = _FakeInstance(si._LOCK_FILE, release_on_quit=True)
    try:
        calls = {"n": 0}

        def once_true():
            calls["n"] += 1
            return True

        result = si.acquire_or_summon(
            on_summon=lambda: None,
            should_supersede=once_true,
        )
        assert result is True
        assert calls["n"] == 1  # predicate consulted exactly once
        port_a = si._read_existing_port()
        assert port_a is not None and port_a != old.port
    finally:
        old.stop()


# --------------------------------------------------------------------------
# 6) dev_source_sync.has_new_source + force_sync_now gating
# --------------------------------------------------------------------------

def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_source_install(tmp_path):
    import dev_source_sync

    source = tmp_path / "source"
    install = tmp_path / "install"
    (source / ".git").mkdir(parents=True)
    _write(source / "VERSION", "9.9.9")
    _write(source / "app" / "main.py", "print('head')\n")
    _write(source / "app" / "studio_shell.py", "NEW = True\n")
    _write(install / "settings.json", json.dumps({
        "enable_dev_source_sync": True,
        "dev_source_path": str(source),
    }))
    _write(install / "app" / "studio_shell.py", "OLD = True\n")
    return dev_source_sync, source, install


def test_has_new_source_true_then_false_after_sync(tmp_path):
    dev_source_sync, source, install = _make_source_install(tmp_path)
    # Before any sync, the marker is absent -> new code present.
    assert dev_source_sync.has_new_source(install) is True
    # After a sync, the marker matches -> no new code.
    dev_source_sync.maybe_sync_and_relaunch(install, ["main.py"], relaunch=False)
    assert dev_source_sync.has_new_source(install) is False


def test_has_new_source_false_when_install_is_git_checkout(tmp_path):
    dev_source_sync, source, install = _make_source_install(tmp_path)
    (install / ".git").mkdir(parents=True)  # install IS a checkout -> guard off
    assert dev_source_sync.has_new_source(install) is False


def test_has_new_source_false_when_no_source_configured(tmp_path):
    import dev_source_sync
    install = tmp_path / "install"
    _write(install / "settings.json", json.dumps({}))  # no dev source
    assert dev_source_sync.has_new_source(install) is False


def test_force_sync_now_ignores_marker(tmp_path):
    """force_sync_now must copy HEAD even when the marker already matches —
    the dev-verify "prove it's HEAD" guarantee."""
    dev_source_sync, source, install = _make_source_install(tmp_path)
    # First, a normal sync brings the install up to date (marker matches now).
    dev_source_sync.maybe_sync_and_relaunch(install, ["main.py"], relaunch=False)
    assert dev_source_sync.has_new_source(install) is False
    # Mutate the install copy out from under the marker (simulate drift).
    _write(install / "app" / "studio_shell.py", "TAMPERED = True\n")
    # maybe_sync would NO-OP (marker still matches); force_sync must re-copy.
    forced = dev_source_sync.force_sync_now(install, ["main.py"])
    assert forced is True
    assert (install / "app" / "studio_shell.py").read_text(encoding="utf-8") == "NEW = True\n"


def test_force_sync_now_noop_without_source(tmp_path):
    import dev_source_sync
    install = tmp_path / "install"
    _write(install / "settings.json", json.dumps({}))
    assert dev_source_sync.force_sync_now(install, ["main.py"]) is False


# --------------------------------------------------------------------------
# 7) reopen=latest PRIMARY fix — the QUIT happens ON THE SYNC PATH, in the
#    parent, BEFORE relaunch. This is the corrected placement: previously the
#    only quit lived in acquire_or_summon (the relaunched child), which fired
#    in the WRONG process (needs_sync was already False there) and summoned the
#    stale instance. Now maybe_sync_and_relaunch quits the old instance before
#    spawning the synced child, so the child binds the lock on the NEW code.
# --------------------------------------------------------------------------

@pytest.fixture()
def si_lock(tmp_path, monkeypatch):
    """Bind single_instance's lock file into tmp_path so a _FakeInstance and
    dev_source_sync's quit-before-relaunch share the SAME lock — exercising the
    real cross-module wire (dev_source_sync -> single_instance.quit_running_instance)."""
    import single_instance

    lock_dir = tmp_path / "ArchHub"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / ".single-instance"
    monkeypatch.setattr(single_instance, "_LOCK_DIR", lock_dir)
    monkeypatch.setattr(single_instance, "_LOCK_FILE", lock_file)
    return single_instance


def test_quit_running_instance_alias_matches_quit_existing(si):
    """The sync-path symbol dev_source_sync imports is a thin alias of the
    existing quit_existing machinery (ONE-SYSTEM: no duplicate quit loop)."""
    # No instance running -> both report "nobody to quit" == True.
    assert si._read_existing_port() is None
    assert si.quit_running_instance() is True
    # A running instance that releases on QUIT -> alias quits it (True) + the
    # instance saw QUIT, exactly like quit_existing.
    old = _FakeInstance(si._LOCK_FILE, release_on_quit=True)
    try:
        assert si.quit_running_instance(timeout=3.0) is True
        assert old.quit_event.wait(timeout=2.0) is True
    finally:
        old.stop()


def test_quit_running_instance_false_when_wont_release(si):
    """Bounded: an instance that never releases -> alias returns False within
    timeout (the caller then syncs + relaunches anyway -> worst case = today)."""
    old = _FakeInstance(si._LOCK_FILE, release_on_quit=False)
    try:
        assert si.quit_running_instance(timeout=0.8) is False
    finally:
        old.stop()


def test_sync_path_quits_old_instance_before_relaunch(tmp_path, si_lock, monkeypatch):
    """END-TO-END reopen=latest: an old instance holds the lock, the source has
    new code (needs_sync True). maybe_sync_and_relaunch must QUIT the old
    instance and do so BEFORE it spawns the relaunch child — proving the quit is
    on the sync path, in the parent, not in the (later) acquire_or_summon."""
    import dev_source_sync

    dev_source_sync, source, install = _make_source_install(tmp_path)

    # An old, stale-code instance is running, holding single_instance's lock.
    old = _FakeInstance(si_lock._LOCK_FILE, release_on_quit=True)

    # Record call order: the QUIT (old.quit_event) must precede _relaunch, and
    # os._exit must NOT actually kill the test process.
    order: list[str] = []

    def fake_relaunch(install_root, argv):
        order.append("relaunch")
        # When _relaunch runs, the old instance must already have been quit.
        assert old.saw_quit is True, "relaunch happened before the old instance was quit"

    def fake_exit(code):  # neutralise os._exit so the test survives
        order.append(f"exit:{code}")
        raise SystemExit(code)

    monkeypatch.setattr(dev_source_sync, "_relaunch", fake_relaunch)
    monkeypatch.setattr(dev_source_sync.os, "_exit", fake_exit)

    try:
        with pytest.raises(SystemExit):
            dev_source_sync.maybe_sync_and_relaunch(install, ["main.py"], relaunch=True)
        # The old instance received QUIT...
        assert old.quit_event.wait(timeout=2.0) is True
        # ...the sync actually wrote the new code...
        assert (install / "app" / "studio_shell.py").read_text(encoding="utf-8") == "NEW = True\n"
        # ...and the order was quit -> relaunch -> exit (quit strictly first).
        assert order == ["relaunch", "exit:0"]
    finally:
        old.stop()


def test_sync_path_proceeds_when_no_instance_running(tmp_path, si_lock, monkeypatch):
    """Graceful degrade #1: NO instance running -> quit_running_instance returns
    True immediately, the sync + relaunch proceed normally (no hang, no error)."""
    import dev_source_sync

    dev_source_sync, source, install = _make_source_install(tmp_path)
    assert si_lock._read_existing_port() is None  # nobody holds the lock

    relaunched = {"n": 0}
    monkeypatch.setattr(dev_source_sync, "_relaunch",
                        lambda *_a, **_k: relaunched.__setitem__("n", relaunched["n"] + 1))
    monkeypatch.setattr(dev_source_sync.os, "_exit",
                        lambda code: (_ for _ in ()).throw(SystemExit(code)))

    with pytest.raises(SystemExit):
        dev_source_sync.maybe_sync_and_relaunch(install, ["main.py"], relaunch=True)
    assert relaunched["n"] == 1
    assert (install / "app" / "studio_shell.py").read_text(encoding="utf-8") == "NEW = True\n"


def test_sync_path_proceeds_when_quit_fails(tmp_path, si_lock, monkeypatch):
    """Graceful degrade #2: the old instance NEVER releases on QUIT (wedged) ->
    the bounded quit returns False, but maybe_sync_and_relaunch STILL syncs +
    relaunches (worst case = today's behaviour), never hangs or aborts."""
    import dev_source_sync

    dev_source_sync, source, install = _make_source_install(tmp_path)
    old = _FakeInstance(si_lock._LOCK_FILE, release_on_quit=False)  # won't free lock

    # Keep the bounded wait short so the test is fast.
    monkeypatch.setattr(dev_source_sync, "QUIT_OLD_INSTANCE_TIMEOUT", 0.6)

    relaunched = {"n": 0}
    monkeypatch.setattr(dev_source_sync, "_relaunch",
                        lambda *_a, **_k: relaunched.__setitem__("n", relaunched["n"] + 1))
    monkeypatch.setattr(dev_source_sync.os, "_exit",
                        lambda code: (_ for _ in ()).throw(SystemExit(code)))

    try:
        with pytest.raises(SystemExit):
            dev_source_sync.maybe_sync_and_relaunch(install, ["main.py"], relaunch=True)
        assert old.quit_event.wait(timeout=2.0) is True  # we DID ask it to quit
        assert relaunched["n"] == 1                       # and relaunched anyway
        assert (install / "app" / "studio_shell.py").read_text(encoding="utf-8") == "NEW = True\n"
    finally:
        old.stop()


def test_sync_path_proceeds_when_quit_symbol_missing(tmp_path, monkeypatch):
    """Graceful degrade #3: if single_instance.quit_running_instance is missing
    (ImportError) the helper swallows it and returns False; the sync + relaunch
    still proceed. Proven directly on the helper to avoid import-cache games."""
    import builtins
    import dev_source_sync

    dev_source_sync, source, install = _make_source_install(tmp_path)

    real_import = builtins.__import__

    def block_single_instance(name, *args, **kwargs):
        if name == "single_instance":
            raise ImportError("simulated missing single_instance")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_single_instance)
    # Must NOT raise — returns False (degrade), caller proceeds.
    assert dev_source_sync._quit_running_instance_before_relaunch(install) is False


def test_sync_path_no_quit_when_relaunch_false(tmp_path, si_lock, monkeypatch):
    """relaunch=False (the in-process force/dev paths) must NOT quit a running
    instance — there is no successor child to take over, so quitting the running
    app would be wrong. Proves the quit is gated to the actual relaunch path."""
    import dev_source_sync

    dev_source_sync, source, install = _make_source_install(tmp_path)
    old = _FakeInstance(si_lock._LOCK_FILE, release_on_quit=True)
    try:
        changed = dev_source_sync.maybe_sync_and_relaunch(install, ["main.py"], relaunch=False)
        assert changed is True
        # The running instance was left completely alone.
        assert old.saw_quit is False
        assert si_lock._read_existing_port() == old.port
    finally:
        old.stop()


def test_sync_path_quit_runs_once_no_loop(tmp_path, si_lock, monkeypatch):
    """NO infinite loop: maybe_sync_and_relaunch invokes the quit exactly once
    per sync, then relaunches once. The relaunched child carries
    --no-dev-source-sync so it bails before this code (the relaunch-once guard),
    making the whole take-over a single, terminating step."""
    import dev_source_sync

    dev_source_sync, source, install = _make_source_install(tmp_path)

    quit_calls = {"n": 0}
    relaunch_calls = {"n": 0}

    def counting_quit(install_root):
        quit_calls["n"] += 1
        return True

    monkeypatch.setattr(dev_source_sync, "_quit_running_instance_before_relaunch", counting_quit)
    monkeypatch.setattr(dev_source_sync, "_relaunch",
                        lambda *_a, **_k: relaunch_calls.__setitem__("n", relaunch_calls["n"] + 1))
    monkeypatch.setattr(dev_source_sync.os, "_exit",
                        lambda code: (_ for _ in ()).throw(SystemExit(code)))

    with pytest.raises(SystemExit):
        dev_source_sync.maybe_sync_and_relaunch(install, ["main.py"], relaunch=True)
    assert quit_calls["n"] == 1
    assert relaunch_calls["n"] == 1

    # The relaunched child (carries --no-dev-source-sync) bails immediately:
    # no second quit, no second relaunch -> the take-over terminates.
    child = dev_source_sync.maybe_sync_and_relaunch(
        install, ["main.py", "--no-dev-source-sync"], relaunch=True)
    assert child is False
    assert quit_calls["n"] == 1
    assert relaunch_calls["n"] == 1
