"""GraphTriggerScheduler — fires v1.4 in-graph trigger nodes.

The legacy `TriggerScheduler` (this directory's `scheduler.py`) operates
on stored *Workflow* file objects. v1.4 introduced in-graph TRIGGER
nodes — `on_file_save`, `on_email_arrive`, `on_schedule`, `on_revit_event`,
`on_warning` — declared inside a session's graph blob. This scheduler
walks every session's graph, finds trigger nodes, and fires them on
their declared cadence.

When a trigger fires, the scheduler calls back with
    on_fire(session_id, node_id, payload)
The caller (bridge.py) then dispatches a `trigger_fired` signal so the
JSX side can cook the downstream subgraph via `run_node`.

Phase 1 implementations:
    on_schedule    — interval / cron-like ("every 5m", "every 1h", etc.)
    on_file_save   — mtime polling on a watched path
    on_warning     — poll host-detector warnings, fire above threshold
    on_email_arrive — Outlook COM poll for unread (best-effort)
    on_revit_event  — broker poll for last_event timestamp diff

All probes are best-effort + wrapped in try/except so a single bad
trigger never kills the loop.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Thread
from typing import Callable, Optional


@dataclass
class GraphTriggerEvent:
    session_id: str
    node_id: str
    trigger_kind: str
    fired_at: float = field(default_factory=time.time)
    payload: dict = field(default_factory=dict)


class GraphTriggerScheduler:
    """Watches every session's TRIGGER-cat nodes, fires them on schedule.

    Args:
        sessions_dir: where session blobs live.
        on_fire: callback (session_id, node_id, payload) when a trigger fires.
        tick_seconds: poll interval (default 10s).
    """

    def __init__(self, sessions_dir: Path,
                 on_fire: Callable[[str, str, dict], None],
                 tick_seconds: float = 10.0) -> None:
        self.sessions_dir = Path(sessions_dir)
        self.on_fire = on_fire
        self.tick_seconds = max(1.0, float(tick_seconds))
        self._stop = Event()
        self._thread: Optional[Thread] = None
        # State keyed by f"{sid}::{node_id}":
        self._last_fired:   dict[str, float] = {}
        self._file_mtime:   dict[str, float] = {}
        self._email_seen:   dict[str, set[str]] = {}
        self._warn_seen:    dict[str, int]      = {}
        self._revit_seen:   dict[str, str]      = {}

    # ── lifecycle ───────────────────────────────────────────────
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._loop,
                                name="ArchHubGraphTriggers", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    # ── main loop ───────────────────────────────────────────────
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                # Loop must never crash; eat + continue.
                pass
            self._stop.wait(self.tick_seconds)

    def _tick(self) -> None:
        now = time.time()
        if not self.sessions_dir.exists():
            return
        for f in self.sessions_dir.glob("*.archhub-session.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            sid = data.get("id") or f.stem.replace(".archhub-session", "")
            graph = data.get("graph") or {}
            for node in (graph.get("nodes") or []):
                if not isinstance(node, dict):
                    continue
                if node.get("cat") != "trigger":
                    continue
                if node.get("frozen"):
                    continue
                kind = (node.get("id") or "").split("_", 1)[0]
                if not kind:
                    continue
                # Allow short id hash on the end (e.g. "g_save_1a2b") —
                # match by prefix on the canonical trigger ids.
                full_id = node.get("id") or ""
                trig_kind = self._classify(full_id)
                if not trig_kind:
                    continue
                key = f"{sid}::{full_id}"
                try:
                    fired, payload = self._eval(trig_kind, node, key, now)
                except Exception as ex:
                    fired, payload = False, {"error": str(ex)}
                if fired:
                    self._last_fired[key] = now
                    try:
                        self.on_fire(sid, full_id,
                                      {"kind": trig_kind, **(payload or {})})
                    except Exception:
                        pass

    # ── classify ────────────────────────────────────────────────
    @staticmethod
    def _classify(node_id: str) -> str:
        nid = (node_id or "").lower()
        if nid.startswith("g_save"):    return "on_file_save"
        if nid.startswith("g_email"):   return "on_email_arrive"
        if nid.startswith("g_sched"):   return "on_schedule"
        if nid.startswith("g_revit"):   return "on_revit_event"
        if nid.startswith("g_warning"): return "on_warning"
        return ""

    # ── per-trigger evaluation ──────────────────────────────────
    def _eval(self, kind: str, node: dict, key: str,
               now: float) -> tuple[bool, dict]:
        params = self._params(node)
        if kind == "on_schedule":
            return self._eval_schedule(params, key, now)
        if kind == "on_file_save":
            return self._eval_file_save(params, key)
        if kind == "on_warning":
            return self._eval_warning(params, key)
        if kind == "on_email_arrive":
            return self._eval_email(params, key)
        if kind == "on_revit_event":
            return self._eval_revit(params, key)
        return False, {}

    @staticmethod
    def _params(node: dict) -> dict:
        # Node param shapes vary: dict OR list[{k,v}] OR missing.
        p = node.get("params")
        if isinstance(p, dict):
            return p
        if isinstance(p, list):
            return {item.get("k"): item.get("v")
                    for item in p
                    if isinstance(item, dict) and item.get("k")}
        return {}

    # ── scheduler ──────────────────────────────────────────────
    def _eval_schedule(self, params: dict, key: str,
                        now: float) -> tuple[bool, dict]:
        spec = str(params.get("interval")
                   or params.get("expression")
                   or params.get("every")
                   or "every 5m").strip().lower()
        seconds = self._parse_interval(spec)
        if seconds <= 0:
            return False, {}
        last = self._last_fired.get(key, 0.0)
        if now - last < seconds:
            return False, {}
        return True, {"interval_s": seconds, "spec": spec}

    @staticmethod
    def _parse_interval(spec: str) -> float:
        # Accept: "every 10m", "every 1h", "every 30s", "every 1d", "5m"
        s = spec.strip().lower().replace("every ", "")
        if not s:
            return 0.0
        try:
            unit = s[-1]
            num = float(s[:-1])
            if unit == "s":
                return num
            if unit == "m":
                return num * 60
            if unit == "h":
                return num * 3600
            if unit == "d":
                return num * 86400
            return float(s)   # bare number = seconds
        except Exception:
            return 0.0

    # ── file watcher ───────────────────────────────────────────
    def _eval_file_save(self, params: dict, key: str
                         ) -> tuple[bool, dict]:
        path = params.get("path") or params.get("file") or ""
        if not path:
            return False, {}
        try:
            mt = Path(path).stat().st_mtime
        except Exception:
            return False, {}
        prev = self._file_mtime.get(key, 0.0)
        if prev == 0:
            self._file_mtime[key] = mt
            return False, {}
        if mt > prev + 0.5:   # debounce sub-second touches
            self._file_mtime[key] = mt
            return True, {"path": str(path), "mtime": mt}
        return False, {}

    # ── host warnings ──────────────────────────────────────────
    def _eval_warning(self, params: dict, key: str
                       ) -> tuple[bool, dict]:
        # Poll host_detector for warnings; fire if count above threshold
        # changes upward since last seen. Cheap — doesn't import every
        # tick; lazy first-use.
        try:
            from host_detector import detect_all_hosts   # type: ignore
        except Exception:
            return False, {}
        threshold = int(params.get("threshold") or 0)
        try:
            hosts = detect_all_hosts() or {}
        except Exception:
            return False, {}
        warnings = []
        for hid, h in hosts.items():
            if not isinstance(h, dict):
                continue
            for w in (h.get("warnings") or []):
                warnings.append({"host": hid, "msg": str(w)})
        count = len(warnings)
        prev = self._warn_seen.get(key, 0)
        self._warn_seen[key] = count
        if count > prev and count > threshold:
            return True, {"warnings": warnings, "count": count}
        return False, {}

    # ── email watcher (Outlook) ────────────────────────────────
    def _eval_email(self, params: dict, key: str
                     ) -> tuple[bool, dict]:
        # Best-effort: Outlook COM poll on Windows. Returns first time
        # we see a NEW unread message id we hadn't seen before.
        if not self._can_outlook():
            return False, {}
        sender_filter = (params.get("from") or "").lower().strip()
        subject_filter = (params.get("subject") or "").lower().strip()
        try:
            ids, latest = self._outlook_unread()
        except Exception:
            return False, {}
        seen = self._email_seen.setdefault(key, set())
        new_ids = [i for i in ids if i not in seen]
        if not seen and new_ids:
            # First poll seeds the cache; don't fire.
            seen.update(new_ids)
            return False, {}
        seen.update(new_ids)
        # Apply filters on the freshest match for descriptive payload.
        if not new_ids:
            return False, {}
        msg = latest.get(new_ids[0]) if isinstance(latest, dict) else {}
        if sender_filter and sender_filter not in str(msg.get("from", "")).lower():
            return False, {}
        if subject_filter and subject_filter not in str(msg.get("subject", "")).lower():
            return False, {}
        return True, {"new_ids": new_ids, "latest": msg}

    @staticmethod
    def _can_outlook() -> bool:
        try:
            import win32com.client  # type: ignore  # noqa: F401
            return True
        except Exception:
            return False

    @staticmethod
    def _outlook_unread() -> tuple[list[str], dict]:
        import pythoncom         # type: ignore
        import win32com.client   # type: ignore
        pythoncom.CoInitialize()
        try:
            outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
            inbox = outlook.GetDefaultFolder(6)  # olFolderInbox
            items = inbox.Items
            items.Sort("[ReceivedTime]", True)
            ids: list[str] = []
            latest: dict = {}
            count = 0
            for it in items:
                count += 1
                if count > 25:
                    break
                if not getattr(it, "UnRead", False):
                    continue
                eid = str(getattr(it, "EntryID", "")) or str(it)
                ids.append(eid)
                if eid not in latest:
                    latest[eid] = {
                        "from": str(getattr(it, "SenderEmailAddress", "")),
                        "subject": str(getattr(it, "Subject", "")),
                        "received": str(getattr(it, "ReceivedTime", "")),
                    }
            return ids, latest
        finally:
            pythoncom.CoUninitialize()

    # ── Revit broker event poll ───────────────────────────────
    def _eval_revit(self, params: dict, key: str
                     ) -> tuple[bool, dict]:
        # Phase 1: poll the broker for last_event timestamp; fire when
        # it advances. Event filters (doc_opened / view_changed /
        # sync_done) are passed in `event_kinds` param as comma list.
        wanted = {x.strip() for x in str(params.get("event_kinds")
                                           or "doc_opened,view_changed,sync_done")
                                          .split(",") if x.strip()}
        try:
            import urllib.request
            req = urllib.request.Request(
                "http://127.0.0.1:48884/last_event",
                headers={"User-Agent": "ArchHub-trigger/1"})
            with urllib.request.urlopen(req, timeout=0.6) as resp:
                payload = json.loads(resp.read().decode("utf-8", "ignore"))
        except Exception:
            return False, {}
        ev_id = str(payload.get("id") or payload.get("ts") or "")
        ev_kind = str(payload.get("kind") or "")
        if not ev_id or ev_kind not in wanted:
            return False, {}
        last = self._revit_seen.get(key, "")
        if ev_id == last:
            return False, {}
        self._revit_seen[key] = ev_id
        return True, {"event": payload}
