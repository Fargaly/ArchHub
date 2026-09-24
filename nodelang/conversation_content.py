"""Graph-admitted binding for ordinary durable conversation records.

The existing conversation root remains the sole policy/participant authority.
Preparing a fresh binding is an in-process composition primitive, not an agent
endpoint or migration approval. The governed adopter must prepare durable data
first, then activate its graph patch atomically. Legacy adoption is separate.
"""
import contextlib
from dataclasses import dataclass
from pathlib import Path
import json
import os
import sqlite3
import stat
import uuid

from .cell_deliberation import (
    MAX_PARTICIPANTS, MAX_CATEGORIES, MAX_REQUIREMENTS,
    read_deliberation_space, _one, _optional, _text, _closed_roles,
    _terminal,
)
from .cell_protocols import compose_relation_cells, prepare_append_relation_members, read_relation
from .universal_cell import InvalidCell


# One chain cell per control incidence: participants, categories, requirements,
# up to 64 scopes, and the bounded singleton fields. No message-count allowance.
CONTROL_BUDGET = MAX_PARTICIPANTS + MAX_CATEGORIES + MAX_REQUIREMENTS + 64 + 32
APPLICATION_BINDING_BUDGET = 100_000
CONTENT_VERSION = "1"
FRESH_CONTENT_BOOTSTRAP_ROOT = "app:conversation-content-bootstrap"


def _content_artifacts(path):
    return tuple(Path(str(path) + suffix) for suffix in ("", "-wal", "-journal", "-shm"))


def preflight_fresh_content_path(graph_path, content_path):
    """Refuse existing content custody before creating a new graph authority."""
    graph, content = Path(graph_path).resolve(), Path(content_path).resolve()
    if content in _content_artifacts(graph) or graph in _content_artifacts(content):
        raise InvalidCell("fresh conversation recovery required: graph and content paths overlap")
    if any(os.path.lexists(path) for path in _content_artifacts(content)):
        raise InvalidCell("fresh conversation recovery required: content file or SQLite sidecar already exists")


def _physical_file_id(path):
    physical = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(physical.st_mode) or not physical.st_ino or physical.st_nlink != 1:
        raise InvalidCell("fresh conversation recovery required: uncertain physical file custody")
    return [physical.st_dev, physical.st_ino]


def _bootstrap_cell(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 16_384:
        raise InvalidCell("fresh conversation bootstrap custody exceeds its bound")
    return _terminal(FRESH_CONTENT_BOOTSTRAP_ROOT, encoded)


def read_fresh_content_bootstrap(snapshot):
    """Read bounded graph metadata, never infer freshness from an empty history."""
    if FRESH_CONTENT_BOOTSTRAP_ROOT not in snapshot.cells:
        return None
    try:
        raw = _text(snapshot, FRESH_CONTENT_BOOTSTRAP_ROOT, "fresh content bootstrap")
        if len(raw.encode("utf-8")) > 16_384:
            raise ValueError("oversized bootstrap")
        value = json.loads(raw)
        common = {"version", "state", "bootstrap_id"}
        fields = ({"graph_path", "content_path", "authority", "graph_file_id"}
            if value.get("state") == "pending" else {"binding_root", "instance_id"})
        if (set(value) != common | fields or type(value["version"]) is not int
                or value["version"] != 1 or value["state"] not in ("pending", "bound")):
            raise ValueError("invalid bootstrap fields")
        if uuid.UUID(value["bootstrap_id"]).hex != value["bootstrap_id"]:
            raise ValueError("invalid bootstrap identity")
        if value["state"] == "pending":
            if any(type(value[key]) is not str or not value[key] or len(value[key]) > 4096
                    for key in ("graph_path", "content_path", "authority")):
                raise ValueError("invalid bootstrap custody")
            physical = value["graph_file_id"]
            if type(physical) is not list or len(physical) != 2 or any(type(n) is not int or n < 0 for n in physical) or not physical[1]:
                raise ValueError("invalid bootstrap file identity")
        elif (uuid.UUID(value["instance_id"]).hex != value["instance_id"]
                or value["binding_root"] != "conversation-content:" + uuid.UUID(value["binding_root"].removeprefix("conversation-content:")).hex):
            raise ValueError("invalid bootstrap binding")
        return value
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise InvalidCell("fresh conversation recovery required: invalid graph bootstrap intent") from exc


def record_fresh_content_bootstrap(store, content_path):
    """Reserve first-boot intent in the new graph before building its application."""
    from .universal_cell import NULL_CELL_ID
    snapshot = store.snapshot()
    if store.database_path is None or snapshot.revision != 0 or set(snapshot.cells) != {NULL_CELL_ID}:
        raise InvalidCell("fresh conversation recovery required: graph is not a new empty authority")
    preflight_fresh_content_path(store.database_path, content_path)
    value = dict(version=1, state="pending", bootstrap_id=uuid.uuid4().hex,
        graph_path=str(Path(store.database_path).resolve()), content_path=str(Path(content_path).resolve()),
        authority=store.authority_identity, graph_file_id=_physical_file_id(store.database_path))
    store.commit(snapshot.revision, create=(_bootstrap_cell(value),))


def _require_empty_bootstrap(snapshot, registry):
    space = read_deliberation_space(snapshot, registry.deliberation_protocol,
        registry.workshop_root, budget=CONTROL_BUDGET)
    members = read_relation(snapshot, registry.application_root, budget=APPLICATION_BINDING_BUDGET)
    instance = _optional(members, registry.deliberation_protocol.role("scope-content-instance"), "application content instance")
    if space.content_store_root is not None or space.entry_roots or instance is not None:
        raise InvalidCell("fresh conversation recovery required: pending graph is not empty and unbound")


def fresh_content_bootstrap_pending(store, registry, content_path):
    snapshot = store.snapshot()
    value = read_fresh_content_bootstrap(snapshot)
    if value is None:
        return False  # Unmarked historical instances retain governed legacy migration.
    if value["state"] == "bound":
        binding = read_content_binding(snapshot, registry.deliberation_protocol,
            application_root=registry.application_root, space_root=registry.workshop_root)
        if (binding.root_id, binding.instance_id) != (value["binding_root"], value["instance_id"]):
            raise InvalidCell("fresh conversation recovery required: settled binding changed")
        return False
    require_fresh_bootstrap_custody(store, value, content_path)
    _require_empty_bootstrap(snapshot, registry)
    return True


def require_fresh_bootstrap_custody(store, value, content_path):
    if (store.database_path is None or content_path is None
            or value["graph_path"] != str(Path(store.database_path).resolve())
            or value["content_path"] != str(Path(content_path).resolve())
            or value["authority"] != store.authority_identity
            or value["graph_file_id"] != _physical_file_id(store.database_path)):
        raise InvalidCell("fresh conversation recovery required: bootstrap path or graph custody changed")
    preflight_fresh_content_path(store.database_path, content_path)


class ConversationContentUnavailable(InvalidCell):
    """An admitted ordinary-content read failed or exceeded its bounded output."""


@dataclass(frozen=True, slots=True)
class ConversationContentBinding:
    root_id: str
    application_root: str
    space_root: str
    instance_root: str
    instance_id: str
    version: str


@dataclass(frozen=True, slots=True)
class PreparedContentBinding:
    expected_revision: int
    binding: ConversationContentBinding
    create: tuple
    replace: tuple


@dataclass(frozen=True, slots=True)
class ConversationMessageProjection:
    """An ordinary content record; its message identity is not a Cell root."""
    message_id: str
    space_root: str
    graph_revision: int
    sequence: int
    actor_root: str
    category_root: str
    content: str
    created_at: str
    idempotency_key: str
    recipient_roots: tuple[str, ...]
    reference_roots: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    reply_to_root: str | None

    @classmethod
    def from_result(cls, result):
        message = result["message"]
        return cls(message["id"], message["conversation_id"], result["graph_revision"],
            message["sequence"], message["author"], message["category"], message["content"],
            message["created_at"], message["idempotency_key"], tuple(message["recipients"]),
            tuple(message["refs"]), tuple(message["evidence"]), message["reply_to"])


def workshop_message_identity(entry):
    """Keep the existing send-ack field while exposing ordinary record identity.

    The legacy transport field `root` is a message identifier in this response,
    never proof of a Cell or authority to inspect/execute one.
    """
    if isinstance(entry, ConversationMessageProjection):
        return {"root": entry.message_id, "message_id": entry.message_id,
            "storage": "conversation-content"}
    return {"root": entry.root_id}


def _instance_id(snapshot, root):
    value = _text(snapshot, root, "conversation instance identity")
    try:
        if uuid.UUID(value).hex != value:
            raise ValueError("noncanonical UUID")
    except ValueError as exc:
        raise InvalidCell("conversation instance identity is invalid") from exc
    return value


def read_content_space(snapshot, protocol, space_root):
    """Read current graph controls with a bound independent of transcript size."""
    space = read_deliberation_space(snapshot, protocol, space_root, budget=CONTROL_BUDGET)
    if space.content_store_root is None:
        raise InvalidCell("conversation content migration or explicit fresh adoption is required")
    # read_deliberation_space already refuses simultaneous content + legacy entries.
    return space


def read_content_binding(snapshot, protocol, *, application_root, space_root):
    space = read_content_space(snapshot, protocol, space_root)
    members = read_relation(snapshot, space.content_store_root, budget=8)
    _closed_roles(members, tuple(protocol.role(name) for name in (
        "content-instance", "content-scope", "content-space", "content-version")),
        "conversation content binding")
    scope = _one(members, protocol.role("content-scope"), "content scope")
    conversation = _one(members, protocol.role("content-space"), "content conversation")
    if scope != application_root or conversation != space_root:
        raise InvalidCell("conversation content scope or conversation changed")
    instance_root = _one(members, protocol.role("content-instance"), "content instance")
    application_members = read_relation(snapshot, application_root, budget=APPLICATION_BINDING_BUDGET)
    admitted = _one(application_members, protocol.role("scope-content-instance"), "application content instance")
    if instance_root != admitted:
        raise InvalidCell("conversation content instance differs from its application scope")
    version = _text(snapshot, _one(members, protocol.role("content-version"), "content version"), "content version")
    if version != CONTENT_VERSION:
        raise InvalidCell("conversation content version is unsupported")
    return ConversationContentBinding(space.content_store_root, application_root,
        space_root, instance_root, _instance_id(snapshot, instance_root), version)


def prepare_empty_content_binding(snapshot, protocol, *, application_root, space_root, binding_root=None):
    """Prepare a fresh empty conversation; never adopt existing message history.

    All conversations in the application reference its one instance terminal.
    A restore preserves that identity; creating an independent clone requires a
    separate governed re-identification, not a path change or automatic fallback.
    No graph or database is modified here. A prepared patch is not activation.
    """
    if application_root == space_root:
        raise InvalidCell("application scope must be distinct from its conversation")
    space = read_deliberation_space(snapshot, protocol, space_root, budget=CONTROL_BUDGET)
    if space.content_store_root is not None:
        raise InvalidCell("conversation content binding already exists; read it without replacement")
    if space.entry_roots:
        raise InvalidCell("legacy conversation requires verified migration before content adoption")
    application_members = read_relation(snapshot, application_root, budget=APPLICATION_BINDING_BUDGET)
    instance_root = _optional(application_members, protocol.role("scope-content-instance"), "application content instance")
    creates, replaces = [], []
    if instance_root is None:
        instance_id = uuid.uuid4().hex
        instance_root = "conversation-instance:" + instance_id
        creates.append(_terminal(instance_root, instance_id))
        instance_patch = prepare_append_relation_members(snapshot, application_root,
            ((protocol.role("scope-content-instance"), instance_root),),
            budget=APPLICATION_BINDING_BUDGET)
        creates.extend(instance_patch.create)
        replaces.extend(instance_patch.replace)
    else:
        instance_id = _instance_id(snapshot, instance_root)
    if binding_root is None:
        binding_root = "conversation-content:" + uuid.uuid4().hex
    elif (type(binding_root) is not str or not binding_root.startswith("conversation-content:")
            or len(binding_root) != len("conversation-content:") + 32):
        raise InvalidCell("conversation content binding identity is invalid")
    try:
        if uuid.UUID(binding_root.removeprefix("conversation-content:")).hex != binding_root.removeprefix("conversation-content:"):
            raise ValueError("noncanonical UUID")
    except ValueError as exc:
        raise InvalidCell("conversation content binding identity is invalid") from exc
    if binding_root in snapshot.cells or binding_root + ":version" in snapshot.cells:
        raise InvalidCell("conversation content binding identity already exists")
    version_root = binding_root + ":version"
    creates.append(_terminal(version_root, CONTENT_VERSION))
    creates.extend(compose_relation_cells((
        (protocol.role("content-instance"), instance_root),
        (protocol.role("content-scope"), application_root),
        (protocol.role("content-space"), space_root),
        (protocol.role("content-version"), version_root),
    ), relation_id=binding_root).cells)
    space_patch = prepare_append_relation_members(snapshot, space_root,
        ((protocol.role("space-content-store"), binding_root),), budget=CONTROL_BUDGET)
    creates.extend(space_patch.create)
    replaces.extend(space_patch.replace)
    return PreparedContentBinding(snapshot.revision, ConversationContentBinding(binding_root,
        application_root, space_root, instance_root, instance_id, CONTENT_VERSION),
        tuple(creates), tuple(replaces))


class ApplicationConversationContent:
    """Lazy content access owned and closed by the existing ApplicationServer.

    The server constructor selects a physical path. Requests supply neither that
    path nor an instance ID, audience identity or read-all privilege. This class
    never starts a worker. Requests cannot adopt a graph; the explicit internal
    migration operation admits and verifies its staged content before adoption.
    """

    def __init__(self, owner, path):
        self._owner = owner
        self._path = Path(path).resolve() if path is not None else None
        self._history = None
        self._closed = False
        self._pending_activation_history = None
        self._pending_activation_lock_mode = None
        self._activation_unresolved = False
        self._pending_backup_lock_mode = None

    def close(self):
        with self._owner.mutation_lock:
            self._closed = True
            current, pending = self._history, self._pending_activation_history
            self._history = self._pending_activation_history = None
            self._pending_activation_lock_mode = None
            self._pending_backup_lock_mode = None
            try:
                if current is not None:
                    current.close()
            finally:
                if pending is not None and pending is not current:
                    pending.close()

    def belongs_to(self, store, registry):
        return self._owner.universal_store is store and self._owner.universal_registry is registry

    def initialize_fresh_workshop(self):
        """Finish this graph's recorded, still-empty first-boot initialization.

        Existing applications, legacy entries, unknown files and missing adopted
        history require their existing recovery/migration path, never this hook.
        """
        from .conversation_history import ConversationHistoryStore
        from .conversation_migration_activation import _reserve, _restore_locking_mode
        from .universal_application import _require_application_authorization
        owner = self._owner
        with owner.mutation_lock:
            self._require_live_owner()
            if getattr(owner, "_fresh_content_bootstrap", False) is not True:
                raise InvalidCell("fresh conversation initialization requires a newly created application")
            if self._path is None or self._history is not None:
                raise InvalidCell("fresh conversation initialization requires an unused content path")
            registry, store = owner.universal_registry, owner.universal_store
            if not fresh_content_bootstrap_pending(store, registry, self._path):
                raise InvalidCell("fresh conversation initialization requires a pending graph intent")
            authority = registry.authorization
            context = authority.session.context()
            history = None
            reservation = None
            intent = read_fresh_content_bootstrap(store.snapshot())
            try:
                with authority.broker.live_context(context):
                    snapshot = store.snapshot()
                    _require_empty_bootstrap(snapshot, registry)
                    for root in (registry.application_root, registry.workshop_root):
                        _require_application_authorization(snapshot, registry, "edit", root,
                            authentication_context=context,
                            resource_lineage_roots=(registry.application_root,))
                    prepared = prepare_empty_content_binding(snapshot, registry.deliberation_protocol,
                        application_root=registry.application_root, space_root=registry.workshop_root)
                    # Reserve the owner-selected path exclusively. A preexisting
                    # database is never opened as a candidate for fresh adoption.
                    preflight_fresh_content_path(store.database_path, self._path)
                    with self._path.open("xb") as reserved:
                        identity = os.fstat(reserved.fileno())
                        reservation = [identity.st_dev, identity.st_ino]
                        if reservation != _physical_file_id(self._path):
                            raise InvalidCell("fresh conversation recovery required: reservation custody changed")
                    history = ConversationHistoryStore(self._path, instance_id=prepared.binding.instance_id)
                    lock_mode = _reserve(history)
                    history.ensure_conversation(registry.workshop_root)
                    history.initialize_retention()
                    self._require_live_owner()
                    if reservation != _physical_file_id(self._path):
                        raise InvalidCell("fresh conversation recovery required: reserved content file changed")
                    settled = dict(version=1, state="bound", bootstrap_id=intent["bootstrap_id"],
                        binding_root=prepared.binding.root_id, instance_id=prepared.binding.instance_id)
                    authority.broker.commit_authenticated(context, store, prepared.expected_revision,
                        create=prepared.create, replace=prepared.replace + (_bootstrap_cell(settled),))
                    _restore_locking_mode(history, lock_mode)
                    self._adopt_activation_history(history)
                    history = None
            except BaseException:
                if reservation is not None:
                    # A raised commit can have published. Refresh the durable
                    # authority before considering removal of our own file.
                    # Unknown outcomes or custody retain every byte for recovery.
                    try:
                        store.refresh()
                        recovered = store.snapshot()
                        if read_fresh_content_bootstrap(recovered) != intent:
                            raise InvalidCell("binding outcome is no longer the pending intent")
                        _require_empty_bootstrap(recovered, registry)
                        if history is not None:
                            history.close()
                            history = None
                        if reservation != _physical_file_id(self._path):
                            raise InvalidCell("reserved file custody changed")
                        if any(os.path.lexists(path) for path in _content_artifacts(self._path)[1:]):
                            raise InvalidCell("reserved content has unresolved SQLite sidecars")
                        self._path.unlink()
                    except BaseException as recovery_error:
                        self._activation_unresolved = True
                        raise InvalidCell("fresh conversation recovery required: reserved content retained; "
                            "binding outcome or physical custody could not be proven absent") from recovery_error
                raise
            finally:
                owner._fresh_content_bootstrap = False
                if history is not None:
                    history.close()

    def _require_live_owner(self, *, allow_activation_recovery=False):
        from .cell_authorization import AuthorizationDenied
        if self._closed:
            raise InvalidCell("conversation content owner is closed")
        if self._owner.runtime_handoff_exit_requested:
            raise AuthorizationDenied("conversation runtime generation was released")
        if self._owner.universal_checkpoint_guard is not None:
            self._owner.universal_checkpoint_guard.require_healthy()
        if self._activation_unresolved and not allow_activation_recovery:
            raise InvalidCell("conversation migration outcome requires an authorized retry")

    def _adopt_activation_history(self, history):
        """Transfer one verified handle under the existing owner mutation lock."""
        if self._history is not None and self._history is not history:
            raise InvalidCell("conversation owner already holds a different history handle")
        self._history = history
        self._pending_activation_history = None
        self._pending_activation_lock_mode = None
        self._activation_unresolved = False

    def activate_legacy_migration(self, ticket, staging_path, *, authentication_context,
                                  time_budget_seconds=30):
        """Internal maintenance operation; never an unauthenticated request route."""
        from .conversation_migration_activation import activate_legacy_migration
        return activate_legacy_migration(self, ticket, staging_path,
            authentication_context=authentication_context, time_budget_seconds=time_budget_seconds)

    def backup_recovery(self, directory, *, authentication_context, timeout_seconds=2.0):
        """Back up this owner's admitted graph and ordinary content together."""
        from .application_recovery import backup_application_recovery
        return backup_application_recovery(self, directory,
            authentication_context=authentication_context, timeout_seconds=timeout_seconds)

    def maintain_retention(self, *, authentication_context, after_conversation_id=None,
                           cancellation_event=None, timeout_seconds=2.0):
        """Internal bounded maintenance; never activates or clears unknown history."""
        from .conversation_retention_maintenance import maintain_conversation_retention
        return maintain_conversation_retention(self, authentication_context=authentication_context,
            after_conversation_id=after_conversation_id, cancellation_event=cancellation_event,
            timeout_seconds=timeout_seconds)

    def prepare_recovery_restore(self, recovery_directory, destination, *,
                                 authentication_context, timeout_seconds=30.0):
        """Prepare an isolated same-instance recovery; never replace live state."""
        from .application_recovery_restore import prepare_owner_recovery_restore
        return prepare_owner_recovery_restore(self, recovery_directory, destination,
            authentication_context=authentication_context, timeout_seconds=timeout_seconds)

    def _history_for(self, binding):
        from .conversation_history import ConversationHistoryStore
        if self._path is None or not self._path.is_file():
            raise FileNotFoundError("admitted conversation database is missing")
        if self._history is None:
            history = ConversationHistoryStore(self._path, instance_id=binding.instance_id, create=False)
            try:
                history.conversation_head(binding.space_root)
            except BaseException:
                history.close()
                raise
            self._history = history
        if self._history.instance_id != binding.instance_id:
            raise InvalidCell("conversation instance changed; governed reopen is required")
        return self._history

    def append_authenticated(self, *, space_root, actor_root, category_root, content,
                             idempotency_key, authentication_context, expected_revision,
                             created_at=None, recipient_roots=(), reference_roots=(),
                             reply_to_root=None, evidence_roots=(), source_authentication_context=None,
                             require_new=False):
        """Internal sink beneath authenticated application writers, not a route.

        The caller retains route/session/provenance checks. This sink enforces
        the current conversation policy and exact authenticated actor itself.
        Graph controls stay unchanged while only ordinary content is committed.
        No default context, graph patch, model call or runtime worker is created.
        """
        from .cell_authorization import AuthorizationDenied, AuthorizationRequest, require_authorization
        from .cell_deliberation import _bounded_unique, absent_roots

        if type(expected_revision) is not int or expected_revision < 0:
            raise InvalidCell("conversation writer requires an expected graph revision")
        recipients = _bounded_unique(recipient_roots, label="message recipients", maximum=64)
        references = _bounded_unique(reference_roots, label="message references", maximum=64)
        evidence = _bounded_unique(evidence_roots, label="message evidence", maximum=64)
        owner = self._owner
        # Match AuthenticationBroker.commit_authenticated lock ordering.
        with owner.mutation_lock:
            self._require_live_owner()
            registry, store = owner.universal_registry, owner.universal_store
            authority = registry.authorization
            with authority.broker.live_context(authentication_context):
                with store.stable_snapshot() as snapshot:
                    if snapshot.revision != expected_revision:
                        raise AuthorizationDenied("conversation authority changed; refresh")
                    binding = read_content_binding(snapshot, registry.deliberation_protocol,
                        application_root=registry.application_root, space_root=space_root)
                    space = read_content_space(snapshot, registry.deliberation_protocol, space_root)
                    if actor_root not in space.participant_roots:
                        raise AuthorizationDenied("message actor is not a conversation participant")
                    if category_root not in space.category_roots:
                        raise InvalidCell("message category is not admitted by the conversation")
                    if set(recipients) - set(space.participant_roots):
                        raise AuthorizationDenied("message recipient is not a conversation participant")
                    if absent_roots(snapshot.cells, (actor_root, category_root, *recipients, *references, *evidence)):
                        raise InvalidCell("message references missing Cells")

                    def authorize_commit():
                        self._require_live_owner()
                        if source_authentication_context is not None:
                            from .universal_application import _require_workshop_message_source
                            _require_workshop_message_source(snapshot, registry, actor_root,
                                source_authentication_context)
                        decision = require_authorization(snapshot, authority.protocol, space.policy_root,
                            authority.broker, authentication_context, AuthorizationRequest(
                                action_root=space.action_root, object_root=space.root_id,
                                resource_lineage_roots=space.scope_roots, interface_root=space.interface_root,
                                purpose_root=space.purpose_root, classification_root=space.classification_root,
                                audience_root=space.audience_root, lifecycle_state_root=space.lifecycle_root,
                                operational_state_root=space.operational_state_root))
                        if decision.subject_root != actor_root:
                            raise AuthorizationDenied("authenticated subject does not match the message actor")
                        if decision.policy_root != space.policy_root or decision.action_root != space.action_root:
                            raise AuthorizationDenied("message policy or action does not match")

                    authorize_commit()
                    history = self._history_for(binding)
                    message = history.append(space_root, author=actor_root, content=content,
                        category=category_root, recipients=recipients, refs=references,
                        evidence=evidence, reply_to=reply_to_root, idempotency_key=idempotency_key,
                        created_at=created_at, reply_principal=actor_root,
                        reply_read_all=actor_root == authority.subject_root, before_commit=authorize_commit,
                        require_new=require_new)
                    return {"graph_revision": snapshot.revision,
                        "message": {**message, "idempotency_key": idempotency_key}}

    def page_for_browser(self, token, *, space_root, limit=50, before=None,
                         high_water=None, max_bytes=262144):
        def admit():
            binding = self._owner._resolve_browser_session(token)
            registry = self._owner.universal_registry
            founder = binding.subject_root == registry.authorization.subject_root
            principal = registry.agent_body.session.root_id if founder else binding.subject_root
            return binding.context, principal, founder, False
        return self._page(admit, space_root=space_root, limit=limit, before=before,
            high_water=high_water, max_bytes=max_bytes)

    def page_for_machine(self, request):
        # The existing session proof covers the exact route, body and session.
        # Shared founder route authority is never the message audience identity.
        if (type(request) is not dict or request.get("method") != "GET"
                or request.get("path") != "/api/universal/deliberation"
                or type(request.get("body")) is not dict
                or set(request["body"]) != {"space", "limit"}):
            raise InvalidCell("conversation content machine request is invalid")
        def admit():
            root = self._owner._resolve_universal_machine_agent_session(request)
            context = self._owner.universal_registry.authorization.session.context()
            return context, root, False, True
        return self._page(admit, space_root=request["body"]["space"], limit=request["body"]["limit"])

    def page_for_workshop_browser(self, token, *, binding, space_root, limit=100,
                                  max_bytes=262144, before=None, if_visible_head=None,
                                  if_content_generation=None, category=None):
        """Internal Workshop reader after its actual browser/canvas admission."""
        from .cell_authorization import AuthorizationDenied
        def admit():
            current = self._owner._resolve_browser_session(token)
            if current != binding:
                raise AuthorizationDenied("Workshop browser binding changed")
            registry = self._owner.universal_registry
            founder = current.subject_root == registry.authorization.subject_root
            principal = registry.agent_body.session.root_id if founder else current.subject_root
            return current.context, principal, founder, False
        return self._page(admit, space_root=space_root, limit=limit, max_bytes=max_bytes, before=before,
            _route_path="/api/universal/workshop", _translate_content_errors=True,
            _include_visible_head=True, _if_visible_head=if_visible_head,
            _if_content_generation=if_content_generation, _category=category)

    def page_for_workshop_machine(self, request, *, agent_session_root,
                                  authentication_context, expected_revision, project, limit=50):
        """Project the actual admitted machine route before final read checks."""
        if (type(request) is not dict or request.get("method", "").upper() != "GET"
                or request.get("path") != "/api/universal/workshop" or request.get("body") != {}
                or not callable(project)):
            raise InvalidCell("Workshop content machine request is invalid")
        return self._page_for_admitted_machine(request, agent_session_root=agent_session_root,
            authentication_context=authentication_context, expected_revision=expected_revision,
            project=project, limit=limit, space_root=self._owner.universal_registry.workshop_root)

    def project_for_deliberation_machine(self, request, *, agent_session_root,
                                         authentication_context, expected_revision, project):
        """Read ordinary content for the actual signed generic history route."""
        if (type(request) is not dict or request.get("method", "").upper() != "GET"
                or request.get("path") != "/api/universal/deliberation"
                or type(request.get("body")) is not dict or not callable(project)):
            raise InvalidCell("ordinary deliberation machine request is invalid")
        body = request["body"]
        if (not {"space", "limit"} <= set(body)
                or set(body) - {"space", "limit", "category", "before"}):
            raise InvalidCell("ordinary deliberation machine request shape is invalid")
        return self._page_for_admitted_machine(request, agent_session_root=agent_session_root,
            authentication_context=authentication_context, expected_revision=expected_revision,
            project=project, space_root=body["space"], limit=body["limit"],
            category=body.get("category"), before=body.get("before"))

    def _page_for_admitted_machine(self, request, *, agent_session_root,
                                   authentication_context, expected_revision, project,
                                   space_root, limit, category=None, before=None):
        from .cell_authorization import AuthorizationDenied
        from .universal_application import _runtime_agent_session, _view_session_for_context

        direct = set(request) == {"method", "path", "body"}
        if not direct and set(request) != {"runtime_id", "request_id", "method", "path", "body", "session"}:
            raise InvalidCell("Workshop content machine request shape is invalid")
        founder = direct or request.get("session") == {}
        owner = self._owner
        with owner.mutation_lock:
            self._require_live_owner()
            registry, store = owner.universal_registry, owner.universal_store
            broker = registry.authorization.broker
            with broker.live_context(authentication_context):
                with store.stable_snapshot(expected_revision=expected_revision) as snapshot:
                    def admit():
                        identity = broker.resolve(authentication_context)
                        view, _ = _view_session_for_context(registry, authentication_context)
                        if founder:
                            if (agent_session_root != registry.agent_body.session.root_id
                                    or identity.subject_root != registry.authorization.subject_root
                                    or view.subject_root != identity.subject_root):
                                raise AuthorizationDenied("Workshop read requires the founder context")
                            return authentication_context, agent_session_root, True, False
                        root = owner._resolve_universal_machine_agent_session(request)
                        if root != agent_session_root:
                            raise AuthorizationDenied("Workshop reader session changed")
                        session = _runtime_agent_session(snapshot, registry, root)
                        if session.subject_root != identity.subject_root or view.subject_root != session.subject_root:
                            raise AuthorizationDenied("Workshop reader belongs to another subject")
                        return authentication_context, root, False, True

                    return self._page(admit, space_root=space_root, limit=limit,
                        _route_path=request["path"], _translate_content_errors=True,
                        _project=project, before=before, _category=category)

    def page_for_runtime_context(self, *, agent_session_root, authentication_context,
                                 expected_revision, limit=8, max_bytes=262144):
        return self._read_for_runtime_context(agent_session_root=agent_session_root,
            authentication_context=authentication_context, expected_revision=expected_revision,
            limit=limit, max_bytes=max_bytes)

    def counts_for_runtime_context(self, *, agent_session_root, authentication_context,
                                   expected_revision, read_guard=None,
                                   route=("GET", "/api/universal/deliberation")):
        return self._read_for_runtime_context(agent_session_root=agent_session_root,
            authentication_context=authentication_context, expected_revision=expected_revision,
            counts_only=True, read_guard=read_guard, route=route)

    def counts_for_founder_context(self, *, authentication_context, expected_revision,
                                   read_guard=None, route=("GET", "/api/universal/deliberation")):
        """Owner-only count path after the caller's founder route admission."""
        return self._read_for_runtime_context(
            agent_session_root=self._owner.universal_registry.agent_body.session.root_id,
            authentication_context=authentication_context, expected_revision=expected_revision,
            counts_only=True, _founder=True, read_guard=read_guard, route=route)

    def project_for_founder_context(self, *, authentication_context, expected_revision, project, limit=8,
                                    read_guard=None, route=("GET", "/api/universal/workshop"),
                                    include_categories=False, hold_owner_lock=True):
        """Internal founder report after its caller's founder-route admission.

        ``hold_owner_lock=False`` reads without the owner mutation lock or the
        broker's revocation lock, from a head pinned at ``expected_revision``.
        The caller must then, under the owner lock, confirm the graph head is
        still that revision and pass the page to ``validate_projection_read``
        before using it; the BABOOM native frame does exactly that.
        """
        return self._read_for_runtime_context(
            agent_session_root=self._owner.universal_registry.agent_body.session.root_id,
            authentication_context=authentication_context, expected_revision=expected_revision,
            limit=limit, _founder=True, _project=project, read_guard=read_guard,
            route=route, _include_categories=include_categories,
            _hold_owner_lock=hold_owner_lock)

    def _owner_scope(self, hold):
        return self._owner.mutation_lock if hold else contextlib.nullcontext()

    @staticmethod
    def _revocation_scope(broker, authentication_context, hold):
        if hold:
            return broker.live_context(authentication_context)
        broker.resolve(authentication_context)
        return contextlib.nullcontext()

    @staticmethod
    def _snapshot_scope(store, expected_revision, hold):
        """Held: no commit during the read. Not held: the same guard pins an
        immutable head, released at once; the caller re-checks its revision."""
        if hold:
            return store.stable_snapshot(expected_revision=expected_revision)
        with store.stable_snapshot(expected_revision=expected_revision) as pinned:
            pass
        return contextlib.nullcontext(pinned)

    @staticmethod
    def _admit_runtime_reader(snapshot, registry, agent_session_root, authentication_context, *, founder):
        from .cell_authorization import AuthorizationDenied
        from .universal_application import _runtime_agent_session, _view_session_for_context

        identity = registry.authorization.broker.resolve(authentication_context)
        view, _context = _view_session_for_context(registry, authentication_context)
        if founder:
            if (agent_session_root != registry.agent_body.session.root_id
                    or identity.subject_root != registry.authorization.subject_root
                    or view.subject_root != identity.subject_root):
                raise AuthorizationDenied("conversation read requires the founder context")
            return authentication_context, agent_session_root, True, False
        session = _runtime_agent_session(snapshot, registry, agent_session_root)
        if session.subject_root != identity.subject_root or view.subject_root != session.subject_root:
            raise AuthorizationDenied("conversation context session belongs to another subject")
        return authentication_context, session.root_id, False, True

    @staticmethod
    def _authorize_content_read(snapshot, registry, *, space_root, authentication_context, principal, machine):
        from .cell_authorization import AuthorizationDenied, AuthorizationRequest, require_authorization
        from .universal_application import _require_application_authorization

        _require_application_authorization(snapshot, registry, "read", space_root,
            authentication_context=authentication_context)
        binding = read_content_binding(snapshot, registry.deliberation_protocol,
            application_root=registry.application_root, space_root=space_root)
        space = read_content_space(snapshot, registry.deliberation_protocol, space_root)
        if machine and principal not in space.participant_roots:
            raise AuthorizationDenied("runtime session is not an admitted conversation participant")
        authority = registry.authorization
        require_authorization(snapshot, authority.protocol, space.policy_root,
            authority.broker, authentication_context, AuthorizationRequest(
                action_root=authority.protocol.actions["read"], object_root=space.root_id,
                resource_lineage_roots=space.scope_roots, interface_root=space.interface_root,
                purpose_root=space.purpose_root, classification_root=space.classification_root,
                audience_root=space.audience_root, lifecycle_state_root=space.lifecycle_root,
                operational_state_root=space.operational_state_root))
        return binding

    def validate_projection_read(self, page, *, store, registry, agent_session_root,
                                  authentication_context, expected_revision):
        """Validate a trusted in-process page without rereading ordinary content.

        Metadata describes an earlier admitted read; it grants no authority.
        The caller retains its source-route admission and final source checks.
        """
        from .cell_authorization import AuthorizationDenied

        if (type(expected_revision) is not int or expected_revision < 0
                or type(page) is not dict
                or type(page.get("graph_revision")) is not int
                or type(page.get("read_all")) is not bool
                or any(type(page.get(key)) is not str or not page[key]
                    for key in ("conversation", "instance_id", "principal"))
                or type(page.get("total")) is not int or page["total"] < 0):
            raise InvalidCell("conversation projection metadata is invalid")
        if "categories" in page and (type(page["categories"]) is not dict
                or any(type(key) is not str or not key or type(value) is not int or value < 0
                    for key, value in page["categories"].items())
                or sum(page["categories"].values()) != page["total"]):
            raise InvalidCell("conversation projection category counts are invalid")
        if "messages" in page and (type(page["messages"]) is not list
                or any(type(message) is not dict for message in page["messages"])):
            raise InvalidCell("conversation projection messages are invalid")
        owner = self._owner
        with owner.mutation_lock:
            self._require_live_owner()
            if not self.belongs_to(store, registry) or getattr(owner, "conversation_content", None) is not self:
                raise AuthorizationDenied("conversation projection service is not the current owner")
            with registry.authorization.broker.live_context(authentication_context):
                with store.stable_snapshot(expected_revision=expected_revision) as snapshot:
                    admission = self._admit_runtime_reader(snapshot, registry, agent_session_root,
                        authentication_context, founder=agent_session_root == registry.agent_body.session.root_id)
                    _context, principal, read_all, machine = admission
                    binding = self._authorize_content_read(snapshot, registry, space_root=registry.workshop_root,
                        authentication_context=authentication_context, principal=principal, machine=machine)
                    if (page["graph_revision"] != snapshot.revision
                            or page["conversation"] != binding.space_root
                            or page["instance_id"] != binding.instance_id
                            or page["principal"] != principal or page["read_all"] is not read_all):
                        raise AuthorizationDenied("conversation projection identity or audience changed")
                    if self._admit_runtime_reader(snapshot, registry, agent_session_root,
                            authentication_context, founder=read_all) != admission:
                        raise AuthorizationDenied("conversation projection reader changed")
                    self._require_live_owner()
        return page

    def _read_for_runtime_context(self, *, agent_session_root, authentication_context,
                                  expected_revision, limit=8, max_bytes=262144, counts_only=False,
                                  _founder=False, _project=None, read_guard=None,
                                  route=("GET", "/api/universal/deliberation"), _include_categories=False,
                                  _hold_owner_lock=True):
        """Internal agent read beneath the owner's admitted machine route.

        The caller retains its signed request and claimed-Work admission. An
        explicit live context must own this exact runtime session; shared route
        authority never gives that session the founder's private message view.
        The read is ephemeral. Its text must not be copied into graph capsules.
        """
        if type(expected_revision) is not int or expected_revision < 0:
            raise InvalidCell("conversation context requires an expected graph revision")
        if read_guard is not None and not callable(read_guard):
            raise InvalidCell("conversation read guard must be callable")
        owner = self._owner
        with self._owner_scope(_hold_owner_lock):
            self._require_live_owner()
            registry, store = owner.universal_registry, owner.universal_store
            broker = registry.authorization.broker
            with self._revocation_scope(broker, authentication_context, _hold_owner_lock):
                with self._snapshot_scope(store, expected_revision, _hold_owner_lock) as snapshot:
                    def admit():
                        if read_guard is not None:
                            read_guard()
                        return self._admit_runtime_reader(snapshot, registry, agent_session_root,
                            authentication_context, founder=_founder)

                    page = self._page(admit, space_root=registry.workshop_root,
                        limit=limit, max_bytes=max_bytes, _counts_only=counts_only,
                        _translate_content_errors=True, _project=_project, _route=route,
                        _include_categories=_include_categories, _hold_owner_lock=_hold_owner_lock)
                    # Resolve again after the SQLite read, including expiry.
                    admit()
                    self._require_live_owner()
                    if _project is not None:
                        return page
                    binding = read_content_binding(snapshot, registry.deliberation_protocol,
                        application_root=registry.application_root, space_root=registry.workshop_root)
                    result = {**page, "instance_id": binding.instance_id}
                    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > max_bytes:
                        raise ConversationContentUnavailable("conversation response exceeds output byte budget")
                    return result

    def _page(self, admit, *, space_root, limit=50, before=None,
              high_water=None, max_bytes=262144, _counts_only=False,
              _translate_content_errors=False, _route_path="/api/universal/deliberation",
              _project=None, _route=None, _include_categories=False,
             _include_visible_head=False, _if_visible_head=None, _category=None,
             _if_content_generation=None, _hold_owner_lock=True):
        from .cell_authorization import AuthorizationDenied

        route = ("GET", _route_path) if _route is None else _route
        if type(route) is not tuple or route not in (
                ("GET", "/api/universal/deliberation"),
                ("GET", "/api/universal/workshop"),
                ("GET", "/api/universal/baboom-context"),
                ("GET", "/api/universal/baboom-presence"),
                ("GET", "/api/universal/baboom-native-frame"),
                ("GET", "/api/universal/baboom-steward-briefing"),
                ("POST", "/api/universal/baboom-command-response")):
            raise InvalidCell("conversation reader route is not admitted")
        if _project is not None and not callable(_project):
            raise InvalidCell("conversation projection must be callable")
        if type(_include_categories) is not bool:
            raise InvalidCell("conversation category inclusion must be boolean")
        if type(_include_visible_head) is not bool:
            raise InvalidCell("conversation visible head inclusion must be boolean")
        owner = self._owner
        with self._owner_scope(_hold_owner_lock):
            self._require_live_owner()
            admission = admit()
            authentication_context, principal, read_all, machine = admission
            registry, store = owner.universal_registry, owner.universal_store
            with self._revocation_scope(registry.authorization.broker, authentication_context,
                                        _hold_owner_lock):
                with self._snapshot_scope(store, None, _hold_owner_lock) as snapshot:
                    if admit() != admission:
                        raise AuthorizationDenied("conversation reader identity changed before read")
                    owner.require_universal_http_route(*route,
                        authentication_context=authentication_context, revalidate=True)
                    binding = self._authorize_content_read(snapshot, registry, space_root=space_root,
                        authentication_context=authentication_context, principal=principal, machine=machine)
                    try:
                        history = self._history_for(binding)
                        page = (history.counts(space_root, principal=principal, read_all=read_all)
                            if _counts_only else history.page(space_root, principal=principal,
                                read_all=read_all, limit=limit, before=before, high_water=high_water,
                                max_bytes=max_bytes, include_categories=_include_categories,
                                include_visible_head=_include_visible_head, if_visible_head=_if_visible_head,
                                **({"if_content_generation": _if_content_generation}
                                   if _if_content_generation is not None else {}),
                                **({"category": _category} if _category is not None else {})))
                    except (sqlite3.Error, OSError, ValueError) as exc:
                        if not _translate_content_errors or isinstance(exc, InvalidCell):
                            raise
                        raise ConversationContentUnavailable(
                            "ordinary conversation content could not be read within its limits") from exc
                    result = {**page, "graph_revision": snapshot.revision, "conversation": space_root}
                    if _project is not None:
                        # Metadata comes from this admitted graph/session, never
                        # from ordinary payloads. The trusted formatter selects
                        # its public fields; final admission follows formatting.
                        result = _project({**result, "instance_id": binding.instance_id,
                            "principal": principal, "read_all": read_all})
                    if store.revision != snapshot.revision:
                        raise AuthorizationDenied("conversation authority changed during read; refresh")
                    if admit() != admission:
                        raise AuthorizationDenied("conversation reader identity changed during read")
                    owner.require_universal_http_route(*route,
                        authentication_context=authentication_context, revalidate=True)
                    current_binding = self._authorize_content_read(snapshot, registry, space_root=space_root,
                        authentication_context=authentication_context, principal=principal, machine=machine)
                    if binding != current_binding or not self.belongs_to(store, registry):
                        raise AuthorizationDenied("conversation binding or owner changed during read")
                    registry.authorization.broker.resolve(authentication_context)
                    self._require_live_owner()
                    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > max_bytes:
                        error = ConversationContentUnavailable if _translate_content_errors else ValueError
                        raise error("conversation response exceeds output byte budget")
                    return result
