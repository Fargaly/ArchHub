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


# ROADMAP P2 fix — family-name aliases.
# Founder saw "AutoCAD MCP not reading sessions" because the bridge
# dispatch map only knows "autocad" / "max" but various JSX + tool
# callsites pass "acad" / "max3ds" / "3dsmax". Normalise here so EVERY
# caller hits the right broker regardless of name flavour.
_FAMILY_ALIASES = {
    "acad":    "autocad",
    "3dsmax":  "max",
    "max3ds":  "max",
    "rhino3d": "rhino",
}


def _normalize_family(family: str) -> str:
    f = (family or "").strip().lower()
    return _FAMILY_ALIASES.get(f, f)


def _list_host_sessions_impl(family: str) -> list[dict]:
    """Family-dispatched list of running host sessions. Pure helper —
    no Qt, callable from tests + the QObject slot above."""
    family = _normalize_family(family)
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
            import importlib as _il
            runner = _il.import_module(
                "connectors.blender_runner" if family == "blender"
                else "connectors.rhino_runner")
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
    family = _normalize_family(family)
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
            import importlib as _il
            runner = _il.import_module(
                "connectors.blender_runner" if family == "blender"
                else "connectors.rhino_runner")
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


# ---------------------------------------------------------------------------
# Canvas-skill store. A "skill" in the Skills panel is a saved canvas
# fragment ({nodes, wires}) the user can splice back onto any canvas.
#
# ONE store, ONE format, ONE resolver — get_saved_skills (the panel's
# list) and load_skill (the panel's click) BOTH go through
# _scan_canvas_skills(), so the list can never again point at a
# different place than the loader. Founder bug 2026-05-18: the list
# read the engine-format skills.library while load_skill globbed the
# source-tree app/skills/ dir — every listed skill 404'd on click.
# ---------------------------------------------------------------------------
def _user_skills_dir() -> "Path":
    """Writable canvas-skill store — %LOCALAPPDATA%/ArchHub/skills/.

    The location get_storage_stats / export / import already treat as
    the skills store; save_as_skill now writes here too. It used to
    write the source tree (app/skills/), which is wiped on every app
    update and never matched the panel's list."""
    import os as _os
    from pathlib import Path
    d = (Path(_os.environ.get("LOCALAPPDATA", str(Path.home())))
         / "ArchHub" / "skills")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _shipped_skills_dir() -> "Path":
    """Read-only canvas skills shipped in the app tree
    (app/skills/*.archhub-skill.json) — scanned alongside the user
    store so built-in starter skills appear with no first-run copy."""
    from pathlib import Path
    return Path(__file__).resolve().parent / "skills"


# ─── AgDR-0033 — skill tombstone list ────────────────────────────────
# `app/skills/` serves double duty: genuine shipped starter seeds AND
# user skills mis-saved there by the historical save_as_skill bug
# (it used to write the source tree).  A shipped seed can't be unlinked
# (an app update restores it; on a read-only install the unlink fails).
# So "deleting" a shipped seed records its slug in a per-user tombstone
# file; `_scan_canvas_skills` filters tombstoned slugs out.  User-store
# skills are still unlinked outright.
def _skill_tombstone_path() -> "Path":
    return _user_skills_dir() / "_hidden-skills.json"


def _load_skill_tombstones() -> set:
    try:
        p = _skill_tombstone_path()
        if not p.exists():
            return set()
        data = json.loads(p.read_text(encoding="utf-8"))
        return set(data) if isinstance(data, list) else set()
    except Exception:
        return set()


def _add_skill_tombstone(slug: str) -> None:
    try:
        tomb = _load_skill_tombstones()
        tomb.add(slug)
        _skill_tombstone_path().write_text(
            json.dumps(sorted(tomb), indent=2), encoding="utf-8")
    except Exception:
        pass


def _clear_skill_tombstone(slug: str) -> None:
    """Used when a user re-saves a skill of a tombstoned slug — the new
    save should be visible again."""
    try:
        tomb = _load_skill_tombstones()
        if slug in tomb:
            tomb.discard(slug)
            _skill_tombstone_path().write_text(
                json.dumps(sorted(tomb), indent=2), encoding="utf-8")
    except Exception:
        pass


def _scan_canvas_skills() -> list:
    """Every canvas-format skill — shipped seeds + the user store —
    deduped by slug (a user save overrides a shipped seed of the same
    slug). The single resolver behind get_saved_skills + load_skill.

    AgDR-0033: tombstoned slugs (user-deleted shipped seeds) are
    filtered out."""
    out: dict[str, dict] = {}
    tombstones = _load_skill_tombstones()
    # Shipped first so a same-slug user save wins the dedup below.
    for root in (_shipped_skills_dir(), _user_skills_dir()):
        try:
            if not root.exists():
                continue
            files = sorted(root.glob("*.archhub-skill.json"))
        except Exception:
            continue
        for f in files:
            try:
                env = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(env, dict):
                continue
            slug = (env.get("slug")
                    or f.stem.replace(".archhub-skill", "")
                    or f.stem)
            graph = env.get("graph")
            if not isinstance(graph, dict):
                # Older files may store {nodes,wires} at top level.
                graph = env if ("nodes" in env or "wires" in env) else {}
            # SLICE G (AgDR-0010): surface the envelope's `meta` so
            # callers (load_skill, get_saved_skills) can branch on
            # `mode` (shared vs private). Older files lack meta —
            # default to private.
            _m = env.get("meta") if isinstance(env.get("meta"), dict) else {}
            out[slug] = {
                "slug":  slug,
                "name":  env.get("name") or slug,
                "path":  str(f),
                # AgDR-0033 — which store the file lives in, so
                # delete_saved_skill knows whether to unlink or tombstone.
                "shipped": (root == _shipped_skills_dir()),
                "graph": graph,
                "meta":  {
                    "mode":        str(_m.get("mode", "private")),
                    "description": str(_m.get("description") or ""),
                    "category":    str(_m.get("category") or ""),
                },
            }
    # AgDR-0033 — drop tombstoned slugs (user deleted a shipped seed).
    return [v for k, v in out.items() if k not in tombstones]


class ArchHubBridge(QObject):
    """Bridge object registered on QWebChannel under the name `archhub`."""

    # Signals visible to JS via QWebChannel auto-emit.
    chat_chunk      = pyqtSignal(str, str)       # (session_id, text)
    chat_reasoning  = pyqtSignal(str, str)       # (session_id, reasoning_step)
    chat_done       = pyqtSignal(str)            # (session_id)
    chat_error      = pyqtSignal(str, str)       # (session_id, error)
    hosts_changed   = pyqtSignal()
    sessions_changed = pyqtSignal()
    memory_changed  = pyqtSignal()
    skills_changed  = pyqtSignal()
    notice          = pyqtSignal(str, str)       # (level, text) — toast hook
    # v1.4 wire-as-data-bridge — runner pushes wire state into JS so
    # the canvas can colour wires by data state in real time.
    wire_state_changed = pyqtSignal(str, str, str)   # (edge_id, state, preview)
    # v1.5 thread-safety: emitted when an async run_workflow/run_node
    # worker thread finishes (success or error). Payload is JSON string
    # of the runner result so JSX can hand it back to the original
    # caller via `kind` ("workflow"|"node") + `request_id`.
    workflow_done   = pyqtSignal(str, str, str)      # (kind, request_id, result_json)
    # v1.5 thread-safety: emitted when a run_workflow / run_node worker
    # thread is about to start. The session_id is the runner's req_id so
    # the JS canvas can correlate started/done pairs and show spinners.
    workflow_started = pyqtSignal(str, str)          # (kind, request_id)
    trigger_fired   = pyqtSignal(str, str, str)     # (session_id, node_id, payload_json)
    agent_step_done = pyqtSignal(str)               # (result_json) — LLM-orchestrator finished
    connector_op_done = pyqtSignal(str)             # (result_json) — a connector op finished
    param_options_ready = pyqtSignal(str)           # (json) — dynamic dropdown options resolved
    node_created    = pyqtSignal(str)               # (json) — AI-minted custom node registered

    def __init__(self, *, router=None, manager=None, tools=None,
                  chat_widget=None, parent=None,
                  auto_extract_memory: bool = True):
        super().__init__(parent)
        self.router = router
        self.manager = manager
        self.tools = tools
        self.chat_widget = chat_widget
        # AgDR-0042 boot hook flag. True (default) populates the
        # shared-memory graph on the deferred boot thread; False skips
        # it. Tests that assert empty-graph slot behaviour pass False
        # to keep the test graph clean. Production paths always boot
        # with True so memory_query / memory_stats slots have data
        # without manual extractor invocation.
        self._auto_extract_memory = bool(auto_extract_memory)
        self._active_session_id: Optional[str] = None
        # AgDR-0036 Phase 1 — custom-node + connector registration are
        # the two heavy boot steps (custom_nodes.load_all scans disk;
        # load_all_connectors imports 16 connector modules, each
        # possibly importing a host SDK).  Run inline they delayed the
        # window paint by seconds.  Deferred onto a daemon thread; when
        # it finishes it emits `hosts_changed` so the JS side re-pulls
        # get_connectors / get_custom_nodes and the palette populates a
        # beat after first paint instead of blocking it.
        import threading as _threading

        def _deferred_boot():
            try:
                from workflows.custom_nodes import load_all as _load_custom
                _load_custom()
            except Exception:
                pass
            try:
                from connectors.base import load_all_connectors
                load_all_connectors()
            except Exception:
                pass
            try:
                self.hosts_changed.emit()
            except Exception:
                pass
            # AgDR-0042 — populate the shared-memory graph on boot so
            # memory_query / memory_stats slots have data without the
            # user / agent having to invoke extractors by hand. All
            # extractors are idempotent + safe to re-run (upserts),
            # so doing this every boot is the simplest correctness
            # contract. Failure (memory pkg missing, library empty,
            # etc.) is silent — memory is a feature, not a critical
            # boot path. Gated by auto_extract_memory constructor
            # flag — tests that assert empty-graph behaviour pass
            # False.
            if not self._auto_extract_memory:
                return
            try:
                from memory import MemoryGraph, default_graph_path
                from memory.extractors import (
                    extract_library, extract_decisions,
                    extract_turns, extract_projects,
                )
                g = MemoryGraph.open(default_graph_path())
                try:
                    extract_library(g, infer_wires=False)
                    extract_decisions(g)
                    # Composer-turn + project extractors are project-
                    # scoped; the M1 default project dir is where
                    # ai.plan writes its records.
                    import os as _os
                    base = _os.environ.get("LOCALAPPDATA") or str(
                        Path.home())
                    default_proj = Path(base) / "ArchHub" / "projects" / "default"
                    if default_proj.is_dir():
                        extract_turns(g, default_proj)
                    projects_root = Path(base) / "ArchHub" / "projects"
                    if projects_root.is_dir():
                        extract_projects(g, projects_root)
                finally:
                    g.close()
            except Exception:
                pass
        _threading.Thread(target=_deferred_boot, daemon=True,
                           name="archhub-deferred-boot").start()
        # ── Founder demand 2026-05-15: TRIGGER nodes go live. The
        # graph-trigger scheduler walks every session blob, finds in-graph
        # trigger nodes (cat='trigger'), and dispatches `trigger_fired`
        # when their schedule / file-watch / warning / event lands. Failure
        # to start must not block the bridge — it just means triggers
        # remain dormant until arm_triggers() is called explicitly.
        self._graph_triggers = None
        try:
            from session_io import SESSIONS_DIR
            from workflows.graph_triggers import GraphTriggerScheduler
            def _on_fire(sid: str, node_id: str, payload: dict) -> None:
                try:
                    self.trigger_fired.emit(sid, node_id, _safe_json(payload))
                except Exception:
                    pass
            self._graph_triggers = GraphTriggerScheduler(
                sessions_dir=SESSIONS_DIR,
                on_fire=_on_fire,
                tick_seconds=10.0,
            )
            self._graph_triggers.start()
        except Exception:
            self._graph_triggers = None

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
        for non-LLM hosts.

        AgDR-0035 — NEVER blocks the Qt main thread.  `detect_all_hosts`
        does filesystem walks + `tasklist` subprocess + port probes —
        measured at 3.7 s.  Running it in this slot froze the ENTIRE
        ArchHub UI (no typing, no drag, no right-click, no repaint) for
        3.7 s every call.  Now: return the cached value instantly +
        refresh on a background thread + emit `hosts_changed` when the
        fresh data lands."""
        def _work():
            from host_detector import detect_all_hosts
            return detect_all_hosts()
        return _safe_json(self._cached_async("hosts", _work, empty={}))

    # ─── AgDR-0036 — the non-blocking-slot MECHANISM ───────────────
    # Every @pyqtSlot that does I/O (HTTP, COM, subprocess, fs walk,
    # broker.forward, connector.probe) MUST route its slow work through
    # `_cached_async`.  The slot returns a cached value INSTANTLY; the
    # slow `work` callable runs on a bounded background pool; a signal
    # fires when fresh data lands so the JS side re-pulls.  This makes
    # it structurally impossible for a slow slot to freeze the Qt main
    # thread.  A guard test (test_no_blocking_slots) fails CI if a new
    # blocking slot is added.

    def _async_state(self):
        """Lazy, one-time per-bridge: {lock, cache, pool}.  Cache is a
        dict key -> (value, ts, busy).  One bounded ThreadPoolExecutor
        caps concurrent background work so rapid UI actions can't
        exhaust OS threads."""
        st = getattr(self, "_async_st", None)
        if st is None:
            import threading
            from concurrent.futures import ThreadPoolExecutor
            st = {
                "lock": threading.Lock(),
                "cache": {},
                "pool": ThreadPoolExecutor(
                    max_workers=6, thread_name_prefix="archhub-async"),
            }
            self._async_st = st
        return st

    def _cook_lock(self):
        """AgDR-0036 Phase 1 — one lock serialising graph cooks.
        `run_workflow` / `run_node` each build a FRESH WorkflowRunner
        (so there is no cross-call cache leak), but two cooks started
        in quick succession would hit the same host brokers /
        connectors concurrently with no coordination.  This lock makes
        the second cook queue behind the first.  The slot still returns
        its request_id instantly — only the background worker waits."""
        lk = getattr(self, "_cook_lk", None)
        if lk is None:
            import threading
            lk = threading.Lock()
            self._cook_lk = lk
        return lk

    def _bg_pool(self):
        """AgDR-0036 Phase 1 — one bounded pool for fire-and-forget
        bridge ops (connector runs, param-option fetches).  Caps OS
        threads at 8; extra work queues cheaply.  The old code did a
        raw `Thread(...).start()` per call — cascading param dropdowns
        + rapid connector runs could spawn unbounded threads and
        exhaust handles."""
        p = getattr(self, "_bg_pool_ex", None)
        if p is None:
            from concurrent.futures import ThreadPoolExecutor
            p = ThreadPoolExecutor(max_workers=8,
                                   thread_name_prefix="archhub-bg")
            self._bg_pool_ex = p
        return p

    def _cached_async(self, key: str, work, *, ttl: float = 30.0,
                      empty=None, signal_name: str = "hosts_changed"):
        """Non-blocking cache.  `work` is a zero-arg callable doing the
        slow I/O.  Returns the cached value instantly; refreshes on the
        background pool when stale; emits `signal_name` when fresh data
        lands.  Thread-safe — the cache dict + the busy check-then-set
        are guarded by one lock (fixes the AgDR-0035 race)."""
        import time as _t
        st = self._async_state()
        now = _t.time()
        with st["lock"]:
            ent = st["cache"].get(key)
            if ent and ent[0] is not None and (now - ent[1]) < ttl:
                return ent[0]
            cur = ent[0] if ent else None
            busy = ent[2] if ent else False
            kick = not busy
            if kick:
                st["cache"][key] = (cur, ent[1] if ent else 0.0, True)

        if kick:
            def _refresh():
                try:
                    result = work()
                except Exception as ex:
                    result = {"error": str(ex)}
                with st["lock"]:
                    st["cache"][key] = (result, _t.time(), False)
                try:
                    getattr(self, signal_name).emit()
                except Exception:
                    pass
            st["pool"].submit(_refresh)

        return cur if cur is not None else (
            empty if empty is not None else {})

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
                try: self.hosts_changed.emit()
                except Exception: pass
                return _safe_json({"ok": True})
            return _safe_json({"error": "manager has no toggle"})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Host connectors (the 16-connector op layer) ───────────────
    # Founder demand 2026-05-15: every host connector + its operations
    # exposed to the canvas. get_connectors returns metadata + the op
    # catalogue WITHOUT probing (probe is COM/HTTP — would block the Qt
    # main thread, the freeze bug). run_connector_op runs one op on a
    # background thread and emits connector_op_done.
    @pyqtSlot(result=str)
    def get_connectors(self) -> str:
        """Connector catalogue: host, mechanism, and every op's metadata.
        No probing here — status is fetched lazily via probe_connector."""
        try:
            from connectors.base import all_connectors
            out = []
            for c in all_connectors():
                try:
                    out.append({
                        "host": c.host,
                        "display_name": c.display_name,
                        "mechanism": c.mechanism,
                        "ops": [o.to_dict() for o in c.ops()],
                    })
                except Exception:
                    continue
            return _safe_json(out)
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def probe_connector(self, host_id: str) -> str:
        """Probe ONE connector's live status.

        AgDR-0036 — `c.probe()` is COM (`GetActiveObject`) or, for
        broker connectors, an HTTP `/ping` + a parallel 16-port range
        scan — measured 1-6 s.  The JSX calls this once per host pill,
        so the old synchronous slot froze the UI 1-6 s on every pill
        render.  Now routed through `_cached_async`: cached status
        returned instantly, real probe on the background pool, the
        `hosts_changed` signal re-pulls when the probe lands."""
        try:
            from connectors.base import get as _get_connector
            c = _get_connector(host_id)
            if c is None:
                return _safe_json({"status": "missing",
                                    "note": f"no connector '{host_id}'"})
            return _safe_json(self._cached_async(
                f"probe:{host_id}", lambda: c.probe(),
                empty={"status": "probing",
                       "note": "probe in progress"}))
        except Exception as ex:
            return _safe_json({"status": "missing", "note": str(ex)})

    @pyqtSlot(str, str, result=str)
    def run_connector_op(self, op_id: str, params_json: str) -> str:
        """Run one connector operation on a background thread; emit
        connector_op_done(result_json) when finished. Returns immediately
        so a slow COM / HTTP / broker call never freezes the UI."""
        import json as _json
        try:
            params = _json.loads(params_json) if params_json else {}
        except Exception as ex:
            return _safe_json({"async": False,
                                "error": f"bad params_json: {ex}"})
        if not isinstance(params, dict):
            params = {}

        def _runner():
            try:
                from connectors.base import run_op
                result = run_op(op_id, **params)
                payload = result.to_dict() if hasattr(result, "to_dict") \
                    else {"ok": False, "error": "bad op result",
                          "op_id": op_id}
            except Exception as ex:
                payload = {"ok": False, "op_id": op_id,
                           "error": f"{type(ex).__name__}: {ex}"}
            try:
                self.connector_op_done.emit(_safe_json(payload))
            except Exception:
                pass

        # AgDR-0036 Phase 1 — bounded pool, not a raw thread per call.
        self._bg_pool().submit(_runner)
        return _safe_json({"async": True, "op_id": op_id})

    @pyqtSlot(str, str, str, result=str)
    def request_param_options(self, req_id: str, source_op_id: str,
                               context_json: str) -> str:
        """Populate a parameter's dropdown dynamically. `source_op_id` is
        a connector op whose result IS the option list (e.g. a `worksheet`
        param has options_source='excel.list_worksheets'). Cascading: the
        context (the node's other param values) is passed through, filtered
        to the inputs the source op actually declares. Threaded — emits
        param_options_ready(req_id, json). Founder demand 2026-05-15:
        cascading dropdowns (document → views → levels)."""
        import json as _json
        try:
            ctx = _json.loads(context_json) if context_json else {}
        except Exception:
            ctx = {}
        if not isinstance(ctx, dict):
            ctx = {}

        def _runner():
            try:
                from connectors.base import run_op, get as _get_conn
                host = source_op_id.split(".", 1)[0] if "." in source_op_id else ""
                conn = _get_conn(host)
                op = conn.op(source_op_id) if conn else None
                # Filter context to the source op's declared inputs so a
                # fixed-arg fn never trips over an unexpected kwarg.
                if op is not None:
                    allowed = {p.id for p in (op.inputs or [])}
                    call_ctx = {k: v for k, v in ctx.items()
                                if k in allowed and v not in (None, "")}
                else:
                    call_ctx = {}
                result = run_op(source_op_id, **call_ctx)
                opts = []
                if getattr(result, "ok", False):
                    val = getattr(result, "value", None)
                    if isinstance(val, list):
                        for item in val:
                            if isinstance(item, dict):
                                opts.append({
                                    "id": str(item.get("id")
                                              or item.get("name")
                                              or item.get("value") or item),
                                    "label": str(item.get("label")
                                                  or item.get("name")
                                                  or item.get("title")
                                                  or item.get("id") or item),
                                })
                            else:
                                opts.append({"id": str(item), "label": str(item)})
                    elif isinstance(val, dict):
                        for k, v in val.items():
                            opts.append({"id": str(k), "label": str(k)})
                payload = {"req_id": req_id, "ok": getattr(result, "ok", False),
                           "options": opts,
                           "error": getattr(result, "error", "")}
            except Exception as ex:
                payload = {"req_id": req_id, "ok": False, "options": [],
                           "error": f"{type(ex).__name__}: {ex}"}
            try:
                self.param_options_ready.emit(_safe_json(payload))
            except Exception:
                pass

        # AgDR-0036 Phase 1 — bounded pool, not a raw thread per call.
        # Cascading param dropdowns can fire many of these per second.
        self._bg_pool().submit(_runner)
        return _safe_json({"async": True, "req_id": req_id})

    # ─── Sessions ───────────────────────────────────────────────
    @pyqtSlot(result=str)
    def get_sessions(self) -> str:
        try:
            from session_io import list_sessions_rich

            def _when(iso) -> str:
                """ISO timestamp -> short relative label for the session
                card ('just now', '3h', '2d', 'May 04'). The JSX card
                reads `s.when`; emitting nothing left it blank."""
                if not iso:
                    return ""
                try:
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(
                        str(iso).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    secs = (datetime.now(timezone.utc)
                            - dt).total_seconds()
                    if secs < 60:
                        return "just now"
                    if secs < 3600:
                        return f"{int(secs // 60)}m"
                    if secs < 86400:
                        return f"{int(secs // 3600)}h"
                    if secs < 7 * 86400:
                        return f"{int(secs // 86400)}d"
                    return dt.strftime("%b %d")
                except Exception:
                    return str(iso)[:10]

            from pathlib import Path
            out = []
            for r in list_sessions_rich():
                # list_sessions_rich returns one uniform dict shape:
                # {path, name, saved_at, host, last, messages,
                #  node_count}. Stable id = the file stem so
                # load_session can resolve it back to a path.
                stem = Path(str(r.get("path") or "")).stem.replace(
                    ".archhub-session", "")
                saved_at = str(r.get("saved_at") or "")
                out.append({
                    "id":         stem,
                    "title":      str(r.get("name") or stem),
                    "saved_at":   saved_at,
                    "when":       _when(saved_at),
                    # Saved-not-running sessions are "idle"; the card's
                    # state badge fell back to "unknown" without this.
                    "state":      "idle",
                    "host":       r.get("host") or [],
                    "last":       r.get("last") or "",
                    "messages":   r.get("messages") or 0,
                    "node_count": r.get("node_count") or 0,
                })
            return _safe_json(out)
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def create_session(self, title: str) -> str:
        """Mint a fresh empty session + return {id, title, saved_at}.
        JSX `+ new session` button calls this; bridge persists an empty
        graph immediately so save_graph keeps working without a special
        first-write code path.

        title is whatever the user typed (or "Untitled" if blank).
        Returns a JSON object with `id` (fresh slug) + `title`."""
        try:
            from datetime import datetime
            from session_io import SESSIONS_DIR
            SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
            t = (title or "").strip() or "Untitled session"
            # Slug: keep alnum + replace runs of other chars with `-`.
            import re as _re
            slug = _re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()
            if not slug:
                slug = "session"
            base = slug
            k = 2
            while (SESSIONS_DIR / f"{slug}.archhub-session.json").exists():
                slug = f"{base}-{k}"
                k += 1
            payload = {
                "id":    slug,
                "name":  t,
                "graph": {"nodes": [], "wires": []},
                "saved_at": datetime.utcnow().isoformat() + "Z",
            }
            (SESSIONS_DIR / f"{slug}.archhub-session.json").write_text(
                json.dumps(payload, indent=2), encoding="utf-8",
            )
            self._active_session_id = slug
            # Notify the JSX so the sidebar list refreshes without a
            # relaunch — fresh session should appear immediately.
            try: self.sessions_changed.emit()
            except Exception: pass
            return _safe_json({"id": slug, "title": t,
                                 "saved_at": payload["saved_at"]})
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

    # ─── Graph triggers (in-canvas TRIGGER nodes) ──────────────
    @pyqtSlot(result=str)
    def arm_triggers(self) -> str:
        try:
            if self._graph_triggers:
                self._graph_triggers.start()
                return _safe_json({"ok": True, "armed": True})
            return _safe_json({"ok": False, "error": "scheduler missing"})
        except Exception as ex:
            return _safe_json({"ok": False, "error": str(ex)})

    @pyqtSlot(result=str)
    def disarm_triggers(self) -> str:
        try:
            if self._graph_triggers:
                self._graph_triggers.stop()
                return _safe_json({"ok": True, "armed": False})
            return _safe_json({"ok": False, "error": "scheduler missing"})
        except Exception as ex:
            return _safe_json({"ok": False, "error": str(ex)})

    @pyqtSlot(result=str)
    def trigger_status(self) -> str:
        running = bool(self._graph_triggers
                        and self._graph_triggers._thread
                        and self._graph_triggers._thread.is_alive())
        return _safe_json({"running": running,
                            "tick_s": getattr(self._graph_triggers,
                                              "tick_seconds", None)})

    # ─── Local LLM detection ───────────────────────────────────
    # Founder demand 2026-05-15: ArchHub auto-utilises whatever local
    # AI stacks the user already has — Claude Desktop / CLI, Codex CLI,
    # Gemini CLI, LM Studio, Ollama, Jan, GPT4All, LocalAI, etc. The
    # detector runs filesystem + port checks; the JSX model picker
    # shows them grouped under LOCAL.
    @pyqtSlot(result=str)
    def get_local_llms(self) -> str:
        """AgDR-0035 — non-blocking.  `detect_all_local_llms` probes
        Ollama + LM Studio over HTTP (measured 2.2 s) — never run it
        on the Qt main thread.  Cached + background-refreshed."""
        def _work():
            from local_llm_detector import detect_all_local_llms
            return detect_all_local_llms()
        return _safe_json(self._cached_async("local_llms", _work, empty={}))

    @pyqtSlot(str, result=str)
    def set_model(self, model_id: str) -> str:
        # Founder demand 2026-05-15: model picker should actually pin the
        # router. Stash the chosen id on the bridge so send_chat_history
        # forwards it to router.complete (was hardcoded `auto`).
        try:
            self._selected_model = (model_id or "").strip() or "auto"
        except Exception:
            self._selected_model = "auto"
        try:
            if self.chat_widget and hasattr(self.chat_widget, "model_picker"):
                cw = self.chat_widget
                for i in range(cw.model_picker.count()):
                    if cw.model_picker.itemData(i) == model_id:
                        cw.model_picker.setCurrentIndex(i)
                        return _safe_json({"ok": True, "model": self._selected_model})
            return _safe_json({"ok": True, "model": self._selected_model,
                                "note": "picker widget not available"})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Chat ───────────────────────────────────────────────────
    @pyqtSlot(str, str)
    def send_chat(self, session_id: str, text: str) -> None:
        """2-arg overload — empty history. Delegates to the 3-arg form."""
        self.send_chat_history(session_id, text, "[]")

    @pyqtSlot(str, str, str)
    def send_chat_history(self, session_id: str, text: str,
                            history_json: str) -> None:
        """Fire-and-forget. JSX side passes the focused conversation
        node's `messages` array as JSON so the LLM gets full context.
        Emits chat_chunk / chat_done / chat_error back to JS on its own
        thread."""
        text = (text or "").strip()
        if not text:
            try: self.chat_error.emit(session_id, "empty prompt")
            except Exception: pass
            try: self.chat_done.emit(session_id)
            except Exception: pass
            return
        if not self.router:
            try: self.chat_error.emit(session_id, "router not wired")
            except Exception: pass
            try: self.chat_done.emit(session_id)
            except Exception: pass
            return

        # Parse the front-end's conversation array into the LLMRouter's
        # canonical [{role, content}, ...] shape. JSX uses {me, text}.
        history: list[dict] = []
        try:
            raw = json.loads(history_json or "[]") if history_json else []
        except Exception:
            raw = []
        for m in raw or []:
            if not isinstance(m, dict):
                continue
            role = "user" if m.get("me") else "assistant"
            content = m.get("text") or m.get("content") or ""
            # Founder demand 2026-05-14: composer attachments. JSX writes
            # attachments to disk via stash_attachment and stores paths
            # under message.images. Forward them so vision-capable
            # providers can read the blocks.
            images = m.get("images") or []
            if isinstance(content, str) and (content or images):
                entry: dict = {"role": role,
                                 "content": content if isinstance(content, str) else ""}
                if images:
                    entry["images"] = [str(p) for p in images if p]
                history.append(entry)
        # The fresh user turn the composer just submitted is the LAST
        # entry on the JSX side too (it was pushed before send). Keep
        # only entries strictly BEFORE that final user echo so we don't
        # double-send. If the last entry is the assistant placeholder,
        # drop it too (it's the empty bubble awaiting stream).
        while history and history[-1]["content"] in ("", text):
            history.pop()
        history.append({"role": "user", "content": text})
        # ── Founder bug (2026-05-15 → 16): the AI fabricated host facts
        # — wrote a fake <function_calls>/<function_result> block and
        # lied ("no files open in AutoCAD" while a drawing was open).
        #
        # ROOT CAUSE: the old patch here prepended a `role:"system_override"`
        # message that ALSO lied — "you have NO tools in this chat". Two
        # failures compounded: (1) `system_override` is not a valid
        # provider message role, so Anthropic 400'd and the request fell
        # back to a tool-less provider; (2) even the prompt text told the
        # model it had no tools. A tool-less model asked a factual
        # question fabricates.
        #
        # FIX: the conversation node IS tool-capable — the router hands
        # the model every reachable host's connector ops. Frame it with a
        # real `role:"system"` message (llm_router._complete_once now
        # folds system messages into the system prompt) that tells the
        # truth: you have tools, CALL them, never invent a result.
        history.insert(0, {"role": "system", "content": (
            "You are ArchHub's in-canvas copilot for AEC professionals, "
            "answering inside a conversation node on the user's graph. "
            "You have real tools — the connector operations for every "
            "reachable host (Revit, AutoCAD, Excel, Outlook, …). When "
            "the user asks anything factual about a host — what files "
            "are open, the current selection, warnings, inbox contents — "
            "CALL the matching tool and report the REAL result. Never "
            "invent a tool call, never write <function_calls> / "
            "<function_result> markup yourself, and never claim an "
            "action succeeded unless a tool actually returned that. If "
            "no tool fits, say so plainly. Be concise."
        )})

        def _runner():
            try:
                # Honor the user's selected model (set via set_model). If
                # the picker has never been touched, fall back to auto.
                # Strip the "local:" prefix synthetic ids from the picker
                # so the router doesn't try to look them up as KNOWN_MODELS.
                sel = getattr(self, "_selected_model", "") or "auto"
                if sel.startswith("local:"):
                    sel = "auto"
                model = sel
                # Track whether the provider actually pushed any chunks.
                # Founder bug 2026-05-14: reply appeared twice because the
                # provider streamed chunks AND we also emitted the final
                # response.text at the end. `streamed` flag on the response
                # is not reliable — some providers call on_chunk but leave
                # streamed=False. Use our own counter, not the flag.
                emitted_chunks = [0]
                def _on_chunk(piece: str) -> None:
                    if piece:
                        emitted_chunks[0] += 1
                        try: self.chat_chunk.emit(session_id, piece)
                        except Exception: pass
                def _on_reasoning(step: str) -> None:
                    # Forward each provider reasoning frame to JSX so the
                    # Conversation node renders a real trace instead of
                    # the v1.4 mocked 4-line block.
                    if step:
                        try: self.chat_reasoning.emit(session_id, str(step))
                        except Exception: pass
                response = self.router.complete(
                    history=history,
                    model=model,
                    on_chunk=_on_chunk,
                    on_reasoning=_on_reasoning,
                    on_tool_invocation=lambda _inv: None,
                )
                # Only emit response.text as a final chunk if NOTHING was
                # streamed. Otherwise we'd duplicate the entire message.
                if response is not None and emitted_chunks[0] == 0:
                    text_out = getattr(response, "text", "") or ""
                    if text_out:
                        try: self.chat_chunk.emit(session_id, text_out)
                        except Exception: pass
                try: self.chat_done.emit(session_id)
                except Exception: pass
            except Exception as ex:
                # Always emit BOTH chat_error and chat_done so the JS UI
                # doesn't hang waiting for a terminal signal.
                try: self.chat_error.emit(session_id, f"{type(ex).__name__}: {ex}")
                except Exception: pass
                try: self.chat_done.emit(session_id)
                except Exception: pass

        threading.Thread(target=_runner, daemon=True).start()

    # ─── Composer attachments (images / files / voice) ─────────
    # Founder demand 2026-05-14: composer accepts images, voice clips,
    # arbitrary files. JSX reads the file via FileReader → base64 →
    # this slot writes to a session-scoped attachment dir and returns
    # the absolute path. Multimodal-capable providers (Anthropic,
    # OpenAI, Google) read the path back via the provider client.
    @pyqtSlot(str, str, str, result=str)
    def stash_attachment(self, filename: str, mime: str,
                          base64_data: str) -> str:
        """Stash a base64-encoded attachment to disk + return its abs
        path. Filename + mime are passed through for metadata; we
        sanitise filename to a safe slug and pick the extension off
        mime when filename has none.
        """
        try:
            import base64
            from session_io import SESSIONS_DIR
            import re as _re
            stash_dir = SESSIONS_DIR / "_attachments"
            stash_dir.mkdir(parents=True, exist_ok=True)
            # Strip data: URL prefix if present.
            data = base64_data or ""
            if data.startswith("data:"):
                comma = data.find(",")
                if comma > 0:
                    data = data[comma+1:]
            # Sanitise filename.
            stem = _re.sub(r"[^A-Za-z0-9._-]", "_",
                            (filename or "attachment").strip())[:60]
            if "." not in stem:
                ext_map = {
                    "image/png": ".png", "image/jpeg": ".jpg",
                    "image/gif": ".gif", "image/webp": ".webp",
                    "audio/webm": ".webm", "audio/mp3": ".mp3",
                    "audio/wav": ".wav", "application/pdf": ".pdf",
                    "text/plain": ".txt",
                }
                stem += ext_map.get(mime or "", ".bin")
            from datetime import datetime
            stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
            path = stash_dir / f"{stamp}_{stem}"
            path.write_bytes(base64.b64decode(data))
            return _safe_json({"ok": True, "path": str(path),
                                "name": path.name, "mime": mime or "",
                                "size": path.stat().st_size})
        except Exception as ex:
            return _safe_json({"ok": False,
                                "error": f"{type(ex).__name__}: {ex}"})

    # ─── Settings ──────────────────────────────────────────────
    @pyqtSlot()
    def open_settings(self) -> None:
        """Open the native SettingsDialog on the Qt main thread."""
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._open_settings_safe)

    def _open_settings_safe(self) -> None:
        if not (self.router and self.manager and self.tools):
            try:
                self.notice.emit("warning",
                    "Settings needs router + manager + tools — initialise the bridge first.")
            except Exception:
                pass
            return
        try:
            from settings_dialog import SettingsDialog
            parent = self.parent()
            # SettingsDialog.__init__(router, parent=None). Keep manager/
            # tools out of the call sig — they're not consumed there. We
            # try both signatures so an alternate dialog build (one that
            # WANTS manager/tools) still works.
            try:
                dlg = SettingsDialog(router=self.router, parent=parent,
                                       manager=self.manager,
                                       tools=self.tools)
            except TypeError:
                dlg = SettingsDialog(self.router, parent)
            dlg.exec()
        except Exception as ex:
            try: self.notice.emit("error", f"Settings unavailable: {ex}")
            except Exception: pass

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
                try: self.notice.emit("error", f"Pricing unavailable: {ex}")
                except Exception: pass

    # ─── Memory ────────────────────────────────────────────────
    # AgDR-0036 — both reads hit the ArchHub cloud over HTTP.  Run on
    # the Qt main thread they froze the UI for the full HTTP timeout
    # on a slow / down network.  Routed through `_cached_async` — the
    # `memory_changed` signal re-pulls when fresh data lands.
    @pyqtSlot(result=str)
    def get_memory_stats(self) -> str:
        def _work():
            from cloud_client import memory_stats
            return memory_stats() or {}
        return _safe_json(self._cached_async(
            "memory_stats", _work, empty={},
            signal_name="memory_changed"))

    @pyqtSlot(str, result=str)
    def list_memory_facts(self, q: str = "") -> str:
        def _work():
            from cloud_client import _request
            path = f"/v1/memory/facts?q={q}" if q else "/v1/memory/facts"
            r = _request("GET", path)
            if r["status"] != "ok":
                return {"error": "not authed or cloud down"}
            return r.get("json") or {}
        return _safe_json(self._cached_async(
            f"memory_facts:{q}", _work, empty={},
            signal_name="memory_changed"))

    @pyqtSlot(str, str, result=str)
    def add_memory_fact(self, text: str, scope: str = "user") -> str:
        try:
            from cloud_client import _request
            r = _request("POST", "/v1/memory/facts",
                          body={"text": text, "scope": scope})
            if r["status"] != "ok":
                return _safe_json({"error": "cloud unavailable"})
            try: self.memory_changed.emit()
            except Exception: pass
            return _safe_json(r.get("json") or {})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Memory mutations ──────────────────────────────────────
    @pyqtSlot(str, str, result=str)
    def update_memory_fact(self, fact_id: str, text: str) -> str:
        try:
            fid_int = int(fact_id)
            from cloud_client import _request
            r = _request("PUT", f"/v1/memory/facts/{fid_int}",
                          body={"text": text})
            if r["status"] != "ok":
                return _safe_json({"error": "update failed"})
            try: self.memory_changed.emit()
            except Exception: pass
            return _safe_json(r.get("json") or {})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def forget_memory_fact(self, fact_id: str) -> str:
        try:
            fid_int = int(fact_id)
            from cloud_client import _request
            r = _request("DELETE", f"/v1/memory/facts/{fid_int}")
            if r["status"] != "ok":
                return _safe_json({"error": "forget failed"})
            try: self.memory_changed.emit()
            except Exception: pass
            return _safe_json({"ok": True, "id": fid_int})
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

    # ─── Node grammar (the JSX canvas palette source) ──────────
    @pyqtSlot(result=str)
    def get_node_grammar(self) -> str:
        """The node grammar — the ~12-primitive set the JSX canvas
        builds its node palette from. ONE source of truth
        (`app/workflows/node_grammar.py`); the JSX side must not keep a
        parallel node list — that parallel list (the 80-node
        `LM_LIBRARY`) was the drift the redesign kills. See
        `docs/NODE_GRAMMAR.md`."""
        try:
            from workflows.node_grammar import grammar_payload
            return _safe_json(grammar_payload())
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── M4 (AgDR-0021) — Plan history surface ─────────────────
    @pyqtSlot(str, int, result=str)
    def get_plan_history(self, project_dir: str = "",
                          limit: int = 50) -> str:
        """List the most-recent `limit` AI-plan records persisted by
        `ai.plan` cooks under `<project_dir>/.archhub/plans/`.

        Empty project_dir → use the default SpeckleWire project dir
        (the canonical `%LOCALAPPDATA%/ArchHub/projects/default`).

        Returns JSON: `{records:[…], count:N}` or `{error:"…"}`.
        Each record carries `plan_id`, `prompt`, `model`, `plan`,
        `result`, `status`, `error`, `ts` — JSX renders these in
        the Composer history panel (M4 phase 2).
        """
        try:
            from plan_history import PlanHistory
            pdir = (project_dir or "").strip()
            if not pdir:
                from speckle_wire import default_project_dir
                pdir = str(default_project_dir())
            history = PlanHistory(pdir)
            records = history.list_records(limit=max(1, int(limit)))
            return _safe_json({"records": records,
                                "count": len(records),
                                "project_dir": pdir})
        except Exception as ex:
            return _safe_json({"error": f"{type(ex).__name__}: {ex}"})

    @pyqtSlot(str, str, result=str)
    def get_plan_record(self, plan_id: str,
                         project_dir: str = "") -> str:
        """Load one plan record by id. Returns the record JSON or
        `{error:"not_found"}`."""
        try:
            from plan_history import PlanHistory
            pdir = (project_dir or "").strip()
            if not pdir:
                from speckle_wire import default_project_dir
                pdir = str(default_project_dir())
            history = PlanHistory(pdir)
            rec = history.load((plan_id or "").strip())
            if rec is None:
                return _safe_json({"error": "not_found"})
            return _safe_json(rec)
        except Exception as ex:
            return _safe_json({"error": f"{type(ex).__name__}: {ex}"})

    @pyqtSlot(str, str, result=str)
    def delete_plan_record(self, plan_id: str,
                            project_dir: str = "") -> str:
        """Drop one record from disk. Returns `{ok:true}` or
        `{ok:false, error:"…"}`."""
        try:
            from plan_history import PlanHistory
            pdir = (project_dir or "").strip()
            if not pdir:
                from speckle_wire import default_project_dir
                pdir = str(default_project_dir())
            history = PlanHistory(pdir)
            ok = history.delete((plan_id or "").strip())
            return _safe_json({"ok": bool(ok)})
        except Exception as ex:
            return _safe_json({"ok": False,
                                "error": f"{type(ex).__name__}: {ex}"})

    @pyqtSlot(str, str, result=str)
    def flatten_chain_to_code(self, graph_json: str,
                                node_ids_json: str) -> str:
        """SLICE L (AgDR-0020 follow-up). Replace the selected chain
        with one `code.expression` node carrying the equivalent
        Python expression.

        Args:
          graph_json — the current LM_GRAPH JSON.
          node_ids_json — JSON array of the selected node ids.

        Returns JSON with either:
          {graph, new_node_id, expression}  — rewrite successful, JSX
              should replace LM_GRAPH with `graph` + focus `new_node_id`
          {error: "..."}                    — chain not flattenable;
              JSX shows the error in a toast
        """
        try:
            import json as _json
            from workflows.flatten_to_code import flatten_chain
            graph = _json.loads(graph_json or "{}")
            node_ids = _json.loads(node_ids_json or "[]")
            if not isinstance(graph, dict):
                return _safe_json({"error": "graph_json must be an object"})
            if not isinstance(node_ids, list):
                return _safe_json({"error": "node_ids_json must be an array"})
            result = flatten_chain(graph, node_ids)
            return _safe_json(result)
        except Exception as ex:
            return _safe_json({"error": f"{type(ex).__name__}: {ex}"})

    # ─── Library (LIBRARY-FIRST mandate — AgDR-0013/0014) ──────
    # Five slots back the Composer panel + the JSX library browser:
    # search, list_node_types, inspect, create_node_type, delete_node_type.
    # They reuse the same in-process registry the LLM tool layer uses
    # (`app/library.py`); the JSX side reads from disk via these slots,
    # the LLM side reads via ToolEngine — both surfaces hit one source
    # of truth.

    @pyqtSlot(str, str, int, result=str)
    def library_search(self, intent: str, category: str = "",
                        limit: int = 8) -> str:
        """Search the in-process library for matches to an intent string.

        Returns `{results: [...], count: N}` or `{error: ...}`.
        Search algorithm + thresholds locked in AgDR-0014 (Token-based
        ranking + ≥30 match threshold).
        """
        try:
            self._library_bootstrap()
            import library as _lib
            results = _lib.search(
                intent=intent or "",
                category=(category or None),
                limit=int(limit or 8),
            )
            return _safe_json({"results": results, "count": len(results)})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def library_list_node_types(self, category: str = "") -> str:
        """List every registered node-type, optionally filtered by
        category. Backs the JSX Library browser tab.
        """
        try:
            self._library_bootstrap()
            import library as _lib
            items = _lib.list_node_types(category=(category or None))
            return _safe_json({"items": items, "count": len(items)})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def library_inspect(self, node_type: str) -> str:
        """Return the full ModularNodeSpec for one registered type.

        On unknown type: `{error: <reason>, code: 'unknown_type'}`.
        """
        try:
            self._library_bootstrap()
            import library as _lib
            spec = _lib.inspect((node_type or "").strip())
            return _safe_json({"spec": spec})
        except Exception as ex:
            from library import UnknownTypeError
            if isinstance(ex, UnknownTypeError):
                return _safe_json({"error": str(ex), "code": "unknown_type"})
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def library_create_node_type(self, spec_json: str) -> str:
        """Register a new modular node-type. `spec_json` is the
        serialised ModularNodeSpec dict.

        On validator failure: `{error: <reason>, violations: [...]}` so
        the JSX caller can surface every gap in one form-validation
        round-trip (mirrors the LLM Layer-3 gate's behaviour).
        """
        try:
            self._library_bootstrap()
            spec = json.loads(spec_json) if isinstance(spec_json, str) else {}
            if not isinstance(spec, dict):
                return _safe_json({
                    "error": "spec_json must be a JSON object",
                })
            import library as _lib
            result = _lib.create_node_type(spec)
            # Auto-persist so the JSX-created node survives a restart.
            try:
                _lib.save_to_disk()
            except Exception:
                # Persistence failure is non-fatal — registration succeeded
                # in-process. Surface a warning in the response.
                pass
            return _safe_json({**result, "ok": True})
        except Exception as ex:
            from library import (
                DuplicateTypeError,
                RegistrationError,
            )
            if isinstance(ex, RegistrationError):
                return _safe_json({
                    "error": str(ex),
                    "violations": ex.violations,
                })
            if isinstance(ex, DuplicateTypeError):
                return _safe_json({
                    "error": str(ex),
                    "code": "duplicate_type",
                })
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def library_delete_node_type(self, node_type: str) -> str:
        """Delete a registered node-type. JSX side surfaces a
        confirmation dialog before invoking this.

        On unknown type: `{error: ..., code: 'unknown_type'}`.
        """
        try:
            self._library_bootstrap()
            import library as _lib
            result = _lib.delete_node_type((node_type or "").strip())
            try:
                _lib.save_to_disk()
            except Exception:
                pass
            return _safe_json({**result})
        except Exception as ex:
            from library import UnknownTypeError
            if isinstance(ex, UnknownTypeError):
                return _safe_json({"error": str(ex), "code": "unknown_type"})
            return _safe_json({"error": str(ex)})

    def _library_bootstrap(self) -> None:
        """One-shot library bootstrap on first access.

        - Load registry from disk if it exists.
        - Otherwise seed with the AgDR-0014 modular primitives.
        Idempotent — subsequent calls are no-ops.
        """
        if getattr(self, "_lib_booted", False):
            return
        try:
            import library as _lib
            import library_persistence as _lp

            loaded = 0
            try:
                if _lp.default_registry_path().exists():
                    loaded = _lib.load_from_disk()
            except Exception:
                loaded = 0

            if loaded == 0:
                # First run — seed with the AgDR-0014 modular primitives.
                from library_seeds import seed_library
                seed_library()
                try:
                    _lib.save_to_disk()
                except Exception:
                    # Seed survived in-process even if disk write failed.
                    pass
        finally:
            self._lib_booted = True

    # ─── Saved skills (canvas-format store) ────────────────────
    @pyqtSlot(result=str)
    def get_saved_skills(self) -> str:
        """List canvas-format skills — the Skills panel's source.

        Reads the SAME store load_skill loads from
        (_scan_canvas_skills: shipped seeds + the user store, canvas
        format), so every skill the panel shows is actually spawnable.
        Founder bug 2026-05-18: this listed the engine-format
        skills.library while load_skill globbed app/skills/ — list and
        loader pointed at different stores, so every click 404'd
        ('empty & not working')."""
        try:
            out = []
            for s in _scan_canvas_skills():
                graph = s.get("graph") or {}
                meta = s.get("meta") if isinstance(s.get("meta"), dict) else {}
                # G2 (slice K): surface mode + description + category so the
                # JSX panel can render a mode badge AND the Promote
                # Private→Shared action knows what to re-save with.
                out.append({
                    "id":          s["slug"],
                    "name":        s["name"],
                    "args":        "",
                    "when":        "",
                    "node_count":  len(graph.get("nodes") or []),
                    "mode":        meta.get("mode") or "private",
                    "description": meta.get("description") or "",
                    "category":    meta.get("category") or "",
                })
            return _safe_json(out)
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def promote_skill_to_shared(self, skill_id: str) -> str:
        """G2 (slice K) — flip a Private skill's mode to Shared.

        Loads the existing skill envelope, re-saves with `meta.mode='shared'`
        so future spawns use the subgraph-reference semantics (edits
        propagate). Returns `{ok:true, id}` on success or `{error:...}`.
        """
        try:
            sid = (skill_id or "").strip()
            if not sid:
                return _safe_json({"error": "skill_id is required"})
            match = next(
                (s for s in _scan_canvas_skills()
                 if s["slug"] == sid or s["name"] == sid),
                None,
            )
            if match is None:
                return _safe_json({"error": f"skill not found: {sid}"})
            graph = match.get("graph") or {}
            meta = match.get("meta") if isinstance(match.get("meta"), dict) else {}
            new_meta = {**meta, "mode": "shared"}
            payload = {
                "nodes": list(graph.get("nodes") or []),
                "wires": list(graph.get("wires") or []),
                "meta":  new_meta,
            }
            # save_as_skill re-writes the envelope with the new meta
            # (and existing meta.mode is replaced by the payload's).
            self.save_as_skill(match["name"], json.dumps(payload))
            return _safe_json({"ok": True, "id": sid, "mode": "shared"})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def load_skill(self, skill_id: str) -> str:
        """Load a saved skill's graph for splicing onto the canvas.

        Resolves `skill_id` (slug or name) against the SAME store
        get_saved_skills lists — _scan_canvas_skills() — and returns
        the canvas graph `{nodes, wires, name}` the JSX `onSpawnSkill`
        handler offsets + inserts. Returns an `{error: ...}` envelope
        when the skill cannot be found.

        Founder bug 2026-05-18: the panel listed skills.library but
        load_skill globbed app/skills/ — a different store — so
        spawning ANY listed skill failed. List + load now share one
        resolver (_scan_canvas_skills), so the two cannot drift."""
        try:
            sid = (skill_id or "").strip()
            if not sid:
                return _safe_json({"error": "skill_id is required"})
            match = next(
                (s for s in _scan_canvas_skills()
                 if s["slug"] == sid or s["name"] == sid),
                None,
            )
            if match is None:
                return _safe_json({"error": f"skill not found: {sid}"})
            graph = match.get("graph") or {}
            # SLICE G (AgDR-0010): surface the envelope's `meta` so the
            # JSX spawn handler can branch on `mode` (shared vs private).
            _meta = match.get("meta") if isinstance(match.get("meta"), dict) else {}
            return _safe_json({
                "nodes": list(graph.get("nodes") or []),
                "wires": list(graph.get("wires") or []),
                "name":  match.get("name") or sid,
                "slug":  match.get("slug") or sid,
                "meta":  {
                    "mode":        str(_meta.get("mode", "private")),
                    "description": str(_meta.get("description") or ""),
                    "category":    str(_meta.get("category") or ""),
                },
            })
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
            configured = set((self.router.configured_providers()
                              if self.router else None) or [])
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
            try: self.sessions_changed.emit()
            except Exception: pass
            return _safe_json({"ok": True, "session_id": sid,
                                "nodes": len(graph.get("nodes") or []),
                                "wires": len(graph.get("wires") or [])})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── AgDR-0042 D1·C — shared-memory graph access ─────────────
    @pyqtSlot(str, result=str)
    def memory_query(self, args_json: str) -> str:
        """Query the shared-memory knowledge graph from the JSX side.

        AgDR-0042 — exposes `memory.query()` as a bridge slot so the
        Composer canvas + Library panel can search without an LLM
        tool round-trip. Args envelope is the same shape the
        memory_query LLM tool accepts:
          {question: str, kinds?: [str], limit?: int, min_score?: float}
        Returns the same response envelope:
          {status: 'ok', results: [{id, kind, label, score, why}], count}
        Errors surface as {status:'error', error:str} so the panel
        can render a single-line banner without crashing."""
        try:
            import json as _json
            args = _json.loads(args_json or "{}")
            if not isinstance(args, dict):
                return _safe_json({"status": "error",
                                    "error": "args must be an object"})
            if self.tools is None:
                return _safe_json({"status": "error",
                                    "error": "tool engine not initialised"})
            res = self.tools.invoke("memory_query", args)
            return _safe_json(res)
        except Exception as ex:
            return _safe_json({"status": "error",
                                "error": f"{type(ex).__name__}: {ex}"})

    @pyqtSlot(result=str)
    def memory_stats(self) -> str:
        """Snapshot of the memory graph — node count by kind +
        community count. Cheap (single SQL COUNT per kind). Used by
        the Library panel header + the upcoming community-grouped
        Library UI."""
        try:
            from memory import MemoryGraph, community_stats
            g = MemoryGraph.open()
            try:
                kinds = ("capability", "skill", "turn", "tool",
                         "decision", "project", "design")
                counts = {k: g.count_nodes(kind=k) for k in kinds}
                stats = community_stats(g)
                return _safe_json({
                    "status": "ok",
                    "total_nodes": g.count_nodes(),
                    "total_edges": g.count_edges(),
                    "by_kind": counts,
                    "communities_total": len(stats),
                    "communities_top": stats[:5],
                })
            finally:
                g.close()
        except Exception as ex:
            return _safe_json({"status": "error",
                                "error": f"{type(ex).__name__}: {ex}"})

    # ─── AgDR-0041 P5 — live validator ─────────────────────────────
    @pyqtSlot(str, result=str)
    def graph_validate(self, graph_json: str) -> str:
        """Validate a canvas graph snapshot and return structured issues.

        AgDR-0041 P5 — debounced on every canvas edit. JSX calls this
        and paints wires + nodes green/yellow/red from the issue list.
        Returns same shape as tool_engine `graph_validate` handler:
          {status, issues:[{level,code,node_id,edge_id,msg}],
           errors, warnings, valid}
        On parse failure returns `{status:"error", error:<reason>}` so
        the panel can show a single-line banner instead of dying."""
        try:
            import json as _json
            graph = _json.loads(graph_json or "{}")
            if not isinstance(graph, dict):
                return _safe_json({"status": "error",
                                    "error": "graph must be an object"})
            if self.tools is None:
                return _safe_json({"status": "error",
                                    "error": "tool engine not initialised"})
            res = self.tools.invoke("graph_validate", {"graph": graph})
            return _safe_json(res)
        except Exception as ex:
            return _safe_json({"status": "error",
                                "error": f"{type(ex).__name__}: {ex}"})

    # ─── AgDR-0041 P4 — delete-with-auto-bridge ────────────────────
    @pyqtSlot(str, str, result=str)
    def graph_on_node_delete(self, node_id: str, graph_json: str) -> str:
        """Preview the impact of deleting a node BEFORE removing it.

        Returns one of:
          - {action:"silent_delete"}  — no incident wires; safe to drop.
          - {action:"auto_bridge", wires:[…]} — upstream src type matches
            downstream dst type; UI applies those wires after delete.
          - {action:"broken_wire", broken:[…], compatible:[…]} — type
            mismatch; UI surfaces BrokenWireDialog with recovery options
            (insert adapter / restore / swap downstream).
        Always returns `status: 'ok' | 'error'`."""
        try:
            import json as _json
            graph = _json.loads(graph_json or "{}")
            if not isinstance(graph, dict):
                return _safe_json({"status": "error",
                                    "error": "graph must be an object"})
            if self.tools is None:
                return _safe_json({"status": "error",
                                    "error": "tool engine not initialised"})
            res = self.tools.invoke("graph_on_node_delete",
                                     {"node_id": (node_id or "").strip(),
                                      "graph": graph})
            return _safe_json(res)
        except Exception as ex:
            return _safe_json({"status": "error",
                                "error": f"{type(ex).__name__}: {ex}"})

    # ─── AgDR-0041 P3 — freeze / unfreeze a node ───────────────────
    @pyqtSlot(str, bool, result=str)
    def node_freeze(self, node_id: str, state: bool) -> str:
        """Freeze (state=True) or unfreeze (state=False) a node.
        Returns the set_node delta the JSX merges into LM_GRAPH so the
        ❄ badge appears + the runner short-circuits the node's cook to
        its cached value next time the graph runs."""
        try:
            if self.tools is None:
                return _safe_json({"status": "error",
                                    "error": "tool engine not initialised"})
            res = self.tools.invoke("node_freeze",
                                     {"node_id": (node_id or "").strip(),
                                      "state": bool(state)})
            return _safe_json(res)
        except Exception as ex:
            return _safe_json({"status": "error",
                                "error": f"{type(ex).__name__}: {ex}"})

    # ─── AgDR-0041 P6 — bypass / un-bypass a node ──────────────────
    @pyqtSlot(str, bool, result=str)
    def node_bypass(self, node_id: str, state: bool) -> str:
        """Bypass (state=True) or un-bypass (state=False) a node.
        Returns the set_node delta the JSX merges into LM_GRAPH so the
        ○ badge appears + the runner skips the node's executor +
        passes upstream input through to downstream output."""
        try:
            if self.tools is None:
                return _safe_json({"status": "error",
                                    "error": "tool engine not initialised"})
            res = self.tools.invoke("node_bypass",
                                     {"node_id": (node_id or "").strip(),
                                      "state": bool(state)})
            return _safe_json(res)
        except Exception as ex:
            return _safe_json({"status": "error",
                                "error": f"{type(ex).__name__}: {ex}"})

    # ─── AgDR-0041 P2 — type-compatible swap suggestions ───────────
    @pyqtSlot(str, int, result=str)
    def library_suggest_swaps(self, node_type: str, limit: int) -> str:
        """Find registered types whose I/O signature matches the target.
        Powers the right-click 'swap with…' context menu. Returns
        ranked alternatives + their port shapes; the UI presents these,
        click swaps the node in place + runner re-cooks downstream."""
        try:
            if self.tools is None:
                return _safe_json({"status": "error",
                                    "error": "tool engine not initialised"})
            args = {"type": (node_type or "").strip(),
                    "limit": int(limit) if limit else 10}
            res = self.tools.invoke("library_suggest_swaps", args)
            return _safe_json(res)
        except Exception as ex:
            return _safe_json({"status": "error",
                                "error": f"{type(ex).__name__}: {ex}"})

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
        """Run the entire workflow (Houdini render) in a background
        thread. Cooks every sink node; pulls cascade upstream
        automatically; frozen nodes are skipped. Wire-state updates
        stream over `wire_state_changed`; the final result is delivered
        via the `workflow_done` signal payload
        ("workflow", request_id, result_json) so the Qt main thread
        never blocks. Returns the request_id immediately."""
        import json as _json
        import time as _time
        req_id = f"wf-{int(_time.time()*1000)}-{id(self)}"
        graph: dict | None = None
        try:
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
                    try: self.workflow_done.emit("workflow", req_id,
                                                  _safe_json({"error": "session not found"}))
                    except Exception: pass
                    return _safe_json({"request_id": req_id,
                                         "error": "session not found"})
                session, _name, _m = load_session_with_messages(p)
                graph = session.graph or {}
        except Exception as ex:
            payload = _safe_json({"error": str(ex)})
            try: self.workflow_done.emit("workflow", req_id, payload)
            except Exception: pass
            return _safe_json({"request_id": req_id, "error": str(ex)})

        def _worker():
            try: self.workflow_started.emit("workflow", req_id)
            except Exception: pass
            try:
                from workflows.runner import WorkflowRunner
                from workflows.node_grammar import normalize_canvas_graph
                # Stamp engine `type` + `config` onto canvas nodes so the
                # runner can dispatch — the canvas/engine "one node model"
                # (docs/NODE_GRAMMAR.md). Before this, canvas nodes carried
                # only `cat` and every Run errored "no executor for ''".
                runner = WorkflowRunner(normalize_canvas_graph(graph),
                                         router=self.router,
                                         tool_engine=self.tools,
                                         manager=self.manager)
                def _emit_wire_state(eid, state, preview):
                    try: self.wire_state_changed.emit(eid, state, preview)
                    except Exception: pass
                runner.on_wire_state(_emit_wire_state)
                # AgDR-0036 Phase 1 — serialise: a 2nd Run queues here.
                with self._cook_lock():
                    result = runner.run_all()
                payload = _safe_json(result)
            except Exception as ex:
                payload = _safe_json({"error": str(ex)})
            try: self.workflow_done.emit("workflow", req_id, payload)
            except Exception: pass

        threading.Thread(target=_worker, daemon=True).start()
        return _safe_json({"request_id": req_id, "status": "started"})

    @pyqtSlot(str, str, str, result=str)
    def run_node(self, session_id: str, node_id: str,
                  graph_json: str = "") -> str:
        """Cook a node via WorkflowRunner.pull in a worker thread —
        lazy upstream walk + dirty cascade + caching. Emits wire_state
        signals as values flow so the JS canvas can light up wires in
        real time, then emits `workflow_done("node", request_id,
        result_json)` when finished. Returns the request_id
        synchronously so the Qt main thread never blocks.

        graph_json is optional. When given, the runner runs against
        that in-memory shape (no disk roundtrip). When empty, we read
        session.graph from the saved session.
        """
        import json as _json
        import time as _time
        req_id = f"nd-{int(_time.time()*1000)}-{id(self)}"
        graph: dict | None = None
        try:
            from pathlib import Path
            sid = session_id or "workspace"
            if graph_json:
                try:
                    graph = _json.loads(graph_json)
                except Exception as ex:
                    payload = _safe_json({"error": f"bad graph_json: {ex}"})
                    try: self.workflow_done.emit("node", req_id, payload)
                    except Exception: pass
                    return _safe_json({"request_id": req_id,
                                         "error": f"bad graph_json: {ex}"})
            else:
                from session_io import (
                    SESSIONS_DIR, load_session_with_messages,
                )
                p = Path(sid)
                if not p.exists():
                    p = SESSIONS_DIR / f"{sid}.archhub-session.json"
                if not p.exists():
                    payload = _safe_json({"error": "session not found"})
                    try: self.workflow_done.emit("node", req_id, payload)
                    except Exception: pass
                    return _safe_json({"request_id": req_id,
                                         "error": "session not found"})
                session, _name, _m = load_session_with_messages(p)
                graph = session.graph or {}
        except Exception as ex:
            payload = _safe_json({"error": str(ex)})
            try: self.workflow_done.emit("node", req_id, payload)
            except Exception: pass
            return _safe_json({"request_id": req_id, "error": str(ex)})

        def _worker():
            try: self.workflow_started.emit("node", req_id)
            except Exception: pass
            try:
                from workflows.runner import WorkflowRunner
                from workflows.node_grammar import normalize_canvas_graph
                # Stamp engine `type` + `config` onto canvas nodes so the
                # runner can dispatch — the canvas/engine "one node model"
                # (docs/NODE_GRAMMAR.md). Before this, canvas nodes carried
                # only `cat` and every Run errored "no executor for ''".
                runner = WorkflowRunner(normalize_canvas_graph(graph),
                                         router=self.router,
                                         tool_engine=self.tools,
                                         manager=self.manager)
                def _emit_wire_state(eid, state, preview):
                    try: self.wire_state_changed.emit(eid, state, preview)
                    except Exception: pass
                runner.on_wire_state(_emit_wire_state)
                # AgDR-0036 Phase 1 — serialise with run_workflow so two
                # cooks never hit the same host brokers concurrently.
                with self._cook_lock():
                    result = runner.pull(node_id)
                payload = _safe_json(result if isinstance(result, dict)
                                       else {"value": result})
            except Exception as ex:
                payload = _safe_json({"error": str(ex)})
            try: self.workflow_done.emit("node", req_id, payload)
            except Exception: pass

        threading.Thread(target=_worker, daemon=True).start()
        return _safe_json({"request_id": req_id, "status": "started"})

    # ─── Host session + document pickers ───────────────────────
    # Founder direction (2026-05-14): host tools should let the user
    # pick WHICH version of the host (Revit 2024 vs Revit 2025) AND
    # WHICH document inside that session. Below two slots feed the
    # dynamic <select> dropdowns in studio-lm.jsx for host.* nodes.
    @pyqtSlot(str, result=str)
    def list_host_sessions(self, family: str) -> str:
        """Return all running sessions for a host family.
        Shape: [{session_id, version, port, opened_doc, host_alive}].

        AgDR-0036 — `_list_host_sessions_impl` does broker HTTP probes
        + a parallel port scan (+ COM MAPI walk for Outlook).  Routed
        through `_cached_async` so the host-node dropdown never freezes
        the UI."""
        try:
            family = (family or "").strip().lower()
            return _safe_json(self._cached_async(
                f"hsess:{family}",
                lambda: _list_host_sessions_impl(family),
                empty=[]))
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, str, result=str)
    def list_host_documents(self, family: str,
                             session_id: str = "") -> str:
        """List documents inside the chosen session.
        Shape: [{path, title, active, kind}].

        AgDR-0036 — `_list_host_documents_impl` does `broker.forward`
        (blocking HTTP, up to 2 s).  Routed through `_cached_async`."""
        try:
            family = (family or "").strip().lower()
            return _safe_json(self._cached_async(
                f"hdocs:{family}:{session_id}",
                lambda: _list_host_documents_impl(family, session_id),
                empty=[]))
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

    # ─── Node context-menu actions (right-click on a node) ─────────
    # Founder direction (2026-05-14): right-click on a node body /
    # title bar opens a per-node menu. Two of those items need bridge
    # support: "Save as Skill" packages the node + reachable downstream
    # graph into a skill JSON, and "Duplicate" clones a node with a
    # +30/+30 px offset so the JSX can splice it cleanly into LM_GRAPH.
    @pyqtSlot(str, str, result=str)
    def save_as_skill(self, name: str, payload_json: str) -> str:
        """Persist a graph subset as a canvas skill JSON.

        `payload_json` is the JSON-serialised graph subset (the node + its
        reachable downstream nodes + the connecting wires) emitted by
        the JSX side. We write it as
        `%LOCALAPPDATA%/ArchHub/skills/<slug>.archhub-skill.json` — the
        writable user store get_saved_skills + load_skill read — and
        return the absolute path (or an error envelope on failure).
        """
        try:
            import json as _json
            import re
            try:
                payload = _json.loads(payload_json) if payload_json else {}
            except Exception as ex:
                return _safe_json({"error": f"bad payload_json: {ex}"})
            if not isinstance(payload, dict):
                return _safe_json({"error": "payload must be a JSON object"})
            slug_src = (name or payload.get("name")
                        or "untitled-skill")
            slug = re.sub(r"[^a-z0-9]+", "-",
                          str(slug_src).lower()).strip("-") or "untitled-skill"
            out_path = _user_skills_dir() / f"{slug}.archhub-skill.json"
            # SLICE G (AgDR-0010): the hybrid skill-as-node contract.
            # `payload.meta` carries `mode` (`shared`|`private`) +
            # optional `description` + `category` from the SaveSkillDialog.
            # Default mode is `private` so older callers stay safe.
            _meta_in = payload.get("meta") if isinstance(payload, dict) else None
            if not isinstance(_meta_in, dict):
                _meta_in = {}
            _mode = _meta_in.get("mode", "private")
            if _mode not in ("shared", "private"):
                _mode = "private"
            envelope_meta = {
                "mode":        _mode,
                "description": str(_meta_in.get("description") or ""),
                "category":    str(_meta_in.get("category") or ""),
            }
            # Strip meta from the stored graph so the runtime graph
            # dict is clean; metadata lives at the envelope level.
            graph_only = {k: v for k, v in payload.items() if k != "meta"} \
                if isinstance(payload, dict) else payload
            # Wrap with a tiny envelope so loaders can distinguish a
            # skill JSON from a raw graph dump.
            envelope = {
                "kind": "archhub.skill",
                "name": str(name or slug_src),
                "slug": slug,
                "meta": envelope_meta,
                "graph": graph_only,
            }
            out_path.write_text(_json.dumps(envelope, indent=2,
                                              ensure_ascii=False),
                                  encoding="utf-8")
            # AgDR-0033 — if this slug was tombstoned (user had deleted
            # a shipped seed of the same name), the fresh save should be
            # visible again — clear the tombstone.
            _clear_skill_tombstone(slug)
            # Notify the JSX side so the Skills panel refreshes without
            # a relaunch — skills are nodes, not files; the user should
            # see the new entry immediately.
            try: self.skills_changed.emit()
            except Exception: pass
            return _safe_json({"ok": True, "path": str(out_path),
                                "slug": slug,
                                "nodes": len(payload.get("nodes") or []),
                                "wires": len(payload.get("wires") or [])})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, str, result=str)
    def duplicate_node(self, graph_json: str, node_id: str) -> str:
        """Return a cloned node dict (offset +30/+30 px, fresh id) so
        the JSX side can splice it into LM_GRAPH without re-implementing
        the deep-copy + id-rewriting logic in JS.

        Returns `{"node": {...}}` on success or `{"error": "..."}` on
        failure. The new id is `<original_id>_copyN` where N is the
        smallest integer that yields a globally-unique id within the
        provided graph.
        """
        try:
            import copy
            import json as _json
            try:
                graph = _json.loads(graph_json) if graph_json else {}
            except Exception as ex:
                return _safe_json({"error": f"bad graph_json: {ex}"})
            nodes = (graph.get("nodes") or []) if isinstance(graph, dict) else []
            existing = {n.get("id") for n in nodes if isinstance(n, dict)}
            src = next((n for n in nodes
                        if isinstance(n, dict) and n.get("id") == node_id),
                       None)
            if src is None:
                return _safe_json({"error": f"node {node_id!r} not found"})
            clone = copy.deepcopy(src)
            # Mint a unique id: <orig>_copy, _copy2, _copy3, ...
            base = f"{node_id}_copy"
            new_id = base
            n = 2
            while new_id in existing:
                new_id = f"{base}{n}"
                n += 1
            clone["id"] = new_id
            # Offset position by +30/+30 px so the clone is visually
            # distinguishable from its source.
            try:
                clone["x"] = float(src.get("x", 0)) + 30
                clone["y"] = float(src.get("y", 0)) + 30
            except Exception:
                # Non-numeric coords — best-effort skip the bump.
                pass
            # Wipe runtime state — the clone is a fresh, idle copy.
            for k in ("state", "progress", "runtime", "result", "ms",
                     "frozen"):
                clone.pop(k, None)
            return _safe_json({"node": clone, "id": new_id})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Subgraph (composite-node) compose / expand ────────────────
    # Founder direction (2026-05-13): the canvas needs to fold N
    # selected nodes into one composite (Cmd-G) + unfold a composite
    # back into its inner contents ("Expand subgraph" context menu).
    # Both operations are pure data transforms on the graph dict, so
    # the heavy lifting lives in `workflows/subgraph.py`. These two
    # slots are thin JSON wrappers around those helpers.
    @pyqtSlot(str, str, result=str)
    def compose_subgraph(self, graph_json: str,
                          node_ids_json: str) -> str:
        """Wrap the listed node ids into one `subgraph.user` node.

        `graph_json` is the JSON-serialised LM_GRAPH; `node_ids_json`
        is a JSON list of node ids. Returns the new graph dict (with
        the composite node spliced in) or an `{"error": "..."}`
        envelope on failure.
        """
        try:
            import json as _json
            try:
                graph = _json.loads(graph_json) if graph_json else {}
            except Exception as ex:
                return _safe_json({"error": f"bad graph_json: {ex}"})
            try:
                node_ids = _json.loads(node_ids_json) if node_ids_json else []
            except Exception as ex:
                return _safe_json({"error": f"bad node_ids_json: {ex}"})
            if not isinstance(node_ids, list) or not node_ids:
                return _safe_json(
                    {"error": "node_ids must be a non-empty JSON list"})
            from workflows.subgraph import compose_subgraph as _compose
            new_graph = _compose(graph, list(node_ids))
            return _safe_json({"ok": True, "graph": new_graph})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, str, result=str)
    def expand_subgraph(self, graph_json: str,
                         subgraph_node_id: str) -> str:
        """Inverse of `compose_subgraph`: replaces the composite node
        with its inner contents + reconnects the outer wires.

        Returns the new graph dict or an `{"error": "..."}` envelope.
        """
        try:
            import json as _json
            try:
                graph = _json.loads(graph_json) if graph_json else {}
            except Exception as ex:
                return _safe_json({"error": f"bad graph_json: {ex}"})
            if not subgraph_node_id:
                return _safe_json(
                    {"error": "subgraph_node_id is required"})
            from workflows.subgraph import expand_subgraph as _expand
            new_graph = _expand(graph, subgraph_node_id)
            return _safe_json({"ok": True, "graph": new_graph})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Composer slash-command parser ─────────────────────────────
    # Founder direction (2026-05-13): when the FloatingComposer input
    # starts with `/wire`, `/freeze`, `/delete`, `/rename`,
    # `/duplicate`, or `/properties`, JSX calls this slot to parse the
    # command into a typed action descriptor. JSX then applies the
    # descriptor against LM_GRAPH (or emits `lm-node-properties` for
    # the properties case).
    @pyqtSlot(str, str, result=str)
    def parse_composer_command(self, raw: str,
                                focused_node_id: str = "") -> str:
        """Parse a slash-command from the composer.

        See `workflows/composer_commands.py` for the action descriptor
        shape. Returns a JSON-string action descriptor — JSX dispatches
        on `command` to apply the change."""
        try:
            from workflows.composer_commands import (
                parse_composer_command as _parse,
            )
            action = _parse(raw, focused_node_id=focused_node_id or None)
            return _safe_json(action)
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Composer agent (LLM-as-orchestrator) ─────────────────────
    # Founder demand (2026-05-14): "whatever I write on the composer
    # the AI should act on it and call the nodes and wire them". Slash
    # commands stay on parse_composer_command; everything else hits
    # this slot. The composer_agent module hands the user message +
    # graph state to Claude with a tool schema describing canvas
    # primitives (spawn_node / add_wire / set_node_param / run_node /
    # run_workflow / query_graph / chat). The LLM picks tool calls;
    # we forward them as structured actions for the JSX side to apply.
    @pyqtSlot(str, str, str, result=str)
    def agent_step(self, user_msg: str, graph_json: str,
                    focused_node_id: str = "") -> str:
        """LLM-as-orchestrator. Founder bug 2026-05-15: the app froze
        ("Not Responding") on every composer submit — root cause was
        this slot running `run_agent_step` SYNCHRONOUSLY on the Qt main
        thread. run_agent_step does ~10s of host probing + a full LLM
        round-trip; both blocked the UI. Fix: run it on a background
        thread and emit `agent_step_done(result_json)` when finished.
        The slot returns immediately so the main thread never stalls.
        """
        import json as _json
        try:
            graph = _json.loads(graph_json) if graph_json else {}
        except Exception as ex:
            return _safe_json({"async": False,
                                "error": f"bad graph_json: {ex}"})

        def _runner():
            try:
                from agents.composer_agent import run_agent_step
                result = run_agent_step(
                    user_msg=user_msg or "",
                    graph=graph if isinstance(graph, dict) else {},
                    focused_node_id=focused_node_id or "",
                    router=self.router,
                )
            except Exception as ex:
                result = {"actions": [], "text": "", "error": str(ex)}
            try:
                self.agent_step_done.emit(_safe_json(result))
            except Exception:
                pass

        threading.Thread(target=_runner, daemon=True,
                          name="ArchHubAgentStep").start()
        # Return immediately — JSX listens for agent_step_done.
        return _safe_json({"async": True})

    @pyqtSlot(str, str, str, result=str)
    def apply_composer_command(self, graph_json: str, raw: str,
                                 focused_node_id: str = "") -> str:
        """One-shot: parse `raw` and apply the resulting action against
        the supplied graph. Convenience wrapper for the JSX side so it
        doesn't have to do `parse_composer_command` then dispatch.

        Returns `{"action": {...}, "graph": {...}}`."""
        try:
            import json as _json
            try:
                graph = _json.loads(graph_json) if graph_json else {}
            except Exception as ex:
                return _safe_json({"error": f"bad graph_json: {ex}"})
            from workflows.composer_commands import (
                parse_composer_command as _parse,
                apply_action as _apply,
            )
            action = _parse(raw, focused_node_id=focused_node_id or None)
            new_graph = _apply(graph, action) if action.get("ok") else graph
            return _safe_json({"action": action, "graph": new_graph})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── Custom node-type creator ─────────────────────────────────
    # Founder direction (2026-05-14): the user should be able to mint a
    # new node type from the UI. The JSX "Create node…" modal POSTs the
    # spec here; we persist it to LOCALAPPDATA and register it with the
    # workflows registry so the canvas + runner pick it up immediately,
    # without requiring a relaunch.
    @pyqtSlot(str, result=str)
    def create_node_type(self, spec_json: str) -> str:
        """Create + register a custom node type from a JSON spec.

        spec_json shape (see workflows/custom_nodes.py):
            {"type": "my.custom", "category": "filter",
             "display_name": "My filter",
             "inputs": ["walls"], "outputs": ["filtered"],
             "config_schema": {...},
             "code": "<optional python source>"}

        Returns `{"ok": true, "type": "...", "path": "..."}` or an
        `{"error": "..."}` envelope on failure. When `code` is empty the
        node is registered as a passthrough — the founder still gets a
        usable custom node without the security risk of exec'ing
        user-supplied scripts."""
        try:
            spec = json.loads(spec_json or "{}")
            if not isinstance(spec, dict):
                return _safe_json({"error": "spec must be a JSON object"})
            from workflows.custom_nodes import write_spec, register_spec
            path = write_spec(spec)
            node_spec = register_spec(spec)
            try: self.skills_changed.emit()
            except Exception: pass
            return _safe_json({"ok": True, "type": node_spec.type,
                                "path": str(path),
                                "inputs":  [p.name for p in node_spec.inputs],
                                "outputs": [p.name for p in node_spec.outputs]})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(result=str)
    def get_custom_nodes(self) -> str:
        """Every user-minted custom node type, for the node library's
        MY NODES section. Founder demand 2026-05-16."""
        try:
            from workflows.custom_nodes import list_specs
            out = []
            for spec in (list_specs() or []):
                if not isinstance(spec, dict):
                    continue
                ins = spec.get("inputs") or []
                outs = spec.get("outputs") or []
                out.append({
                    "type": spec.get("type", ""),
                    "category": spec.get("category", "transform"),
                    "title": spec.get("display_name") or spec.get("type", ""),
                    "description": spec.get("description", ""),
                    "icon": spec.get("icon", "⊕"),
                    "inputs": ins, "outputs": outs,
                })
            return _safe_json(out)
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    # ─── AgDR-0028 — library item actions (delete + bulk clear) ─────

    @pyqtSlot(str, result=str)
    def delete_saved_skill(self, skill_id: str) -> str:
        """AgDR-0028/0032/0033 — delete a saved skill by slug.

        Resolves via the SAME store get_saved_skills + load_skill use
        (_scan_canvas_skills), keyed by slug.

        AgDR-0033 — a user-store file is unlinked; a shipped seed is
        tombstoned (its slug recorded in _hidden-skills.json) because
        an app update would restore an unlinked seed and a read-only
        install would fail the unlink.  `_scan_canvas_skills` filters
        tombstoned slugs out, so the skill vanishes from the panel
        either way.

        Returns
            {"ok": true,  "id": "...", "method": "unlinked"|"tombstoned"}
          or
            {"ok": false, "id": "...", "error_code": "...", "error": "..."}
        Failure codes: not_found, unlink_failed, bad_args, exception.
        """
        try:
            sid = (skill_id or "").strip()
            if not sid:
                return _safe_json({"ok": False, "id": "",
                                    "error_code": "bad_args",
                                    "error": "skill_id is required"})
            match = next(
                (s for s in _scan_canvas_skills()
                 if s.get("slug") == sid or s.get("name") == sid),
                None,
            )
            if match is None:
                return _safe_json({"ok": False, "id": sid,
                                    "error_code": "not_found",
                                    "error": f"skill {sid!r} not found"})
            from pathlib import Path as _Path
            target = _Path(match["path"])
            user_dir = _user_skills_dir().resolve()
            is_user_store = user_dir in target.resolve().parents

            # AgDR-0033 — shipped seed: tombstone instead of reject.
            # An app update would restore an unlinked seed, and a
            # read-only install would fail the unlink — so we record
            # the slug in a per-user tombstone file that
            # `_scan_canvas_skills` filters out.  User-store files are
            # unlinked outright.
            if is_user_store:
                try:
                    target.unlink(missing_ok=True)
                except Exception as ex:
                    return _safe_json({"ok": False, "id": sid,
                                        "error_code": "unlink_failed",
                                        "error": str(ex)})
                method = "unlinked"
            else:
                _add_skill_tombstone(sid)
                method = "tombstoned"

            # Cloud-sync push happens off-thread so the bridge slot returns fast.
            try:
                import cloud_sync, threading
                threading.Thread(
                    target=cloud_sync.push,
                    args=(f"Delete Skill: {match.get('name', sid)}",),
                    daemon=True,
                ).start()
            except Exception:
                pass
            try: self.skills_changed.emit()
            except Exception: pass
            return _safe_json({"ok": True, "id": sid, "method": method})
        except Exception as ex:
            return _safe_json({"ok": False, "id": skill_id,
                                "error_code": "exception",
                                "error": str(ex)})

    @pyqtSlot(str, result=str)
    def delete_custom_node(self, type_id: str) -> str:
        """AgDR-0028 — delete a custom node by type id.  Unregisters
        from the live registry + removes the spec file."""
        try:
            from workflows.custom_nodes import delete_spec
            ok = bool(delete_spec(type_id))
            if ok:
                try: self.skills_changed.emit()
                except Exception: pass
            return _safe_json({"ok": ok, "type": type_id,
                               "error": "" if ok else "not_found"})
        except Exception as ex:
            return _safe_json({"ok": False, "error": str(ex)})

    @pyqtSlot(result=str)
    def clear_all_custom_nodes(self) -> str:
        """AgDR-0028 — wipe every saved custom-node spec.  Confirmation
        happens in the JSX modal — the bridge call is the point of no
        return."""
        try:
            from workflows.custom_nodes import list_specs, delete_spec
            removed = 0
            for spec in (list_specs() or []):
                t = (spec or {}).get("type") if isinstance(spec, dict) else None
                if t and delete_spec(t):
                    removed += 1
            if removed:
                try: self.skills_changed.emit()
                except Exception: pass
            return _safe_json({"ok": True, "removed": removed})
        except Exception as ex:
            return _safe_json({"ok": False, "error": str(ex)})

    @pyqtSlot(result=str)
    def clear_all_saved_skills(self) -> str:
        """AgDR-0028 + AgDR-0033 — wipe every saved skill the panel
        shows.  User-store files are unlinked; shipped seeds are
        tombstoned so they don't reappear."""
        try:
            from pathlib import Path as _Path
            user_dir = _user_skills_dir().resolve()
            removed = 0
            for s in _scan_canvas_skills():
                slug = s.get("slug")
                try:
                    target = _Path(s.get("path") or "").resolve()
                except Exception:
                    target = None
                if target is not None and user_dir in target.parents:
                    try:
                        target.unlink(missing_ok=True)
                        removed += 1
                    except Exception:
                        continue
                elif slug:
                    # Shipped seed — tombstone it.
                    _add_skill_tombstone(slug)
                    removed += 1
            if removed:
                try: self.skills_changed.emit()
                except Exception: pass
            return _safe_json({"ok": True, "removed": removed})
        except Exception as ex:
            return _safe_json({"ok": False, "error": str(ex)})

    @pyqtSlot(str, str, result=str)
    def ai_create_node(self, req_id: str, description: str) -> str:
        """Founder demand 2026-05-16: custom-make a node on a whim with
        AI. The user describes a node in natural language; an LLM
        generates the full spec — type, category, typed I/O, and a
        sandboxed Python `execute(config, inputs, ctx)` body — which we
        register as a real, runnable custom node. Threaded; emits
        `node_created(result_json)` when done."""
        def _runner():
            try:
                import json as _json
                from agents.node_smith import design_node_spec
                spec = design_node_spec(description or "", router=self.router)
                if not isinstance(spec, dict) or spec.get("error"):
                    self.node_created.emit(_safe_json({
                        "req_id": req_id, "ok": False,
                        "error": (spec or {}).get("error", "AI returned no spec"),
                    }))
                    return
                from workflows.custom_nodes import write_spec, register_spec
                write_spec(spec)
                node_spec = register_spec(spec)
                try: self.skills_changed.emit()
                except Exception: pass
                self.node_created.emit(_safe_json({
                    "req_id": req_id, "ok": True,
                    "type": node_spec.type,
                    "spec": {
                        "type": spec.get("type"),
                        "category": spec.get("category", "transform"),
                        "title": spec.get("display_name") or spec.get("type"),
                        "description": spec.get("description", ""),
                        "icon": spec.get("icon", "⊕"),
                        "inputs": spec.get("inputs") or [],
                        "outputs": spec.get("outputs") or [],
                    },
                }))
            except Exception as ex:
                try:
                    self.node_created.emit(_safe_json({
                        "req_id": req_id, "ok": False,
                        "error": f"{type(ex).__name__}: {ex}"}))
                except Exception:
                    pass

        threading.Thread(target=_runner, daemon=True,
                          name="ArchHubNodeSmith").start()
        return _safe_json({"async": True, "req_id": req_id})

    # ─── Settings-overlay / housekeeping slots ─────────────────────
    # Founder direction (2026-05-14): the Settings overlay in JSX calls
    # a family of bridge slots for storage stats, theme persistence,
    # session rename/fork/delete, export-all, cache clearing, and
    # opening data folders. Without these, the JSX buttons silently
    # no-op. Each slot here is defensive — failures must never bubble
    # exceptions to the JSX side; they always return _safe_json with
    # an `{"error": ...}` envelope on failure.

    @pyqtSlot(str, str, result=str)
    def rename_session(self, session_id: str, new_title: str) -> str:
        """Rename a saved session. Updates payload['name'] + ['title']
        and writes atomically. Emits sessions_changed."""
        try:
            from pathlib import Path
            from session_io import SESSIONS_DIR
            sid = (session_id or "").strip()
            title = (new_title or "").strip()
            if not sid:
                return _safe_json({"error": "session_id is required"})
            if not title:
                return _safe_json({"error": "new_title is required"})
            p = Path(sid)
            if not p.exists():
                p = SESSIONS_DIR / f"{sid}.archhub-session.json"
            if not p.exists():
                return _safe_json({"error": "session not found"})
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
            except Exception as ex:
                return _safe_json({"error": f"bad session JSON: {ex}"})
            if not isinstance(payload, dict):
                return _safe_json({"error": "session payload is not a dict"})
            payload["name"]  = title
            payload["title"] = title
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(p)
            try: self.sessions_changed.emit()
            except Exception: pass
            return _safe_json({"ok": True, "id": sid, "title": title})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, str, result=str)
    def fork_session(self, session_id: str, new_title: str = "") -> str:
        """Duplicate a saved session under a fresh slug + id. Same
        graph, fresh id, new file. Emits sessions_changed."""
        try:
            import re as _re
            from pathlib import Path
            from datetime import datetime
            from session_io import SESSIONS_DIR
            sid = (session_id or "").strip()
            if not sid:
                return _safe_json({"error": "session_id is required"})
            p = Path(sid)
            if not p.exists():
                p = SESSIONS_DIR / f"{sid}.archhub-session.json"
            if not p.exists():
                return _safe_json({"error": "session not found"})
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
            except Exception as ex:
                return _safe_json({"error": f"bad session JSON: {ex}"})
            if not isinstance(payload, dict):
                return _safe_json({"error": "session payload is not a dict"})
            base_title = (new_title or "").strip()
            if not base_title:
                base_title = f"{payload.get('name') or payload.get('title') or sid}-fork"
            slug_src = _re.sub(r"[^A-Za-z0-9]+", "-", base_title).strip("-").lower()
            if not slug_src:
                slug_src = "session-fork"
            SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
            new_slug = slug_src
            k = 2
            while (SESSIONS_DIR / f"{new_slug}.archhub-session.json").exists():
                new_slug = f"{slug_src}-{k}"
                k += 1
            payload["id"]       = new_slug
            payload["name"]     = base_title
            payload["title"]    = base_title
            payload["saved_at"] = datetime.utcnow().isoformat() + "Z"
            (SESSIONS_DIR / f"{new_slug}.archhub-session.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            try: self.sessions_changed.emit()
            except Exception: pass
            return _safe_json({"ok": True, "id": new_slug,
                                "title": base_title})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def delete_session(self, session_id: str) -> str:
        """Delete a session JSON file. Emits sessions_changed."""
        try:
            from pathlib import Path
            from session_io import SESSIONS_DIR
            sid = (session_id or "").strip()
            if not sid:
                return _safe_json({"error": "session_id is required"})
            p = Path(sid)
            if not p.exists():
                p = SESSIONS_DIR / f"{sid}.archhub-session.json"
            if not p.exists():
                return _safe_json({"error": "session not found"})
            try:
                p.unlink()
            except Exception as ex:
                return _safe_json({"error": f"unlink failed: {ex}"})
            try: self.sessions_changed.emit()
            except Exception: pass
            return _safe_json({"ok": True, "id": sid})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def duplicate_session(self, session_id: str) -> str:
        """Duplicate a session in place — identical content under a
        fresh slug, titled '<name> (copy)'. A distinct slot so the JSX
        'Duplicate' menu item resolves: it previously called a
        non-existent `duplicate_session` and silently no-op'd. Delegates
        to fork_session so the atomic write + slug-collision handling +
        sessions_changed signal stay in one place."""
        try:
            from pathlib import Path
            from session_io import SESSIONS_DIR
            sid = (session_id or "").strip()
            if not sid:
                return _safe_json({"error": "session_id is required"})
            p = Path(sid)
            if not p.exists():
                p = SESSIONS_DIR / f"{sid}.archhub-session.json"
            if not p.exists():
                return _safe_json({"error": "session not found"})
            base = sid
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    base = (payload.get("name")
                            or payload.get("title") or sid)
            except Exception:
                pass
            return self.fork_session(session_id, f"{base} (copy)")
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def set_theme(self, name: str) -> str:
        """Persist theme choice to %LOCALAPPDATA%/ArchHub/theme.json.
        Accepts 'dark' / 'light' / 'system'."""
        try:
            import os as _os
            from pathlib import Path
            n = (name or "").strip().lower()
            if n not in ("dark", "light", "system"):
                return _safe_json({"error":
                    "theme must be one of: dark, light, system"})
            base = Path(_os.environ.get("LOCALAPPDATA",
                                          str(Path.home()))) / "ArchHub"
            base.mkdir(parents=True, exist_ok=True)
            (base / "theme.json").write_text(
                json.dumps({"theme": n}, indent=2),
                encoding="utf-8",
            )
            return _safe_json({"ok": True, "theme": n})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(result=str)
    def get_theme(self) -> str:
        """Read theme.json, defaulting to 'dark' when missing/invalid."""
        try:
            import os as _os
            from pathlib import Path
            p = Path(_os.environ.get("LOCALAPPDATA",
                                       str(Path.home()))) / "ArchHub" / "theme.json"
            if not p.exists():
                return _safe_json({"theme": "dark"})
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return _safe_json({"theme": "dark"})
            theme = str((data or {}).get("theme", "dark") or "dark").lower()
            if theme not in ("dark", "light", "system"):
                theme = "dark"
            return _safe_json({"theme": theme})
        except Exception as ex:
            return _safe_json({"error": str(ex), "theme": "dark"})

    @pyqtSlot(result=str)
    def get_storage_stats(self) -> str:
        """Report on-disk usage across sessions/, app/, custom_nodes/
        and skills/. Used by the Settings → Storage badge.

        AgDR-0036 — the recursive `glob('**/*')` + per-file `stat()`
        across the whole %LOCALAPPDATA%/ArchHub tree stalls the UI for
        seconds on a large account.  Routed through `_cached_async`."""
        return _safe_json(self._cached_async(
            "storage_stats", self._compute_storage_stats, empty={}))

    def _compute_storage_stats(self) -> dict:
        try:
            import os as _os
            from pathlib import Path
            from session_io import SESSIONS_DIR

            def _stat(root: Path) -> dict:
                count = 0
                total = 0
                try:
                    if root.exists():
                        for f in root.glob("**/*"):
                            try:
                                if f.is_file():
                                    count += 1
                                    total += f.stat().st_size
                            except Exception:
                                continue
                except Exception:
                    pass
                return {"count": count, "bytes": total,
                        "path":  str(root)}

            appdata = Path(_os.environ.get("LOCALAPPDATA",
                                              str(Path.home()))) / "ArchHub"
            cn_dir = appdata / "custom_nodes"
            skills_dir = appdata / "skills"
            sessions = _stat(SESSIONS_DIR)
            app_stat = _stat(appdata)
            cn = _stat(cn_dir)
            sk = _stat(skills_dir)
            total = (sessions["bytes"] + app_stat["bytes"]
                      + cn["bytes"] + sk["bytes"])
            return {
                "sessions":     sessions,
                "app":          app_stat,
                "custom_nodes": cn,
                "skills":       sk,
                "total_bytes":  total,
            }
        except Exception as ex:
            return {"error": str(ex)}

    @pyqtSlot(result=str)
    def get_profile(self) -> str:
        """Read the user profile (firm / role / discipline) from
        %LOCALAPPDATA%/ArchHub/profile.json. Returns {} when the file
        is absent — the desktop UI reads that to decide whether to show
        the first-run profile prompt. Roadmap #P0 2026-05-17."""
        try:
            import os as _os
            from pathlib import Path
            p = (Path(_os.environ.get("LOCALAPPDATA", str(Path.home())))
                 / "ArchHub" / "profile.json")
            if not p.exists():
                return _safe_json({})
            data = json.loads(p.read_text(encoding="utf-8"))
            return _safe_json(data if isinstance(data, dict) else {})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def save_profile(self, payload_json: str) -> str:
        """Persist the user profile to profile.json. The first-run
        prompt sends {firm, role, discipline}; a skipped prompt sends
        {skipped: true} so it never nags again. Merges with any
        existing profile. Roadmap #P0 2026-05-17."""
        try:
            import os as _os
            from pathlib import Path
            data = json.loads(payload_json or "{}")
            if not isinstance(data, dict):
                return _safe_json({"error": "profile must be a JSON object"})
            appdata = (Path(_os.environ.get("LOCALAPPDATA", str(Path.home())))
                       / "ArchHub")
            appdata.mkdir(parents=True, exist_ok=True)
            p = appdata / "profile.json"
            existing: dict = {}
            if p.exists():
                try:
                    loaded = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        existing = loaded
                except Exception:
                    existing = {}
            existing.update({k: v for k, v in data.items() if v is not None})
            p.write_text(json.dumps(existing, indent=2, ensure_ascii=False),
                         encoding="utf-8")
            return _safe_json({"ok": True, "profile": existing})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(result=str)
    def export_all(self) -> str:
        """Zip sessions/, skills/, custom_nodes/, profile.json,
        theme.json into ~/Downloads/archhub-export-<ts>.zip."""
        try:
            import os as _os
            import zipfile
            from datetime import datetime
            from pathlib import Path
            from session_io import SESSIONS_DIR

            appdata = Path(_os.environ.get("LOCALAPPDATA",
                                              str(Path.home()))) / "ArchHub"
            cn_dir = appdata / "custom_nodes"
            skills_dir = appdata / "skills"
            profile_path = appdata / "profile.json"
            theme_path = appdata / "theme.json"

            home = Path(_os.environ.get("USERPROFILE",
                                           str(Path.home())))
            downloads = home / "Downloads"
            try:
                downloads.mkdir(parents=True, exist_ok=True)
            except Exception:
                downloads = home
            ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            zip_path = downloads / f"archhub-export-{ts}.zip"

            def _add_dir(z: zipfile.ZipFile, root: Path, arc_prefix: str) -> None:
                if not root.exists():
                    return
                try:
                    for f in root.glob("**/*"):
                        try:
                            if f.is_file():
                                rel = f.relative_to(root)
                                z.write(f, arcname=f"{arc_prefix}/{rel}")
                        except Exception:
                            continue
                except Exception:
                    pass

            with zipfile.ZipFile(zip_path, "w",
                                   compression=zipfile.ZIP_DEFLATED) as z:
                _add_dir(z, SESSIONS_DIR, "sessions")
                _add_dir(z, skills_dir,   "skills")
                _add_dir(z, cn_dir,       "custom_nodes")
                for one in (profile_path, theme_path):
                    try:
                        if one.exists() and one.is_file():
                            z.write(one, arcname=one.name)
                    except Exception:
                        pass

            size = 0
            try:
                size = zip_path.stat().st_size
            except Exception:
                pass
            return _safe_json({"ok": True,
                                "path": str(zip_path),
                                "size": size})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(result=str)
    def clear_model_cache(self) -> str:
        """Best-effort delete of %LOCALAPPDATA%/ArchHub/model_cache/*.
        Returns total bytes freed."""
        try:
            import os as _os
            import shutil
            from pathlib import Path
            cache = Path(_os.environ.get("LOCALAPPDATA",
                                            str(Path.home()))) / "ArchHub" / "model_cache"
            freed = 0
            if not cache.exists():
                return _safe_json({"ok": True, "freed_bytes": 0,
                                    "note": "no cache dir"})
            try:
                for f in cache.glob("**/*"):
                    try:
                        if f.is_file():
                            freed += f.stat().st_size
                    except Exception:
                        continue
            except Exception:
                pass
            try:
                shutil.rmtree(cache, ignore_errors=True)
            except Exception:
                pass
            try:
                cache.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            return _safe_json({"ok": True, "freed_bytes": freed})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(result=str)
    def forget_all_memory(self) -> str:
        """Wipe local memory cache + best-effort cloud forget. Emits
        memory_changed."""
        try:
            forgot_cloud = False
            try:
                import cloud_client
                fn = getattr(cloud_client, "forget_all", None)
                if callable(fn):
                    fn()
                    forgot_cloud = True
            except Exception:
                forgot_cloud = False
            # Local memory cache — best-effort wipe of facts file.
            try:
                import os as _os
                from pathlib import Path
                base = Path(_os.environ.get("LOCALAPPDATA",
                                              str(Path.home()))) / "ArchHub"
                for name in ("memory_facts.json", "memory_cache.json"):
                    p = base / name
                    try:
                        if p.exists():
                            p.unlink()
                    except Exception:
                        continue
            except Exception:
                pass
            try: self.memory_changed.emit()
            except Exception: pass
            return _safe_json({"ok": True,
                                "cloud_forgotten": forgot_cloud})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(result=str)
    def delete_all_sessions(self) -> str:
        """Remove every *.archhub-session.json under SESSIONS_DIR. Emits
        sessions_changed."""
        try:
            from session_io import SESSIONS_DIR
            deleted = 0
            if SESSIONS_DIR.exists():
                for f in SESSIONS_DIR.glob("*.archhub-session.json"):
                    try:
                        f.unlink()
                        deleted += 1
                    except Exception:
                        continue
            try: self.sessions_changed.emit()
            except Exception: pass
            return _safe_json({"ok": True, "deleted": deleted})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, result=str)
    def open_folder(self, kind: str) -> str:
        """Open a known ArchHub directory in the OS file explorer."""
        try:
            import os as _os
            from pathlib import Path
            from session_io import SESSIONS_DIR
            k = (kind or "").strip().lower()
            appdata = Path(_os.environ.get("LOCALAPPDATA",
                                              str(Path.home()))) / "ArchHub"
            mapping = {
                "sessions":      SESSIONS_DIR,
                "skills":        appdata / "skills",
                "custom_nodes":  appdata / "custom_nodes",
                "app":           appdata,
                "logs":          appdata / "logs",
            }
            if k not in mapping:
                return _safe_json({"error":
                    f"unknown kind: {k!r}; want sessions|skills|custom_nodes|app|logs"})
            path = mapping[k]
            try:
                path.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            try:
                startfile = getattr(_os, "startfile", None)
                if callable(startfile):
                    startfile(str(path))
            except Exception as ex:
                return _safe_json({"error": f"startfile failed: {ex}",
                                    "path": str(path)})
            return _safe_json({"ok": True, "path": str(path)})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(result=str)
    def get_session_stats(self) -> str:
        """Return summary of sessions on disk for Settings overlay."""
        try:
            from session_io import SESSIONS_DIR
            count = 0
            last_mtime = 0.0
            if SESSIONS_DIR.exists():
                for f in SESSIONS_DIR.glob("*.archhub-session.json"):
                    try:
                        count += 1
                        m = f.stat().st_mtime
                        if m > last_mtime:
                            last_mtime = m
                    except Exception:
                        continue
            last_iso = ""
            if last_mtime > 0:
                try:
                    from datetime import datetime, timezone
                    last_iso = (datetime.fromtimestamp(last_mtime,
                                                        tz=timezone.utc)
                                .isoformat())
                except Exception:
                    last_iso = ""
            return _safe_json({
                "count":         count,
                "active_id":     self._active_session_id or "",
                "last_modified": last_iso,
            })
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(result=str)
    def get_provider_stats(self) -> str:
        """Return {configured, blocked} provider counts for badges."""
        try:
            configured = 0
            blocked = 0
            if self.router is not None:
                try:
                    cfg = self.router.configured_providers() or []
                    configured = len(list(cfg))
                except Exception:
                    configured = 0
                try:
                    blk = self.router.blocked_providers() or {}
                    blocked = len(list(blk))
                except Exception:
                    blocked = 0
            return _safe_json({"configured": configured,
                                "blocked":    blocked})
        except Exception as ex:
            return _safe_json({"error": str(ex)})
