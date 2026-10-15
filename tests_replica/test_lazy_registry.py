"""First-open singleflight must never hold the cross-scope inventory lock."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from nodelang.lazy_application_registry import VerifiedLazyMapping, VerifiedLazyViews


def test_loaded_view_inventory_finishes_while_another_view_loader_is_blocked():
    entered, release = Event(), Event()
    existing, loaded = object(), object()

    def load(key):
        entered.set()
        assert release.wait(3)
        return loaded

    views = VerifiedLazyViews({"existing": existing}, load)
    with ThreadPoolExecutor(max_workers=2) as readers:
        loading = readers.submit(lambda: views["next"])
        try:
            assert entered.wait(3)
            inventory = readers.submit(views.loaded_values)
            assert inventory.result(timeout=1) == (existing,)
        finally:
            release.set()
        assert loading.result(timeout=3) is loaded


def test_eight_first_opens_share_one_loader_without_blocking_inventory():
    entered, release = Event(), Event()
    ready = Barrier(8)
    calls = []
    loaded = object()

    def load(key):
        calls.append(key)
        entered.set()
        assert release.wait(3)
        return loaded

    views = VerifiedLazyMapping({}, load)

    def open_view():
        ready.wait(timeout=3)
        return views["next"]

    with ThreadPoolExecutor(max_workers=9) as readers:
        futures = [readers.submit(open_view) for _ in range(8)]
        try:
            assert entered.wait(3)
            assert readers.submit(views.loaded_values).result(timeout=1) == ()
            assert calls == ["next"]
        finally:
            release.set()
        assert all(future.result(timeout=3) is loaded for future in futures)
    assert calls == ["next"]


def test_failed_verified_read_is_not_cached_and_next_open_retries():
    calls = []
    loaded = object()

    def load(key):
        calls.append(key)
        if len(calls) == 1:
            raise ValueError("verified read refused")
        return loaded

    views = VerifiedLazyMapping({}, load)
    with pytest.raises(ValueError, match="verified read refused"):
        views["next"]
    assert views.loaded_values() == ()
    assert views["next"] is loaded
    assert views["next"] is loaded
    assert calls == ["next", "next"]


def test_invalidation_during_load_reloads_instead_of_publishing_old_values():
    entered, release = Event(), Event()
    source = {"value": "before"}
    calls = []

    def load(key):
        value = source["value"]
        calls.append(value)
        entered.set()
        assert release.wait(3)
        return value

    views = VerifiedLazyMapping({}, load)
    with ThreadPoolExecutor(max_workers=1) as readers:
        loading = readers.submit(lambda: views["next"])
        try:
            assert entered.wait(3)
            views.invalidate()
            source["value"] = "after"
        finally:
            release.set()
        assert loading.result(timeout=3) == "after"
    assert views["next"] == "after"
    assert calls == ["before", "after"]


def test_concurrent_provisioning_keeps_its_published_verified_view():
    entered, release = Event(), Event()
    from_loader, provisioned = object(), object()

    def load(key):
        entered.set()
        assert release.wait(3)
        return from_loader

    views = VerifiedLazyViews({}, load)
    with ThreadPoolExecutor(max_workers=1) as readers:
        loading = readers.submit(lambda: views["next"])
        try:
            assert entered.wait(3)
            views["next"] = provisioned
        finally:
            release.set()
        assert loading.result(timeout=3) is provisioned
    assert views["next"] is provisioned


def test_slow_key_enumeration_does_not_hold_the_loaded_inventory_lock():
    entered, release = Event(), Event()
    existing = object()

    def keys():
        entered.set()
        assert release.wait(3)
        return ("next",)

    views = VerifiedLazyMapping({"existing": existing}, lambda key: key, keys)
    with ThreadPoolExecutor(max_workers=2) as readers:
        enumerating = readers.submit(lambda: tuple(views))
        try:
            assert entered.wait(3)
            assert readers.submit(views.loaded_values).result(timeout=1) == (existing,)
        finally:
            release.set()
        assert enumerating.result(timeout=3) == ("existing", "next")
