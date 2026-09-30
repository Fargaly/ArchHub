"""Agents propose governed Work; only the founder binds it (founder decisions 2026-09-30).

The application refuses Work creation from an agent session: "governed Work is
created by the application owner; an agent proposes it in the Workshop". A
proposal is exactly that, an ordinary Workshop message from the proposer's own
bound session. Its text is one marker line and one canonical JSON document naming
the Work, its inputs and requirements (with any artifact reviewers), its CDE
container, and write grants per governed root (each grant its own scoped path,
never a combined root). Posting it admits nothing: no Work, no grant, no permit.

The founder binds a checked set of proposals in one action. Every proposal is read
and checked first; then each becomes a Work through the browser's own creation path
and has its inputs, requirements and CDE first-bound through the one configuration
path, which validates the container and reviewers and records its authorization
evidence. Each Work is its own commit; the result names every Work created.
"""
import hashlib
import json
import re

from .cell_authorization import AuthorizationDenied
from .universal_cell import InvalidCell

MARKER = "ArchHub work proposal v1"
_FIELDS = {"title", "description", "priority", "purpose", "inputs", "requirements", "container", "write_grants"}
_CONTAINER_FIELDS = {"container_id", "source_requirement", "domain", "suitability_status",
                     "owner", "checker", "gate_kind", "tier", "gate_spec", "revision"}
_PURPOSES = {"general", "artifact-publication"}
_RUNTIME_SESSION = "app:agent-session:runtime:"
_MESSAGE_ID = re.compile(r"[A-Za-z0-9:._-]{1,256}\Z")
KEY_PREFIX = "proposal:"


def _refuse(message):
    raise InvalidCell(message)


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def cde_container(payload):
    """The Work's CDE value: WIP, its grants, and exactly the grant paths as allowed paths."""
    grants = payload["write_grants"]
    return {**payload["container"], "lifecycle_state": "WIP", "write_grants": grants,
            "allowed_paths": list(dict.fromkeys(grant["path"] for grant in grants))}


def validate(payload):
    """Refuse any proposal the configuration path would not accept; nothing is written."""
    from .cell_cde_authority import CdeWriteDenied, authorize_cde_container_write

    if type(payload) is not dict or set(payload) != _FIELDS:
        _refuse("A Work proposal names exactly: " + ", ".join(sorted(_FIELDS)))
    title, description = payload["title"], payload["description"]
    if type(title) is not str or not title.strip() or len(title) > 200:
        _refuse("A Work proposal title is 1 to 200 characters")
    if type(description) is not str or len(description) > 4000:
        _refuse("A Work proposal description is at most 4000 characters")
    if type(payload["priority"]) is not int or not 0 <= payload["priority"] <= 1000:
        _refuse("A Work proposal priority is an integer from 0 to 1000")
    if payload["purpose"] not in _PURPOSES:
        _refuse("A Work proposal purpose is general or artifact-publication")
    if type(payload["inputs"]) is not dict or type(payload["requirements"]) is not dict:
        _refuse("A Work proposal's inputs and requirements are objects")
    reviewers = payload["requirements"].get("artifact_reviewers")
    if payload["purpose"] == "artifact-publication" and (
            type(reviewers) is not list or not 0 < len(reviewers) <= 16
            or any(type(root) is not str or not root.startswith(_RUNTIME_SESSION) for root in reviewers)
            or len(set(reviewers)) != len(reviewers)):
        _refuse("An artifact-publication proposal names 1 to 16 reviewer Agent Sessions")
    container = payload["container"]
    if type(container) is not dict or set(container) != _CONTAINER_FIELDS:
        _refuse("A Work proposal container names exactly: " + ", ".join(sorted(_CONTAINER_FIELDS)))
    grants = payload["write_grants"]
    if type(grants) is not list or not 0 < len(grants) <= 128:
        _refuse("A Work proposal carries 1 to 128 write grants")
    for grant in grants:
        if type(grant) is not dict or type(grant.get("operations")) is not list or not grant["operations"]:
            _refuse("A write grant names its path, scope and operations")
    value = cde_container(payload)
    try:
        # The write authority's own container check, on its first grant: every grant,
        # path root and the grants/allowed-paths agreement are validated with it.
        authorize_cde_container_write(value, operation=grants[0]["operations"][0], path=grants[0]["path"])
    except CdeWriteDenied as exc:
        _refuse("Work proposal CDE container is invalid: %s" % exc)
    if len(canonical(payload).encode("utf-8")) > 60000:
        _refuse("A Work proposal is at most 60000 bytes")
    return payload


def render(payload):
    """The message text: the marker line, then the canonical document."""
    return MARKER + "\n" + canonical(validate(payload))


def parse(text):
    """(payload, digest) for exactly a rendered proposal; anything else is refused."""
    if type(text) is not str or not text.startswith(MARKER + "\n"):
        _refuse("This message is not a Work proposal")
    document = text[len(MARKER) + 1:]
    try:
        payload = json.loads(document)
    except ValueError:
        _refuse("This Work proposal is not valid JSON")
    if canonical(payload) != document:
        _refuse("This Work proposal is not in its canonical form")
    return validate(payload), hashlib.sha256(document.encode("utf-8")).hexdigest()


def _bound_works(snapshot, registry):
    """{external key: Work root} for every registered Work bound from a proposal."""
    from . import universal_application as app
    from .cell_protocols import read_relation

    works = {}
    for member in read_relation(snapshot, registry.governed_work_registry_root, budget=100_000):
        if member.role_id != registry.roles["member"]:
            continue
        try:
            key = app._governed_work_interface(snapshot, registry, member.participant_id, "external-key")["value"]
        except (InvalidCell, KeyError, TypeError):
            continue
        if type(key) is str and key.startswith(KEY_PREFIX):
            works[key] = member.participant_id
    return works


def _bound_keys(snapshot, registry):
    """External keys of every registered Work: a proposal binds once."""
    return set(_bound_works(snapshot, registry))


def founder_bind_route(owner, binding, body, session_token):
    """The route's entry: the founder's own Workshop reader and browser guard, then the action."""
    registry = owner.universal_registry

    def guard():
        if owner._resolve_browser_session(session_token) != binding:
            raise AuthorizationDenied("Workshop browser changed during the bind")
        owner.require_universal_http_route("POST", "/api/universal/workshop-native",
            authentication_context=binding.context, revalidate=True)

    def read(sequence):
        return owner.conversation_content.page_for_workshop_browser(session_token, binding=binding,
            space_root=registry.workshop_root, limit=1, before=sequence + 1)

    guard()
    if type(body) is dict and body.get("action") == "read_work_proposals":
        return read_work_proposals(owner, binding, body)
    return bind_work_proposals(owner, binding, body, read_message=read, browser_guard=guard)


def read_work_proposals(owner, binding, body):
    """Which of the proposals the founder is shown are already bound, and to which Work.

    The founder's list reads its proposals from his own Workshop page; this read
    answers only the bound state, so a bound proposal is never offered again.
    """
    fields = {"action", "root", "scope", "request_id", "data_class", "message_ids"}
    if (type(body) is not dict or set(body) != fields or body["action"] != "read_work_proposals"
            or body["data_class"] != "public-text"
            or any(type(body[key]) is not str or not body[key] or len(body[key]) > 4096
                   for key in ("root", "scope", "request_id"))):
        _refuse("Reading Work proposals requires its exact request")
    ids = body["message_ids"]
    if (type(ids) is not list or not 0 < len(ids) <= 100
            or any(type(item) is not str or not _MESSAGE_ID.fullmatch(item) for item in ids)
            or len(set(ids)) != len(ids)):
        _refuse("Name 1 to 100 distinct proposal messages")
    store, registry = owner.universal_store, owner.universal_registry
    if binding.subject_root != registry.authorization.subject_root:
        raise AuthorizationDenied("Only the founder reads Work proposals for binding")
    host = getattr(owner, "_existing_workshop_native_host", None)
    if host is None:
        _refuse("Native Workshop owner is unavailable")
    with owner.mutation_lock:
        host._admit(binding, body["root"], body["scope"])
        snapshot = store.snapshot()
        works = _bound_works(snapshot, registry)
    return {"ok": True, "root": body["root"], "scope": body["scope"], "request_id": body["request_id"],
            "owner": binding.subject_root, "revision": snapshot.revision,
            "bound": {item: works.get(KEY_PREFIX + item) for item in ids}}


def bind_work_proposals(owner, binding, body, *, read_message, browser_guard):
    """The founder's one action: bind exactly the checked proposals, as the founder.

    read_message(sequence) returns the founder's own Workshop reader page ending at
    that sequence. The route supplies it with the founder's browser session, so a
    proposal is read as the founder sees it and never from the request body.
    """
    from . import universal_application as app
    from .existing_workshop_project_revision import configure_work_interfaces
    from .workshop_work_creation import create_browser_workshop_work

    fields = {"action", "root", "scope", "request_id", "data_class", "proposals"}
    if (type(body) is not dict or set(body) != fields or body["action"] != "bind_work_proposals"
            or body["data_class"] != "public-text"
            or any(type(body[key]) is not str or not body[key] or len(body[key]) > 4096
                   for key in ("root", "scope", "request_id"))):
        _refuse("Binding Work proposals requires its exact request")
    items = body["proposals"]
    if (type(items) is not list or not 0 < len(items) <= 16
            or any(type(item) is not dict or set(item) != {"message_id", "sequence", "digest"}
                   or type(item["message_id"]) is not str or not _MESSAGE_ID.fullmatch(item["message_id"])
                   or type(item["sequence"]) is not int or not 0 < item["sequence"] < 2 ** 62
                   or type(item["digest"]) is not str or not re.fullmatch("[0-9a-f]{64}", item["digest"])
                   for item in items)
            or len({item["message_id"] for item in items}) != len(items)):
        _refuse("Choose 1 to 16 distinct proposals, each with its message, sequence and digest")
    store, registry = owner.universal_store, owner.universal_registry
    founder = registry.authorization.subject_root
    if binding.subject_root != founder:
        raise AuthorizationDenied("Only the founder binds Work proposals")
    host = getattr(owner, "_existing_workshop_native_host", None)
    if host is None:
        _refuse("Native Workshop owner is unavailable")
    root, scope = body["root"], body["scope"]

    # 1. Read and check every chosen proposal before anything is created.
    prepared = []
    with owner.mutation_lock:
        host._admit(binding, root, scope)
        bound = _bound_keys(store.snapshot(), registry)
    for item in items:
        page = read_message(item["sequence"])
        messages = page.get("messages") if type(page) is dict else None
        message = messages[-1] if type(messages) is list and messages else None
        if (type(message) is not dict or message.get("id") != item["message_id"]
                or message.get("sequence") != item["sequence"]):
            _refuse("Proposal %s is not visible in this Workshop" % item["message_id"])
        author = message.get("author")
        if type(author) is not str or not author.startswith(_RUNTIME_SESSION):
            raise AuthorizationDenied("A Work proposal comes from an agent session")
        if app._runtime_agent_session(store.snapshot(), registry, author).subject_root != founder:
            raise AuthorizationDenied("A Work proposal comes from one of this founder's agent sessions")
        payload, digest = parse(message.get("content"))
        if digest != item["digest"]:
            _refuse("Proposal %s changed since it was shown; review it again" % item["message_id"])
        key = KEY_PREFIX + item["message_id"]
        if key in bound:
            _refuse("Proposal %s is already bound" % item["message_id"])
        if author in (payload["requirements"].get("artifact_reviewers") or ()):
            _refuse("The proposing agent cannot review its own proposed Work")
        prepared.append((item, author, payload, digest, key))

    # 2. Bind each, in order, through the browser's creation and the one configuration path.
    results = []
    for item, author, payload, digest, key in prepared:
        created = create_browser_workshop_work(owner, binding, {
            "workshop_root": root, "workshop_scope": scope, "revision": store.revision,
            "title": payload["title"], "description": payload["description"],
            "priority": payload["priority"], "external_key": key, "projection": False},
            browser_guard=browser_guard)
        work = created["created_root"]
        current = host._read_work_configuration(binding, root, scope, work, body["request_id"])
        values = {"inputs": payload["inputs"], "requirements": payload["requirements"],
                  "cde-container": cde_container(payload)}
        with owner.mutation_lock, registry.authorization.broker.live_context(binding.context):
            host._admit(binding, root, scope, work, work_action="edit")
            configured = configure_work_interfaces(owner, binding, root=root, scope=scope, work=work,
                revision_id=digest[:32], expected_revision=store.revision, purpose=payload["purpose"],
                fields={name: {"expected_target": current["fields"][name]["target"],
                               "expected_digest": current["fields"][name]["digest"], "value": value}
                        for name, value in values.items()},
                before_binding_commit=lambda: host._admit(binding, root, scope, work, work_action="edit"))
            host.invalidate_work_approval(work)
        results.append({"message_id": item["message_id"], "proposer": author, "digest": digest,
                        "work_root": work, "external_key": key,
                        "authorization": configured["record"] + ":authorization"})
    return {"ok": True, "root": root, "scope": scope, "request_id": body["request_id"],
            "owner": binding.subject_root, "bound": results, "revision": store.revision}
