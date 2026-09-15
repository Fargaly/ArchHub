"""Text conversation through an admitted AI instance in the existing clean graph.

No store, session, graph mutation, workflow execution or transcript owner is
created here. The browser server must supply fresh session/CSRF admission.
"""
from __future__ import annotations

from .model_router import ModelRouteRefused, route_chat
from .unified_authority import read_instance, read_instance_definition, read_scope_level
from .universal_cell import InvalidCell


_SYSTEM = (
    "You are the AI node in ArchHub. Answer the user's message as plain text. "
    "This conversation call returns text only: it cannot change the graph, run "
    "a workflow, operate tools, or complete effects. Never claim those actions "
    "happened. If asked for a workflow, propose its steps for review and state "
    "that the graph has not been changed."
)


def resolve_clean_node_model_route(authority, caller, projection, node_root, *, scope_root, model=None):
    """Read the visible instance's pinned definition and effective model value."""
    if type(node_root) is not str or not node_root.strip():
        raise InvalidCell("Select an AI node on the canvas to ask.")
    if (projection.get("root") != scope_root or
            sum(node.get("id") == node_root for node in projection.get("nodes", ())) != 1):
        raise InvalidCell("agent node is not visible in this canvas scope")
    revision = authority.store.revision
    if projection.get("revision") != revision:
        raise InvalidCell("canvas changed while resolving the agent model")
    level = read_scope_level(authority, scope_root, scope_root=scope_root, caller=caller)
    if node_root not in level.instances:
        raise InvalidCell("agent node is not a visible instance in this scope")
    definition = read_instance_definition(authority, node_root, scope_root=scope_root, caller=caller)
    if (definition.lifecycle != "published" or
            definition.contracts.get("rules", {}).get("engine") != "ai.master" or
            "model" not in definition.contracts.get("parameters", {})):
        raise InvalidCell("agent node does not declare the released AI model capability")
    instance = read_instance(authority, node_root, scope_root=scope_root, caller=caller)
    values = instance["values"]
    chosen = values.get("model")
    if type(chosen) is not str or not chosen.strip() or chosen.strip() == "provider-selected":
        raise InvalidCell("No model chosen for this agent node. Set its model parameter first.")
    chosen = chosen.strip()
    if model is not None and (type(model) is not str or model.strip() != chosen):
        raise InvalidCell("requested model differs from the agent node model; update its parameter first")
    if authority.store.revision != revision:
        raise InvalidCell("canvas changed while resolving the agent model")
    return {"node": node_root, "scope": scope_root, "model": chosen, "revision": revision,
            "definition_revision": definition.revision_root,
            "action": values.get("action"), "prompt": values.get("prompt", "")}


def run_clean_agent_conversation(owner, binding, body, *, revalidate):
    """Resolve under the owner lock, call the provider outside it, re-admit reply."""
    if type(body) is not dict or set(body) - {"node", "prompt", "model", "expected_scope"}:
        raise InvalidCell("agent conversation fields are invalid")
    prompt = body.get("prompt")
    if type(prompt) is not str or not prompt.strip() or len(prompt.encode("utf-8")) > 32768:
        raise InvalidCell("agent prompt must be non-empty text of at most 32768 bytes")
    if not callable(revalidate):
        raise InvalidCell("agent conversation requires fresh browser admission")
    def resolve():
        scope = owner._standing_scope(binding, expected_scope=body.get("expected_scope"))
        return resolve_clean_node_model_route(owner.clean_authority, owner.clean_caller,
            owner._canvas(binding, scope_root=scope), body.get("node"), scope_root=scope,
            model=body.get("model"))
    with owner._mutation_lock:
        revalidate()
        admitted = resolve()
    if admitted["action"] not in ("converse", "think"):
        raise InvalidCell("this text conversation supports the AI node's converse or think action")
    instruction = admitted["prompt"]
    if type(instruction) is not str or len(instruction.encode("utf-8")) > 16384:
        raise InvalidCell("agent node prompt must be text of at most 16384 bytes")
    try:
        routed = route_chat(admitted["model"], [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (instruction + "\n\n" if instruction else "") + prompt.strip()},
        ], max_tokens=900, temperature=0, response_byte_limit=262144,
            free_only=admitted["model"] == "openrouter/free" or admitted["model"].endswith(":free"))
    except ModelRouteRefused:
        raise
    except Exception:
        return {"ok": False, "error": "The model provider did not answer.",
            "error_code": "provider_unavailable", "node": admitted["node"], "applied": []}
    result = {"ok": True, "answer": routed["text"], "node": admitted["node"],
        "model": admitted["model"], "actual_model": routed.get("actual_model"),
        "provider": routed.get("provider"), "family": routed.get("family"),
        "scope_root": admitted["scope"], "source_revision": admitted["revision"],
        "applied": [], "execution_requested": False}
    with owner._mutation_lock:
        revalidate()
        try:
            current = resolve()
            changed = any(current[key] != admitted[key]
                for key in ("node", "scope", "model", "definition_revision", "action", "prompt"))
        except InvalidCell:
            changed = True
    if changed:
        result.pop("answer", None)
        result.update(ok=False, error_code="agent_binding_changed",
            error="The agent binding changed while its reply was pending. Retry with the current node.")
    return result
