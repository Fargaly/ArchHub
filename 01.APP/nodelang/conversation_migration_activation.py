"""Activate verified ordinary history through its existing application owner.

Graph controls remain the authority. SQL publication receipts are reconciliation
evidence, never credentials or stored graph patches. No service or route starts.
"""
from pathlib import Path
import os
import time

from .cell_authorization import AuthorizationDenied
from .conversation_content import read_content_binding
from .conversation_history import ConversationHistoryStore
from .conversation_migration import (
    LegacyConversationImport, _check_time, _deadline, _reconcile_history,
    _source_matches, _verify_stage_owner, open_legacy_migration_manifest,
)
from .conversation_migration_binding import prepare_legacy_content_binding
from .conversation_migration_publication import (
    _database_path, _RECEIPT_COLUMNS, _require_instance, _row, publish_legacy_conversation,
)
from .universal_cell import InvalidCell


def _remaining(deadline):
    _check_time(deadline)
    return min(120, deadline - time.monotonic())


def _configured_target(service, history):
    if service._path is None or not service._path.is_file():
        raise FileNotFoundError("configured conversation destination is missing")
    with history._lock:
        if not os.path.samefile(_database_path(history), service._path):
            raise InvalidCell("conversation owner destination changed")


def _reserve(history):
    with history._lock:
        if history._db.in_transaction:
            raise InvalidCell("conversation activation requires an idle owned connection")
        previous = history._db.execute("PRAGMA main.locking_mode").fetchone()[0]
        mode = history._db.execute("PRAGMA main.locking_mode=EXCLUSIVE").fetchone()[0]
        if mode != "exclusive":
            raise InvalidCell("conversation activation exclusive ownership unavailable")
        try:
            history._db.execute("BEGIN EXCLUSIVE")
            history._db.execute("SELECT instance_id FROM history_identity").fetchone()
            history._db.execute("COMMIT")
        except BaseException:
            if history._db.in_transaction:
                history._db.execute("ROLLBACK")
            _restore_locking_mode(history, previous)
            raise
        return previous


def _restore_locking_mode(history, previous_mode):
    """NORMAL releases retained locks only after an actual database access.

    https://www.sqlite.org/pragma.html#pragma_locking_mode
    Do not close/reopen a replacement path to simulate transferring this handle.
    """
    if previous_mode != "normal":
        return
    with history._lock:
        if history._db.in_transaction:
            raise InvalidCell("conversation activation left a transaction open")
        if history._db.execute("PRAGMA main.locking_mode=NORMAL").fetchone()[0] != "normal":
            raise InvalidCell("conversation activation could not restore normal locking")
        history._db.execute("SELECT instance_id FROM history_identity").fetchone()


def _read_receipt(history, space_root):
    with history._lock:
        if not history._db.execute("SELECT 1 FROM sqlite_schema WHERE name='migration_publications'").fetchone():
            return None
        row = history._db.execute("SELECT " + ",".join(_RECEIPT_COLUMNS) +
            " FROM migration_publications WHERE conversation_id=?", (space_root,)).fetchone()
        return None if row is None else dict(row)


def _owned_receipt(history, header, ticket, stage_id, *, binding_root=None):
    receipt = _read_receipt(history, header["space_root"])
    if receipt is None:
        return None
    expected = dict(conversation_id=header["space_root"], application_root=header["application_root"],
        instance_id=header["instance_id"], manifest_digest=ticket.manifest_digest, stage_id=stage_id,
        source_authority=header["source_authority"], source_revision=header["source_revision"],
        source_digest=header["source_digest"], imported_count=header["total"])
    if any(receipt[key] != value for key, value in expected.items()) or (
            binding_root is not None and receipt["binding_root"] != binding_root):
        raise InvalidCell("conversation activation publication ownership mismatch")
    return receipt


def _verify_prefix(history, manifest, header, deadline, *, allow_tail):
    with history._lock:
        _require_instance(history, header["instance_id"])
        head = history._head(header["space_root"])
        if head < header["total"] or not allow_tail and head != header["total"]:
            raise InvalidCell("conversation activation imported prefix count mismatch")
        cursor = manifest.execute("SELECT * FROM entries ORDER BY sequence")
        try:
            for expected in cursor:
                _check_time(deadline)
                LegacyConversationImport._verify_record(
                    _row(history, header["space_root"], expected["message_id"]), expected)
        finally:
            cursor.close()
        _reconcile_history(history, deadline)


def _authorize(service, snapshot, context, *, space_root=None):
    from . import cell_authorization as authorization_module
    from .cell_identity import verify_relationship_authority_snapshot
    from .universal_application import _require_application_authorization

    service._require_live_owner(allow_activation_recovery=True)
    registry = service._owner.universal_registry
    authority = registry.authorization
    identity = authority.broker.resolve(context)
    if identity.subject_root != authority.subject_root:
        raise AuthorizationDenied("conversation migration requires its authenticated founder")
    # Resolve current policy time as well as the opaque context's expiry. A
    # cached relationship evaluation time must not extend an expired grant.
    verified = verify_relationship_authority_snapshot(snapshot, authority.identity_protocol,
        authority.relationship_broker, now=authorization_module.time.time())
    for root in dict.fromkeys((registry.application_root, space_root)):
        if root is not None:
            _require_application_authorization(snapshot, registry, "edit", root,
                authentication_context=context, resource_lineage_roots=(registry.application_root,),
                authority_snapshot=verified)


def activate_legacy_migration(service, ticket, staging_path, *, authentication_context,
                             time_budget_seconds=30):
    if authentication_context is None:
        raise AuthorizationDenied("conversation migration requires an explicit authenticated context")
    deadline = _deadline(time_budget_seconds)
    owner = service._owner
    with owner.mutation_lock:
        service._require_live_owner(allow_activation_recovery=True)
        registry, store = owner.universal_registry, owner.universal_store
        with registry.authorization.broker.live_context(authentication_context):
            if service._activation_unresolved:
                store.refresh()
            with store.stable_snapshot() as snapshot:
                _authorize(service, snapshot, authentication_context)
            manifest, header = open_legacy_migration_manifest(ticket, registry.deliberation_protocol,
                time_budget_seconds=_remaining(deadline))
            importer = target = stage = None
            stage_owned = target_owned = False
            reserved = False
            stage_previous_mode = None
            previous_mode = "normal"
            keep_pending = False
            try:
                if header["application_root"] != registry.application_root or header["source_authority"] != store.authority_identity:
                    raise InvalidCell("conversation migration belongs to a different application owner")
                with store.stable_snapshot() as snapshot:
                    _authorize(service, snapshot, authentication_context, space_root=header["space_root"])
                    revision = snapshot.revision
                    if revision == header["source_revision"]:
                        _source_matches(store, header)
                        binding = None
                    else:
                        binding = read_content_binding(snapshot, registry.deliberation_protocol,
                            application_root=registry.application_root, space_root=header["space_root"])
                        if binding.instance_id != header["instance_id"]:
                            raise InvalidCell("conversation activation instance changed")
                staging_path = Path(staging_path).resolve()
                if not staging_path.is_file():
                    raise FileNotFoundError("verified conversation staging is missing")
                if service._path is None or not service._path.is_file():
                    raise FileNotFoundError("configured conversation destination is missing")
                same_path = os.path.samefile(staging_path, service._path)
                held = service._history or service._pending_activation_history
                if held is not None:
                    _configured_target(service, held)
                if binding is None:
                    # A failed uncertain first transfer may retain an otherwise
                    # inactive handle. The refreshed graph has now established
                    # the old state; reopen and fully verify that stage again.
                    if same_path and held is not None and held is service._pending_activation_history and service._history is None:
                        held.close()
                        service._pending_activation_history = None
                        service._pending_activation_lock_mode = None
                        held = None
                    if same_path and held is not None:
                        raise InvalidCell("conversation staging conflicts with the active owner handle")
                    importer = LegacyConversationImport(store, registry.deliberation_protocol, ticket,
                        staging_path, time_budget_seconds=_remaining(deadline))
                    if not importer._verified_complete:
                        raise InvalidCell("conversation migration copy is incomplete")
                    stage = importer._history
                else:
                    if same_path and held is not None:
                        stage = held
                    else:
                        stage = ConversationHistoryStore(staging_path, instance_id=header["instance_id"], create=False)
                        stage_owned = True
                    stage_previous_mode = _reserve(stage)
                target = stage if same_path else held
                if target is None:
                    target = ConversationHistoryStore(service._path, instance_id=header["instance_id"], create=False)
                    target_owned = True
                previous_mode = stage_previous_mode if target is stage and stage_previous_mode is not None else _reserve(target)
                if target is service._pending_activation_history:
                    if service._pending_activation_lock_mode not in ("normal", "exclusive"):
                        raise InvalidCell("conversation activation recovery lacks its intended lock mode")
                    previous_mode = service._pending_activation_lock_mode
                # A first stage becomes the ordinary owner's normal connection.
                if same_path and importer is not None or same_path and stage_owned:
                    previous_mode = "normal"
                reserved = True
                _configured_target(service, target)
                with stage._lock:
                    _verify_stage_owner(stage, staging_path, ticket.manifest_digest)
                    stage_id = stage._db.execute("SELECT stage_id FROM migration_staging WHERE singleton=1").fetchone()[0]
                with store.stable_snapshot(expected_revision=revision) as snapshot:
                    _authorize(service, snapshot, authentication_context, space_root=header["space_root"])
                    receipt = _owned_receipt(target, header, ticket, stage_id,
                        binding_root=binding.root_id if binding is not None else None)
                    if binding is None:
                        prepared = prepare_legacy_content_binding(importer,
                            binding_root=receipt["binding_root"] if receipt is not None else None,
                            time_budget_seconds=_remaining(deadline))
                        publish_legacy_conversation(importer, prepared, target,
                            before_commit=lambda: _authorize(service, snapshot, authentication_context,
                                space_root=header["space_root"]), time_budget_seconds=_remaining(deadline))
                        binding = prepared.patch.binding
                        already_active = False
                    else:
                        if receipt is None:
                            raise InvalidCell("conversation binding lacks its owned migration publication")
                        _verify_prefix(target, manifest, header, deadline, allow_tail=True)
                        already_active = True
                recovered_commit = False
                if not already_active:
                    guard_passed = False

                    def before_graph_commit():
                        nonlocal guard_passed
                        _check_time(deadline)
                        _authorize(service, snapshot, authentication_context, space_root=header["space_root"])
                        _configured_target(service, target)
                        with target._lock:
                            if target._db.execute("PRAGMA main.locking_mode").fetchone()[0] != "exclusive":
                                raise InvalidCell("conversation activation lost destination ownership")
                            if _owned_receipt(target, header, ticket, stage_id, binding_root=binding.root_id) is None:
                                raise InvalidCell("conversation activation publication is missing")
                            _verify_prefix(target, manifest, header, deadline, allow_tail=False)
                        _authorize(service, snapshot, authentication_context, space_root=header["space_root"])
                        guard_passed = True

                    try:
                        store.commit(prepared.patch.expected_revision, create=prepared.patch.create,
                            replace=prepared.patch.replace, precommit_guard=before_graph_commit)
                    except Exception:
                        if not guard_passed:
                            raise  # Definite refusal before journal publication.
                        try:
                            store.refresh()
                            with store.stable_snapshot() as current:
                                actual = read_content_binding(current, registry.deliberation_protocol,
                                    application_root=registry.application_root, space_root=header["space_root"])
                                if actual != binding:
                                    raise InvalidCell("conversation activation durable binding differs")
                                _verify_prefix(target, manifest, header, deadline, allow_tail=True)
                            recovered_commit = True
                        except Exception:
                            keep_pending = True
                            raise
                try:
                    # Verification can outlive a grant. Recheck both the actual
                    # current binding and fresh permission immediately before
                    # clearing recovery state or exposing the adopted handle.
                    with store.stable_snapshot() as current:
                        actual = read_content_binding(current, registry.deliberation_protocol,
                            application_root=registry.application_root, space_root=header["space_root"])
                        if actual != binding:
                            raise InvalidCell("conversation activation binding changed before adoption")
                        _authorize(service, current, authentication_context, space_root=header["space_root"])
                        service._adopt_activation_history(target)
                        _restore_locking_mode(target, previous_mode)
                        reserved = False
                        activated_revision = current.revision
                except Exception:
                    keep_pending = True
                    raise
                return dict(state="active", conversation_id=header["space_root"], binding_root=binding.root_id,
                    imported_count=header["total"], graph_revision=activated_revision,
                    already_active=already_active, recovered_commit=recovered_commit)
            finally:
                if keep_pending and target is not None:
                    service._pending_activation_history = target
                    service._pending_activation_lock_mode = previous_mode
                    service._activation_unresolved = True
                try:
                    if reserved and not keep_pending and target is not None:
                        _restore_locking_mode(target, previous_mode)
                except Exception:
                    if target is not None:
                        service._pending_activation_history = target
                        service._pending_activation_lock_mode = previous_mode
                        service._activation_unresolved = True
                    raise
                finally:
                    kept = target is not None and target in (service._history, service._pending_activation_history)
                    if importer is not None and importer._history is target and kept:
                        importer._history = None
                    try:
                        if importer is not None:
                            importer.close()
                        elif stage_owned and stage is not target:
                            stage.close()
                    finally:
                        try:
                            if not kept and target is not None and (target_owned or stage_owned):
                                target.close()
                        finally:
                            manifest.close()
