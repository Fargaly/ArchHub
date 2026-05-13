"""ArchHubBridge — QWebChannel bridge between Python desktop + embedded JS.

The prototype HTML loaded by web_shell.WebShell mounts <StudioLM />,
which has its own internal demo data (LM_SESSIONS / LM_HOSTS /
LM_GRAPH). This bridge swaps that demo with the REAL desktop state
and routes UI actions back to the desktop runtime.

The JS side accesses everything via `window.archhub.*` after
QWebChannel handshake completes. All slots return JSON-serializable
data (lists/dicts/strings/numbers) so React state hooks can consume
them directly with `JSON.parse`.

Signals (Python → JS):
  chat_chunk(session_id, text)   token-by-token streaming response
  chat_done(session_id)          end of stream
  hosts_changed()                manager.entries changed; JS should refetch
  sessions_changed()             session list changed
  memory_changed()               memory facts changed

Slots (JS → Python):
  get_version()             → "1.4.0-alpha"
  get_hosts()               → [{id,name,state,version,...}]
  get_sessions()            → [{id,title,saved_at,...}]
  get_models()              → [{id,label,provider,configured,blocked}]
  get_memory_stats()        → {capture_today, redact_clean, ...}
  get_active_session()      → {id,title,graph}
  send_chat(session_id, text)   fires LLM round-trip; emits chat_chunk
  open_settings()           opens the native SettingsDialog
  open_pricing()            opens pricing dialog
  set_model(model_id)       sets active model on router
  set_host_active(host_id, on)  toggles a host on/off via manager
  load_session(session_id)  loads + emits session via signal
  save_active_session(graph_json)  persists current session.graph
  add_memory_fact(text, scope)  POST /v1/memory/facts via cloud_client
  list_memory_facts(q)      GET /v1/memory/facts?q=

Failures bubble as JSON {"error": "..."} so the JS side can show a
toast without crashing the React tree.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Optional

from PyQt6.QtCore import QObject, pyqtSlot, pyqtSignal


def _safe_json(obj: Any) -> str:
    """JSON-encode anything; drops un-encodable fields silently."""
    try:
        return json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:
        return "null"


class ArchHubBridge(QObject):
    """Bridge object registered on QWebChannel under the name `archhub`."""

    # Signals visible to JS via QWebChannel auto-emit.
    chat_chunk      = pyqtSignal(str, str)       # (session_id, text)
    chat_done       = pyqtSignal(str)            # (session_id)
    chat_error      = pyqtSignal(str, str)       # (session_id, error)
    hosts_changed   = pyqtSignal()
    sessions_changed = pyqtSignal()
    memory_changed  = pyqtSignal()
    notice          = pyqtSignal(str, str)       # (level, text) — toast hook
    # v1.4 wire-as-data-bridge — runner pushes wire state into JS so
    # the canvas can colour wires by data state in real time.
    wire_state_changed = pyqtSignal(str, str, str)   # (edge_id, state, preview)

    def __init__(self, *, router=None, manager=None, tools=None,
                  chat_widget=None, parent=None):
        super().__init__(parent)
        self.router = router
        self.manager = manager
        self.tools = tools
        self.chat_widget = chat_widget
        self._active_session_id: Optional[str] = None

    # ─── Identity ───────────────────────────────────────────────
    @pyqtSlot(result=str)
    def get_version(self) -> str:
        try:
            from pathlib import Path
            p = Path(__file__).resolve().parent.parent / "VERSION"
            return p.read_text(encoding="utf-8").strip() if p.exists() else "1.4.0-alpha"
        except Exception:
            return "1.4.0-alpha"

    # ─── Hosts ──────────────────────────────────────────────────
    @pyqtSlot(result=str)
    def get_hosts(self) -> str:
        out: list[dict] = []
        try:
            from manager import ConnectorState
            for entry in getattr(self.manager, "entries", []) or []:
                state = entry.state
                state_s = (state.value if hasattr(state, "value")
                            else str(state)).lower()
                out.append({
                    "id":     entry.family,
                    "family": entry.family,
                    "name":   (entry.display_name
                                or entry.family.title()),
                    "state":  state_s,
                    "version": getattr(entry, "version", "") or "",
                    "port":    getattr(entry, "port", None),
                })
        except Exception:
            pass
        return _safe_json(out)

    @pyqtSlot(str, bool, result=str)
    def set_host_active(self, host_id: str, on: bool) -> str:
        try:
            if not self.manager:
                return _safe_json({"error": "no manager"})
            mfn = getattr(self.manager, "activate_family"
                            if on else "deactivate_family", None)
            if mfn:
                mfn(host_id)
                self.hosts_changed.emit()
                return _safe_json({"ok": True})
            return _safe_json({"error": "manager has no toggle"})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Sessions ───────────────────────────────────────────────
    @pyqtSlot(result=str)
    def get_sessions(self) -> str:
        try:
            from session_io import list_sessions
            entries = list_sessions() or []
            out = []
            for e in entries:
                # e is either a SessionListEntry dataclass or a dict.
                if hasattr(e, "name"):
                    out.append({
                        "id":       getattr(e, "name", "")
                                      or getattr(e, "path", ""),
                        "title":    getattr(e, "name", ""),
                        "saved_at": str(getattr(e, "saved_at", "")),
                        "messages": getattr(e, "message_count", 0),
                    })
                elif isinstance(e, dict):
                    out.append({
                        "id":       e.get("name") or e.get("path") or "",
                        "title":    e.get("name", ""),
                        "saved_at": str(e.get("saved_at", "")),
                        "messages": e.get("message_count", 0),
                    })
            return _safe_json(out)
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def load_session(self, session_id: str) -> str:
        try:
            from pathlib import Path
            from session_io import SESSIONS_DIR, load_session
            # session_id can be a name or a path; try both.
            p = Path(session_id)
            if not p.exists():
                p = SESSIONS_DIR / f"{session_id}.archhub-session.json"
            if not p.exists():
                return _safe_json({"error": "session not found"})
            session, name = load_session(p)
            self._active_session_id = session.id
            return _safe_json({
                "id":    session.id,
                "name":  name,
                "graph": session.graph or {},
            })
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Models ─────────────────────────────────────────────────
    @pyqtSlot(result=str)
    def get_models(self) -> str:
        if not self.router:
            return _safe_json([])
        try:
            from llm_router import (
                KNOWN_MODELS, ROUTE_AUTO, ollama_models, lmstudio_models,
            )
            configured = set(self.router.configured_providers() or [])
            blocked = self.router.blocked_providers() or {}
            out = [{
                "id":       ROUTE_AUTO,
                "label":    "Auto · best model per task",
                "provider": "auto",
                "configured": True,
                "blocked": "",
            }]
            for mid, label in KNOWN_MODELS:
                provider = mid.partition(":")[0]
                out.append({
                    "id":       mid,
                    "label":    label,
                    "provider": provider,
                    "configured": provider in configured,
                    "blocked":  blocked.get(provider, ""),
                })
            for mid, label in ollama_models():
                out.append({"id": mid, "label": label,
                            "provider": "ollama",
                            "configured": True, "blocked": ""})
            for mid, label in lmstudio_models():
                out.append({"id": mid, "label": label,
                            "provider": "lmstudio",
                            "configured": True, "blocked": ""})
            return _safe_json(out)
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def set_model(self, model_id: str) -> str:
        try:
            if self.chat_widget and hasattr(self.chat_widget, "model_picker"):
                cw = self.chat_widget
                for i in range(cw.model_picker.count()):
                    if cw.model_picker.itemData(i) == model_id:
                        cw.model_picker.setCurrentIndex(i)
                        return _safe_json({"ok": True})
            return _safe_json({"error": "picker not available"})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Chat ───────────────────────────────────────────────────
    @pyqtSlot(str, str)
    def send_chat(self, session_id: str, text: str) -> None:
        """Fire-and-forget. Emits chat_chunk / chat_done / chat_error
        back to JS on its own thread."""
        text = (text or "").strip()
        if not text:
            self.chat_error.emit(session_id, "empty prompt")
            return
        if not self.router:
            self.chat_error.emit(session_id, "router not wired")
            return

        def _runner():
            try:
                # ChatWindow is the integrated front-end — when present,
                # invoke its send pipeline so we get the same tool-use
                # loop + memory + telemetry pipeline. Otherwise call
                # the router directly with no tools.
                if self.chat_widget and hasattr(self.chat_widget, "_send_text_async"):
                    # Use the chat widget's internal send pipeline.
                    try:
                        self.chat_widget._send_text_async(text)
                        self.chat_done.emit(session_id)
                        return
                    except Exception:
                        pass
                # Fallback: direct router call.
                result = self.router.complete(
                    prompt=text, conversation=[],
                )
                if result is not None:
                    reply = getattr(result, "text", str(result))
                    self.chat_chunk.emit(session_id, reply)
                self.chat_done.emit(session_id)
            except Exception as ex:
                self.chat_error.emit(session_id, f"{type(ex).__name__}: {ex}")

        threading.Thread(target=_runner, daemon=True).start()

    # ─── Settings ──────────────────────────────────────────────
    @pyqtSlot()
    def open_settings(self) -> None:
        """Open the native SettingsDialog on the Qt main thread."""
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._open_settings_safe)

    def _open_settings_safe(self) -> None:
        try:
            from settings_dialog import SettingsDialog
            parent = self.parent()
            dlg = SettingsDialog(parent=parent, router=self.router,
                                   manager=self.manager, tools=self.tools)
            dlg.exec()
        except Exception as ex:
            self.notice.emit("error", f"Settings unavailable: {ex}")

    @pyqtSlot()
    def open_pricing(self) -> None:
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._open_pricing_safe)

    def _open_pricing_safe(self) -> None:
        try:
            from pricing_dialog import PricingDialog
            parent = self.parent()
            PricingDialog(parent=parent).exec()
        except Exception:
            try:
                from upgrade_dialog import UpgradeDialog
                parent = self.parent()
                UpgradeDialog(parent=parent).exec()
            except Exception as ex:
                self.notice.emit("error", f"Pricing unavailable: {ex}")

    # ─── Memory ────────────────────────────────────────────────
    @pyqtSlot(result=str)
    def get_memory_stats(self) -> str:
        try:
            from cloud_client import memory_stats
            stats = memory_stats() or {}
            return _safe_json(stats)
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def list_memory_facts(self, q: str = "") -> str:
        try:
            from cloud_client import _request
            path = f"/v1/memory/facts?q={q}" if q else "/v1/memory/facts"
            r = _request("GET", path)
            if r["status"] != "ok":
                return _safe_json({"error": "not authed or cloud down"})
            return _safe_json(r.get("json") or {})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, str, result=str)
    def add_memory_fact(self, text: str, scope: str = "user") -> str:
        try:
            from cloud_client import _request
            r = _request("POST", "/v1/memory/facts",
                          body={"text": text, "scope": scope})
            if r["status"] != "ok":
                return _safe_json({"error": "cloud unavailable"})
            self.memory_changed.emit()
            return _safe_json(r.get("json") or {})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Memory mutations ──────────────────────────────────────
    @pyqtSlot(int, str, result=str)
    def update_memory_fact(self, fact_id: int, text: str) -> str:
        try:
            from cloud_client import _request
            r = _request("PUT", f"/v1/memory/facts/{fact_id}",
                          body={"text": text})
            if r["status"] != "ok":
                return _safe_json({"error": "update failed"})
            self.memory_changed.emit()
            return _safe_json(r.get("json") or {})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(int, result=str)
    def forget_memory_fact(self, fact_id: int) -> str:
        try:
            from cloud_client import _request
            r = _request("DELETE", f"/v1/memory/facts/{fact_id}")
            if r["status"] != "ok":
                return _safe_json({"error": "forget failed"})
            self.memory_changed.emit()
            return _safe_json({"ok": True, "id": fact_id})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Session graph ─────────────────────────────────────────
    @pyqtSlot(str, result=str)
    def get_session_graph(self, session_id: str) -> str:
        """Return the graph (nodes+wires) for an open session in the
        shape studio-lm.jsx's LM_GRAPH expects.

        The session id is the slug under SESSIONS_DIR. When the session
        has a stored graph (ADR-003 Phase 2 dual-write), we ship that.
        Otherwise we wrap the message log as a single conversation
        node so the canvas always has something to render."""
        try:
            from pathlib import Path
            from session_io import SESSIONS_DIR, load_session_with_messages
            p = Path(session_id)
            if not p.exists():
                p = SESSIONS_DIR / f"{session_id}.archhub-session.json"
            if not p.exists():
                return _safe_json({"nodes": [], "wires": []})
            session, _name, messages = load_session_with_messages(p)
            if session.graph and session.graph.get("nodes"):
                return _safe_json(session.graph)
            # No graph yet — wrap messages.
            from session_graph_migrator import wrap_legacy_as_graph
            g = wrap_legacy_as_graph(session, messages, name=session_id)
            return _safe_json(g)
        except Exception as ex:
            return _safe_json({"nodes": [], "wires": [],
                                "error": str(ex)})

    # ─── Saved skills ──────────────────────────────────────────
    @pyqtSlot(result=str)
    def get_saved_skills(self) -> str:
        try:
            import skills
            out = []
            for s in (skills.list_skills() or []):
                out.append({
                    "id":    s.get("id") or s.get("slug") or "",
                    "name":  s.get("name", ""),
                    "runs":  s.get("run_count", 0),
                    "args":  s.get("args", "") or "",
                    "when":  str(s.get("updated_at") or s.get("created_at") or ""),
                })
            return _safe_json(out)
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Permissions (auto/ask/block per tool) ─────────────────
    @pyqtSlot(result=str)
    def get_permissions(self) -> str:
        """Pull every tool's policy from the secrets store under
        `tool_policies`. Returns shape the Permissions settings tab
        consumes: [{id, label, sub, mode}]."""
        try:
            from secrets_store import load_setting
            policies = load_setting("tool_policies") or {}
            from tool_engine import TOOLS
            out = []
            for tool_name, tool in (TOOLS or {}).items():
                out.append({
                    "id":    tool_name,
                    "label": tool.get("display_name", tool_name)
                               if isinstance(tool, dict)
                               else tool_name,
                    "sub":   tool.get("description", "")
                               if isinstance(tool, dict) else "",
                    "mode":  policies.get(tool_name, "ask"),
                })
            return _safe_json(out)
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, str, result=str)
    def set_permission(self, tool_id: str, mode: str) -> str:
        if mode not in ("auto", "ask", "block"):
            return _safe_json({"error": "mode must be auto|ask|block"})
        try:
            from secrets_store import load_setting, save_setting
            policies = dict(load_setting("tool_policies") or {})
            policies[tool_id] = mode
            save_setting("tool_policies", policies)
            return _safe_json({"ok": True, "id": tool_id, "mode": mode})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Providers (LLM vendor keys) ───────────────────────────
    @pyqtSlot(result=str)
    def get_providers(self) -> str:
        """Cloud/local LLM providers in the design's Settings → Providers
        tab shape: [{id, name, state, key, usage, col}]."""
        try:
            from llm_router import lmstudio_models
            from secrets_store import load_api_key
            configured = set(self.router.configured_providers()
                              if self.router else [])
            providers_meta = [
                ("anthropic",  "Anthropic",   "#cc785c"),
                ("openai",     "OpenAI",      "#10a37f"),
                ("google",     "Google",      "#4285f4"),
                ("openrouter", "OpenRouter",  "#a98cd6"),
                ("ollama",     "Ollama",      "#7ec18e"),
                ("lmstudio",   "LM Studio",   "#5fb3b3"),
            ]
            out = []
            for pid, pname, col in providers_meta:
                k = ""
                try:
                    k = load_api_key(pid) or ""
                except Exception:
                    pass
                if pid in configured:
                    state = "connected"
                elif pid in ("ollama", "lmstudio"):
                    state = "local" if pid in configured else "off"
                else:
                    state = "off"
                # Mask the key for transport (last 4 chars).
                masked = (("…" + k[-4:]) if k else "")
                out.append({
                    "id":     pid,
                    "name":   pname,
                    "state":  state,
                    "key":    masked,
                    "usage":  "—",
                    "col":    col,
                })
            return _safe_json(out)
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, str, result=str)
    def set_provider_key(self, provider_id: str, api_key: str) -> str:
        try:
            from secrets_store import save_api_key
            save_api_key(provider_id, api_key)
            if self.router and hasattr(self.router, "invalidate_clients"):
                self.router.invalidate_clients()
            return _safe_json({"ok": True, "id": provider_id})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Graph persistence + execution ─────────────────────────
    @pyqtSlot(str, str, result=str)
    def save_graph(self, session_id: str, graph_json: str) -> str:
        """Persist a graph (JSON-string) to its session's on-disk file.

        Mutating the canvas (add wire, drop node, delete) fires this
        so reload restores state. Round-trip-safe per ADR-003 Phase 2:
        we update session.graph + session_io.save_session writes the
        same JSON back.
        """
        try:
            import json as _json
            from pathlib import Path
            from session_io import (
                SESSIONS_DIR, save_session, load_session_with_messages,
            )
            graph = _json.loads(graph_json or "{}")
            sid = session_id or "workspace"
            p = Path(sid)
            if not p.exists():
                p = SESSIONS_DIR / f"{sid}.archhub-session.json"
            if p.exists():
                session, name, messages = load_session_with_messages(p)
            else:
                # Fresh session — create one + use sid as name slug.
                from session import Session
                session = Session()
                name = sid
                messages = []
            session.graph = graph
            save_session(session, name=name, messages=messages or None)
            self.sessions_changed.emit()
            return _safe_json({"ok": True, "session_id": sid,
                                "nodes": len(graph.get("nodes") or []),
                                "wires": len(graph.get("wires") or [])})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Wire validation (canvas drop-validation) ──────────────────
    @pyqtSlot(str, str, bool, bool, result=bool)
    def can_wire(self, out_type: str, in_type: str,
                  out_exec: bool, in_exec: bool) -> bool:
        """Type-check a prospective wire from canvas mouseup. Returns
        False when the rubber-band should snap back instead of
        committing the wire."""
        try:
            from workflows.typesystem import can_wire as _cw
            from workflows.graph import PortType
            out_t = PortType(out_type) if out_type else PortType.ANY
            in_t  = PortType(in_type)  if in_type  else PortType.ANY
            return bool(_cw(out_t, in_t,
                             output_is_exec=bool(out_exec),
                             input_is_exec=bool(in_exec)))
        except Exception:
            return True   # fail-open: prefer accepting questionable
                          # types over refusing valid ones

    @pyqtSlot(str, str, str, str, result=bool)
    def would_create_cycle(self, session_id: str,
                             src_node: str, dst_node: str,
                             graph_json: str = "") -> bool:
        """True if dropping a wire from src→dst would create a cycle.
        Canvas calls this on socket-drop before committing."""
        try:
            import json as _json
            graph = _json.loads(graph_json) if graph_json else None
            if graph is None:
                # Load from disk fallback.
                from pathlib import Path
                from session_io import (
                    SESSIONS_DIR, load_session_with_messages,
                )
                p = Path(session_id)
                if not p.exists():
                    p = SESSIONS_DIR / f"{session_id}.archhub-session.json"
                if not p.exists():
                    return False
                session, _name, _m = load_session_with_messages(p)
                graph = session.graph or {}
            from workflows.runner import WorkflowRunner
            return WorkflowRunner(graph).would_create_cycle(
                src_node, dst_node)
        except Exception:
            return False

    @pyqtSlot(str, str, str, result=str)
    def run_node(self, session_id: str, node_id: str,
                  graph_json: str = "") -> str:
        """Cook a node via WorkflowRunner.pull — lazy upstream walk +
        dirty cascade + caching. Emits wire_state(edge_id, state,
        preview) signals as values flow so the JS canvas can light up
        wires in real time.

        graph_json is optional. When given, the runner runs against
        that in-memory shape (no disk roundtrip). When empty, we read
        session.graph from the saved session.
        """
        try:
            import json as _json
            from pathlib import Path
            sid = session_id or "workspace"
            graph: dict
            if graph_json:
                try:
                    graph = _json.loads(graph_json)
                except Exception as ex:
                    return _safe_json({"error": f"bad graph_json: {ex}"})
            else:
                from session_io import (
                    SESSIONS_DIR, load_session_with_messages,
                )
                p = Path(sid)
                if not p.exists():
                    p = SESSIONS_DIR / f"{sid}.archhub-session.json"
                if not p.exists():
                    return _safe_json({"error": "session not found"})
                session, _name, _m = load_session_with_messages(p)
                graph = session.graph or {}
            from workflows.runner import WorkflowRunner
            runner = WorkflowRunner(graph)
            # Wire wire-state changes through to JS via Qt signal.
            runner.on_wire_state(
                lambda eid, state, preview:
                    self.wire_state_changed.emit(eid, state, preview))
            result = runner.pull(node_id)
            return _safe_json(result if isinstance(result, dict)
                                else {"value": result})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Workflow / node library ────────────────────────────────
    @pyqtSlot(result=str)
    def get_node_library(self) -> str:
        """All registered node specs from the workflows registry,
        grouped by category. Used by the JS Nodes panel to show
        real types (host.revit, conversation.chat, doc.ifc, ...)."""
        try:
            from workflows.registry import _REGISTRY
            out: dict[str, list[dict]] = {}
            for tname, (spec, _exec) in sorted(_REGISTRY.items()):
                cat = spec.category or "misc"
                out.setdefault(cat, []).append({
                    "type":         spec.type,
                    "display_name": spec.display_name,
                    "description":  spec.description,
                    "icon":         spec.icon,
                    "inputs":       [p.to_dict() for p in spec.inputs],
                    "outputs":      [p.to_dict() for p in spec.outputs],
                })
            return _safe_json(out)
        except Exception as ex:
            return _safe_json({"error": str(ex)})
