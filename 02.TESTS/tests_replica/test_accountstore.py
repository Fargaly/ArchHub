"""ACCOUNTSTORE: real readers and Settings translation, fake OS custody only."""
import hashlib
import json
import secrets
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from app import secrets_store as store
from nodelang import model_router as router, settings_owner as settings, cloud_signin
from nodelang.universal_cell import InvalidCell


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / 'ArchHub'
    root.mkdir()
    monkeypatch.setattr(store, 'APP_DIR', root)
    monkeypatch.setattr(store, 'SECRETS_FILE', root / 'secrets.dat')
    monkeypatch.setattr(store, 'SETTINGS_FILE', root / 'settings.json')
    monkeypatch.setattr(store, 'os_store_refused', lambda: False)
    values = {}
    failures = set()
    names = []
    settings_values = {'known_providers': names}
    monkeypatch.setattr(store, '_read_settings', lambda: settings_values)
    monkeypatch.setattr(store, 'save_setting', lambda k, v: settings_values.update({k: v}))
    def read(service, name):
        assert service == store.SERVICE
        if name in failures:
            raise OSError('backend exception body must stay private')
        return values.get(name)
    from keyring.backends.Windows import WinVaultKeyring
    backend = SimpleNamespace(get_password=read, get_keyring=lambda: WinVaultKeyring(),
        set_password=lambda service, name, value: values.update({name: value}),
        delete_password=lambda service, name: values.pop(name, None))
    monkeypatch.setattr(store, '_try_keyring', lambda: backend)
    monkeypatch.setattr(router, '_application_secrets_store', lambda: store)
    def no_decode(*args, **kwargs):
        pytest.fail('Non-DPAPI legacy bytes were decoded')
    monkeypatch.setattr(store, '_dpapi', no_decode)
    return SimpleNamespace(root=root, values=values, failures=failures, names=names,
                           settings=settings_values, backend=backend)


def controls(monkeypatch):
    owner = settings.SettingsOwner(None, dependencies=object())
    monkeypatch.setattr(owner, '_control_preferences', lambda: {})
    monkeypatch.setattr(owner, '_provider_models', lambda: {})
    return owner


def test_stub_archived_once_with_hash_and_os_accounts_listed(vault, monkeypatch):
    raw = b'Og8='
    store.SECRETS_FILE.write_bytes(raw)
    for name in ('openai', 'openrouter', 'anthropic', 'google', 'nvidia', 'notion-mcp'):
        vault.names.append(name)
        vault.values[name] = secrets.token_hex(24)
    name = 'social-linkedin-fixture'
    vault.names.append(name)
    vault.values[name] = json.dumps({'format': router._SOCIAL_VERIFIED_FORMAT,
        'provider': 'linkedin', 'account_id': 'urn:li:person:fixture',
        'token': secrets.token_hex(24), 'account_binding': 'provider-verified',
        'display_name': 'Fixture account'})
    owner = controls(monkeypatch)
    result = owner.readControls()
    rows = result['secrets']
    assert len(rows) == 7
    assert {row['id'] for row in rows} == set(vault.names)
    assert all(row['status'] == 'Connected' for row in rows)
    assert not result['controlErrors']
    digest = hashlib.sha256(raw).hexdigest()
    archived = vault.root / 'backups' / ('secrets-legacy-' + digest + '.dat')
    assert archived.read_bytes() == raw
    assert archived.with_suffix('.sha256').read_text().strip() == digest
    assert not store.SECRETS_FILE.exists()
    first = {p.name: p.stat().st_mtime_ns for p in archived.parent.iterdir()}
    assert owner.readControls() == result
    assert {p.name: p.stat().st_mtime_ns for p in archived.parent.iterdir()} == first
    public = json.dumps(result)
    assert all(value not in public for value in vault.values.values())


def test_one_failed_item_names_it_and_keeps_other_accounts(vault, monkeypatch):
    vault.names.extend(['notion-mcp', 'openai'])
    vault.values.update({name: secrets.token_hex(24) for name in vault.names})
    vault.failures.add('notion-mcp')
    result = controls(monkeypatch).readControls()
    assert any(row['id'] == 'openai' and row['status'] == 'Connected' for row in result['secrets'])
    message = result['controlErrors']['secrets']
    assert 'notion-mcp' in message
    assert 'custody is unavailable' not in message
    assert 'backend exception body' not in json.dumps(result)


def test_missing_indexed_item_is_not_connected(vault, monkeypatch):
    vault.names.append('notion-mcp')
    result = controls(monkeypatch).readControls()
    assert not any(row['status'] == 'Connected' for row in result['secrets'])
    assert 'notion-mcp' in result['controlErrors']['secrets']


def test_bad_social_record_names_item_and_preserves_good(vault, monkeypatch):
    vault.names.extend(['social-broken', 'notion-mcp'])
    vault.values.update({'social-broken': secrets.token_hex(24), 'notion-mcp': secrets.token_hex(24)})
    result = controls(monkeypatch).readControls()
    assert 'social-broken' in result['controlErrors']['secrets']
    assert any(row['id'] == 'notion-mcp' for row in result['secrets'])
    assert all(value not in json.dumps(result) for value in vault.values.values())


def test_social_resolver_reads_same_os_item_without_legacy_file(vault):
    vault.values['social-linkedin-fixture'] = secrets.token_hex(24)
    assert isinstance(router.protected_credential_entry('social-linkedin-fixture'), str)
    assert not store.SECRETS_FILE.exists()


def test_protected_corruption_is_preserved_and_named(vault, monkeypatch):
    raw = store._DPAPI_MARK + b'invalid!'
    store.SECRETS_FILE.write_bytes(raw)
    vault.names.append('notion-mcp')
    vault.values['notion-mcp'] = secrets.token_hex(24)
    result = controls(monkeypatch).readControls()
    assert store.SECRETS_FILE.read_bytes() == raw
    assert not (vault.root / 'backups').exists()
    assert 'secrets.dat' in result['controlErrors']['secrets']
    assert any(row['id'] == 'notion-mcp' for row in result['secrets'])


def test_archive_failure_keeps_legacy_bytes_and_os_items(vault, monkeypatch):
    store.SECRETS_FILE.write_bytes(b'Og8=')
    (vault.root / 'backups').write_bytes(b'fixture obstruction')
    vault.names.append('notion-mcp')
    vault.values['notion-mcp'] = secrets.token_hex(24)
    result = controls(monkeypatch).readControls()
    assert store.SECRETS_FILE.read_bytes() == b'Og8='
    assert 'secrets.dat' in result['controlErrors']['secrets']
    assert any(row['id'] == 'notion-mcp' for row in result['secrets'])


def test_internal_session_and_signing_entries_are_not_accounts(vault, monkeypatch):
    vault.names.extend(['archhub-account-session:v1:' + '0' * 64, 'archhub-host-bridge', 'notion-mcp'])
    vault.values.update({name: secrets.token_hex(24) for name in vault.names})
    result = controls(monkeypatch).readControls()
    assert [row['id'] for row in result['secrets']] == ['notion-mcp']


@pytest.mark.parametrize(('state', 'expected'), [
    ('signed_out', 'Not signed in'), ('unreachable', 'Cloud backend unreachable'),
    ('refused', 'Cloud backend refused (HTTP 403)'),
])
def test_cloud_states_are_distinct_without_private_details(monkeypatch, state, expected):
    held = {} if state == 'signed_out' else {'token': secrets.token_hex(24)}
    monkeypatch.setattr(cloud_signin, 'read_cloud_session', lambda path: held)
    called = []
    def request(*args, **kwargs):
        called.append(True)
        if state == 'unreachable':
            raise URLError('private transport body')
        raise HTTPError('https://fixture.invalid', 403, 'private refusal', {},
                        BytesIO(b'{"detail":"private backend body"}'))
    monkeypatch.setattr(settings, 'urlopen', request)
    with pytest.raises(InvalidCell) as failed:
        settings.cloud_call('GET', '/v1/me')
    assert expected in str(failed.value)
    assert 'private' not in str(failed.value)
    assert bool(called) == (state != 'signed_out')


def test_cloud_success_stays_success(monkeypatch):
    monkeypatch.setattr(cloud_signin, 'read_cloud_session', lambda path: {'token': secrets.token_hex(24)})
    class Answer(BytesIO):
        status = 200
    monkeypatch.setattr(settings, 'urlopen', lambda *a, **k: Answer(b'{"ok":true,"user_id":"fixture"}'))
    assert settings.cloud_call('GET', '/v1/me')['user_id'] == 'fixture'


def test_social_save_rotate_and_revoke_use_same_os_item(vault):
    name = 'social-linkedin-fixture'
    body = {'vault_entry': name, 'provider': 'linkedin', 'account_id': 'urn:li:person:fixture',
            'token': secrets.token_hex(24)}
    called = []
    router.save_social_credential(body, before_replace=lambda: called.append(True), verified=True)
    assert called and name in vault.settings['known_providers']
    assert isinstance(router.protected_credential_entry(name), str)
    assert not store.SECRETS_FILE.exists()
    previous = vault.values[name]
    body['token'] = secrets.token_hex(24)
    router.save_social_credential(body, verified=True)
    assert vault.values[name] != previous
    assert router.list_social_credentials()['items'][0]['vault_entry'] == name
    result = router.revoke_social_credential({key: body[key] for key in ('vault_entry', 'provider', 'account_id')})
    assert result['state'] == 'removed'
    assert name not in vault.values and name not in vault.settings['known_providers']
    assert not store.SECRETS_FILE.exists()


def test_os_writer_retains_binding_guard_and_other_items(vault):
    name = 'social-linkedin-fixture'
    body = {'vault_entry': name, 'provider': 'linkedin', 'account_id': 'urn:li:person:fixture',
            'token': secrets.token_hex(24)}
    vault.values['notion-mcp'] = secrets.token_hex(24)
    router.save_social_credential(body, verified=True)
    before = dict(vault.values)
    body['account_id'] = 'urn:li:person:other'
    with pytest.raises(router.ProviderCredentialError, match='another provider account'):
        router.save_social_credential(body, verified=True)
    assert vault.values == before
    def deny():
        raise InvalidCell('fixture admission revoked')
    body['account_id'] = 'urn:li:person:fixture'
    with pytest.raises(router.ProviderCredentialError, match='no longer authorized'):
        router.save_social_credential(body, before_replace=deny, verified=True)
    assert vault.values == before


def test_plaintext_keyring_is_refused(vault, monkeypatch):
    monkeypatch.setattr(vault.backend, 'get_keyring', lambda: object())
    vault.names.append('notion-mcp')
    vault.values['notion-mcp'] = secrets.token_hex(24)
    result = router.list_social_credentials()
    assert not result['stored_items']
    assert result['issues'][0]['item'] == 'notion-mcp'


def test_os_session_read_does_not_touch_legacy_stub(vault):
    reference = 'archhub-account-session:v1:' + '0' * 64
    store.SECRETS_FILE.write_bytes(b'Og8=')
    vault.values[reference] = secrets.token_hex(24)
    backend = vault.backend.get_keyring()
    backend.get_password = vault.backend.get_password
    vault.backend.get_keyring = lambda: backend
    assert isinstance(store.load_session_secret(reference), str)
    assert store.SECRETS_FILE.read_bytes() == b'Og8='


def test_archive_collision_never_overwrites_existing_bytes(vault, monkeypatch):
    raw = b'Og8='
    store.SECRETS_FILE.write_bytes(raw)
    directory = vault.root / 'backups'
    directory.mkdir()
    archive = directory / ('secrets-legacy-' + hashlib.sha256(raw).hexdigest() + '.dat')
    archive.write_bytes(b'other preserved evidence')
    result = controls(monkeypatch).readControls()
    assert store.SECRETS_FILE.read_bytes() == raw
    assert archive.read_bytes() == b'other preserved evidence'
    assert 'secrets.dat' in result['controlErrors']['secrets']


def test_unconfirmed_os_write_does_not_report_saved(vault, monkeypatch):
    monkeypatch.setattr(vault.backend, 'set_password', lambda *args: None)
    with pytest.raises(router.ProviderCredentialError, match='could not be confirmed'):
        router.save_provider_key({'provider': 'openai', 'key': secrets.token_hex(24)})
    assert 'openai' not in vault.values
