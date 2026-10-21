"""Option 1 (owner-opened): the first workspace-roots key is admitted by the window
opening the owner-protected key ONCE, non-silently (the Windows prompt is the owner's
consent); the public half is read from that opened handle and pinned. The enrollment
is recorded in the graph -- mode "owner-opened", who, when, fingerprint -- and shown
in Settings. Re-enrollment requires the existing key. Owner never opens the key.

Graph-level court (the signing open-flag court is test_workspace_roots_owner_opens_once).
RED on a9e534ea (no window ceremony) and a44a4e8e (no enrollment record / no mode).
"""
import uuid

import pytest

from nodelang import workspace_roots_catalogue as roots
from tests_replica.test_workspace_roots_window_approval import (  # noqa: F401
    _Key, _active, _change, _offer, _register,
    _the_key_store_is_never_opened_by_a_graph_court, world)


def _enrollment(world):
    return roots.read_enrollment(world["authority"], world["catalogue"], caller=world["caller"])


def test_first_enrollment_is_recorded_as_owner_opened(world):
    view = _register(world, "alpha")
    record = view["enrollment"]
    assert record is not None, "first enrollment left no owner-opened record"
    assert record["mode"] == roots.OWNER_OPENED                 # the owner opened the key
    assert record["fingerprint"] == world["key"].fingerprint()  # the key fingerprint
    assert record["enrolled_by"]                                # who (non-empty)
    assert record["enrolled_at"].endswith("Z") and len(record["enrolled_at"]) == 20  # when
    assert _enrollment(world) == record                         # same record in the graph
    assert _active(world) == (["alpha"], world["key"].fingerprint())


def test_the_record_is_shown_on_a_plain_list(world):
    _register(world, "alpha")
    view = world["owner"]({"action": "list"})
    assert view["enrollment"]["mode"] == roots.OWNER_OPENED
    assert view["enrollment"]["fingerprint"] == world["key"].fingerprint()


def test_re_enrollment_requires_the_existing_key(world):
    _register(world, "alpha")
    first = _enrollment(world)
    substitute = _Key()
    change = _change(world, "beta")
    with pytest.raises(roots.WorkspaceRootRefused):
        world["owner"]({"action": "prepare", "change": change, **_offer(substitute, check=True)},
                       verifier=substitute)
    with pytest.raises(roots.WorkspaceRootRefused):
        world["owner"]({**change,
                        "signature": substitute.sign(roots.canonical(
                            roots.snapshot_body([], first["fingerprint"]))),
                        "command_id": str(uuid.uuid4()), **_offer(substitute, check=True)},
                       verifier=substitute)
    assert _active(world)[1] == world["key"].fingerprint()
    assert _enrollment(world) == first


def test_a_later_add_keeps_the_same_record(world):
    _register(world, "alpha")
    first = _enrollment(world)
    _register(world, "beta")
    assert sorted(_active(world)[0]) == ["alpha", "beta"]
    assert _enrollment(world) == first  # one enrollment, recorded once, unchanged
