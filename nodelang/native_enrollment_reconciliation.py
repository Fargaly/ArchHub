"""Read existing enrollment custody; never mint, retry or infer past success."""
import hashlib
import math
import json
import re
import secrets
import time

from .application_machine_transport import MachinePipePeer
from .cell_authorization import AuthorizationDenied

PATH = "/api/universal/agent-session-reconcile"
STATUS = "/api/universal/agent-session-continuation-status"


def _digest(body):
    return hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()


def reserve_continuation(owner, body, peer):
    """Called under mutation/session locks before the one capability insertion."""
    identity = body.get("continuation_id")
    now = time.time()
    if (type(peer) is not MachinePipePeer or type(identity) is not str
            or not re.fullmatch(r"[a-f0-9]{32}",identity)
            or not now-60 <= int(identity[:8],16) <= now+5):
        raise AuthorizationDenied("native continuation requires a fresh exact request and OS peer")
    receipts = owner._machine_agent_continuation_receipts
    for key in tuple(receipts):
        if receipts[key]["until"] <= now:
            del receipts[key]
    if identity in receipts:
        raise AuthorizationDenied("native continuation was already attempted; inspect its exact outcome")
    if len(receipts) >= 128:
        raise AuthorizationDenied("native continuation receipt capacity reached")
    receipts[identity] = {"digest":_digest(body),"peer":peer,"until":now+600,
        "actor":body["expected_agent_session"],"outcome":"pending"}


def confirm_continuation(owner, body, result):
    held = owner._machine_agent_continuation_receipts[body["continuation_id"]]
    held["token_digest"] = hashlib.sha256(result["session_token"].encode()).hexdigest()
    held["result"] = {key:value for key,value in result.items() if key != "session_token"}
    held["outcome"] = "confirmed"


def record_pre_enrollment_refusal(owner, body, peer):
    """Record an exact fresh refusal before capability insertion, under owner locks."""
    reserve_continuation(owner, body, peer)
    owner._machine_agent_continuation_receipts[body['continuation_id']]['outcome'] = 'not-enrolled'


def continuation_status(owner, request, peer):
    body = request.get("body")
    if type(body) is not dict or set(body) != {"runtime","external_session_id","expected_agent_session","continuation_id"}:
        raise AuthorizationDenied("native continuation status requires its exact request")
    if type(body["continuation_id"]) is not str or not re.fullmatch(r"[a-f0-9]{32}",body["continuation_id"]):
        raise AuthorizationDenied("native continuation status identity is invalid")
    with owner.mutation_lock, owner._machine_agent_session_lock:
        identity = reconcile_enrollment(owner,{**request,"path":PATH,
            "body":{key:value for key,value in body.items() if key != "continuation_id"}},peer)
        held = owner._machine_agent_continuation_receipts.get(body["continuation_id"])
        base = {"continuation_id":body["continuation_id"],"agent_session":identity["agent_session"]}
        if held is None or held["until"] <= time.time():
            return {**base,"outcome":"unknown"}
        if held["digest"] != _digest(body) or held["peer"] != peer:
            raise AuthorizationDenied("native continuation outcome belongs to different custody")
        if held['outcome'] == 'not-enrolled':
            return {**base, 'outcome':'not-enrolled'}
        if held["outcome"] != "confirmed":
            return {**base,"outcome":"unresolved"}
        binding = owner._machine_agent_sessions.get(held["actor"])
        if (binding is None or binding["expires_at"] <= time.time()
                or binding.get("enrollment_peer") != {"pid":peer.pid,"created_at":peer.created_at}
                or hashlib.sha256(binding["token"].encode()).hexdigest() != held["token_digest"]):
            return {**base,"outcome":"unavailable"}
        return {**base,"outcome":"confirmed","result":{**held["result"],"session_token":binding["token"]}}


def reconcile_enrollment(owner, request, peer):
    from .application_server import _agent_body_catalog_entry_for_runtime
    body = request.get("body")
    if (type(peer) is not MachinePipePeer or request.get("method") != "POST"
            or request.get("path") != PATH or type(request.get("session")) is not dict
            or request["session"] != {} or type(body) is not dict
            or set(body) not in ({"runtime", "external_session_id", "expected_agent_session"},
                                {"runtime", "external_session_id", "expected_agent_session", "projection"},
                                {"runtime", "external_session_id", "expected_agent_session", "projection", "cursor"})
            or ("projection" in body and body["projection"] != "effects")
            or type(body["runtime"]) is not str
            or body["runtime"] not in {"codex", "claude", "gemini", "opencode"}
            or type(body["external_session_id"]) is not str
            or not 0 < len(body["external_session_id"].encode("utf-8")) <= 4096
            or type(body["expected_agent_session"]) is not str
            or not re.fullmatch(r"app:agent-session:runtime:[a-f0-9]{32}", body["expected_agent_session"])):
        raise AuthorizationDenied("native reconciliation requires exact unbound identity and local peer")
    fingerprint = hashlib.sha256(body["external_session_id"].encode("utf-8")).hexdigest()
    with owner.mutation_lock, owner._machine_agent_session_lock:
        entry = _agent_body_catalog_entry_for_runtime(owner.universal_store.snapshot(),
            owner.universal_registry, body["runtime"])
        if entry.credential_mode != "machine-transport":
            raise AuthorizationDenied("native reconciliation requires existing machine transport authority")
        # Do not use the continuation helper: its legacy fallback can mint a
        # signed identity relationship. Missing proof must stay a refusal.
        actor = owner._bound_machine_agent_session_identity(entry=entry, runtime=body["runtime"],
            external_session_fingerprint=fingerprint, custody_root=None)
        if actor is None or actor.root_id != body["expected_agent_session"]:
            raise AuthorizationDenied("native reconciliation signed identity does not match expected actor")
        binding = owner._machine_agent_sessions.get(actor.root_id)
        status, same_peer = "absent", None
        if binding is not None:
            if (binding.get("runtime") != body["runtime"] or binding.get("catalog_entry") != entry.root_id
                    or binding.get("external_session_fingerprint") != fingerprint
                    or binding.get("device_custody") is not None):
                raise AuthorizationDenied("native reconciliation current custody is inconsistent")
            expires = binding.get("expires_at")
            if type(expires) not in (int,float) or not math.isfinite(expires):
                raise AuthorizationDenied("native reconciliation lease is invalid")
            status = "expired" if expires <= time.time() else "retained"
            same_peer = binding.get("enrollment_peer") == {"pid":peer.pid,"created_at":peer.created_at}
        result = {"agent_session":actor.root_id,"runtime":body["runtime"],
            "runtime_id":request["runtime_id"],"binding_status":status,
            "binding_matches_caller":same_peer,
            "active_operations":owner._machine_agent_active_requests.get(actor.root_id,0),
            "revision":owner.universal_store.revision,
            "historical_attempt_outcome":"unknown","continuation_authorized":False}
        if body.get("projection") == "effects":
            from .native_session_release import read_pending_effects
            from .universal_cell import NULL_CELL_ID
            cache = getattr(owner, "_native_effects_read_cursors", None)
            if cache is None:
                cache = owner._native_effects_read_cursors = {}
            now = time.monotonic()
            for key in tuple(cache):
                if cache[key]["until"] <= now:
                    del cache[key]
            start = None
            remaining = None
            cursor = body.get("cursor")
            if cursor is not None:
                held = cache.get(cursor) if type(cursor) is str else None
                if (held is None or held["actor"] != actor.root_id or held["peer"] != peer
                        or held["revision"] != owner.universal_store.revision):
                    raise AuthorizationDenied("Native effects cursor custody or revision changed")
                start = held["chain"]
                remaining = held["remaining"]
            page = read_pending_effects(owner.universal_store.snapshot(),
                owner.universal_registry.cde_write_authority_protocol, actor.root_id, start=start, remaining=remaining)
            following = page.pop("_next_chain")
            next_remaining = page.pop("_next_remaining")
            if same_peer is not True:
                page["pending_permits"] = [{key:row[key] for key in ("permit","state","issued_at","expires_at")}
                    for row in page["pending_permits"]]
                page["receipt_references"] = []
            page["disclosure"] = "bound-peer" if same_peer is True else "minimal"
            page["next_cursor"] = None
            if following != NULL_CELL_ID:
                if cursor is None and len(cache) >= 16:
                    raise AuthorizationDenied("Native effects cursor capacity is occupied")
                token = secrets.token_hex(16)
                cache[token] = {"actor":actor.root_id,"peer":peer,"revision":page["revision"],
                    "chain":following,"remaining":next_remaining,"until":now+60.0}
                page["next_cursor"] = token
            if cursor is not None:
                cache.pop(cursor, None)
            result["effects"] = page
            if len(json.dumps(result, ensure_ascii=True).encode("utf-8")) > 65536:
                raise AuthorizationDenied("Native effects inspection exceeds its bounded projection")
        return result
