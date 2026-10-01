"""Process trust never deadlocks against an admitted operation (6eff, 2026-10-01).

The first-run pipeline seed holds the broker's lock (broker.live_context) and,
inside the seed, asks the desktop session for its context. A machine route at
the same moment asks the session for its context, which used to hold the
session's lock while resolving through the broker. Each thread then held the
lock the other waited for, and a new user's first boot froze.

Real AuthenticationBroker and DesktopAuthenticationSession; two threads; the
join timeout is the verdict. Threads are daemons so a deadlock fails the court
instead of hanging the run.
"""
from __future__ import annotations

import dataclasses
import threading
import time

from nodelang.cell_authorization import AuthenticationBroker
from nodelang.universal_application import DesktopAuthenticationSession


def _session():
    broker = AuthenticationBroker()
    session = DesktopAuthenticationSession(
        "session-root", broker, "subject-root", (), "tenant-root", "assurance-root",
        lifetime_seconds=600.0)
    return broker, session


def test_an_admitted_operation_and_a_machine_route_both_finish():
    broker, session = _session()
    context = session.context()          # the process trust both threads share
    holding_broker = threading.Event()
    results = {}

    def seed():
        # The seed: inside broker.live_context it asks the session again
        # (create_universal_property -> _active_authentication_context).
        with broker.live_context(context):
            holding_broker.set()
            time.sleep(0.3)              # the machine route is now inside context()
            results["seed"] = session.context(minimum_validity_seconds=5)

    def machine_route():
        holding_broker.wait(5)
        results["route"] = session.context(minimum_validity_seconds=5)

    threads = [threading.Thread(target=seed, daemon=True),
               threading.Thread(target=machine_route, daemon=True)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert not any(thread.is_alive() for thread in threads), (
        "session.context() deadlocked against broker.live_context()")
    assert results["seed"] is context and results["route"] is context


def test_the_session_lock_is_never_held_across_a_broker_call():
    """The rule itself: while the broker's lock is taken by another thread, the
    session's lock stays free for everyone else (it guards only the handle)."""
    broker, session = _session()
    context = session.context()
    blocked_in_resolve = threading.Event()
    release = threading.Event()

    def hold_broker():
        with broker.live_context(context):
            blocked_in_resolve.set()
            release.wait(5)

    holder = threading.Thread(target=hold_broker, daemon=True)
    holder.start()
    blocked_in_resolve.wait(5)
    asker = threading.Thread(target=lambda: session.context(minimum_validity_seconds=5), daemon=True)
    asker.start()
    time.sleep(0.3)                      # the asker now waits for the broker
    acquired = session._lock.acquire(timeout=2)
    if acquired:
        session._lock.release()
    release.set()
    holder.join(5)
    asker.join(5)
    assert acquired, "the session lock was held while waiting for the broker"


def test_an_expired_or_revoked_handle_is_renewed_once_and_shared():
    broker, session = _session()
    first = session.context()
    broker.revoke(first)
    renewed = session.context()
    assert renewed is not first
    assert session.context() is renewed


# Ping 2026-10-01: a renewal race. Thread A mints, pauses before storing, thread B
# renews and stores its own handle; then A resumes. Events order every step; the
# only waits are bounded Event.wait timeouts, never sleeps as proof.

class _Race:
    """A's mint pauses right after it returns from the broker, before context()
    stores or compares anything; every other thread mints straight through."""

    def __init__(self, broker):
        self.broker = broker
        self.real_mint = broker.mint_authenticated_context
        self.a_minted = threading.Event()
        self.release_a = threading.Event()
        self.minted_a = None
        self.errors = []
        self.results = {}
        broker.mint_authenticated_context = self._mint

    def _mint(self, *args, **kwargs):
        handle = self.real_mint(*args, **kwargs)
        if threading.current_thread().name == "renewal-A":
            self.minted_a = handle
            self.a_minted.set()
            assert self.release_a.wait(10), "A was never released"
        return handle

    def run(self, name, call):
        def target():
            try:
                self.results[name] = call()
            except BaseException as exc:  # noqa: BLE001 - the court reports it
                self.errors.append((name, exc))
        thread = threading.Thread(target=target, name="renewal-" + name, daemon=True)
        thread.start()
        return thread


def _race_after_revoking_the_held_handle(minimum_a=5.0):
    broker, session = _session()
    held = session.context()
    broker.revoke(held)                        # both A and B must renew
    race = _Race(broker)
    a = race.run("A", lambda: session.context(minimum_validity_seconds=minimum_a))
    assert race.a_minted.wait(10), "A never reached its mint"
    b = race.run("B", lambda: session.context(minimum_validity_seconds=5))
    b.join(10)
    assert not b.is_alive() and not race.errors, race.errors
    return broker, session, race, a


def _finish(race, thread):
    race.release_a.set()
    thread.join(10)
    assert not thread.is_alive(), "A did not finish"
    assert not race.errors, race.errors


def test_a_renewal_that_lost_the_race_shares_the_winners_valid_handle():
    broker, session, race, a = _race_after_revoking_the_held_handle()
    winner = race.results["B"]
    assert winner is not race.minted_a
    _finish(race, a)
    assert race.results["A"] is winner         # A shares B, its own handle is never used
    broker.resolve(winner)
    assert session.context() is winner


def test_a_renewal_never_returns_a_winner_that_was_revoked_meanwhile():
    broker, session, race, a = _race_after_revoking_the_held_handle()
    winner = race.results["B"]
    broker.revoke(winner)                      # B's handle dies before A resumes
    _finish(race, a)
    assert race.results["A"] is not winner
    assert race.results["A"] is race.minted_a  # A falls back to its own fresh handle
    broker.resolve(race.results["A"])
    later = session.context()
    broker.resolve(later)
    assert later is race.minted_a


def test_a_renewal_never_returns_a_winner_too_close_to_its_expiry():
    broker, session, race, a = _race_after_revoking_the_held_handle(minimum_a=30.0)
    winner = race.results["B"]
    # B is still valid, but for less than A's minimum validity.
    entry = broker._entries[winner]
    broker._entries[winner] = dataclasses.replace(entry, expires_at=time.time() + 10.0)
    _finish(race, a)
    assert race.results["A"] is race.minted_a
    assert broker.resolve(race.results["A"]).expires_at - time.time() > 30.0
