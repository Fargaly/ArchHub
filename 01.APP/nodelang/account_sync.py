"""Account sync, desktop side (D-051): the ArchHub account is the source, this PC caches.

One client for the cloud owner (/v1/account-sync/*). A namespace (logical-path
prefix such as "connections/") registers three local callbacks and gets: put
and delete that follow every local change to the account, and pull_and_restore()
after sign-in, which uploads local-only items once (migration), brings account
items this PC lacks or holds an older copy of, and drops items the account
removed. Inert when signed out or when DesktopAccess does not admit work. The
sync watermark (logical path -> last agreed sha256, per account) is machine-local
metadata in settings/sync-state.json and never synced.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import logging
import os
import threading
import urllib.parse

from . import cloud_social_oauth as _cloud

MISSING = object()  # the account says this item was removed
_NEEDS_RECONNECT: set = set()  # account items sealed under a key the cloud lost (last restore)
_NAMESPACES: dict[str, dict] = {}
_LOCK = threading.RLock()
_http = None     # tests replace the cloud request
_access = None   # tests replace the DesktopAccess admission
_LOG = logging.getLogger(__name__)


def register(prefix, *, items, cache, drop, conflict_copies=True):
    """items() -> {logical_path: (meta, bytes)}; cache(path, bytes); drop(path, meta).

    conflict_copies=False for items whose newest version is simply right (a rotated token).
    """
    _NAMESPACES[prefix] = {"items": items, "cache": cache, "drop": drop, "conflicts": conflict_copies}


def canonical(record):
    """The one byte form of a JSON item, shared with the cloud so hashes agree."""
    return json.dumps(record, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode("ascii")


def _admitted():
    global _access
    if _access is None:
        from .cloud_session import DesktopAccess
        _access = DesktopAccess()
    try:
        return _access.check().get("admitted") is True
    except Exception:
        return False


def _call(method, route, body=None, query=""):
    token, base = _cloud._session(None)
    if not token or not _admitted():
        return None, {}
    try:
        return (_http or _cloud._request)(method, base + route + query, bearer=token, body=body)
    except OSError:
        return None, {}


def _account():
    from .cloud_signin import cloud_session_path, read_cloud_session
    held = read_cloud_session(cloud_session_path())
    return str(held.get("user_id") or held.get("email") or "").strip().casefold()


def _state_path():
    from .user_paths import state_directory
    return state_directory() / "settings" / "sync-state.json"


def _state():
    """{"base": {path: sha256}, "pending_delete": set} for the signed-in account."""
    try:
        whole = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        whole = {}
    mine = whole.get(_account(), {}) if isinstance(whole, dict) else {}
    return {"base": dict(mine.get("base", {})), "pending_delete": set(mine.get("pending_delete", []))}


def _save_state(state):
    path = _state_path()
    try:
        whole = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        whole = {}
    whole[_account()] = {"base": state["base"], "pending_delete": sorted(state["pending_delete"])}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(whole, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _device():
    return "desktop-" + hashlib.sha256(os.environ.get("COMPUTERNAME", "pc").encode()).hexdigest()[:16]


def _upload(path, content, state):
    code, answer = _call("PUT", "/v1/account-sync/item", {
        "logical_path": path, "base_sha256": state["base"].get(path, ""), "device_id": _device(),
        "content_b64": base64.b64encode(gzip.compress(content)).decode("ascii")})
    if code == 200 and isinstance(answer.get("sha256"), str):
        state["base"][path] = answer["sha256"]
        state["pending_delete"].discard(path)
        return True
    return False


def put(path, content):
    """Follow a local save to the account; False when not reached (pull_and_restore retries)."""
    with _LOCK:
        state = _state()
        done = _upload(path, content, state)
        if done:
            _save_state(state)
        return done


def delete(path):
    """Follow a local removal to the account; an unreached account is retried on restore."""
    with _LOCK:
        if not _cloud._session(None)[0]:
            return False
        state = _state()
        code, _answer = _call("PUT", "/v1/account-sync/item", {"logical_path": path, "deleted": True, "device_id": _device(),
                                              "base_sha256": state["base"].get(path, "")})
        state["base"].pop(path, None)
        (state["pending_delete"].discard if code == 200 else state["pending_delete"].add)(path)
        _save_state(state)
        return code == 200


def connection(entry):
    """The account's record for one connection call: dict, MISSING if the account removed it, None if unknown."""
    entry = urllib.parse.quote(entry, safe="")
    code, answer = _call("POST", f"/v1/account-sync/connection/{entry}")
    if code == 200 and isinstance(answer.get("record"), dict):
        return answer["record"]
    if code == 410 and answer == {"removed": True}:
        return MISSING  # only the account-sync route's explicit removal answer revokes
    return None  # a missing route, a bare 404, 5xx or no answer: unavailable, this PC's cache serves


def _fetch(path, sha256):
    code, answer = _call("GET", f"/v1/account-sync/blob/{sha256}", query="?" + urllib.parse.urlencode({"logical_path": path}))
    try:
        content = gzip.decompress(base64.b64decode(answer["content_b64"])) if code == 200 else None
    except (KeyError, TypeError, ValueError, OSError, EOFError):
        content = None
    return content if isinstance(content, bytes) and hashlib.sha256(content).hexdigest() == sha256 else None


def pull_and_restore(prefix=None):
    """Sign-in restore for one namespace or all: {prefix: counts}, or {} when not signed in."""
    with _LOCK:
        code, listing = _call("GET", "/v1/account-sync/manifest", query="?since=0")
        if code != 200 or not isinstance(listing.get("items"), list):
            return {}
        heads = {row["logical_path"]: row for row in listing["items"] if isinstance(row, dict)}
        state = _state()
        for path in list(state["pending_delete"]):
            if _call("PUT", "/v1/account-sync/item", {"logical_path": path, "deleted": True, "device_id": _device()})[0] == 200:
                state["pending_delete"].discard(path)
        done = {}
        for name in ([prefix] if prefix else list(_NAMESPACES)):
            done[name] = _restore(name, _NAMESPACES[name], heads, state)
        _save_state(state)
        return done


def _restore(prefix, hooks, heads, state):
    counts = {"uploaded": 0, "pulled": 0, "dropped": 0}
    remote = {path: row for path, row in heads.items() if path.startswith(prefix) and not row.get("deleted")
              and path not in state["pending_delete"]}
    local = hooks["items"]()
    for path, (meta, content) in local.items():
        if path in remote or path in state["pending_delete"]:
            continue
        if path in state["base"] and heads.get(path, {}).get("deleted") is True:  # removed on another PC (tombstone)
            hooks["drop"](path, meta)
            state["base"].pop(path)
            counts["dropped"] += 1
        elif _upload(path, content, state):  # migration: a local-only item joins the account once
            counts["uploaded"] += 1
    for path, row in remote.items():
        held = local.get(path)
        _NEEDS_RECONNECT.discard(path)
        if row.get("needs_reconnect"):
            # The account lost the key that sealed this item: this PC's copy heals it, else it must be reconnected.
            if held and _upload(path, held[1], state):
                counts["healed"] = counts.get("healed", 0) + 1
            else:
                _NEEDS_RECONNECT.add(path)
            continue
        if held and hashlib.sha256(held[1]).hexdigest() == row["sha256"]:
            state["base"][path] = row["sha256"]
            continue
        if hooks["conflicts"] and held and state["base"].get(path) not in (None, row["sha256"]) and \
                hashlib.sha256(held[1]).hexdigest() != state["base"][path]:
            # Both sides changed since the last agreement: the account's head wins (LWW); this PC's copy goes up
            # beside it so nothing is lost.
            _upload(path.rsplit(".", 1)[0] + " (conflict " + _device() + ")." + path.rsplit(".", 1)[-1],
                    held[1], state)
        content = _fetch(path, row["sha256"])
        if content is not None:
            hooks["cache"](path, content)
            state["base"][path] = row["sha256"]
            counts["pulled"] += 1
    return counts


def needs_reconnect(prefix):
    """Account items under prefix that no PC can open any more (shown as Reconnect, never dropped)."""
    return sorted(path for path in _NEEDS_RECONNECT if path.startswith(prefix))


def restore_in_background():
    """After sign-in: restore every namespace without holding the caller."""
    def work():
        try:
            pull_and_restore()
        except Exception as missed:
            _LOG.warning("account restore did not finish (%s); retried at the next sign-in", type(missed).__name__)
    threading.Thread(target=work, name="archhub-account-restore", daemon=True).start()
