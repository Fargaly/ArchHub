"""Core node types for the graph-first architecture (ADR-003 Phase 4).

Three families register here:

  • host.*         — AEC application connectors (Revit/AutoCAD/Blender/...)
  • conversation.* — chat nodes carrying message history + LLM params
  • doc.*          — opened documents inside a host (Revit model, DWG, IFC)

Phase 1 used stubs; Phase 4 wires real adapters under `app/connectors/`
+ `app/*_broker.py`. Stubs remain as graceful fallbacks when the
adapter is unavailable (no Revit running, pywin32 missing, no LLM
key) so unit tests + offline edits keep working.

The return shapes are still pinned — Phase 4 ADD richer fields but
NEVER drops the original envelope keys.
"""
from __future__ import annotations

import csv as _csv
import io as _io
import json as _json
from pathlib import Path as _Path
from typing import Any

from ..graph import Port, PortType
from ..registry import NodeSpec, register


# ===========================================================================
# 1. Host nodes (7 variants)
# ===========================================================================
#
# A Host node represents one AEC application. Its parameters declare which
# *version* of that host (Revit 2024 vs 2025). Its body carries the bridge
# session state — current document, last action, port number.
#
# Inputs are typed actions ("open file", "select wall types", "save"). Each
# Host has an EXEC input port so a Trigger/Cron node can fire actions on a
# schedule. Outputs carry the live state: opened document, current selection,
# warning count.
#
# The seven concrete types share one executor implementation parameterised by
# host family — DRY without losing per-host UX surface.

_HOST_FAMILIES = (
    ("revit",    "Revit",        "▲", "BIM authoring + documentation"),
    ("autocad",  "AutoCAD",      "◇", "2D drafting + 3D modelling"),
    ("blender",  "Blender",      "◈", "DCC + scripting + Python addons"),
    ("rhino",    "Rhino",        "◐", "NURBS modelling + Grasshopper"),
    ("max",      "3ds Max",      "◑", "Visualisation + rendering"),
    ("speckle",  "Speckle",      "⌬", "BIM data exchange + streams"),
    ("outlook",  "Outlook",      "✉", "Email + calendar + tasks"),
)


# ---------------------------------------------------------------------------
# Host adapter dispatch helpers
# ---------------------------------------------------------------------------

def _broker_host_info(family: str) -> dict:
    """Resolve live host session info for the broker-style families
    (revit/autocad/max/outlook). Returns:

        {alive, port, version, opened_doc, selection, warnings, reason}

    `alive=False` + `reason="missing_dep"` when the module can't import;
    `alive=False` + `reason="unavailable"` when import works but no
    session is reachable.
    """
    module_map = {
        "revit":   "revit_broker",
        "autocad": "acad_broker",
        "max":     "max_broker",
        "outlook": "outlook_broker",
    }
    mod_name = module_map.get(family)
    if mod_name is None:
        return {"alive": False, "reason": "unsupported"}
    try:
        broker = __import__(mod_name)
    except Exception as ex:
        return {"alive": False, "reason": "missing_dep",
                "error": f"{type(ex).__name__}: {ex}"}
    try:
        session = broker.pick_session()
    except Exception as ex:
        return {"alive": False, "reason": "unavailable",
                "error": f"{type(ex).__name__}: {ex}"}
    if session is None:
        return {"alive": False, "reason": "unavailable",
                "error": f"No {family} session running"}
    info: dict[str, Any] = {
        "alive":   True,
        "port":    getattr(session, "port", 0),
        "version": getattr(session, "version", "") or "",
        "session_id": getattr(session, "session_id", ""),
        "opened_doc": getattr(session, "doc_title", "") or None,
        "selection": [],
        "warnings": [],
    }
    # Best-effort /info probe — pull live doc + selection counts. If
    # the endpoint isn't implemented (legacy DLL) the broker returns
    # status="error", which we silently absorb.
    try:
        probe = broker.forward(session, "/info", timeout=2.0)
        if isinstance(probe, dict) and probe.get("status") != "error":
            info["opened_doc"] = (probe.get("doc_title")
                                   or probe.get("opened_doc")
                                   or info["opened_doc"])
            sel = probe.get("selection") or []
            if isinstance(sel, list):
                info["selection"] = sel
            warns = probe.get("warnings") or []
            if isinstance(warns, list):
                info["warnings"] = warns
            if probe.get("version"):
                info["version"] = probe["version"]
    except Exception:
        pass
    return info


def _runner_host_info(family: str) -> dict:
    """Resolve live host info for the connector-style families
    (blender/rhino) which expose a single HTTP listener via their
    `connectors/<family>_runner.py` module.
    """
    try:
        if family == "blender":
            from connectors import blender_runner as runner  # type: ignore
        elif family == "rhino":
            from connectors import rhino_runner as runner   # type: ignore
        else:
            return {"alive": False, "reason": "unsupported"}
    except Exception as ex:
        return {"alive": False, "reason": "missing_dep",
                "error": f"{type(ex).__name__}: {ex}"}

    # Both runners expose ping() and info(). ping returns dict|None.
    try:
        pong = runner.ping()
    except Exception as ex:
        return {"alive": False, "reason": "unavailable",
                "error": f"{type(ex).__name__}: {ex}"}
    if not pong or (isinstance(pong, dict)
                     and pong.get("status") == "error"):
        return {"alive": False, "reason": "unavailable",
                "error": (isinstance(pong, dict)
                          and pong.get("error")) or
                         f"No {family} bridge responding"}
    info_data: dict[str, Any] = {}
    try:
        info_data = runner.info() or {}
    except Exception:
        info_data = {}
    return {
        "alive":     True,
        "port":      getattr(runner, "CONNECTOR_PORT_DEFAULT", 0),
        "version":   str(info_data.get("version") or pong.get("version") or ""),
        "opened_doc": (info_data.get("filepath")
                        or info_data.get("doc_path")
                        or info_data.get("filename")
                        or None),
        "selection": list(info_data.get("selection") or []),
        "warnings":  list(info_data.get("warnings") or []),
    }


def _outlook_host_info() -> dict:
    """Outlook is special — no listener, COM-only. Use the connectors
    runner directly for the heartbeat."""
    try:
        from connectors import outlook_runner  # type: ignore
    except Exception as ex:
        return {"alive": False, "reason": "missing_dep",
                "error": f"{type(ex).__name__}: {ex}"}
    try:
        if not outlook_runner.is_reachable():
            return {"alive": False, "reason": "unavailable",
                    "error": "Outlook not running or pywin32 missing"}
        snap = outlook_runner.info() or {}
    except Exception as ex:
        return {"alive": False, "reason": "unavailable",
                "error": f"{type(ex).__name__}: {ex}"}
    return {
        "alive":     True,
        "port":      0,
        "version":   "",
        "opened_doc": snap.get("default_account_email") or None,
        "selection": [],
        "warnings":  [],
        "extra":     {k: v for k, v in snap.items()
                      if k not in ("status",)},
    }


def _speckle_host_info() -> dict:
    """Speckle is a cloud service — no local session. We just ask
    whether the SpeckleClient can be constructed (which doesn't talk
    to the server yet) and surface that as 'alive=True'. Real reach-
    ability is checked when an action posts a dispatch."""
    try:
        from speckle_client import SpeckleClient  # type: ignore
        client = SpeckleClient()
    except Exception as ex:
        return {"alive": False, "reason": "missing_dep",
                "error": f"{type(ex).__name__}: {ex}"}
    return {
        "alive":     True,
        "port":      0,
        "version":   "",
        "opened_doc": None,
        "selection": [],
        "warnings":  [],
        "client":    client,
    }


def _dispatch_host_action(family: str, action: str, inputs: dict,
                           info: dict) -> dict:
    """Route a typed action to the matching adapter.

    Returns a dict with `dispatched: bool` + adapter-specific fields.
    On adapter-missing / unreachable: dispatched=False + reason.
    """
    if not info.get("alive"):
        return {"dispatched": False, "reason": info.get("reason", "")}

    a = (action or "").strip().lower()
    if not a:
        return {"dispatched": False, "reason": "no_action"}

    # ---- broker-driven families (revit/autocad/max) -----------------
    if family in ("revit", "autocad", "max"):
        try:
            broker = __import__(
                {"revit": "revit_broker",
                 "autocad": "acad_broker",
                 "max": "max_broker"}[family]
            )
            # Prefer a session already pinned by version (set by
            # _host_exec via info["_pinned_session"]).
            session = info.get("_pinned_session") if isinstance(info, dict) else None
            if session is None:
                session = broker.pick_session()
        except Exception as ex:
            return {"dispatched": False,
                    "reason": f"broker_failed: {ex}"}
        if session is None:
            return {"dispatched": False, "reason": "no_session"}
        body = _json.dumps(inputs or {}).encode("utf-8")
        path = "/" + a.replace(" ", "_")
        # If a document was supplied, append it to the path as
        # ?doc=<title> so adapters that support it can narrow.
        doc_q = inputs.get("doc") if isinstance(inputs, dict) else None
        if doc_q:
            from urllib.parse import quote as _q
            path = f"{path}?doc={_q(str(doc_q))}"
        try:
            res = broker.forward(session, path, body=body,
                                  method="POST", timeout=10.0)
        except Exception as ex:
            return {"dispatched": False,
                    "reason": f"forward_failed: {ex}"}
        return {"dispatched": True, "result": res,
                "session_id": getattr(session, "session_id", "")}

    # ---- runner-driven families (blender/rhino) ---------------------
    if family in ("blender", "rhino"):
        try:
            if family == "blender":
                from connectors import blender_runner as runner  # type: ignore
            else:
                from connectors import rhino_runner as runner   # type: ignore
        except Exception as ex:
            return {"dispatched": False,
                    "reason": f"missing_dep: {ex}"}
        # Map a couple of common actions; everything else falls
        # through to execute() with a one-liner Python snippet.
        try:
            if a in ("ping", "heartbeat"):
                return {"dispatched": True, "result": runner.ping()}
            if a in ("info", "session", "session_info"):
                return {"dispatched": True, "result": runner.info()}
            if a in ("open", "open_document"):
                path = (inputs.get("path") or "").strip()
                if hasattr(runner, "open_document"):
                    return {"dispatched": True,
                            "result": runner.open_document(path)}
                code = (f"import bpy; bpy.ops.wm.open_mainfile("
                         f"filepath={path!r})")
                return {"dispatched": True,
                        "result": runner.execute(code)}
            # Generic — let the adapter dispatch if it can.
            if hasattr(runner, "dispatch"):
                return {"dispatched": True,
                        "result": runner.dispatch(a, **(inputs or {}))}
            # Last-ditch: just return info so the wire still carries data.
            return {"dispatched": True,
                    "result": runner.info(),
                    "note": f"no handler for action '{a}'"}
        except Exception as ex:
            return {"dispatched": False,
                    "reason": f"adapter_failed: {ex}"}

    # ---- outlook ----------------------------------------------------
    if family == "outlook":
        try:
            from connectors import outlook_runner  # type: ignore
        except Exception as ex:
            return {"dispatched": False,
                    "reason": f"missing_dep: {ex}"}
        try:
            if hasattr(outlook_runner, "outlook_dispatch"):
                res = outlook_runner.outlook_dispatch(action=a,
                                                       **(inputs or {}))
            elif a in ("list", "folders", "list_folders"):
                res = outlook_runner.list_folders()
            elif a in ("search", "find"):
                res = outlook_runner.search(
                    query=inputs.get("query", ""),
                    sender=inputs.get("sender", ""),
                    subject_contains=inputs.get("subject_contains", ""),
                    days=int(inputs.get("days", 0) or 0),
                    limit=int(inputs.get("limit", 30) or 30),
                )
            elif a in ("inbox", "list_inbox"):
                res = outlook_runner.list_inbox(
                    limit=int(inputs.get("limit", 20) or 20),
                    unread_only=bool(inputs.get("unread_only", False)),
                )
            else:
                res = outlook_runner.list_folders()
            return {"dispatched": True, "result": res}
        except Exception as ex:
            return {"dispatched": False,
                    "reason": f"outlook_failed: {ex}"}

    # ---- speckle ----------------------------------------------------
    if family == "speckle":
        try:
            from speckle_client import SpeckleClient  # type: ignore
        except Exception as ex:
            return {"dispatched": False,
                    "reason": f"missing_dep: {ex}"}
        try:
            client = SpeckleClient()
            res = client.dispatch(a, dict(inputs or {}))
            return {"dispatched": True, "result": res}
        except Exception as ex:
            return {"dispatched": False,
                    "reason": f"speckle_failed: {ex}"}

    return {"dispatched": False, "reason": "unhandled_family"}


def _pick_session_by_version(family: str, version_filter: str):
    """Pick a broker session matching `version_filter`. Returns the
    session object (broker dataclass) or None when no match. When the
    filter is empty we fall back to broker.pick_session() (most-recent
    healthy).

    Used by _host_exec to honour the founder direction (2026-05-14):
    'host tools should allow for specific version connection.'
    """
    mod_map = {"revit": "revit_broker",
                "autocad": "acad_broker",
                "max":     "max_broker"}
    if family not in mod_map:
        return None
    try:
        broker = __import__(mod_map[family])
    except Exception:
        return None
    if not (version_filter or "").strip():
        try:
            return broker.pick_session()
        except Exception:
            return None
    needle = str(version_filter).strip().lower()
    try:
        sessions = broker.list_sessions(prune=False) or []
    except Exception:
        sessions = []
    for s in sessions:
        if not getattr(s, "healthy", False):
            continue
        sv = str(getattr(s, "version", "") or "").lower()
        sid = str(getattr(s, "session_id", "") or "").lower()
        if needle and (needle == sv or needle in sv or needle in sid):
            return s
    return None


def _host_exec(config: dict, inputs: dict, ctx) -> dict:
    """Probe the matching host adapter + (if action) dispatch it.

    Always returns a typed envelope so downstream nodes can pin shape
    regardless of adapter availability. When the adapter is missing
    or unreachable, `host_alive` is False + `state` carries the
    reason; `status` stays "ok" so the workflow doesn't abort.

    `status="missing_dep"` is reserved for the catastrophic case where
    the adapter MODULE itself fails to import (truly unrecoverable).

    Honours config.version (pick the matching live session) and
    config.document (narrow commands to that doc).
    """
    family = config.get("_family") or config.get("family") or "revit"
    version_cfg = (config.get("version") or "").strip()
    document_cfg = (config.get("document") or "").strip()
    action = (inputs.get("action") or "").strip()

    # 1. Resolve host info — narrowed by version when supplied.
    if family == "outlook":
        info = _outlook_host_info()
    elif family == "speckle":
        info = _speckle_host_info()
    elif family in ("revit", "autocad", "max"):
        if version_cfg:
            # Try to pin to the session matching this version. Falls
            # back to default _broker_host_info if no match found.
            pinned = _pick_session_by_version(family, version_cfg)
            if pinned is not None:
                info = {
                    "alive":   True,
                    "port":    getattr(pinned, "port", 0),
                    "version": getattr(pinned, "version", "") or "",
                    "session_id": getattr(pinned, "session_id", ""),
                    "opened_doc": getattr(pinned, "doc_title", "") or None,
                    "selection": [],
                    "warnings": [],
                    "_pinned_session": pinned,
                }
            else:
                info = _broker_host_info(family)
                if info.get("alive"):
                    # Surface that we asked for a specific version
                    # but couldn't find it.
                    info["version_mismatch"] = version_cfg
        else:
            info = _broker_host_info(family)
    elif family in ("blender", "rhino"):
        info = _runner_host_info(family)
    else:
        info = {"alive": False, "reason": "unsupported"}

    # If a document was requested, narrow inputs so dispatch routes there.
    if document_cfg:
        inputs = dict(inputs or {})
        # Pass through both common shapes adapters expect.
        inputs.setdefault("doc", document_cfg)
        inputs.setdefault("document", document_cfg)

    # 2. Dispatch action if one was supplied.
    dispatch_result: dict = {}
    if action:
        dispatch_result = _dispatch_host_action(family, action, inputs, info)

    # 3. Compose envelope.
    alive = bool(info.get("alive"))
    reason = info.get("reason", "")
    status = "ok"
    if not alive and reason == "missing_dep":
        # Catastrophic: surface as missing_dep so the user sees a clear
        # install hint upstream.
        status = "missing_dep"

    if not action:
        state = "idle" if alive else (reason or "unavailable")
    elif dispatch_result.get("dispatched"):
        state = f"action: {action}"
    else:
        state = (f"action: {action} ({dispatch_result.get('reason', 'failed')})"
                 if reason != "missing_dep" else (reason or "missing_dep"))

    out = {
        "status":       status,
        "family":       family,
        "version":      info.get("version") or version_cfg,
        "opened_doc":   info.get("opened_doc")
                          or (config.get("default_doc") or None),
        "selection":    list(info.get("selection") or []),
        "state":        state,
        "tool_calls":   [dispatch_result] if dispatch_result else [],
        "host_alive":   alive,
        "port":         info.get("port", 0),
        "warnings":     list(info.get("warnings") or []),
        "after":        None,        # exec pins don't carry data
    }
    if status == "missing_dep":
        out["reason"] = info.get("error") or reason
        out["hint"]   = (f"Install or open {family} to enable this node. "
                          f"({reason})")
    return out


def _register_host_node(family: str, name: str, icon: str,
                         description: str) -> None:
    """Register one host.{family} type with the registry."""
    register(
        NodeSpec(
            type=f"host.{family}",
            category="host",
            display_name=name,
            description=description,
            inputs=[
                Port(name="action",  type=PortType.STRING,
                      description=f"Action to invoke on {name}"),
                Port(name="trigger", type=PortType.EXEC, exec=True,
                      description="Fire on incoming execution signal"),
            ],
            outputs=[
                Port(name="opened_doc",  type=PortType.DOCUMENT,
                      description="Currently-active document"),
                Port(name="selection",   type=PortType.SELECTION,
                      description="Current host selection"),
                Port(name="state",       type=PortType.STRING,
                      description="Bridge / session state"),
                Port(name="after",       type=PortType.EXEC, exec=True,
                      description="Fires after action completes"),
            ],
            config_schema={
                "_family":     {"type": "string", "default": family,
                                "hidden": True},
                # Dynamic — JS picker fetches options live from
                # bridge.list_host_sessions(family). Stored value is
                # the chosen version string (e.g. "2025"). When empty,
                # the runner picks the most-recent healthy session.
                "version":     {"type": "string", "default": "",
                                "enum": "<dynamic>",
                                "source": "list_host_sessions",
                                "source_args": [family],
                                "description": (
                                    f"Pick which running instance of {name} "
                                    f"to connect to. Refreshes live."
                                )},
                # Dynamic — JS picker fetches via
                # bridge.list_host_documents(family, session_id).
                # Stored value is the document title/path; runner
                # narrows commands to that doc.
                "document":    {"type": "string", "default": "",
                                "enum": "<dynamic>",
                                "source": "list_host_documents",
                                "source_args": [family],
                                "depends_on": ["version"],
                                "description": (
                                    f"Pick which open document inside "
                                    f"the selected {name} session."
                                )},
                "default_doc": {"type": "string", "default": "",
                                "description": "Document to open on activate"},
                "auto_run":    {"type": "boolean", "default": False,
                                "description": "Re-execute on upstream param change"},
            },
            icon=icon,
        ),
        _host_exec,
    )


for _family, _name, _icon, _desc in _HOST_FAMILIES:
    _register_host_node(_family, _name, _icon, _desc)


# ===========================================================================
# 2. Conversation node — chat as a node
# ===========================================================================
#
# Body carries the list of chat turns. Params declare model, system prompt,
# temperature, max tokens. Inputs accept upstream context (a Document's
# contents, a previous Conversation's response, an extracted intent). Outputs
# emit the assistant's response, an extracted intent string (for downstream
# Logic nodes), and the full tool_trace dict.
#
# Phase 4 wires the executor to `ctx.router.complete(...)` (LLMRouter) when
# a router is in scope; falls back to the deterministic stub when there's no
# context (unit tests, offline editing, no provider keys).

def _conversation_exec(config: dict, inputs: dict, ctx) -> dict:
    """Append the user turn + LLM response to the conversation body.

    Path A — `ctx.router` available (production WorkflowExecutor):
        Build history from body.messages + the new prompt, call the
        router, append the assistant turn back.

    Path B — `ctx is None` or no router (unit tests, simple
    WorkflowRunner): fall back to a deterministic stub so the shape
    contract holds and tests are stable.

    Path C — router raises (no key, blocked, refused):
        status="missing_dep" + helpful provider hint.
    """
    prompt = (inputs.get("prompt") or "").strip()
    if not prompt:
        return {"status": "error", "error": "prompt required",
                "response": "", "intent": "", "tool_trace": [],
                "messages": [], "conversation": [], "after": None}

    body = config.get("body") or {"messages": []}
    if isinstance(body, dict):
        msgs = list(body.get("messages") or [])
    else:
        msgs = []
    model = config.get("model") or "auto"
    system_cfg = inputs.get("system") or config.get("system") or ""

    # Path A: real router in scope.
    router = getattr(ctx, "router", None) if ctx is not None else None
    if router is not None and hasattr(router, "complete"):
        # LLMRouter.complete signature: complete(history, model, on_chunk,
        # on_tool_invocation, on_reasoning?, on_status?, session_pin?)
        history: list[dict] = []
        if system_cfg:
            history.append({"role": "system_override",
                             "content": str(system_cfg)})
        history.extend(msgs)
        history.append({"role": "user", "content": prompt})
        invocations: list[dict] = []

        def _on_inv(inv):
            try:
                invocations.append(inv.to_dict()
                                    if hasattr(inv, "to_dict") else dict(inv))
            except Exception:
                invocations.append({"raw": repr(inv)[:200]})

        try:
            response = router.complete(
                history=history,
                model=model,
                on_chunk=lambda _piece: None,
                on_tool_invocation=_on_inv,
            )
        except Exception as ex:
            # No key / blocked / refused — fall through to missing_dep
            # with the best hint we can derive.
            try:
                blocked = router.blocked_providers() or {}
            except Exception:
                blocked = {}
            try:
                configured = router.configured_providers() or []
            except Exception:
                configured = []
            return {
                "status":      "missing_dep",
                "response":    "",
                "intent":      "",
                "tool_trace":  [],
                "messages":    msgs,
                "conversation": msgs,
                "reason":      f"{type(ex).__name__}: {ex}",
                "hint": (
                    f"LLM provider unavailable. Configured: {configured or 'none'}; "
                    f"blocked: {dict(blocked) or 'none'}. Add a provider key in "
                    f"Settings or start Ollama."
                ),
                "after":       None,
            }

        response_text = getattr(response, "text", "") or ""
        appended = msgs + [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": response_text},
        ]
        return {
            "status":       "ok",
            "response":     response_text,
            "intent":       prompt.split()[0].lower() if prompt else "",
            "tool_trace":   invocations,
            "messages":     appended,
            "conversation": appended,
            "model":        getattr(response, "model", model),
            "after":        None,
        }

    # Path B: no router — deterministic stub keeps the shape contract.
    response_text = f"[stub-{model}] {prompt[:80]}"
    appended = msgs + [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": response_text},
    ]
    return {
        "status":       "ok",
        "response":     response_text,
        "intent":       prompt.split()[0].lower() if prompt else "",
        "tool_trace":   [],
        "messages":     appended,
        "conversation": appended,
        "after":        None,
    }


register(
    NodeSpec(
        type="conversation.chat",
        category="ai",
        display_name="Conversation",
        description="A chat thread with the LLM. Body carries the turns.",
        inputs=[
            Port(name="prompt",  type=PortType.STRING, required=True,
                  description="User turn to append"),
            Port(name="context", type=PortType.ANY, multiple=True,
                  description="Upstream context (docs, intents, results)"),
            Port(name="system",  type=PortType.STRING,
                  description="System prompt override"),
            Port(name="trigger", type=PortType.EXEC, exec=True),
        ],
        outputs=[
            Port(name="response",    type=PortType.COMPLETION,
                  description="Latest assistant response"),
            Port(name="intent",      type=PortType.INTENT,
                  description="Extracted intent for Logic routing"),
            Port(name="tool_trace",  type=PortType.LIST,
                  description="Tool calls invoked during this turn"),
            Port(name="conversation", type=PortType.CONVERSATION,
                  description="Full thread (for downstream Conversation nodes)"),
            Port(name="after",       type=PortType.EXEC, exec=True),
        ],
        config_schema={
            "model":       {"type": "string", "default": "auto",
                            "description": "Router model id (auto = best per task)"},
            "system":      {"type": "string", "default": "",
                            "description": "System prompt"},
            "temperature": {"type": "number", "default": 0.7,
                            "min": 0.0, "max": 2.0},
            "max_tokens":  {"type": "number", "default": 4096},
            "auto_run":    {"type": "boolean", "default": False},
        },
        icon="✦",
    ),
    _conversation_exec,
)


# ===========================================================================
# 3. Document nodes (8 variants)
# ===========================================================================
#
# A Document node points at a file inside a host. Params declare path +
# version. Body caches last-read contents. Inputs accept edits (host-typed).
# Outputs emit contents, selection (subset of the doc's elements), warnings.
#
# Multi-document graphs are the unlock: two doc.revit nodes side-by-side
# + a doc.csv input + a Conversation tying them together = "import the
# schedule, compare against both Revit models, draft the discrepancy
# email" — all in ONE graph.

_DOC_FAMILIES = (
    ("revit",   "Revit Model",   "▣", PortType.DOCUMENT, ".rvt"),
    ("dwg",     "DWG Drawing",   "◇", PortType.DOCUMENT, ".dwg"),
    ("ifc",     "IFC Model",     "◰", PortType.IFC,      ".ifc"),
    ("blender", "Blender Scene", "◈", PortType.DOCUMENT, ".blend"),
    ("3dm",     "Rhino 3DM",     "◐", PortType.DOCUMENT, ".3dm"),
    ("max",     "3ds Max Scene", "◑", PortType.DOCUMENT, ".max"),
    ("csv",     "CSV Data",      "≡", PortType.CSV,      ".csv"),
    ("pdf",     "PDF Document",  "◫", PortType.FILE,     ".pdf"),
)


# ---------------------------------------------------------------------------
# Document adapter helpers
# ---------------------------------------------------------------------------

# Map doc family → host family so we can ask the live host for metadata
# about the open document.
_DOC_TO_HOST = {
    "revit":   "revit",
    "dwg":     "autocad",
    "blender": "blender",
    "3dm":     "rhino",
    "max":     "max",
}


def _doc_from_host(family: str, path: str) -> dict:
    """Ask the matching host adapter for live document metadata.

    Returns {alive, contents, selection, warnings, current_view, ...}.
    `alive=False` when the host isn't running — caller falls back to
    the offline envelope.
    """
    host_family = _DOC_TO_HOST.get(family)
    if host_family is None:
        return {"alive": False}
    if host_family == "outlook":
        return {"alive": False}
    if host_family in ("revit", "autocad", "max"):
        info = _broker_host_info(host_family)
    elif host_family in ("blender", "rhino"):
        info = _runner_host_info(host_family)
    else:
        info = {"alive": False}
    if not info.get("alive"):
        return {"alive": False, "reason": info.get("reason", "")}

    # Best-effort live read. We DO NOT auto-open the file — the host
    # node owns open semantics — but we DO surface the currently-open
    # document if it matches `path` (or no path was given).
    opened = info.get("opened_doc") or ""
    matches = (not path) or (path and str(opened).lower().endswith(
        _Path(path).name.lower()))
    return {
        "alive":     True,
        "contents":  None,   # heavy contents stay in the host
        "selection": list(info.get("selection") or []),
        "warnings":  list(info.get("warnings") or []),
        "current_view": info.get("current_view") or "",
        "opened_doc": opened or None,
        "matches":   bool(matches),
    }


def _read_csv(path: str) -> dict:
    """Read a CSV via stdlib. Returns columns + rows (first 100) +
    full row_count."""
    p = _Path(path)
    if not p.exists():
        return {"status": "missing", "error": f"file not found: {path}"}
    try:
        with p.open("r", encoding="utf-8", newline="") as fh:
            reader = _csv.reader(fh)
            rows_all = list(reader)
    except UnicodeDecodeError:
        with p.open("r", encoding="latin-1", newline="") as fh:
            reader = _csv.reader(fh)
            rows_all = list(reader)
    except Exception as ex:
        return {"status": "error",
                "error": f"{type(ex).__name__}: {ex}"}
    if not rows_all:
        return {"status": "ok", "columns": [], "rows": [],
                "row_count": 0}
    header = rows_all[0]
    data = rows_all[1:]
    return {
        "status":    "ok",
        "columns":   header,
        "rows":      data[:100],
        "row_count": len(data),
    }


def _read_pdf(path: str) -> dict:
    """Best-effort PDF text extraction. Returns status=missing_dep
    when pypdf isn't installed."""
    try:
        import pypdf  # type: ignore
    except ImportError:
        return {"status": "missing_dep",
                "hint": "pip install pypdf to enable PDF reading"}
    p = _Path(path)
    if not p.exists():
        return {"status": "missing", "error": f"file not found: {path}"}
    try:
        reader = pypdf.PdfReader(str(p))
        pages: list[str] = []
        for i, page in enumerate(reader.pages):
            if i >= 50:                         # cap so we don't OOM
                break
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pages.append("")
        return {
            "status":     "ok",
            "page_count": len(reader.pages),
            "text":       "\n\n".join(pages)[:200_000],
            "metadata":   dict(reader.metadata or {}),
        }
    except Exception as ex:
        return {"status": "error",
                "error": f"{type(ex).__name__}: {ex}"}


def _read_ifc(path: str) -> dict:
    """Best-effort IFC summary. Returns status=missing_dep when
    ifcopenshell isn't installed."""
    try:
        import ifcopenshell  # type: ignore
    except ImportError:
        return {"status": "missing_dep",
                "hint": "pip install ifcopenshell to enable IFC reading"}
    p = _Path(path)
    if not p.exists():
        return {"status": "missing", "error": f"file not found: {path}"}
    try:
        f = ifcopenshell.open(str(p))
        return {
            "status":  "ok",
            "schema":  getattr(f, "schema", ""),
            "project": getattr(f, "wrapped_data", None) and "loaded",
            "entity_count": len(list(f)),
        }
    except Exception as ex:
        return {"status": "error",
                "error": f"{type(ex).__name__}: {ex}"}


def _doc_exec(config: dict, inputs: dict, ctx) -> dict:
    """Return live doc metadata.

    For host-resident docs (revit/dwg/blender/3dm/max): ask the host
    runner if it's alive; otherwise return the offline envelope.

    For file-resident docs (csv/pdf/ifc): read directly from disk
    using stdlib (csv) or best-effort optional deps (pypdf,
    ifcopenshell).
    """
    family = config.get("_family") or "revit"
    path = (inputs.get("path") or config.get("path") or "").strip()
    version = config.get("version", "")

    base = {
        "status":     "ok",
        "family":     family,
        "path":       path,
        "version":    version,
        "contents":   None,
        "selection":  [],
        "warnings":   [],
        "document":   {"family": family, "path": path,
                       "version": version} if path else None,
        "after":      None,
    }

    # File-resident families ------------------------------------------
    if family == "csv":
        if not path:
            return base                 # no file = empty envelope
        res = _read_csv(path)
        if res.get("status") == "ok":
            base["contents"] = {
                "columns":   res["columns"],
                "rows":      res["rows"],
                "row_count": res["row_count"],
            }
        else:
            base["status"] = res.get("status", "ok")
            base["warnings"] = [res.get("error") or ""]
        return base

    if family == "pdf":
        if not path:
            return base
        res = _read_pdf(path)
        if res.get("status") == "ok":
            base["contents"] = {
                "page_count": res["page_count"],
                "text":       res["text"],
                "metadata":   res["metadata"],
            }
        elif res.get("status") == "missing_dep":
            base["status"]   = "missing_dep"
            base["hint"]     = res["hint"]
        else:
            base["warnings"] = [res.get("error") or ""]
        return base

    if family == "ifc":
        if not path:
            return base
        res = _read_ifc(path)
        if res.get("status") == "ok":
            base["contents"] = {
                "schema":       res["schema"],
                "entity_count": res["entity_count"],
            }
        elif res.get("status") == "missing_dep":
            base["status"]   = "missing_dep"
            base["hint"]     = res["hint"]
        else:
            base["warnings"] = [res.get("error") or ""]
        return base

    # Host-resident families ------------------------------------------
    live = _doc_from_host(family, path)
    if live.get("alive"):
        base["selection"] = list(live.get("selection") or [])
        base["warnings"]  = list(live.get("warnings") or [])
        base["contents"]  = {
            "current_view":   live.get("current_view") or "",
            "selection_count": len(base["selection"]),
            "warning_count":   len(base["warnings"]),
            "opened_doc":      live.get("opened_doc"),
            "matches":         live.get("matches", False),
        }
    return base


def _register_doc_node(family: str, name: str, icon: str,
                        out_type: PortType, ext: str) -> None:
    register(
        NodeSpec(
            type=f"doc.{family}",
            category="document",
            display_name=name,
            description=f"Opened {ext} document. Connects to a Host node.",
            inputs=[
                Port(name="path",   type=PortType.PATH,
                      description=f"Absolute path to the {ext} file"),
                Port(name="host",   type=PortType.HOST,
                      description="Host node managing this document"),
                Port(name="trigger", type=PortType.EXEC, exec=True),
            ],
            outputs=[
                Port(name="document",  type=out_type,
                      description="The opened document reference"),
                Port(name="contents",  type=PortType.OBJECT,
                      description="Document body (parsed)"),
                Port(name="selection", type=PortType.SELECTION,
                      description="Active selection within this document"),
                Port(name="warnings",  type=PortType.LIST,
                      description="Health/QA warnings from the document"),
                Port(name="after",     type=PortType.EXEC, exec=True),
            ],
            config_schema={
                "_family":  {"type": "string", "default": family,
                              "hidden": True},
                "path":     {"type": "string", "default": "",
                              "description": f"Path to {ext} file"},
                "version":  {"type": "string", "default": "",
                              "description": "Document version label"},
                "read_only":{"type": "boolean", "default": False},
            },
            icon=icon,
        ),
        _doc_exec,
    )


for _family, _name, _icon, _out_type, _ext in _DOC_FAMILIES:
    _register_doc_node(_family, _name, _icon, _out_type, _ext)
