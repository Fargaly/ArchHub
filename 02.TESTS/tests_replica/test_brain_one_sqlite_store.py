"""BRAINSTORE (D-BRAINSTORE): the Brain is one SQLite file -- FTS5 + sqlite-vec, beliefs with evidence and validity windows.

Every check drives the brain.* tools the app calls (pipeline_engines._brain_call) on a disposable profile.
"""
import json
import time

import pytest

from nodelang import brain_files
from nodelang.pipeline_engines import _brain_call


@pytest.fixture
def brain(tmp_path, monkeypatch):
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME', 'TEMP', 'TMP'):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(name, str(tmp_path / name))

    def call(tool, **arguments):
        return json.loads(_brain_call(tool, arguments))
    yield call
    brain_files.close()


def add(call, fid, text, **extra):
    return call('brain.write', ops=[{'op': 'add', 'fragment': dict({'id': fid, 'kind': 'fact', 'text': text}, **extra)}])


def test_a_corrected_fact_wins_over_the_old_one_with_its_evidence(brain):
    add(brain, 'ramp-1', 'Car park ramps are 12.5 percent everywhere')
    before = time.time()
    time.sleep(0.01)
    add(brain, 'ramp-2', 'Car park ramps are 1:6 with 3 m transitions at 1:12 each end',
        supersedes='ramp-1', source='founder chat', evidence='DoT AD App.A says 1:6 main with transitions')

    facts = brain('brain.context', prompt='car park ramps slope')['facts']
    assert [f['id'] for f in facts] == ['ramp-2']
    assert facts[0]['replaces'][0]['text'] == 'Car park ramps are 12.5 percent everywhere'
    assert facts[0]['evidence'][0] == {'source': 'founder chat', 'at': facts[0]['valid_from'],
                                       'quote': 'DoT AD App.A says 1:6 main with transitions'}
    # The old belief keeps its closed validity window: asked as of before the correction, it answers.
    then = brain('brain.context', prompt='car park ramps', as_of=before)['facts']
    assert [f['id'] for f in then] == ['ramp-1'] and then[0]['valid_to'] is not None
    assert brain('brain.health')['facts'] == 1


def test_an_edit_is_a_new_version_and_the_old_text_is_evidence(brain):
    add(brain, 'doors', 'Doors are 900 mm in Tower A')
    assert brain('brain.edit_fact', fragment_id='doors', text='Doors are 1000 mm in Tower A')['edited'] is True
    fact = brain('brain.context', prompt='doors tower')['facts'][0]
    assert fact['text'] == 'Doors are 1000 mm in Tower A'
    assert fact['evidence'][0]['source'] == 'corrected by the owner'
    assert fact['evidence'][0]['quote'] == 'was: Doors are 900 mm in Tower A'
    assert [v['text'] for v in brain('brain.history', fragment_id='doors')['versions']] == [
        'Doors are 900 mm in Tower A', 'Doors are 1000 mm in Tower A']


def test_recall_finds_a_word_form_the_full_text_index_alone_misses(brain):
    add(brain, 'width', 'Minimum door width is 900 mm clear')
    add(brain, 'noise', 'Lobby ceiling height is 3.2 m')
    connection = brain_files._db()
    assert connection.execute("SELECT count(*) FROM chunk_fts WHERE chunk_fts MATCH '\"doorways\"'").fetchone()[0] == 0
    facts = brain('brain.context', prompt='doorways')['facts']
    assert facts and facts[0]['id'] == 'width'   # the sqlite-vec half of the fused ranking


def test_arabic_and_long_facts_are_recalled_by_their_chunks(brain):
    add(brain, 'ar', 'المنحدرات في الجراج بميل ١:٦ مع انتقال ١:١٢')
    long_text = ' '.join('Sentence %d about general coordination notes.' % i for i in range(60)) + \
        ' The sprinkler riser sits in the north core shaft.'
    add(brain, 'long', long_text)
    assert brain_files._db().execute(
        'SELECT count(*) FROM chunks JOIN beliefs ON beliefs.id = chunks.belief WHERE fact_id = ?',
        ('long',)).fetchone()[0] > 1
    assert brain('brain.context', prompt='المنحدرات')['facts'][0]['id'] == 'ar'
    assert brain('brain.context', prompt='sprinkler riser shaft')['facts'][0]['id'] == 'long'


def test_forget_leaves_recall_but_stays_in_history(brain):
    add(brain, 'temp', 'Site office moves to gate 3')
    assert brain('brain.delete_fact', fragment_id='temp')['ok'] is True
    assert brain('brain.context', prompt='site office gate')['facts'] == []
    assert brain('brain.list_facts')['held'] == 0
    assert brain('brain.history', fragment_id='temp')['versions'][0]['forgotten'] is True
    assert brain('brain.delete_fact', fragment_id='temp') == {'ok': False, 'error': 'no such fact'}


def test_the_old_brain_json_is_imported_once_and_kept(brain, tmp_path):
    settings = tmp_path / 'LOCALAPPDATA' / 'ArchHub' / 'settings'
    settings.mkdir(parents=True)
    (settings / 'brain.json').write_text(json.dumps({'revision': 3, 'facts': [
        {'id': 'a', 'text': 'Sheets are A1 for Tower B', 'kind': 'fact', 'clock': 100.0},
        {'id': 'b', 'text': 'Old note', 'kind': 'fact', 'clock': 50.0, 'forgotten': True}]}), encoding='utf-8')
    assert brain('brain.health')['facts'] == 1
    assert not (settings / 'brain.json').exists() and (settings / 'brain.json.imported').is_file()
    fact = brain('brain.context', prompt='sheets tower')['facts'][0]
    assert fact['id'] == 'a' and fact['evidence'][0]['source'] == 'imported from brain.json'
    brain_files.close()
    assert brain('brain.health')['facts'] == 1   # reopened: nothing imported twice
    assert sorted(p.name for p in settings.iterdir() if not p.name.endswith(('-wal', '-shm'))) == [
        'brain.json.imported', 'brain.sqlite']


def test_publish_still_refuses_and_unknown_tools_are_named(brain):
    add(brain, 'client', 'P-603 uses blue tiles')
    assert 'client area' in brain('brain.publish', fragment_id='client')['error']
    with pytest.raises(Exception, match='does not provide'):
        _brain_call('brain.nothing', {})
