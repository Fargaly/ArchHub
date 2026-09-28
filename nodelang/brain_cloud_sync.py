"""Personal cloud sync as a transport over graph-held, governed memory.

The legacy client (personal-brain-mcp personal_cloud_sync.py) read SQLite,
pushed the whole USER corpus every tick, carried no forgets, and reset local
columns on every round-trip. This client reads and writes ``cell_brain_memory``
for ONE session and speaks the UNCHANGED cloud contract: ``POST
/v1/brain/sync`` over a replica that keeps last-writer-wins by HLC string
(cloud_backend brain_replica.py). The server keeps its replica and its search;
nothing here replaces them.

What may leave the device is the governance layer's decision, never this
module's: a memory is pushed only while ``may_release(..., to_lake="personal")``
allows it, so unclassified and sealed memories never leave. When a memory the
server already holds stops being releasable -- it was forgotten, or filed into
a sealed class -- the client sends a RETRACTION: a row with no text, marked
expired, that blanks the server copy and tells the owner's other devices to
apply the forget and the classification. The classification travels with every
row, so all of the owner's devices reach the same ceiling.

One server row per memory:

* ``hlc`` is ``<16-digit clock>.<origin>`` of the newest part (text, state or
  classification), so the server's string comparison orders like the sync law;
* ``extra.brain_memory`` carries the parts with their own origin and clock, so
  pulling a row back restores the memory exactly and a replay changes nothing.

The server keeps one row per id and replaces it only for a strictly greater
HLC, so the row HLC versions the WHOLE row, not one part. A push is first
offered at its natural HLC. When the server keeps its own row instead -- a
forget whose clock is older than the text it takes back, or one whose clock
equals the row it replaces -- the answer shows that row; the client merges it
part by part and, only if its own parts still differ, offers the whole row
again just above the HLC seen in that same answer. A push counts as landed only when the server's answer shows
that row with that HLC and that text; otherwise the client merges the server
row part by part and offers the whole row again. Tracking moves only after
that confirmation.

A row the legacy client left has no ``extra.brain_memory``: its clock is the
HLC's physical milliseconds, its origin is named from the HLC suffix, and it
arrives unclassified, so it stays on this device until someone files it.

What to push is decided per origin: the cursor keeps, for each origin, the
newest clock the server is known to hold, and the ids whose content the server
holds. Clocks are epoch milliseconds and never go backwards within one origin
(one origin names one device). The transport is injected (``post(payload) ->
response``) and the caller keeps the cursor, so no network call and no token
read happen here. Run one sync at a time per store.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .cell_brain_governance import classification_record, classify, may_release
from .cell_brain_memory import (
    CONFIDENCES,
    FORGOTTEN,
    LIVE,
    MEMORY_KINDS,
    Memory,
    acting_owner,
    forget,
    memories,
    merge_memories,
    recall_memory,
)
from .cell_brain_secrets import assert_no_credential_in_text, assert_not_a_secret
from .universal_cell import InvalidCell

EXTRA_KEY = "brain_memory"
PERSONAL_LAKE = "personal"
_MAX_CLOCK = 10 ** 16
# A push the server did not store is rebuilt over the server row and offered
# again within the same sync, at most this many exchanges in all.
_ROUNDS = 3
# Skip reasons name only values from these lists, never an arbitrary server value.
_KNOWN_SCOPES = frozenset(("project", "firm", "community"))
_KNOWN_OTHER_KINDS = frozenset(("skill", "trace", "wiring", "secret_ref", "geometry",
                                "image"))


@dataclass(frozen=True, slots=True)
class SyncCursor:
    """``since_hlc``: the server's pull cursor. ``held``: per origin, the newest
    clock the server is known to hold, as sorted (origin, clock) pairs.
    ``released``: the sorted ids whose content the server holds. ``rows``: per
    id, the server row's HLC and the parts that row carries, as sorted
    (id, hlc, parts) triples -- what the server confirmed, not what was sent."""

    since_hlc: str = ""
    held: tuple = ()
    released: tuple = ()
    rows: tuple = ()


@dataclass(frozen=True, slots=True)
class SyncReport:
    pushed: int
    retracted: int
    pulled: int
    unchanged: int
    rejected: tuple
    skipped: dict
    cursor: SyncCursor


@dataclass(frozen=True, slots=True)
class _Incoming:
    fragment_id: str
    memory: Memory | None
    retraction: dict | None
    classification: dict | None


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < _MAX_CLOCK


def encode_hlc(clock, origin):
    if not _whole(clock):
        raise InvalidCell("a sync clock must be a whole number below 10**16")
    if not isinstance(origin, str) or not origin.strip():
        raise InvalidCell("a sync origin cannot be empty")
    return "%016d.%s" % (clock, origin)


def _decode_hlc(hlc):
    if not isinstance(hlc, str) or "." not in hlc:
        return None, None
    physical, suffix = hlc.split(".", 1)
    if not physical.isdigit() or not suffix:
        return None, None
    return int(physical), suffix


def _iso(clock_ms):
    moment = datetime.fromtimestamp(clock_ms / 1000, timezone.utc)
    return moment.isoformat().replace("+00:00", "Z")


def _epoch_ms(stamp):
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    try:
        moment = datetime.fromisoformat(stamp.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return round(moment.timestamp() * 1000)


def _classification_part(record):
    if record is None:
        return None
    return {"value": record.value, "origin": record.origin, "clock": record.clock}


def _parts(memory, record):
    parts = [(memory.text_origin, memory.text_clock),
             (memory.state_origin, memory.state_clock)]
    if record is not None:
        parts.append((record.origin, record.clock))
    return tuple(parts)


def _newest(parts):
    origin, clock = max(parts, key=lambda part: (part[1], part[0]))
    return clock, origin


def _raise_to(held, parts):
    for origin, clock in parts:
        if clock > held.get(origin, -1):
            held[origin] = clock


def _row_hlc(parts, above):
    """The newest part's HLC, raised just above the server row it replaces."""
    clock, origin = _newest(parts)
    hlc = encode_hlc(clock, origin)
    if above is not None and hlc <= above:
        server_clock, _ = _decode_hlc(above)
        if server_clock is None or not _whole(server_clock + 1):
            raise InvalidCell("the server row carries no clock to follow")
        hlc = encode_hlc(server_clock + 1, origin)
    return hlc


def _row(memory, record, *, owner_user, text, valid_until, parts, above=None):
    return {
        "id": memory.fragment_id,
        "kind": memory.kind,
        "text": text,
        "scope": "user",
        "visibility": "private",
        "owner_user": owner_user,
        "confidence": memory.confidence,
        "provenance": {},
        "valid_until": valid_until,
        "extra": {EXTRA_KEY: parts},
        "hlc": _row_hlc(_parts(memory, record), above),
    }


def memory_to_row(memory, record, *, owner_user, above=None):
    """The server row that carries one releasable memory and its classification.
    ``above`` is the HLC of the server row it must replace."""
    return _row(
        memory, record, owner_user=owner_user, text=memory.text, above=above,
        valid_until=_iso(memory.state_clock) if memory.state == FORGOTTEN else None,
        parts={
            "text_origin": memory.text_origin,
            "text_clock": memory.text_clock,
            "state": memory.state,
            "state_origin": memory.state_origin,
            "state_clock": memory.state_clock,
            "classification": _classification_part(record),
        })


def retraction_row(memory, record, *, owner_user, above=None):
    """A row that takes back what the server was given. It carries no content."""
    clock, _ = _newest(_parts(memory, record))
    return _row(
        memory, record, owner_user=owner_user, text="", valid_until=_iso(clock),
        above=above,
        parts={
            "retracted": True,
            "state": memory.state,
            "state_origin": memory.state_origin,
            "state_clock": memory.state_clock,
            "classification": _classification_part(record),
        })


def _read_classification(parts):
    found = parts.get("classification")
    if found is None:
        return None
    if (not isinstance(found, dict) or not isinstance(found.get("value"), str)
            or found["value"].count("|") != 1
            or not isinstance(found.get("origin"), str) or not found["origin"].strip()
            or not _whole(found.get("clock"))):
        raise InvalidCell("malformed classification")
    return found


def _read_row(row, owner_root):
    """One server row as incoming memory, or the named reason it is not."""
    if not isinstance(row, dict):
        return None, "not-an-object"
    fragment_id = row.get("id")
    if not isinstance(fragment_id, str) or not fragment_id.strip():
        return None, "no-id"
    scope = row.get("scope") or "user"
    if scope != "user":
        return None, "scope:%s" % (scope if scope in _KNOWN_SCOPES else "other")
    kind = row.get("kind")
    if kind not in MEMORY_KINDS:
        return None, "kind:%s" % (kind if kind in _KNOWN_OTHER_KINDS else "other")
    extra = row.get("extra")
    parts = extra.get(EXTRA_KEY) if isinstance(extra, dict) else None
    if parts is not None and not isinstance(parts, dict):
        return None, "malformed-parts"
    try:
        classification = _read_classification(parts) if parts else None
    except InvalidCell:
        return None, "malformed-parts"
    if parts is not None and parts.get("retracted") is True:
        state = parts.get("state")
        origin, clock = parts.get("state_origin"), parts.get("state_clock")
        if (state not in (LIVE, FORGOTTEN) or not isinstance(origin, str)
                or not origin.strip() or not _whole(clock)):
            return None, "malformed-parts"
        return _Incoming(fragment_id, None,
                         {"state": state, "origin": origin, "clock": clock},
                         classification), None
    text = row.get("text")
    if not isinstance(text, str) or not text.strip():
        return None, "empty"
    try:
        assert_not_a_secret(text, "synced memory text")
        assert_no_credential_in_text(text, "synced memory text")
    except InvalidCell:
        return None, "looks-like-a-secret"
    confidence = row.get("confidence")
    if confidence not in CONFIDENCES:
        confidence = "extracted"
    if parts is not None:
        state = parts.get("state")
        text_origin, state_origin = parts.get("text_origin"), parts.get("state_origin")
        text_clock, state_clock = parts.get("text_clock"), parts.get("state_clock")
        if (state not in (LIVE, FORGOTTEN)
                or not isinstance(text_origin, str) or not text_origin.strip()
                or not isinstance(state_origin, str) or not state_origin.strip()
                or not _whole(text_clock) or not _whole(state_clock)):
            return None, "malformed-parts"
        memory = Memory(fragment_id, text, kind, confidence, owner_root, state,
                        text_origin, text_clock, state_origin, state_clock)
        return _Incoming(fragment_id, memory, None, classification), None
    clock, suffix = _decode_hlc(row.get("hlc"))
    if clock is None or not _whole(clock):
        return None, "no-clock"
    origin = "hlc:" + suffix
    state, state_clock = LIVE, clock
    if row.get("valid_until"):
        until = _epoch_ms(row["valid_until"])
        state = FORGOTTEN
        state_clock = until if until is not None and until > clock else clock + 1
        if not _whole(state_clock):
            return None, "no-clock"
    memory = Memory(fragment_id, text, kind, confidence, owner_root, state,
                    origin, clock, origin, state_clock)
    return _Incoming(fragment_id, memory, None, None), None


def _apply(store, session_root, incoming):
    """Merge one incoming row; return the parts it proves the server holds."""
    if incoming.memory is not None:
        merge_memories(store, (incoming.memory,), session_root=session_root)
        parts = _parts(incoming.memory, None)
    else:
        retraction = incoming.retraction
        parts = ((retraction["origin"], retraction["clock"]),)
        held_here = recall_memory(store.snapshot(), incoming.fragment_id,
                                  session_root=session_root)
        if held_here is not None and retraction["state"] == FORGOTTEN:
            forget(store, session_root=session_root, fragment_id=incoming.fragment_id,
                   origin=retraction["origin"], clock=retraction["clock"])
    found = incoming.classification
    if found is not None:
        parts += ((found["origin"], found["clock"]),)
        if recall_memory(store.snapshot(), incoming.fragment_id,
                         session_root=session_root) is not None:
            data_class, stratum = found["value"].split("|")
            classify(store, session_root=session_root, fragment_id=incoming.fragment_id,
                     data_class=data_class, stratum=stratum, origin=found["origin"],
                     clock=found["clock"])
    return parts


def _incoming_parts(incoming):
    """The parts one server row carries, in the shape ``_parts`` gives."""
    if incoming.memory is not None:
        parts = ((incoming.memory.text_origin, incoming.memory.text_clock),
                 (incoming.memory.state_origin, incoming.memory.state_clock))
    else:
        parts = ((incoming.retraction["origin"], incoming.retraction["clock"]),)
    found = incoming.classification
    if found is not None:
        parts += ((found["origin"], found["clock"]),)
    return parts


def _outgoing(snapshot, *, session_root, owner_user, held, released, rows, only, seen):
    """What this device offers: (action, id, parts, row) per changed memory.

    An id whose server row is known is offered when its parts differ from that
    row's; any other id when one of its parts is newer than ``held``. A row is
    stamped above a server row only when ``seen`` holds that row from THIS
    sync's own answer: a view kept from an earlier sync may be stale, and
    stamping over it would let an older edit replace a newer one."""
    outgoing = []
    for memory in memories(snapshot, session_root=session_root, include_forgotten=True):
        if only is not None and memory.fragment_id not in only:
            continue
        record = classification_record(snapshot, session_root=session_root,
                                       fragment_id=memory.fragment_id)
        parts = _parts(memory, record)
        known = rows.get(memory.fragment_id)
        if known is not None:
            if known[1] == parts:
                continue
        elif not any(clock > held.get(origin, -1) for origin, clock in parts):
            continue
        above = seen.get(memory.fragment_id)
        if may_release(snapshot, session_root=session_root,
                       fragment_id=memory.fragment_id, to_lake=PERSONAL_LAKE).allowed:
            row = memory_to_row(memory, record, owner_user=owner_user, above=above)
            outgoing.append(("content", memory.fragment_id, parts, row))
        elif memory.fragment_id in released:
            row = retraction_row(memory, record, owner_user=owner_user, above=above)
            outgoing.append(("retraction", memory.fragment_id, parts, row))
        else:
            outgoing.append(("withheld", memory.fragment_id, parts, None))
    return outgoing


def _exchange(post, since, outgoing):
    """One POST. The pull reaches down to the oldest row pushed, so the answer
    shows every pushed id as the server now holds it."""
    sent = [row for _, _, _, row in outgoing if row is not None]
    if sent and since:
        since = min(since, min(row["hlc"] for row in sent).split(".", 1)[0])
    response = post({"since_hlc": since, "delta": {"fragments": sent, "wiring": []}})
    if not isinstance(response, dict):
        raise InvalidCell("the sync server answered with no object")
    merged = response.get("merged")
    found = merged.get("fragments") if isinstance(merged, dict) else None
    if not isinstance(found, list):
        raise InvalidCell("the sync server answered without merged fragments")
    new_hlc = response.get("new_hlc")
    if not isinstance(new_hlc, str):
        raise InvalidCell("the sync server answered without a cursor")
    rejected = frozenset(
        str(item.get("id")) for item in (response.get("rejected") or [])
        if isinstance(item, dict))
    return found, new_hlc, rejected


def sync_once(store, *, session_root, owner_user, cursor, post, full_pull=False):
    """Push what may leave and changed, take back what may no longer stay, and
    merge what the server returns -- all for the one owner the session acts for.

    ``full_pull`` asks for every row again. The server's cursor is its own
    clock, so a device that was offline can hold edits older than another
    device's cursor; a periodic full pull catches those, and because merging is
    idempotent it costs only time.
    """
    if not isinstance(cursor, SyncCursor):
        raise InvalidCell("sync needs its cursor")
    if not isinstance(owner_user, str) or not owner_user.strip():
        raise InvalidCell("sync needs the account it syncs for")
    owner_root = acting_owner(store.snapshot(), session_root)
    held = dict(cursor.held)
    released = set(cursor.released)
    rows = {fragment_id: (hlc, tuple(tuple(part) for part in parts))
            for fragment_id, hlc, parts in cursor.rows}
    advanced = dict(held)
    since = "" if full_pull else cursor.since_hlc
    rejected_ids, frozen, landed = set(), set(), {}
    pulled = unchanged = 0
    skipped = {}
    only = None
    # The server rows read in THIS sync's answers: the only rows a retry may
    # be stamped above. The first exchange always pushes at the natural HLC.
    seen = {}
    for _ in range(_ROUNDS):
        outgoing = _outgoing(store.snapshot(), session_root=session_root,
                             owner_user=owner_user, held=held, released=released,
                             rows=rows, only=only, seen=seen)
        found, new_hlc, rejected = _exchange(post, since, outgoing)
        server = {}
        for row in found:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                server[row["id"]] = row
                if isinstance(row.get("hlc"), str):
                    seen[row["id"]] = row["hlc"]
            incoming, reason = _read_row(row, owner_root)
            if incoming is not None:
                before = store.snapshot().revision
                try:
                    parts = _apply(store, session_root, incoming)
                except InvalidCell:
                    reason = "refused"
                else:
                    if store.snapshot().revision == before:
                        unchanged += 1
                    else:
                        pulled += 1
                    _raise_to(advanced, parts)
                    rows[incoming.fragment_id] = (row.get("hlc"), _incoming_parts(incoming))
                    if incoming.memory is not None:
                        released.add(incoming.fragment_id)
                    else:
                        released.discard(incoming.fragment_id)
                    continue
            skipped[reason] = skipped.get(reason, 0) + 1
        retry = set()
        for action, fragment_id, parts, sent in outgoing:
            if fragment_id in rejected:
                rejected_ids.add(fragment_id)
                frozen.update(origin for origin, _ in parts)
                continue
            if sent is None:
                _raise_to(advanced, parts)
                continue
            there = server.get(fragment_id)
            if (there is None or there.get("hlc") != sent["hlc"]
                    or (there.get("text") or "") != sent["text"]):
                retry.add(fragment_id)
                continue
            # The server holds exactly this row: only now does tracking move.
            _raise_to(advanced, parts)
            rows[fragment_id] = (sent["hlc"], parts)
            landed[fragment_id] = action
            if action == "content":
                released.add(fragment_id)
            else:
                released.discard(fragment_id)
        if not retry:
            break
        only, since = retry, new_hlc
    else:
        # Never stored: nothing about these ids is taken as held.
        for _, fragment_id, parts, _ in outgoing:
            if fragment_id in retry:
                frozen.update(origin for origin, _ in parts)
    for origin in frozen:
        if origin in held:
            advanced[origin] = held[origin]
        else:
            advanced.pop(origin, None)
    actions = list(landed.values())
    return SyncReport(
        actions.count("content"), actions.count("retraction"), pulled, unchanged,
        tuple(sorted(rejected_ids)), skipped,
        SyncCursor(new_hlc, tuple(sorted(advanced.items())), tuple(sorted(released)),
                   tuple(sorted((fragment_id, hlc, parts)
                                for fragment_id, (hlc, parts) in rows.items()))))