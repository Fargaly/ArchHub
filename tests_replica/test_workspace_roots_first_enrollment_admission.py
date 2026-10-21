"""Option 1 v2 gate: the FIRST workspace enrollment is admitted only through the
authenticated transport. clean_coordination_host verifies the SETTINGS identity and
threads it to the owner as trusted internal context (never a body field); owner_change
mints a single-use, owner-signed admission ticket at prepare, bound to the verified
principal, this instance, the offered key, the exact change and revision, with an
expiry, and verifies+consumes it at commit. A direct-to-owner call (no authenticated
admission), or a missing/forged/expired/replayed ticket, is refused BEFORE any pin,
graph or file effect -- even with a valid self-signed key and KEY_CHECK.

RED on 36b1700d (option 1 with no admission gate: owner_change has no `admission`,
no ticket, and the fixture has no owner_direct) -> GREEN on v2.
"""
import time

import pytest

from nodelang import workspace_roots_catalogue as roots
from tests_replica.test_workspace_roots_window_approval import (  # noqa: F401
    _Key, _active, _change, _offer, _register,
    _the_key_store_is_never_opened_by_a_graph_court, world)


def _enrollment(world):
    return roots.read_enrollment(world["authority"], world["catalogue"], caller=world["caller"])


def _prepare(world, name="alpha"):
    world["key"].exists = True
    change = _change(world, name)
    prepared = world["owner"](
        {"action": "prepare", "change": change, **_offer(world["key"], check=True)}
    )["prepared"]
    return change, prepared


def test_a_direct_to_owner_first_enrollment_prepare_is_refused(world):
    # A direct call to the owner that skipped the authenticated window admission: no
    # verified principal reaches owner_change, so even the prepare is refused.
    world["key"].exists = True
    with pytest.raises(roots.WorkspaceRootRefused, match="admission is required"):
        world["owner_direct"]({"action": "prepare", "change": _change(world, "alpha"),
                               **_offer(world["key"], check=True)})
    assert _active(world)[1] is None        # nothing pinned
    assert _enrollment(world) is None       # nothing enrolled


def test_a_direct_commit_is_refused_even_carrying_a_valid_ticket(world):
    # Prepare legitimately (authenticated) to obtain a genuine ticket, then replay the
    # whole commit through a DIRECT call: the missing authenticated principal is caught
    # before the ticket is ever examined, so a stolen ticket buys nothing.
    change, prepared = _prepare(world)
    commit = {**change, "signature": world["key"].sign(roots.canonical(prepared["body"])),
              **_offer(world["key"], check=True),
              "admission_ticket": prepared["admission_ticket"]}
    with pytest.raises(roots.WorkspaceRootRefused, match="admission is required"):
        world["owner_direct"](commit)
    assert _active(world)[1] is None
    assert _enrollment(world) is None


def test_a_commit_without_the_ceremony_ticket_is_refused(world):
    # Authenticated principal present, but the single-use ceremony ticket is absent: the
    # principal alone does not enroll -- the owner's own admission must be carried back.
    change, prepared = _prepare(world)
    commit = {**change, "signature": world["key"].sign(roots.canonical(prepared["body"])),
              **_offer(world["key"], check=True)}            # no admission_ticket
    with pytest.raises(roots.WorkspaceRootRefused, match="forged, expired"):
        world["owner"](commit)
    assert _active(world)[1] is None
    assert _enrollment(world) is None


def test_a_forged_admission_ticket_is_refused(world):
    # The real statement, a bogus signature: the owner re-signs and compares, so a
    # ticket it did not issue never verifies.
    change, prepared = _prepare(world)
    forged = {"statement": dict(prepared["admission_ticket"]["statement"]),
              "signature": "00" * 64}
    commit = {**change, "signature": world["key"].sign(roots.canonical(prepared["body"])),
              **_offer(world["key"], check=True), "admission_ticket": forged}
    with pytest.raises(roots.WorkspaceRootRefused, match="forged, expired"):
        world["owner"](commit)
    assert _active(world)[1] is None
    assert _enrollment(world) is None


def test_an_expired_admission_ticket_is_refused(world):
    # An owner-signed ticket whose expiry has passed: re-signed correctly, but stale.
    change, prepared = _prepare(world)
    statement = dict(prepared["admission_ticket"]["statement"])
    statement["expiry"] = int(time.time()) - 10
    authority = world["authority"]
    signature = authority.key_provider.sign(
        authority.manifest.key_id, authority.manifest.key_version, roots.canonical(statement))
    expired = {"statement": statement, "signature": signature}
    commit = {**change, "signature": world["key"].sign(roots.canonical(prepared["body"])),
              **_offer(world["key"], check=True), "admission_ticket": expired}
    with pytest.raises(roots.WorkspaceRootRefused, match="forged, expired"):
        world["owner"](commit)
    assert _active(world)[1] is None
    assert _enrollment(world) is None


def test_an_exact_ticket_replay_does_not_re_enroll_or_re_pin(world):
    # Single-use is enforced by pinning once: once the first enrollment pins the
    # key, the first-enrollment branch never runs again, so the owner's ticket is
    # never re-verified. Replaying the EXACT same ticket on a later add is inert --
    # the add is an ordinary authenticated change; nothing re-pins or re-enrolls.
    world["key"].exists = True
    key = world["key"]
    change_a = _change(world, "alpha")
    prep = world["owner"]({"action": "prepare", "change": change_a,
                           **_offer(key, check=True)})["prepared"]
    ticket = prep["admission_ticket"]
    world["owner"]({**change_a, "signature": key.sign(roots.canonical(prep["body"])),
                    **_offer(key, check=True), "admission_ticket": ticket})
    pinned = key.fingerprint()
    record = _enrollment(world)
    assert record["mode"] == roots.OWNER_OPENED
    assert _active(world) == (["alpha"], pinned)

    change_b = _change(world, "beta")
    prep_b = world["owner"]({"action": "prepare", "change": change_b,
                             **_offer(key, check=True)})["prepared"]
    assert "admission_ticket" not in prep_b            # none minted once a pin exists
    world["owner"]({**change_b, "signature": key.sign(roots.canonical(prep_b["body"])),
                    **_offer(key, check=True), "admission_ticket": ticket})  # replayed, ignored
    assert sorted(_active(world)[0]) == ["alpha", "beta"]
    assert _active(world)[1] == pinned                 # the key was never re-pinned
    assert _enrollment(world) == record                # one enrollment, unchanged


def test_a_retried_enrollment_commit_applies_no_second_effect(world):
    # Settlement: re-submitting the exact same first-enrollment commit (same ticket,
    # same change) applies no second effect -- it is refused, and the pin and the
    # enrollment record are unchanged. No blind retry re-runs the enrollment.
    world["key"].exists = True
    key = world["key"]
    change = _change(world, "alpha")
    prep = world["owner"]({"action": "prepare", "change": change,
                           **_offer(key, check=True)})["prepared"]
    commit = {**change, "signature": key.sign(roots.canonical(prep["body"])),
              **_offer(key, check=True), "admission_ticket": prep["admission_ticket"]}
    world["owner"](dict(commit))                       # first commit: enrolls + pins
    record = _enrollment(world)
    with pytest.raises(roots.WorkspaceRootRefused):
        world["owner"](dict(commit))                   # exact retry
    assert _active(world) == (["alpha"], key.fingerprint())
    assert _enrollment(world) == record
