"""Keeps the application's Brain in step with the cloud while someone is signed in.

One pass (``sync_now``) runs the personal sync (``brain_cloud_sync``: only what
``may_release(..., "personal")`` allows leaves; unclassified stays here) and the
community sync (``brain_community_sync``: only what may reach the community goes
out; what comes back is quarantined). Signed out, a pass does nothing.

The cursors live beside the cloud session as one small file. They are an
accelerator: deleting the file only makes the next pass pull everything again,
and merging is idempotent, so nothing changes.

``start`` runs a pass shortly after the application opens and then every ten
minutes on one daemon thread; ``stop`` ends it. A failed pass is recorded and
retried at the next tick, never raised into the application.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import app_brain
from .brain_cloud_sync import SyncCursor, sync_once
from .brain_community_sync import CommunityCursor, community_sync_once
from .cell_brain_governance import firms_of, solo_firm_root
from .cloud_relay import load_cloud_session
from .cloud_session import signed_in_cloud_account

SYNC_PATH = "/v1/brain/sync"
FIRST_PASS_SECONDS = 30.0
INTERVAL_SECONDS = 600.0
DEFAULT_COMMUNITY_ID = "archhub-community"
_LOCK = threading.Lock()
_STATE: dict = {}


def community_id() -> str:
    return os.environ.get("ARCHHUB_DEFAULT_COMMUNITY_ID", DEFAULT_COMMUNITY_ID).strip()


def _appdata(appdata=None) -> Path:
    return Path(appdata or os.environ.get("APPDATA", ""))


def cursor_path(appdata=None) -> Path:
    return _appdata(appdata) / "ArchHub" / "brain" / "sync-cursor.json"


def _tuples(value):
    return tuple(_tuples(v) for v in value) if isinstance(value, list) else value


def _load_cursors(path):
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
        personal = SyncCursor(**{k: _tuples(v) for k, v in held["personal"].items()})
        community = CommunityCursor(**{k: _tuples(v) for k, v in held["community"].items()})
        return personal, community
    except (OSError, ValueError, KeyError, TypeError):
        return SyncCursor(), CommunityCursor()


def _save_cursors(path, personal, community):
    def plain(cursor):
        return {name: getattr(cursor, name) for name in cursor.__slots__}
    path.parent.mkdir(parents=True, exist_ok=True)
    spare = path.with_suffix(".tmp")
    spare.write_text(json.dumps({"personal": plain(personal), "community": plain(community)}),
                     encoding="utf-8")
    os.replace(spare, path)


def http_post(base_url, token, timeout=15.0):
    """The one transport: POST the sync body to the pinned cloud with the bearer."""
    def post(payload):
        request = urllib.request.Request(
            base_url.rstrip("/") + SYNC_PATH, method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                     "Accept": "application/json", "User-Agent": "ArchHub-desktop/2.0"})
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            return json.loads(answer.read().decode("utf-8"))
    return post


def _firm_root(store, owner):
    firms = firms_of(store.snapshot(), owner)
    return firms[0].root_id if firms else solo_firm_root(owner)


def sync_now(*, appdata=None, post=None) -> dict:
    """One pass for the signed-in account over the bound application Brain."""
    session = load_cloud_session(_appdata(appdata))
    email = signed_in_cloud_account(_appdata(appdata) / "ArchHub" / "brain" / "cloud.json")
    if session is None or email is None:
        return {"ok": False, "reason": "signed out"}
    post = post or http_post(session["base_url"], session["token"])
    path = cursor_path(appdata)
    personal, community = _load_cursors(path)
    cid = community_id()

    def run(store, owner):
        report = sync_once(store, session_root=app_brain.SESSION_ROOT, owner_user=email,
                           cursor=personal, post=post)
        shared = None
        if cid:
            shared = community_sync_once(
                store, session_root=app_brain.SESSION_ROOT, owner_user=email,
                firm_root=_firm_root(store, owner), community_id=cid,
                cursor=community, post=post)
        return report, shared
    report, shared = app_brain._write("sync the Brain with the cloud", run)
    _save_cursors(path, report.cursor, shared.cursor if shared else community)
    return {"ok": True, "pushed": report.pushed, "pulled": report.pulled,
            "retracted": report.retracted,
            "shared": shared.offered if shared else 0,
            "quarantined": shared.quarantined if shared else 0}


def _loop(stop, appdata):
    wait = FIRST_PASS_SECONDS
    while not stop.wait(wait):
        wait = INTERVAL_SECONDS
        try:
            result = sync_now(appdata=appdata)
        except (app_brain.BrainUnavailable, urllib.error.URLError, OSError, ValueError) as failed:
            result = {"ok": False, "reason": "%s: %s" % (type(failed).__name__, failed)}
        except Exception as failed:  # noqa: BLE001 -- a pass never takes the application down
            result = {"ok": False, "reason": "%s: %s" % (type(failed).__name__, failed)}
        with _LOCK:
            _STATE["last"] = dict(result, at=time.time())


def start(*, appdata=None):
    """Run passes in the background; one runner per process."""
    with _LOCK:
        if _STATE.get("thread") is not None and _STATE["thread"].is_alive():
            return _STATE["thread"]
        stop = threading.Event()
        thread = threading.Thread(target=_loop, args=(stop, appdata),
                                  name="archhub-brain-cloud-sync", daemon=True)
        _STATE.update(thread=thread, stop=stop)
        thread.start()
        return thread


def stop():
    with _LOCK:
        event = _STATE.pop("stop", None)
        _STATE.pop("thread", None)
    if event is not None:
        event.set()


def last_pass():
    with _LOCK:
        return dict(_STATE.get("last") or {})


__all__ = ["community_id", "cursor_path", "http_post", "last_pass", "start", "stop", "sync_now"]