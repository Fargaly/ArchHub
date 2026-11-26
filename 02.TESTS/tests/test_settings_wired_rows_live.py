"""Settings rows change what the app does: real clicks in the compiled Studio on an isolated real server, then the
consumers (schedules, DWG/PDF export, sheet layout, Session node, New project) read the values those clicks saved."""
import datetime
import json
import os
from pathlib import Path
import subprocess

from test_task_session_roundtrip import _isolate


def test_settings_rows_reach_their_consumers(tmp_path, monkeypatch):
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')
    if not browser_cache:
        browser_cache = subprocess.check_output(['node', '-p', "require('node:path').join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright')"], text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang.nograph_server import NoGraphServer
    monkeypatch.setattr(NoGraphServer, '_probe_hosts', staticmethod(lambda: []))
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    state.mkdir()
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(state))
    parent = tmp_path / 'Projects'
    parent.mkdir()
    server = NoGraphServer(state).start()
    try:
        result = subprocess.run(
            ['node', '02.TESTS/tests_js/settings_wired_rows_live.cjs'],
            input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token, 'browserCache': browser_cache,
                              'parent': str(parent), 'shots': os.environ.get('ARCHHUB_SETTINGS_SHOTS', '')}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=1200,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout, result.stderr[-3000:])
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout[result.stdout.index('{'):])
        for width in (944, 1920):
            at = '@%d' % width
            rapid = report['rapid' + at]
            # Five quick clicks: five writes, each the opposite of the one before, and the switch ends opposite to its start.
            assert len(rapid['writes']) == 5, rapid
            assert rapid['writes'] == [not rapid['before'] if i % 2 == 0 else rapid['before'] for i in range(5)], rapid
            assert rapid['held'] is (not rapid['before']) and rapid['shown'] == str(not rapid['before']).lower(), rapid
            assert report['created' + at] is True, report
            assert report['parent' + at] == 'Projects', report
            assert report['status' + at] == 'Off: needs the ArchHub cloud service, which does not offer this', report
            assert report['zone' + at] == {'utc': '12:00', 'dubai': '16:00'}, report
            assert report['numbers' + at]['arabic'] > 0 and report['numbers' + at]['latinInTabs'] == 0, report
            assert report['errors' + at] == [], report
        tree = sorted(p.relative_to(parent / 'CDE-1920').as_posix() for p in (parent / 'CDE-1920').rglob('*'))
        assert 'WIP/Models/A' in tree and 'Archive/Documents/M' in tree and len(tree) == 4 * (1 + 3 * 4), tree

        # The consumers read what the clicks saved.
        from nodelang import library_engines, nodeslib_v2_engines, canvas_triggers
        from nodelang.canvas_documents import _run_session
        from nodelang.session_files import new_document
        saved = json.loads((state / 'settings' / 'settings.json').read_text(encoding='utf-8'))
        assert saved['timezone'] == 'Asia/Dubai (GMT+4)' and saved['numerals'] == '123'
        assert library_engines.pdf_color_depth() == 'BlackLine'
        assert library_engines.place_views_on_sheets_engine({'scale': 'From Projects', 'sheet_size': 'A1'}, {'views': []})[1].endswith('(A1, 1:200)')

        class Reviewed(Exception):
            pass

        def stop(request):
            raise Reviewed(request)
        monkeypatch.setattr(nodeslib_v2_engines, 'validate_dwg_options', stop)
        try:
            nodeslib_v2_engines.dwg_export_request({'version': '2018', 'setup_source': 'Revit default', 'session': '48884', 'views': [5]}, {}, {})
        except Reviewed as reviewed:
            request = reviewed.args[0]
        assert request['layers'] == 'ISO13567' and request['shared_coords'] is True
        project = _run_session({}, {}, new_document('New session'))[0]['project']
        assert project['Revit template'] == 'C:\\Templates\\Office 1920.rte' and project['Layer standard'] == 'ISO 13567'
        # A daily schedule fires at its time in Settings › Account › Time zone (Dubai), not the PC's zone.
        zone = datetime.timezone(datetime.timedelta(hours=4))
        now = datetime.datetime(2026, 1, 1, 7, 0, tzinfo=zone)
        assert canvas_triggers.next_delay({'daily_at': '08:00'}, now) == 3600
        delay = canvas_triggers.next_delay({'daily_at': '08:00'})
        fires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=delay)
        assert fires.astimezone(zone).strftime('%H:%M') == '08:00'
    finally:
        server.close()
