"""ArchHub menu > App health > Activity reads the run receipts every canvas run writes beside its session file."""
from test_task_session_roundtrip import _isolate


def test_a_canvas_run_shows_in_app_health_activity_with_its_session_title(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang import session_files as files
    folder = files.sessions_directory()
    first, second = folder / 'one.archhub', folder / 'two.archhub'
    for path, title in ((first, 'Sheet set review'), (second, 'Door schedule')):
        files.write_document(path, files.new_document(title))
    assert files.recent_runs() == []
    files.record_run(str(first), 'manual', lambda: {'succeeded': True})
    files.record_run(str(second), 'manual', lambda: {'succeeded': True})
    rows = files.recent_runs()
    assert [row['title'] for row in rows] == ['Door schedule', 'Sheet set review']
    assert {row['state'] for row in rows} == {'succeeded'} and all(row['path'] for row in rows)
    assert len(files.recent_runs(1)) == 1


def test_a_run_of_a_file_saved_outside_the_sessions_folder_shows_in_activity(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang import session_files as files
    project = tmp_path / 'project'
    project.mkdir()
    saved = project / 'Receipt check.archhub'
    files.write_document(saved, files.new_document('Receipt check'))
    files.record_run(str(saved), 'manual', lambda: {'succeeded': True})
    assert files.recent_runs() == []
    rows = files.recent_runs(known_paths=[str(saved), str(tmp_path / 'gone' / 'x.archhub')])
    assert [(row['title'], row['path'], row['state']) for row in rows] == [('Receipt check', str(saved), 'succeeded')]
