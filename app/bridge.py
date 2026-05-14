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


# ---------------------------------------------------------------------------
# Host session/document picker implementation (used by the bridge slots
# `list_host_sessions` and `list_host_documents`).
#
# Each host family exposes either a broker (revit/autocad/max/outlook) with
# `list_sessions()` returning a list of Session dataclasses, OR a runner
# (blender/rhino) with a single listener model. Speckle is cloud-only and
# returns an empty list.
# ---------------------------------------------------------------------------

def _session_to_dict(s: Any, family: str) -> dict:
    """Serialise a broker Session dataclass into a JSON-safe dict using
    the contract the JS picker consumes."""
    return {
        "session_id": str(getattr(s, "session_id", "") or ""),
        "family":     family,
        "version":    str(getattr(s, "version", "") or ""),
        "port":       int(getattr(s, "port", 0) or 0),
        "opened_doc": str(getattr(s, "doc_title", "") or ""),
        "host_alive": bool(getattr(s, "healthy", False)),
        "pid":        int(getattr(s, "pid", 0) or 0),
        "legacy":     bool(getattr(s, "legacy", False)),
    }


def _list_host_sessions_impl(family: str) -> list[dict]:
    """Family-dispatched list of running host sessions. Pure helper —
    no Qt, callable from tests + the QObject slot above."""
    if family in ("revit", "autocad", "max"):
        mod_map = {"revit": "revit_broker",
                    "autocad": "acad_broker",
                    "max":     "max_broker"}
        try:
            broker = __import__(mod_map[family])
        except Exception:
            return []
        try:
            sessions = broker.list_sessions(prune=False)
        except Exception:
            return []
        return [_session_to_dict(s, family) for s in (sessions or [])]

    if family == "outlook":
        try:
            from outlook_broker import list_sessions as _ol_list
            sessions = _ol_list(prune=False)
        except Exception:
            return []
        return [_session_to_dict(s, family) for s in (sessions or [])]

    if family in ("blender", "rhino"):
        # Single-listener model. Build a synthetic 1-entry list when the
        # bridge is responding; empty list otherwise. The runner picker
        # may expose list_sessions() in the future — try first, fall
        # back to a probe.
        try:
            if family == "blender":
                from connectors import blender_runner as runner  # type: ignore
            else:
                from connectors import rhino_runner as runner   # type: ignore
        except Exception:
            return []
        listed = getattr(runner, "list_sessions", None)
        if callable(listed):
            try:
                rows = listed() or []
                # Normalise: runners may return list[dict] already; coerce.
                return [{
                    "session_id": str(r.get("session_id", f"{family}-default")),
                    "family":     family,
                    "version":    str(r.get("version", "") or ""),
                    "port":       int(r.get("port", 0) or 0),
                    "opened_doc": str(r.get("opened_doc")
                                       or r.get("filepath", "") or ""),
                    "host_alive": bool(r.get("host_alive", True)),
                } for r in rows]
            except Exception:
                pass
        # Fallback: single-listener probe.
        try:
            pong = runner.ping()
        except Exception:
            pong = None
        if not pong:
            return []
        version = ""
        opened = ""
        try:
            info_d = runner.info() or {}
            version = str(info_d.get("version") or "")
            opened = str(info_d.get("filepath")
                          or info_d.get("doc_path")
                          or info_d.get("filename") or "")
        except Exception:
            pass
        return [{
            "session_id": f"{family}-default",
            "family":     family,
            "version":    version,
            "port":       int(getattr(runner,
                                       "CONNECTOR_PORT_DEFAULT", 0) or 0),
            "opened_doc": opened,
            "host_alive": True,
        }]

    if family == "speckle":
        # Streams not sessions — return empty list with a note.
        return []

    return []


def _list_host_documents_impl(family: str, session_id: str) -> list[dict]:
    """List documents available inside the chosen session. For broker-
    backed hosts we POST to /list_docs (falling back to /info for the
    single open doc). For runner-backed hosts we call list_files()/
    info(). For Outlook we list folders."""
    family = (family or "").strip().lower()
    session_id = (session_id or "").strip()

    if family in ("revit", "autocad", "max"):
        mod_map = {"revit": "revit_broker",
                    "autocad": "acad_broker",
                    "max":     "max_broker"}
        try:
            broker = __import__(mod_map[family])
        except Exception:
            return []
        # Find the matching session.
        try:
            sessions = broker.list_sessions(prune=False) or []
        except Exception:
            sessions = []
        chosen = None
        for s in sessions:
            if not session_id or str(getattr(s, "session_id", ""))== session_id:
                chosen = s
                break
        if chosen is None:
            return []
        # Try /list_docs; fall back to /info.
        try:
            docs = broker.forward(chosen, "/list_docs", timeout=2.0)
        except Exception:
            docs = None
        if isinstance(docs, dict) and docs.get("status") != "error":
            rows = docs.get("documents") or docs.get("docs") or []
            return [{
                "path":   str(d.get("path", "") or ""),
                "title":  str(d.get("title")
                               or d.get("name", "") or ""),
                "active": bool(d.get("active", False)),
                "kind":   str(d.get("kind", "") or ""),
            } for d in rows if isinstance(d, dict)]
        # Fallback: single doc from session metadata.
        title = str(getattr(chosen, "doc_title", "") or "")
        if not title:
            return []
        return [{"path": "", "title": title,
                  "active": True, "kind": family}]

    if family == "outlook":
        # For outlook, "documents" = folders / accounts.
        try:
            from connectors import outlook_runner
            folders = outlook_runner.list_folders() or []
            return [{
                "path":   str(f.get("path", "") or ""),
                "title":  str(f.get("name", "") or ""),
                "active": False,
                "kind":   "folder",
            } for f in folders if isinstance(f, dict)]
        except Exception:
            return []

    if family in ("blender", "rhino"):
        try:
            if family == "blender":
                from connectors import blender_runner as runner  # type: ignore
            else:
                from connectors import rhino_runner as runner   # type: ignore
        except Exception:
            return []
        # Runner may expose list_files/list_docs explicitly.
        for fn_name in ("list_files", "list_docs", "list_documents"):
            fn = getattr(runner, fn_name, None)
            if callable(fn):
                try:
                    rows = fn() or []
                    return [{
                        "path":   str(r.get("path", "") or ""),
                        "title":  str(r.get("title")
                                       or r.get("name", "") or ""),
                        "active": bool(r.get("active", False)),
                        "kind":   str(r.get("kind", "") or family),
                    } for r in rows if isinstance(r, dict)]
                except Exception:
                    continue
        # Fallback: info() exposes the single open doc.
        try:
            info_d = runner.info() or {}
        except Exception:
            info_d = {}
        files = info_d.get("files") or []
        if files and isinstance(files, list):
            return [{
                "path":   str(f.get("path", "") or "") if isinstance(f, dict)
                          else str(f),
                "title":  str(f.get("title")
                               or f.get("name", "") or "") if isinstance(f, dict)
                          else str(f),
                "active": bool(f.get("active", False)) if isinstance(f, dict)
                          else False,
                "kind":   family,
            } for f in files]
        opened = (info_d.get("filepath")
                   or info_d.get("doc_path")
                   or info_d.get("filename") or "")
        if not opened:
            return []
        from pathlib import Path as _P
        return [{"path": str(opened),
                  "title": _P(str(opened)).name,
                  "active": True, "kind": family}]

    if family == "speckle":
        return []   # streams are not documents

    return []


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
    def get_all_hosts(self) -> str:
        """All desktop / SaaS hosts ArchHub knows about — Outlook,
        Teams, Word, Excel, PowerPoint, Photoshop, Illustrator, InDesign,
        LM Studio, Antigravity. Each entry: {status, version, note,
        detail}. Used by the JS host-pill row to render live indicators
        for non-LLM hosts."""
        try:
            from host_detector import detect_all_hosts
            return _safe_json(detect_all_hosts())
        except Exception as ex:
            return _safe_json({"error": str(ex)})

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

    @pyqtSlot(str, str, result=str)
    def run_workflow(self, session_id: str, graph_json: str = "") -> str:
        """Run the entire workflow (Houdini render). Cooks every sink
        node; pulls cascade upstream automatically; frozen nodes are
        skipped. The canvas toolbar 'RUN WORKFLOW' button calls this."""
        try:
            import json as _json
            graph: dict
            if graph_json:
                graph = _json.loads(graph_json)
            else:
                from pathlib import Path
                from session_io import (
                    SESSIONS_DIR, load_session_with_messages,
                )
                p = Path(session_id or "workspace")
                if not p.exists():
                    p = SESSIONS_DIR / f"{session_id}.archhub-session.json"
                if not p.exists():
                    return _safe_json({"error": "session not found"})
                session, _name, _m = load_session_with_messages(p)
                graph = session.graph or {}
            from workflows.runner import WorkflowRunner
            runner = WorkflowRunner(graph)
            runner.on_wire_state(
                lambda eid, state, preview:
                    self.wire_state_changed.emit(eid, state, preview))
            return _safe_json(runner.run_all())
        except Exception as ex:
            return _safe_json({"error": str(ex)})

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

    # ─── Host session + document pickers ───────────────────────
    # Founder direction (2026-05-14): host tools should let the user
    # pick WHICH version of the host (Revit 2024 vs Revit 2025) AND
    # WHICH document inside that session. Below two slots feed the
    # dynamic <select> dropdowns in studio-lm.jsx for host.* nodes.
    @pyqtSlot(str, result=str)
    def list_host_sessions(self, family: str) -> str:
        """Return all running sessions for a host family.
        Shape: [{session_id, version, port, opened_doc, host_alive}].
        Empty list = nothing running (or unsupported family)."""
        try:
            family = (family or "").strip().lower()
            return _safe_json(_list_host_sessions_impl(family))
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, str, result=str)
    def list_host_documents(self, family: str,
                             session_id: str = "") -> str:
        """List documents inside the chosen session.
        Shape: [{path, title, active, kind}]."""
        try:
            family = (family or "").strip().lower()
            return _safe_json(_list_host_documents_impl(family, session_id))
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Profound wires (field selectors) ───────────────────────
    # Founder direction (2026-05-14): "wires should be profound...
    # capable of transferring models between models, taking out specific
    # outputs." A wire can (a) pick a sub-field of the source output
    # before flowing (src_field) and (b) wrap into a sub-key of the
    # destination input slot (dst_field). The JS canvas exposes this as
    # a right-click "Pick source field…" / "Pick destination field…"
    # overlay on a wire. The two slots below back that UI.
    @pyqtSlot(str, str, str, result=str)
    def wire_transform(self, payload_json: str,
                        src_field: str = "",
                        dst_field: str = "") -> str:
        """Apply the same src_field/dst_field resolver used by the
        runner to an arbitrary JSON payload. Lets the JS canvas preview
        a wire transformation without re-cooking the whole graph.
        Returns `{"value": <result>}` or `{"error": "..."}`.
        """
        try:
            import json as _json
            from workflows.runner import (
                _resolve_field, _wrap_field,
            )
            try:
                payload = _json.loads(payload_json) if payload_json else None
            except Exception as ex:
                return _safe_json({"error": f"bad payload_json: {ex}"})
            value = payload
            if src_field:
                value = _resolve_field(value, src_field)
            if dst_field:
                value = _wrap_field(value, dst_field)
            return _safe_json({"value": value})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, str, str, result=str)
    def list_wire_fields(self, node_id: str,
                          port_name: str = "",
                          sample_json: str = "") -> str:
        """Introspect an upstream output schema and return the available
        dotted paths the user could pick as a wire src_field.

        The canvas is expected to pass the most recently cached preview
        for `(node_id, port_name)` as `sample_json` — that's the value
        the wire just carried. If sample_json is empty, returns an
        empty paths list with no error.
        Shape: `{"paths": ["selection.walls", "selection.walls[0].id",
        ...], "sample": <pretty repr>}`.
        """
        try:
            import json as _json
            from workflows.runner import _enumerate_paths
            if not sample_json:
                return _safe_json({"paths": [], "sample": None,
                                    "node": node_id, "port": port_name})
            try:
                sample = _json.loads(sample_json)
            except Exception:
                # Not JSON — caller passed e.g. repr(value). Still tell
                # the user we can't introspect that.
                return _safe_json({"paths": [], "sample": sample_json,
                                    "node": node_id, "port": port_name,
                                    "note": "preview not JSON"})
            paths = _enumerate_paths(sample)
            return _safe_json({"paths": paths, "sample": sample,
                                "node": node_id, "port": port_name})
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

    # ─── Per-node MCP servers ───────────────────────────────────
    # Founder direction (2026-05-14): "as if every node initiates its
    # own MCP server." The canvas calls register_node_mcp(...) when a
    # node is materialised, then get_node_mcp_tools / invoke_node_tool
    # for live tool discovery + dispatch.
    @pyqtSlot(str, str, str, result=str)
    def register_node_mcp(self, node_id: str, node_type: str,
                            config_json: str = "") -> str:
        """Register a node as an MCP server. `config_json` is the same
        config blob the workflow graph stores for the node — `path`,
        `version`, `model`, etc."""
        try:
            from mcp.node_mcp import NodeMCPServer, REGISTRY
            cfg: dict = {}
            if config_json:
                try:
                    cfg = json.loads(config_json) or {}
                except Exception as ex:
                    return _safe_json(
                        {"error": f"bad config_json: {ex}"})
            server = NodeMCPServer(node_id=node_id,
                                     node_type=node_type,
                                     config=cfg)
            REGISTRY.register(node_id, server)
            return _safe_json(server.to_dict())
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def get_node_mcp_tools(self, node_id: str) -> str:
        """Return the JSON list of MCP tools the node exposes. The
        canvas calls this once per node-mount and again after a
        config change."""
        try:
            from mcp.node_mcp import REGISTRY
            server = REGISTRY.get(node_id)
            if server is None:
                return _safe_json(
                    {"error": f"Unknown node_id: {node_id}"})
            return _safe_json(server.list_tools())
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, str, str, result=str)
    def invoke_node_tool(self, node_id: str, tool_name: str,
                          args_json: str = "") -> str:
        """Invoke a tool on the node's MCP server. Returns a JSON
        envelope. Unknown node_id → error envelope (no raise)."""
        try:
            from mcp.node_mcp import REGISTRY
            args: dict = {}
            if args_json:
                try:
                    args = json.loads(args_json) or {}
                except Exception as ex:
                    return _safe_json(
                        {"error": f"bad args_json: {ex}"})
            return _safe_json(
                REGISTRY.invoke(node_id, tool_name, args))
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def unregister_node_mcp(self, node_id: str) -> str:
        """Unregister a node — called when the canvas deletes a node."""
        try:
            from mcp.node_mcp import REGISTRY
            removed = REGISTRY.unregister(node_id)
            return _safe_json({"ok": True, "removed": removed})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(result=str)
    def list_node_mcp_servers(self) -> str:
        """List every node-MCP server currently live."""
        try:
            from mcp.node_mcp import REGISTRY
            return _safe_json(REGISTRY.list_servers())
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, str, str, result=str)
    def dispatch_node_mcp(self, node_id: str, method: str,
                           params_json: str = "") -> str:
        """Send a raw MCP JSON-RPC method (initialize / tools/list /
        tools/call / ping) to the node's server. Returns the JSON-RPC
        envelope."""
        try:
            from mcp.node_mcp import REGISTRY
            server = REGISTRY.get(node_id)
            if server is None:
                return _safe_json(
                    {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32001,
                                "message": f"Unknown node_id: {node_id}"}})
            params: dict = {}
            if params_json:
                try:
                    params = json.loads(params_json) or {}
                except Exception as ex:
                    return _safe_json(
                        {"jsonrpc": "2.0", "id": None,
                         "error": {"code": -32700,
                                    "message": f"bad params_json: {ex}"}})
            return _safe_json(server.dispatch(method, params))
        except Exception as ex:
            return _safe_json({"error": str(ex)})
