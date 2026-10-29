"""CLOUD404: real Settings owner over loopback HTTP, never the live account."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from nodelang import cloud_session, cloud_signin, settings_owner
from nodelang.universal_cell import CellStore, InvalidCell


@pytest.fixture
def account_cloud(tmp_path, monkeypatch):
    replies = {
        '/v1/me': (200, {'user_id': 'court-user', 'email': 'court-user@example.test',
                         'full_name': 'Verified user', 'plan': 'solo', 'remaining_messages': 17}),
        '/v1/companies/mine': (200, {'companies': []}),
        '/v1/billing/plans': (200, {'tiers': ['solo'], 'pricing_visible': True}),
        '/v1/companies/invites/mine': (404, {'detail': 'Not Found'}),
    }
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.headers['Authorization'] == 'Bearer court-session'
            calls.append(self.path)
            code, payload = replies[self.path]
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = 'http://127.0.0.1:%d' % server.server_port
    monkeypatch.setattr(cloud_session, 'FOUNDER_CHECK_BASES', (base,))
    monkeypatch.setattr(cloud_signin, 'read_cloud_session', lambda _path: {'token': 'court-session'})
    store = CellStore(tmp_path / 'GRAPH.sqlite3')
    try:
        yield settings_owner.SettingsOwner(store, dependencies=object()), replies, calls
    finally:
        store.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_missing_invitations_keeps_verified_account_and_billing(account_cloud):
    owner, _replies, calls = account_cloud
    result = owner.dispatch('read', [])
    assert result['profile']['name'] == 'Verified user'
    assert result['profile']['plan'] == 'Personal'
    assert result['billing']['remainingMessages'] == 17
    assert result['officeInvitations'] == []
    assert 'officeInvitations' not in result['controlErrors']  # internal deploy lag: logged, never a toast
    assert '404' not in json.dumps(result)
    assert calls == ['/v1/me', '/v1/companies/mine', '/v1/billing/plans', '/v1/companies/invites/mine']


def test_invitation_recovery_returns_actual_rows_and_clears_notice(account_cloud):
    owner, replies, _calls = account_cloud
    first = owner.read()
    assert first['officeInvitations'] == [] and 'officeInvitations' not in first['controlErrors']
    invitation = {'id': 'existing-invite', 'office': 'Actual office', 'status': 'Pending'}
    replies['/v1/companies/invites/mine'] = (200, {'invitations': [invitation]})
    result = owner.read()
    assert result['officeInvitations'] == [invitation]
    assert result['controlErrors'] == {}


@pytest.mark.parametrize(('path', 'status'), [
    ('/v1/companies/invites/mine', 401), ('/v1/companies/invites/mine', 403),
    ('/v1/companies/invites/mine', 500), ('/v1/me', 404),
    ('/v1/companies/mine', 404), ('/v1/billing/plans', 404),
])
def test_other_failures_are_not_reported_as_success(account_cloud, path, status):
    owner, replies, _calls = account_cloud
    replies[path] = (status, {'detail': 'private service detail'})
    with pytest.raises(InvalidCell) as error:
        owner.read()
    assert 'private' not in str(error.value)


def test_served_invitations_and_profile_still_work(account_cloud):
    owner, replies, _calls = account_cloud
    replies['/v1/companies/invites/mine'] = (200, {'invitations': []})
    assert owner.read()['billing']['status'] == 'solo'
    assert owner.updateProfile({'name': 'Saved name'})['message'] == 'Profile saved'
    assert owner.read()['profile']['name'] == 'Saved name'
