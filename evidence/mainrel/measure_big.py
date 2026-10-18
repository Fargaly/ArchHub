"""Byte-scale installer/boot measurement in a disposable, explicit lane profile.

The large file uses SQLite padding, not six million live graph Cells. The report
names this limitation; it must never be represented as a full founder-size graph.
"""
from pathlib import Path
from contextlib import closing
import json
import os
import shutil
import sqlite3
import sys
import time

# PREMORTEM-A B.5#2 acceptance contract, not a mutable runtime preference.
MIGRATION_DEADLINE: float = 30.0
STARTUP_UNMEASURED: bool = False


def typed_measurements(report):
    """Keep observed values as typed immutable evidence, separate from policy."""
    for name, value_type, unit in (
        ('backup_seconds', 'number', 's'),
        ('migration_seconds', 'number', 's'),
        ('startup_within_30_seconds', 'boolean', 'predicate'),
    ):
        report[name] = {'type': value_type, 'value': report[name], 'unit': unit,
                        'mutability': 'measured', 'source': 'measure_big.py'}
    return report

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PROFILE = Path(__file__).resolve().parent / 'court-state' / ('round3-big-profile' if '--round3' in sys.argv else 'big-profile')
REPORT_NAME = 'round3-big-measurement.json' if '--round3' in sys.argv else 'big-measurement.json'
PROFILE.mkdir(parents=True, exist_ok=True)
for key in ('LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP', 'USERPROFILE'):
    directory = PROFILE / key
    directory.mkdir(exist_ok=True)
    os.environ[key] = str(directory)
os.environ['ARCHHUB_TEST_STATE_DIR'] = str(PROFILE / 'ArchHub')
os.environ['LOCALAPPDATA'] = str(PROFILE)
os.environ.pop('ARCHHUB_LEGACY_STATE_DIR', None)

from nodelang import persistence
from nodelang.application_recovery_files import preserve_closed_application_journals
from tests_replica.test_ogboot_upgrade_selection import _journal, _selected

if '--round3' in sys.argv:
    (PROFILE / 'mainrel-fixture.json').write_text(json.dumps({'owner':'MAINREL','kind':'sqlite-padding-fixture'}))

state = PROFILE / 'ArchHub'
state.mkdir(exist_ok=True)
source = PROFILE / 'ArchHub-Test' / 'archhub-test.universal.sqlite3'
if not source.exists():
    _selected(state)
    _journal(source, 'chosen', 500, commits=4)
    for name in ('authority.sqlite3', 'archhub-test.universal.sqlite3', 'node-native-wip.json.gz.universal.sqlite3'):
        _journal(state / name, 'older-' + name, 100)
target_bytes = int(8.3 * 1024**3)
remaining = max(0, target_bytes - source.stat().st_size)
if shutil.disk_usage(PROFILE).free < remaining + target_bytes + 25 * 1024**3:
    raise OSError('OGF fixture plus backup must leave 25 GiB; no large allocation started')
with closing(sqlite3.connect(source)) as db:
    db.execute('CREATE TABLE IF NOT EXISTS mainrel_fixture_padding (id INTEGER PRIMARY KEY, payload BLOB)')
    size = 0
    while source.stat().st_size < target_bytes:
        db.executemany('INSERT INTO mainrel_fixture_padding(payload) VALUES (zeroblob(1048576))', [()] * 64)
        db.commit()
        size += 64
        if size % 1024 == 0:
            print('FIXTURE_BYTES', source.stat().st_size, flush=True)
source_bytes = source.stat().st_size
free_before = shutil.disk_usage(PROFILE).free
if '--boot-only' in sys.argv:
    previous = json.loads((Path(__file__).parent / 'big-backup-only.json').read_text(encoding='utf-8'))
    backup_seconds = previous['backup_seconds']['value']
    backups = list(PROFILE.rglob('*-closed'))
else:
    started = time.perf_counter()
    backups = preserve_closed_application_journals(PROFILE, 'mainrel-big', progress=lambda line: print(line, flush=True))
    backup_seconds = time.perf_counter() - started
started = time.perf_counter()
candidate_count = len(persistence._application_journal_candidates(state))
try:
    result = persistence.prepare_application_database(state, persistence.application_database_path(state), timeout_seconds=MIGRATION_DEADLINE)
except Exception as exc:
    report = dict(fixture_bytes=source_bytes, fixture_GiB=source_bytes / 1024**3,
        semantic_fixture='small valid graph plus SQLite padding; not a six-million-Cell court',
        candidates=candidate_count, backup_seconds=backup_seconds,
        migration_seconds=time.perf_counter() - started,
        migration_error=f'{type(exc).__name__}: {exc}',
        backup_directories=len(backups), free_before_bytes=free_before,
        free_after_bytes=shutil.disk_usage(PROFILE).free,
        startup_within_30_seconds=STARTUP_UNMEASURED)
    report = typed_measurements(report)
    (Path(__file__).parent / REPORT_NAME).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)
    raise
migration_seconds = time.perf_counter() - started
if Path(result['database_path']) != source:
    raise AssertionError('OGF measured the wrong candidate; no startup pass may be recorded')
report = dict(fixture_bytes=source_bytes, fixture_GiB=source_bytes / 1024**3,
    semantic_fixture='small valid graph plus SQLite padding; not a six-million-Cell court',
    candidates=candidate_count, backup_seconds=backup_seconds, migration_seconds=migration_seconds,
    migration=result, backup_directories=len(backups), free_before_bytes=free_before,
    free_after_bytes=shutil.disk_usage(PROFILE).free,
    startup_within_30_seconds=migration_seconds <= MIGRATION_DEADLINE)
report = typed_measurements(report)
(Path(__file__).parent / REPORT_NAME).write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2), flush=True)
if migration_seconds > MIGRATION_DEADLINE:
    raise SystemExit(1)
