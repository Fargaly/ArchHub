"""Deleting an owner cannot manufacture a new unchanged-file diagnostic."""
import copy
import pytest
from tools.pipeline import strict_check

pytest_plugins = ('tests_replica.test_acompiler_gate',)


def _diagnostic(message, *, code='E0001', file='untouched.py'):
    return dict(code=code, language='python', file=file, line=1, column=1,
        message=message, help='merge the duplicate owner')


def _report(rows):
    counts = {code: {'python': sum(row['code'] == code for row in rows)} for code in strict_check.CODES}
    return dict(diagnostics=rows, counts=counts,
        files=[{'file': '01.APP/nodelang/old.py', 'language': 'python'}, {'file': 'untouched.py', 'language': 'python'}])


def _check(repository, monkeypatch, before, after):
    reports = iter((_report(before), _report(after)))
    monkeypatch.setattr(strict_check, 'scan_model', lambda *args, **kwargs: copy.deepcopy(next(reports)))
    return strict_check.check_files(repository, ['01.APP/nodelang/old.py'], {'01.APP/nodelang/old.py': "print('after')\n"},
        context={'author': 'court-human', 'intent': 'F76', 'why': 'retire duplicate runtime owner'})


def test_related_owner_location_changes_preserve_semantic_diagnostic_identity(repository, monkeypatch):
    before = [_diagnostic('multiple owners of `singleton:nodelang::http-handler` (other: retired.py:12)')]
    after = [_diagnostic('multiple owners of `singleton:nodelang::http-handler` (other: active.py:99)')]
    assert _check(repository, monkeypatch, before, after)['ok'] is True


@pytest.mark.parametrize('change', ['object', 'file', 'code', 'new_duplicate', 'changed_line'])
def test_semantic_identity_preserves_new_duplicate_and_owned_line_refusals(repository, monkeypatch, change):
    before = [_diagnostic('multiple owners of `object:first` (other: retired.py:12)')]
    after = copy.deepcopy(before)
    if change == 'object':
        after[0]['message'] = 'multiple owners of `object:second` (other: active.py:99)'
    elif change == 'file':
        after[0]['file'] = 'another.py'
    elif change == 'code':
        after[0]['code'] = 'E0022'
    elif change == 'new_duplicate':
        after.append(_diagnostic('multiple owners of `object:first` (other: active.py:99)', file='another.py'))
    else:
        before[0]['file'] = after[0]['file'] = '01.APP/nodelang/old.py'
    result = _check(repository, monkeypatch, before, after)
    assert result['ok'] is False
    if change == 'new_duplicate':
        assert result['regressions']
