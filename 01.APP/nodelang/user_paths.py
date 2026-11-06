"""Per-user application paths. Test state always wins over profile defaults."""
import os
from pathlib import Path


def state_directory(environment=None):
    env = os.environ if environment is None else environment
    if 'ARCHHUB_TEST_STATE_DIR' in env:
        root = Path(env['ARCHHUB_TEST_STATE_DIR'])
    elif selected := env.get('ARCHHUB_STATE_DIR'):
        root = Path(selected).expanduser()
    else:
        root = Path(env.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'ArchHub'
    if not root.is_absolute():
        raise ValueError('Application state directory must be absolute')
    return root


def sessions_directory(environment=None):
    env = os.environ if environment is None else environment
    if 'ARCHHUB_TEST_STATE_DIR' in env:
        return state_directory(env) / 'Sessions'
    return Path(env.get('USERPROFILE') or Path.home()) / 'ArchHub' / 'Sessions'
