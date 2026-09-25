"""Owner admission for one native Workshop turn through existing graph protocols.

The retained reservation is process custody, never graph authority. Lost delivery
stays reserved. Only the owner supplies terminal/publisher evidence; these helpers
are not machine routes and never claim, submit, adjudicate or complete Work.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import json
import math
import re
import secrets
import time
import uuid

from .cell_adapters import (
    authorize_adapter_invocation, build_adapter_catalog, build_adapter_definition,
    build_permission_request, grant_permission, read_permission,
    release_adapter_definition, revoke_permission, verify_adapter_catalog,
    verify_released_adapter,
)
from .cell_authorization import AuthorizationDenied
from .cell_model_execution import (
    create_model_delegation, create_model_execution_grant,
    create_model_execution_receipt, read_model_delegation,
    read_model_execution_grant, read_model_execution_receipt,
    read_model_provider, register_model_provider,
)
from .cell_protocols import read_relation
from .cell_value_graph import build_value_graph, read_value_graph
from .native_workshop_tools import WORKSHOP_TASK_TOOL_NAMES
from .universal_cell import InvalidCell, overlay_read_snapshot


PROFILE_VERSION = "native-workshop-task-v1"
ACTION = "native-workshop-turn:claude"
ADAPTER = "app:adapter:native-workshop-turn:claude:v1"
CATALOG = "app:adapter-catalog:native-workshop-turn:v1"
PROVIDER = "app:model-provider:native-workshop-turn:claude:v1"
_TURN_INSTRUCTION = (
    "Execute the exact assigned ArchHub Work through the admitted Workshop tools. "
    "Read and claim that Work, coordinate real evidence, and return a draft patch. "
    "Do not claim a file was changed by producing a patch. Return JSON only: "
    "{\"summary\":\"...\",\"edits\":[{\"path\":\"declared path\","
    "\"before\":\"unique exact current text\",\"after\":\"replacement\"}]}. "
    "Use only the declared inputs; this prompt grants no extra tools. "
    "Do not submit Work or request its completion court until the owner has published "
    "and provided the real artifact execution receipt.\n"
)
_RESERVATION_KEY = object()
EXISTING_ARTIFACT_VERSION = "existing-session-artifact-v1"
_LIMITS = {
    "max_turns": (1, 32), "max_processes": (1, 64),
    "max_input_bytes": (1024, 16 * 1024**2),
    "max_output_bytes": (1024, 16 * 1024**2),
    "max_event_bytes": (256, 1024**2), "max_events": (1, 2048),
    "max_process_bytes": (1024**2, 8 * 1024**3),
}
_TIMES = ("startup_timeout_seconds", "turn_timeout_seconds", "lifetime_seconds",
          "stop_timeout_seconds")


def _require(ok, message):
    if not ok:
        raise InvalidCell(message)


def _text(value, limit):
    return (type(value) is str and bool(value.strip()) and "\0" not in value
            and len(value.encode("utf-8")) <= limit)


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _uuid(value):
    try:
        return type(value) is str and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        return False


def _existing_actor(server, request, context):
    """Internal authenticated machine boundary; no actor selector in tool input."""
    from . import universal_application as app
    actor = server._resolve_universal_machine_agent_session(request)
    session = app._runtime_agent_session(server.universal_store.snapshot(),
                                        server.universal_registry, actor)
    identity = server.universal_registry.authorization.broker.resolve(context)
    if session.subject_root != identity.subject_root:
        raise AuthorizationDenied("Artifact caller does not belong to its authenticated view")
    return actor


def _existing_material(server, context, work_root, *, recorded_material=None):
    from . import universal_application as app
    store, registry = server.universal_store, server.universal_registry
    snapshot = store.snapshot()
    registered = {row.participant_id for row in read_relation(snapshot,
        registry.governed_work_registry_root, budget=100000) if row.role_id == registry.roles['member']}
    _require(work_root in registered, "Artifact Work is not registered")
    app._require_application_authorization(snapshot, registry, 'read', work_root,
                                         authentication_context=context)
    claim = app._governed_work_claimant_binding(snapshot, registry, work_root)
    work = app._instance_projection(snapshot, registry, work_root)
    state = str((work or {}).get('operational', {}).get('current_state_label', '')).casefold()
    if claim is None and state == 'complete' and recorded_material is not None:
        # Read completed Work through its actual last claim history; never
        # substitute a caller-provided publisher for a missing claim.
        machine = app.read_instance_state_machine(snapshot, registry.assembly_protocol,
            registry.standard_library.state_machine_protocol, work_root)
        history = app.machine_history(snapshot, registry.standard_library.state_machine_protocol, machine.root_id)
        last_claim = next((event for event in reversed(history)
                           if app._text(snapshot, event.event_root).casefold() == 'claim'), None)
        binding_root = recorded_material['claim_binding']
        _require(last_claim is not None and binding_root in last_claim.context_roots,
                 "Completed artifact has no matching historical claim")
        binding = app._read_governed_work_claim_binding(snapshot, registry, binding_root)
        _require(binding['work'] == work_root and binding['session'] == recorded_material['publisher']
                 and binding['transition'] == last_claim.event_root, "Artifact historical claim changed")
        claim = (binding['session'], binding['body'], binding_root)
    _require(claim is not None and claim[2] is not None, "Artifact requires an exact retained Work claim")
    _require(state in {'claimed', 'review', 'complete'}, "Artifact Work state is not admitted")
    targets, values = {}, {}
    for name in ('inputs', 'requirements', 'cde-container', 'title', 'description'):
        target = app._governed_work_interface_target(snapshot, registry, work_root, name)
        app._require_application_authorization(snapshot, registry, 'read', target,
                                             authentication_context=context)
        if name not in {'title', 'description'} and app._text(snapshot, target) == 'unwired':
            raise InvalidCell("Artifact Work field '%s' is unwired; configure the Work's inputs, "
                              "requirements and CDE before preparing a publication" % name)
        value = (app._text(snapshot, target) if name in {'title', 'description'} else
                 read_value_graph(snapshot, registry.value_graph_protocol, target))
        values[name] = value
        targets[name] = {'root': target, 'digest': _digest(value)}
    _require(type(values['inputs']) is dict and values['inputs'].get('data_class') == 'public-text',
             "Existing-session artifacts require public-text Work inputs")
    _require(type(values['requirements']) is dict and type(values['cde-container']) is dict,
             "Artifact Work requirements and CDE must be objects")
    reviewers = values['requirements'].get('artifact_reviewers')
    _require(type(reviewers) is list and 0 < len(reviewers) <= 16
             and all(_text(row, 256) for row in reviewers) and len(set(reviewers)) == len(reviewers),
             "Artifact reviewers must be explicitly admitted by Work requirements")
    material = {'contract': EXISTING_ARTIFACT_VERSION, 'application': registry.application_root,
                'work': work_root, 'publisher': claim[0], 'claim_binding': claim[2], 'targets': targets}
    return {**material, 'material_digest': _digest(material)}, reviewers, state


def existing_session_artifact_material(server, *, request, context, work_root):
    with _admitted(server, context):
        actor = _existing_actor(server, request, context)
        material, _, _ = _existing_material(server, context, work_root)
        _require(actor == material['publisher'], "Only this Work's bound publisher may prepare publication")
        return material


def _existing_record(server, root):
    _require(type(root) is str and root.startswith('app:existing-artifact:'), "Artifact record identity is invalid")
    value = read_value_graph(server.universal_store.snapshot(),
                            server.universal_registry.value_graph_protocol, root)
    _require(type(value) is dict and value.get('contract') == EXISTING_ARTIFACT_VERSION,
             "Artifact record contract is invalid")
    return value


def _existing_save(server, context, root, document):
    if root in server.universal_store.snapshot().cells:
        _require(_existing_record(server, root) == document, "Artifact idempotency identity conflicts")
        return
    pending = _PendingStore(server.universal_store.snapshot())
    build_value_graph(pending, server.universal_registry.value_graph_protocol, document, root_id=root)
    _attach(pending, server.universal_registry, (root,))
    if document.get('kind') == 'existing-session-publication':
        from .cell_protocols import build_relation, append_relation_member
        registry = server.universal_registry
        index = document['work'] + ':artifact-publications'
        if index not in pending.snapshot().cells:
            build_relation(pending, ((registry.roles['scope'], document['work']),
                (registry.roles['member'], root)), relation_id=index)
            _attach(pending, registry, (index,))
        else:
            append_relation_member(pending, index, registry.roles['member'], root)
    _publish(server, pending, context, None)


def publish_existing_session_artifact(server, *, request, context, work_root,
                                    material_digest, idempotency_key, patch, summary):
    """Reserve intent, publish once, reconcile bytes; never invent execution evidence."""
    from . import universal_application as app
    _require(type(patch) is bytes and 0 < len(patch) <= 262144, "Artifact byte limit exceeded")
    try:
        patch.decode('utf-8')
    except UnicodeError as exc:
        raise InvalidCell("Artifact must be UTF-8") from exc
    _require(_text(summary, 4096) and _text(idempotency_key, 128), "Artifact request metadata is invalid")
    digest = hashlib.sha256(patch).hexdigest()
    with _admitted(server, context):
        actor = _existing_actor(server, request, context)
        material, _, state = _existing_material(server, context, work_root)
        _require(actor == material['publisher'] and material_digest == material['material_digest'],
                 "Artifact publisher or reviewed material changed")
        app._require_application_authorization(server.universal_store.snapshot(), server.universal_registry,
                                             'execute', work_root, authentication_context=context)
        # Publishing artifact bytes on claimed Work is an effect: the Workshop
        # execution gate holds before the intent is written.
        app._require_workshop_execution_gate(server.universal_store.snapshot(), server.universal_registry,
            work_root=work_root, agent_session_root=actor,
            content_service=getattr(server, "conversation_content", None))
        key = _digest([server.universal_registry.application_root, work_root, actor, idempotency_key])
        intent_root = 'app:existing-artifact:' + key + ':intent'
        publication_root = 'app:existing-artifact:' + key + ':publication'
        name = 'existing-' + key + '.patch'
        intent = {'contract': EXISTING_ARTIFACT_VERSION, 'kind': 'publication-intent',
                  'material': material, 'artifact_digest': digest, 'artifact_bytes': len(patch),
                  'artifact_name': name, 'summary_digest': _digest(summary), 'idempotency_key': idempotency_key}
        exists = intent_root in server.universal_store.snapshot().cells
        if not exists:
            _require(state == 'claimed', "New publication requires claimed Work")
        _existing_save(server, context, intent_root, intent)

        @contextmanager
        def publication_guard():
            with _admitted(server, context):
                current, _, current_state = _existing_material(server, context, work_root)
                _require(current == material and current_state == 'claimed'
                         and _existing_actor(server, request, context) == actor,
                         "Artifact admission changed before physical publication")
                app._require_application_authorization(server.universal_store.snapshot(),
                    server.universal_registry, 'execute', work_root, authentication_context=context)
                yield

        if not exists:
            result = server.project_work_execution_broker.publish_artifact(patch, name,
                summary=summary, before_publish=publication_guard)
            if result.outcome != 'succeeded':
                return {'status': 'uncertain', 'intent': intent_root, 'publication': None}
        # Also reconciles a lost physical-success/graph-commit response. An
        # intent without matching physical bytes is never permission to retry.
        try:
            actual = server.project_work_execution_broker.read_artifact(name, digest).encode('utf-8')
        except (OSError, InvalidCell, UnicodeError):
            return {'status': 'uncertain', 'intent': intent_root, 'publication': None}
        _require(actual == patch, "Artifact bytes changed")
        _require(_existing_material(server, context, work_root)[0] == material
                 and _existing_actor(server, request, context) == actor, "Artifact binding changed after publication")
        publication = {'contract': EXISTING_ARTIFACT_VERSION, 'kind': 'existing-session-publication',
                       'intent': intent_root, 'intent_digest': _digest(intent), **intent['material'],
                       'artifact_digest': digest, 'artifact_bytes': len(patch), 'artifact_name': name}
        _existing_save(server, context, publication_root, publication)
        return {'status': 'published', 'publication': publication_root, **publication}


def _existing_publication(server, context, work_root, publication_root):
    publication = _existing_record(server, publication_root)
    _require(publication.get('kind') == 'existing-session-publication' and publication.get('work') == work_root,
             "Artifact publication belongs to another Work")
    intent = _existing_record(server, publication['intent'])
    material, reviewers, _ = _existing_material(server, context, work_root, recorded_material=intent['material'])
    _require(publication['intent_digest'] == _digest(intent) and intent['material'] == material
             and all(publication.get(key) == value for key, value in material.items())
             and all(publication.get(key) == intent.get(key) for key in
                     ('artifact_digest', 'artifact_bytes', 'artifact_name')),
             "Artifact publication material or receipt changed")
    return publication, reviewers


def _existing_read(server, context, work_root, publication_root):
    publication, reviewers = _existing_publication(server, context, work_root, publication_root)
    content = server.project_work_execution_broker.read_artifact(publication['artifact_name'], publication['artifact_digest'])
    _require(len(content.encode('utf-8')) == publication['artifact_bytes'], "Artifact size changed")
    return publication, content, reviewers


def existing_session_saved_artifacts(server, *, context, work_root):
    """Read admitted publication metadata; status polling never loads patch bytes."""
    from . import universal_application as app
    with _admitted(server, context):
        snapshot, registry = server.universal_store.snapshot(), server.universal_registry
        app._require_application_authorization(snapshot, registry, 'read', work_root,
                                              authentication_context=context)
        index = work_root + ':artifact-publications'
        if index not in snapshot.cells:
            return []
        members = read_relation(snapshot, index, budget=8192, retain_projection=False)
        _require([row.participant_id for row in members if row.role_id == registry.roles['scope']] == [work_root],
                 "Artifact index belongs to another Work")
        roots = [row.participant_id for row in members if row.role_id == registry.roles['member']]
        _require(len(roots) <= 256 and len(roots) == len(set(roots)),
                 "Existing artifact selection exceeds its bounded Work index")
        results = []
        for root in roots[-32:]:
            publication = _existing_record(server, root)
            _require(publication.get('work') == work_root and publication.get('kind') == 'existing-session-publication',
                     "Artifact index publication belongs to another Work")
            available = True
            try:
                _existing_publication(server, context, work_root, root)
            except (InvalidCell, AuthorizationDenied):
                available = False
            results.append({'publication': root, 'work': work_root,
                'publisher': publication['publisher'], 'name': publication['artifact_name'],
                'digest': publication['artifact_digest'], 'bytes': publication['artifact_bytes'],
                'available': available})
        return results


def read_existing_session_artifact(server, *, request, context, work_root, publication_root):
    with _admitted(server, context):
        actor = _existing_actor(server, request, context)
        publication, content, reviewers = _existing_read(server, context, work_root, publication_root)
        _require(actor == publication['publisher'] or actor in reviewers, "Artifact reader is not admitted")
        return {'publication': publication_root, **publication, 'artifact_text': content}


def review_existing_session_artifact(server, *, request, context, work_root, publication_root,
                                   artifact_digest, idempotency_key, verdict, notes):
    from . import universal_application as app
    from .conversation_content import workshop_message_identity
    _require(verdict in {'approve', 'request_changes'} and _text(notes, 16384)
             and _text(idempotency_key, 128), "Artifact review fields are invalid")
    with _admitted(server, context):
        actor = _existing_actor(server, request, context)
        publication, _, reviewers = _existing_read(server, context, work_root, publication_root)
        _require(actor != publication['publisher'] and actor in reviewers, "Artifact reviewer is not independently admitted")
        _require(artifact_digest == publication['artifact_digest'], "Reviewed artifact digest changed")
        app._require_application_authorization(server.universal_store.snapshot(), server.universal_registry,
                                             'execute', work_root, authentication_context=context)
        root = 'app:existing-artifact:' + _digest([publication_root, actor, idempotency_key]) + ':review'
        document = {'contract': EXISTING_ARTIFACT_VERSION, 'kind': 'existing-session-review',
                    'work': work_root, 'publication': publication_root, 'artifact_digest': artifact_digest,
                    'material_digest': publication['material_digest'], 'publisher': publication['publisher'],
                    'reviewer': actor, 'verdict': verdict, 'notes_digest': _digest(notes),
                    'idempotency_key': idempotency_key}
        # Reserve the immutable review identity before ordinary content append.
        # A lost content/graph response cannot authorize different notes/verdict.
        if root not in server.universal_store.snapshot().cells:
            _, _, state = _existing_material(server, context, work_root,
                recorded_material=_existing_record(server, publication['intent'])['material'])
            _require(state in {'claimed', 'review'}, "New review requires unfinished Work")
        _existing_save(server, context, root + ':intent', document)
        if root in server.universal_store.snapshot().cells:
            saved = _existing_record(server, root)
            _require(all(saved.get(k) == v for k, v in document.items()), "Review idempotency identity conflicts")
            return {'review': root, **saved}
        # Same owner-mediated actor context used by real Work notices; retain
        # the originating context so minting cannot replace source admission.
        authority = server.universal_registry.authorization.broker
        app._require_workshop_message_source(server.universal_store.snapshot(),
            server.universal_registry, actor, context)
        identity = authority.resolve(context)
        actor_context = authority.mint_authenticated_context(actor, principal_roots=(),
            tenant_root=identity.tenant_root, assurance_root=identity.assurance_root, lifetime_seconds=60.0)
        try:
            entry = app.append_universal_workshop_entry(server.universal_store, server.universal_registry,
                actor_root=actor, category_root=server.universal_registry.workshop_category_roots['note'],
                content=notes, idempotency_key='artifact-review:' + _digest([root, document]), created_at=None,
                reference_roots=(work_root, publication_root), recipient_roots=(publication['publisher'],),
                authentication_context=actor_context, source_authentication_context=context,
                expected_revision=server.universal_store.revision, content_service=server.conversation_content)
        finally:
            authority.revoke(actor_context)
        _require(_existing_actor(server, request, context) == actor, "Reviewer identity changed")
        _existing_read(server, context, work_root, publication_root)
        document['message'] = workshop_message_identity(entry)
        _existing_save(server, context, root, document)
        return {'review': root, **document}


def verify_existing_session_artifact_review(server, *, context, work_root, publication_root, review_root):
    """Court composition seam: signed court remains the only completion judge."""
    with _admitted(server, context):
        publication, _, reviewers = _existing_read(server, context, work_root, publication_root)
        review = _existing_record(server, review_root)
        intent = _existing_record(server, review_root + ':intent')
        expected_root = 'app:existing-artifact:' + _digest([
            publication_root, review.get('reviewer'), review.get('idempotency_key')]) + ':review'
        _require(review_root == expected_root
                 and set(review) == set(intent) | {'message'}
                 and all(review.get(key) == value for key, value in intent.items())
                 and type(review.get('message')) is dict and bool(review['message'].get('root')),
                 "Independent artifact review intent or identity changed")
        _require(review.get('kind') == 'existing-session-review' and review.get('work') == work_root
                 and review.get('publication') == publication_root and review.get('verdict') == 'approve'
                 and review.get('publisher') == publication['publisher']
                 and review.get('reviewer') != publication['publisher'] and review.get('reviewer') in reviewers
                 and review.get('artifact_digest') == publication['artifact_digest']
                 and review.get('material_digest') == publication['material_digest'],
                 "Independent artifact review does not match current Work")
        return {'publication': publication_root, 'review': review_root,
                'artifact_digest': publication['artifact_digest'], 'publisher': publication['publisher'],
                'reviewer': review['reviewer'], 'material_digest': publication['material_digest']}


def _prompt(material, digest):
    return material["turn_instruction"] + _bytes({"work": material["work"],
        "input_digest": digest, "request": material["request"]}).decode("utf-8")


def native_material_from_values(inputs, requirements, *, title, description):
    """Return a detached request and its canonical bytes; no graph or file reads."""
    from .project_work_execution_broker import _artifact_name, _validated_inputs
    _require(type(inputs) is dict and set(inputs) == {
        "runtime", "model", "data_class", "files", "artifact_name", "limits"
    }, "Native Work input fields are incomplete or undeclared")
    _require(inputs["runtime"] == "claude" and inputs["data_class"] == "public-text",
             "Native Work requires explicit Claude and public-text input")
    _require(_text(inputs["model"], 160) and not inputs["model"].startswith("-")
             and inputs["model"] == inputs["model"].strip()
             and not any(character.isspace() for character in inputs["model"]),
             "Native Work requires an explicit model")
    limits = inputs["limits"]
    _require(type(limits) is dict and set(limits) == set(_LIMITS) | set(_TIMES),
             "Native Work requires all explicit resource and time limits")
    for name, (low, high) in _LIMITS.items():
        _require(type(limits[name]) is int and low <= limits[name] <= high,
                 "Native Work resource limit is invalid")
    for name in _TIMES:
        _require(type(limits[name]) in (int, float) and math.isfinite(limits[name])
                 and 0 < limits[name] <= 3600, "Native Work time limit is invalid")
    _require(limits["max_event_bytes"] <= limits["max_output_bytes"]
             and max(limits["startup_timeout_seconds"], limits["turn_timeout_seconds"])
             <= limits["lifetime_seconds"] and limits["stop_timeout_seconds"] <= 60,
             "Native Work limits are inconsistent")
    _require(_text(title, 2048) and _text(description, 16384),
             "Native Work requires an explicit task")
    _require(type(requirements) is dict and set(requirements) == {"acceptance_criteria"},
             "Native Work requires connected acceptance criteria")
    criteria = requirements["acceptance_criteria"]
    _require(type(criteria) is list and 1 <= len(criteria) <= 8 and all(
        type(row) is dict and set(row) == {"criterion", "verification"}
        and all(_text(row[key], 4096) for key in row) for row in criteria
    ), "Native Work criteria require an outcome and verification")
    # The publisher's provider-neutral validators also cover Windows reserved
    # names and exact path normalization before the user reviews this request.
    files = _validated_inputs(inputs["files"])
    artifact = _artifact_name(inputs["artifact_name"])
    request = {"runtime": inputs["runtime"], "model": inputs["model"],
        "task": title + "\n\n" + description,
        "criteria": [row["criterion"] + "\nVerification: " + row["verification"]
                     for row in criteria], "inputs": files, "artifact_name": artifact,
        "data_class": inputs["data_class"], "limits": limits}
    raw = _bytes(request)
    _require(len(raw) <= 131072, "Native Work request exceeds its bound")
    return json.loads(raw), raw


class _PendingStore:
    """Compose existing primitives over a small overlay, never copy the graph."""
    def __init__(self, snapshot):
        self.base = snapshot
        self.current = snapshot
        self.create, self.replace = {}, {}

    @property
    def revision(self):
        return self.current.revision

    def snapshot(self):
        return self.current

    def commit(self, expected_revision, *, create=(), replace=()):
        _require(expected_revision == self.revision, "Native preparation revision drifted")
        create, replace = tuple(create), tuple(replace)
        self.current = overlay_read_snapshot(self.current, create=create, replace=replace)
        for cell in create:
            self.create[cell.id] = cell
        for cell in replace:
            (self.create if cell.id in self.create else self.replace)[cell.id] = cell
        return self.revision


@contextmanager
def _admitted(server, context):
    _require(context is not None, "Native Workshop requires authenticated owner context")
    registry = server.universal_registry
    with server.mutation_lock, registry.authorization.broker.live_context(context):
        # stable_snapshot is explicitly read-only: mutations use the owner
        # lock plus the pending base revision CAS at authenticated publication.
        yield


def _founder(server, context, work_root):
    from . import universal_application as app
    registry, snapshot = server.universal_registry, server.universal_store.snapshot()
    identity = registry.authorization.broker.resolve(context)
    if identity.subject_root != registry.authorization.subject_root:
        raise AuthorizationDenied("Native Workshop preparation requires its authenticated owner")
    app._require_application_authorization(snapshot, registry, "execute", work_root,
                                          authentication_context=context)
    return identity


def _publish(server, pending, context, guard):
    if guard is not None:
        guard()
    return server.universal_registry.authorization.broker.commit_authenticated(
        context, server.universal_store, pending.base.revision,
        create=tuple(pending.create.values()), replace=tuple(pending.replace.values()))


def _provider(store, registry, *, create=False):
    protocol, adapters = registry.baboom_model_execution_protocol, registry.adapter_protocol
    if ADAPTER not in store.snapshot().cells and create:
        build_adapter_definition(store, adapters, adapter_id=ADAPTER,
            name="Native Workshop Claude turn", actions=(ACTION,),
            locations=("local-cli:claude:workshop",), datatypes=("public-text",),
            evidence="One approved native Workshop turn; exact Work, session, tool profile and limits")
        release_adapter_definition(store, adapters, ADAPTER)
    adapter = verify_released_adapter(store.snapshot(), adapters, ADAPTER)
    snapshot = store.snapshot()
    _require(len(adapter.action_roots) == len(adapter.location_roots) == len(adapter.datatype_roots) == 1
        and snapshot.cells[adapter.action_roots[0]].atom == ACTION.encode()
        and snapshot.cells[adapter.location_roots[0]].atom == b"local-cli:claude:workshop"
        and snapshot.cells[adapter.datatype_roots[0]].atom == b"public-text",
        "Native Workshop adapter release drifted")
    if CATALOG not in snapshot.cells and create:
        build_adapter_catalog(store, adapters, (ADAPTER,), catalog_id=CATALOG, version="1.0.0")
    catalog = verify_adapter_catalog(store.snapshot(), adapters, CATALOG)
    _require(catalog.adapter_roots == (ADAPTER,), "Native Workshop catalog scope drifted")
    if PROVIDER not in store.snapshot().cells and create:
        register_model_provider(store, protocol, adapters, provider_id=PROVIDER,
            adapter_root=ADAPTER, action_root=adapter.action_roots[0],
            location_root=adapter.location_roots[0], datatype_roots=adapter.datatype_roots)
    provider = read_model_provider(store.snapshot(), protocol, adapters, PROVIDER)
    _require(provider.adapter_root == ADAPTER and provider.action_root == adapter.action_roots[0]
             and provider.location_root == adapter.location_roots[0]
             and provider.datatype_roots == adapter.datatype_roots,
             "Native Workshop provider binding drifted")
    return provider


def _material(server, work_root, session_root, context, *, publication=False):
    from . import universal_application as app
    _founder(server, context, work_root)
    registry, store = server.universal_registry, server.universal_store
    snapshot = store.snapshot()
    session, entry, parameters, _ = app._runtime_compliance_subject(snapshot, registry, session_root)
    _require(entry.runtime == parameters["runtime"] == "claude"
             and session.subject_root == registry.authorization.subject_root,
             "Native Workshop child has a different runtime or owner")
    assignments = [app._read_workshop_assignment(snapshot, registry, root)
                   for root in app._workshop_assignment_roots(snapshot, registry)]
    assigned = [row for row in assignments if row.work_root == work_root]
    _require(len(assigned) == 1 and assigned[0].agent_session_root == session_root,
             "Native Work requires one exact assignment to this child")
    claimant = app._governed_work_claimant_binding(snapshot, registry, work_root)
    if claimant is not None and claimant[:2] != (session_root, session.body_root):
        raise AuthorizationDenied("Native Work is claimed by another agent")
    work = app._instance_projection(snapshot, registry, work_root)
    state = str((work or {}).get("operational", {}).get("current_state_label", "")).casefold()
    _require(work is not None and state in ({"open", "claimed", "review"} if publication else {"open", "claimed"})
             and (state != "review" or claimant is not None), "Native Work is not admitted in its current state")
    targets, values = {}, {}
    for name in ("inputs", "requirements", "title", "description"):
        target = app._governed_work_interface_target(snapshot, registry, work_root, name)
        app._require_application_authorization(snapshot, registry, "read", target,
                                              authentication_context=context)
        value = (read_value_graph(snapshot, registry.value_graph_protocol, target)
                 if name in {"inputs", "requirements"} else app._text(snapshot, target))
        values[name] = value
        targets[name] = {"root": target, "digest": _digest(value)}
    request, _ = native_material_from_values(values["inputs"], values["requirements"],
        title=values["title"], description=values["description"])
    # The admitted profile is sealed below from the canonical tool inventory.
    # A duplicated historical count must not reject newly integrated tools.
    _require(bool(WORKSHOP_TASK_TOOL_NAMES)
             and len(set(WORKSHOP_TASK_TOOL_NAMES)) == len(WORKSHOP_TASK_TOOL_NAMES),
             "Native Workshop tool inventory is empty or duplicated")
    value = {"contract": PROFILE_VERSION, "application": registry.application_root,
        "workshop": registry.workshop_root, "work": work_root, "session": session_root,
        "assignment": assigned[0].root_id, "agent_body": session.body_root,
        "catalogue": entry.root_id, "identity": dict(parameters), "targets": targets,
        "profile": {"version": PROFILE_VERSION, "tools": list(WORKSHOP_TASK_TOOL_NAMES)},
        "turn_instruction": _TURN_INSTRUCTION, "request": request}
    # Reserve input room for the actual user envelope and bounded control traffic.
    frame = {"type": "user", "message": {"role": "user", "content": _prompt(value, _digest(value))},
             "session_id": "0" * 36, "parent_tool_use_id": None}
    _require(len(_bytes(frame)) + 4096 <= request["limits"]["max_input_bytes"],
             "Native prompt exceeds its approved input budget")
    _require(store.revision == snapshot.revision, "Native Work changed during material admission")
    return value


def _attach(store, registry, roots):
    from . import universal_application as app
    # Existing graph region membership. Do not add duplicate incidences on reuse.
    snapshot = store.snapshot()
    regions = [tuple(row.participant_id for row in read_relation(snapshot, region, budget=100000)
               if row.role_id == registry.roles["member"])
               for region in (registry.application_root, registry.map.domains["models"])]
    _require(all(regions[0].count(root) == regions[1].count(root) in {0, 1} for root in roots),
             "Native execution graph region membership drifted")
    missing = tuple(root for root in roots if root not in regions[0])
    if missing:
        app._attach_baboom_model_execution_roots(store, registry, missing)


def prepare_native_work(server, *, work_root, session_root, context, before_commit=None):
    """Prepare graph-held material and requested consent; no launch or claim."""
    with _admitted(server, context):
        if before_commit is not None:
            before_commit()
        material = _material(server, work_root, session_root, context)
        store, registry = server.universal_store, server.universal_registry
        pending = _PendingStore(store.snapshot())
        provider = _provider(pending, registry, create=True)
        root = session_root + ":native-workshop-delegation:v1"
        _require(root not in pending.snapshot().cells,
                 "Native child already has a prepared turn; reconcile its existing evidence")
        input_root, permission_root = root + ":input", root + ":permission"
        digest = _digest(material)
        expires = time.time() + min(3600.0, material["request"]["limits"]["lifetime_seconds"] + 300.0)
        build_value_graph(pending, registry.value_graph_protocol, material, root_id=input_root)
        build_permission_request(pending, registry.adapter_protocol, CATALOG,
            request_id=permission_root, adapter_root=ADAPTER,
            user_root=registry.authorization.subject_root, action_roots=(provider.action_root,),
            location_roots=(provider.location_root,), datatype_roots=provider.datatype_roots,
            expires_at=expires, max_invocations=1)
        delegation = create_model_delegation(pending, registry.baboom_model_execution_protocol,
            registry.adapter_protocol, delegation_id=root, session_root=session_root,
            work_root=work_root, provider_root=provider.root_id, model=material["request"]["model"],
            input_digest=digest, datatype_root=provider.datatype_roots[0],
            permission_root=permission_root, expires_at=expires)
        _attach(pending, registry, (ADAPTER, CATALOG, PROVIDER, input_root, permission_root, root))
        revision = _publish(server, pending, context, before_commit)
        request = material["request"]
        return {"work": work_root, "worker": session_root, "delegation": root,
            "input_root": input_root, "permission_root": permission_root,
            "input_digest": delegation.input_digest, "model": request["model"],
            "runtime": request["runtime"], "limits": request["limits"],
            "profile": material["profile"],
            "artifact_name": request["artifact_name"],
            "review_text": json.dumps(material, ensure_ascii=False, indent=2),
            "revision": revision, "expires_at": expires}


def _validated(server, delegation_root, reviewed_digest, context, *, publication=False):
    registry, store = server.universal_registry, server.universal_store
    delegation = read_model_delegation(store.snapshot(), registry.baboom_model_execution_protocol,
                                      registry.adapter_protocol, delegation_root)
    _require(delegation.provider_root == PROVIDER and not delegation.cognition_request_root,
             "Delegation is not a native Workshop turn")
    _require(type(reviewed_digest) is str and hmac.compare_digest(reviewed_digest, delegation.input_digest),
             "Native Work reviewed digest changed")
    material = _material(server, delegation.work_root, delegation.session_root, context, publication=publication)
    sealed = read_value_graph(store.snapshot(), registry.value_graph_protocol, delegation_root + ":input")
    _require(material == sealed and _digest(sealed) == delegation.input_digest
             and delegation.model == material["request"]["model"], "Native Work material changed")
    _require(time.time() < delegation.expires_at, "Native Work delegation expired")
    provider = _provider(store, registry)
    return delegation, provider, material


def approve_native_work(server, *, delegation_root, reviewed_digest, context,
                        consent_broker, consent_handle, before_commit=None):
    with _admitted(server, context):
        delegation, _, _ = _validated(server, delegation_root, reviewed_digest, context)
        pending = _PendingStore(server.universal_store.snapshot())
        if before_commit is not None:
            before_commit()
        grant_permission(pending, server.universal_registry.adapter_protocol, CATALOG,
            delegation.permission_root, consent_broker, consent_handle,
            expected_revision=pending.revision)
        revision = _publish(server, pending, context, before_commit)
        return {"delegation": delegation.root_id, "permission_root": delegation.permission_root,
                "input_digest": delegation.input_digest, "approved": True, "revision": revision}


class NativeTurnReservation:
    """Opaque retained owner custody. Never serialize the capability or repr it."""
    __slots__ = ("_server", "_store", "_delegation", "_grant", "_material", "_token",
                 "external_session_id", "_consumed", "_terminal", "_settled")

    def __init__(self, key, server, delegation, grant, material, token, external_session_id):
        if key is not _RESERVATION_KEY:
            raise TypeError("Native turn reservations require admitted owner creation")
        self._server, self._store = server, server.universal_store
        self._delegation, self._grant, self._material = delegation, grant, material
        self._token, self.external_session_id = token, external_session_id
        self._consumed, self._terminal, self._settled = False, None, None

    def __reduce_ex__(self, protocol):
        raise TypeError("Native turn reservations cannot be serialized")


def _reservation(server, reservation):
    _require(type(reservation) is NativeTurnReservation and reservation._server is server
             and reservation._store is server.universal_store
             and getattr(server, "_native_workshop_reservations", {}).get(reservation._grant.root_id)
             is reservation, "Native turn reservation is not owned by this application process")
    return reservation


def _invocation(server, delegation, provider):
    registry = server.universal_registry
    authorize_adapter_invocation(server.universal_store.snapshot(), registry.adapter_protocol,
        CATALOG, delegation.permission_root, adapter_root=provider.adapter_root,
        user_root=registry.authorization.subject_root, action_root=provider.action_root,
        location_root=provider.location_root, datatype_root=delegation.datatype_root,
        invocation_count=0)


def reserve_native_turn(server, *, delegation_root, session_root, reviewed_digest,
                        external_session_id, context, before_commit=None):
    with _admitted(server, context):
        delegation, provider, material = _validated(server, delegation_root, reviewed_digest, context)
        _require(session_root == delegation.session_root, "Native turn child changed")
        _require(_uuid(external_session_id)
                 and hashlib.sha256(external_session_id.encode()).hexdigest()
                 == material["identity"]["sessionFingerprint"], "Native process session identity changed")
        _invocation(server, delegation, provider)
        registry, store = server.universal_registry, server.universal_store
        protocol = registry.baboom_model_execution_protocol
        grants = [read_model_execution_grant(store.snapshot(), protocol, registry.adapter_protocol,
                  row.participant_id) for row in read_relation(store.snapshot(), protocol.registry("grant"),
                  budget=100000) if row.role_id == protocol.role("registry-member")]
        _require(not any(row.delegation_root == delegation_root for row in grants),
                 "Native delegation is already reserved; reconcile without replay")
        reservations = getattr(server, "_native_workshop_reservations", None)
        if reservations is None:
            reservations = server._native_workshop_reservations = {}
        _require(len(reservations) < 32, "Native owner reservation custody is full")
        pending, token = _PendingStore(store.snapshot()), secrets.token_bytes(32)
        grant = create_model_execution_grant(pending, protocol, registry.adapter_protocol,
            grant_id=delegation_root + ":grant", delegation_root=delegation_root,
            session_root=session_root, expires_at=delegation.expires_at,
            token_digest=hashlib.sha256(token).hexdigest())
        _attach(pending, registry, (grant.root_id,))
        reservation = NativeTurnReservation(_RESERVATION_KEY, server, delegation, grant,
                                             material, token, external_session_id)
        # Retain before the only fallible publication. A lost commit response is
        # not permission to create another grant or another physical attempt.
        reservations[grant.root_id] = reservation
        _publish(server, pending, context, before_commit)
        return reservation


def consume_native_turn(server, reservation, *, context, before_dispatch=None):
    with _admitted(server, context):
        reservation = _reservation(server, reservation)
        _require(not reservation._consumed and reservation._settled is None,
                 "Native turn has already been consumed")
        delegation, provider, material = _validated(server, reservation._delegation.root_id,
                                                    reservation._delegation.input_digest, context)
        grant = read_model_execution_grant(server.universal_store.snapshot(),
            server.universal_registry.baboom_model_execution_protocol,
            server.universal_registry.adapter_protocol, reservation._grant.root_id)
        _require(grant == reservation._grant and time.time() < grant.expires_at
                 and hmac.compare_digest(grant.token_digest, hashlib.sha256(reservation._token).hexdigest()),
                 "Native grant binding or expiry changed")
        _invocation(server, delegation, provider)
        if before_dispatch is not None:
            before_dispatch()
            delegation, provider, material = _validated(server, reservation._delegation.root_id,
                                                        reservation._delegation.input_digest, context)
            _invocation(server, delegation, provider)
            _require(read_model_execution_grant(server.universal_store.snapshot(),
                server.universal_registry.baboom_model_execution_protocol,
                server.universal_registry.adapter_protocol, reservation._grant.root_id) == grant
                and time.time() < grant.expires_at, "Native grant changed during dispatch admission")
        server.universal_registry.authorization.broker.resolve(context)
        request = json.loads(_bytes(material["request"]))
        prompt = _prompt(material, delegation.input_digest)
        # Only deterministic detached return construction follows this latch.
        reservation._consumed = True
        return {"work": delegation.work_root, "worker": delegation.session_root,
            "delegation": delegation.root_id, "grant": grant.root_id,
            "input_digest": delegation.input_digest, "request": request, "prompt": prompt,
            "runtime": request["runtime"], "model": request["model"], "limits": request["limits"],
            "profile": material["profile"],
            "artifact_name": request["artifact_name"]}


@contextmanager
def native_artifact_admission(server, reservation, *, context, before_publish=None):
    """Hold current graph admission only across the bounded artifact publication."""
    with _admitted(server, context), server.universal_store.stable_snapshot():
        reservation = _reservation(server, reservation)
        _require(reservation._consumed and reservation._settled is None,
                 "Native artifact requires its consumed pending turn")
        registry = server.universal_registry
        def revalidate():
            registry.authorization.broker.resolve(context)
            delegation, provider, material = _validated(server, reservation._delegation.root_id,
                reservation._delegation.input_digest, context, publication=True)
            grant = read_model_execution_grant(server.universal_store.snapshot(),
                registry.baboom_model_execution_protocol, registry.adapter_protocol,
                reservation._grant.root_id)
            _require(grant == reservation._grant and time.time() < grant.expires_at
                     and material == reservation._material, "Native artifact grant or material changed")
            _invocation(server, delegation, provider)
        revalidate()
        if before_publish is not None:
            before_publish()
            revalidate()
        yield
        # A slow write or reentrant guard may expire/change authority. The
        # publisher then retains real bytes as uncertain instead of success.
        revalidate()


def settle_native_turn(server, reservation, *, terminal, artifact_result=None, context=None):
    """Record retained confirmed evidence, including after authority expiry.

    This is receipt reconciliation, never effect admission. No new invocation
    occurs here, and changed Work state cannot erase what the owned process did.
    """
    from .project_work_execution_broker import ProjectWorkExecutionResult
    with server.mutation_lock:
        reservation = _reservation(server, reservation)
        _require(reservation._consumed, "Native turn was not dispatched")
        if terminal is None:
            return {"state": "pending", "grant": reservation._grant.root_id, "receipt": None}
        _require(type(terminal) is dict and terminal.get("type") == "result"
                 and terminal.get("session_id") == reservation.external_session_id
                 and _uuid(terminal.get("uuid")),
                 "Native terminal identity is unconfirmed")
        success = terminal.get("subtype") == "success" and terminal.get("is_error") is False
        failure = terminal.get("subtype") in {"error_during_execution", "error_max_turns",
            "error_max_budget_usd", "error_max_structured_output_retries"} and terminal.get("is_error") is True
        _require((success and type(terminal.get("result")) is str) or
                 (failure and type(terminal.get("errors")) is list
                  and all(type(item) is str for item in terminal["errors"])),
                 "Native terminal outcome is unconfirmed")
        raw = _bytes(terminal)
        _require(len(raw) <= reservation._material["request"]["limits"]["max_output_bytes"],
                 "Native terminal exceeds its approved output bound")
        terminal_digest = hashlib.sha256(raw).hexdigest()
        _require(reservation._terminal in (None, terminal_digest), "Native terminal evidence changed")
        reservation._terminal = terminal_digest
        if success and artifact_result is not None:
            _require(type(artifact_result) is ProjectWorkExecutionResult,
                     "Native result requires actual publisher evidence")
        if success and (artifact_result is None or artifact_result.outcome == "uncertain"):
            return {"state": "pending", "grant": reservation._grant.root_id, "receipt": None}
        if success:
            _require(type(artifact_result) is ProjectWorkExecutionResult
                     and artifact_result.outcome in {"succeeded", "failed"},
                     "Native result requires actual publisher evidence")
            result = {key: getattr(artifact_result, key) for key in
                      ("outcome", "output_digest", "output_bytes", "error_code", "artifact_name", "summary")}
            _require(result["artifact_name"] == reservation._material["request"]["artifact_name"],
                     "Native artifact name changed")
        else:
            result = {"outcome": "failed", "output_digest": hashlib.sha256(b"").hexdigest(),
                "output_bytes": 0, "error_code": "native_provider_error", "artifact_name": "", "summary": ""}
        delegation, grant = reservation._delegation, reservation._grant
        registry, store = server.universal_registry, server.universal_store
        protocol = registry.baboom_model_execution_protocol
        _require(read_model_execution_grant(store.snapshot(), protocol, registry.adapter_protocol,
                 grant.root_id) == grant and read_model_delegation(store.snapshot(), protocol,
                 registry.adapter_protocol, delegation.root_id) == delegation,
                 "Native retained graph evidence changed")
        value = {"work": delegation.work_root, "session": delegation.session_root,
            "delegation": delegation.root_id, "grant": grant.root_id,
            "input_digest": delegation.input_digest, "terminal_digest": terminal_digest, **result}
        result_root, receipt_root = grant.root_id + ":native-result", grant.root_id + ":native-receipt"
        if reservation._settled is not None:
            _require(reservation._settled["value"] == value, "Native settled evidence changed")
            return dict(reservation._settled["response"])
        pending = _PendingStore(store.snapshot())
        if result_root in pending.snapshot().cells:
            _require(read_value_graph(pending.snapshot(), registry.value_graph_protocol, result_root) == value,
                     "Native saved outcome differs from retained evidence")
        else:
            build_value_graph(pending, registry.value_graph_protocol, value, root_id=result_root)
        if receipt_root in pending.snapshot().cells:
            receipt = read_model_execution_receipt(pending.snapshot(), protocol, registry.adapter_protocol, receipt_root)
            _require(receipt.grant_root == grant.root_id and receipt.outcome == result["outcome"]
                and receipt.output_digest == result["output_digest"]
                and receipt.output_bytes == result["output_bytes"] and receipt.error_code == result["error_code"],
                "Native saved receipt differs from retained evidence")
        else:
            create_model_execution_receipt(pending, protocol, registry.adapter_protocol,
                receipt_id=receipt_root, delegation_root=delegation.root_id, grant_root=grant.root_id,
                provider_root=delegation.provider_root, model=delegation.model,
                input_digest=delegation.input_digest, output_digest=result["output_digest"],
                output_bytes=result["output_bytes"], outcome=result["outcome"], error_code=result["error_code"])
        permission = read_permission(pending.snapshot(), registry.adapter_protocol, delegation.permission_root)
        if permission.lifecycle_root == registry.adapter_protocol.states["granted"]:
            revoke_permission(pending, registry.adapter_protocol, delegation.permission_root)
        _attach(pending, registry, (result_root, receipt_root))
        if pending.create or pending.replace:
            store.commit(pending.base.revision, create=tuple(pending.create.values()),
                         replace=tuple(pending.replace.values()))
        response = {"state": "settled", "work": delegation.work_root, "grant": grant.root_id,
            "receipt": receipt_root, "result": result_root, "revision": store.revision, **result,
            "name": result["artifact_name"], "digest": result["output_digest"], "bytes": result["output_bytes"]}
        reservation._settled = {"value": value, "response": response}
        return dict(response)


def native_saved_artifacts(snapshot, registry, work_root, *, receipt_root=None):
    """Read durable native artifact pointers for an already read-admitted Work."""
    protocol = registry.baboom_model_execution_protocol
    if receipt_root is None:
        roots = [row.participant_id for row in read_relation(snapshot, protocol.registry("receipt"),
                 budget=8192, retain_projection=False) if row.role_id == protocol.role("registry-member")]
        _require(len(roots) <= 256 and len(roots) == len(set(roots)),
                 "Native receipt selection exceeds its bounded registry")
    else:
        roots = [receipt_root]
    results = []
    for root in roots:
        receipt = read_model_execution_receipt(snapshot, protocol, registry.adapter_protocol, root)
        if receipt.provider_root != PROVIDER:
            _require(receipt_root is None, "Receipt is not a native Workshop artifact")
            continue
        delegation = read_model_delegation(snapshot, protocol, registry.adapter_protocol, receipt.delegation_root)
        if delegation.work_root != work_root or receipt.outcome != "succeeded":
            _require(receipt_root is None, "Native artifact receipt belongs to a different Work or failed turn")
            continue
        grant = read_model_execution_grant(snapshot, protocol, registry.adapter_protocol, receipt.grant_root)
        result_root = grant.root_id + ":native-result"
        value = read_value_graph(snapshot, registry.value_graph_protocol, result_root, max_depth=4)
        fields = {"work", "session", "delegation", "grant", "input_digest", "terminal_digest",
                  "outcome", "output_digest", "output_bytes", "error_code", "artifact_name", "summary"}
        _require(type(value) is dict and set(value) == fields and value["work"] == work_root
            and value["session"] == delegation.session_root == grant.session_root
            and value["delegation"] == delegation.root_id == grant.delegation_root
            and value["grant"] == grant.root_id and value["input_digest"] == delegation.input_digest == receipt.input_digest
            and value["output_digest"] == receipt.output_digest and value["output_bytes"] == receipt.output_bytes
            and type(value["output_bytes"]) is int and 0 < value["output_bytes"] <= 262144
            and value["outcome"] == "succeeded" and value["error_code"] == receipt.error_code == ""
            and type(value["terminal_digest"]) is str and re.fullmatch(r"[0-9a-f]{64}", value["terminal_digest"])
            and type(value["artifact_name"]) is str and len(value["artifact_name"]) <= 128
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.patch", value["artifact_name"])
            and type(value["summary"]) is str and len(value["summary"].encode("utf-8")) <= 8192,
            "Native artifact pointer disagrees with its registered receipt")
        sealed = read_value_graph(snapshot, registry.value_graph_protocol, delegation.root_id + ":input")
        _require(type(sealed) is dict and _digest(sealed) == delegation.input_digest
                 and sealed.get("request", {}).get("artifact_name") == value["artifact_name"],
                 "Native saved artifact disagrees with its sealed request")
        results.append({"work": work_root, "result": result_root, "receipt": receipt.root_id,
            "name": value["artifact_name"], "digest": receipt.output_digest,
            "bytes": receipt.output_bytes, "summary": value["summary"], "outcome": "succeeded"})
        _require(len(results) <= 32, "Native Work artifact page exceeds its bound")
    return results


def release_native_turn_custody(server, reservation, *, process):
    """Forget only this drained process's verified settled reservation.

    This releases bounded memory custody, not the Work claim or graph history.
    Missing settlement, uncertain delivery and live descendants remain retained.
    """
    from .native_workshop_process import NativeWorkshopProcess

    _require(type(process) is NativeWorkshopProcess, "Release requires the retained native driver")
    observed = process.status(force_observation=True)
    _require(observed.get("drained") is True and observed.get("started") is True
             and observed.get("process_alive") is False and observed.get("remaining_processes") == []
             and observed.get("pipe_threads_alive") == 0 and observed.get("active_turn") is None
             and observed.get("tree_observed") is True and observed.get("tree_observation_uncertain") is False
             and observed.get("tree_observation_pending") is False,
             "Native custody cannot be released before confirmed drain")
    with server.mutation_lock, server.universal_store.stable_snapshot():
        host = getattr(server, "_existing_workshop_native_host", None)
        held = getattr(host, "_native", None)
        _require(type(reservation) is NativeTurnReservation and reservation._server is server
                 and reservation._store is server.universal_store
                 and getattr(host, "server", None) is server and type(held) is dict
                 and held.get("process") is process and held.get("reservation") is reservation
                 and held.get("worker") == reservation._delegation.session_root
                 and getattr(held.get("profile"), "external_session_id", None)
                 == process.launch.external_session_id == reservation.external_session_id,
                 "Native release does not own this settled process")
        retained = getattr(server, "_native_workshop_reservations", {})
        current = retained.get(reservation._grant.root_id)
        _require(current is reservation or (current is None and reservation._token == b""),
                 "Native release reservation custody changed")
        _require(reservation._consumed and type(reservation._settled) is dict
                 and set(reservation._settled) == {"value", "response"},
                 "Native release requires a confirmed settled graph receipt")
        registry, snapshot = server.universal_registry, server.universal_store.snapshot()
        expected = reservation._settled["response"]
        _require(expected.get("state") == "settled" and expected.get("outcome") in ("succeeded", "failed")
                 and expected.get("grant") == reservation._grant.root_id
                 and expected.get("receipt") == reservation._grant.root_id + ":native-receipt"
                 and expected.get("result") == reservation._grant.root_id + ":native-result"
                 and read_value_graph(snapshot, registry.value_graph_protocol, expected["result"])
                 == reservation._settled["value"], "Native saved settlement is missing or changed")
        if expected["outcome"] == "succeeded":
            rows = native_saved_artifacts(snapshot, registry, reservation._delegation.work_root,
                                          receipt_root=expected["receipt"])
            _require(rows == [{key: expected[key] for key in
                     ("work", "result", "receipt", "name", "digest", "bytes", "summary", "outcome")}],
                     "Native release artifact differs from retained evidence")
        else:
            # A confirmed failed receipt has no successful artifact to publish.
            # Read its registered receipt and exact saved result independently;
            # an in-memory failure label alone cannot release uncertain custody.
            receipt = read_model_execution_receipt(snapshot, registry.baboom_model_execution_protocol,
                                                   registry.adapter_protocol, expected["receipt"])
            delegation = reservation._delegation
            value = reservation._settled["value"]
            fields = {"work", "session", "delegation", "grant", "input_digest", "terminal_digest",
                      "outcome", "output_digest", "output_bytes", "error_code", "artifact_name", "summary"}
            _require(type(value) is dict and set(value) == fields
                     and value["work"] == expected.get("work") == delegation.work_root
                     and value["session"] == reservation._grant.session_root == delegation.session_root
                     and value["delegation"] == receipt.delegation_root == delegation.root_id
                     and value["grant"] == receipt.grant_root == reservation._grant.root_id
                     and receipt.provider_root == delegation.provider_root == PROVIDER
                     and receipt.model == delegation.model
                     and value["input_digest"] == receipt.input_digest == delegation.input_digest
                     and value["terminal_digest"] == reservation._terminal
                     and type(value["terminal_digest"]) is str
                     and re.fullmatch(r"[0-9a-f]{64}", value["terminal_digest"])
                     and value["outcome"] == receipt.outcome == "failed"
                     and value["output_digest"] == receipt.output_digest == expected.get("digest")
                     == expected.get("output_digest")
                     and type(value["output_bytes"]) is int and 0 <= value["output_bytes"] <= 262144
                     and value["output_bytes"] == receipt.output_bytes == expected.get("bytes")
                     == expected.get("output_bytes")
                     and value["error_code"] == receipt.error_code == expected.get("error_code")
                     and value["artifact_name"] == expected.get("name") == expected.get("artifact_name")
                     and value["summary"] == expected.get("summary")
                     and type(value["summary"]) is str and len(value["summary"].encode("utf-8")) <= 8192,
                     "Native failed receipt differs from retained evidence")
            sealed = read_value_graph(snapshot, registry.value_graph_protocol, delegation.root_id + ":input")
            _require(type(sealed) is dict and _digest(sealed) == delegation.input_digest
                     and (value["artifact_name"] == sealed.get("request", {}).get("artifact_name")
                          or value["artifact_name"] == "" and value["error_code"] == "native_provider_error")
                     and read_model_delegation(snapshot, registry.baboom_model_execution_protocol,
                         registry.adapter_protocol, delegation.root_id) == delegation,
                     "Native failed settlement disagrees with its sealed request")
        _require(read_model_execution_grant(snapshot, registry.baboom_model_execution_protocol,
                     registry.adapter_protocol, reservation._grant.root_id) == reservation._grant
                 and read_permission(snapshot, registry.adapter_protocol, reservation._delegation.permission_root)
                 .lifecycle_root == registry.adapter_protocol.states["revoked"],
                 "Native release receipt or permission differs from retained evidence")
        reservation._token = b""
        if current is reservation:
            del retained[reservation._grant.root_id]
        return {"state": "released", "grant": reservation._grant.root_id,
                "receipt": expected["receipt"], "already_released": current is None}


def cancel_native_work(server, *, work_root, session_root, assignment_root, process,
                       context, delegation_root=None, reservation=None, before_commit=None):
    """Retire only a drained, never-dispatched preparation; preserve all history.

    Session close writes its existing signed receipt at its real store revision.
    If the final retirement commit fails, the same closed child/reason can be
    reconciled by this call. A consumed or unknown grant is never cancellation.
    No process is stopped here and no model/Work outcome is manufactured.
    """
    from . import universal_application as app
    from .cell_agent_body import close_agent_session, read_agent_body, read_agent_session
    from .cell_attention import read_obligation, resolve_obligation
    from .cell_protocols import prepare_remove_relation_members
    from .native_workshop_process import NativeWorkshopProcess

    # Observe outside graph/auth locks. Retained owner identity is checked again
    # under the mutation lock; a caller-supplied status dictionary proves nothing.
    _require(type(process) is NativeWorkshopProcess, "Cancellation requires the retained native driver")
    observed = process.status(force_observation=True)
    _require(observed.get("drained") is True and observed.get("started") is True
             and observed.get("process_alive") is False and observed.get("remaining_processes") == []
             and observed.get("pipe_threads_alive") == 0 and observed.get("active_turn") is None
             and observed.get("last_turn") is None and observed.get("tree_observed") is True
             and observed.get("tree_observation_uncertain") is False
             and observed.get("tree_observation_pending") is False,
             "Cancellation requires confirmed drain before any native turn")
    with _admitted(server, context):
        host = getattr(server, "_existing_workshop_native_host", None)
        held = getattr(host, "_native", None)
        _require(getattr(host, "server", None) is server and type(held) is dict
                 and held.get("process") is process and held.get("worker") == session_root
                 and getattr(held.get("profile"), "external_session_id", None) == process.launch.external_session_id,
                 "Cancellation does not own this native preparation")
        _founder(server, context, work_root)
        if before_commit is not None:
            before_commit()
        store, registry = server.universal_store, server.universal_registry
        snapshot = store.snapshot()
        session = read_agent_session(snapshot, registry.agent_body.protocol,
                                     registry.authorization.protocol, session_root)
        entry = app._agent_body_catalog_entry_for_session(snapshot, registry, session)
        _require(entry.runtime == process.launch.runtime == "claude"
                 and session.subject_root == registry.authorization.subject_root,
                 "Cancellation child runtime or owner changed")
        properties = app._property_index(snapshot, registry, tuple(
            row.participant_id for row in read_relation(snapshot, registry.canvas_root, budget=100000)
            if row.role_id == registry.roles["property"])).get(session_root, ())
        fingerprints = [app._text(snapshot, row.value_root) for row in properties
                        if app._text(snapshot, row.label_root) == "session fingerprint"]
        _require(fingerprints == [hashlib.sha256(process.launch.external_session_id.encode()).hexdigest()],
                 "Cancellation process identity differs from its graph child")
        assignment = app._read_workshop_assignment(snapshot, registry, assignment_root)
        _require(assignment.work_root == work_root and assignment.agent_session_root == session_root,
                 "Cancellation assignment identity changed")
        cancellation_root = assignment_root + ":native-cancellation"
        if cancellation_root in snapshot.cells:
            saved = read_value_graph(snapshot, registry.value_graph_protocol, cancellation_root)
            fields = {"outcome", "work", "session", "assignment", "session_close_receipt",
                      "delegation", "grant", "session_fingerprint", "process_id",
                      "drain_coverage", "native_turn_dispatched"}
            _require(type(saved) is dict and set(saved) == fields and saved.get("work") == work_root
                     and saved.get("session") == session_root and saved.get("assignment") == assignment_root
                     and saved.get("outcome") == "cancelled-before-turn"
                     and saved["session_close_receipt"] == session.close_receipt_root
                     and saved["session_fingerprint"] == fingerprints[0]
                     and type(saved["process_id"]) is int and saved["process_id"] == observed["pid"]
                     and saved["drain_coverage"] == "observed-descendants"
                     and saved["native_turn_dispatched"] is False
                     and saved["delegation"] in (None, session_root + ":native-workshop-delegation:v1")
                     and (delegation_root is None or saved["delegation"] == delegation_root)
                     and saved["grant"] in (None, session_root + ":native-workshop-delegation:v1:grant")
                     and (saved["grant"] is None or saved["delegation"] is not None)
                     and session.state_root == registry.agent_body.protocol.state("closed")
                     and session.close_reason_root == assignment_root
                     and assignment_root not in app._workshop_assignment_roots(snapshot, registry)
                     and read_obligation(snapshot, registry.attention_protocol,
                         assignment.obligation_root).state_root == registry.attention_protocol.state("resolved"),
                     "Saved native cancellation is incomplete or changed")
            _require(not any(row.role_id == registry.roles["relation"] and row.participant_id == assignment_root
                     for row in read_relation(snapshot, registry.workshop_workbench_root, budget=100000))
                     and [row.participant_id for row in read_relation(snapshot, assignment.obligation_root)
                          if row.role_id == registry.attention_protocol.role("obligation-resolution-evidence")]
                     == [cancellation_root], "Saved cancellation still has an active assignment or changed evidence")
            if saved["delegation"] is not None:
                delegated = read_model_delegation(snapshot, registry.baboom_model_execution_protocol,
                                                  registry.adapter_protocol, saved["delegation"])
                _require(delegated.session_root == session_root and delegated.work_root == work_root
                         and delegated.provider_root == PROVIDER
                         and read_permission(snapshot, registry.adapter_protocol, delegated.permission_root)
                         .lifecycle_root == registry.adapter_protocol.states["revoked"],
                         "Saved cancellation retains an execution permission")
            if saved["grant"] is not None:
                retained = getattr(server, "_native_workshop_reservations", {})
                _require(type(reservation) is NativeTurnReservation and reservation._server is server
                         and reservation._store is store and held.get("reservation") is reservation
                         and reservation._grant.root_id == saved["grant"]
                         and reservation._delegation == delegated and not reservation._consumed
                         and reservation._settled in (None, {"cancelled": cancellation_root})
                         and read_model_execution_grant(snapshot, registry.baboom_model_execution_protocol,
                             registry.adapter_protocol, saved["grant"]) == reservation._grant
                         and (retained.get(saved["grant"]) is reservation or
                              (saved["grant"] not in retained and reservation._token == b""
                               and reservation._settled == {"cancelled": cancellation_root})),
                         "Saved cancellation has unknown or consumed reservation custody")
                # Reconcile a successful graph commit whose acknowledgement
                # was lost before the ordinary in-memory retirement ran.
                reservation._token = b""
                reservation._settled = {"cancelled": cancellation_root}
                if retained.get(saved["grant"]) is reservation:
                    del retained[saved["grant"]]
            else:
                _require(reservation is None and held.get("reservation") is None
                         and not held.get("reservation_pending"),
                         "Saved cancellation does not account for retained reservation custody")
            return {"state": "cancelled", "releasable": True, "work": work_root,
                "worker": session_root, "assignment": assignment_root,
                "cancellation": cancellation_root, "session_close_receipt": session.close_receipt_root,
                "revision": snapshot.revision}
        current = [app._read_workshop_assignment(snapshot, registry, root)
                   for root in app._workshop_assignment_roots(snapshot, registry)
                   if root == assignment_root]
        _require(len(current) == 1, "Cancellation requires its current registered assignment")
        work = app._instance_projection(snapshot, registry, work_root)
        _require(work is not None and str(work.get("operational", {}).get("current_state_label", "")).casefold()
                 == "open" and app._governed_work_claimant_binding(snapshot, registry, work_root) is None,
                 "Cancellation cannot release claimed or non-open Work")
        if session.state_root == registry.agent_body.protocol.state("active"):
            claimed, _ = app.read_universal_current_work_assignment(store, registry,
                agent_session_root=session_root, authentication_context=context)
            _require(claimed is None, "Cancellation child still owns pending Work")
        else:
            _require(session.state_root == registry.agent_body.protocol.state("closed")
                     and session.close_reason_root == assignment_root,
                     "Cancellation cannot adopt a differently closed child")
            # The ordinary current-claim reader requires an active child. A
            # closed retry is deliberately stricter: any recorded ownership by
            # this never-dispatched child needs reconciliation, not release.
            _require(not any(app._read_governed_work_claim_binding(snapshot, registry, root)["session"]
                             == session_root for root in app._governed_work_claim_binding_roots(snapshot, registry)),
                     "Closed cancellation child has recorded Work ownership")
        protocol = registry.baboom_model_execution_protocol
        expected_delegation = session_root + ":native-workshop-delegation:v1"
        _require(delegation_root in (None, expected_delegation), "Cancellation delegation identity changed")
        selected_delegation = (read_model_delegation(snapshot, protocol, registry.adapter_protocol,
            expected_delegation) if expected_delegation in snapshot.cells else None)
        _require((selected_delegation is None and delegation_root is None) or
                 (selected_delegation is not None and selected_delegation.session_root == session_root
                  and selected_delegation.work_root == work_root and selected_delegation.provider_root == PROVIDER),
                 "Cancellation delegation is missing or changed")
        expected_grant = expected_delegation + ":grant"
        grants = ([read_model_execution_grant(snapshot, protocol, registry.adapter_protocol, expected_grant)]
                  if expected_grant in snapshot.cells else [])
        if grants or reservation is not None:
            reservation = _reservation(server, reservation)
            _require(not reservation._consumed and reservation._settled is None
                     and held.get("reservation") is reservation
                     and reservation._delegation.session_root == session_root
                     and reservation._delegation.work_root == work_root
                     and selected_delegation == reservation._delegation
                     and grants == [reservation._grant],
                     "A consumed or unknown native attempt cannot be cancelled")
        else:
            _require(held.get("reservation") is None and not held.get("reservation_pending"),
                     "An unresolved native reservation cannot be cancelled")
        # The signed close receipt must use the actual physical store revision,
        # not the virtual revision of a multi-primitive pending overlay.
        if session.state_root == registry.agent_body.protocol.state("active"):
            body = read_agent_body(snapshot, registry.agent_body.protocol,
                                   registry.authorization.protocol, session.body_root)
            resolver = app.verify_relationship_authority_snapshot(snapshot,
                registry.authorization.identity_protocol, registry.authorization.relationship_broker)
            close_agent_session(store, registry.agent_body.protocol, registry.authorization.protocol,
                registry.authorization.broker, context,
                app._agent_body_request(registry.authorization, registry.agent_body.protocol,
                    body.lifecycle_root, "execute", session_root, lineage_roots=(session.scope_root,)),
                session_root, reason_root=assignment_root, resolver_state=resolver)
        session = read_agent_session(store.snapshot(), registry.agent_body.protocol,
                                     registry.authorization.protocol, session_root)
        pending = _PendingStore(store.snapshot())
        evidence = {"outcome": "cancelled-before-turn", "work": work_root, "session": session_root,
            "assignment": assignment_root, "session_close_receipt": session.close_receipt_root,
            "delegation": selected_delegation.root_id if selected_delegation else None,
            "grant": grants[0].root_id if grants else None,
            "session_fingerprint": fingerprints[0], "process_id": observed["pid"],
            "drain_coverage": "observed-descendants", "native_turn_dispatched": False}
        build_value_graph(pending, registry.value_graph_protocol, evidence, root_id=cancellation_root)
        if selected_delegation is not None:
            permission = read_permission(pending.snapshot(), registry.adapter_protocol,
                                         selected_delegation.permission_root)
            if permission.lifecycle_root in {registry.adapter_protocol.states["requested"],
                                             registry.adapter_protocol.states["granted"]}:
                revoke_permission(pending, registry.adapter_protocol, selected_delegation.permission_root)
        resolve_obligation(pending, registry.attention_protocol, assignment.obligation_root,
                           evidence_root=cancellation_root)
        for region, role in ((registry.workshop_assignment_registry_root, registry.roles["member"]),
                             (registry.workshop_workbench_root, registry.roles["relation"])):
            incidences = [row.incidence_id for row in read_relation(pending.snapshot(), region, budget=100000)
                          if row.role_id == role and row.participant_id == assignment_root]
            _require(len(incidences) == 1, "Cancellation active assignment membership changed")
            removal = prepare_remove_relation_members(pending.snapshot(), region, incidences, budget=100000)
            pending.commit(pending.revision, replace=removal.replace)
        _attach(pending, registry, (cancellation_root,))
        revision = _publish(server, pending, context, before_commit)
        if reservation is not None:
            reservation._token = b""
            reservation._settled = {"cancelled": cancellation_root}
            server._native_workshop_reservations.pop(reservation._grant.root_id, None)
        return {"state": "cancelled", "releasable": True, "work": work_root,
            "worker": session_root, "assignment": assignment_root,
            "cancellation": cancellation_root, "session_close_receipt": session.close_receipt_root,
            "revision": revision}
