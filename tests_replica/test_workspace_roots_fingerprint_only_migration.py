"""Option 1 v3 migration coverage: a GENUINE pre-attestation graph enrolls with
no crash and no change of key identity.

The founder's live graph published the key definition BEFORE the enrollment
record existed, so it declares only key_id + fingerprint, and _publish retains
it unchanged. v2 pinned mode/enrolled_by/enrolled_at as undeclared overrides ->
InvalidCell "instance override targets an undeclared mutable parameter". v3
revises that definition through the product's own revision path (key identity
unchanged) so the FIRST enrollment records the real owner-opened attestation;
an EXISTING fingerprint-only pin stays "legacy" with no re-pin.

RED on 8c0d3101: test_first_enrollment_on_the_old_graph... raises InvalidCell.
Uses fake ncrypt only (old_schema_world); the key store is never opened.
"""
import uuid

import pytest

from nodelang import workspace_roots_catalogue as roots
from tests_replica.test_workspace_roots_window_approval import (  # noqa: F401
    _active, _register,
    _the_key_store_is_never_opened_by_a_graph_court, old_schema_world)


def _enrollment(world):
    return roots.read_enrollment(world["authority"], world["catalogue"], caller=world["caller"])


def _key_cells(world):
    governance = roots._governance(world["authority"], world["caller"])
    projection = roots.read_contained_scope(
        world["authority"], governance, scope_root=governance, caller=world["caller"])
    return sum(1 for instance in projection.instances.values()
               if instance.get("definition") == world["catalogue"].key_definition)


def _legacy_pin(world, fingerprint):
    """The pin a pre-attestation graph wrote: key_id + fingerprint only,
    instantiated against the OLD definition (which declares nothing else)."""
    roots.instantiate_definition(
        world["authority"], world["catalogue"].key_definition,
        {"key_id": roots.KEY_ID, "fingerprint": fingerprint},
        scope_root=roots._governance(world["authority"], world["caller"]),
        caller=world["caller"], command_id=str(uuid.uuid4()))


def test_publish_retains_the_old_two_field_key_definition(old_schema_world):
    current = roots.read_definition(
        old_schema_world["authority"], old_schema_world["catalogue"].key_definition,
        caller=old_schema_world["caller"])
    assert set(current.contracts["parameters"]) == {"key_id", "fingerprint"}


def test_first_enrollment_on_the_old_graph_records_the_full_attestation(old_schema_world):
    world = old_schema_world
    world["key"].exists = True
    # v2 raised InvalidCell (undeclared override) right here; v3 revises first.
    view = _register(world, "alpha")
    assert view["projection"] == "match"
    record = _enrollment(world)
    assert record["mode"] == roots.OWNER_OPENED                  # real, not degraded to legacy
    assert record["enrolled_by"]                                 # the verified settings principal
    assert record["enrolled_at"].endswith("Z") and len(record["enrolled_at"]) == 20
    assert record["fingerprint"] == world["key"].fingerprint()   # key identity UNCHANGED
    assert _active(world) == (["alpha"], world["key"].fingerprint())
    assert _key_cells(world) == 1


def test_existing_fingerprint_only_pin_stays_legacy_without_re_pin(old_schema_world):
    world = old_schema_world
    world["key"].exists = True
    fingerprint = world["key"].fingerprint()
    _legacy_pin(world, fingerprint)                              # a real pre-attestation pin
    assert _enrollment(world) == {"fingerprint": fingerprint, "mode": "legacy",
                                  "enrolled_by": "", "enrolled_at": ""}
    # A later add commits against the existing pin: no crash, no re-pin, no re-identity.
    view = _register(world, "alpha")
    assert view["projection"] == "match"
    assert _active(world) == (["alpha"], fingerprint)
    assert _enrollment(world)["mode"] == "legacy"                # unchanged
    assert _key_cells(world) == 1                                # no second key cell


def _published_with_fields(world):
    current = roots.read_definition(
        world["authority"], world["catalogue"].key_definition, caller=world["caller"])
    return (current.lifecycle == "published"
            and {"mode", "enrolled_by", "enrolled_at"} <= set(current.contracts["parameters"]))


def _recovers_after(world, monkeypatch, fail_on):
    """Inject a promote_definition failure on the given promotion, prove the first
    enrollment raises and writes no pin, then restore promotion and prove the retry
    recovers: full attestation, published definition, key identity, single pin."""
    world["key"].exists = True
    real = roots.promote_definition
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == fail_on:
            raise RuntimeError("injected promotion failure")
        return real(*args, **kwargs)

    monkeypatch.setattr(roots, "promote_definition", flaky)
    with pytest.raises(RuntimeError):
        _register(world, "alpha")
    assert _active(world)[1] is None                 # no pin written on the failed attempt

    monkeypatch.setattr(roots, "promote_definition", real)   # promotion restored
    view = _register(world, "alpha")                 # retry recovers through the same authority
    assert view["projection"] == "match"
    record = _enrollment(world)
    assert record["mode"] == roots.OWNER_OPENED
    assert record["enrolled_by"]
    assert record["fingerprint"] == world["key"].fingerprint()   # key identity preserved
    assert _active(world) == (["alpha"], world["key"].fingerprint())
    assert _key_cells(world) == 1                     # no duplicate pin
    assert _published_with_fields(world)              # no unpublishable remnant


def test_recovers_from_interruption_after_revise(old_schema_world, monkeypatch):
    # The WIP revision commits, the FIRST promotion (WIP -> shared) is interrupted.
    _recovers_after(old_schema_world, monkeypatch, fail_on=1)


def test_recovers_from_interruption_after_share(old_schema_world, monkeypatch):
    # The shared promotion commits, the SECOND promotion (shared -> published) fails.
    _recovers_after(old_schema_world, monkeypatch, fail_on=2)
