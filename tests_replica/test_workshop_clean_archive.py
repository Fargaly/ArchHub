"""Courts: the clean Workshop is preserved once, field for field, as its own archive conversation (plan B, S4).

The source is a REAL clean graph built by the clean coordination court's own foundation
(signed founder caller, two bound Agent Sessions attached to the Workshop, messages sent,
replied to and read through GraphAgentCoordinator). The target is a real universal owner
whose Workshop is bound to conversation content in tmp_path. Nothing touches a live graph.
"""
import hashlib
import json
import sqlite3
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nodelang import application_server as server_module
from nodelang.cell_authorization import RefusedWithoutEffect
from nodelang.cell_deliberation import read_deliberation_space
from nodelang.cell_protocols import read_relation
from nodelang.universal_cell import InvalidCell
from nodelang.workshop_clean_archive import (
    ARCHIVE_TITLE, archive_label, export_clean_workshop_archive, import_clean_workshop_archive,
    record_digest, validate_clean_archive_record)
from tests_replica.test_clean_agent_coordination import _command, _foundation, _session
from tests_replica.test_universal_workshop_assignments import _green_runtime_compliance


@pytest.fixture
def clean(tmp_path):
    """A clean graph with three delivered messages: a send, a reply to it (then read), another send."""
    from nodelang.clean_agent_coordination import BoundAgentSession, GraphAgentCoordinator
    from nodelang.unified_authority import attach_composition_from_scope, composition_root
    authority, _provider, founder, sessions, workshop = _foundation(tmp_path / "clean.sqlite3")
    keys = (Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate())
    (a_bundle, a_caller), (b_bundle, b_caller) = (
        _session(authority, sessions, founder, "Builder", keys[0], "codex"),
        _session(authority, sessions, founder, "Reviewer", keys[1], "reviewer"))
    source = composition_root(authority, "Agent Sessions", caller=founder)
    target = composition_root(authority, "Workshop", caller=founder)
    for bundle in (a_bundle, b_bundle):
        attach_composition_from_scope(authority, source, target, bundle.session_root,
                                      caller=founder, command_id=str(uuid.uuid4()))
    a = GraphAgentCoordinator(authority, sessions, workshop, BoundAgentSession(a_bundle, a_caller))
    b = GraphAgentCoordinator(authority, sessions, workshop, BoundAgentSession(b_bundle, b_caller))
    first = a.send_message(target_session_root=b_bundle.session_root, body="Review revision 7.",
                           operation_id=_command("archive-first"))
    reply = b.send_message(target_session_root=a_bundle.session_root, body="Reviewed: one finding.",
                           operation_id=_command("archive-reply"), reply_to_root=first.root_id)
    b.mark_message_read(first.root_id, command_id=_command("archive-read"))
    third = a.send_message(target_session_root=b_bundle.session_root, body="Fixed; please recheck.\n",
                           operation_id=_command("archive-third"))
    return authority, founder, b_caller, (first, reply, third)


@pytest.fixture
def owner(tmp_path, monkeypatch):
    from nodelang.conversation_content import prepare_empty_content_binding
    from nodelang.conversation_history import ConversationHistoryStore
    original = server_module.QuietThreadingHTTPServer
    monkeypatch.setattr(server_module, "QuietThreadingHTTPServer",
        lambda address, handler: original(address, handler, bind_and_activate=False))
    (tmp_path / "universal").mkdir()
    server = server_module.ApplicationServer(universal_workspace_root=tmp_path / "universal",
        runtime_compliance_runner=_green_runtime_compliance,
        enable_machine_transport=False, enable_machine_projection_prewarm=False)
    try:
        registry, store = server.universal_registry, server.universal_store
        path = tmp_path / "archive-history.sqlite3"
        server.conversation_content._path = path
        adopted = prepare_empty_content_binding(store.snapshot(), registry.deliberation_protocol,
            application_root=registry.application_root, space_root=registry.workshop_root)
        with ConversationHistoryStore(path, instance_id=adopted.binding.instance_id) as history:
            history.ensure_conversation(registry.workshop_root)
            history.initialize_retention()
        store.commit(adopted.expected_revision, create=adopted.create, replace=adopted.replace)
        yield server, path
    finally:
        server.close()


def _rows(path):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        return db.execute("select id, conversation_id, sequence, author, content, category, recipients, "
                          "refs, reply_to, created_at, idempotency_key from messages "
                          "order by conversation_id, sequence").fetchall()


def _state(server, path):
    rows = _rows(path)
    return server.universal_store.revision, len(rows), hashlib.sha256(
        json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()


def _browser(server):
    return server._resolve_browser_session(server.browser_session_token)


def test_the_export_reads_with_the_founder_caller_and_writes_nothing(clean):
    authority, founder, agent_caller, (first, reply, third) = clean
    store = authority.store
    revision, cells = store.revision, len(store.snapshot().cells)
    with pytest.raises(RefusedWithoutEffect, match="founder's bootstrap caller"):
        export_clean_workshop_archive(authority, caller=agent_caller)
    record = export_clean_workshop_archive(authority, caller=founder)
    assert store.revision == revision and len(store.snapshot().cells) == cells   # read-only
    assert validate_clean_archive_record(record) is record
    assert record["digest"] == record_digest(record)
    assert record["source"] == {"graph_id": authority.manifest.graph_id,
        "workshop_root": record["source"]["workshop_root"], "revision": revision,
        "chain_digest": store.revision_chain_digest(revision)}
    rows = record["messages"]
    assert [row["root"] for row in rows] == [first.root_id, reply.root_id, third.root_id]
    assert [row["state"] for row in rows] == ["read", "sent", "sent"]
    assert rows[1]["reply_to_root"] == first.root_id and rows[0]["reply_to_root"] is None
    assert rows[2]["body"] == "Fixed; please recheck.\n"
    with sqlite3.connect(store.database_path) as journal:
        for row in rows:
            assert row["committed_at"] == journal.execute(
                "select committed_at from revisions where revision=?", (row["created_revision"],)).fetchone()[0]


def test_the_import_preserves_every_message_once_with_exactly_one_graph_commit(clean, owner):
    authority, founder, _agent, _messages = clean
    server, path = owner
    record = export_clean_workshop_archive(authority, caller=founder)
    registry, store = server.universal_registry, server.universal_store
    browser = _browser(server)
    snapshot = store.snapshot()
    general_before = read_deliberation_space(snapshot, registry.deliberation_protocol, registry.workshop_root)
    workbench_before = {(m.role_id, m.participant_id) for m in
                        read_relation(snapshot, registry.workshop_workbench_root, budget=100_000)}
    general_rows_before = [row for row in _rows(path) if row[1] == registry.workshop_root]
    revision = store.revision

    done = import_clean_workshop_archive(server, authentication_context=browser.context,
                                         record=record, expected_revision=revision)
    root = done["conversation"]
    assert done["created"] is True and done["added"] == len(record["messages"]) == 3
    # P5 amendment A1: exactly one graph commit, and only the conversation's own cells.
    assert store.revision == revision + 1 == done["graph_revision_after"]
    snapshot = store.snapshot()
    workbench_after = {(m.role_id, m.participant_id) for m in
                       read_relation(snapshot, registry.workshop_workbench_root, budget=100_000)}
    assert workbench_after - workbench_before == {(registry.roles["scope"], root),
                                                  (registry.roles["member"], root)}
    assert read_deliberation_space(snapshot, registry.deliberation_protocol,
                                   registry.workshop_root) == general_before
    archive = read_deliberation_space(snapshot, registry.deliberation_protocol, root)
    assert archive.title == ARCHIVE_TITLE and archive.participant_roots == (browser.subject_root,)
    # The live Workshop's own history is untouched; the archive holds the messages in order 1..3.
    assert [row for row in _rows(path) if row[1] == registry.workshop_root] == general_rows_before
    archived = [row for row in _rows(path) if row[1] == root]
    assert [row[2] for row in archived] == [1, 2, 3]
    ids = {}
    for source, row, reported in zip(record["messages"], archived, done["messages"]):
        (identifier, _conversation, _sequence, author, content, _category, recipients, refs,
         reply_to, created_at, key) = row
        assert reported["id"] == identifier and reported["legacy"] == source["root"]
        assert content == source["body"]                                    # byte-equal text
        assert author == archive_label(source["sender_root"])               # D1 labels
        assert json.loads(recipients) == [archive_label(source["recipient_root"])]
        assert created_at == done["messages"][len(ids)]["created_at"]
        from datetime import datetime, timezone
        assert created_at == datetime.fromtimestamp(source["committed_at"], tz=timezone.utc).isoformat()  # D2
        assert reply_to == (ids[source["reply_to_root"]] if source["reply_to_root"] else None)
        assert json.loads(refs) == ["clean-message:" + source["root"], "clean-state:" + source["state"],
            "clean-category:" + source["category"],
            "clean-source:%s@%d:%s" % (record["source"]["graph_id"], record["source"]["revision"],
                                       record["source"]["chain_digest"]),
            "clean-record:" + record["digest"]]                             # durable source evidence
        assert key == "clean-workshop-message:" + source["root"]
        ids[source["root"]] = identifier

    after = _state(server, path)
    again = import_clean_workshop_archive(server, authentication_context=browser.context,
                                          record=record, expected_revision=store.revision)
    assert again["created"] is False and again["added"] == 0 and again["conversation"] == root
    assert [row["id"] for row in again["messages"]] == [row["id"] for row in done["messages"]]
    assert _state(server, path) == after                                    # rerun: 0 duplicates, 0 commits


def test_the_founder_reads_every_archived_message(clean, owner):
    authority, founder, _agent, _messages = clean
    server, _path = owner
    record = export_clean_workshop_archive(authority, caller=founder)
    browser = _browser(server)
    done = import_clean_workshop_archive(server, authentication_context=browser.context,
        record=record, expected_revision=server.universal_store.revision)
    page = server.conversation_content.page_for_workshop_browser(server.browser_session_token,
        binding=browser, space_root=done["conversation"])
    shown = json.dumps(page, ensure_ascii=False)
    for row in record["messages"]:
        assert json.dumps(row["body"], ensure_ascii=False)[1:-1] in shown


def test_a_tampered_record_or_a_non_founder_imports_nothing(clean, owner):
    authority, founder, _agent, _messages = clean
    server, path = owner
    record = export_clean_workshop_archive(authority, caller=founder)
    before = _state(server, path)
    tampered = json.loads(json.dumps(record))
    tampered["messages"][0]["body"] = "Rewritten history."
    with pytest.raises(InvalidCell, match="digest does not match"):
        import_clean_workshop_archive(server, authentication_context=_browser(server).context,
                                      record=tampered, expected_revision=server.universal_store.revision)
    authority_u = server.universal_registry.authorization
    stranger = authority_u.broker.mint_authenticated_context("app:identity:someone-else",
        tenant_root=authority_u.session.tenant_root, assurance_root=authority_u.session.assurance_root)
    with pytest.raises(RefusedWithoutEffect, match="only the founder"):
        import_clean_workshop_archive(server, authentication_context=stranger, record=record,
                                      expected_revision=server.universal_store.revision)
    assert _state(server, path) == before


def test_the_import_counts_as_activity_now_and_never_backdates_retention(clean, owner):
    """Rev 4 P4 retention: the archive is a normal conversation; its activity is the import time,
    so it is not purge-eligible on arrival even though its messages are weeks old."""
    import time
    authority, founder, _agent, _messages = clean
    server, _path = owner
    record = export_clean_workshop_archive(authority, caller=founder)
    started = time.time()
    done = import_clean_workshop_archive(server, authentication_context=_browser(server).context,
        record=record, expected_revision=server.universal_store.revision)
    registry = server.universal_registry
    from nodelang.conversation_content import read_content_binding
    binding = read_content_binding(server.universal_store.snapshot(), registry.deliberation_protocol,
        application_root=registry.application_root, space_root=done["conversation"])
    status = server.conversation_content._history_for(binding).retention_status(done["conversation"])
    assert status["archived_at"] is None
    assert status["last_activity_at"] is not None and status["last_activity_at"] >= started - 1


def _redigested(record, change):
    """A malformed record that still carries a VALID digest, so the semantic checks are what refuse it."""
    bad = json.loads(json.dumps(record))
    change(bad["messages"])
    bad.pop("digest")
    bad["digest"] = record_digest(bad)
    return bad


def _nul_body(rows):
    rows[0]["body"] = "before\x00after"   # passes the record check; content storage refuses NUL


def _forward(rows):
    rows[0]["reply_to_root"] = rows[1]["root"]


def _self(rows):
    rows[1]["reply_to_root"] = rows[1]["root"]


def _cycle(rows):
    rows[0]["reply_to_root"], rows[1]["reply_to_root"] = rows[1]["root"], rows[0]["root"]


def _nan_time(rows):
    rows[2]["committed_at"] = float("nan")


def _negative_time(rows):
    rows[2]["committed_at"] = -5.0


@pytest.mark.parametrize("change, refusal", [
    (_forward, "earlier message"), (_self, "earlier message"), (_cycle, "earlier message"),
    (_nan_time, "commit time"), (_negative_time, "commit time"), (_nul_body, "cannot be stored")])
def test_a_malformed_record_changes_neither_graph_nor_history(clean, owner, change, refusal):
    authority, founder, _agent, _messages = clean
    server, path = owner
    record = _redigested(export_clean_workshop_archive(authority, caller=founder), change)
    before = _state(server, path)
    with pytest.raises(InvalidCell, match=refusal):
        import_clean_workshop_archive(server, authentication_context=_browser(server).context,
                                      record=record, expected_revision=server.universal_store.revision)
    assert _state(server, path) == before            # no conversation commit, no history row


def test_an_idempotency_clash_rolls_back_every_append_and_commits_nothing(clean, owner):
    authority, founder, _agent, _messages = clean
    server, path = owner
    record = export_clean_workshop_archive(authority, caller=founder)
    browser = _browser(server)
    done = import_clean_workshop_archive(server, authentication_context=browser.context,
                                         record=record, expected_revision=server.universal_store.revision)
    assert done["summary"] == "Imported 3 messages into the Clean Workshop archive."
    again = import_clean_workshop_archive(server, authentication_context=browser.context,
                                          record=record, expected_revision=server.universal_store.revision)
    assert again["summary"] == "Clean Workshop archive is already imported; 0 messages added."
    before = _state(server, path)
    # Same legacy roots, rewritten text, valid digest: the stored keys conflict on the LAST message,
    # after the first two appends ran inside the transaction; all of it rolls back.
    clash = _redigested(record, lambda rows: rows[2].update(body="Rewritten history."))
    with pytest.raises(ValueError, match="idempotency conflict"):
        import_clean_workshop_archive(server, authentication_context=browser.context,
                                      record=clash, expected_revision=server.universal_store.revision)
    assert _state(server, path) == before
