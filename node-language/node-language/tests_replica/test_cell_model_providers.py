"""Courts for providers: keys by reference, failures classified, calls metered."""
from __future__ import annotations

import pytest

from nodelang.cell_brain_secrets import admit_secret
from nodelang.cell_model_providers import (
    ADMITTED_PROVIDERS,
    FATAL,
    PROVIDERS_ROOT,
    RATE_LIMITED,
    RETRYABLE,
    classify_failure,
    is_available,
    key_entry_for,
    record_call,
    record_failure,
    register_provider,
    registered,
    usage,
)
from nodelang.universal_cell import CellStore, InvalidCell

NOW = 1_000_000


def _store():
    store = CellStore()
    admit_secret(
        store, name="anthropic",
        reference="op://archhub/models/anthropic", custody="operator-vault",
    )
    register_provider(store, provider="anthropic", key_entry_name="anthropic")
    return store


def test_a_provider_points_at_a_vault_entry_never_a_key():
    store = _store()
    assert registered(store.snapshot()) == ("anthropic",)
    assert key_entry_for(store.snapshot(), "anthropic") == "anthropic"


def test_a_provider_whose_key_was_never_put_in_custody_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        register_provider(provider="openai", key_entry_name="openai", store=store)


def test_a_provider_that_is_not_admitted_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        register_provider(store, provider="guesswork", key_entry_name="anthropic")
    assert "guesswork" not in ADMITTED_PROVIDERS


def test_registering_the_same_provider_twice_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        register_provider(store, provider="anthropic", key_entry_name="anthropic")


def test_every_failure_kind_means_something():
    assert classify_failure("timeout") == RETRYABLE
    assert classify_failure("rate-limit") == RATE_LIMITED
    assert classify_failure("unauthorized") == FATAL


def test_an_unclassified_failure_is_refused_rather_than_retried_blindly():
    with pytest.raises(InvalidCell):
        classify_failure("something-went-wrong")


def test_a_rate_limited_provider_is_unavailable_until_its_cooldown_passes():
    store = _store()
    severity, until = record_failure(
        store, provider="anthropic", kind="rate-limit", now=NOW)
    assert severity == RATE_LIMITED
    assert is_available(store.snapshot(), "anthropic", NOW) is False
    assert is_available(store.snapshot(), "anthropic", until) is True


def test_a_fatal_failure_cools_down_far_longer_than_a_retryable_one():
    store = _store()
    _severity, retry_until = record_failure(
        store, provider="anthropic", kind="timeout", now=NOW)
    _severity, fatal_until = record_failure(
        store, provider="anthropic", kind="unauthorized", now=NOW)
    assert fatal_until > retry_until


def test_a_cooling_provider_must_not_be_called():
    store = _store()
    record_failure(store, provider="anthropic", kind="rate-limit", now=NOW)
    with pytest.raises(InvalidCell):
        record_call(store, provider="anthropic", tokens=10, now=NOW)


def test_every_call_is_metered():
    store = _store()
    record_call(store, provider="anthropic", tokens=120, now=NOW)
    record_call(store, provider="anthropic", tokens=80, now=NOW)
    assert usage(store.snapshot(), "anthropic") == (
        usage(store.snapshot(), "anthropic"))
    metered = usage(store.snapshot(), "anthropic")
    assert (metered.calls, metered.tokens) == (2, 200)


def test_a_call_that_reports_no_real_token_count_is_refused():
    store = _store()
    with pytest.raises(InvalidCell):
        record_call(store, provider="anthropic", tokens=-1, now=NOW)
    with pytest.raises(InvalidCell):
        record_call(store, provider="anthropic", tokens=True, now=NOW)


def test_an_unregistered_provider_answers_nothing():
    store = _store()
    with pytest.raises(InvalidCell):
        usage(store.snapshot(), "openai")


def test_no_registry_registers_nothing():
    store = CellStore()
    assert PROVIDERS_ROOT not in store.snapshot().cells
    assert registered(store.snapshot()) == ()
