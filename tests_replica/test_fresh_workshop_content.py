"""Normal first creation must enable indexed Workshop content without fixture adoption."""
import json
from pathlib import Path
import secrets
from urllib.request import Request, urlopen
from urllib.parse import urlencode

import pytest

from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.conversation_content import ApplicationConversationContent, read_content_binding
from nodelang import universal_application as app
from nodelang.universal_cell import InvalidCell


@pytest.mark.parametrize("suffix", ["", "-wal", "-journal", "-shm"])
@pytest.mark.parametrize("custom_path", [False, True])
def test_unknown_content_custody_refuses_before_graph_creation(tmp_path, monkeypatch, suffix, custom_path):
    import nodelang.application_server as module
    database = tmp_path / "new.sqlite3"
    content = tmp_path / "selected.sqlite3" if custom_path else Path(str(database) + ".conversations.sqlite3")
    artifact = Path(str(content) + suffix)
    artifact.write_bytes(b"existing custody")
    monkeypatch.setattr(module, "CellStore", lambda *a, **k: pytest.fail("graph creation preceded content preflight"))
    with pytest.raises(InvalidCell, match="content file or SQLite sidecar already exists"):
        ApplicationServer(universal_state_path=database,
            conversation_history_path=content if custom_path else None,
            enable_machine_transport=False, enable_universal_cloud_gateway=False)
    assert not database.exists()
    assert artifact.read_bytes() == b"existing custody"


@pytest.fixture
def empty_bootstrap(tmp_path, monkeypatch):
    """Real small graph/SQLite; application edit admission is a named fixture.

    Full constructor, signed application access and HTTP are checked separately.
    This fixture isolates content commit failure and physical reservation custody.
    """
    from types import SimpleNamespace
    from threading import RLock
    from nodelang.universal_cell import CellStore
    from nodelang.conversation_content import record_fresh_content_bootstrap
    import tests_replica.test_cell_deliberation as fixture

    database, content = tmp_path / "graph.sqlite3", tmp_path / "content.sqlite3"
    store = CellStore(database)
    record_fresh_content_bootstrap(store, content)
    with monkeypatch.context() as setup:
        setup.setattr(fixture, "CellStore", lambda *a: store)
        _, protocol, authorization, broker, context, _ = fixture._system(database)
    registry = SimpleNamespace(application_root="workspace", workshop_root="test:workshop",
        deliberation_protocol=protocol,
        authorization=SimpleNamespace(broker=broker, session=SimpleNamespace(context=lambda: context)))
    owner = SimpleNamespace(mutation_lock=RLock(), universal_store=store, universal_registry=registry,
        universal_checkpoint_guard=None, runtime_handoff_exit_requested=False, _fresh_content_bootstrap=True,
        test_authorization=(authorization, broker, context))
    owner.conversation_content = ApplicationConversationContent(owner, content)
    monkeypatch.setattr(app, "_require_application_authorization", lambda *a, **k: None)
    try:
        yield owner
    finally:
        owner.conversation_content.close()
        store.close()


@pytest.mark.parametrize("failure", ["history-open", "retention", "commit-before"])
def test_proven_absent_binding_cleans_only_own_reservation_and_retries(empty_bootstrap, monkeypatch, failure):
    import nodelang.conversation_history as history_module
    from nodelang.conversation_content import fresh_content_bootstrap_pending, read_fresh_content_bootstrap
    owner = empty_bootstrap
    content, store, registry = owner.conversation_content, owner.universal_store, owner.universal_registry
    intent = read_fresh_content_bootstrap(store.snapshot())

    def refused(*a, **k):
        raise RuntimeError("injected before binding")

    with monkeypatch.context() as fail:
        if failure == "history-open":
            fail.setattr(history_module.ConversationHistoryStore, "__init__", refused)
        elif failure == "retention":
            fail.setattr(history_module.ConversationHistoryStore, "initialize_retention", refused)
        else:
            fail.setattr(registry.authorization.broker, "commit_authenticated", refused)
        with pytest.raises(RuntimeError, match="injected before binding"):
            content.initialize_fresh_workshop()
    assert not content._path.exists()
    assert read_fresh_content_bootstrap(store.snapshot()) == intent
    assert fresh_content_bootstrap_pending(store, registry, content._path)
    owner._fresh_content_bootstrap = True
    content.initialize_fresh_workshop()
    settled = read_fresh_content_bootstrap(store.snapshot())
    assert settled["bootstrap_id"] == intent["bootstrap_id"] and settled["state"] == "bound"
    assert not fresh_content_bootstrap_pending(store, registry, content._path)


@pytest.mark.parametrize("published", [False, True])
def test_uncertain_commit_preserves_reserved_content(empty_bootstrap, monkeypatch, published):
    from nodelang.conversation_content import fresh_content_bootstrap_pending, read_fresh_content_bootstrap
    owner = empty_bootstrap
    content, store, registry = owner.conversation_content, owner.universal_store, owner.universal_registry
    commit = registry.authorization.broker.commit_authenticated

    def uncertain(*a, **k):
        if published:
            commit(*a, **k)
        raise RuntimeError("uncertain commit receipt")

    with monkeypatch.context() as fail:
        fail.setattr(registry.authorization.broker, "commit_authenticated", uncertain)
        if not published:
            fail.setattr(store, "refresh", lambda: (_ for _ in ()).throw(RuntimeError("refresh unavailable")))
        with pytest.raises(InvalidCell, match="reserved content retained"):
            content.initialize_fresh_workshop()
    assert content._path.is_file()
    marker = read_fresh_content_bootstrap(store.snapshot())
    if published:
        assert marker["state"] == "bound"
        assert not fresh_content_bootstrap_pending(store, registry, content._path)
        binding = read_content_binding(store.snapshot(), registry.deliberation_protocol,
            application_root=registry.application_root, space_root=registry.workshop_root)
        from nodelang.conversation_history import ConversationHistoryStore
        with ConversationHistoryStore(content._path, instance_id=binding.instance_id, create=False) as history:
            assert history.conversation_head(registry.workshop_root) == 0
    else:
        assert marker["state"] == "pending"
        with pytest.raises(InvalidCell, match="content file or SQLite sidecar already exists"):
            fresh_content_bootstrap_pending(store, registry, content._path)


@pytest.mark.parametrize("refusal", ["authorization", "checkpoint", "foreign-reservation", "changed-path"])
def test_refusal_precedes_content_reservation(empty_bootstrap, monkeypatch, refusal):
    owner = empty_bootstrap
    content, store = owner.conversation_content, owner.universal_store
    revision = store.revision
    if refusal == "authorization":
        monkeypatch.setattr(app, "_require_application_authorization",
            lambda *a, **k: (_ for _ in ()).throw(InvalidCell("admission refused")))
    elif refusal == "checkpoint":
        from types import SimpleNamespace
        owner.universal_checkpoint_guard = SimpleNamespace(require_healthy=
            lambda: (_ for _ in ()).throw(InvalidCell("checkpoint refused")))
    elif refusal == "foreign-reservation":
        content._path.write_bytes(b"foreign reserved file")
    else:
        content._path = content._path.with_name("changed.sqlite3")
    with pytest.raises(InvalidCell):
        content.initialize_fresh_workshop()
    assert store.revision == revision
    if refusal == "foreign-reservation":
        assert content._path.read_bytes() == b"foreign reserved file"
    else:
        assert not content._path.exists()


@pytest.mark.parametrize("existing", ["legacy-entry", "binding", "instance"])
def test_pending_intent_never_adopts_existing_graph_content(empty_bootstrap, existing):
    from nodelang.conversation_content import prepare_empty_content_binding
    from nodelang.cell_protocols import prepare_append_relation_members
    from nodelang.cell_deliberation import _terminal
    from tests_replica.test_cell_deliberation import _append
    owner = empty_bootstrap
    content, store, registry = owner.conversation_content, owner.universal_store, owner.universal_registry
    if existing == "legacy-entry":
        _append(store, registry.deliberation_protocol, *owner.test_authorization)
    elif existing == "binding":
        prepared = prepare_empty_content_binding(store.snapshot(), registry.deliberation_protocol,
            application_root=registry.application_root, space_root=registry.workshop_root)
        store.commit(prepared.expected_revision, create=prepared.create, replace=prepared.replace)
    else:
        patch = prepare_append_relation_members(store.snapshot(), registry.application_root,
            ((registry.deliberation_protocol.role("scope-content-instance"), "existing-instance"),))
        store.commit(store.revision, create=patch.create + (_terminal("existing-instance", "already-owned"),),
            replace=patch.replace)
    revision = store.revision
    with pytest.raises(InvalidCell, match="pending graph is not empty and unbound"):
        content.initialize_fresh_workshop()
    assert not content._path.exists()
    assert store.revision == revision


def test_unresolved_sidecar_is_preserved_even_when_binding_is_absent(empty_bootstrap, monkeypatch):
    from nodelang.conversation_history import ConversationHistoryStore
    owner = empty_bootstrap
    content = owner.conversation_content
    sidecar = Path(str(content._path) + "-wal")
    def failed_retention(self):
        sidecar.write_bytes(b"unknown sidecar custody")
        raise RuntimeError("injected content failure")
    monkeypatch.setattr(ConversationHistoryStore, "initialize_retention", failed_retention)
    with pytest.raises(InvalidCell, match="reserved content retained"):
        content.initialize_fresh_workshop()
    assert content._path.exists()
    assert sidecar.read_bytes() == b"unknown sidecar custody"


@pytest.mark.parametrize("caller_store", [False, True])
def test_memory_and_caller_owned_graphs_do_not_initialize_content(tmp_path, monkeypatch, caller_store):
    from nodelang.universal_cell import CellStore
    from nodelang.cell_deliberation import read_deliberation_space
    from nodelang.conversation_content import read_fresh_content_bootstrap
    public_map = Path(app.__file__).parent / "data/public_runtime_map.json"
    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH", str(public_map))
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    content = tmp_path / "explicit-content.sqlite3"
    supplied = {}
    store = None
    if caller_store:
        store = CellStore(tmp_path / "caller.sqlite3")
        try:
            store, registry = app.build_universal_application(public_map, store,
                key_provider=keys, court_workspace_root=tmp_path)
        except BaseException:
            store.close()
            raise
        supplied = dict(universal_store=store, universal_registry=registry)
    def forbidden(self):
        pytest.fail("in-memory or caller-owned constructor attempted content initialization")
    monkeypatch.setattr(ApplicationConversationContent, "initialize_fresh_workshop", forbidden)
    server = None
    try:
        server = ApplicationServer(**supplied, conversation_history_path=content,
            universal_key_provider=keys, universal_workspace_root=tmp_path, enable_machine_transport=False,
            enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False, live_watch=False)
        assert not content.exists()
        assert server._fresh_content_bootstrap is False
        snapshot, registry = server.universal_store.snapshot(), server.universal_registry
        assert read_fresh_content_bootstrap(snapshot) is None
        assert read_deliberation_space(snapshot, registry.deliberation_protocol,
            registry.workshop_root).content_store_root is None
    finally:
        if server is not None:
            server.close()
        elif store is not None:
            store.close()


def test_failed_build_leaves_explicit_same_graph_recovery(tmp_path, monkeypatch):
    import nodelang.application_server as module
    from nodelang.conversation_content import read_fresh_content_bootstrap
    from nodelang.universal_cell import CellStore
    database = tmp_path / "partial.sqlite3"
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    def failed_build(*a, **k):
        raise RuntimeError("injected partial application build")
    monkeypatch.setattr(module, "build_universal_application", failed_build)
    with pytest.raises(RuntimeError, match="partial application build"):
        ApplicationServer(universal_state_path=database, universal_key_provider=keys,
            enable_machine_transport=False, enable_universal_cloud_gateway=False)
    with CellStore(database) as store:
        original = read_fresh_content_bootstrap(store.snapshot())
        revision = store.revision
    with pytest.raises(InvalidCell, match="incomplete or unmarked existing graph"):
        ApplicationServer(universal_state_path=database, universal_key_provider=keys,
            enable_machine_transport=False, enable_universal_cloud_gateway=False)
    with CellStore(database) as store:
        assert store.revision == revision
        assert read_fresh_content_bootstrap(store.snapshot()) == original


def test_interrupted_constructor_resumes_same_empty_bootstrap(tmp_path, monkeypatch):
    from nodelang.conversation_content import read_fresh_content_bootstrap
    from nodelang.universal_cell import CellStore
    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH", str(Path(app.__file__).parent / "data/public_runtime_map.json"))
    database = tmp_path / "interrupted.sqlite3"
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    def construct():
        return ApplicationServer(universal_state_path=database, universal_key_provider=keys,
            universal_workspace_root=tmp_path, enable_machine_transport=False,
            enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False, live_watch=False)
    with monkeypatch.context() as fail:
        fail.setattr(ApplicationServer, "_claim_runtime_ownership",
            lambda self: (_ for _ in ()).throw(RuntimeError("interrupted before content initialization")))
        with pytest.raises(RuntimeError, match="interrupted before content initialization"):
            construct()
    with CellStore(database) as store:
        intent = read_fresh_content_bootstrap(store.snapshot())
        application = store.snapshot().cells["app:archhub"]
    assert intent["state"] == "pending"
    assert not Path(str(database) + ".conversations.sqlite3").exists()
    server = construct()
    try:
        registry = server.universal_registry
        binding = read_content_binding(server.universal_store.snapshot(), registry.deliberation_protocol,
            application_root=registry.application_root, space_root=registry.workshop_root)
        settled = read_fresh_content_bootstrap(server.universal_store.snapshot())
        assert settled["bootstrap_id"] == intent["bootstrap_id"]
        assert settled["instance_id"] == binding.instance_id
        assert server.universal_store.snapshot().cells["app:archhub"].id == application.id
        assert server.conversation_content._history.instance_id == binding.instance_id
    finally:
        server.close()


def test_first_boot_http_workshop_send_and_same_binding_after_reopen(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH", str(Path(app.__file__).parent / "data/public_runtime_map.json"))
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    database = tmp_path / "fresh-public.sqlite3"

    def start():
        return ApplicationServer(universal_state_path=database, universal_key_provider=keys,
            universal_workspace_root=tmp_path, enable_machine_transport=False,
            enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False,
            live_watch=False).start()

    def request(path, body=None):
        call = Request(server.url + path, headers={"Content-Type":"application/json", "Origin":server.url,
            "Cookie":"ArchHub-Session=" + server.browser_session_token,
            "X-ArchHub-CSRF":server.browser_csrf_token},
            data=None if body is None else json.dumps(body).encode())
        with urlopen(call, timeout=30) as response:
            result = json.loads(response.read())
            assert response.status == 200 and result.get("ok") is not False, result
            return result

    server = start()
    try:
        registry = server.universal_registry
        binding = read_content_binding(server.universal_store.snapshot(), registry.deliberation_protocol,
            application_root=registry.application_root, space_root=registry.workshop_root)
        content_path = server.conversation_content._path
        assert str(content_path) == str(database) + ".conversations.sqlite3"
        assert content_path.is_file()
        assert server.conversation_content._history.instance_id == binding.instance_id
        browser = server._resolve_browser_session(server.browser_session_token)
        app.set_universal_scope(server.universal_store, registry, registry.map.domains["brain"],
            authentication_context=browser.context)
        app.set_universal_scope(server.universal_store, registry, registry.workshop_workbench_root,
            authentication_context=browser.context)
        sent = request("/api/universal/workshop", {"root":registry.workshop_root,
            "scope":registry.workshop_workbench_root, "category":"note", "text":"Fresh public Workshop message",
            "refs":[], "evidence":[], "recipients":[browser.subject_root], "reply_to":None,
            "idempotency_key":"first-public-message", "created_at":None})
        assert sent["storage"] == "conversation-content"
        message_id = sent["message_id"]
        query = urlencode({"root":registry.workshop_root, "scope":registry.workshop_workbench_root})
        assert message_id in str(request("/api/universal/workshop?" + query))
        revision = server.universal_store.revision
        with pytest.raises(InvalidCell, match="newly created application"):
            server.conversation_content.initialize_fresh_workshop()
        assert server.universal_store.revision == revision
    finally:
        server.close()

    def forbidden_reinitialization(self):
        pytest.fail("Restoring an instance must not initialize or adopt its content")
    monkeypatch.setattr(ApplicationConversationContent, "initialize_fresh_workshop", forbidden_reinitialization)
    server = start()
    try:
        registry = server.universal_registry
        reopened = read_content_binding(server.universal_store.snapshot(), registry.deliberation_protocol,
            application_root=registry.application_root, space_root=registry.workshop_root)
        assert reopened == binding
        assert server.conversation_content._path == content_path
        page = request("/api/universal/workshop?" + query)
        assert message_id in str(page)
        assert "Fresh public Workshop message" in str(page)
    finally:
        server.close()
