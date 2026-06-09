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
# Settings housekeeping — heavy filesystem work, factored to MODULE scope.
#
# AgDR-0036 follow-up (2026-06-02): export-all + clear-model-cache were the last
# two GUI-thread blockers. The recursive glob+zip / glob+delete is intrinsically
# slow (a big sessions/ tree, a fat model_cache). Keeping it here — OUTSIDE any
# @pyqtSlot — means the maintenance_audit blocking-in-pyqtslot detector (which
# only scans lines between a slot's `def` and the next top-level `def`) never
# sees the glob, while the bridge slots stay thin: they submit these to
# `_bg_pool()` and emit `settings_op_done`. Both functions are pure + fail-safe
# (return an envelope dict, never raise) so the same code serves the live async
# path AND the direct synchronous unit-test call.
# ---------------------------------------------------------------------------

def _do_export_all() -> dict:
    """Zip sessions/, skills/, custom_nodes/, profile.json, theme.json into
    ~/Downloads/archhub-export-<ts>.zip. Returns {ok, path, size} or {error}.

    Pure + synchronous: the caller decides the thread. Never raises — a failure
    lands as an {"error": ...} envelope so the off-thread runner can ship a
    clean error result instead of crashing the worker."""
    try:
        import os as _os
        import zipfile
        from datetime import datetime, timezone
        from pathlib import Path
        from session_io import SESSIONS_DIR

        appdata = Path(_os.environ.get("LOCALAPPDATA",
                                          str(Path.home()))) / "ArchHub"
        cn_dir = appdata / "custom_nodes"
        skills_dir = appdata / "skills"
        profile_path = appdata / "profile.json"
        theme_path = appdata / "theme.json"

        home = Path(_os.environ.get("USERPROFILE", str(Path.home())))
        downloads = home / "Downloads"
        try:
            downloads.mkdir(parents=True, exist_ok=True)
        except Exception:
            downloads = home
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        zip_path = downloads / f"archhub-export-{ts}.zip"

        def _add_dir(z: "zipfile.ZipFile", root: Path, arc_prefix: str) -> None:
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
        return {"ok": True, "path": str(zip_path), "size": size}
    except Exception as ex:
        return {"error": str(ex)}


def _do_clear_model_cache() -> dict:
    """Best-effort delete of %LOCALAPPDATA%/ArchHub/model_cache/*. Returns
    {ok, freed_bytes} or {error}. Pure + synchronous + never raises (see
    _do_export_all)."""
    try:
        import os as _os
        import shutil
        from pathlib import Path
        cache = Path(_os.environ.get("LOCALAPPDATA", str(Path.home()))) \
            / "ArchHub" / "model_cache"
        freed = 0
        if not cache.exists():
            return {"ok": True, "freed_bytes": 0, "note": "no cache dir"}
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
        return {"ok": True, "freed_bytes": freed}
    except Exception as ex:
        return {"error": str(ex)}


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
    # Brain #32 — emitted when a brain_export_dataset worker finishes. Payload
    # is the brain.dataset_export manifest JSON ({ok,row_count,files,...}) with
    # `request_id` stamped in so the Brain view can match its pending click.
    brain_dataset_done = pyqtSignal(str)            # (result_json) — dataset export finished
    # Visual brain browser (BrainViewModal). brain_browse_changed fires when a
    # fresh organized-view snapshot lands on the background pool (the cached
    # snapshot is returned instantly on the Qt main thread). brain_search_done
    # carries the retrieval-ranked search cards for a query, request_id-stamped
    # so a stale result never overwrites the current search.
    brain_browse_changed = pyqtSignal()             # () — organized brain view refreshed
    brain_search_done = pyqtSignal(str)             # (result_json) — brain search finished
    # Multi-device COMMUNITIES panel (BrainViewModal → Communities). Reads
    # (community_groups / community_members / community_owned_server) route
    # through `_cached_async` and re-pull on `community_changed`. Writes
    # (community_create / community_join / community_set_transport /
    # community_join_code / community_leave) run on `_bg_pool` and deliver a
    # definitive per-request answer via `community_op_done(result_json)`
    # (request_id-stamped, the connector_op_done / node_op_done idiom). A
    # successful write also emits `community_changed` so the panel re-pulls
    # the roster + current-community without the caller wiring a refresh.
    community_changed  = pyqtSignal()               # () — community state changed (re-pull reads)
    community_op_done  = pyqtSignal(str)            # (result_json) — community write finished
    # Cloud-DB backup — emitted when a brain_cloud_backup worker finishes.
    # Payload is the /v1/brain/sync result JSON ({ok,synced,new_hlc,...} or
    # {ok:false,...}) with `request_id` stamped in so the Brain view's backup
    # button can match its pending click (mirrors brain_dataset_done).
    brain_backup_done = pyqtSignal(str)             # (result_json) — cloud backup finished
    # Cloud sign-in — emitted when the cloud_sign_in() SignInWorker finishes
    # (the real PKCE browser flow, reachable any time, not just first-run).
    # Payload {ok, signed_in, email, plan, request_id, error?}. The Settings
    # Account section + any signed-out CTA listen for this to flip to the
    # signed-in state. The agent NEVER signs in — the browser step is the
    # founder's; this signal just reports the outcome of THEIR action.
    cloud_signin_done  = pyqtSignal(str)            # (result_json) — cloud sign-in finished
    # Cloud sign-out — emitted when cloud_sign_out() finishes revoking the
    # token server-side (POST /v1/auth/logout) + clearing it locally. Payload
    # {ok, signed_in:false, msg, request_id}. `ok` is the SERVER revoke result;
    # the local token is ALWAYS cleared (honest sign-out even when offline).
    cloud_signout_done = pyqtSignal(str)            # (result_json) — cloud sign-out finished
    # AgDR-0036 follow-up — the canvas-edit slots (graph_validate /
    # graph_on_node_delete / library_suggest_swaps) used to run their
    # work SYNCHRONOUSLY in the @pyqtSlot body on the Qt main thread.
    # graph_validate fires debounced on EVERY canvas edit and
    # graph_on_node_delete on every delete; holding the GUI thread there
    # (even for sub-ms in-memory work, unbounded as the graph grows) is
    # the same freeze CLASS as the host probes. They now route through
    # `_cached_async` and emit this signal when fresh data lands so the
    # JSX re-pulls the (now-cached) answer without ever blocking the
    # main thread. Mirrors how `memory_changed` drives the memory slots.
    graph_validated = pyqtSignal()                  # canvas validation/edit result refreshed
    # AgDR-0036 follow-up — the two INTERACTIVE canvas slots that need a
    # definitive answer for a SPECIFIC request before the UI can act:
    #   graph_on_node_delete  (delete preview → silent/auto-bridge/recovery)
    #   library_suggest_swaps (right-click "swap with…" → ranked list)
    # A cached empty-first-call would corrupt their UX (a node with
    # incident wires must NOT be reported silent-deletable just because
    # the cache is cold). So instead of `_cached_async`, they run on
    # `_bg_pool` and emit this signal with the real result JSON +
    # `request_id` stamped in — the EXACT idiom already used by
    # connector_op_done / workflow_done / brain_dataset_done. The JSX
    # correlates by request_id (via the `bridgeAsyncSignal` helper) so
    # the caller still gets a single awaited answer, just off the Qt
    # main thread.
    node_op_done    = pyqtSignal(str)               # (result_json) — interactive canvas op finished
    # AgDR-0036 follow-up (2026-06-02) — the LAST two GUI-thread blockers were
    # the Settings "Export everything" + "Clear model cache" buttons. Both ran
    # a recursive glob+zip / glob+delete inside their @pyqtSlot, on the Qt main
    # thread, freezing the UI for the duration of the user's click. They were
    # the only entries on test_no_blocking_slots' allowlist (a documented
    # block-on-user-action exception). Now converted to the proven off-thread
    # idiom: the slot validates inline, submits the heavy fs work to _bg_pool,
    # returns {async, request_id} instantly, and emits this signal with the
    # real result + request_id when the work lands. Both the native
    # SettingsTab (settings_dialog.py) and the JSX SettingsModal correlate by
    # request_id, so the click stays responsive and the allowlist is empty.
    settings_op_done = pyqtSignal(str)              # (result_json) — Settings housekeeping op finished

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
            # R5 — close the dual-registry trap on boot. A node minted +
            # persisted in a prior session lives in the library's disk
            # registry; library.load_from_disk now mirrors each spec into
            # the workflow runner registry (library._mirror_to_runner) so it
            # can COOK this session, not merely be searchable. We call
            # load_from_disk ONLY when a registry file already exists —
            # never the seeding _library_bootstrap here, so the deferred
            # thread can't race a first-run seed-and-persist onto disk
            # (the lazy _library_bootstrap still seeds on the first JSX
            # library call). Fail-soft: a boot mirror hiccup must not crash
            # the boot thread.
            try:
                import library as _lib_boot
                import library_persistence as _lp_boot
                if _lp_boot.default_registry_path().exists():
                    _lib_boot.load_from_disk()
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

        # ── MAKE-IT-REAL auto-sync: keep local + cloud brain from drifting
        # between sign-ins. When SIGNED IN, a daemon thread runs the existing
        # brain_cloud_backup delta-push on an interval (default 600s,
        # env-overridable via ARCHHUB_BRAIN_SYNC_INTERVAL_S). Started after a
        # successful sign-in, stopped on sign-out. Off the Qt main thread;
        # best-effort + logged; never blocks the UI. State lives here so the
        # cloud_sign_in / cloud_sign_out slots can start/stop it.
        self._autosync_thread = None          # threading.Thread | None
        self._autosync_stop = None            # threading.Event | None
        self._autosync_lock = __import__("threading").Lock()
        self._autosync_ticks = 0              # observability: completed pushes
        try:
            # If the app launches already signed in (token persisted from a
            # prior session), start the scheduler at boot so sync resumes
            # without waiting for a fresh sign-in.
            import cloud_client as _cc
            if _cc.is_signed_in():
                self._start_brain_autosync()
        except Exception:
            pass

    # ─── Brain ⇄ cloud auto-sync scheduler ──────────────────────────
    def _brain_autosync_interval_s(self) -> float:
        """Sync cadence in seconds. Default 600 (10 min); override with
        ARCHHUB_BRAIN_SYNC_INTERVAL_S. Floored at a small positive epsilon
        (0.01s) so a `0` / negative typo can't busy-spin the loop, while
        still allowing fast cadences in tests."""
        import os as _os
        raw = _os.environ.get("ARCHHUB_BRAIN_SYNC_INTERVAL_S", "")
        try:
            val = float(raw) if raw else 600.0
        except (TypeError, ValueError):
            val = 600.0
        return max(0.01, val)

    def _start_brain_autosync(self) -> bool:
        """Start the background auto-sync loop (idempotent). Returns True if a
        new loop was started, False if one was already running. The loop runs
        `brain_cloud_backup` (the existing local→cloud delta push) every
        interval WHILE a cloud token is present; it self-stops if the token
        disappears. Thread is a daemon so it never blocks process exit."""
        import threading as _threading
        with self._autosync_lock:
            existing = self._autosync_thread
            if existing is not None and existing.is_alive():
                return False
            stop = _threading.Event()
            self._autosync_stop = stop

            def _loop():
                interval = self._brain_autosync_interval_s()
                while not stop.is_set():
                    # Wait FIRST so we don't double-push right after sign-in
                    # (sign-in already fires an empty-delta handshake). A
                    # stop() during the wait returns True → clean exit.
                    if stop.wait(interval):
                        break
                    try:
                        import cloud_client as _cc
                        if not _cc.is_signed_in():
                            # Token gone (e.g. expired) — stop syncing; the
                            # next sign-in restarts the loop.
                            break
                    except Exception:
                        # cloud_client missing — nothing to sync against.
                        break
                    try:
                        # Reuse the real push. It is itself threaded + emits
                        # brain_backup_done; we just trigger it on schedule.
                        self.brain_cloud_backup()
                        self._autosync_ticks += 1
                    except Exception:
                        # Best-effort: a failed tick must not kill the loop;
                        # the next interval retries.
                        pass

            t = _threading.Thread(target=_loop, daemon=True,
                                   name="archhub-brain-autosync")
            self._autosync_thread = t
            t.start()
            return True

    def _stop_brain_autosync(self) -> bool:
        """Stop the background auto-sync loop if running. Returns True if a
        loop was signalled to stop, False if none was running. Non-blocking —
        signals the Event; the daemon thread unwinds on its next wake."""
        with self._autosync_lock:
            stop = self._autosync_stop
            thread = self._autosync_thread
            self._autosync_stop = None
            self._autosync_thread = None
        if stop is not None:
            try:
                stop.set()
            except Exception:
                pass
        return bool(thread is not None and thread.is_alive())

    def _brain_autosync_running(self) -> bool:
        """True iff the auto-sync daemon thread is alive. Used by tests +
        any future status surface."""
        t = self._autosync_thread
        return bool(t is not None and t.is_alive())

    def _unbind_brain_owner(self) -> Optional[dict]:
        """Unbind the local brain from the cloud account on sign-out.

        Calls brain.clear_owner() via the memory_gate BrainClient (the
        canonical arbitrary-brain-tool path). The brain DATA is untouched —
        only the persisted owner binding is removed, so the default owner
        reverts to env / OS / 'founder'. Best-effort: returns the clear_owner
        result on success, None when the daemon is unreachable (graceful
        degrade — sign-out still completes locally)."""
        try:
            from memory_gate import BrainClient
            return BrainClient()._call("brain.clear_owner", {}, timeout=3.0)
        except Exception:
            return None

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

    @staticmethod
    def _hash_payload(s: str) -> str:
        """Stable short hash of a string payload — used to key
        `_cached_async` on a graph snapshot so identical canvas states
        share a cache entry (and the cache doesn't grow per keystroke)."""
        import hashlib
        return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:16]

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
                except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
            from datetime import datetime, timezone
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
                "saved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            (SESSIONS_DIR / f"{slug}.archhub-session.json").write_text(
                json.dumps(payload, indent=2), encoding="utf-8",
            )
            self._active_session_id = slug
            # Notify the JSX so the sidebar list refreshes without a
            # relaunch — fresh session should appear immediately.
            try: self.sessions_changed.emit()
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
    # ── Telemetry (track-G, AgDR-0049) — JSX→Python so the pii_redactor
    #    stays the single egress chokepoint. The canvas never imports a
    #    PostHog SDK; all PII scrubbing + the internal-user guard live in
    #    app/telemetry.py. All three slots are fire-and-forget no-ops when
    #    telemetry is off. ──
    @pyqtSlot(str, str)
    def track_event_json(self, name: str, props_json: str) -> None:
        """Fire a product-analytics event from the canvas. props_json is a
        JSON object of bounded, PII-free properties. No-op when telemetry is
        off / the SDK is missing / the user is internal (telemetry guards)."""
        try:
            import json as _json
            import telemetry as _t
            props = _json.loads(props_json) if props_json else {}
            if not isinstance(props, dict):
                props = {}
            _t.track_event(name, **props)
        except Exception:
            pass  # telemetry must never break the UI

    @pyqtSlot(str, str)
    def identify_json(self, user_id: str, traits_json: str) -> None:
        """Bind this install to a cloud user_id on sign-in. Traits (incl.
        email) stay Python-side; the first call aliases the install UUID."""
        try:
            import json as _json
            import telemetry as _t
            traits = _json.loads(traits_json) if traits_json else {}
            if not isinstance(traits, dict):
                traits = {}
            _t.identify(user_id, traits)
        except Exception:
            pass

    @pyqtSlot()
    def telemetry_reset(self) -> None:
        """Clear the identity cache on sign-out so the next user is not
        attributed to the previous one."""
        try:
            import telemetry as _t
            _t.reset()
        except Exception:
            pass

    def _persist_chat_plan(self, *, prompt: str, model: str, result: str,
                            reasoning: list, tool_calls: list,
                            routing_note: str = "", session_id: str = "") -> None:
        """AgDR-0021 — write one ai.plan record for a Composer chat turn.

        Makes every chat turn an inspectable, replayable canvas artefact:
        the ai.plan History modal + Inspector read these back so the
        founder SEES the prompt, the AI's reasoning, the tool calls it
        ran, and the result as NODES — not just a transient chat bubble.

        `session_id` (IA fix, ia-critique-ai-stemcells-2026-06-03 — plans
        belong to a SESSION, not a global pool) roots the record under
        the session's own plan dir and folds into the deterministic id.
        It defaults to "" so existing callers (and the test suite, which
        drives this helper without a session) keep writing to the
        historical global pool, byte-for-byte unchanged.

        Best-effort + atomic (PlanHistory.save writes .tmp then renames).
        A persistence failure never blocks the chat turn — the bubble
        already rendered live; this is the durable record.
        """
        try:
            from plan_history import PlanHistory
            from speckle_wire import default_project_dir
        except Exception:
            return
        try:
            sid = (session_id or "").strip()
            pdir = str(default_project_dir())
            # Session-scoped when a session id is present; the historical
            # global pool when it's empty (back-compat).
            history = PlanHistory(pdir, session_id=sid)
            # Deterministic id keyed on prompt+model (+session) so a
            # re-ask in the SAME session replays the same slot (matches
            # the ai.plan node executor contract); a different session
            # gets its own slot.
            plan_id = PlanHistory.id_for(prompt=prompt or "", model=model or "auto",
                                         session_id=sid)
            import time as _t
            record = {
                "plan_id":  plan_id,
                "session_id": sid,
                "prompt":   prompt or "",
                "model":    model or "auto",
                # `plan` is the canonical tool-invocation list the JSX
                # ai.plan node + History modal render.
                "plan":     tool_calls or [],
                "result":   result or "",
                "reasoning": [str(s) for s in (reasoning or [])],
                "status":   "ok" if (result or tool_calls) else "empty",
                "error":    None,
                "source":   "composer_chat",
                "routing_note": routing_note or "",
                "ts":       int(_t.time()),
            }
            history.save(record)
        except Exception:
            # Honest no-op on failure — never crash the chat thread.
            pass

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
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
            try: self.chat_done.emit(session_id)
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
            return
        if not self.router:
            try: self.chat_error.emit(session_id, "router not wired")
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
            try: self.chat_done.emit(session_id)
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
                # AgDR-0021 — capture the turn so it persists as an
                # auditable ai.plan canvas node (founder demand 2026-06-01:
                # "see everything in nodes — REASONING, tool-calls"). We
                # accumulate the streamed text, every reasoning frame, and
                # every tool invocation, then write one PlanHistory record
                # on completion. The Conversation node still renders live;
                # the plan record is the durable, replayable artefact the
                # ai.plan History modal + Inspector read back.
                _reasoning_steps: list = []
                _tool_calls: list = []
                _text_parts: list = []
                def _on_chunk(piece: str) -> None:
                    if piece:
                        emitted_chunks[0] += 1
                        _text_parts.append(piece)
                        try: self.chat_chunk.emit(session_id, piece)
                        except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
                def _on_reasoning(step: str) -> None:
                    # Forward each provider reasoning frame to JSX so the
                    # Conversation node renders a real trace instead of
                    # the v1.4 mocked 4-line block.
                    if step:
                        _reasoning_steps.append(str(step))
                        try: self.chat_reasoning.emit(session_id, str(step))
                        except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
                def _on_tool(inv) -> None:
                    # Record each tool the turn ran (router-loop tools, e.g.
                    # Anthropic/OpenAI function calls). Keep only completed
                    # frames so we don't log the running→ok duplicate twice.
                    try:
                        if getattr(inv, "status", "") in ("ok", "error"):
                            _tool_calls.append({
                                "id":        getattr(inv, "id", ""),
                                "tool_name": getattr(inv, "tool_name", ""),
                                "arguments": getattr(inv, "arguments", {}),
                                "status":    getattr(inv, "status", ""),
                                "result":    getattr(inv, "result", None),
                            })
                    except Exception:
                        pass
                response = self.router.complete(
                    history=history,
                    model=model,
                    on_chunk=_on_chunk,
                    on_reasoning=_on_reasoning,
                    on_tool_invocation=_on_tool,
                )
                # Only emit response.text as a final chunk if NOTHING was
                # streamed. Otherwise we'd duplicate the entire message.
                if response is not None and emitted_chunks[0] == 0:
                    text_out = getattr(response, "text", "") or ""
                    if text_out:
                        try: self.chat_chunk.emit(session_id, text_out)
                        except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
                # AgDR-0021 — persist this Composer turn as an ai.plan
                # record so it materialises as an inspectable, replayable
                # canvas node (prompt + reasoning + tool-calls + result),
                # not just a transient chat bubble. Best-effort: a failed
                # save never blocks the turn.
                try:
                    final_text = ("".join(_text_parts)
                                  or (getattr(response, "text", "") or ""))
                    # Fold any provider tool-calls the client executed
                    # itself (claude_cli runs its MCP tools in-process and
                    # reports them via tool_calls_log on the LLMResponse).
                    extra_calls = []
                    raw_log = getattr(response, "tool_calls_log", None)
                    if isinstance(raw_log, list):
                        for c in raw_log:
                            if isinstance(c, dict):
                                extra_calls.append({
                                    "tool_name": c.get("name") or "",
                                    "arguments": c.get("input") or {},
                                    "status":    "ok",
                                    "result":    c.get("result"),
                                })
                    self._persist_chat_plan(
                        prompt=text,
                        model=(getattr(response, "model", None) or model),
                        result=final_text,
                        reasoning=_reasoning_steps,
                        tool_calls=_tool_calls + extra_calls,
                        routing_note=getattr(response, "routing_note", "") or "",
                        # IA fix: key this turn's plan to its session so
                        # the ai.plan history is per-session, not a global
                        # pool. `session_id` is the conversation node id
                        # the composer is anchored to (send_chat_history
                        # arg). Empty → global pool (back-compat).
                        session_id=session_id or "",
                    )
                except Exception:
                    pass
                try: self.chat_done.emit(session_id)
                except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
            except Exception as ex:
                # Always emit BOTH chat_error and chat_done so the JS UI
                # doesn't hang waiting for a terminal signal.
                try: self.chat_error.emit(session_id, f"{type(ex).__name__}: {ex}")
                except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
                try: self.chat_done.emit(session_id)
                except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend

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
            from datetime import datetime, timezone
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
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
    @pyqtSlot(str)
    def open_settings(self, section: str = "") -> None:
        """Open the native SettingsDialog on the Qt main thread.

        `section` (optional) names a tab to focus on open, e.g. "account"
        so the Brain "Back up my brain" signed-out CTA lands the founder
        directly on Settings → Account where the real "Sign in to ArchHub
        Cloud" button lives. Empty string keeps the default (first) tab.
        Two stacked @pyqtSlot decorators expose BOTH the legacy no-arg call
        (existing JS: bridgeCall('open_settings')) and the new one-arg call
        (bridgeCall('open_settings','account')) across QWebChannel."""
        from PyQt6.QtCore import QTimer
        sec = str(section or "")
        QTimer.singleShot(0, lambda: self._open_settings_safe(sec))

    def _open_settings_safe(self, section: str = "") -> None:
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
            # Focus the requested tab (e.g. "account") if the dialog
            # supports it. Best-effort — older dialogs without the method
            # just open on their default tab.
            if section:
                focus = getattr(dlg, "focus_section", None)
                if callable(focus):
                    try: focus(section)
                    except Exception: pass  # audit: deliberate-fail-soft — best-effort dialog focus nudge
            dlg.exec()
        except Exception as ex:
            try: self.notice.emit("error", f"Settings unavailable: {ex}")
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend

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
                except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend

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
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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

    # ─── In-app update notification (founder 2026-06-09: a Claude-desktop-
    # style "Update available — Relaunch" prompt for the installed/dev-sync
    # app, so the user KNOWS an update landed instead of a silent re-sync) ────
    @pyqtSlot(result=str)
    def update_status(self) -> str:
        """Is newer code available than what's running? NON-BLOCKING — returns the
        cached delta computed OFF-THREAD by `refresh_updates()`. Does ZERO git /
        subprocess / network I/O on the Qt UI thread (so it can never freeze it; see
        tests/test_no_blocking_slots). Empty `{pending:true}` until the first
        refresh populates the cache. Drives the web-UI 'Update available' poll."""
        cache = getattr(self, "_update_status_cache", None)
        if cache is None:
            return _safe_json({"available": False, "pending": True})
        return _safe_json(cache)

    @pyqtSlot(result=str)
    def refresh_updates(self) -> str:
        """Fire-and-forget: kick the OFF-THREAD fetch + status recompute, so the
        next `update_status()` reflects newly-merged code. Returns INSTANTLY — the
        slot body only starts a daemon thread (NO blocking I/O on the UI thread);
        a busy flag stops overlapping polls stacking git processes."""
        try:
            import threading
            if getattr(self, "_update_fetch_busy", False):
                return _safe_json({"started": False, "busy": True})
            self._update_fetch_busy = True
            threading.Thread(target=self._refresh_updates_work, daemon=True).start()
            return _safe_json({"started": True})
        except Exception as ex:
            return _safe_json({"started": False, "error": str(ex)[:160]})

    def _refresh_updates_work(self) -> None:
        """Daemon-thread body for refresh_updates (NOT a @pyqtSlot): fetch
        origin/main + recompute the `_update_status_cache` that update_status()
        serves. ALL blocking git I/O lives here, never on the Qt UI thread."""
        try:
            import subprocess
            from pathlib import Path
            install_root = Path(__file__).resolve().parent.parent
            import dev_source_sync as dss

            def _rev(root, ref):
                try:
                    r = subprocess.run(
                        ["git", "-C", str(root), "rev-parse", "--short", ref],
                        capture_output=True, text=True, timeout=5,
                        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
                    return r.stdout.strip() if r.returncode == 0 else ""
                except Exception:
                    return ""

            if dss.is_git_checkout(install_root):
                try:
                    subprocess.run(
                        ["git", "-C", str(install_root), "fetch", "origin"],
                        capture_output=True, text=True, timeout=20,
                        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
                except Exception:
                    pass
                head = _rev(install_root, "HEAD")
                upstream = _rev(install_root, "@{u}")
                self._update_status_cache = {
                    "available": bool(head and upstream and head != upstream),
                    "current": head, "latest": upstream, "kind": "git"}
            else:
                src = dss.find_source_root(install_root)
                if src is None:
                    self._update_status_cache = {"available": False, "kind": "none"}
                else:
                    try:
                        dss.pull_source_to_main(src)   # fetch + ff origin/main (guarded)
                    except Exception:
                        pass
                    latest = _rev(src, "origin/main") or _rev(src, "HEAD")
                    marker = dss._read_json(install_root / dss.SYNC_MARKER)
                    current = (marker.get("source_stamp") or {}).get("commit", "")
                    self._update_status_cache = {
                        "available": bool(latest and current and latest != current),
                        "current": current, "latest": latest, "kind": "dev"}
        except Exception:
            pass
        finally:
            self._update_fetch_busy = False

    @pyqtSlot(result=str)
    def last_sync_info(self) -> str:
        """Post-update confirmation feed: when did the dev-sync last copy new
        code in, and to which commit? The web UI shows a '✓ Updated to <commit>'
        toast on launch when `seconds_ago` is small (the sync just happened on
        THIS launch)."""
        try:
            import time
            from pathlib import Path
            install_root = Path(__file__).resolve().parent.parent
            import dev_source_sync as dss
            marker = dss._read_json(install_root / dss.SYNC_MARKER)
            stamp = marker.get("source_stamp") or {}
            synced_at = marker.get("synced_at") or ""
            seconds_ago = None
            if synced_at:
                try:
                    t = time.strptime(synced_at[:19], "%Y-%m-%dT%H:%M:%S")
                    seconds_ago = max(0, int(time.time() - time.mktime(t)))
                except Exception:
                    seconds_ago = None
            return _safe_json({
                "commit": stamp.get("commit", ""),
                "synced_at": synced_at, "seconds_ago": seconds_ago,
            })
        except Exception as ex:
            return _safe_json({"error": str(ex)[:160]})

    @pyqtSlot(result=str)
    def apply_update_and_relaunch(self) -> str:
        """Install the available update + relaunch — the web-UI 'Relaunch' button.
        Returns INSTANTLY: the slot only starts a daemon thread (NO blocking I/O on
        the UI thread; see tests/test_no_blocking_slots). The thread does the
        install (force_sync_now / updater.apply_update) then `updater.restart()`
        (spawns a fresh instance + os._exit's this one). The web UI flushes its
        graph save BEFORE calling this."""
        try:
            import threading
            if getattr(self, "_update_applying", False):
                return _safe_json({"ok": True, "busy": True})
            self._update_applying = True
            threading.Thread(target=self._apply_update_work, daemon=True).start()
            return _safe_json({"ok": True, "started": True})
        except Exception as ex:
            return _safe_json({"ok": False, "message": str(ex)[:200]})

    def _apply_update_work(self) -> None:
        """Daemon-thread body for apply_update_and_relaunch (NOT a @pyqtSlot): all
        blocking work + the os._exit restart, off the Qt UI thread."""
        try:
            import sys
            from pathlib import Path
            install_root = Path(__file__).resolve().parent.parent
            import dev_source_sync as dss
            if dss.is_git_checkout(install_root):
                import updater
                ok, _msg = updater.apply_update()
                if not ok:
                    self._update_applying = False
                    return
            else:
                src = dss.find_source_root(install_root)
                if src is not None:
                    dss.pull_source_to_main(src)
                    dss.force_sync_now(install_root, sys.argv)
            import updater
            updater.restart()   # relaunches + os._exit(0) — does not return
        except Exception:
            self._update_applying = False

    # ─── M4 (AgDR-0021) — Plan history surface ─────────────────
    @pyqtSlot(str, int, result=str)
    @pyqtSlot(str, int, str, result=str)
    def get_plan_history(self, project_dir: str = "",
                          limit: int = 50, session_id: str = "") -> str:
        """List the most-recent `limit` AI-plan records persisted by
        `ai.plan` cooks.

        Records root under either the session's own plan dir
        (`<project_dir>/.archhub/sessions/<session_id>/plans/`) when
        `session_id` is given, or the historical global pool
        (`<project_dir>/.archhub/plans/`) when it's empty.

        Empty project_dir → use the default SpeckleWire project dir
        (the canonical `%LOCALAPPDATA%/ArchHub/projects/default`).

        IA fix (ia-critique-ai-stemcells-2026-06-03): `session_id` is a
        NEW trailing param, defaulted "" — the historical 2-arg call
        (`get_plan_history(project_dir, limit)`) is unchanged and still
        reads the global pool, so old global plans keep showing.

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
            history = PlanHistory(pdir, session_id=(session_id or "").strip())
            records = history.list_records(limit=max(1, int(limit)))
            return _safe_json({"records": records,
                                "count": len(records),
                                "project_dir": pdir,
                                "session_id": (session_id or "").strip()})
        except Exception as ex:
            return _safe_json({"error": f"{type(ex).__name__}: {ex}"})

    @pyqtSlot(str, str, result=str)
    @pyqtSlot(str, str, str, result=str)
    def get_plan_record(self, plan_id: str,
                         project_dir: str = "", session_id: str = "") -> str:
        """Load one plan record by id. Returns the record JSON or
        `{error:"not_found"}`.

        IA fix: `session_id` (NEW trailing param, defaulted "") roots the
        lookup in the session's plan dir; empty → the global pool, so the
        historical 2-arg call is unchanged."""
        try:
            from plan_history import PlanHistory
            pdir = (project_dir or "").strip()
            if not pdir:
                from speckle_wire import default_project_dir
                pdir = str(default_project_dir())
            history = PlanHistory(pdir, session_id=(session_id or "").strip())
            rec = history.load((plan_id or "").strip())
            if rec is None:
                return _safe_json({"error": "not_found"})
            return _safe_json(rec)
        except Exception as ex:
            return _safe_json({"error": f"{type(ex).__name__}: {ex}"})

    @pyqtSlot(str, str, result=str)
    @pyqtSlot(str, str, str, result=str)
    def delete_plan_record(self, plan_id: str,
                            project_dir: str = "", session_id: str = "") -> str:
        """Drop one record from disk. Returns `{ok:true}` or
        `{ok:false, error:"…"}`.

        IA fix: `session_id` (NEW trailing param, defaulted "") roots the
        delete in the session's plan dir; empty → the global pool, so the
        historical 2-arg call is unchanged."""
        try:
            from plan_history import PlanHistory
            pdir = (project_dir or "").strip()
            if not pdir:
                from speckle_wire import default_project_dir
                pdir = str(default_project_dir())
            history = PlanHistory(pdir, session_id=(session_id or "").strip())
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

    # ─── Accessibility prefs (read-only exposure to the React UI) ─
    @pyqtSlot(result=str)
    def get_a11y_prefs(self) -> str:
        """Expose the accessibility preferences the Settings →
        Accessibility tab persists locally (settings_dialog.AccessibilityTab
        ._save → secrets_store.save_setting under the same keys).

        The React UI (studio-lm.jsx boot effect) reads this on mount to
        apply `reduce_motion` (toggles html.lm-reduce-motion). font_size /
        contrast / screen_reader are returned for completeness but are NOT
        yet applied in the UI — that's deferred pending a design decision
        (px-scale refactor / high-contrast palette / component aria work).

        Never raises — returns sane defaults on any error so the boot
        effect can rely on a well-shaped object."""
        try:
            from secrets_store import load_setting
            return _safe_json({
                "reduce_motion": bool(load_setting("a11y_reduce_motion")),
                "screen_reader": bool(load_setting("a11y_screen_reader")),
                "font_size": load_setting("a11y_font_size") or "default",
                "contrast": load_setting("a11y_contrast") or "default",
            })
        except Exception:
            return _safe_json({
                "reduce_motion": False,
                "screen_reader": False,
                "font_size": "default",
                "contrast": "default",
            })

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
            # Write back to the EXACT file we loaded (`p`), not a re-slugified
            # name. create_session slugifies "ping rhino" -> "ping-rhino"
            # (hyphen) and load_session reads `<sid>.archhub-session.json`, but
            # session_io._slugify("ping rhino") -> "ping_rhino" (underscore).
            # Without path=p, save_session wrote the UNDERSCORE file while the
            # loader looked for the HYPHEN one — so a saved graph never loaded
            # back (founder bug 2026-06-02: "saved but empty", second cause
            # under the empty-payload refusal). Passing path keeps the
            # save/load round-trip on one file regardless of slug convention.
            save_session(session, name=name, path=p, messages=messages or None)
            try: self.sessions_changed.emit()
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
        can render a single-line banner without crashing.

        AgDR-0036 follow-up — `memory.query()` opens the graph.sqlite
        knowledge graph and runs a community-aware BFS (measured ~6-7 ms
        per call). This slot is called on EVERY search keystroke; running
        it synchronously in the @pyqtSlot body janked the Qt main thread
        on every character. Now routed through `_cached_async` keyed by
        the query envelope: the cached result returns instantly, the
        SQLite query runs on the background pool, and `memory_changed`
        fires when fresh data lands so the search consumer re-pulls the
        (now-cached) hits. No SQLite ever touches the main thread."""
        try:
            import json as _json
            args = _json.loads(args_json or "{}")
            if not isinstance(args, dict):
                return _safe_json({"status": "error",
                                    "error": "args must be an object"})
            if self.tools is None:
                return _safe_json({"status": "error",
                                    "error": "tool engine not initialised"})
        except Exception as ex:
            return _safe_json({"status": "error",
                                "error": f"{type(ex).__name__}: {ex}"})

        # Cheap input validation stays INLINE (no I/O) so the caller gets
        # an immediate, correct error — only the SQLite query goes
        # off-thread. (The JSX search consumers already guard q.length>=2,
        # so the empty-question path is defensive.)
        if not str(args.get("question", "") or "").strip():
            return _safe_json({"status": "error",
                                "error": "memory_query needs `question`"})

        def _work():
            try:
                return self.tools.invoke("memory_query", args)
            except Exception as ex:
                return {"status": "error",
                        "error": f"{type(ex).__name__}: {ex}"}

        # Cache key = the normalised query envelope so distinct searches
        # don't collide and an identical repeated search hits cache. Short
        # TTL — memory facts change as the user works, so re-query soon.
        key = "memory_query:" + _safe_json(args)
        return _safe_json(self._cached_async(
            key, _work, ttl=5.0,
            empty={"status": "ok", "results": [], "count": 0},
            signal_name="memory_changed"))

    @pyqtSlot(result=str)
    def get_brain_stats(self) -> str:
        """Snapshot of the last AgDR-0044 Layer 5 brain pre_prompt hit.

        Polled by the JSX BrainChip near the ModelStrip so the user
        sees a live `⌬ brain · N skills · M facts · Δms` indicator
        without round-tripping the gate. Returns the in-process module
        global `memory_gate._LAST_BRAIN_STATS` updated on every
        MemoryGate.pre_prompt call. Empty dict before the first turn.

        Shape:
          {ts, skills_n, facts_n, secret_refs_n, retrieval_ms,
           user_message_preview, available, client_status}
        """
        try:
            from memory_gate import get_last_brain_stats
            return _safe_json(get_last_brain_stats() or {})
        except Exception as ex:
            return _safe_json({"error": f"{type(ex).__name__}: {ex}"})

    # ─────────────────────── Slice 9-16 settings bridge ──────────────
    # AgDR-0045 — Settings × Brain. Every slot proxies to a brain.* MCP
    # tool. Returns JSON string (QWebChannel friendly). Errors land as
    # {"ok":false,"error":"..."} — never raise across the bridge.

    def _brain_tool(self, tool_name: str, args: dict,
                    timeout: float = 4.0) -> dict:
        """Internal helper — call a brain MCP tool via the local BrainClient.

        MUST NOT be called from a @pyqtSlot body on the Qt main thread —
        it does a blocking HTTP round-trip to the brain daemon
        (`http://127.0.0.1:8473/mcp`) and the daemon is frequently DOWN,
        so a call can stall for the full `timeout`. Every caller routes
        through `_cached_async` / `_bg_pool` so this runs on a worker
        thread. `timeout` is exposed so hot paths can fast-fail (a short
        connect timeout) instead of waiting the default 4 s for a dead
        daemon."""
        try:
            from memory_gate import BrainClient
        except Exception as ex:
            return {"ok": False, "error": f"BrainClient import: {ex}"}
        try:
            client = BrainClient()
            # Reuse the BrainClient transport (handles SSE + stateless HTTP)
            result = client._call(tool_name, args, timeout=timeout)
            if isinstance(result, dict):
                return result
            return {"ok": True, "result": result}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    @pyqtSlot(result=str)
    def brain_status(self) -> str:
        """Health probe + daemon status. Drives the status pulse + stats
        tiles in Settings → Brain."""
        try:
            health = self._brain_tool("brain.health", {})
            from memory_gate import get_last_brain_stats
            last_hit = get_last_brain_stats() or {}
            return _safe_json({
                "ok": health.get("ok", False),
                "health": health,
                "last_hit": last_hit,
            })
        except Exception as ex:
            return _safe_json({"ok": False, "error": f"{type(ex).__name__}: {ex}"})

    @pyqtSlot(str, str, int, result=str)
    def brain_firm_create(self, name: str, created_by: str = "",
                            force: int = 0) -> str:
        return _safe_json(self._brain_tool("brain.firm_create", {
            "name": name, "created_by": created_by or None,
            "force": bool(force),
        }))

    @pyqtSlot(str, int, result=str)
    def brain_firm_invite_create(self, role: str = "seat",
                                   ttl_hours: int = 24) -> str:
        return _safe_json(self._brain_tool("brain.firm_invite_create", {
            "role": role, "ttl_hours": ttl_hours,
        }))

    @pyqtSlot(str, str, result=str)
    def brain_firm_invite_accept(self, token: str, user_id: str = "") -> str:
        return _safe_json(self._brain_tool("brain.firm_invite_accept", {
            "token": token, "user_id": user_id or None,
        }))

    @pyqtSlot(result=str)
    def brain_firm_seats(self) -> str:
        return _safe_json(self._brain_tool("brain.firm_seats", {}))

    @pyqtSlot(result=str)
    def brain_firm_leave(self) -> str:
        return _safe_json(self._brain_tool("brain.firm_leave", {}))

    @pyqtSlot(str, str, int, result=str)
    def brain_promote(self, fragment_id: str, target_scope: str,
                       is_maintainer: int = 0) -> str:
        return _safe_json(self._brain_tool("brain.promote", {
            "fragment_id": fragment_id,
            "target_scope": target_scope,
            "is_maintainer": bool(is_maintainer),
        }))

    @pyqtSlot(result=str)
    def brain_wiring_announce(self) -> str:
        """Manual trigger of SessionStart-style wiring announce. Used by
        Settings → Brain → 'Rescan' button."""
        import os as _os
        import socket as _sock
        return _safe_json(self._brain_tool("brain.wiring_announce", {
            "device_id": _sock.gethostname() or "device-?",
            "cwd": _os.getcwd(),
        }))

    @pyqtSlot(str, str, result=str)
    def brain_export_dataset(self, scope: str = "user",
                             dataset_name: str = "my-brain") -> str:
        """Brain #32 — export the brain as a HuggingFace-style training
        dataset via the brain.dataset_export MCP tool.

        Founder vision (2026-05-26): *"this brain should be able to produce
        training datasets."* This is the user-facing surface — the Brain
        view's "Generate training dataset" button calls this slot.

        `scope` is a founder-facing key: "user" (your private memory),
        "project", "firm", or "collective". COLLECTIVE never emits raw rows
        — the export tool routes it through privacy.privatize_for_collective
        (differential-privacy aggregates only). Maps "collective" → the
        brain's COMMUNITY pool string the tool understands.

        Runs on the background pool + emits brain_dataset_done(result_json)
        when finished, so a large brain never freezes the Qt main thread
        (and never trips bridgeAsync's 1.5s synchronous ceiling). Returns
        immediately with {async, request_id, out_dir}.

        The manifest the signal carries includes row_count, scope_distribution,
        and files{jsonl{path,bytes}} — real proof a dataset hit disk.
        """
        import os as _os
        import uuid as _uuid
        request_id = _uuid.uuid4().hex[:12]

        # Founder-facing scope key → brain scope string. "collective" is the
        # privacy-gated path: the export tool detects a collective-class scope
        # and emits DP aggregates instead of raw rows.
        scope_key = (scope or "user").strip().lower()
        _SCOPE_MAP = {
            "user": "user", "you": "user", "u": "user",
            "project": "project", "p": "project",
            "firm": "firm", "f": "firm",
            "collective": "collective", "community": "collective", "c": "collective",
        }
        brain_scope = _SCOPE_MAP.get(scope_key, "user")

        # User-visible export location under the repo so the founder can find
        # the dataset on disk. Created up-front so a failure path still has a
        # real directory to report.
        out_dir = _os.path.join(_os.getcwd(), "exports", "brain-datasets")
        try:
            _os.makedirs(out_dir, exist_ok=True)
        except Exception:
            pass

        safe_name = (dataset_name or "my-brain").strip() or "my-brain"

        def _runner():
            payload: dict
            try:
                from memory_gate import BrainClient
                client = BrainClient()
                # Generous timeout — local SQLite read + JSONL write is fast,
                # but a cold daemon may need a moment. Stays under the 60s
                # no-long-waits floor.
                result = client._call("brain.dataset_export", {
                    "out_dir": out_dir,
                    "dataset_name": safe_name,
                    "scopes": [brain_scope],
                }, timeout=45.0)
                payload = result if isinstance(result, dict) \
                    else {"ok": True, "result": result}
            except Exception as ex:
                # Degrade gracefully — daemon down / unreachable lands here.
                payload = {"ok": False,
                           "error": f"{type(ex).__name__}: {ex}"}
            payload["request_id"] = request_id
            payload.setdefault("scope", brain_scope)
            payload.setdefault("out_dir", out_dir)
            try:
                self.brain_dataset_done.emit(_safe_json(payload))
            except Exception:
                pass

        try:
            self._bg_pool().submit(_runner)
        except Exception as ex:
            return _safe_json({"async": False, "request_id": request_id,
                               "ok": False,
                               "error": f"pool submit: {ex}"})
        return _safe_json({"async": True, "request_id": request_id,
                           "out_dir": out_dir, "scope": brain_scope})

    # ─── Visual brain browser (BrainViewModal "Your brain, organized") ──
    @pyqtSlot(result=str)
    def brain_browse(self) -> str:
        """Organized brain view for the founder-facing visual browser.

        Returns the four coordinated views (top-of-mind cards, facet lanes,
        archived tray, learning timeline) assembled READ-ONLY by the daemon's
        `brain.browse` tool. The tool walks every fragment + computes
        decay-weighted salience — heavier than the 1.5 s bridgeAsync ceiling on
        a cold daemon — so this is routed through `_cached_async`: the cached
        snapshot returns INSTANTLY on the Qt main thread, the real `brain.browse`
        HTTP call runs ONLY on the background pool, and `brain_browse_changed`
        fires when fresh data lands so the modal re-pulls. A down daemon
        degrades to an honest empty payload (ANTI-LIE — never a fabricated
        view), and the modal keeps its existing 7-layer map regardless."""
        return _safe_json(self._cached_async(
            "brain_browse_view", self._compute_brain_browse,
            ttl=20.0,
            empty={"ok": False, "pending": True, "totals": {},
                   "top_of_mind": [], "facets": [], "archived": [],
                   "timeline": []},
            signal_name="brain_browse_changed"))

    def _compute_brain_browse(self) -> dict:
        """Heavy body for `brain_browse` — runs ONLY on the background pool via
        `_cached_async`, never the Qt main thread. One blocking HTTP call to the
        brain daemon's read-only browse tool. Fast-fails (3 s) so a dead daemon
        can't pin a worker thread; the honest empty payload carries the down
        state to the UI."""
        res = self._brain_tool("brain.browse", {}, timeout=3.0)
        if isinstance(res, dict) and res.get("ok"):
            return res
        # Daemon down / tool missing — honest degraded payload.
        err = res.get("error") if isinstance(res, dict) else None
        return {"ok": False, "degraded": err or "brain daemon unreachable",
                "totals": {}, "top_of_mind": [], "facets": [],
                "archived": [], "timeline": []}

    @pyqtSlot(str, result=str)
    @pyqtSlot(str, str, result=str)
    def brain_search(self, query: str, project: str = "") -> str:
        """Run the brain's real retrieval ranker for `query` and return the hits
        as browser cards (facet colour + 'matches your search').

        Threaded server-side (FTS5 + vector rerank can exceed the 1.5 s sync
        ceiling); returns instantly with {async, request_id} and emits
        `brain_search_done(result_json)` when finished. request_id-stamped so a
        stale result never overwrites the current search. Empty/blank query is
        answered inline with an empty card list (no daemon round-trip). An
        optional `project` (e.g. 'P-674') scopes the search to one project's
        facts, matching the browser's project filter chip-row."""
        import uuid as _uuid
        q = (query or "").strip()
        proj = (project or "").strip()
        request_id = _uuid.uuid4().hex[:12]
        if not q:
            return _safe_json({"async": False, "request_id": request_id,
                               "ok": True, "query": "", "cards": []})

        def _runner():
            payload: dict
            try:
                args = {"query": q}
                if proj:
                    args["project"] = proj
                res = self._brain_tool("brain.browse", args, timeout=20.0)
                if isinstance(res, dict) and res.get("ok"):
                    payload = {"ok": True, "query": q,
                               "cards": res.get("search", [])}
                else:
                    err = res.get("error") if isinstance(res, dict) else None
                    payload = {"ok": False, "query": q, "cards": [],
                               "error": err or "brain daemon unreachable"}
            except Exception as ex:
                payload = {"ok": False, "query": q, "cards": [],
                           "error": f"{type(ex).__name__}: {ex}"}
            payload["request_id"] = request_id
            try:
                self.brain_search_done.emit(_safe_json(payload))
            except Exception:
                pass

        try:
            self._bg_pool().submit(_runner)
        except Exception as ex:
            return _safe_json({"async": False, "request_id": request_id,
                               "ok": False, "error": f"pool submit: {ex}"})
        return _safe_json({"async": True, "request_id": request_id, "query": q})

    @pyqtSlot(str, result=str)
    def brain_restore(self, fragment_id: str) -> str:
        """Restore a faded/archived note to active memory (clears valid_until).

        The visual browser's 'Restore' button calls this. Runs the daemon's
        `brain.restore` tool on the background pool (it's a write — must not
        block the Qt main thread) and emits `brain_browse_changed` on success
        so the modal re-pulls and the card leaves the archived tray. Returns
        instantly with {async, request_id}; an honest failure (daemon down) is
        reported via the signal payload."""
        import uuid as _uuid
        fid = (fragment_id or "").strip()
        request_id = _uuid.uuid4().hex[:12]
        if not fid:
            return _safe_json({"async": False, "request_id": request_id,
                               "ok": False, "error": "missing fragment_id"})

        def _runner():
            try:
                res = self._brain_tool("brain.restore", {"fragment_id": fid},
                                       timeout=10.0)
                ok = isinstance(res, dict) and res.get("ok")
            except Exception:
                ok = False
            if ok:
                # View changed — let the modal re-pull the organized snapshot.
                try: self.brain_browse_changed.emit()
                except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend

        try:
            self._bg_pool().submit(_runner)
        except Exception as ex:
            return _safe_json({"async": False, "request_id": request_id,
                               "ok": False, "error": f"pool submit: {ex}"})
        return _safe_json({"async": True, "request_id": request_id})

    # ─── Multi-device COMMUNITIES (BrainViewModal → Communities panel) ──
    # The community MECHANISM (brain.community_* — 8 tools on the daemon) was
    # wired-not-shipped: no GUI. These slots are its desktop surface. Every
    # body calls a brain.community_* tool, which does a BLOCKING HTTP round
    # trip to the (frequently-down) daemon — so NONE of this runs on the Qt
    # main thread:
    #   • READS  (community_groups / community_members / community_owned_server)
    #     route through `_cached_async` — cached value returns INSTANTLY, the
    #     real `_brain_tool` call runs ONLY on the background pool, and
    #     `community_changed` fires when fresh data lands so the panel re-pulls.
    #   • WRITES (community_create / community_join_code / community_join /
    #     community_set_transport / community_leave) run on `_bg_pool` via the
    #     shared `_community_write` helper and deliver a definitive answer over
    #     `community_op_done(result_json)` (request_id-stamped — the
    #     connector_op_done / node_op_done idiom the JSX's bridgeAsyncSignal
    #     already understands). A successful write also emits `community_changed`
    #     so the reads re-pull. Mirrors brain_browse / brain_search / brain_restore.

    @pyqtSlot(result=str)
    def community_groups(self) -> str:
        """READ — the multi-device communities this device knows about, plus
        which one is current (drives the Communities panel's "Current
        community" header + "No community yet" empty state).

        Routed through `_cached_async`: the cached snapshot returns instantly
        on the Qt main thread, the blocking `brain.community_groups` HTTP call
        runs ONLY on the background pool, and `community_changed` fires when
        fresh data lands so the panel re-pulls. Honest empty payload when the
        daemon is down (ANTI-LIE — never a fabricated community)."""
        return _safe_json(self._cached_async(
            "community_groups", self._compute_community_groups,
            ttl=15.0,
            empty={"ok": False, "pending": True,
                   "current_community_id": None, "communities": []},
            signal_name="community_changed"))

    def _compute_community_groups(self) -> dict:
        """Heavy body for `community_groups` — background pool only. One
        blocking HTTP call, fast-failing (3 s) so a dead daemon can't pin a
        worker."""
        res = self._brain_tool("brain.community_groups", {}, timeout=3.0)
        if isinstance(res, dict) and res.get("ok"):
            return res
        err = res.get("error") if isinstance(res, dict) else None
        return {"ok": False, "degraded": err or "brain daemon unreachable",
                "current_community_id": None, "communities": []}

    @pyqtSlot(result=str)
    @pyqtSlot(str, result=str)
    def community_members(self, community_id: str = "") -> str:
        """READ — the members (devices/users) of the current community (or an
        explicit `community_id`). Drives the panel's MEMBERS list.

        `_cached_async` keyed per community_id so switching communities doesn't
        show a stale roster; re-pulls on `community_changed`. Honest empty list
        when the daemon is down."""
        cid = (community_id or "").strip()
        key = "community_members:" + (cid or "_current")

        def _work():
            args = {"community_id": cid} if cid else {}
            res = self._brain_tool("brain.community_members", args, timeout=3.0)
            if isinstance(res, dict) and res.get("ok"):
                return res
            err = res.get("error") if isinstance(res, dict) else None
            return {"ok": False, "degraded": err or "brain daemon unreachable",
                    "community_id": cid or None, "members": []}

        return _safe_json(self._cached_async(
            key, _work, ttl=15.0,
            empty={"ok": False, "pending": True,
                   "community_id": cid or None, "members": []},
            signal_name="community_changed"))

    @pyqtSlot(result=str)
    @pyqtSlot(str, result=str)
    def community_owned_server(self, base_url: str = "") -> str:
        """READ — owned-server readiness for a `speckle` community transport.

        Reports {reachable, docker_available, can_start, code, message}: code
        is 'running' / 'ready_to_start' / 'docker_missing'. The panel uses
        docker_available + code to show the "install Docker Desktop to
        self-host" hint when absent. `brain.community_owned_server` probes a
        port + Docker (blocking, multi-second) so it is `_cached_async` — never
        on the Qt main thread."""
        url = (base_url or "").strip()
        key = "community_owned_server:" + (url or "_default")

        def _work():
            args = {"base_url": url} if url else {}
            res = self._brain_tool("brain.community_owned_server", args,
                                   timeout=4.0)
            if isinstance(res, dict) and res.get("ok"):
                return res
            err = res.get("error") if isinstance(res, dict) else None
            return {"ok": False, "degraded": err or "brain daemon unreachable",
                    "reachable": False, "docker_available": False,
                    "can_start": False, "code": "unknown",
                    "message": err or "Brain daemon unreachable — can't probe "
                                      "the owned server yet."}

        return _safe_json(self._cached_async(
            key, _work, ttl=10.0,
            empty={"ok": False, "pending": True, "reachable": False,
                   "docker_available": False, "can_start": False,
                   "code": "pending", "message": "Checking owned server…"},
            signal_name="community_changed"))

    def _community_write(self, tool_name: str, args: dict,
                         request_id: str) -> str:
        """Shared WRITE driver for the community panel. Runs `tool_name`
        (a brain.community_* mutation) on `_bg_pool` — NEVER the Qt main
        thread — and emits `community_op_done(result_json)` with the result +
        `request_id` stamped in (so the JSX's bridgeAsyncSignal correlates the
        answer to its click). On success also emits `community_changed` so the
        cached reads (groups / members / owned_server) re-pull. Returns the
        instant {async, request_id} ack."""
        def _runner():
            payload: dict
            try:
                res = self._brain_tool(tool_name, args, timeout=12.0)
                if isinstance(res, dict):
                    payload = dict(res)
                    payload.setdefault("ok", False)
                else:
                    payload = {"ok": False,
                               "error": "unexpected tool result"}
            except Exception as ex:
                payload = {"ok": False,
                           "error": f"{type(ex).__name__}: {ex}"}
            payload["request_id"] = request_id
            if payload.get("ok"):
                try: self.community_changed.emit()
                except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
            try:
                self.community_op_done.emit(_safe_json(payload))
            except Exception:
                pass

        try:
            self._bg_pool().submit(_runner)
        except Exception as ex:
            return _safe_json({"async": False, "request_id": request_id,
                               "ok": False, "error": f"pool submit: {ex}"})
        return _safe_json({"async": True, "request_id": request_id})

    @pyqtSlot(str, str, result=str)
    def community_create(self, name: str, request_id: str = "") -> str:
        """WRITE — create a multi-device community; the caller becomes OWNER.

        Transport is intentionally NOT chosen here — it defaults to 'disk'
        (offline JSON snapshot) on the daemon and the founder picks the real
        transport afterward via the panel's TRANSPORT SELECTOR
        (community_set_transport). Off-thread; answer via community_op_done."""
        import uuid as _uuid
        rid = (request_id or "").strip() or _uuid.uuid4().hex[:12]
        nm = (name or "").strip()
        if not nm:
            return _safe_json({"async": False, "request_id": rid,
                               "ok": False, "error": "community name required"})
        return self._community_write(
            "brain.community_create", {"name": nm}, rid)

    @pyqtSlot(str, int, str, result=str)
    def community_join_code(self, role: str = "member",
                            ttl_hours: int = 168,
                            request_id: str = "") -> str:
        """WRITE (owner-only) — mint a signed join-code + archhub:// URL for the
        current community so a second device can join. Default TTL 168 h
        (7 days). The daemon rejects this when this device isn't the owner; the
        honest {ok:false, error} rides back over community_op_done. Off-thread."""
        import uuid as _uuid
        rid = (request_id or "").strip() or _uuid.uuid4().hex[:12]
        return self._community_write(
            "brain.community_join_code",
            {"role": (role or "member").strip() or "member",
             "ttl_hours": int(ttl_hours) if ttl_hours else 168}, rid)

    @pyqtSlot(str, str, result=str)
    def community_join(self, code: str, request_id: str = "") -> str:
        """WRITE — join a community on THIS device from a join-code (bare token
        OR the full archhub://community/join?code=... URL). The panel's JOIN
        field (second-device flow) calls this. Signature + expiry are verified
        offline by the daemon. Off-thread; answer via community_op_done."""
        import uuid as _uuid
        rid = (request_id or "").strip() or _uuid.uuid4().hex[:12]
        c = (code or "").strip()
        if not c:
            return _safe_json({"async": False, "request_id": rid,
                               "ok": False, "error": "paste a join code"})
        return self._community_write(
            "brain.community_join", {"code": c}, rid)

    @pyqtSlot(str, str, str, result=str)
    def community_set_transport(self, transport_kind: str,
                                transport_base_url: str = "",
                                request_id: str = "") -> str:
        """WRITE — point the current community at a transport: 'cloud_relay'
        (works anywhere), 'disk' (shared Dropbox/OneDrive folder), or 'speckle'
        (LAN/Tailscale owned server). This is the founder's fork, exposed in the
        panel as an explicit CHOICE (default-none) — not a silent default.
        `transport_base_url` carries the folder path (disk) or server URL
        (speckle); ignored for cloud_relay. Off-thread; answer via
        community_op_done, which also triggers a roster re-pull."""
        import uuid as _uuid
        rid = (request_id or "").strip() or _uuid.uuid4().hex[:12]
        kind = (transport_kind or "").strip()
        if kind not in ("cloud_relay", "disk", "speckle"):
            return _safe_json({"async": False, "request_id": rid, "ok": False,
                               "error": "transport must be cloud_relay, disk, "
                                        "or speckle"})
        args = {"transport_kind": kind,
                "transport_base_url": (transport_base_url or "").strip()}
        return self._community_write(
            "brain.community_set_transport", args, rid)

    @pyqtSlot(str, result=str)
    def community_leave(self, request_id: str = "") -> str:
        """WRITE — leave the current community on this device (tombstones this
        device's member fragment; reversible by re-joining with a fresh code).
        Off-thread; answer via community_op_done + a re-pull."""
        import uuid as _uuid
        rid = (request_id or "").strip() or _uuid.uuid4().hex[:12]
        return self._community_write("brain.community_leave", {}, rid)

    # ─── Cloud-DB backup — "Back up my brain" ──────────────────────────
    @pyqtSlot(result=str)
    def brain_cloud_backup_status(self) -> str:
        """Cheap, synchronous probe that drives the Brain view's "Back up
        my brain" button enabled/disabled state.

        Returns {signed_in: bool, cloud_url: str}. `signed_in` is True iff a
        non-expired cloud bearer token is present (resolved through
        cloud_client → secrets_store, which holds the credential encrypted
        at rest — never plaintext in code). The JSX enables the button only
        when signed_in is True; otherwise it keeps the honest
        "Sign in to enable cloud backup" state. No network I/O — safe to
        call on every Brain-view open without tripping bridgeAsync's 1.5s
        ceiling."""
        try:
            import cloud_client
            return _safe_json({
                "signed_in": bool(cloud_client.is_signed_in()),
                "cloud_url": cloud_client.base_url(),
            })
        except Exception as ex:
            # Module missing on a slimmed install → treat as not signed in
            # (button stays honestly disabled). Never raise across the bridge.
            return _safe_json({"signed_in": False,
                               "error": f"{type(ex).__name__}: {ex}"})

    @pyqtSlot(result=str)
    def brain_cloud_backup(self) -> str:
        """Cloud-DB backup — the real client push behind the Brain view's
        "Back up my brain" button (cloud server live since commit 0dce168,
        POST /v1/brain/sync with Bearer auth + per-user sqlite replica).

        Token resolution (BRAIN-FIRST · secrets are references only): the
        cloud bearer token is read via cloud_client.current_token(), which
        loads it from secrets_store (encrypted at rest, the same path the
        op:// / browser sign-in writes). NO token is ever embedded in code.
        If absent → returns {ok:false, need_signin:true, msg:...} so the UI
        keeps the honest "Sign in to enable" state (the agent never signs in
        — that's the founder's one manual step, per safety rules).

        When a token IS present: gather a brain delta (USER-scope fragments
        via the same brain.dataset_export tool the "Generate training
        dataset" button uses → fragments.jsonl on disk → fragment list) plus
        a wiring announce for this device, then POST it to
        <cloud_url>/v1/brain/sync with Authorization: Bearer <token>. The
        cloud URL comes from cloud_client.base_url() (env-overridable via
        ARCHHUB_CLOUD_BASE_URL — never a hardcoded prod URL here).

        Threaded + signal-based like brain_export_dataset: returns
        immediately with {async, request_id} and emits brain_backup_done(
        result_json) — {ok:true, synced:N, new_hlc, rejected, request_id} on
        success, {ok:false, error|need_signin, request_id} otherwise — so a
        large brain never freezes the Qt main thread. Match on request_id in
        the JSX so a stale result never overwrites the current one."""
        import uuid as _uuid
        request_id = _uuid.uuid4().hex[:12]

        def _emit(payload: dict) -> None:
            payload.setdefault("request_id", request_id)
            try:
                self.brain_backup_done.emit(_safe_json(payload))
            except Exception:
                pass

        def _runner():
            # 1. Resolve the cloud token (encrypted at rest; never plaintext).
            try:
                import cloud_client
                token = cloud_client.current_token()
                cloud_url = cloud_client.base_url()
            except Exception as ex:
                _emit({"ok": False,
                       "error": f"cloud client unavailable: {ex}"})
                return
            if not token:
                # Honest gate — the founder must sign in (the one manual
                # step). Never fabricate a backup.
                _emit({"ok": False, "need_signin": True,
                       "msg": "Sign in to enable cloud backup"})
                return

            # 2. Gather a brain delta — SLICE-17 FANOUT. Reuse the new
            #    brain.fanout_export tool to enumerate RAW fragment rows for
            #    USER + FIRM + COMMUNITY scope (was USER-only via
            #    dataset_export). FIRM/COMMUNITY rows converge through the
            #    cloud's shared replicas so a teammate / 2nd device receives
            #    them; USER rows stay private per account. We use
            #    fanout_export (not dataset_export) precisely because
            #    dataset_export routes COMMUNITY to DP-aggregates for model
            #    training — the multi-device convergence path wants raw rows
            #    (community_groups.py: COMMUNITY groups converge raw, keyed by
            #    community_id). GLOBAL is never requested (DP-only).
            import json as _json
            import socket as _sock
            fragments: list = []
            client = None
            try:
                from memory_gate import BrainClient
                client = BrainClient()
                export = client._call("brain.fanout_export", {
                    "scopes": ["user", "firm", "community"],
                }, timeout=45.0)
                if isinstance(export, dict) and export.get("ok"):
                    fragments = list(export.get("fragments") or [])
                elif isinstance(export, dict) and export.get("error"):
                    _emit({"ok": False,
                           "error": f"brain export failed: {export['error']}"})
                    return
            except Exception as ex:
                # Daemon down / unreachable → fail honestly, never a fake ok.
                _emit({"ok": False,
                       "error": f"could not read local brain: "
                                f"{type(ex).__name__}: {ex}"})
                return

            # 2b. Which multi-device communities ride the CLOUD RELAY?
            #     community_groups.TransportConfig.kind == "cloud_relay" means
            #     "POST deltas to ArchHub's /v1/brain/sync replica" — exactly
            #     this fanout. We pass those community_ids so the cloud unions
            #     their shared per-community replicas on the pull, converging
            #     COMMUNITY fragments across every relay member. (A `disk` /
            #     `speckle` community syncs through its own transport, not the
            #     cloud, so it is NOT listed here.) Best-effort: a missing/old
            #     daemon just yields no community keys (firm + user still
            #     converge).
            community_keys: list = []
            try:
                groups = client._call("brain.community_groups", {}, timeout=10.0)
                if isinstance(groups, dict):
                    for c in (groups.get("communities") or []):
                        if not isinstance(c, dict):
                            continue
                        cid = c.get("community_id")
                        transport = c.get("transport") or {}
                        kind = (transport.get("kind") if isinstance(transport, dict)
                                else "") or ""
                        if cid and kind == "cloud_relay":
                            community_keys.append(str(cid))
            except Exception:
                community_keys = []

            # 2c. Keep non-relay communities OFF the cloud. fanout_export
            #     returns ALL community rows, but only communities whose
            #     transport is cloud_relay should converge through the cloud.
            #     Drop community-scope fragments whose community_id is not a
            #     relay community (disk/speckle communities sync elsewhere) so
            #     their facts never land in a cloud replica at all.
            if fragments:
                relay_set = set(community_keys)
                kept = []
                for f in fragments:
                    if (f.get("scope") or "").strip().lower() == "community":
                        cid = (f.get("extra") or {}).get("community_id") \
                            or f.get("firm_id")
                        if not cid or str(cid) not in relay_set:
                            continue  # non-relay community → not cloud-synced
                    kept.append(f)
                fragments = kept

            wiring = [{
                "name": "archhub-desktop",
                "device_id": _sock.gethostname() or "device-?",
                "kind": "desktop",
                "status": "active",
            }]
            delta = {"fragments": fragments, "wiring": wiring}

            # 3. PUSH the delta + PULL the merged delta back via the shared
            #    cloud_client.brain_sync helper (Bearer + error envelope reused
            #    from every other cloud call). since_hlc="" pulls the full
            #    merged firm/community state (a backup AND a curated feed).
            server = cloud_client.brain_sync(
                delta=delta, since_hlc="", community_keys=community_keys)
            if server.get("error"):
                err = server["error"]
                if err.startswith("http_"):
                    _emit({"ok": False,
                           "error": f"cloud rejected backup ({err})",
                           "detail": server.get("detail")})
                else:
                    _emit({"ok": False,
                           "error": f"could not reach cloud: {err}",
                           "detail": server.get("detail")})
                return

            # 4. MERGE the pulled firm/community delta back into the LOCAL
            #    brain (the OTHER half of the fanout — this device both pushes
            #    its facts AND receives the others'). The merged payload's
            #    FIRM/COMMUNITY rows are teammates' / other devices' facts; we
            #    hand them to brain.fanout_apply, which writes them via the
            #    store's CRDT upsert exactly like the SyncWorker's inbound
            #    path — NOT brain.write (that re-gates a direct community write
            #    through promote/redaction and would refuse it). USER rows are
            #    this account's own private state, never fanned in. Idempotent:
            #    fanout_apply skips any id whose local HLC is equal/newer.
            merged_back = 0
            try:
                merged = server.get("merged") or {}
                inbound = [f for f in (merged.get("fragments") or [])
                           if isinstance(f, dict)
                           and (f.get("scope") or "").strip().lower()
                           in ("firm", "community")]
                if inbound and client is not None:
                    res = client._call("brain.fanout_apply",
                                       {"fragments": inbound}, timeout=45.0)
                    if isinstance(res, dict):
                        merged_back = int(res.get("applied") or 0)
            except Exception:
                # Best-effort merge-in: a write-back failure must not fail the
                # push half. The next sync re-pulls and retries.
                merged_back = 0

            # 5. Real server-side result → success line for the UI.
            accepted = server.get("accepted")
            _emit({
                "ok": True,
                "synced": accepted if isinstance(accepted, int) else len(fragments),
                "merged_in": merged_back,
                "firm_keys": server.get("firm_keys") or [],
                "community_keys": server.get("community_keys") or [],
                "rejected": server.get("rejected") or [],
                "new_hlc": server.get("new_hlc"),
                "cloud_url": cloud_url,
            })

        try:
            self._bg_pool().submit(_runner)
        except Exception as ex:
            return _safe_json({"async": False, "request_id": request_id,
                               "ok": False,
                               "error": f"pool submit: {ex}"})
        return _safe_json({"async": True, "request_id": request_id})

    # ─── ArchHub Cloud sign-in / sign-out (real, reachable any time) ───────
    # The ONLY token-minting path used to be onboarding's first-run dialog
    # (cloud_auth.SignInWorker). After first run there was NO way to sign in
    # from the UI, and the Brain "Back up my brain" button dead-ended at a
    # Settings page with no sign-in handler. These slots make the SAME real
    # PKCE browser flow reachable any time, plus a real server-side logout.
    @pyqtSlot(result=str)
    def cloud_status(self) -> str:
        """Cheap, synchronous probe of cloud sign-in state — drives the
        Settings Account section + any signed-out CTA. Returns
        {signed_in: bool, cloud_url: str}. NO network I/O (token presence is
        read from secrets_store via cloud_client), so it's safe to call on
        every Account-tab open without tripping bridgeAsync's 1.5s ceiling.
        Richer account detail (email / plan / remaining) arrives via the
        cloud_signin_done signal after a sign-in, or the Account tab fetches
        cloud_client.me() on its own thread."""
        try:
            import cloud_client
            return _safe_json({
                "signed_in": bool(cloud_client.is_signed_in()),
                "cloud_url": cloud_client.base_url(),
            })
        except Exception as ex:
            return _safe_json({"signed_in": False,
                               "error": f"{type(ex).__name__}: {ex}"})

    @pyqtSlot(result=str)
    def cloud_sign_in(self) -> str:
        """Launch the REAL ArchHub Cloud sign-in — the exact PKCE browser
        flow onboarding uses (cloud_auth.SignInWorker), just reachable any
        time from Settings → Account or the Brain backup CTA.

        SignInWorker is a QObject that opens the user's default browser to
        the magic-link sign-in page and runs a one-shot loopback HTTP server
        on 127.0.0.1 to capture the redirect `code`, then exchanges it for a
        bearer token. It does ALL of that on its OWN internal daemon thread
        (worker._run spawns threading.Thread), so constructing + start()-ing
        it here does NOT block the Qt main thread — the slot returns instantly
        with {async, request_id}. We hold a reference (self._cloud_signin_worker)
        so it isn't garbage-collected mid-flight, and re-entrancy is guarded so
        a second click while a browser flow is open is a no-op.

        On completion the worker's succeeded/failed signals are bridged to
        cloud_signin_done({ok, signed_in, email, plan, request_id, error?}).

        SAFETY: the agent never signs in / creates an account / types
        credentials — opening the browser is the founder's one manual step.
        This slot only OPENS that browser and reports the outcome."""
        import uuid as _uuid
        request_id = _uuid.uuid4().hex[:12]

        def _emit(payload: dict) -> None:
            payload.setdefault("request_id", request_id)
            try:
                self.cloud_signin_done.emit(_safe_json(payload))
            except Exception:
                pass

        # Re-entrancy guard: a sign-in browser flow is already open.
        existing = getattr(self, "_cloud_signin_worker", None)
        if existing is not None:
            running = getattr(existing, "_thread", None)
            if running is not None and running.is_alive():
                return _safe_json({"async": True, "request_id": request_id,
                                   "already_running": True})

        try:
            from cloud_auth import SignInWorker
        except Exception as ex:
            _emit({"ok": False, "signed_in": False,
                   "error": f"sign-in module unavailable: {ex}"})
            return _safe_json({"async": False, "request_id": request_id,
                               "ok": False, "error": str(ex)})

        def _on_succeeded(payload: dict) -> None:
            # payload = {token, expires_at, plan, ..., me:{email,plan,remaining_messages}}
            me = (payload or {}).get("me") or {}
            _emit({
                "ok": True,
                "signed_in": True,
                "email": me.get("email") or (payload or {}).get("email") or "",
                "plan": me.get("plan") or (payload or {}).get("plan") or "",
                "remaining_messages": me.get("remaining_messages"),
            })
            # Warm the usage cache so the status meter paints the right
            # number immediately (mirrors onboarding's behaviour).
            try:
                from cloud_usage import refresh_async
                refresh_async()
            except Exception:
                pass
            # MAKE-IT-REAL: start the brain⇄cloud auto-sync scheduler now that
            # a token exists, so local + cloud no longer drift between
            # sign-ins. Idempotent (a second sign-in won't double-start).
            # Best-effort — a scheduler hiccup must not break the sign-in
            # report. The owner BIND itself already happened inside the
            # SignInWorker (_pair_brain → brain.set_owner) before this signal.
            try:
                self._start_brain_autosync()
            except Exception:
                pass

        def _on_failed(message: str) -> None:
            _emit({"ok": False, "signed_in": False,
                   "error": str(message) or "sign-in failed"})

        try:
            worker = SignInWorker(self)
            worker.succeeded.connect(_on_succeeded)
            worker.failed.connect(_on_failed)
            self._cloud_signin_worker = worker   # keep alive
            worker.start()                       # spawns its own thread; non-blocking
        except Exception as ex:
            _emit({"ok": False, "signed_in": False,
                   "error": f"couldn't start sign-in: {type(ex).__name__}: {ex}"})
            return _safe_json({"async": False, "request_id": request_id,
                               "ok": False, "error": str(ex)})

        return _safe_json({"async": True, "request_id": request_id,
                           "opened_browser": True})

    @pyqtSlot(result=str)
    def cloud_sign_in_google(self) -> str:
        """Launch "Sign in with Google" — the SAME real PKCE browser flow as
        cloud_sign_in(), via cloud_auth.GoogleSignInWorker instead of
        SignInWorker. The worker asks the backend for the Google auth URL
        (GET /v1/auth/google/start), opens the user's default browser to it,
        captures the loopback ?code=, exchanges it for a bearer token (the
        same cloud_client.exchange path), persists it to cloud.json, and pairs
        the brain — all on its OWN daemon thread, so this slot returns instantly
        with {async, request_id}.

        Emits the SAME cloud_signin_done payload shape as cloud_sign_in
        ({ok, signed_in, email, plan, request_id, error?}) so the Account tab's
        existing handler flips state with no extra wiring. Shares the
        self._cloud_signin_worker re-entrancy guard with the magic-link slot so
        a second click (either flow) while a browser flow is open is a no-op.

        SAFETY: identical to cloud_sign_in — the agent never signs in / creates
        an account / types credentials; opening the browser is the founder's
        one manual step. This slot only OPENS that browser + reports outcome."""
        import uuid as _uuid
        request_id = _uuid.uuid4().hex[:12]

        def _emit(payload: dict) -> None:
            payload.setdefault("request_id", request_id)
            try:
                self.cloud_signin_done.emit(_safe_json(payload))
            except Exception:
                pass

        # Re-entrancy guard: a sign-in browser flow (either kind) is open.
        existing = getattr(self, "_cloud_signin_worker", None)
        if existing is not None:
            running = getattr(existing, "_thread", None)
            if running is not None and running.is_alive():
                return _safe_json({"async": True, "request_id": request_id,
                                   "already_running": True})

        try:
            from cloud_auth import GoogleSignInWorker
        except Exception as ex:
            _emit({"ok": False, "signed_in": False,
                   "error": f"sign-in module unavailable: {ex}"})
            return _safe_json({"async": False, "request_id": request_id,
                               "ok": False, "error": str(ex)})

        def _on_succeeded(payload: dict) -> None:
            # payload = {token, expires_at, plan, ..., me:{email,plan,remaining_messages}}
            me = (payload or {}).get("me") or {}
            _emit({
                "ok": True,
                "signed_in": True,
                "email": me.get("email") or (payload or {}).get("email") or "",
                "plan": me.get("plan") or (payload or {}).get("plan") or "",
                "remaining_messages": me.get("remaining_messages"),
            })
            # Warm the usage cache so the status meter paints the right number.
            try:
                from cloud_usage import refresh_async
                refresh_async()
            except Exception:
                pass
            # Start the brain⇄cloud auto-sync scheduler now a token exists.
            # The owner BIND already happened inside GoogleSignInWorker
            # (_pair_brain → brain.set_owner) before this signal. Idempotent.
            try:
                self._start_brain_autosync()
            except Exception:
                pass

        def _on_failed(message: str) -> None:
            _emit({"ok": False, "signed_in": False,
                   "error": str(message) or "sign-in failed"})

        try:
            worker = GoogleSignInWorker(self)
            worker.succeeded.connect(_on_succeeded)
            worker.failed.connect(_on_failed)
            self._cloud_signin_worker = worker   # keep alive (shared guard)
            worker.start()                       # spawns its own thread; non-blocking
        except Exception as ex:
            _emit({"ok": False, "signed_in": False,
                   "error": f"couldn't start sign-in: {type(ex).__name__}: {ex}"})
            return _safe_json({"async": False, "request_id": request_id,
                               "ok": False, "error": str(ex)})

        return _safe_json({"async": True, "request_id": request_id,
                           "opened_browser": True})

    @pyqtSlot(result=str)
    def cloud_sign_out(self) -> str:
        """Sign out of ArchHub Cloud — revoke the token server-side then
        clear it locally.

        Calls cloud_client.logout() which POSTs /v1/auth/logout with the
        Bearer token (server contract: 200 {ok:true} → token deleted/revoked)
        and then ALWAYS clears the local credential, so the user is honestly
        signed out on this device even when offline (a stale encrypted token
        left after "Sign out" would be the dishonest outcome). The HTTP call
        runs on the background pool so the Qt main thread never blocks on the
        network; the result lands via cloud_signout_done({ok, signed_in:false,
        msg, request_id}). `ok` reflects the SERVER revoke; `signed_in` is
        always False after this completes."""
        import uuid as _uuid
        request_id = _uuid.uuid4().hex[:12]

        def _emit(payload: dict) -> None:
            payload.setdefault("request_id", request_id)
            payload.setdefault("signed_in", False)
            try:
                self.cloud_signout_done.emit(_safe_json(payload))
            except Exception:
                pass

        def _runner():
            try:
                import cloud_client
            except Exception as ex:
                # Module missing — best we can do is report; nothing to clear.
                # Still stop the scheduler + unbind so we don't keep syncing.
                self._stop_brain_autosync()
                self._unbind_brain_owner()
                _emit({"ok": False,
                       "msg": f"cloud client unavailable: {ex}"})
                return
            try:
                server_ok, msg = cloud_client.logout()
            except Exception as ex:
                # logout() is defensive, but never let an exception cross the
                # bridge. Force a local clear so the user is signed out.
                try: cloud_client.clear_token()
                except Exception: pass  # audit: deliberate-fail-soft — best-effort local token clear on the logout-error path; sign-out is forced regardless below
                # Stop auto-sync + unbind the local brain even on the error
                # path — the user asked to sign out.
                self._stop_brain_autosync()
                self._unbind_brain_owner()
                _emit({"ok": False,
                       "msg": f"signed out locally (logout error: {ex})"})
                return
            # Token is now cleared (logout() clears unconditionally). Stop the
            # auto-sync scheduler and UNBIND the local brain from the account:
            # brain.clear_owner() drops the persisted owner binding so the
            # default owner reverts to env/OS — the brain DATA stays, only the
            # binding clears. Best-effort: a down daemon must not fail sign-out.
            self._stop_brain_autosync()
            self._unbind_brain_owner()
            _emit({"ok": bool(server_ok), "msg": str(msg)})

        try:
            self._bg_pool().submit(_runner)
        except Exception as ex:
            return _safe_json({"async": False, "request_id": request_id,
                               "ok": False, "error": f"pool submit: {ex}"})
        return _safe_json({"async": True, "request_id": request_id})

    @pyqtSlot(result=str)
    def memory_stats(self) -> str:
        """Snapshot of the brain — fact/skill counts + community grouping.

        ONE-SYSTEM unify (2026-05-28, design:
        docs/audits/brain-unify-design-2026-05-28.md). The CANONICAL store is
        the daemon's `brain.db`, NOT `graph.sqlite`. Before unify, this slot
        read graph.sqlite directly, so the in-app brain view showed a
        DIFFERENT number than the daemon's `brain.health` — the two-brains
        bug. Now `total_nodes` is the daemon's canonical fact count, so the
        in-app brain view and the daemon report the SAME figure from the SAME
        store. graph.sqlite is consulted only for the community grouping (the
        topology staging table the extractors write) and as an HONEST fallback
        when the daemon is unreachable.

        Shape preserved for callers (BrainViewModal, MemoryExplorer):
          {status, total_nodes, total_edges, by_kind, communities_total,
           communities_top, source}
        `source` is 'brain.db' (canonical / daemon) or 'graph.sqlite'
        (fallback) so the UI can be honest about degraded mode.

        AgDR-0036 follow-up — THE WORST main-thread offender. The body
        (extracted to `_compute_memory_stats`) runs SQLite (7×
        count_nodes + count_edges + community_stats) AND a BLOCKING
        `brain.health` HTTP call to a daemon that is often DOWN — up to a
        4 s UI freeze on every open of the Brain view / memory strip.
        Now routed through `_cached_async`: returns the cached snapshot
        INSTANTLY on the Qt main thread, recomputes on the background
        pool, and emits `memory_changed` when fresh data lands so the
        Brain view / memory strip re-pull. The SQLite reads + the
        brain.health HTTP call run ONLY on the worker thread — never the
        UI thread — and the health call fast-fails (1.5 s) against a dead
        daemon, with the staging-graph fallback below."""
        return _safe_json(self._cached_async(
            "memory_stats_brain", self._compute_memory_stats,
            ttl=15.0,
            empty={"status": "ok", "source": "pending",
                   "total_nodes": 0, "total_edges": 0, "by_kind": {},
                   "communities_total": 0, "communities_top": []},
            signal_name="memory_changed"))

    def _compute_memory_stats(self) -> dict:
        """Heavy body for `memory_stats` — runs ONLY on the background
        pool (via `_cached_async`), never the Qt main thread. Does the
        SQLite reads + the (often-stalling) brain.health HTTP call."""
        # Community grouping + edge topology come from the extractor staging
        # graph (graph.sqlite). Counts come from the CANONICAL store.
        communities_total = 0
        communities_top: list = []
        graph_edges = 0
        graph_by_kind: dict[str, int] = {}
        graph_nodes_total = 0
        try:
            from memory import MemoryGraph, community_stats
            g = MemoryGraph.open()
            try:
                kinds = ("capability", "skill", "turn", "tool",
                         "decision", "project", "design")
                graph_by_kind = {k: g.count_nodes(kind=k) for k in kinds}
                graph_nodes_total = g.count_nodes()
                graph_edges = g.count_edges()
                stats = community_stats(g)
                communities_total = len(stats)
                communities_top = stats[:5]
            finally:
                g.close()
        except Exception:
            # Staging graph unavailable — degrade to canonical-only below.
            pass

        # Canonical counts from the daemon (brain.db). This is the ONE store
        # the daemon serves on :8473; making the in-app view read it is what
        # retires the manual graph→brain sync (tools/brain_unify.py).
        # We are on the background pool here, so a stall can't freeze the
        # UI — but we STILL fast-fail (1.5 s) so a dead daemon doesn't pin
        # a worker thread for the full 4 s; the staging-graph fallback
        # below carries the panel in degraded mode.
        try:
            health = self._brain_tool("brain.health", {}, timeout=1.5)
        except Exception as ex:
            health = {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

        if isinstance(health, dict) and health.get("ok"):
            facts_n = health.get("facts")
            skills_n = health.get("skills")
            # by_kind keeps the graph's kind breakdown for the panel, but the
            # canonical skill count overrides the staging value so the badge
            # matches the daemon.
            by_kind = dict(graph_by_kind)
            if isinstance(skills_n, int):
                by_kind["skill"] = skills_n
            return {
                "status": "ok",
                "source": "brain.db",
                "total_nodes": facts_n if isinstance(facts_n, int) else graph_nodes_total,
                "total_edges": graph_edges,
                "by_kind": by_kind,
                "skills_total": skills_n,
                "communities_total": communities_total,
                "communities_top": communities_top,
                "canonical_db": health.get("db_path"),
            }

        # Daemon down — HONEST fallback to the staging graph counts so the
        # panel still shows something real, clearly labelled as non-canonical.
        if graph_nodes_total or graph_by_kind:
            return {
                "status": "ok",
                "source": "graph.sqlite",
                "total_nodes": graph_nodes_total,
                "total_edges": graph_edges,
                "by_kind": graph_by_kind,
                "communities_total": communities_total,
                "communities_top": communities_top,
                "degraded": "brain daemon unreachable — showing staging graph",
            }
        return {
            "status": "error",
            "error": "brain daemon unreachable and no staging graph available",
        }

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
        the panel can show a single-line banner instead of dying.

        AgDR-0036 follow-up — this fires debounced on EVERY canvas edit.
        The validation is in-memory O(nodes+edges); cheap on small graphs
        but it ran SYNCHRONOUSLY in the slot body, holding the Qt main
        thread for an unbounded amount as the graph grows. Now routed
        through `_cached_async` keyed by the graph snapshot: returns the
        cached issue list instantly, recomputes on the background pool,
        emits `graph_validated` when fresh data lands so the canvas
        re-pulls. The validation never blocks the main thread / canvas.
        Parse + arg errors are returned inline (they're trivial and the
        caller needs the banner immediately)."""
        try:
            import json as _json
            graph = _json.loads(graph_json or "{}")
            if not isinstance(graph, dict):
                return _safe_json({"status": "error",
                                    "error": "graph must be an object"})
            if self.tools is None:
                return _safe_json({"status": "error",
                                    "error": "tool engine not initialised"})
        except Exception as ex:
            return _safe_json({"status": "error",
                                "error": f"{type(ex).__name__}: {ex}"})

        def _work():
            try:
                return self.tools.invoke("graph_validate", {"graph": graph})
            except Exception as ex:
                return {"status": "error",
                        "error": f"{type(ex).__name__}: {ex}"}

        key = "graph_validate:" + self._hash_payload(graph_json)
        return _safe_json(self._cached_async(
            key, _work, ttl=3.0,
            empty={"status": "ok", "issues": [], "errors": 0,
                   "warnings": 0, "valid": True},
            signal_name="graph_validated"))

    # ─── AgDR-0041 P4 — delete-with-auto-bridge ────────────────────
    @pyqtSlot(str, str, str, result=str)
    def graph_on_node_delete(self, node_id: str, graph_json: str,
                             request_id: str = "") -> str:
        """Preview the impact of deleting a node BEFORE removing it.

        Returns one of (delivered via the `node_op_done` signal):
          - {action:"silent_delete"}  — no incident wires; safe to drop.
          - {action:"auto_bridge", wires:[…]} — upstream src type matches
            downstream dst type; UI applies those wires after delete.
          - {action:"broken_wire", broken:[…], compatible:[…]} — type
            mismatch; UI surfaces BrokenWireDialog with recovery options
            (insert adapter / restore / swap downstream).
        Always carries `status: 'ok' | 'error'`.

        AgDR-0036 follow-up — this is INTERACTIVE: the delete handler
        needs the REAL answer (a node with incident wires must never be
        reported silent-deletable). A cached empty-first-call would
        corrupt that, so rather than `_cached_async` we run the (trivial,
        in-memory) preview on the `_bg_pool` and emit `node_op_done` with
        the result + `request_id`. The slot returns `{async, request_id}`
        instantly on the Qt main thread; the JSX `bridgeAsyncSignal`
        helper awaits the matching signal. Parse / arg errors come back
        inline (and are ALSO emitted) so the caller resolves either way."""
        import time as _time
        req = (request_id or "").strip() or f"del-{int(_time.time()*1000)}-{id(self)}"

        def _fail(msg: str) -> str:
            payload = {"status": "error", "error": msg, "request_id": req}
            try: self.node_op_done.emit(_safe_json(payload))
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
            return _safe_json({"async": True, "request_id": req,
                               "status": "error", "error": msg})

        try:
            import json as _json
            graph = _json.loads(graph_json or "{}")
        except Exception as ex:
            return _fail(f"{type(ex).__name__}: {ex}")
        if not isinstance(graph, dict):
            return _fail("graph must be an object")
        if self.tools is None:
            return _fail("tool engine not initialised")

        nid = (node_id or "").strip()

        def _runner():
            try:
                res = self.tools.invoke("graph_on_node_delete",
                                        {"node_id": nid, "graph": graph})
                if not isinstance(res, dict):
                    res = {"status": "error", "error": "bad handler result"}
            except Exception as ex:
                res = {"status": "error",
                       "error": f"{type(ex).__name__}: {ex}"}
            res["request_id"] = req
            try: self.node_op_done.emit(_safe_json(res))
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend

        try:
            self._bg_pool().submit(_runner)
        except Exception as ex:
            return _fail(f"pool submit: {ex}")
        return _safe_json({"async": True, "request_id": req})

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
    @pyqtSlot(str, int, str, result=str)
    def library_suggest_swaps(self, node_type: str, limit: int,
                              request_id: str = "") -> str:
        """Find registered types whose I/O signature matches the target.
        Powers the right-click 'swap with…' context menu. Returns
        ranked alternatives + their port shapes; the UI presents these,
        click swaps the node in place + runner re-cooks downstream.

        AgDR-0036 follow-up — INTERACTIVE (right-click → list). Runs the
        `tools.invoke` on the `_bg_pool` and delivers the result via the
        `node_op_done` signal with `request_id`; the slot returns
        `{async, request_id}` instantly so the Qt main thread is never
        held. The JSX `bridgeAsyncSignal` helper awaits the match. The
        trailing `request_id` arg is optional so a legacy 2-arg call
        still works (it gets an auto-generated id back)."""
        import time as _time
        req = (request_id or "").strip() or f"swap-{int(_time.time()*1000)}-{id(self)}"

        if self.tools is None:
            payload = {"status": "error",
                       "error": "tool engine not initialised",
                       "request_id": req}
            try: self.node_op_done.emit(_safe_json(payload))
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
            return _safe_json({"async": True, "request_id": req,
                               "status": "error",
                               "error": "tool engine not initialised"})

        # arg1 (`node_type`) carries EITHER a plain registered type name (the
        # right-click "swap with…" + inspector paths) OR a JSON filter object
        # {in_types,out_types,limit} (the broken-wire "Insert adapter" path,
        # which needs to find an adapter by PORT types, not by an existing
        # node type). The underlying `library_suggest_swaps` tool handler
        # already supports in_types/out_types (tool_engine.py) — this slot just
        # forwards them. Detecting a JSON object here keeps the slot signature
        # (and the JSX call shape: a string in arg1) unchanged + back-compat: a
        # plain type name is not a JSON object, so it falls through to `type`
        # exactly as before. Before this, the adapter path crammed the blob
        # into `type` and the search filtered on a bogus type → never matched.
        _nt = (node_type or "").strip()
        args: dict = {"limit": int(limit) if limit else 10}
        _filter = None
        if _nt[:1] == "{":
            try:
                import json as _json
                _parsed = _json.loads(_nt)
                if isinstance(_parsed, dict):
                    _filter = _parsed
            except Exception:
                _filter = None
        if _filter is not None:
            if _filter.get("in_types"):
                args["in_types"] = _filter["in_types"]
            if _filter.get("out_types"):
                args["out_types"] = _filter["out_types"]
            if _filter.get("type"):
                args["type"] = str(_filter["type"]).strip()
            # an explicit limit inside the blob overrides the positional one
            if _filter.get("limit"):
                args["limit"] = int(_filter["limit"])
        else:
            args["type"] = _nt

        def _runner():
            try:
                res = self.tools.invoke("library_suggest_swaps", args)
                if not isinstance(res, dict):
                    res = {"status": "error", "error": "bad handler result"}
            except Exception as ex:
                res = {"status": "error",
                       "error": f"{type(ex).__name__}: {ex}"}
            res["request_id"] = req
            try: self.node_op_done.emit(_safe_json(res))
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend

        try:
            self._bg_pool().submit(_runner)
        except Exception as ex:
            return _safe_json({"async": True, "request_id": req,
                               "status": "error",
                               "error": f"pool submit: {ex}"})
        return _safe_json({"async": True, "request_id": req})

    # ─── Wire validation (canvas drop-validation) ──────────────────
    @pyqtSlot(str, str, bool, bool, result=bool)
    def can_wire(self, out_type: str, in_type: str,
                  out_exec: bool, in_exec: bool) -> bool:
        """Type-check a prospective wire from canvas mouseup. Returns
        False when the rubber-band should snap back instead of
        committing the wire.

        AgDR-0036 — DELIBERATELY SYNCHRONOUS. The canvas needs an
        immediate allow/block answer on wire-drop; an async round-trip
        would let an invalid wire flash in before snapping back. Verified
        cheap + bounded: a pure in-memory enum compare via
        `workflows.typesystem.can_wire` — no SQLite, no network, no disk.
        Safe on the Qt main thread."""
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
        Canvas calls this on socket-drop before committing.

        AgDR-0036 — DELIBERATELY SYNCHRONOUS, same reason as `can_wire`:
        the canvas needs an immediate true/false to accept/reject the
        rubber-band. Verified cheap + bounded on the HOT path: the JSX
        ALWAYS passes the live graph as `graph_json`, so we take the
        in-memory branch — a pure DFS over edges (O(nodes+edges)) in
        `WorkflowRunner.would_create_cycle`, NO SQLite / network. The
        disk-load fallback only runs if `graph_json` is empty (never on
        the wire-drop path), so the main thread is never blocked on I/O
        here."""
        try:
            import json as _json
            graph = _json.loads(graph_json) if graph_json else None
            if graph is None:
                # Load from disk fallback (NOT the hot path — JSX always
                # passes graph_json on wire-drop; this is for headless /
                # programmatic callers that pass only a session id).
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
                    except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
                    return _safe_json({"request_id": req_id,
                                         "error": "session not found"})
                session, _name, _m = load_session_with_messages(p)
                graph = session.graph or {}
        except Exception as ex:
            payload = _safe_json({"error": str(ex)})
            try: self.workflow_done.emit("workflow", req_id, payload)
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
            return _safe_json({"request_id": req_id, "error": str(ex)})

        def _worker():
            try: self.workflow_started.emit("workflow", req_id)
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
                    except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
                runner.on_wire_state(_emit_wire_state)
                # AgDR-0036 Phase 1 — serialise: a 2nd Run queues here.
                with self._cook_lock():
                    result = runner.run_all()
                payload = _safe_json(result)
            except Exception as ex:
                payload = _safe_json({"error": str(ex)})
            try: self.workflow_done.emit("workflow", req_id, payload)
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend

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
                    except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
                    except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
                    return _safe_json({"request_id": req_id,
                                         "error": "session not found"})
                session, _name, _m = load_session_with_messages(p)
                graph = session.graph or {}
        except Exception as ex:
            payload = _safe_json({"error": str(ex)})
            try: self.workflow_done.emit("node", req_id, payload)
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
            return _safe_json({"request_id": req_id, "error": str(ex)})

        def _worker():
            try: self.workflow_started.emit("node", req_id)
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
                    except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
                runner.on_wire_state(_emit_wire_state)
                # AgDR-0036 Phase 1 — serialise with run_workflow so two
                # cooks never hit the same host brokers concurrently.
                with self._cook_lock():
                    result = runner.pull(node_id)
                # `runner.pull` returns the cooked node's FLAT output dict (its
                # ports: {status, value, …}) — NOT a {results:{nodeId:…}} map
                # like run_all/recook_from. Stamp the cooked node_id at the top
                # level so the JS `onWorkflowDone` handler can route a
                # kind:"node" result back onto the right canvas node. Without
                # this the single-node cook result was anonymous and the
                # handler (which keyed off `results`) dropped it on the floor —
                # a Rerun/▶ on one node produced a value nothing displayed.
                res_dict = result if isinstance(result, dict) else {"value": result}
                if isinstance(res_dict, dict) and "node_id" not in res_dict:
                    res_dict = {**res_dict, "node_id": node_id}
                payload = _safe_json(res_dict)
            except Exception as ex:
                payload = _safe_json({"error": str(ex), "node_id": node_id})
            try: self.workflow_done.emit("node", req_id, payload)
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend

        threading.Thread(target=_worker, daemon=True).start()
        return _safe_json({"request_id": req_id, "status": "started"})

    @pyqtSlot(str, str, str, result=str)
    def recook_node(self, session_id: str, node_id: str,
                     graph_json: str = "") -> str:
        """Re-cook a node + its downstream chain after a param edit.

        cook.recook_trigger / court-verdict 2026-06-01: dragging a slider
        (NodeRail.onParamChange / ConnectorRail.setParam in studio-lm.jsx)
        must re-run the edited node AND propagate downstream — NOT just
        repaint. This is the cook path for that. It mirrors `run_node`
        EXACTLY — fresh stateless WorkflowRunner, wire-state streaming,
        serialised under `_cook_lock` so two cooks never hit the same
        host brokers concurrently, run on a worker thread so the Qt main
        thread never blocks — but calls `runner.recook_from(node_id)`
        instead of `pull`: that marks the node dirty (cascading downstream
        + flipping incident edges to "stale") then pulls the sinks
        reachable downstream, re-cooking the edited node and the whole
        chain it feeds while unrelated branches stay cached.

        Returns the request_id synchronously (non-blocking); the result
        lands via `workflow_done("recook", request_id, result_json)`.
        graph_json is the in-memory canvas shape (no disk roundtrip);
        when empty we read session.graph from disk — same as run_node."""
        import json as _json
        import time as _time
        req_id = f"rc-{int(_time.time()*1000)}-{id(self)}"
        graph: dict | None = None
        try:
            from pathlib import Path
            sid = session_id or "workspace"
            if graph_json:
                try:
                    graph = _json.loads(graph_json)
                except Exception as ex:
                    payload = _safe_json({"error": f"bad graph_json: {ex}"})
                    try: self.workflow_done.emit("recook", req_id, payload)
                    except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
                    try: self.workflow_done.emit("recook", req_id, payload)
                    except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
                    return _safe_json({"request_id": req_id,
                                         "error": "session not found"})
                session, _name, _m = load_session_with_messages(p)
                graph = session.graph or {}
        except Exception as ex:
            payload = _safe_json({"error": str(ex)})
            try: self.workflow_done.emit("recook", req_id, payload)
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
            return _safe_json({"request_id": req_id, "error": str(ex)})

        def _worker():
            try: self.workflow_started.emit("recook", req_id)
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
            try:
                from workflows.runner import WorkflowRunner
                from workflows.node_grammar import normalize_canvas_graph
                runner = WorkflowRunner(normalize_canvas_graph(graph),
                                         router=self.router,
                                         tool_engine=self.tools,
                                         manager=self.manager)
                def _emit_wire_state(eid, state, preview):
                    try: self.wire_state_changed.emit(eid, state, preview)
                    except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
                runner.on_wire_state(_emit_wire_state)
                # AgDR-0036 Phase 1 — serialise with run_workflow / run_node
                # so two cooks never hit the same host brokers concurrently.
                with self._cook_lock():
                    result = runner.recook_from(node_id)
                payload = _safe_json(result if isinstance(result, dict)
                                       else {"value": result})
            except Exception as ex:
                payload = _safe_json({"error": str(ex)})
            try: self.workflow_done.emit("recook", req_id, payload)
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend

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
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
            return _safe_json({"ok": True, "path": str(out_path),
                                "slug": slug,
                                "nodes": len(payload.get("nodes") or []),
                                "wires": len(payload.get("wires") or [])})
        except Exception as ex:
            return _safe_json({"error": str(ex)})

    @pyqtSlot(str, str, str, result=str)
    def save_node_output(self, node_id: str, title: str,
                          content_json: str) -> str:
        """Write an output node's REAL cooked value to a file on disk.

        Audit 2026-05-28: the OutputBody `save` button was decorative (no
        handler). This is the real slot behind it. The JSX side passes the
        node's actual last output (its `cooked` value / op_result / params)
        as `content_json`; we write it to
        `<cwd>/exports/node-outputs/<slug>-<ts>.<ext>` and return the
        absolute path so the UI can show the user exactly where it landed.

        Plain strings are written verbatim (e.g. a code/text output);
        structured values are written as pretty JSON. The extension is
        chosen from the payload shape so the saved file is directly usable.
        """
        try:
            import json as _json
            import os as _os
            import re
            import time as _time
            # The JS side wraps the real value as {"value": <output>}.
            try:
                wrapper = _json.loads(content_json) if content_json else {}
            except Exception as ex:
                return _safe_json({"error": f"bad content_json: {ex}"})
            if not isinstance(wrapper, dict):
                wrapper = {"value": wrapper}
            value = wrapper.get("value", wrapper)
            if value is None or value == "":
                return _safe_json({"error": "no output to save — run the "
                                            "node first"})

            out_dir = _os.path.join(_os.getcwd(), "exports", "node-outputs")
            try:
                _os.makedirs(out_dir, exist_ok=True)
            except Exception:
                pass

            slug_src = (title or node_id or "node-output")
            slug = re.sub(r"[^a-z0-9]+", "-",
                          str(slug_src).lower()).strip("-") or "node-output"
            stamp = _time.strftime("%Y%m%d-%H%M%S")

            # A bare string is a text/code output — save it verbatim with a
            # .txt extension. Anything structured serialises to pretty JSON.
            if isinstance(value, str):
                body = value
                ext = "txt"
            else:
                body = _json.dumps(value, indent=2, ensure_ascii=False,
                                    default=str)
                ext = "json"

            from pathlib import Path
            out_path = Path(out_dir) / f"{slug}-{stamp}.{ext}"
            out_path.write_text(body, encoding="utf-8")
            return _safe_json({"ok": True, "path": str(out_path),
                                "bytes": len(body.encode("utf-8")),
                                "ext": ext})
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
    @pyqtSlot(str, str, str, str, result=str)
    def agent_step(self, user_msg: str, graph_json: str,
                    focused_node_id: str = "", mode: str = "plan") -> str:
        """LLM-as-orchestrator. Founder bug 2026-05-15: the app froze
        ("Not Responding") on every composer submit — root cause was
        this slot running `run_agent_step` SYNCHRONOUSLY on the Qt main
        thread. run_agent_step does ~10s of host probing + a full LLM
        round-trip; both blocked the UI. Fix: run it on a background
        thread and emit `agent_step_done(result_json)` when finished.
        The slot returns immediately so the main thread never stalls.

        `mode` (IA fix, ia-critique-ai-stemcells-2026-06-03 §4 — the
        backend half the "all writes gated" chip never had) is the
        USER-AGENCY gate: "plan" (default, gates host writes pending
        approval), "auto" (auto reads, gates writes), "yolo" (runs
        free). NEW trailing param, defaulted "plan" → the historical
        3-arg call is unchanged AND fail-safe gated. run_agent_step
        enforces it; the result carries `gated` (count blocked) +
        `mode`."""
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
                    mode=mode or "plan",
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
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
                except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
                except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
                except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
                except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
            from datetime import datetime, timezone
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
            payload["saved_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            (SESSIONS_DIR / f"{new_slug}.archhub-session.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            try: self.sessions_changed.emit()
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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

    # Theme vocabulary — the founder-signed branded ids are the store's
    # native tongue. Legacy ids (the original dark/light/system slots) are
    # still ACCEPTED on write and FOLDED on read, so any value written by
    # an older build or an older caller still resolves to a branded theme.
    #   forge     ← dark, system, auto   (the signed default)
    #   blueprint ← (branded only)
    #   vellum    ← light
    _THEME_BRANDED = ("forge", "blueprint", "vellum")
    _THEME_LEGACY_FOLD = {
        "dark": "forge", "system": "forge", "auto": "forge",
        "light": "vellum",
    }
    _THEME_DEFAULT = "forge"

    @classmethod
    def _canon_theme(cls, value) -> str:
        """Fold any stored/incoming theme id to a branded id. Branded ids
        pass through; legacy ids map via _THEME_LEGACY_FOLD; anything
        unknown (or blank) falls back to the signed default — never
        raises."""
        n = str(value or "").strip().lower()
        if n in cls._THEME_BRANDED:
            return n
        return cls._THEME_LEGACY_FOLD.get(n, cls._THEME_DEFAULT)

    @pyqtSlot(str, result=str)
    def set_theme(self, name: str) -> str:
        """Persist theme choice to %LOCALAPPDATA%/ArchHub/theme.json.

        Accepts the branded ids 'forge' / 'blueprint' / 'vellum'
        (case-insensitive) and persists them branded. Still accepts the
        legacy 'dark' / 'light' / 'system' (and 'auto') for back-compat,
        mapping each to its branded slot before persisting. An unknown id
        is rejected (the store stays unchanged) so a typo can't silently
        repaint the app."""
        try:
            import os as _os
            from pathlib import Path
            raw = (name or "").strip().lower()
            if (raw not in self._THEME_BRANDED
                    and raw not in self._THEME_LEGACY_FOLD):
                return _safe_json({"error":
                    "theme must be one of: forge, blueprint, vellum"})
            n = self._canon_theme(raw)
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
        """Read theme.json, returning a branded id ('forge' default when
        missing/invalid). Any legacy value still on disk (dark/light/
        system/auto) is folded to its branded slot on read, so an old
        store upgrades transparently without a migration step."""
        try:
            import os as _os
            from pathlib import Path
            p = Path(_os.environ.get("LOCALAPPDATA",
                                       str(Path.home()))) / "ArchHub" / "theme.json"
            if not p.exists():
                return _safe_json({"theme": self._THEME_DEFAULT})
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return _safe_json({"theme": self._THEME_DEFAULT})
            theme = self._canon_theme((data or {}).get("theme"))
            return _safe_json({"theme": theme})
        except Exception as ex:
            return _safe_json({"error": str(ex), "theme": self._THEME_DEFAULT})

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
    @pyqtSlot(str, result=str)
    def export_all(self, request_id: str = "") -> str:
        """Zip sessions/, skills/, custom_nodes/, profile.json, theme.json into
        ~/Downloads/archhub-export-<ts>.zip — OFF the Qt main thread.

        AgDR-0036 follow-up (2026-06-02): the recursive glob+zip used to run
        inline in this slot, freezing the UI for the user's whole "Export
        everything" click (the last allowlisted GUI-thread blocker). Now the
        heavy work (`_do_export_all`, a module-level helper invisible to the
        blocking-in-pyqtslot audit) runs on `_bg_pool()` and the result is
        delivered via `settings_op_done(result_json)` with `request_id` stamped
        in. The slot returns {async, request_id} INSTANTLY so the click never
        stalls — the EXACT idiom proven by brain_export_dataset / node_op_done.

        Dual-path: when called WITH a request_id (the live UI, via the JSX
        `bridgeAsyncSignal` helper or the native SettingsTab worker) it goes
        off-thread. When called WITHOUT one (a direct in-process call, e.g. a
        unit test) it runs synchronously and returns the full {ok,path,size}
        envelope so existing callers keep their contract."""
        rid = (request_id or "").strip()
        if not rid:
            # Direct/synchronous path — no signal to correlate. Heavy work runs
            # on the caller's own thread (a test / script, never the Qt UI).
            return _safe_json(_do_export_all())

        def _runner():
            try:
                payload = _do_export_all()
            except Exception as ex:  # _do_* is fail-safe, but belt-and-braces
                payload = {"error": f"{type(ex).__name__}: {ex}"}
            payload["request_id"] = rid
            try:
                self.settings_op_done.emit(_safe_json(payload))
            except Exception:
                pass

        try:
            self._bg_pool().submit(_runner)
        except Exception as ex:
            return _safe_json({"async": False, "request_id": rid,
                               "error": f"pool submit: {ex}"})
        return _safe_json({"async": True, "request_id": rid})

    @pyqtSlot(result=str)
    @pyqtSlot(str, result=str)
    def clear_model_cache(self, request_id: str = "") -> str:
        """Best-effort delete of %LOCALAPPDATA%/ArchHub/model_cache/* — OFF the
        Qt main thread. Returns total bytes freed.

        AgDR-0036 follow-up (2026-06-02): the recursive glob+delete used to run
        inline in this slot, freezing the UI for the user's whole "Clear model
        cache" click. Now `_do_clear_model_cache` (module-level, audit-invisible)
        runs on `_bg_pool()` and the result lands via `settings_op_done(
        result_json)` with `request_id`. Same dual-path contract as
        `export_all`: with a request_id → instant {async} + signal; without one
        → synchronous {ok,freed_bytes} for direct/unit-test callers."""
        rid = (request_id or "").strip()
        if not rid:
            return _safe_json(_do_clear_model_cache())

        def _runner():
            try:
                payload = _do_clear_model_cache()
            except Exception as ex:
                payload = {"error": f"{type(ex).__name__}: {ex}"}
            payload["request_id"] = rid
            try:
                self.settings_op_done.emit(_safe_json(payload))
            except Exception:
                pass

        try:
            self._bg_pool().submit(_runner)
        except Exception as ex:
            return _safe_json({"async": False, "request_id": rid,
                               "error": f"pool submit: {ex}"})
        return _safe_json({"async": True, "request_id": rid})

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
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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
            except Exception: pass  # audit: deliberate-fail-soft — fire-and-forget UI signal; no receiver / teardown must not crash the backend
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

    @pyqtSlot(str, result=str)
    def open_file(self, path: str) -> str:
        """Open a single ArchHub data file in its default OS application.

        Backs the JSX "Open full table" button (ai.plan card). Locked down so
        the bridge can never be used to open/execute arbitrary system files:
        the target must (1) be an existing file, (2) live inside the ArchHub
        data tree (LOCALAPPDATA/ArchHub or the sessions dir), and (3) carry a
        safe, inert extension. Mirrors open_folder's structure + return shape.
        """
        try:
            import os as _os
            from pathlib import Path
            p = (path or "").strip()
            if not p:
                return _safe_json({"error": "no path given"})
            target = Path(p).expanduser().resolve()
            if not target.is_file():
                return _safe_json({"error": f"not a file: {target}"})
            # SECURITY — only files inside the ArchHub data tree may be opened.
            appdata = (Path(_os.environ.get("LOCALAPPDATA",
                                            str(Path.home()))) / "ArchHub").resolve()
            roots = [appdata]
            try:
                from session_io import SESSIONS_DIR
                roots.append(Path(SESSIONS_DIR).resolve())
            except Exception:
                pass
            def _inside(root) -> bool:
                try:
                    return target.is_relative_to(root)
                except Exception:
                    return False
            if not any(_inside(r) for r in roots):
                return _safe_json({"error":
                    "path outside the ArchHub data tree is not allowed"})
            # SECURITY — extension allowlist denies opening/executing arbitrary
            # system files (.exe/.bat/.dll/...). Inert document types only.
            SAFE = {".json", ".txt", ".md", ".csv", ".log",
                    ".yaml", ".yml", ".tsv", ".html", ".pdf"}
            if target.suffix.lower() not in SAFE:
                return _safe_json({"error":
                    f"refusing to open {target.suffix} via bridge"})
            try:
                startfile = getattr(_os, "startfile", None)
                if callable(startfile):
                    startfile(str(target))
            except Exception as ex:
                return _safe_json({"error": f"startfile failed: {ex}",
                                    "path": str(target)})
            return _safe_json({"ok": True, "path": str(target)})
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

    @pyqtSlot(result=str)
    def get_runtime_info(self) -> str:
        """Return REAL runtime facts for the footer ServerStrip.

        Audit 2026-05-28: the strip hardcoded `server :7300` (a port that
        corresponds to nothing). ArchHub is a desktop app — its only real
        listening surfaces are the optional QtWebEngine remote-debug port
        and the local brain daemon. Report the real ones so the footer
        tells the truth:
          - `debug_port`: the actual remote-debugging port if enabled
            (env QTWEBENGINE_REMOTE_DEBUGGING), else null.
          - `brain_port` / `brain_ok`: the brain daemon port + a cheap
            reachability check (the daemon is the app's real backend).
          - `providers`: configured / blocked LLM provider counts.
        """
        import os as _os
        info: dict = {}
        # Real remote-debug port (only present when launched with the env).
        dbg = (_os.environ.get("QTWEBENGINE_REMOTE_DEBUGGING") or "").strip()
        info["debug_port"] = int(dbg) if dbg.isdigit() else None
        # Brain daemon — the app's real local backend (AgDR-0044, :8473).
        brain_port = 8473
        info["brain_port"] = brain_port
        brain_ok = False
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.25)
            brain_ok = (s.connect_ex(("127.0.0.1", brain_port)) == 0)
            s.close()
        except Exception:
            brain_ok = False
        info["brain_ok"] = brain_ok
        # Provider counts (real — same source as get_provider_stats).
        try:
            if self.router is not None:
                info["providers_configured"] = len(list(self.router.configured_providers() or []))
                info["providers_blocked"] = len(list(self.router.blocked_providers() or {}))
            else:
                info["providers_configured"] = 0
                info["providers_blocked"] = 0
        except Exception:
            info["providers_configured"] = 0
            info["providers_blocked"] = 0
        return _safe_json(info)

    @pyqtSlot(result=str)
    def get_token_usage(self) -> str:
        """REAL provider-reported token usage for this session, accumulated
        by the router from each completion's usage block (Anthropic
        message.usage, OpenAI/OpenRouter chat.completion usage, Ollama
        prompt_eval_count/eval_count).

        Replaces the footer ServerStrip's old client-side chars/4 ESTIMATE.
        Shape: {prompt_tokens, completion_tokens, tokens, cost, cost_known,
        model, completions}. tokens stays 0 until a real completion lands —
        an honest empty state, not a fabricated baseline. `cost` is only
        meaningful when cost_known is True (a metered model with a known
        price contributed); local/subscription models report tokens with
        cost_known False, so the UI shows tokens only. Cheap read — no
        off-thread needed."""
        empty = {
            "prompt_tokens": 0, "completion_tokens": 0, "tokens": 0,
            "cost": 0.0, "cost_known": False, "model": "", "completions": 0,
        }
        try:
            if self.router is not None and hasattr(self.router, "get_token_usage"):
                return _safe_json(self.router.get_token_usage())
        except Exception:
            pass
        return _safe_json(empty)
