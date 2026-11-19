"""R136: a wrong decision, once found and fixed, can never come back unnoticed.

Founder: "انا عاوز القرارات الغلط بنت الوسخة دي متتكررش تاني" (I want these wrong decisions never
to be repeated). Each row names the wrong decision, how it was fixed, a pattern that must not reappear
in shipped code (comments and docstrings ignored), and a live runtime check of the fixed behaviour.
A failure names the decision and the file, so it is reported, not silently reverted. Prior art: fitness
functions (Ford/Parsons, Building Evolutionary Architectures) and ArchUnit's "no class may..." rules.
"""
from __future__ import annotations

import io
import re
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / '01.APP'
sys.path.insert(0, str(APP))
SUFFIXES = {'.py', '.js', '.jsx', '.mjs', '.cjs', '.ps1', '.iss'}
SKIP = {'__pycache__', 'node_modules', '.venv', 'vendor'}


def _no_backup_location_setting():
    from nodelang.settings_owner import _APPLICATION_SETTING_SPECS
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES
    assert 'backup_location' not in _APPLICATION_SETTING_SPECS
    assert 'backup_location' not in LIBRARY_ITEM_ENGINES['tool_workshop']['params']


def _archive_stays_in_app_state():
    from app import secrets_store
    assert not hasattr(secrets_store, '_backup_location')
    assert secrets_store._local_backup_directory() == secrets_store.APP_DIR / 'backups'


WRONG_DECISIONS = [
    {'id': 'F17-backup-other-drive',
     'wrong': 'local backups followed an installer pick to other drives (40.75 GB on E:, a folder on the '
              'System Reserved D: partition)',
     'fixed': 'BACKUPSSMALL: the legacy archive stays in the app state folder',
     'pattern': r'ArchHub-backups|backup-location\.json',
     'runtime': _archive_stays_in_app_state},
    {'id': 'F17-backup-location-setting',
     'wrong': 'a backup_location setting that moved copies off the machine folder and did nothing visible',
     'fixed': 'BACKUPSSMALL: the setting is removed',
     'pattern': r'\bbackup_location\b',
     'runtime': _no_backup_location_setting},
]


def _shipped_sources():
    """Every app source file; works in a checkout and in the installed app (no .git there)."""
    return [path for path in APP.rglob('*')
            if path.suffix in SUFFIXES and path.is_file() and not SKIP.intersection(path.relative_to(APP).parts)]


def _code_lines(path):
    """(line number, text) of code only: Python comments and docstrings are dropped; other files keep every line."""
    text = path.read_text(encoding='utf-8', errors='replace')
    if path.suffix != '.py':
        return list(enumerate(text.splitlines(), 1))
    kept = {}
    previous = tokenize.NEWLINE
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            docstring = token.type == tokenize.STRING and previous in (tokenize.NEWLINE, tokenize.INDENT,
                                                                       tokenize.DEDENT, tokenize.NL)
            if token.type not in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE) and not docstring:
                for number in range(token.start[0], token.end[0] + 1):
                    kept.setdefault(number, []).append(token.string)
            if token.type not in (tokenize.COMMENT, tokenize.NL):
                previous = token.type
    except (tokenize.TokenError, SyntaxError):
        return list(enumerate(text.splitlines(), 1))
    return [(number, ' '.join(parts)) for number, parts in sorted(kept.items())]


@pytest.mark.parametrize('row', WRONG_DECISIONS, ids=[row['id'] for row in WRONG_DECISIONS])
def test_a_fixed_wrong_decision_does_not_return(row):
    pattern = re.compile(row['pattern'])
    found = ['%s:%d' % (path.relative_to(ROOT).as_posix(), number)
             for path in _shipped_sources() for number, line in _code_lines(path) if pattern.search(line)]
    assert not found, ('Wrong decision %s is back: %s. It was fixed by %s. Found at %s'
                       % (row['id'], row['wrong'], row['fixed'], ', '.join(found[:10])))
    row['runtime']()


def test_the_scanner_ignores_comments_and_docstrings_but_not_code(tmp_path):
    sample = tmp_path / 'sample.py'
    sample.write_text('"""Mentions backup_location in a docstring."""\n'
                      '# backup_location in a comment\n'
                      'def f():\n    """backup_location again."""\n    return "x"\n'
                      'value = {"backup_location": 1}\n', encoding='utf-8')
    hits = [number for number, line in _code_lines(sample) if re.search(r'\bbackup_location\b', line)]
    assert hits == [6]


def test_every_row_says_what_was_wrong_and_what_fixed_it():
    assert _shipped_sources(), 'the app sources are found without git'
    for row in WRONG_DECISIONS:
        assert row['wrong'].strip() and row['fixed'].strip() and callable(row['runtime'])
        re.compile(row['pattern'])
