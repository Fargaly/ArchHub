"""Measure the real 1030 8-GB fixture on a lane-only copy, never the source."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import threading
import time
import faulthandler

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider
from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID
from tests_replica.test_ogboot_upgrade_selection import _selected

if '--baseline' in sys.argv:
    import importlib.util
    import subprocess
    import nodelang
    directory = ROOT / 'tmp-base'
    directory.mkdir(exist_ok=True)
    path = directory / 'persistence.py'
    path.write_bytes(subprocess.check_output(['git', 'show', 'ce671c2e:nodelang/persistence.py'], cwd=ROOT))
    spec = importlib.util.spec_from_file_location('nodelang.persistence', path)
    baseline = importlib.util.module_from_spec(spec)
    sys.modules['nodelang.persistence'] = baseline
    nodelang.persistence = baseline
    try:
        spec.loader.exec_module(baseline)
    finally:
        path.unlink()
        directory.rmdir()

from nodelang import persistence

fixture = Path('E:/ARCHHUB-RIG-FIXTURES/ogfbig-20261018-1030-4535ff5-8')
work = ROOT / "05.EVIDENCE/large-boot/court-state/big"
local = work / 'LOCALAPPDATA'
root = work / 'state'
source = local / 'ArchHub-Test/archhub-test.universal.sqlite3'
source.parent.mkdir(parents=True, exist_ok=True)
fresh_copy = not source.is_file()
if '--boot-only' in sys.argv:
    assert fresh_copy, 'fresh startup court requires a new source copy'
if fresh_copy:
    if shutil.disk_usage(work).free < 25 * 1024**3 + (fixture / source.name).stat().st_size:
        raise RuntimeError('lane fixture would breach the 25 GB disk reserve')
    for item in fixture.iterdir():
        if item.is_file() and item.name.startswith(source.name) and not item.name.endswith(('-shm', '.owner.lock')):
            shutil.copyfile(item, source.parent / item.name)
    shutil.copytree(fixture / 'keys', local / 'ArchHub/keys', dirs_exist_ok=True)
os.environ['LOCALAPPDATA'] = str(local)
os.environ['APPDATA'] = str(work / 'APPDATA')
os.environ['ARCHHUB_TEST_STATE_DIR'] = str(root)
os.environ['ARCHHUB_GRAND_MAP_PATH'] = str(ROOT / "01.APP/nodelang/data/public_runtime_map.json")
keys = WindowsDpapiSigningKeyProvider(WindowsDpapiSigningKeyProvider.default_path())
stale = _selected(root)
started = time.monotonic()
marker = 'mainfix:saved-edit'
conversation_court = '--conversation' in sys.argv
if not conversation_court:
    with CellStore(source) as store:
        if marker not in store.snapshot().cells:
            store.commit(store.revision, create=(Cell(marker, NULL_CELL_ID, NULL_CELL_ID, b'MAINFIX saved edit'),))
    # The fixture may retain committed WAL frames after an interrupted court.
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as db:
        before = db.execute('SELECT COUNT(*) FROM current_cells').fetchone()[0]
else:
    before = None
print(json.dumps({'fixture_bytes': source.stat().st_size, 'live_before': before, 'fresh_fixture_copy': fresh_copy}), flush=True)
faulthandler.dump_traceback_later(20, repeat=True)
adoption = persistence.prepare_application_database(root, stale, key_provider=keys)
selected = persistence.application_database_path(root)
assert selected == source
server = ApplicationServer(universal_state_path=selected, universal_key_provider=keys,
    conversation_history_path=persistence.application_content_path(selected),
    universal_workspace_root=work, legacy_state_directory=root,
    enable_machine_transport=False, enable_universal_cloud_gateway=False,
    enable_machine_projection_prewarm=False, enable_brain_cloud_sync=False, live_watch=False)
try:
    from nodelang.universal_application import project_universal_home_frame
    context = server.universal_registry.authorization.session.context(minimum_validity_seconds=5)
    canvas = project_universal_home_frame(server.universal_store, server.universal_registry, authentication_context=context)
    measurement = 'direct-authenticated-home'
    if '--boot-only' in sys.argv:
        from tests_replica.test_adopt_boot import _browser, _json as boot_json
        server.start()
        opener, _csrf = _browser(server)
        assert boot_json(opener, server, '/api/universal/canvas?screen=home')['ok']
        for asset in ('/studio/', '/studio/studio-lm.jsx'):
            with opener.open(server.url + asset, timeout=10) as response:
                assert response.status == 200 and response.read()
        measurement = 'authenticated-http-home-and-studio-assets'
    elapsed = time.monotonic() - started
    faulthandler.cancel_dump_traceback_later()
    assert server.universal_store.snapshot().cells[marker].atom == b'MAINFIX saved edit'
    print(json.dumps({'studio_home_seconds': elapsed, 'measurement': measurement,
        'saved_edit': True, 'selected_same_file': selected == source}), flush=True)
    if conversation_court:
        from urllib.parse import urlencode
        from tests_replica.test_clean_server_visual_projection import _json
        from nodelang import agent_composer, pipeline_engines
        from nodelang.existing_workshop_conversation import agent_graph_conversation_root
        pipeline_engines.brain_recall = lambda *_a, **_k: ({'out': ''}, '')
        calls = []
        def provider(prompt, *_a, **_k):
            calls.append(prompt)
            return json.dumps({'actions': [], 'answer': 'MAINFIX durable large reply'})
        agent_composer._chat = provider
        def request(path, body=None):
            began = time.monotonic()
            status, answer = _json(server.url, path, body,
                token=server.browser_session_token, csrf=server.browser_csrf_token)
            print(json.dumps({'path': path.split('?')[0], 'seconds': round(time.monotonic()-began, 3),
                'status': status, 'ok': answer.get('ok'), 'delivery': answer.get('delivery'),
                'error': answer.get('error')}), flush=True)
            assert status == 200, answer
            return answer
        server.start()
        canvas = request('/api/universal/canvas')
        scope = canvas['scope']['current']
        transcript_path = '/api/universal/workshop-transcript?' + urlencode({'node':'graph:'+scope,'scope':scope})
        conversation_root = agent_graph_conversation_root(server.universal_registry, scope)
        print(json.dumps({'scope':scope,'conversation_root':conversation_root,
            'content_path':str(persistence.application_content_path(selected))}), flush=True)
        faulthandler.dump_traceback_later(15, repeat=True)
        # The RED run acknowledged these writes before its transcript timed out.
        initial = request(transcript_path)
        texts = ('MAINFIX large saved message one', 'MAINFIX large saved message two')
        if '--expect-red-writes' in sys.argv:
            for text in texts:
                assert any(row['text'] == text for row in initial['rows'])
        run_id = str(time.time_ns())
        for index, text in enumerate(texts):
            answer = request('/api/universal/agent', {'prompt':text,'model':'court/free','graph':True,
                'graph_id':scope,'request_id':'mainfix-r2-large-'+run_id+'-'+str(index)})
            assert answer['delivery']['state'] == 'replied', answer
        first = request(transcript_path)
        server.close()
        server = ApplicationServer(universal_state_path=selected, universal_key_provider=keys,
            conversation_history_path=persistence.application_content_path(selected),
            universal_workspace_root=work, legacy_state_directory=root, enable_machine_transport=False,
            enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False,
            enable_brain_cloud_sync=False, live_watch=False).start()
        reopened = request(transcript_path)
        assert reopened['conversation_root'] == first['conversation_root'] == conversation_root
        assert reopened['rows'] == first['rows']
        for text in texts:
            assert any(row['text'] == text for row in reopened['rows'])
        assert calls == ['MAINFIX large saved message one', 'MAINFIX large saved message two']
        faulthandler.cancel_dump_traceback_later()
        print('MAINFIX_LARGE conversation_saved=2 reopened=2 provider_replayed=0', flush=True)
        raise SystemExit(0)
    assert elapsed <= 45, 'Studio exceeds the 45 s first-boot budget'
    if '--boot-only' in sys.argv:
        print(json.dumps({'FRESH_BOOT_PASS': True, 'fresh_fixture_copy': fresh_copy,
            'studio_home_seconds': elapsed, 'measurement': measurement, 'saved_edit': True}), flush=True)
        raise SystemExit(0)
    from nodelang.conversation_retention_maintenance import maintain_trace_families
    from nodelang.conversation_trace_receipts import maintain_trace_receipts
    service = server.conversation_content
    cancel = threading.Event()
    cursor = None
    deadline = time.monotonic() + 5400
    last = None
    inventory_done = False
    last_measure = 0.0
    last_progress = time.monotonic()
    live = before
    while time.monotonic() < deadline:
        if shutil.disk_usage(work).free < 25 * 1024**3:
            raise RuntimeError('lane court reached the founder disk reserve; source retained')
        context = server.universal_registry.authorization.session.context(minimum_validity_seconds=5)
        if not inventory_done:
            result = service.maintain_legacy_trace_inventory(authentication_context=context,
                cursor=cursor, cancellation_event=cancel, timeout_seconds=2.0)
            cursor = result.get('next_cursor')
            inventory_done = result['status'] == 'inventory-complete'
        if inventory_done:
            result = maintain_trace_families(service, authentication_context=context,
                cancellation_event=cancel, prepare_only=True)
            if result['status'] in ('family-ready', 'family-complete'):
                result = maintain_trace_receipts(service, authentication_context=context, cancellation_event=cancel)
                if result['status'] == 'receipts-complete':
                    result = maintain_trace_families(service, authentication_context=context, cancellation_event=cancel)
        if time.monotonic() - last_measure >= 5 or result['status'] == 'family-complete':
            connection, lock = server.universal_store.sqlite_storage()
            with lock:
                live = connection.execute('SELECT COUNT(*) FROM current_cells').fetchone()[0]
            last_measure = time.monotonic()
        state = (result['status'], live)
        if state != last:
            print(json.dumps({'archive_status': result['status'], 'live_cells': live}), flush=True)
            last = state
        if time.monotonic() - last_progress >= 30:
            history = service._history
            phase = history._db.execute('SELECT phase,cursor,delta_revision,delta_cell FROM trace_family_state WHERE singleton=1').fetchone()
            print(json.dumps({'archive_progress': list(phase) if phase else None,
                'elapsed_seconds': round(time.monotonic()-started, 1)}), flush=True)
            last_progress = time.monotonic()
        if result['status'] == 'family-complete':
            break
        if result['status'] == 'failed':
            raise RuntimeError(result)
    assert result['status'] == 'family-complete', 'background pass did not complete within the court budget'
    assert live <= 6_000_000, 'background pass left too many live cells'
    assert server.universal_store.snapshot().cells[marker].atom == b'MAINFIX saved edit'
    print(json.dumps({'BIG_PASS': True, 'studio_home_seconds': elapsed, 'live_before': before,
        'live_after': live, 'saved_edit': True}), flush=True)
finally:
    server.close()
