"""Settings › Account, Connections and Projects rows: one owner file, checked values, real consumers."""
import json
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from test_task_session_roundtrip import _isolate


def _owner():
    from nodelang import session_files as files
    from nodelang.nograph_server import JsonFile
    return JsonFile(files.profile_directory() / 'settings/settings.json', {})


def test_every_declared_row_is_one_owned_checked_preference(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang.settings_owner import DECLARED_ROWS, declared_settings, preference_settings
    settings = _owner()
    shown = {row['id']: row for row in preference_settings(settings=settings)['appearanceSettings']}
    assert len({row['id'] for row in DECLARED_ROWS}) == len(DECLARED_ROWS) == 53
    for spec in DECLARED_ROWS:
        assert shown[spec['id']]['value'] == spec['default'], spec['id']
    preference_settings('setAppearance', ['Projects.Survey point east', '1250.5'], settings)
    preference_settings('setAppearance', ['Connections.Quiet hours from', '22:00'], settings)
    preference_settings('setAppearance', ['Account.Memories in each request', 12], settings)
    held = json.loads(settings.path.read_text(encoding='utf-8'))
    assert held['surveyE'] == '1250.5' and held['quietFrom'] == '22:00' and held['brainContext'] == 12
    for identity, bad in (('Projects.Survey point east', 'east'), ('Connections.Quiet hours from', '25:00'),
                          ('Account.Memories in each request', 500), ('Connections.Proxy', 'http://a b'), ('Connections.Proxy', 'http://someone@proxy.example'),
                          ('Projects.Discipline codes', 'a; b'), ('Account.Public profile', 'yes')):
        with pytest.raises(ValueError):
            preference_settings('setAppearance', [identity, bad], settings)
    assert declared_settings()['Projects']['Survey point east'] == '1250.5'
    preference_settings('resetAppearance', ['Projects.Survey point east'], settings)
    assert 'surveyE' not in settings.read()


def test_quiet_hours_cross_midnight():
    from nodelang.settings_owner import quiet_hours
    assert quiet_hours('22:00', '07:00', '23:30') and quiet_hours('22:00', '07:00', '06:59')
    assert not quiet_hours('22:00', '07:00', '07:00') and not quiet_hours('22:00', '07:00', '12:00')
    assert not quiet_hours('Off', '07:00', '03:00')


def test_work_offline_refuses_every_outside_request_and_brain_reads_the_memory_count(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang.settings_owner import apply_network_settings, preference_settings
    settings = _owner()
    preference_settings('setAppearance', ['Connections.Work offline', True], settings)
    try:
        assert apply_network_settings()['offline'] is True
        with pytest.raises(URLError, match='Work offline'):
            urlopen('http://archhub.invalid/', timeout=2)
    finally:
        preference_settings('resetAppearance', ['Connections.Work offline'], settings)
        assert apply_network_settings() == {'offline': False, 'proxy': ''}
    preference_settings('setAppearance', ['Connections.Proxy', 'http://prox'], settings)
    assert apply_network_settings()['proxy'] == 'http://prox'
    preference_settings('setAppearance', ['Connections.Proxy', 'http:/'], settings)
    assert apply_network_settings()['proxy'] == '', 'a half-typed address keeps direct connections'
    from nodelang import brain_files
    asked = []
    monkeypatch.setattr(brain_files, 'context', lambda prompt, limit, as_of=None: asked.append(limit) or {'facts': []})
    preference_settings('setAppearance', ['Account.Memories in each request', 3], settings)
    brain_files.call('brain.context', {'prompt': 'walls'})
    assert asked == [3]


def test_settings_follow_the_account_without_this_pcs_network(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang import settings_owner
    settings = _owner()
    settings_owner.preference_settings('setAppearance', ['Connections.Sound', True], settings)
    settings_owner.preference_settings('setAppearance', ['Connections.Proxy', 'http://proxy.example:8080'], settings)
    settings_owner.preference_settings('setAppearance', ['Projects.Stage', 'Tender'], settings)
    items = settings_owner._sync_items()
    sent = json.loads(items['settings/preferences.json'][1])
    assert sent.get('sound') is True and 'proxy' not in sent and 'projStage' not in sent
    settings_owner._sync_cache('settings/preferences.json', json.dumps({'sound': False, 'proxy': 'http://evil', 'quietTo': 'never'}).encode())
    held = settings.read()
    assert held['sound'] is False and held['proxy'] == 'http://proxy.example:8080' and 'quietTo' not in held
    settings_owner.preference_settings('setAppearance', ['Account.Settings follow your account', False], settings)
    assert settings_owner._sync_items() == {}
