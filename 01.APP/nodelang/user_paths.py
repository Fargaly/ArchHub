"""Per-user application paths. Test state always wins over profile defaults."""
import os
from pathlib import Path
import time


def test_writer():
    """Test provenance only; normal application files keep their existing schemas."""
    marker = os.environ.get('ARCHHUB_TEST_RUN_ID')
    return ({'test_run_id': marker, 'writer_pid': os.getpid(),
             'writer_session': marker + ':' + str(os.getpid()), 'created_at': time.time()}
            if marker else {})


def stamp_test_write(value):
    if isinstance(value, list):
        return [stamp_test_write(row) for row in value]
    writer = test_writer()
    return {**value, '_test_writer': writer} if writer and isinstance(value, dict) else value


def strip_test_write(value):
    if isinstance(value, list):
        return [strip_test_write(row) for row in value]
    return {key: row for key, row in value.items() if key != '_test_writer'} if isinstance(value, dict) else value


def stamp_test_rows(db, table):
    """Attribute inserts without changing row identities or production table schemas."""
    import json
    writer = test_writer()
    if not writer:
        return
    if table not in ('requests', 'workshop_tasks'):
        raise ValueError('Unknown test provenance table')
    # Stamp even an empty new DB without starting a write transaction in connect().
    encoded = json.dumps(writer).replace("'", "''")
    db.execute('CREATE TABLE IF NOT EXISTS test_write_provenance '
               f"(table_name TEXT, row_id TEXT, writer TEXT DEFAULT '{encoded}')")
    db.create_function('archhub_test_writer', 0, lambda: json.dumps(test_writer()))
    db.execute(f'CREATE TEMP TRIGGER IF NOT EXISTS test_writer_{table} AFTER INSERT ON {table} '
               f"BEGIN INSERT INTO test_write_provenance VALUES ('{table}', NEW.id, archhub_test_writer()); END")


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
