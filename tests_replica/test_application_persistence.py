"""Forcing tests for persistent node-native application WIP state."""
from __future__ import annotations

import ctypes
import gzip
import json
import sys
import threading
import urllib.request
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang.application import (APPLICATION_SCHEMA_VERSION,
                                  build_archhub_application)  # noqa: E402
from nodelang.application_server import ApplicationServer  # noqa: E402
from nodelang.cell_browser_sessions import read_browser_session  # noqa: E402
from nodelang.cell_exclusive_ownership import (  # noqa: E402
    read_ownership,
    verify_ownership_authority,
)
from nodelang.persistence import (load_snapshot, save_snapshot,
                                  save_snapshot_cooperative)  # noqa: E402
import nodelang.windows_cng_signing_provider as cng  # noqa: E402
from nodelang.universal_cell import (  # noqa: E402
    Cell as UniversalCell,
    CellStore as UniversalCellStore,
    InvalidCell as UniversalInvalidCell,
)


def _delete_court_checkpoint_key(key_name):
    assert key_name.startswith('ArchHub.Court.')
    api = cng._api()
    provider = api.open_provider(cng._PROVIDERS[cng.SOFTWARE_PROVIDER_ID][0])
    key = None
    try:
        key = api.handle_type()
        status = api.library.NCryptOpenKey(
            provider, ctypes.byref(key), key_name, 0, cng._NCRYPT_SILENT_FLAG
        )
        if api.code(status) == cng._NTE_BAD_KEYSET:
            return
        api.require('open application court key for cleanup', status)
        api.require(
            'delete isolated application court key',
            api.library.NCryptDeleteKey(key, 0),
        )
        key = None
    finally:
        if key is not None:
            api.free(key)
        api.free(provider)


@pytest.fixture
def cng_checkpoint_court(tmp_path):
    key_name = 'ArchHub.Court.%s' % uuid.uuid4()
    values = {
        'checkpoint': tmp_path / 'universal-checkpoint.json',
        'authority': tmp_path / 'universal-checkpoint-authority.sqlite3',
        'key_name': key_name,
    }
    yield values
    _delete_court_checkpoint_key(key_name)


def test_snapshot_round_trip_keeps_the_single_graph_and_focus(tmp_path):
    path = tmp_path / 'archhub-state.json.gz'
    store, registry = build_archhub_application()
    selected = list(registry['cards'])[4]
    store.edit(registry['focus'], ['body', 'floor', 'value'], selected)

    save_snapshot(store, path)
    restored, restored_registry = load_snapshot(path)

    assert restored.pull(restored_registry['focus']) == selected
    assert len(restored.nodes) == len(store.nodes)
    assert restored_registry['app'] == registry['app']
    assert restored_registry['website']['session'] == registry['website']['session']


def test_server_mutations_survive_a_real_server_restart(
    tmp_path, cng_checkpoint_court
):
    path = tmp_path / 'archhub-state.json.gz'
    store, registry = build_archhub_application()
    selected = list(registry['cards'])[5]
    server = ApplicationServer(
        store=store, registry=registry, state_path=path,
        universal_checkpoint_path=cng_checkpoint_court['checkpoint'],
        universal_checkpoint_authority_path=cng_checkpoint_court['authority'],
        universal_checkpoint_key_name=cng_checkpoint_court['key_name'],
        universal_checkpoint_provider_id=cng.SOFTWARE_PROVIDER_ID,
        allow_legacy_mutations=True,
    ).start()
    try:
        checkpoint_binding = server.universal_checkpoint_binding_root
        assert checkpoint_binding in server.universal_store.snapshot().cells
        request = urllib.request.Request(
            server.url + '/api/activate', method='POST',
            headers={
                'Content-Type': 'application/json',
                'X-ArchHub-Session': server.browser_session_token,
            },
            data=json.dumps({'ui_id': registry['cards'][selected]}).encode('utf-8'))
        response = json.loads(urllib.request.urlopen(request, timeout=10).read())
        assert response['ok'] is True
        gesture = urllib.request.Request(
            server.url + '/api/universal/gesture', method='POST',
            headers={
                'Content-Type': 'application/json',
                'X-ArchHub-Session': server.browser_session_token,
            },
            data=json.dumps({
                'viewport': {'pan_x': 73, 'pan_y': -21, 'zoom': 1.4},
            }).encode('utf-8'),
        )
        universal_response = json.loads(
            urllib.request.urlopen(gesture, timeout=10).read()
        )
        assert universal_response['ok'] is True
        universal_revision = server.universal_store.revision
        health_request = urllib.request.Request(
            server.url + '/api/universal/health',
            headers={'X-ArchHub-Session': server.browser_session_token},
        )
        cloud_health = json.loads(urllib.request.urlopen(
            health_request, timeout=10).read())
        assert cloud_health['ok'] is True
        assert cloud_health['legacy_parallel_runtime'] is True
        assert cloud_health['core_values']['root'] == 'app:core-values:v1'
        assert cloud_health['core_values']['lifecycle'] == 'WIP'
        assert set(cloud_health['core_values']['coverage'].values()) == {'partial'}
        assert cloud_health['checkpoint_binding'] == checkpoint_binding
        browser_session_root = server.browser_session_root
        runtime_ownership_root = server._runtime_ownership_root
    finally:
        server.close()
    closed_revision = server.universal_store.revision
    assert closed_revision > universal_revision
    closed_session = read_browser_session(
        server.universal_store.snapshot(),
        server.universal_registry.browser_session_protocol,
        browser_session_root,
    )
    assert closed_session.state_root == (
        server.universal_registry.browser_session_protocol.states['revoked']
    )
    closed_owner = read_ownership(
        server.universal_store.snapshot(),
        server.universal_registry.ownership_protocol,
        runtime_ownership_root,
    )
    assert closed_owner.state_root == (
        server.universal_registry.ownership_protocol.states['released']
    )

    restarted = ApplicationServer(
        state_path=path,
        universal_checkpoint_path=cng_checkpoint_court['checkpoint'],
        universal_checkpoint_authority_path=cng_checkpoint_court['authority'],
        universal_checkpoint_key_name=cng_checkpoint_court['key_name'],
        universal_checkpoint_provider_id=cng.SOFTWARE_PROVIDER_ID,
        allow_legacy_mutations=True,
    ).start()
    try:
        state_request = urllib.request.Request(
            restarted.url + '/api/state',
            headers={'X-ArchHub-Session': restarted.browser_session_token},
        )
        state = json.loads(urllib.request.urlopen(
            state_request, timeout=10).read())
        page = urllib.request.urlopen(urllib.request.Request(
            restarted.url + '/',
            headers={'X-ArchHub-Session': restarted.browser_session_token},
        ), timeout=10).read().decode('utf-8')
        website_response = urllib.request.urlopen(
            restarted.url + '/website', timeout=10)
        website = website_response.read().decode('utf-8')
        assert state['legacy']['focus'] == selected
        assert state['persistent'] is True
        assert state['universal_persistent'] is True
        assert state['universal_checkpoint'] == 'anchored'
        assert state['universal_checkpoint_format'] == 'v2-asymmetric'
        assert state['universal_checkpoint_descriptor'].endswith(
            ':descriptor:v2'
        )
        assert state['universal_checkpoint_binding'] == checkpoint_binding
        assert restarted.universal_checkpoint_binding_root == checkpoint_binding
        checkpoint = json.loads(
            cng_checkpoint_court['checkpoint'].read_text(encoding='ascii')
        )
        assert checkpoint['format_version'] == 2
        assert set(checkpoint) == {
            'database', 'digest', 'envelope_root', 'format',
            'format_version', 'issued_at', 'revision',
        }
        # Restart creates a signed next owner generation and, without shared
        # browser custody in this test, issues a fresh browser session.
        assert state['universal_revision'] > closed_revision
        ownerships = verify_ownership_authority(
            restarted.universal_store.snapshot(),
            restarted.universal_registry.ownership_protocol,
        )
        assert len(ownerships) == 2
        assert ownerships[-1].generation == 2
        assert ownerships[-1].state_root == (
            restarted.universal_registry.ownership_protocol.states['active']
        )
        assert restarted.universal_store.read(
            restarted.universal_registry.viewport_properties['pan_x'].value_root
        ).atom == b'73.0'
        assert restarted.universal_store.read(
            restarted.universal_registry.viewport_properties['pan_y'].value_root
        ).atom == b'-21.0'
        assert restarted.universal_store.read(
            restarted.universal_registry.viewport_properties['zoom'].value_root
        ).atom == b'1.4'
        assert state['valid'] is True
        assert state['universal_runtime_node'] == (
            restarted.universal_registry.application_root
        )
        assert state['universal_runtime_url'] == restarted.url
        health_request = urllib.request.Request(
            state['universal_runtime_url'] + '/api/universal/health',
            headers={'X-ArchHub-Session': restarted.browser_session_token},
        )
        cloud_health = json.loads(urllib.request.urlopen(
            health_request, timeout=10).read())
        assert cloud_health['ok'] is True
        assert cloud_health['runtime'] == (
            restarted.universal_registry.application_root
        )
        assert cloud_health['routes'] == len(
            restarted.universal_registry.application_http_route_roots
        )
        assert cloud_health['core_values']['root'] == 'app:core-values:v1'
        assert cloud_health['core_values']['lifecycle'] == 'WIP'
        assert set(cloud_health['core_values']['coverage'].values()) == {'partial'}
        assert cloud_health['checkpoint_binding'] == checkpoint_binding
        assert cloud_health['legacy_parallel_runtime'] is True
        assert 'class="archhub-app"' in page
        assert 'class="site-shell"' in website
        assert website_response.headers['X-ArchHub-Graph-Root'] == (
            restarted.universal_registry.website.root_id
        )

        secret_command = 'read api_key=must-never-survive-restart'
        request = urllib.request.Request(
            restarted.url + '/api/activate', method='POST',
            headers={
                'Content-Type': 'application/json',
                'X-ArchHub-Session': restarted.browser_session_token,
            },
            data=json.dumps({
                'ui_id': registry['cockpit_command_submit'],
                'input_value': secret_command,
            }).encode('utf-8'))
        response = json.loads(urllib.request.urlopen(request, timeout=10).read())
        assert response['ok'] is True
        assert restarted.store.pull(
            restarted.registry['cockpit_domain']['command']
        ) == '[REDACTED BY COCKPIT POLICY]'
        assert secret_command not in repr(restarted.store.nodes)
    finally:
        restarted.close()


def test_server_rejects_authority_binding_tamper_before_checkpoint_advance(
    tmp_path, cng_checkpoint_court
):
    path = tmp_path / 'archhub-state.json.gz'
    server = ApplicationServer(
        state_path=path,
        universal_checkpoint_path=cng_checkpoint_court['checkpoint'],
        universal_checkpoint_authority_path=cng_checkpoint_court['authority'],
        universal_checkpoint_key_name=cng_checkpoint_court['key_name'],
        universal_checkpoint_provider_id=cng.SOFTWARE_PROVIDER_ID,
    ).start()
    binding_root = server.universal_checkpoint_binding_root
    universal_path = server.universal_state_path
    server.close()
    anchored = cng_checkpoint_court['checkpoint'].read_bytes()

    tampered = UniversalCellStore(universal_path)
    purpose_root = binding_root + ':purpose'
    purpose = tampered.read(purpose_root)
    tampered.commit(
        tampered.revision,
        replace=(UniversalCell(
            purpose.id,
            purpose.link0,
            purpose.link1,
            b'other-purpose',
        ),),
    )
    tampered.close()

    with pytest.raises(UniversalInvalidCell, match='purpose'):
        ApplicationServer(
            state_path=path,
            universal_checkpoint_path=cng_checkpoint_court['checkpoint'],
            universal_checkpoint_authority_path=(
                cng_checkpoint_court['authority']
            ),
            universal_checkpoint_key_name=cng_checkpoint_court['key_name'],
            universal_checkpoint_provider_id=cng.SOFTWARE_PROVIDER_ID,
        )
    assert cng_checkpoint_court['checkpoint'].read_bytes() == anchored


def test_incompatible_snapshot_is_not_loaded(tmp_path):
    path = tmp_path / 'old-state.json.gz'
    with gzip.open(path, 'wt', encoding='utf-8') as stream:
        json.dump({'schema_version': 'old', 'nodes': {}}, stream)
    assert load_snapshot(path) is None


def test_cooperative_snapshot_is_atomic_and_revision_consistent(tmp_path):
    path = tmp_path / 'cooperative.json.gz'
    store, _registry = build_archhub_application()
    lock = threading.RLock()
    revision = {'value': 7}

    assert save_snapshot_cooperative(
        store, path, lock, 7, lambda: revision['value'], chunk_size=64) is True
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        payload = json.load(stream)
    assert len(payload['nodes']) == len(store.nodes)

    stale_path = tmp_path / 'stale.json.gz'
    revision['value'] = 8
    assert save_snapshot_cooperative(
        store, stale_path, lock, 7, lambda: revision['value'], chunk_size=64) is False
    assert not stale_path.exists()


def test_server_migrates_schema_30_state_and_keeps_a_rollback_copy(tmp_path):
    path = tmp_path / 'schema-30.json.gz'
    store, registry = build_archhub_application()
    store.edit(registry['canvas_view']['pan_x'], ['body', 'floor', 'value'], -175.0,
               actor='schema-migration', transaction='older-migration')
    store.edit(registry['mode'], ['body', 'floor', 'value'], 'home',
               actor='user', transaction='user-state')
    schema = store.nodes[registry['app']]['params']['schema_version']
    store.nodes[schema]['body']['floor']['value'] = '2026.07.13.30'
    with gzip.open(path, 'wt', encoding='utf-8') as stream:
        json.dump({'schema_version': '2026.07.13.30', 'nodes': store.dump()}, stream)

    server = ApplicationServer(
        state_path=path, allow_legacy_mutations=True
    ).start()
    try:
        assert server.migration_report['migrated'] is True
        assert server.store.pull(server.registry['mode']) == 'home'
        pan_x = next(nid for nid, node in server.store.nodes.items()
                     if node['title'] == 'canvas pan x')
        assert server.store.pull(pan_x) == -175.0
        assert server.store.pull(
            server.store.nodes[server.registry['app']]['params']['schema_version']
        ) == APPLICATION_SCHEMA_VERSION
    finally:
        server.close()

    backup = path.with_name(path.name + '.schema-2026.07.13.30.bak')
    assert backup.exists()
    with gzip.open(backup, 'rt', encoding='utf-8') as stream:
        assert json.load(stream)['schema_version'] == '2026.07.13.30'
    assert load_snapshot(path) is not None
