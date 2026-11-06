"""Collection and every fixture use disposable application state."""
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

# Set before collection; Python and non-Python children inherit this run identity.
os.environ.setdefault('ARCHHUB_TEST_RUN_ID', str(uuid4()))


# Use the existing child wrapper so grandchildren keep the same provenance.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '03.TOOLS'))
from tools.real_app_check.profile_guard import mark_test_processes
mark_test_processes()


@pytest.fixture(autouse=True)
def test_state_directory(tmp_path, monkeypatch):
    state = tmp_path / 'state'
    state.mkdir()
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(state))
    # Exercise the normal default, without changing a user's saved settings.
    (state / 'settings').mkdir()
    (state / 'settings' / 'settings.json').write_text(
        json.dumps({'sessionsFolder': str(state / 'Sessions')}), encoding='utf-8')
