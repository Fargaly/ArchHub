"""Session-hook integration over the existing catalogue, router and broker."""
import json
import urllib.request
from pathlib import Path

from . import model_catalogue as catalogue, model_router as router
from .model_execution_broker import ModelExecutionBroker, ApplicationOpenRouterCredentialResolver


def brains(*, opener=urllib.request.urlopen, timeout=6):
    """Live inventory, with availability distinct from installed/login evidence."""
    rows = [{"name": "claude", "route": None, "callable": True, "state": "session default"}]
    errors = []
    providers = router.provider_rows()
    keyed = {r["id"] for r in providers if r["state"] == "keyed"}
    groups = catalogue.live_model_groups(opener=opener, timeout=timeout, force=True)
    for group in groups["groups"]:
        for item in group["items"]:
            route = item["route"]
            if route.startswith("local-cli/"):
                continue
            if item.get("tag") == "BYO":
                if not route.endswith(":free") or "tools" not in item.get("supported_parameters", []):
                    continue
                route = "openrouter/" + route
                ready = "openrouter" in keyed
            else:
                ready = True
            rows.append({"name": route, "route": route, "callable": ready,
                         "state": "detected" if ready else "no key"})
    errors.extend(groups.get("source_errors", {}).keys())
    # Discovery extends the app catalogue; provider execution stays in route_chat.
    for family, prefix, url, header in (
        ("google", "gemini/", catalogue.GOOGLE_MODELS + "?pageSize=1000", "x-goog-api-key"),
        ("nvidia", "nvidia/", "https://integrate.api.nvidia.com/v1/models", "Authorization"),
        ("openai", "openai/", catalogue.OPENAI_MODELS, "Authorization"),
    ):
        if family not in keyed:
            continue
        try:
            key, _ = router.discover_key(family)
            value = key if header == "x-goog-api-key" else "Bearer " + key
            data = catalogue._get_json(url, headers={header: value}, timeout=timeout, opener=opener)
            for item in data.get("models" if family == "google" else "data", []):
                model = str(item.get("name" if family == "google" else "id", ""))
                if family == "google":
                    if "generateContent" not in item.get("supportedGenerationMethods", []):
                        continue
                    model = model.removeprefix("models/")
                if model:
                    if not catalogue._text_chat_id(family, model):
                        continue
                    rows.append({"name": prefix + model,
                                 "route": {"google": "google-api/", "nvidia": "nvidia-api/", "openai": "openai-api/"}[family] + model,
                                 "callable": True, "state": "detected; key present; chat compatibility unverified",
                                 "paid": family == "openai"})
        except Exception:
            errors.append(family + " catalogue unavailable")
    for provider in providers:
        name = provider["id"]
        if name not in {"codex", "copilot", "opencode", "gemini-cli", "antigravity"}:
            continue
        if provider["state"] == "not installed":
            continue
        callable_ = name != "antigravity"
        rows.append({"name": name, "route": "local-cli/" + {"gemini-cli": "gemini"}.get(name, name),
                     "callable": callable_, "state": provider["state"] + "; login/quota unverified" if callable_ else "not callable yet"})
    return {"brains": rows, "notes": errors}


def answer(request, *, workspace, chat=None, secrets_loader=None):
    """One step; caller supplies canonical chat rows and function declarations."""
    if not isinstance(request, dict) or not isinstance(request.get("brain"), str):
        raise ValueError("Invalid brain request")
    from .library_engines import LIBRARY_ITEM_ENGINES
    from .universal_application import _APPLICATION_SETTING_SPECS
    parameters = request.get('parameters', {})
    if type(parameters) is not dict:
        raise ValueError('Model parameters must be an object')
    route = request["brain"]
    destination = router.resolve_model_route(route)
    key = 'model_cli_request_ms' if destination.family == 'local-cli' else 'model_request_ms'
    value = parameters.get(key, LIBRARY_ITEM_ENGINES['tool_workshop']['params'][key])
    bounds = _APPLICATION_SETTING_SPECS[key][1]
    if type(value) is not int or not bounds['min'] <= value <= bounds['max']:
        raise ValueError('Model request duration is outside its node bounds')
    paid = request.get("paid") is True
    if destination.family == "openai" and not paid:
        raise ValueError("This brain requires --paid")
    if destination.family == "openrouter" and not destination.model.endswith(":free") and not paid:
        raise ValueError("This brain requires --paid")
    if chat is None and destination.family == "local-cli":
        router.bind_local_cli_broker(ModelExecutionBroker(
            workspace_root=Path(workspace),
            credential_resolver=ApplicationOpenRouterCredentialResolver()))
    tools = request.get("tools", [])
    messages = request.get("messages")
    if destination.family == "local-cli":
        latest = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        # The session's rules and memory live in the system rows; keep them whole, trim only the conversation.
        rules = "\n\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "system")
        excerpt = "\n".join(str(m.get("role")) + ": " + str(m.get("content", "")) for m in messages if m.get("role") != "system")
        messages = [{"role": "system", "content": "You are continuing the user's Claude Code session in its place. "
                     "Obey every rule, restriction and memory below exactly as that session must (language, tone, forbidden actions). "
                     "Never invent tool output or errors; if you did not run something, say so.\n\n"
                     + ("READ-ONLY (the session is in plan mode): read and search only; do not create, edit or delete files "
                        "and run no command that changes anything.\n\n" if (request.get("session") or {}).get("access") == "read" else "")
                     + rules[-50000:] + "\n\nRecent conversation:\n" + excerpt[-16000:]},
                    {"role": "user", "content": latest}]
    session = request.get("session") if isinstance(request.get("session"), dict) else None
    effort = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}.get(
        str((session or {}).get("effort") or "medium"), "medium")
    extra = {"local_cli_session": session} if session and destination.family == "local-cli" else {}
    result = (chat or router.route_chat)(
        route, messages, tools=tools if destination.family != "local-cli" else None,
        free_only=destination.family == "openrouter" and not paid,
        # the session's effort only where route_chat admits one (OpenRouter); Gemini refuses it (model_router:2530)
        reasoning_effort=effort if destination.family == "openrouter" else None,
        max_tokens=4096, timeout=value / 1000,
        response_byte_limit=1024 * 1024, **extra,
    )
    names = {t["function"]["name"] for t in tools}
    calls = []
    for call in result.get("tool_calls", []):
        if call.get("name") not in names:
            raise ValueError("Provider returned an unknown tool")
        args = call.get("arguments", {})
        args = json.loads(args) if isinstance(args, str) else args
        if not isinstance(args, dict):
            raise ValueError("Provider returned invalid tool arguments")
        calls.append({"id": str(call["id"]), "name": call["name"], "input": args})
    output = {"text": router.redact_user_visible(result.get("text", "")), "tools": calls,
              "model": result.get("actual_model", result.get("model", destination.model))}
    encoded = json.dumps(output, ensure_ascii=True)
    for family in ("openrouter", "google", "nvidia", "openai"):
        try:
            key, _ = router.discover_key(family, secrets_loader=secrets_loader)
        except router.ModelRouteRefused:
            continue
        if key:
            encoded = encoded.replace(json.dumps(key, ensure_ascii=True)[1:-1], "[redacted]")
    return json.loads(encoded)
