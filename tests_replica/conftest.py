"""One built application, forked per test.

Every court that wants the application called build_universal_application
and paid ~15 seconds to rebuild 162,904 cells from the same map -- fifty
builds per file put HALF AN HOUR of pure fixture cost in front of the
courts. Commits are copy-on-write over immutable maps, so one template
build can hand every test its own store that shares the base and can
never write into it.

The fork is exact isolation, not a shared fixture: a forked store's
commits land in its own overlay, and the registry is replaced with a
copy of its one mutable member, so a test that provisions a view session
cannot leak it into the next test. Any call that passes its own store,
key provider, court workspace, or runner falls through to the real build.
"""
from __future__ import annotations

import copy
import dataclasses
import threading

import nodelang.universal_application as _application_module
from nodelang.universal_application import (
    build_universal_application as _real_build,
)


_TEMPLATES: dict[str, tuple[object, object]] = {}
_TEMPLATE_LOCK = threading.Lock()


def _fork_store(template):
    forked = copy.copy(template)
    for name in list(vars(forked) if hasattr(forked, "__dict__") else ()):
        value = getattr(forked, name)
        if isinstance(value, threading.RLock().__class__):
            object.__setattr__(forked, name, threading.RLock())
        elif isinstance(value, (dict, list, set)):
            # type(value)(value), not dict(value): the store keeps
            # OrderedDicts whose move_to_end a plain dict lacks.
            object.__setattr__(forked, name, type(value)(value))
    return forked


def _fork_registry(template):
    return dataclasses.replace(
        template, view_sessions=dict(template.view_sessions)
    )


def _mutable_state(obj):
    return {
        name: (
            dict(value) if isinstance(value, dict)
            else list(value) if isinstance(value, list)
            else set(value)
        )
        for name, value in vars(obj).items()
        if isinstance(value, (dict, list, set))
    }


def _restore_state(obj, saved):
    for name, value in saved.items():
        held = getattr(obj, name)
        if isinstance(held, dict):
            held.clear(); held.update(value)
        elif isinstance(held, list):
            held[:] = value
        else:
            held.clear(); held.update(value)


import pytest


@pytest.fixture(autouse=True)
def _template_broker_state_rolls_back():
    """The brokers are identity: a verified snapshot carries ITS broker
    and later checks it by `is`, so a forked broker fails "broker
    differs" while a shared one leaks generations -- one test's grants
    made every other fork's signed material read as stale, 36 courts at
    once. The object stays shared; its runtime bookkeeping (handles,
    generations, sessions) is saved before each test and restored after.
    """
    saved = []
    with _TEMPLATE_LOCK:
        held = list(_TEMPLATES.values())
    for _store, registry in held:
        for broker in (
            registry.authorization.broker,
            registry.authorization.relationship_broker,
        ):
            saved.append((broker, _mutable_state(broker)))
    # The verified-authority cache is keyed by id(authority) with a
    # 120-second TTL. Forks share the authorization object, so one
    # test's verified snapshot -- its relationships, its inspector, its
    # promotions -- was served to the next test as current authority.
    _application_module._AUTHORITY_SNAPSHOT_CACHE.clear()
    yield
    for broker, state in saved:
        _restore_state(broker, state)
    _application_module._AUTHORITY_SNAPSHOT_CACHE.clear()


def _forking_build(map_path, store=None, **kwargs):
    if store is not None or any(value is not None for value in kwargs.values()):
        return _real_build(map_path, store, **kwargs)
    key = str(map_path)
    with _TEMPLATE_LOCK:
        held = _TEMPLATES.get(key)
    if held is None:
        built_store, built_registry = _real_build(map_path)
        with _TEMPLATE_LOCK:
            _TEMPLATES[key] = (built_store, built_registry)
        held = (built_store, built_registry)
    template_store, template_registry = held
    return _fork_store(template_store), _fork_registry(template_registry)


_application_module.build_universal_application = _forking_build

# Courts import the symbol directly at module load; conftest loads first,
# so their `from ... import build_universal_application` binds the fork.
build_universal_application = _forking_build


# ---------------------------------------------------------------------------
# No court may reach a live host. On 2026-09-06 the founder had Revit 2025
# open with the ArchHub broker on :48884 while the library shape court ran
# the Revit authoring cards with nothing stubbed: the C# went to his model
# (it failed closed only because of a compile error and a nested
# transaction). A court that can write into the founder's model is not a
# court. Every test starts with the hosts unreachable; a test that needs a
# host fakes it with its own monkeypatch, which wins over this one.
import pytest as _pytest


@_pytest.fixture(autouse=True)
def no_live_hosts(monkeypatch):
    import nodelang.clean_revit_adapter as _revit
    import nodelang.host_brokers as _hosts
    import nodelang.library_engines as _library

    def _refuse(*_args, **_kwargs):
        raise AssertionError("a court tried to reach a live host")

    monkeypatch.setattr(_revit, "live_sessions", lambda: [])
    monkeypatch.setattr(_revit, "_call", _refuse)
    monkeypatch.setattr(_hosts, "_com_alive", lambda _prog_id: False)
    monkeypatch.setattr(_hosts, "_port_open", lambda *_a, **_k: False)
    monkeypatch.setattr(_library, "_OUTLOOK", [lambda: None])
    monkeypatch.setattr(_library, "_NOTIFY_SURFACE", [])
