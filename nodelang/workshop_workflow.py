"""Agent-proposed Workshop workflows: draft, user edit, approval, execution, review.

SPEC 3.4: an agent's reply is input, not the operation. The user turns a native
agent's proposal into editable graph nodes, wires and parameters through the
existing composer draft path, edits them with the ordinary property controls,
approves the exact behavior, then runs it. Approval is a graph property bound
to a digest of the members' engines, parameters and wires; any behavioral edit
invalidates it, layout does not. Execution reuses the canvas pipeline limited to
the approved members, and every agent effect is keyed to (workflow, approval,
node inputs), so a retry, a second run or a reopened application never relays
twice; two steps with the same agent and the same message are one send. SPEC 3.5: independent review keeps judged_by distinct from claimed_by;
a reviewer's reply is evidence, never a court pass.

The three Workshop node definitions below reconcile the clean-bootstrap
catalogue contracts (clean_runtime_bootstrap -> agent_session_catalogue /
coordination_workshop) into the one running catalogue. The clean bootstrap is
not started and its state is not copied: only the contract is mapped.
"""
from __future__ import annotations

import hashlib
import json
import re

from .cell_authorization import AuthorizationDenied
from .universal_cell import InvalidCell


WORKSHOP_CATALOGUE = {
    "w_workshop": {
        "engine": "workshop.conversation", "title": "Workshop",
        "sub": "this conversation; routes wired agents into it",
        "clean_definition": "Workshop",
        "clean_source": "clean_runtime_bootstrap.COMPOSITION_LABELS; coordination_workshop 'Coordination message'",
        "params": {"conversation": ""},
        "mapping": {"Coordination message.body/state": "ordinary indexed Workshop content (SPEC 3.4)"},
    },
    "w_agent": {
        "engine": "agent.session", "title": "Agent session",
        "sub": "one live native session through Session Link",
        "clean_definition": "Agent session state",
        "clean_source": "agent_session_catalogue.install_agent_session_catalogue",
        "params": {"agent": "", "message": ""},
        "mapping": {"runtime/provider": "bound contact endpoint app", "model": "the session's own model",
                    "status": "delivery state read from the Workshop receipts",
                    "identity": "the contact's exact native session binding"},
    },
    "w_review": {
        "engine": "workshop.review", "title": "Independent review",
        "sub": "a different agent reviews the wired artifact",
        "clean_definition": "Independent review",
        "clean_source": "coordination_workshop 'Independent review' (reviewer-not-builder)",
        "params": {"reviewer": ""},
        "mapping": {"decision": "verdict from the reviewer's own reply (pass/fail/unstated)",
                    "reviewer": "reviewer contact; must differ from the artifact's claimant"},
    },
}
WORKSHOP_ENGINES = frozenset(row["engine"] for row in WORKSHOP_CATALOGUE.values())
ACTIONS = frozenset({"workflow-draft", "workflow-approve", "workflow-execute", "artifact-review"})

_ANCHOR = "workshop-workflow"
_DRAFT_KEY = "workflow-draft:"
_REVIEW_KEY = "artifact-review:"
# Presentation the engines ignore; every other property is behavior and is approved.
_LAYOUT = frozenset({"position_x", "position_y", "color"})
_NOT_BEHAVIOR = _LAYOUT | {"status", "seed"}
_VERDICT = re.compile(r"^\s*VERDICT:\s*(pass|fail)\b", re.I)
_ARTIFACT_LIMIT = 5000


def approval_required(params, feeds):
    """The ungated canvas run never performs a Workshop effect."""
    raise ValueError("This node runs only inside an approved Workshop workflow; "
                     "approve it in the Workshop, then run it there.")


def _sha(*parts):
    return hashlib.sha256(json.dumps(parts, separators=(",", ":"), ensure_ascii=False,
                                     sort_keys=True).encode("utf-8")).hexdigest()


def _text(value, label, maximum=4096):
    if type(value) is not str or not value or len(value) > maximum or "\x00" in value:
        raise InvalidCell("%s must be exact bounded text" % label)
    return value


def _content(owner, browser, root, scope):
    """Admitted history for this browser, with its page audience."""
    from .existing_workshop_conversation import _admit
    registry, service = owner.universal_registry, owner.conversation_content
    if service is None or not service.belongs_to(owner.universal_store, registry):
        raise InvalidCell("The Workshop's indexed history is unavailable")
    snapshot, space = _admit(owner, browser, root, scope, allow_child=True)
    if browser.subject_root not in space.participant_roots:
        raise AuthorizationDenied("Only a participant of this conversation may act on its workflows")
    founder = browser.subject_root == registry.authorization.subject_root
    principal = registry.agent_body.session.root_id if founder else browser.subject_root
    binding = service._authorize_content_read(snapshot, registry, space_root=root,
        authentication_context=browser.context, principal=principal, machine=False)
    return service._history_for(binding), principal, founder, space


def _append(owner, browser, root, space, content, key, *, reply_to=None, refs=(), require_new=False):
    registry, store = owner.universal_registry, owner.universal_store
    tool = registry.workshop_category_roots.get("tool")
    category = tool if tool in space.category_roots else registry.workshop_category_roots["note"]
    return owner.conversation_content.append_authenticated(space_root=root,
        actor_root=browser.subject_root, category_root=category, content=content,
        idempotency_key=key, recipient_roots=(browser.subject_root,), reference_roots=tuple(refs),
        reply_to_root=reply_to, require_new=require_new, authentication_context=browser.context,
        expected_revision=store.revision)["message"]


def message_states(owner, history, root, message_ids, principal, read_all):
    """Delivery state for exact messages from their own receipts."""
    from .workshop_delivery_state import project_delivery, relay_pending_digests
    registry = owner.universal_registry
    rows = [history.get(root, message_id, principal=principal, read_all=read_all)
            for message_id in dict.fromkeys(message_ids)]
    rows = [row for row in rows if row is not None]
    if not rows:
        return {}, {}
    replies = history.replies_to(root, [row["id"] for row in rows], principal=principal,
                                 read_all=read_all)["messages"]
    return project_delivery(rows, replies, relay_pending=relay_pending_digests(owner),
        note_category=registry.workshop_category_roots["note"],
        tool_category=registry.workshop_category_roots.get("tool"),
        relay_author=registry.authorization.subject_root)


def _contacts(owner, browser, root, scope):
    from .native_contact import project_native_contacts
    return {row["root"]: row for row in project_native_contacts(owner, browser, root=root,
            scope=scope, discovery={})}


def _resolve_contact(value, contacts):
    """A proposal names an agent by contact root, app or exact title; one match only."""
    if type(value) is not str or not value.strip():
        return None
    value = value.strip()
    if value in contacts:
        return value
    matches = [root for root, row in contacts.items()
               if value.casefold() in (str(row["app"]).casefold(), str(row["label"]).casefold())]
    return matches[0] if len(matches) == 1 else None


def _extract_plan(text):
    """The first JSON object with an actions list in the agent's own reply."""
    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if "{" in text and "}" in text:
        candidates.append(text[text.index("{"):text.rindex("}") + 1])
    for candidate in candidates:
        try:
            plan = json.loads(candidate)
        except ValueError:
            continue
        if type(plan) is dict and type(plan.get("actions")) is list:
            if not 1 <= len(plan["actions"]) <= 12:
                raise InvalidCell("A workflow proposal holds 1 to 12 actions")
            return plan
    raise InvalidCell("This reply holds no workflow proposal (a JSON object with an actions list)")


def _resolve_actions(actions, contacts, root):
    """Bind agent names to exact contacts and give engine wires their pipeline ports."""
    resolved, issues, nodes = [], [], set()
    column = 0
    refused = sorted({str(action.get("op")) for action in actions
                      if type(action) is dict and action.get("op") not in ("node", "wire")})
    if refused or any(type(action) is not dict for action in actions):
        # Agent text may only add its own nodes and the wires between them; it
        # never selects, edits, groups or opens anything already on the canvas.
        raise InvalidCell("A workflow proposal may only add engine nodes and wires between them; "
                          "it also asked for: " + (", ".join(refused) or "a malformed action"))
    for action in actions:
        action = dict(action)
        if action.get("op") == "node":
            engine = action.get("engine")
            params = action.get("params", {})
            if type(params) is not dict or any(type(k) is not str or type(v) is not str
                                               for k, v in params.items()):
                raise InvalidCell("Workflow node parameters must map names to text")
            params = dict(params)
            if engine == "workshop.conversation":
                if params.get("conversation", "this") in ("", "this", root):
                    params["conversation"] = root
                else:
                    issues.append("Workshop node names another conversation")
            for name in ("agent", "reviewer"):
                if engine in ("agent.session", "workshop.review") and name in params:
                    contact = _resolve_contact(params[name], contacts)
                    if contact is None:
                        issues.append("%s %r is not one agent bound in this Workshop" % (name, params[name]))
                    else:
                        params[name] = contact
            action["params"] = params
            action.setdefault("x", 260.0 + 280.0 * column)
            action.setdefault("y", 240.0)
            column += 1
            if type(action.get("ref")) is str:
                nodes.add(action["ref"])
        elif action.get("op") == "wire":
            for key, side in (("source", "source_port"), ("target", "target_port")):
                endpoint = action.get(key)
                if type(endpoint) is not dict or set(endpoint) != {"ref"} or endpoint["ref"] not in nodes:
                    raise InvalidCell("A proposed wire may only join nodes this proposal adds")
                action.setdefault(side, "out" if key == "source" else "in")
        resolved.append(action)
    return resolved, issues


def _workflow_value(snapshot, anchor, root):
    cell = snapshot.cells.get(anchor)
    if cell is None:
        raise InvalidCell("That workflow is not in this graph")
    try:
        value = json.loads(cell.atom.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise InvalidCell("That node is not a Workshop workflow") from None
    if (type(value) is not dict or value.get("kind") != _ANCHOR or value.get("version") != 1
            or value.get("conversation") != root or type(value.get("members")) is not list):
        raise InvalidCell("That node is not a workflow of this conversation")
    return value


def workflow_state(owner, browser, root, anchor, *, projection=None):
    """Members, parameters, wires, current digest and approval, as the graph holds them."""
    from . import universal_application as app
    from .universal_pipeline import _owner_properties
    registry, store = owner.universal_registry, owner.universal_store
    snapshot = store.snapshot()
    value = _workflow_value(snapshot, anchor, root)
    members = list(value["members"])
    # The same property source run_universal_pipeline hands to each engine, so
    # the approved digest covers exactly what the run will receive.
    owned = _owner_properties(snapshot, registry)

    def properties(node):
        return dict(owned.get(node, {}))

    if projection is None:
        projection = app.project_universal_canvas(store, registry, authentication_context=browser.context)
    visible = {str(node["id"]): node for node in projection.get("nodes", ())}
    nodes, reason = [], None
    for node in members:
        held = properties(node)
        nodes.append({"root": node, "title": str((visible.get(node) or {}).get("label") or node),
            "engine": held.get("engine", ("", ""))[1],
            "params": {label: {"value": text, "relation": relation, "editable": label not in ("engine", "status")}
                       for label, (relation, text) in sorted(held.items()) if label not in _LAYOUT}})
        if node not in visible:
            reason = "Open the canvas that holds this workflow to review, approve or run it"
    wires = []
    for wire in projection.get("wires", ()):
        source, target = str(wire.get("source") or ""), str(wire.get("target") or "")
        if source in members and target in members:
            ports = {port.get("id"): port.get("name") for node in (visible.get(source), visible.get(target))
                     if node for port in node.get("ports", ())}
            wires.append([source, ports.get(wire.get("source_interface")), target,
                ports.get(wire.get("target_interface")),
                sorted((row.get("label"), str(row.get("value", ""))) for row in wire.get("params", ())
                       if row.get("label"))])
    behavior = [[node["root"], node["engine"], sorted((label, row["value"]) for label, row in node["params"].items()
                 if label not in _NOT_BEHAVIOR)] for node in nodes]
    digest = None if reason else _sha(anchor, root, behavior, sorted(wires))
    approval = None
    held = properties(anchor).get("approval")
    if held is not None:
        try:
            decided = json.loads(held[1])
            if decided.get("kind") != "workshop-workflow-approval" or decided.get("version") != 1:
                raise ValueError("not a workflow approval")
            approval = {"digest": decided["digest"], "approved_by": decided["approved_by"],
                        "revision": decided["revision"], "relation": held[0],
                        "current": digest is not None and decided["digest"] == digest}
        except (ValueError, KeyError, TypeError):
            approval = {"digest": None, "current": False, "relation": held[0], "invalid": True}
    return {"root": anchor, "title": value.get("title") or "Workflow", "conversation": root,
            "members": members, "nodes": nodes, "wires": len(wires), "digest": digest,
            "reason": reason, "approval": approval, "proposed_by": value.get("proposed_by"),
            "source_message": value.get("source_message")}


def draft_workflow(owner, browser, body, *, browser_guard):
    fields = {"action", "root", "scope", "message", "revision", "idempotency_key"}
    if type(body) is not dict or set(body) != fields or type(body["revision"]) is not int:
        raise InvalidCell("Workflow draft fields are invalid")
    root, scope = _text(body["root"], "Workshop"), _text(body["scope"], "canvas scope")
    message = _text(body["message"], "proposal message")
    key = _DRAFT_KEY + _sha(browser.subject_root, _text(body["idempotency_key"], "request identity", 128))
    from . import universal_application as app
    from .agent_composer import _apply_draft_actions, _validate_draft_references
    from .workshop_delivery_state import artifact_digest, relay_reply_record, relayed_reply_text
    registry, store = owner.universal_registry, owner.universal_store
    with owner.mutation_lock:
        browser_guard()
        history, principal, read_all, space = _content(owner, browser, root, scope)
        held = history.get_by_idempotency(root, key, principal=principal, read_all=read_all)
        if held is not None:
            value = json.loads(held["content"])
            if value.get("message") != message:
                raise InvalidCell("This draft request identity belongs to another proposal")
            return {"ok": True, "reused": True, **_draft_response(owner, browser, root, value)}
        if history.get_by_idempotency(root, key + ":reserved", principal=principal, read_all=read_all):
            raise InvalidCell("An earlier draft of this proposal was interrupted; its nodes may already be "
                              "on the canvas. Review them there instead of drafting again.")
        source = history.get(root, message, principal=principal, read_all=read_all)
        text = relayed_reply_text(source.get("content")) if source else None
        if text is None or not relay_reply_record(source, tool_category=registry.workshop_category_roots.get("tool"),
                                                  relay_author=registry.authorization.subject_root):
            raise InvalidCell("Choose an agent's relayed reply that holds a workflow proposal")
        proposer = source["refs"][0]
        plan = _extract_plan(text)
        if store.revision != body["revision"]:
            raise AuthorizationDenied("The Workshop changed; refresh before drafting this proposal")
        actions, issues = _resolve_actions(plan["actions"], _contacts(owner, browser, root, scope), root)
        projection = app.project_universal_canvas(store, registry, authentication_context=browser.context)
        _validate_draft_references(actions, projection)
        _append(owner, browser, root, space, "Workflow draft started from agent proposal %s." % message,
                key + ":reserved", reply_to=source["id"], require_new=True)
        applied = _apply_draft_actions(store, registry, projection, {"answer": str(plan.get("answer", ""))},
            actions, authentication_context=browser.context)
        members = [row["root"] for row in applied["applied"] if row.get("op") == "node" and row.get("ok")]
        issues += [str(row.get("why")) for row in applied["applied"] if not row.get("ok")]
        if not members:
            raise InvalidCell("The proposal placed no executable node: " + "; ".join(issues)[:500])
        title = str(plan.get("title") or plan.get("answer") or "Agent proposal")[:80]
        anchor_value = {"kind": _ANCHOR, "version": 1, "conversation": root, "scope": scope,
            "members": members, "proposed_by": proposer, "source_message": source["id"],
            "source_digest": artifact_digest(text), "title": title}
        anchor, _revision = app.instantiate_universal_primitive(store, registry,
            x=260.0, y=120.0, title="Workflow: " + title,
            atom=json.dumps(anchor_value, sort_keys=True, separators=(",", ":")),
            mutation_route="/api/universal/workshop", authentication_context=browser.context)
        value = {"kind": "workshop-workflow-draft", "version": 1, "workflow": anchor, "message": source["id"],
                 "proposed_by": proposer, "members": members, "issues": issues}
        _append(owner, browser, root, space, json.dumps(value, sort_keys=True, separators=(",", ":")), key,
                reply_to=source["id"], refs=(proposer, anchor))
        return {"ok": True, "reused": False, **_draft_response(owner, browser, root, value)}


def _draft_response(owner, browser, root, value):
    state = workflow_state(owner, browser, root, value["workflow"])
    return {"workflow": value["workflow"], "members": state["members"], "wires": state["wires"],
            "proposed_by": value["proposed_by"], "issues": value.get("issues", []),
            "digest": state["digest"], "approval": state["approval"], "revision": owner.universal_store.revision}


def approve_workflow(owner, browser, body, *, browser_guard):
    fields = {"action", "root", "scope", "workflow", "digest", "revision"}
    if type(body) is not dict or set(body) != fields or type(body["revision"]) is not int:
        raise InvalidCell("Workflow approval fields are invalid")
    root, scope = _text(body["root"], "Workshop"), _text(body["scope"], "canvas scope")
    anchor = _text(body["workflow"], "workflow")
    from . import universal_application as app
    registry, store = owner.universal_registry, owner.universal_store
    with owner.mutation_lock:
        browser_guard()
        _content(owner, browser, root, scope)
        if store.revision != body["revision"]:
            raise AuthorizationDenied("The Workshop changed; review the workflow again before approving")
        state = workflow_state(owner, browser, root, anchor)
        if state["digest"] is None:
            raise InvalidCell(state["reason"])
        if body["digest"] != state["digest"]:
            raise InvalidCell("The workflow changed since you reviewed it; review it again before approving")
        decision = json.dumps({"kind": "workshop-workflow-approval", "version": 1, "digest": state["digest"],
            "approved_by": browser.subject_root, "revision": store.revision},
            sort_keys=True, separators=(",", ":"))
        if state["approval"] is None:
            app.create_universal_property(store, registry, anchor, "approval", decision,
                authentication_context=browser.context)
        else:
            app.edit_universal_property(store, registry, state["approval"]["relation"], decision,
                mutation_route="/api/universal/workshop", authentication_context=browser.context)
        approved = workflow_state(owner, browser, root, anchor)
        return {"ok": True, "workflow": anchor, "digest": approved["digest"], "approval": approved["approval"],
                "revision": store.revision}


def execute_workflow(owner, browser, body, *, browser_guard):
    fields = {"action", "root", "scope", "workflow", "idempotency_key"}
    if type(body) is not dict or set(body) != fields:
        raise InvalidCell("Workflow run fields are invalid")
    root, scope = _text(body["root"], "Workshop"), _text(body["scope"], "canvas scope")
    anchor = _text(body["workflow"], "workflow")
    _text(body["idempotency_key"], "request identity", 128)
    from .universal_pipeline import run_universal_pipeline
    registry, store = owner.universal_registry, owner.universal_store
    with owner.mutation_lock:
        browser_guard()
        history, principal, read_all, space = _content(owner, browser, root, scope)
        state = workflow_state(owner, browser, root, anchor)
        if state["digest"] is None:
            raise InvalidCell(state["reason"])
        if state["approval"] is None:
            raise InvalidCell("Approve this workflow before it runs; an agent's proposal is not your approval")
        if not state["approval"]["current"]:
            raise InvalidCell("The workflow changed since approval; review and approve it again before it runs")
        if state["approval"].get("approved_by") not in space.participant_roots:
            raise AuthorizationDenied("The approval was not given by a participant of this conversation")
        digest = state["digest"]
        engines = {**dict(owner.pipeline_effect_engines or {}),
                   **_bound_engines(owner, browser, root=root, scope=scope, anchor=anchor, digest=digest,
                                    guard=browser_guard, history=history, principal=principal,
                                    read_all=read_all, space=space)}
        result = run_universal_pipeline(store, registry, effect_engines=engines,
            authentication_context=browser.context, only_roots=state["members"])
        record = {"kind": "workshop-workflow-run", "version": 1, "workflow": anchor, "approval": digest,
                  "display": result["display"], "pending": result["pending"]}
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":"))[:7000]
        try:
            _append(owner, browser, root, space, encoded,
                    "workflow-run:" + _sha(browser.subject_root, anchor, digest, result["display"], result["pending"]),
                    reply_to=state["source_message"], refs=(anchor,))
        except ValueError as exc:
            if str(exc) != "idempotency conflict":
                raise
        return {"ok": True, "workflow": anchor, "approval": digest, "ran": result["ran"],
                "display": result["display"], "pending": result["pending"], "revision": store.revision}


def _bound_engines(owner, browser, *, root, scope, anchor, digest, guard, history, principal, read_all, space):
    """The Workshop node engines, bound to this approved run and this browser."""
    from .native_contact import send_native_contact
    contacts = _contacts(owner, browser, root, scope)

    def label(contact):
        row = contacts.get(contact)
        return str(row["label"]) if row else str(contact)

    def conversation(params, feeds):
        if str(params.get("conversation", "")).strip() != root:
            raise ValueError("This Workshop node names another conversation; this run belongs to its own Workshop")
        return {"out": {"conversation": root}}, "Workshop · this conversation"

    def agent(params, feeds):
        upstream = feeds.get("in")
        if isinstance(upstream, dict) and upstream.get("conversation") not in (None, root):
            raise ValueError("The wired Workshop is another conversation")
        contact = str(params.get("agent", "")).strip()
        row = contacts.get(contact)
        if row is None:
            raise ValueError("Set agent to one native agent bound in this Workshop")
        message = str(params.get("message", "")).strip()
        if not message and isinstance(upstream, str):
            message = upstream.strip()
        if not message:
            raise ValueError("Set the message this agent should act on")
        text = "[ArchHub approved workflow step; workflow %s; approval %s]\n%s" % (anchor, digest[:12], message)
        sent = send_native_contact(owner, browser, {"root": root, "scope": scope, "contact": contact,
            "binding_digest": row["binding_digest"], "text": text,
            "idempotency_key": "workflow:" + _sha(anchor, digest, "agent.session", contact, message)[:64]},
            browser_guard=guard)
        states, relayed = message_states(owner, history, root, [sent["message_id"]], principal, read_all)
        entry = states.get(sent["message_id"], {"state": "stored", "delivery": []})
        rows = [item for item in entry["delivery"] if item["recipient"] == contact]
        state = rows[0]["state"] if rows else entry["state"]
        out = {"conversation": root, "agent": contact, "message_id": sent["message_id"], "state": state}
        reply = rows[0].get("reply_message_id") if rows else None
        if reply:
            out["reply_message_id"] = reply
            if reply in relayed:
                out["artifact_digest"] = relayed[reply]["artifact_digest"]
        return {"out": out}, "%s · %s" % (state, label(contact))

    def review(params, feeds):
        upstream = feeds.get("in")
        reviewer = str(params.get("reviewer", "")).strip()
        if not isinstance(upstream, dict) or not upstream.get("agent"):
            raise ValueError("Wire an Agent session node into this review")
        if upstream.get("state") != "replied" or not upstream.get("reply_message_id"):
            raise ValueError("Waiting for the artifact: %s has not replied (%s); run the approved "
                             "workflow again after its reply" % (label(upstream["agent"]), upstream.get("state")))
        result = request_artifact_review(owner, browser, root=root, scope=scope,
            artifact=upstream["reply_message_id"], reviewer=reviewer, guard=guard, workflow=anchor,
            idempotency_key="workflow-review:" + _sha(anchor, digest, reviewer, upstream["reply_message_id"])[:64])
        verdict = (" · verdict " + result["verdict"]) if result.get("verdict") else ""
        return {"out": result}, "%s · review by %s%s" % (result["state"], label(reviewer), verdict)

    return {"workshop.conversation": conversation, "agent.session": agent, "workshop.review": review}


def request_artifact_review(owner, browser, *, root, scope, artifact, reviewer, idempotency_key, guard,
                            workflow=None):
    """Ask a different agent to review one relayed artifact; exactly once per request identity."""
    from .native_contact import send_native_contact
    from .workshop_delivery_state import artifact_digest, relay_reply_record, relayed_reply_text
    registry = owner.universal_registry
    key = _REVIEW_KEY + _sha(browser.subject_root, idempotency_key)
    with owner.mutation_lock:
        guard()
        history, principal, read_all, space = _content(owner, browser, root, scope)
        source = history.get(root, artifact, principal=principal, read_all=read_all)
        text = relayed_reply_text(source.get("content")) if source else None
        if text is None or not relay_reply_record(source, tool_category=registry.workshop_category_roots.get("tool"),
                                                  relay_author=registry.authorization.subject_root):
            raise InvalidCell("Choose an agent's relayed reply as the artifact to review")
        claimant = source["refs"][0]
        contacts = _contacts(owner, browser, root, scope)
        target = contacts.get(reviewer)
        if target is None:
            raise InvalidCell("The reviewer must be one native agent bound in this Workshop")
        producer = contacts.get(claimant)
        produced_by = _native_identity(owner, owner.universal_store.snapshot(), claimant, contacts)
        judged = (target["app"], hashlib.sha256(target["session_id"].encode("utf-8")).hexdigest())
        if reviewer == claimant or produced_by == judged:
            raise AuthorizationDenied("Independent review requires a different agent: judged_by must "
                                      "differ from claimed_by")
        if produced_by is None:
            raise AuthorizationDenied("The artifact's producing session cannot be identified, so an "
                                      "independent reviewer cannot be proven different (judged_by vs claimed_by)")
        digest = artifact_digest(text)
        held = history.get_by_idempotency(root, key, principal=principal, read_all=read_all)
        if held is not None:
            value = json.loads(held["content"])
            if (value.get("artifact_message"), value.get("judged_by")) != (artifact, reviewer):
                raise InvalidCell("This review request identity belongs to another review")
            return _review_projection(owner, history, root, principal, read_all, value, held["id"])
        excerpt = text if len(text) <= _ARTIFACT_LIMIT else text[:_ARTIFACT_LIMIT] + "\n[truncated]"
        prompt = ("[ArchHub independent review request; artifact sha256 %s produced by %s]\n"
                  "Review the artifact below as an independent reviewer. Reply with a first line of exactly "
                  "'VERDICT: pass' or 'VERDICT: fail', then your findings. Your reply is review evidence; it is "
                  "not a court pass and grants no execution authority.\n\n--- artifact ---\n%s"
                  % (digest, producer["label"] if producer else claimant, excerpt))
        sent = send_native_contact(owner, browser, {"root": root, "scope": scope, "contact": reviewer,
            "binding_digest": target["binding_digest"], "text": prompt,
            "idempotency_key": "review-request:" + _sha(key)[:64]}, browser_guard=guard)
        value = {"kind": "artifact-review", "version": 1, "artifact_message": artifact, "artifact_digest": digest,
                 "claimed_by": claimant, "judged_by": reviewer, "request_message": sent["message_id"],
                 "workflow": workflow}
        record = _append(owner, browser, root, space, json.dumps(value, sort_keys=True, separators=(",", ":")),
                         key, reply_to=artifact, refs=(claimant, reviewer))
        return _review_projection(owner, history, root, principal, read_all, value, record["id"])


def _native_identity(owner, snapshot, root, contacts):
    """(app, sha256 of the native session id) of an artifact's producer, or None."""
    row = contacts.get(root)
    if row is not None:
        return (row["app"], hashlib.sha256(row["session_id"].encode("utf-8")).hexdigest())
    if root.startswith("app:agent-session:runtime:"):
        from .application_server import _NATIVE_RELAY_APPS
        with owner._machine_agent_session_lock:
            binding = dict(owner._machine_agent_sessions.get(root) or {})
        app = "codex" if binding.get("runtime") == "codex" else _NATIVE_RELAY_APPS.get(binding.get("runtime"))
        fingerprint = binding.get("external_session_fingerprint")
        return (app, fingerprint) if app and type(fingerprint) is str else None
    cell = snapshot.cells.get(root)
    try:
        endpoint = json.loads(cell.atom.decode("utf-8"))["endpoint"]
        return (endpoint["app"], hashlib.sha256(endpoint["id"].encode("utf-8")).hexdigest())
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeDecodeError):
        return None


def _review_projection(owner, history, root, principal, read_all, value, record_id, states=None, relayed=None):
    from .workshop_delivery_state import relayed_reply_text
    request = value["request_message"]
    if states is None or request not in states:
        states, relayed = message_states(owner, history, root, [request], principal, read_all)
    entry = states.get(request, {"state": "stored", "delivery": []})
    rows = [row for row in entry["delivery"] if row["recipient"] == value["judged_by"]]
    state = rows[0]["state"] if rows else entry["state"]
    verdict, review_message = None, None
    if rows and rows[0].get("reply_message_id"):
        review_message = rows[0]["reply_message_id"]
        reply = (relayed or {}).get(review_message)
        text = reply["agent_text"] if reply else None
        if text is None:
            row = history.get(root, review_message, principal=principal, read_all=read_all)
            text = relayed_reply_text(row.get("content")) if row else None
        found = _VERDICT.match(text or "")
        verdict = found.group(1).lower() if found else "unstated"
    return {"review": record_id, "artifact_message": value["artifact_message"],
            "artifact_digest": value["artifact_digest"], "claimed_by": value["claimed_by"],
            "judged_by": value["judged_by"], "request_message": request, "state": state,
            "verdict": verdict, "review_message": review_message, "workflow": value.get("workflow")}


def review_artifact(owner, browser, body, *, browser_guard):
    fields = {"action", "root", "scope", "artifact", "reviewer", "idempotency_key"}
    if type(body) is not dict or set(body) != fields:
        raise InvalidCell("Artifact review fields are invalid")
    result = request_artifact_review(owner, browser, root=_text(body["root"], "Workshop"),
        scope=_text(body["scope"], "canvas scope"), artifact=_text(body["artifact"], "artifact"),
        reviewer=_text(body["reviewer"], "reviewer"),
        idempotency_key=_text(body["idempotency_key"], "request identity", 128), guard=browser_guard)
    return {"ok": True, **result, "revision": owner.universal_store.revision}


def perform_workshop_action(owner, browser, body, *, browser_guard):
    action = body.get("action") if type(body) is dict else None
    function = {"workflow-draft": draft_workflow, "workflow-approve": approve_workflow,
                "workflow-execute": execute_workflow, "artifact-review": review_artifact}.get(action)
    if function is None or not callable(browser_guard):
        raise InvalidCell("Unknown Workshop workflow action")
    return function(owner, browser, body, browser_guard=browser_guard)


def project_workshop_extras(owner, browser, *, root, rows, history, principal, read_all, states, relayed):
    """Reviews and workflows referenced by this page's records; nothing else is scanned."""
    reviews, anchors = [], []
    for row in rows:
        key = str(row.get("idempotency_key") or "")
        if row.get("author") != browser.subject_root or not (key.startswith(_REVIEW_KEY) or key.startswith(_DRAFT_KEY)):
            continue
        if key.endswith(":reserved"):
            continue
        try:
            value = json.loads(row["content"])
        except ValueError:
            continue
        if key.startswith(_REVIEW_KEY) and type(value) is dict and value.get("kind") == "artifact-review":
            if not any(item["review"] == row["id"] for item in reviews):
                reviews.append(_review_projection(owner, history, root, principal, read_all, value, row["id"],
                                                  states, relayed))
        elif type(value) is dict and value.get("kind") == "workshop-workflow-draft":
            if value.get("workflow") not in anchors:
                anchors.append(value["workflow"])
    workflows = []
    if anchors:
        from . import universal_application as app
        projection = app.project_universal_canvas(owner.universal_store, owner.universal_registry,
            authentication_context=browser.context)
        for anchor in anchors[:8]:
            try:
                workflows.append(workflow_state(owner, browser, root, anchor, projection=projection))
            except InvalidCell:
                continue
    return {"reviews": reviews, "workflows": workflows}


__all__ = ["ACTIONS", "WORKSHOP_CATALOGUE", "WORKSHOP_ENGINES", "approval_required",
           "message_states", "perform_workshop_action", "project_workshop_extras",
           "request_artifact_review", "workflow_state"]
