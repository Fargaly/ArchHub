"""The clean Workshop's delivered messages, preserved as one archive conversation (plan B, S4).

Two owners, each touching only its own store (plan B rev 4, R1 = (A)):

* `export_clean_workshop_archive` runs inside the clean graph's owner with the founder's
  real bootstrap caller. It is read-only on the clean graph and returns one record: the
  graph id, the Workshop root, the source revision and its chain digest, and every
  delivered message with its original commit time. The record carries a digest of its
  own canonical content. TEMPORARY: it retires with the clean service in S5.
* `import_clean_workshop_archive` runs in the universal application, the content owner.
  Founder only. It re-verifies the record's digest, creates (or finds) the separate
  "Clean Workshop archive" conversation through the existing
  `create_workshop_conversation` (its one authenticated graph commit is plan B P5
  amendment A1), then appends every message in one history transaction.

What each preserved message keeps (P4): the byte-equal text, the sender and recipient
as archive labels (D1: "archived clean participant <root>", text only, never a Cell,
session or actor), the original commit time as created_at (D2), the order by created
revision, the reply relation mapped to the new id, and the legacy root, historical
state and original category as provenance refs, together with the clean source revision and
its chain digest and the record's digest (durable on every message). A reply must name an
earlier message, so replies map in one forward pass; every stored field is preflighted before
any graph or history write. The legacy root resolves to the new id
through the idempotency key "clean-workshop-message:<root>". A rerun adds nothing.
No message Cell, mapping Cell or migration receipt is written.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .cell_authorization import AuthorizationDenied, RefusedWithoutEffect
from .universal_cell import InvalidCell

RECORD_KIND = "archhub.clean-workshop-archive"
RECORD_VERSION = 1
ARCHIVE_TITLE = "Clean Workshop archive"
ARCHIVE_KEY = "clean-workshop-archive"
MESSAGE_KEY_PREFIX = "clean-workshop-message:"
LABEL_PREFIX = "archived clean participant "
MAX_MESSAGES = 100
_DELIVERED = ("sent", "read", "acted")
_MESSAGE_FIELDS = ("root", "sender_root", "recipient_root", "reply_to_root", "body", "category",
                   "state", "created_revision", "committed_at")
_SOURCE_FIELDS = ("graph_id", "workshop_root", "revision", "chain_digest")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def record_digest(record):
    """sha256 of the record's canonical content, its own digest field excluded."""
    return hashlib.sha256(_canonical({key: value for key, value in record.items()
                                      if key != "digest"})).hexdigest()


def archive_label(root):
    return LABEL_PREFIX + root


def _created_at(seconds):
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def _short_text(value, label):
    if type(value) is not str or not value or "\x00" in value or len(value.encode("utf-8")) > 480:
        raise InvalidCell("clean archive %s is invalid" % label)
    return value


def validate_clean_archive_record(record):
    """The exact record shape, its digest, and messages in commit order; anything else refuses."""
    if (type(record) is not dict or set(record) != {"kind", "version", "source", "messages", "digest"}
            or record["kind"] != RECORD_KIND or record["version"] != RECORD_VERSION):
        raise InvalidCell("clean archive record shape is invalid")
    if type(record["digest"]) is not str or record["digest"] != record_digest(record):
        raise InvalidCell("clean archive record digest does not match its content")
    source = record["source"]
    if type(source) is not dict or set(source) != set(_SOURCE_FIELDS):
        raise InvalidCell("clean archive source is invalid")
    for name in ("graph_id", "workshop_root", "chain_digest"):
        _short_text(source[name], "source " + name)
    if type(source["revision"]) is not int or source["revision"] < 1:
        raise InvalidCell("clean archive source revision is invalid")
    messages = record["messages"]
    if type(messages) is not list or not 1 <= len(messages) <= MAX_MESSAGES:
        raise InvalidCell("clean archive must hold 1 to %d messages" % MAX_MESSAGES)
    roots = set()
    for row in messages:
        if type(row) is not dict or set(row) != set(_MESSAGE_FIELDS):
            raise InvalidCell("clean archive message fields are invalid")
        for name in ("root", "sender_root", "recipient_root", "category"):
            _short_text(row[name], "message " + name)
        if row["reply_to_root"] is not None:
            _short_text(row["reply_to_root"], "message reply_to_root")
        if type(row["body"]) is not str or not row["body"] or len(row["body"].encode("utf-8")) > 65536:
            raise InvalidCell("clean archive message body is invalid")
        if row["state"] not in _DELIVERED:
            raise InvalidCell("clean archive holds only delivered messages")
        if (type(row["created_revision"]) is not int
                or not 1 <= row["created_revision"] <= source["revision"]):
            raise InvalidCell("clean archive message revision is outside its source")
        if type(row["committed_at"]) not in (int, float) or not 0 < row["committed_at"] < 32503680000:
            raise InvalidCell("clean archive message commit time is invalid")
        if row["root"] in roots:
            raise InvalidCell("clean archive message is duplicated")
        roots.add(row["root"])
    order = [(row["created_revision"], row["root"]) for row in messages]
    if order != sorted(order):
        raise InvalidCell("clean archive messages are not in commit order")
    # A reply names a message that came EARLIER in commit order: the importer maps replies in
    # one forward pass, so a forward, self or cyclic reference is refused here, before any write.
    earlier = set()
    for row in messages:
        if row["reply_to_root"] is not None and row["reply_to_root"] not in earlier:
            raise InvalidCell("clean archive reply target is not an earlier message of the archive")
        earlier.add(row["root"])
    return record


def export_clean_workshop_archive(authority, *, caller):
    """Read the clean Workshop's delivered messages with the founder's real caller; write nothing.

    Runs inside the clean graph's owner (the caller is that owner's founder bootstrap
    caller). TEMPORARY: retires with the clean service in S5.
    """
    import sqlite3
    from pathlib import Path
    from .unified_authority import composition_root
    from .workshop_conversation import read_workshop_conversation

    # Founder only: the owner's bootstrap caller (WindowsDpapiCallerKeyStore.bind_bootstrap),
    # never an agent session. Every read below is still signed and checked by the authority.
    if (getattr(caller, "actor_root", None), getattr(caller, "session_root", None)) != (
            authority.manifest.principal_root, authority.manifest.bootstrap_session_root):
        raise RefusedWithoutEffect("only the founder's bootstrap caller exports the clean Workshop")
    store = authority.store
    revision = store.revision
    workshop = composition_root(authority, "Workshop", caller=caller)
    page = read_workshop_conversation(authority, workshop, caller=caller, limit=MAX_MESSAGES)
    if page.get("has_older"):
        raise InvalidCell("the clean Workshop holds more messages than one archive record")
    if page["revision"] != revision or store.revision != revision:
        raise InvalidCell("the clean Workshop changed during the export; run it again")
    if not page["messages"]:
        raise InvalidCell("the clean Workshop has no delivered messages to preserve")
    created = sorted({row["created_revision"] for row in page["messages"]})
    # The store keeps each revision's commit time in its own journal; read it read-only.
    database = Path(store.database_path)
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as journal:
        times = dict(journal.execute(
            "SELECT revision, committed_at FROM revisions WHERE revision IN (%s)"
            % ",".join("?" * len(created)), created).fetchall())
    if set(times) != set(created):
        raise InvalidCell("a message revision has no commit time")
    messages = [{"root": row["root"], "sender_root": row["sender_root"],
                 "recipient_root": row["recipient_root"], "reply_to_root": row["reply_to_root"],
                 "body": row["body"], "category": row["category"], "state": row["state"],
                 "created_revision": row["created_revision"],
                 "committed_at": float(times[row["created_revision"]])}
                for row in sorted(page["messages"], key=lambda row: (row["created_revision"], row["root"]))]
    record = {"kind": RECORD_KIND, "version": RECORD_VERSION,
              "source": {"graph_id": authority.manifest.graph_id, "workshop_root": workshop,
                         "revision": revision, "chain_digest": store.revision_chain_digest(revision)},
              "messages": messages}
    record["digest"] = record_digest(record)
    if store.revision != revision:
        raise InvalidCell("the clean Workshop changed during the export; run it again")
    return validate_clean_archive_record(record)


def import_clean_workshop_archive(owner, *, authentication_context, record, expected_revision):
    """Preserve one verified clean archive record as the "Clean Workshop archive" conversation.

    Founder only. At most one graph commit (the conversation's creation, plan B P5 A1);
    the messages are content in one history transaction. A rerun adds nothing.
    """
    from .conversation_content import read_content_binding
    from .conversation_history import validate_message_fields
    from .workshop_conversation_catalog import create_workshop_conversation

    record = validate_clean_archive_record(record)
    registry, store = owner.universal_registry, owner.universal_store
    authority = registry.authorization
    founder = authority.subject_root
    category = registry.workshop_category_roots["note"]
    source = record["source"]
    # Durable provenance on every message: the exact clean source revision and its chain digest,
    # and the digest of the record that carried it.
    provenance = ("clean-source:%s@%d:%s" % (source["graph_id"], source["revision"], source["chain_digest"]),
                  "clean-record:" + record["digest"])

    def fields(row, conversation, reply_to):
        return validate_message_fields(conversation, author=archive_label(row["sender_root"]),
            content=row["body"], category=category, recipients=(archive_label(row["recipient_root"]),),
            refs=("clean-message:" + row["root"], "clean-state:" + row["state"],
                  "clean-category:" + row["category"], *provenance),
            evidence=(), reply_to=reply_to, idempotency_key=MESSAGE_KEY_PREFIX + row["root"],
            message_id=None, created_at=_created_at(row["committed_at"]))

    # Preflight every message's stored fields before any graph or history write. The ids used
    # here have the real ids' shapes; the real ones exist only after creation and append.
    shaped_root = "app:workshop:conversation:" + "0" * 64 + ":" + "0" * 64
    for row in record["messages"]:
        try:
            fields(row, shaped_root, "0" * 32 if row["reply_to_root"] else None)
        except (ValueError, OverflowError, OSError) as invalid:
            raise InvalidCell("clean archive message %s cannot be stored: %s" % (row["root"], invalid)) from invalid
    with owner.mutation_lock:
        try:
            identity = authority.broker.resolve(authentication_context)
        except AuthorizationDenied as denied:
            raise RefusedWithoutEffect("the archive import needs the founder's live session") from denied
        if identity.subject_root != founder:
            raise RefusedWithoutEffect("only the founder preserves the clean Workshop; nothing was written")
        revision_before = store.revision
        created = create_workshop_conversation(owner, authentication_context=authentication_context,
            expected_revision=expected_revision, title=ARCHIVE_TITLE, participant_roots=[founder],
            idempotency_key=ARCHIVE_KEY)
        root = created["root"]
        snapshot = store.snapshot()
        binding = read_content_binding(snapshot, registry.deliberation_protocol,
            application_root=registry.application_root, space_root=root)
        history = owner.conversation_content._history_for(binding)
        mapping, report = {}, []
        # One transaction: an idempotency conflict with a stored message rolls every append back.
        with history._transaction(write=True):
            head_before = history._head(root)
            for row in record["messages"]:
                validated = fields(row, root, mapping[row["reply_to_root"]] if row["reply_to_root"] else None)
                message = history._append_in_transaction(validated)
                mapping[row["root"]] = message["id"]
                report.append({"legacy": row["root"], "id": message["id"], "sequence": message["sequence"],
                               "body_sha256": hashlib.sha256(message["content"].encode("utf-8")).hexdigest(),
                               "author": message["author"], "recipients": list(message["recipients"]),
                               "created_at": message["created_at"], "reply_to": message["reply_to"],
                               "refs": list(message["refs"])})
            head_after = history._head(root)
            if head_after > head_before and history._retention_active():
                history._record_activity(root)
    added = head_after - head_before
    summary = ("Clean Workshop archive is already imported; 0 messages added." if not added else
               "Imported %d message%s into the Clean Workshop archive." % (added, "" if added == 1 else "s"))
    return {"ok": True, "summary": summary, "conversation": root, "created": created["created"],
            "source": dict(record["source"]), "record_digest": record["digest"],
            "graph_revision_before": revision_before, "graph_revision_after": store.revision,
            "added": added, "messages": report}


__all__ = ["ARCHIVE_KEY", "ARCHIVE_TITLE", "archive_label", "export_clean_workshop_archive",
           "import_clean_workshop_archive", "record_digest", "validate_clean_archive_record"]
