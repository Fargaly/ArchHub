"""Interleaved user edits and repeated first-run admission remain safe."""
from contextlib import contextmanager

import pytest

from nodelang import universal_pipeline as pipeline
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import build_universal_application, edit_universal_property
from nodelang.universal_cell import InvalidCell


def test_seed_never_overwrites_a_row_filled_between_preparation_and_admission(monkeypatch):
    store, registry = build_universal_application(resolve_map_path())
    monkeypatch.setattr(pipeline, '_SEED', pipeline._SEED[:1])
    monkeypatch.setattr(pipeline, '_LENS_SEED', ())
    monkeypatch.setattr(pipeline, '_ALL_SEED', (pipeline._SEED[0],))
    try:
        pipeline.seed_wall_pipeline(store, registry)
        properties = pipeline._owner_properties(store.snapshot(), registry)
        root, held = next((root, rows) for root, rows in properties.items()
            if rows.get('seed', ('', ''))[1] == 'sketch-lines')
        relation = held['threshold'][0]
        edit_universal_property(store, registry, relation, '')
        interleaved = []

        @contextmanager
        def guard():
            if not interleaved:
                edit_universal_property(store, registry, relation, 'user threshold')
                interleaved.append(True)
            yield

        pipeline.seed_wall_pipeline(store, registry, settle_guard=guard)
        assert interleaved
        assert pipeline._owner_properties(store.snapshot(), registry)[root]['threshold'][1] == 'user threshold'
    finally:
        store.close()


def test_competing_seed_returns_a_visible_error_and_releases_its_turn(monkeypatch):
    # Invoke the public owner recursively at the real prepare boundary. This
    # models the HTTP repair arriving while startup already owns the seed.
    from nodelang.universal_cell import CellStore
    store = CellStore()
    calls = []

    def prepare(owner, registry, **kwargs):
        with pytest.raises(InvalidCell, match='already in progress'):
            pipeline.seed_wall_pipeline(owner, registry)
        calls.append('prepared')
        return {'ok': True}

    monkeypatch.setattr(pipeline, '_seed_wall_pipeline', prepare)
    try:
        assert pipeline.seed_wall_pipeline(store, None) == {'ok': True}
        assert pipeline.seed_wall_pipeline(store, None) == {'ok': True}
        assert calls == ['prepared', 'prepared']
    finally:
        store.close()


def test_revoked_context_cannot_enter_a_seed_write():
    from nodelang.cell_authorization import AuthenticationBroker, AuthorizationDenied
    broker = AuthenticationBroker()
    context = broker.mint_authenticated_context(subject_root='subject',
        tenant_root=None, assurance_root='assurance')
    broker.revoke(context)
    writes = []
    with pytest.raises(AuthorizationDenied):
        pipeline._persist(lambda: writes.append('committed'),
            guard=lambda: broker.live_context(context))
    assert writes == []
