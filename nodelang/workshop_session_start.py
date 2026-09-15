"""Start a saved conversation through the existing Workshop, composer and relay."""
import hashlib
import json

from . import universal_application as app
from .cell_authorization import AuthorizationDenied
from .model_router import ModelRouteRefused, resolve_model_route
from .universal_cell import InvalidCell
from .workshop_conversation_catalog import create_workshop_conversation, validate_workshop_conversation_scope


def _turn_history(owner, browser, conversation, prefix, guard):
    registry, store, service = owner.universal_registry, owner.universal_store, owner.conversation_content

    def history():
        guard()
        binding = service._authorize_content_read(store.snapshot(), registry, space_root=conversation,
            authentication_context=browser.context, principal=browser.subject_root, machine=False)
        return service._history_for(binding)

    def append(text, suffix, *, category="tool", refs=(), reply_to=None, require_new=False):
        with owner.mutation_lock:
            guard()
            return service.append_authenticated(space_root=conversation, actor_root=browser.subject_root,
                category_root=registry.workshop_category_roots[category], content=text,
                idempotency_key=prefix + suffix, recipient_roots=(browser.subject_root,),
                reference_roots=refs, reply_to_root=reply_to, require_new=require_new,
                authentication_context=browser.context, expected_revision=store.revision)["message"]

    def lookup(suffix):
        with owner.mutation_lock:
            return history().get_by_idempotency(conversation, prefix + suffix, principal=browser.subject_root)

    def context(before):
        with owner.mutation_lock:
            page = history().page(conversation, principal=browser.subject_root,
                limit=24, before=before, max_bytes=24_000)
            rows = [{"author":row["author"], "content":row["content"]} for row in page["messages"]
                if row["category"] == registry.workshop_category_roots["note"]
                or (row["category"] == registry.workshop_category_roots["tool"]
                    and row["idempotency_key"].endswith(":reply")
                    and row["content"].startswith("Model reply from "))]
            return json.dumps(rows, ensure_ascii=False, separators=(",", ":")) if rows else None
    return append, lookup, context


def _append_user(registry, browser, prompt, reference, append, lookup):
    try:
        return append(prompt, ":user", category="note", refs=(reference,))
    except ValueError as exc:
        if str(exc) != "idempotency conflict":
            raise
        user = lookup(":user")
        if (user is None or user["content"] != prompt or user["refs"] != [reference]
                or user["author"] != browser.subject_root
                or user["category"] != registry.workshop_category_roots["note"]
                or user["recipients"] != [browser.subject_root] or user["reply_to"] is not None
                or user["evidence"]):
            raise InvalidCell("The saved message differs from this exact session request") from None
        return user


def project_workshop_model_agent(owner, browser, root, scope):
    """Project the actual visible child Agent; an identity never grants access."""
    from .existing_workshop_conversation import _admit
    from .agent_composer import resolve_node_model_route
    from .cell_protocols import read_relation
    with owner.mutation_lock:
        snapshot, _ = _admit(owner, browser, root, scope, allow_child=True)
        registry, store = owner.universal_registry, owner.universal_store
        if root == registry.workshop_root:
            return None
        validate_workshop_conversation_scope(snapshot, registry.deliberation_protocol,
            application_root=registry.application_root, canonical_root=registry.workshop_root, root=root)
        token = hashlib.sha256((root + ":agent").encode()).hexdigest()
        node = "assembly-instance:" + token
        view, _ = app._view_session_for_context(registry, browser.context)
        visible, _, _ = app._session_canvas_roots(snapshot, registry, view)
        if node not in visible:
            return None
        lens_roots = tuple(member.participant_id for member in read_relation(
            snapshot, view.properties_lens_root, budget=100_000)
            if member.role_id == registry.roles["scope"])
        rows = app._property_index(snapshot, registry, lens_roots).get(node, ())
        conversation_rows = [row for row in rows if app._text(snapshot, row.label_root) == "conversation"]
        if len(conversation_rows) != 1 or app._text(snapshot, conversation_rows[0].value_root) != root:
            return None
        try:
            route = resolve_node_model_route(store, registry,
                {"nodes":[{"id":item} for item in visible], "revision":snapshot.revision},
                node, authentication_context=browser.context)
        except InvalidCell:
            return None
        digest = hashlib.sha256(json.dumps([registry.application_root, root, scope,
            node, route, browser.subject_root], separators=(",", ":")).encode()).hexdigest()
        return {"root":node, "model":route, "binding_digest":digest}


def _current_model_agent(owner, browser, root, scope):
    try:
        return project_workshop_model_agent(owner, browser, root, scope)
    except (InvalidCell, AuthorizationDenied):
        return None


def start_workshop_session(owner, browser, body, *, browser_guard):
    fields = {"prompt", "idempotency_key"}
    if type(body) is not dict or set(body) not in (fields | {"model"}, fields | {"native"}):
        raise InvalidCell("Choose one model or native session for the new conversation")
    prompt, key = body["prompt"], body["idempotency_key"]
    if (type(prompt) is not str or not prompt.strip() or "\x00" in prompt
            or len(prompt.encode("utf-8")) > 16_000 or type(key) is not str
            or not 1 <= len(key) <= 128 or "\x00" in key):
        raise InvalidCell("A bounded prompt and exact request identity are required")
    app.validate_universal_workshop_entry_content(prompt)
    native = body.get("native")
    if native is not None:
        from .native_contact import APPS
        if (type(native) is not dict or set(native) != {"app", "session_id"}
                or any(type(value) is not str or not value for value in native.values())
                or native["app"] not in APPS or len(native["session_id"]) > 512):
            raise InvalidCell("Choose one exact native session")
        route = None
        chosen = {"native": native}
    else:
        route = body.get("model")
        if type(route) is not str or not route.strip() or route != route.strip():
            raise InvalidCell("Choose an exact model route")
        resolve_model_route(route)
        chosen = {"model": route}
    registry, store, service = owner.universal_registry, owner.universal_store, owner.conversation_content
    prefix = "home-session:" + hashlib.sha256(key.encode()).hexdigest()
    intent = hashlib.sha256(json.dumps({"prompt": prompt, **chosen},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def guard():
        browser_guard()
        owner.require_universal_http_route("POST", "/api/universal/agent" if route else
            "/api/universal/native-contact", authentication_context=browser.context, revalidate=True)

    with owner.mutation_lock:
        guard()
        # This existing graph metadata reader performs no transport discovery.
        from .native_contact import workshop_metadata
        navigation = workshop_metadata(owner, browser.context)
        created = create_workshop_conversation(owner, authentication_context=browser.context,
            expected_revision=store.revision, title=prompt.strip()[:80],
            participant_roots=(browser.subject_root,), idempotency_key=prefix,
            before_commit=guard)
        conversation = created["root"]

    append, lookup, context = _turn_history(owner, browser, conversation, prefix, guard)

    def response(user, state, **extra):
        return {"ok": True, "graph_id": registry.application_root, "root": conversation,
            "title": created["title"], "message_id": user["id"], "idempotency_key": key,
            "revision": store.revision, "scope_path": navigation["scope_path"],
            "scope": registry.workshop_workbench_root,
            "model_agent":_current_model_agent(owner, browser, conversation, registry.workshop_workbench_root),
            **({"node":extra["node"]} if extra.get("node") else {}),
            **({"contact":extra["contact"]} if extra.get("contact") else {}),
            "delivery": {"state": state, **extra}}

    # Bind retry intent in the same ordinary history, not a sidecar request ledger.
    intent_text = "Session request " + intent
    held_intent = lookup(":intent")
    if held_intent is not None and held_intent["content"] != intent_text:
        raise InvalidCell("This session request changed; use a new request identity")
    append(intent_text, ":intent")
    previous_user = lookup(":user")
    if lookup(":started") is not None:
        if previous_user is None:
            raise InvalidCell("The saved session receipt has no user message")
        reply = lookup(":reply")
        return response(previous_user, "replied" if reply is not None else "already_recorded",
            **({"reply_message_id":reply["id"], "node":previous_user["refs"][0]} if reply else {}))

    # A refused retry must not navigate away from the user's current canvas.
    with owner.mutation_lock:
        guard()
        canvas = app.project_universal_canvas(store, registry, authentication_context=browser.context)
        if canvas["scope"]["current"] != registry.canvas_root:
            app.set_universal_scope(store, registry, registry.canvas_root,
                projected_canvas=canvas, authentication_context=browser.context)
        for root in navigation["scope_path"]:
            app.set_universal_scope(store, registry, root, authentication_context=browser.context)

    if route:
        from .universal_pipeline import create_engine_node
        # The already-published child identity reserves this node identity before
        # placement. Atomic initial properties make a partial retry unambiguous.
        node_token = hashlib.sha256((conversation + ":agent").encode()).hexdigest()
        with owner.mutation_lock:
            guard()
            node = create_engine_node(store, registry, title="Agent: " + created["title"][:60],
                engine="library.think", properties={"model":route, "conversation":conversation},
                instance_token=node_token, authentication_context=browser.context)["root"]
        reference = node
    else:
        from .native_contact import bind_native_contact
        contact = bind_native_contact(owner, browser, {"root":conversation,
            "scope":registry.workshop_workbench_root, "node":None, **native,
            "revision":store.revision}, browser_guard=guard)
        reference = contact["contact"]
    user = _append_user(registry, browser, prompt, reference, append, lookup)
    if not route:
        # Native relay owns its durable dispatch receipt for this same message.
        from .native_contact import send_native_contact
        delivered = send_native_contact(owner, browser, {"root":conversation,
            "scope":registry.workshop_workbench_root, "contact":contact["contact"],
            "binding_digest":contact["binding_digest"], "text":prompt,
            "idempotency_key":prefix + ":user"}, browser_guard=guard)
        delivery = delivered["delivery"]
        return response(user, delivery.get("state", delivery.get("status", "unknown")),
            relay=delivery, contact=contact["contact"], execution_authority=False)
    expected = project_workshop_model_agent(owner, browser, conversation, registry.workshop_workbench_root)
    return _dispatch_model_turn(owner, browser, conversation, registry.workshop_workbench_root,
        prompt, node, route, expected, user, append, context, guard, response)


def _dispatch_model_turn(owner, browser, conversation, scope, prompt, node, route,
                         expected, user, append, context, guard, response):
    from .agent_composer import run_agent_composer, resolve_node_model_route
    registry, store = owner.universal_registry, owner.universal_store
    dispatched = False

    def binding_guard():
        guard()
        current = _current_model_agent(owner, browser, conversation, scope)
        if expected is None or current != expected:
            raise InvalidCell("The conversation Agent binding changed or is not visible; refresh its selection")

    def before_dispatch():
        nonlocal dispatched
        with owner.mutation_lock:
            binding_guard()
            projection = app.project_universal_canvas(store, registry, authentication_context=browser.context)
            resolve_node_model_route(store, registry, projection, node, model=route,
                authentication_context=browser.context)
            append("The agent request started. An unrecorded outcome is unknown and is not retried automatically.",
                ":started", reply_to=user["id"], require_new=True)
            dispatched = True

    try:
        with owner.mutation_lock:
            binding_guard()
            app.project_universal_canvas(store, registry, authentication_context=browser.context)
            conversation_context = context(user["sequence"])
        result = run_agent_composer(store, registry, prompt, model=route, node_root=node,
            authentication_context=browser.context, mutation_lock=owner.mutation_lock,
            revalidate=binding_guard, before_dispatch=before_dispatch,
            conversation_context=conversation_context)
        applied = result.get("applied", [])
        draft_text = ""
        if applied:
            draft_text = "\n\nDraft prepared for your review; no workflow execution was approved or run:\n" + "\n".join(
                "- %s: %s%s" % (row.get("op", "draft"),
                    "prepared" if row.get("ok") else "needs attention",
                    (" (" + str(row["root"]) + ")") if row.get("root") else "")
                for row in applied)
        draft_roots = tuple(dict.fromkeys((node, *(row["root"] for row in applied if row.get("root")))))
        reply = append("Model reply from %s:\n%s%s" % (route, result.get("answer", ""), draft_text),
            ":reply", refs=draft_roots, reply_to=user["id"])
        return response(user, "replied", reply_message_id=reply["id"], model=route,
            node=node, applied=result.get("applied", []))
    except AuthorizationDenied:
        raise
    except (ModelRouteRefused, InvalidCell) as exc:
        if not dispatched:
            return response(user, "not_sent", reason=getattr(exc, "reason_code", "admission_refused"),
                message=str(exc), provider_not_called=True, model=route, node=node)
        append("The model did not return an admitted reply. Its outcome is not retried automatically.",
            ":failure", refs=(node,), reply_to=user["id"])
        return response(user, "failed", reason="model_reply_unavailable", model=route, node=node)
    except Exception:
        if not dispatched:
            return response(user, "not_sent", reason="preparation_failed", provider_not_called=True,
                message="The model request could not be prepared. Your prompt is saved.", model=route, node=node)
        append("The model did not return an admitted reply. Its outcome is not retried automatically.",
            ":failure", refs=(node,), reply_to=user["id"])
        return response(user, "failed", reason="model_reply_unavailable", model=route, node=node)


def send_workshop_model_message(owner, browser, body, *, browser_guard):
    fields = {"root", "scope", "node", "binding_digest", "prompt", "idempotency_key"}
    if type(body) is not dict or set(body) != fields or any(type(value) is not str or not value for value in body.values()):
        raise InvalidCell("Model conversation send requires one exact child and Agent binding")
    if (len(body["prompt"].encode("utf-8")) > 16_000 or not 1 <= len(body["idempotency_key"]) <= 128
            or "\x00" in body["idempotency_key"] or len(body["binding_digest"]) != 64):
        raise InvalidCell("Model conversation request exceeds its bounded interface")
    app.validate_universal_workshop_entry_content(body["prompt"])
    from .existing_workshop_conversation import _admit
    registry, store = owner.universal_registry, owner.universal_store
    root, scope, node = body["root"], body["scope"], body["node"]

    def guard():
        browser_guard()
        owner.require_universal_http_route("POST", "/api/universal/agent",
            authentication_context=browser.context, revalidate=True)

    with owner.mutation_lock:
        guard()
        _admit(owner, browser, root, scope, allow_child=True)
        if root == registry.workshop_root:
            raise InvalidCell("Choose a model conversation before sending to its Agent")
    prefix = "model-turn:" + hashlib.sha256(body["idempotency_key"].encode()).hexdigest()
    append, lookup, context = _turn_history(owner, browser, root, prefix, guard)
    intent_text = "Model conversation request " + hashlib.sha256(json.dumps(body,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    held = lookup(":intent")
    if held is not None and held["content"] != intent_text:
        raise InvalidCell("This model message changed; use a new request identity")

    def response(user, state, **extra):
        return {"ok":True, "graph_id":registry.application_root, "root":root, "scope":scope,
            "scope_root":scope, "node":node, "binding_digest":body["binding_digest"],
            "model_agent":_current_model_agent(owner, browser, root, scope),
            "message_id":user["id"], "idempotency_key":body["idempotency_key"],
            "revision":store.revision, "delivery":{"state":state, **extra}}

    if lookup(":started") is not None:
        user, reply = lookup(":user"), lookup(":reply")
        if user is None or user["content"] != body["prompt"] or user["refs"] != [node]:
            raise InvalidCell("The saved model request has no matching user message")
        return response(user, "replied" if reply else "already_recorded",
            **({"reply_message_id":reply["id"], "node":node} if reply else {}))
    expected = project_workshop_model_agent(owner, browser, root, scope)
    if expected is None or expected["root"] != node or expected["binding_digest"] != body["binding_digest"]:
        raise InvalidCell("The conversation Agent binding changed or is not visible; refresh its selection")
    append(intent_text, ":intent")
    user = _append_user(registry, browser, body["prompt"], node, append, lookup)
    return _dispatch_model_turn(owner, browser, root, scope, body["prompt"], node,
        expected["model"], expected, user, append, context, guard, response)
