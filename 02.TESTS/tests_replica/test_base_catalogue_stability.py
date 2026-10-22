"""Coordination binding does no catalogue installation or full-graph traversal."""
from types import SimpleNamespace

from nodelang.clean_coordination_host import CleanCoordinationHost


def test_coordination_reopen_is_read_only_and_does_not_walk_the_graph():
    class Store:
        def snapshot(self):
            raise AssertionError('coordination must not traverse or install a catalogue')
        def commit(self, *_args, **_kwargs):
            raise AssertionError('binding must not change the desktop graph')
    owner = SimpleNamespace(universal_store=Store())
    first, second = CleanCoordinationHost(owner), CleanCoordinationHost(owner)
    assert first.store is second.store is owner.universal_store
