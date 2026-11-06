"""Collection and every fixture use disposable application state."""
import json

import pytest


@pytest.fixture(autouse=True)
def test_state_directory(tmp_path, monkeypatch):
    state = tmp_path / 'state'
    state.mkdir()
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(state))
    # Exercise the normal default, without changing a user's saved settings.
    (state / 'settings').mkdir()
    (state / 'settings' / 'settings.json').write_text(
        json.dumps({'sessionsFolder': str(state / 'Sessions')}), encoding='utf-8')
