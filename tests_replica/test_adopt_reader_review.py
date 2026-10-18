"""Independent real-HTTP ADOPT archive navigation; synthetic profile only."""
from contextlib import closing
import json
from pathlib import Path
import secrets
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from nodelang import commit_intent, conversation_archive as archive
from nodelang import universal_application as app
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.universal_cell import Cell, NULL_CELL_ID
from nodelang.workshop_conversation_catalog import create_workshop_conversation
pytest_plugins = ("tests_replica.test_ogboot_upgrade_selection",)


def test_http_older_opens_verified_archive_only_on_demand_and_refuses_bad_reads(
        tmp_path, monkeypatch, isolated_profile):
    monkeypatch.setenv('ARCHHUB_GRAND_MAP_PATH',
        str(Path(app.__file__).parent / 'data/public_runtime_map.json'))
    keys = MemorySigningKeyProvider('archhub.local.relationship-authority', secrets.token_bytes(32))
    keys.add_key('archhub.local.court-attestation', secrets.token_bytes(32))
    server = ApplicationServer(universal_state_path=tmp_path / 'reader.sqlite3',
        universal_key_provider=keys, universal_workspace_root=tmp_path,
        enable_machine_transport=False, enable_universal_cloud_gateway=False,
        enable_machine_projection_prewarm=False, live_watch=False).start()
    try:
        registry, store = server.universal_registry, server.universal_store
        browser = server._resolve_browser_session(server.browser_session_token)
        with commit_intent.declare(commit_intent.USER_ACTION, actor=browser.subject_root,
                reason='independent archive reader court setup'):
            app.set_universal_scope(store, registry, registry.map.domains['brain'],
                authentication_context=browser.context)
            app.set_universal_scope(store, registry, registry.workshop_workbench_root,
                authentication_context=browser.context)
            foreign = create_workshop_conversation(server, authentication_context=browser.context,
                expected_revision=store.revision, title='Other independently admitted room',
                participant_roots=[browser.subject_root], idempotency_key='archive-reader-foreign')['root']

        text = 'ADOPT independent cold-only testimony 71e2\n' + '\u754c' * 17000
        trace = Cell('app:workshop:reader-review:chain:0', NULL_CELL_ID, NULL_CELL_ID, text.encode())
        with commit_intent.declare(commit_intent.MIGRATION, actor='independent archive court',
                reason='seed verified synthetic cold custody'):
            store.commit(store.revision, create=(trace,))
        history = server.conversation_content._history
        history.initialize_trace_maintenance()
        history.admit_trace_custody(store.authority_identity, registry.application_root)
        cold_path = archive.trace_archive_path(server.conversation_content._path)
        connection, lock = store.sqlite_storage()
        with lock, closing(archive.preserve_trace_batch(connection, cold_path,
                store.authority_identity, (trace.id,), {trace.id: registry.workshop_root},
                lambda: None)[0]) as cold:
            history.index_trace_archive(cold, (registry.workshop_root,), archive_path=cold_path,
                cell_ids=(trace.id,))
            store.partition_archived_cells(cold, (trace.id,), check=lambda: None)
        assert trace.id not in store.snapshot().cells
        assert connection.execute('SELECT 1 FROM cell_versions WHERE cell_id=?', (trace.id,)).fetchone() is None
        original_graph = {cell.id: cell for cell in store.snapshot().cells.values()}
        revision = store.revision

        cold_opens = []
        open_cold = archive._open_trace_archive

        def observed_open(path, authority, **options):
            cold_opens.append((Path(path), options['create']))
            return open_cold(path, authority, **options)

        monkeypatch.setattr(archive, '_open_trace_archive', observed_open)

        def request(root=registry.workshop_root, before=None):
            query = {'root': root, 'scope': registry.workshop_workbench_root}
            if before is not None:
                query['before'] = before
            call = Request(server.url + '/api/universal/workshop?' + urlencode(query), headers={
                'Content-Type': 'application/json', 'Origin': server.url,
                'Cookie': 'ArchHub-Session=' + server.browser_session_token,
                'X-ArchHub-CSRF': server.browser_csrf_token})
            try:
                with urlopen(call, timeout=30) as response:
                    raw = response.read()
                    return response.status, json.loads(raw), raw
            except HTTPError as refused:
                raw = refused.read()
                return refused.code, json.loads(raw), raw

        def accepted(before=None):
            status, page, _raw = request(before=before)
            assert status == 200 and page.get('ok') is not False, page
            assert len(json.dumps(page, separators=(',', ':')).encode()) <= 262144
            return page

        def refused(root=registry.workshop_root, before=None):
            status, page, raw = request(root, before)
            assert status in (400, 403, 409, 503) and page.get('ok') is False, (status, page)
            assert text[:42] not in raw.decode() and len(raw) <= 262144

        latest = accepted()
        assert cold_opens == []
        assert text[:42] not in json.dumps(latest)
        assert latest['has_older'] is True and latest['next_before'].startswith('a1:')
        token = latest['next_before']
        status, foreign_page, _ = request(foreign)
        assert status == 200 and foreign_page.get('ok') is not False, foreign_page
        refused(foreign, token)
        assert cold_opens == []

        first = accepted(token)
        assert cold_opens and all(path == cold_path and create is False for path, create in cold_opens)
        assert first['page_before'] == token
        assert first['can_send'] is False and first['can_manage_history'] is False
        assert len(first['messages']) == 1
        message = first['messages'][0]
        assert message['archive_projection'] is True and message['state'] == 'archived'
        assert message['root'].startswith('trace-archive:') and message['root'] != trace.id
        assert message['body'] == 'Archived conversation (read only)\n\n' + text[:16384]
        assert first['has_older'] is True and first['next_before'].startswith('a1:')
        second = accepted(first['next_before'])
        assert second['messages'][0]['body'] == 'Archived conversation (read only)\n\n' + text[16384:]
        assert second['has_older'] is False and second['next_before'] is None

        # A legitimate index refresh invalidates already-issued archive positions.
        with history._transaction(write=True):
            history._db.execute('UPDATE trace_sessions SET content=content WHERE session_id=?',
                (registry.workshop_root,))
        before_stale = len(cold_opens)
        refused(before=token)
        assert len(cold_opens) == before_stale
        token = accepted()['next_before']

        # Tampering with cold bytes must fail even after the projection was cached.
        with closing(open_cold(cold_path, store.authority_identity, create=True)) as writer:
            writer.execute('UPDATE trace_current SET atom=? WHERE cell_id=?', (b'counterfeit', trace.id))
        try:
            refused(before=token)
        finally:
            with closing(open_cold(cold_path, store.authority_identity, create=True)) as writer:
                writer.execute('UPDATE trace_current SET atom=? WHERE cell_id=?', (trace.atom, trace.id))
        assert accepted(token)['messages'][0]['body'].endswith(text[:16384])

        # The HTTP formatter must independently enforce its complete envelope cap.
        read_session = history.archived_trace_session

        def oversized(session_id, **options):
            result = read_session(session_id, **options)
            if options.get('offset') is not None and result is not None:
                result = {**result, 'content': 'x' * 262145}
            return result

        with monkeypatch.context() as bounded:
            bounded.setattr(history, 'archived_trace_session', oversized)
            refused(before=token)
        assert store.revision == revision
        assert {cell.id: cell for cell in store.snapshot().cells.values()} == original_graph
    finally:
        server.close()


def test_interrupted_empty_trace_initialization_does_not_block_reads_or_trust_foreign_owner(
        tmp_path, monkeypatch):
    import pytest
    from nodelang.conversation_history import ConversationHistoryStore
    from nodelang.universal_cell import CellStore

    path = tmp_path / 'interrupted-history.sqlite3'
    instance, room, application = 'interrupted-reader', 'app:workshop:main', 'app:archhub'
    expected = ('expected-current-journal-owner', application)
    # This close/reopen preserves exactly the committed state at a kill between
    # additive schema initialization and the separate owner-admission transaction.
    with ConversationHistoryStore(path, instance_id=instance) as history:
        history.ensure_conversation(room)
        history.initialize_trace_maintenance()
        assert history._db.execute('SELECT COUNT(*) FROM trace_sessions').fetchone()[0] == 0
        assert history._db.execute('SELECT COUNT(*) FROM trace_owner').fetchone()[0] == 0

    opened = []
    original_open = archive._open_trace_archive

    def observed_open(*args, **kwargs):
        opened.append(args[0])
        return original_open(*args, **kwargs)

    monkeypatch.setattr(archive, '_open_trace_archive', observed_open)
    with ConversationHistoryStore(path, instance_id=instance, create=False) as history:
        assert history.archived_trace_session(None, metadata_only=True, catalogue=True,
            expected_owner=expected) is None
        assert history.archived_trace_session(room, metadata_only=True, expected_owner=expected) is None
        assert opened == []

        session = 'app:agent-session:other-profile'
        cell = Cell(session+':chain:0', NULL_CELL_ID, NULL_CELL_ID, b'foreign archived text')
        cold_path = tmp_path / 'other-profile-cold.sqlite3'
        with CellStore(tmp_path / 'other-profile.sqlite3') as source:
            source.commit(source.revision, create=(cell,))
            history.admit_trace_custody(source.authority_identity, application)
            connection, lock = source.sqlite_storage()
            with lock, closing(archive.preserve_trace_batch(connection, cold_path,
                    source.authority_identity, (cell.id,), {cell.id: session}, lambda: None)[0]) as cold:
                history.index_trace_archive(cold, (session,), archive_path=cold_path, cell_ids=(cell.id,))
        opened.clear()  # fixture copying above is distinct from application reads
        for selected, options in (
                (None, dict(metadata_only=True, catalogue=True)),
                (session, dict(metadata_only=True)),
                (session, dict(offset=0))):
            with pytest.raises(ValueError, match='another source owner'):
                history.archived_trace_session(selected, expected_owner=expected, **options)
        assert opened == []


def test_main_workshop_discovers_nonroom_archive_sessions_with_owner_authority(
        tmp_path, monkeypatch, isolated_profile):
    import base64
    import time
    from nodelang.conversation_content import read_content_binding
    from nodelang.existing_workshop_conversation import _workshop_position_token

    monkeypatch.setenv('ARCHHUB_GRAND_MAP_PATH',
        str(Path(app.__file__).parent / 'data/public_runtime_map.json'))
    keys = MemorySigningKeyProvider('archhub.local.relationship-authority', secrets.token_bytes(32))
    keys.add_key('archhub.local.court-attestation', secrets.token_bytes(32))
    server = ApplicationServer(universal_state_path=tmp_path / 'nonroom-reader.sqlite3',
        universal_key_provider=keys, universal_workspace_root=tmp_path,
        enable_machine_transport=False, enable_universal_cloud_gateway=False,
        enable_machine_projection_prewarm=False, live_watch=False).start()
    try:
        registry, store = server.universal_registry, server.universal_store
        browser = server._resolve_browser_session(server.browser_session_token)
        authority = registry.authorization
        member = 'court:archive-reader:delegated-principal'
        with commit_intent.declare(commit_intent.USER_ACTION, actor=browser.subject_root,
                reason='independent non-room archive reader setup'):
            app.set_universal_scope(store, registry, registry.map.domains['brain'],
                authentication_context=browser.context)
            app.set_universal_scope(store, registry, registry.workshop_workbench_root,
                authentication_context=browser.context)
            foreign = create_workshop_conversation(server, authentication_context=browser.context,
                expected_revision=store.revision, title='Room archive remains room-authorized',
                participant_roots=[browser.subject_root], idempotency_key='nonroom-reader-foreign')['root']
            store.commit(store.revision, create=(Cell(member, NULL_CELL_ID, NULL_CELL_ID,
                b'A different signed subject with delegated application read authority'),))
            app.provision_universal_view_session(store, registry, member,
                principal_root=authority.principal_root, visible_roots=())
            member_context = authority.broker.mint_authenticated_context(member,
                principal_roots=(authority.principal_root,), tenant_root=authority.tenant_root,
                assurance_root=authority.assurance_root, lifetime_seconds=900)
            member_token, _csrf = server.issue_browser_session(member_context)
        member_binding = server._resolve_browser_session(member_token)

        texts = {
            'app:agent-session:reader-global': 'AGENT cold testimony 6359\n' + 'A' * 17000,
            'app:baboom-session:reader-global': 'BABOOM cold testimony 3814',
            'app:deliberation-payload:reader-global-orphan': 'ORPHAN payload testimony 7521',
        }
        own_text, foreign_text = 'Main room archive before global sessions', 'Other room private archive 4923'
        cells = tuple(Cell(session+':chain:0', NULL_CELL_ID, NULL_CELL_ID, text.encode())
            for session, text in texts.items())
        own = Cell('app:workshop:reader-global-main:chain:0', NULL_CELL_ID, NULL_CELL_ID, own_text.encode())
        other = Cell('app:workshop:reader-global-foreign:chain:0', NULL_CELL_ID, NULL_CELL_ID,
            foreign_text.encode())
        sessions = {cell.id: session for cell, session in zip(cells, texts)}
        sessions.update({own.id: registry.workshop_root, other.id: foreign})
        identifiers = (*sessions,)
        with commit_intent.declare(commit_intent.MIGRATION, actor='independent archive court',
                reason='seed exact synthetic non-room cold custody'):
            store.commit(store.revision, create=(*cells, own, other))
        history = server.conversation_content._history
        history.initialize_trace_maintenance()
        history.admit_trace_custody(store.authority_identity, registry.application_root)
        room_binding = read_content_binding(store.snapshot(), registry.deliberation_protocol,
            application_root=registry.application_root, space_root=foreign)
        with history._transaction(write=True):
            history._db.execute('INSERT INTO trace_migrations(conversation_id,source_authority,'
                'source_revision,delta_cell,cursor,controls,state,binding_root,last_activity_at) '
                'VALUES(?,?,?,?,?,?,?,?,?)', (foreign, store.authority_identity, store.revision,
                '', '', '[]', 'bound', room_binding.root_id, time.time()-40*86400))
        cold_path = archive.trace_archive_path(server.conversation_content._path)
        connection, lock = store.sqlite_storage()
        with lock, closing(archive.preserve_trace_batch(connection, cold_path,
                store.authority_identity, identifiers, sessions, lambda: None)[0]) as cold:
            store.partition_archived_cells(cold, identifiers, check=lambda: None)
        assert set(identifiers).isdisjoint(store.snapshot().cells)

        opens = []
        open_cold = archive._open_trace_archive

        def observed_open(path, source_authority, **options):
            opens.append((Path(path), options['create']))
            return open_cold(path, source_authority, **options)

        monkeypatch.setattr(archive, '_open_trace_archive', observed_open)

        def request(*, root=registry.workshop_root, before=None, feed='all',
                token=server.browser_session_token, content_after=None, path=None,
                scope=registry.workshop_workbench_root):
            query = {'root': root, 'scope': scope, 'feed': feed}
            if before is not None:
                query['before'] = before
            if content_after is not None:
                query['content_after'] = content_after
            call = Request(server.url + (path or '/api/universal/workshop?' + urlencode(query)),
                headers={'Origin': server.url, 'Cookie': 'ArchHub-Session=' + token})
            try:
                with urlopen(call, timeout=30) as response:
                    return response.status, json.loads(response.read())
            except HTTPError as refused:
                return refused.code, json.loads(refused.read())

        def accepted(**options):
            status, page = request(**options)
            assert status == 200 and page.get('ok') is not False, (status, page)
            assert len(json.dumps(page, separators=(',', ':')).encode()) <= 262144
            return page

        def refused(**options):
            status, page = request(**options)
            assert status in (400, 403, 409, 503) and page.get('ok') is False, (status, page)
            assert all(text[:24] not in json.dumps(page) for text in (*texts.values(), foreign_text))

        def parts(token):
            fields = token.split(':')
            assert len(fields) == 5 and fields[0] == 'a2', token
            session = base64.urlsafe_b64decode(fields[1] + '=' * (-len(fields[1]) % 4)).decode()
            return session, int(fields[2]), int(fields[3])

        content_binding = read_content_binding(store.snapshot(), registry.deliberation_protocol,
            application_root=registry.application_root, space_root=registry.workshop_root)

        def position(session, generation, *, root=registry.workshop_root, binding=browser, feed='all',
                scope=registry.workshop_workbench_root):
            encoded = base64.urlsafe_b64encode(session.encode()).decode().rstrip('=')
            identity = [registry.application_root, content_binding.instance_id, root,
                scope, binding.subject_root, binding.view_root,
                binding.subject_root == authority.subject_root]
            if feed != 'all':
                identity.append(feed)
            return _workshop_position_token('a2', (encoded, 0, generation), identity)

        # This is a real, authenticated second subject that can read the normal
        # main Workshop from its own top canvas (SPEC section 6). It is assigned
        # no founder-owned WIP resources. The global archive gate must refuse it.
        status, canvas = request(path='/api/universal/canvas', token=member_token)
        assert status == 200 and canvas.get('ok') is not False, (status, canvas)
        assert canvas['authorization']['subject'] == member != authority.subject_root
        ordinary_member = accepted(token=member_token, scope=registry.canvas_root)
        assert not (ordinary_member.get('next_before') or '').startswith('a2:')
        initial = accepted()
        assert initial['has_older'] is False and opens == []
        original_graph = dict(store.snapshot().cells)
        revision = store.revision

        # Only the idle index changes; ordinary message etags and graph do not.
        with closing(open_cold(cold_path, store.authority_identity, create=False)) as cold:
            history.index_trace_archive(cold, (*texts, foreign), archive_path=cold_path,
                cell_ids=tuple(cell.id for cell in (*cells, other)))
        latest = accepted(content_after=initial['content_cursor'])
        assert latest.get('unchanged') is not True
        assert latest['has_older'] is True and latest['next_before'].startswith('a2:')
        assert opens == [], 'catalogue discovery must not open cold custody'
        cursor = first_token = latest['next_before']
        seen, bodies = [], {}
        for _ in range(8):
            session, offset, generation = parts(cursor)
            assert session in texts and session != foreign
            if offset == 0:
                seen.append(session)
            page = accepted(before=cursor)
            assert page['page_before'] == cursor and page['can_send'] is False
            assert page['can_manage_history'] is False and len(page['messages']) == 1
            message = page['messages'][0]
            assert message['archive_projection'] is True and message['state'] == 'archived'
            chunk = texts[session][offset:offset+16384]
            assert message['body'].endswith(chunk)
            bodies[session] = bodies.get(session, '') + chunk
            if not page['has_older']:
                assert page['next_before'] is None
                break
            cursor = page['next_before']
        else:
            raise AssertionError('bounded three-session archive did not terminate')
        assert seen == sorted(texts) and bodies == texts
        assert opens and all(path == cold_path and not create for path, create in opens)

        session, _offset, generation = parts(first_token)
        before_refusal = len(opens)
        refused(before=position(session, generation, binding=member_binding, scope=registry.canvas_root),
            token=member_token, scope=registry.canvas_root)
        refused(root=foreign, before=position(session, generation, root=foreign))
        refused(feed='messages', before=position(session, generation, feed='messages'))
        foreign_generation = history._db.execute('SELECT generation FROM trace_projection_versions '
            'WHERE session_id=?', (foreign,)).fetchone()[0]
        refused(before=position(foreign, foreign_generation))
        # Before room publication, its real migration has no binding root yet.
        # That partial state must not reclassify room text as a global session.
        with history._transaction(write=True):
            history._db.execute("UPDATE trace_migrations SET binding_root=NULL,state='copying' "
                'WHERE conversation_id=?', (foreign,))
        try:
            refused(before=position(foreign, foreign_generation))
        finally:
            with history._transaction(write=True):
                history._db.execute("UPDATE trace_migrations SET binding_root=?,state='bound' "
                    'WHERE conversation_id=?', (room_binding.root_id, foreign))
        assert len(opens) == before_refusal
        assert accepted(root=foreign)['next_before'].startswith('a1:')

        with history._transaction(write=True):
            history._db.execute('UPDATE trace_sessions SET content=content WHERE session_id=?', (session,))
        before_stale = len(opens)
        refused(before=first_token)
        assert len(opens) == before_stale
        fresh = accepted(content_after=latest['content_cursor'])['next_before']
        assert parts(fresh)[0] == session and parts(fresh)[2] > generation
        accepted(before=fresh)  # warm the exact session projection before tampering
        source_cell = next(cell for cell in cells if sessions[cell.id] == session)
        with closing(open_cold(cold_path, store.authority_identity, create=True)) as writer:
            writer.execute('UPDATE trace_current SET atom=? WHERE cell_id=?',
                (b'forged non-room history', source_cell.id))
        try:
            refused(before=fresh)
        finally:
            with closing(open_cold(cold_path, store.authority_identity, create=True)) as writer:
                writer.execute('UPDATE trace_current SET atom=? WHERE cell_id=?',
                    (source_cell.atom, source_cell.id))
        accepted(before=fresh)

        # A main-room a1 archive remains first and hands off to the same global
        # catalogue at its end, without creating an ordinary message or Cell.
        with closing(open_cold(cold_path, store.authority_identity, create=False)) as cold:
            history.index_trace_archive(cold, (registry.workshop_root,), archive_path=cold_path,
                cell_ids=(own.id,))
        own_page = accepted(before=accepted()['next_before'])
        assert own_page['page_before'].startswith('a1:')
        assert own_page['messages'][0]['body'].endswith(own_text)
        assert own_page['has_older'] is True and own_page['next_before'].startswith('a2:')
        assert store.revision == revision and dict(store.snapshot().cells) == original_graph
    finally:
        server.close()
