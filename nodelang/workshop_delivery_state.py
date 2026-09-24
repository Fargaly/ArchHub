"""Per-message delivery state read from the Workshop's own indexed receipts.

A stored message says nothing about delivery. The relay, the Everyone broadcast
and the model turn each write their decision and outcome as ordinary history
records that reply to the message (SPEC 3.4/3.5). This module reads only those
records; it never infers success from a transcript, a registered session or a
connected process. States, per recipient:

    started      a dispatch record exists and the relay still holds that job
    replied      the recipient's own reply was relayed back into this Workshop
    unavailable  nothing reached the recipient, or it held/refused the message
    uncertain    a dispatch began and no outcome was recorded; never resent

A message with no delivery record is ``stored``. The overall state never claims
more than its weakest recipient: uncertain, then started, then unavailable,
then replied.
"""
from __future__ import annotations

import hashlib
import json
import re


RELAY_DECISION = "session-link:decision:"
RELAY_OUTCOME = "session-link:outcome:"
BROADCAST = "workshop-broadcast:"
RELAYED_REPLY = "Session Link relayed reply from "
STATES = ("stored", "started", "replied", "unavailable", "uncertain")
_ORDER = ("uncertain", "started", "unavailable", "replied")
_REASON = re.compile(r"\(([^()]{1,200})\)\. ")


# The relay writes these under its reply header when no agent text was stored;
# they are the application's own sentences, never the agent's.
_NOT_AGENT_TEXT = ("The transport reported a reply without readable text.",
                   "The reply arrived, but this Workshop refused to store its text")


def relayed_reply_text(content):
    """The agent's own text inside a relayed-reply record, or None."""
    if type(content) is not str or not content.startswith(RELAYED_REPLY) or "\n\n" not in content:
        return None
    header, text = content.split("\n\n", 1)
    if (header.endswith("execution evidence.") and text.startswith(_NOT_AGENT_TEXT)
            and "\n\n" not in text):
        return None
    return text


def relay_reply_record(row, *, tool_category, relay_author):
    """Whether a history row is a reply the relay itself recorded.

    Only the application's relay writes tool-category outcome records as the
    instance subject; a browser note can reuse neither its category nor, with
    it, its idempotency key, so user text cannot pose as an agent's reply.
    """
    return (type(row) is dict and row.get("category") == tool_category
            and row.get("author") == relay_author
            and str(row.get("idempotency_key") or "").startswith(RELAY_OUTCOME)
            and bool(row.get("refs")))


def artifact_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _reason(content):
    found = _REASON.findall(content)
    return found[-1] if found else None


def _relay_decision(content):
    if content.startswith("Session Link did not relay"):
        return "unavailable", _reason(content)
    if (content.startswith("Session Link started relaying this message to")
            or (content.startswith("Session Link relay of this message to") and " started. " in content)):
        return "started", None
    return "uncertain", "unrecognized relay decision"


def _relay_outcome(content):
    if content.startswith(RELAYED_REPLY):
        return "replied", None
    if content.startswith("The native recipient held or refused"):
        found = re.search(r"reported status: ([a-z]+)\)", content)
        return "unavailable", found.group(1) if found else "held"
    if content.startswith("Session Link did not relay"):
        return "unavailable", _reason(content)
    if content.startswith("Stopped waiting for a reply"):
        return "uncertain", "wait stopped"
    return "uncertain", _reason(content)


def _overall(rows):
    if not rows:
        return "stored"
    states = {row["state"] for row in rows}
    for state in _ORDER:
        if state in states:
            return state
    return "uncertain"


def project_delivery(messages, replies, *, relay_pending=frozenset(), note_category, tool_category,
                     relay_author):
    """Return (per-message state map, relayed-reply map) for a bounded page.

    ``replies`` are the visible direct replies to the page's messages, read by
    the history reply index, so outcomes newer than the page are included.
    """
    by_parent = {}
    for row in replies:
        by_parent.setdefault(row.get("reply_to"), []).append(row)
    states = {}
    relayed = {}
    for row in [*messages, *replies]:
        if row.get("category") != tool_category:
            continue
        text = relayed_reply_text(row.get("content"))
        if text is not None and relay_reply_record(row, tool_category=tool_category, relay_author=relay_author):
            relayed[row["id"]] = {"relayed_from": row["refs"][0], "agent_text": text,
                                  "artifact_digest": artifact_digest(text)}
    for message in messages:
        if message.get("category") != note_category:
            continue
        children = by_parent.get(message["id"], ())
        relay = {}
        broadcast = {}
        model = {}
        for child in children:
            if child.get("category") != tool_category:
                continue
            key = str(child.get("idempotency_key") or "")
            content = str(child.get("content") or "")
            recipient = (child.get("refs") or [None])[0]
            relay_row = child.get("author") == relay_author
            if key.startswith(RELAY_DECISION) and recipient and relay_row:
                entry = relay.setdefault(key[len(RELAY_DECISION):], {"recipient": recipient})
                state, reason = _relay_decision(content)
                entry.setdefault("decision", (state, reason, child))
            elif key.startswith(RELAY_OUTCOME) and recipient and relay_row:
                entry = relay.setdefault(key[len(RELAY_OUTCOME):], {"recipient": recipient})
                entry["outcome"] = _relay_outcome(content) + (child,)
            elif key.startswith(BROADCAST) and ":target:" in key:
                target = key.rsplit(":", 1)
                if target[1] == "outcome":
                    try:
                        value = json.loads(content)
                    except ValueError:
                        continue
                    if type(value) is dict and type(value.get("recipient")) is str:
                        broadcast.setdefault(target[0], {})["outcome"] = value
                elif target[1] == "started":
                    broadcast.setdefault(target[0], {})["started"] = child
            elif child.get("author") == message.get("author") and message.get("refs"):
                if key.endswith(":reply") and content.startswith("Model reply from "):
                    model["replied"] = child
                elif key.endswith(":failure"):
                    model["failure"] = child
                elif key.endswith(":started") and content.startswith("The agent request started."):
                    model["started"] = child
        rows = {}
        for digest, entry in relay.items():
            recipient = entry["recipient"]
            if "outcome" in entry:
                state, reason, child = entry["outcome"]
                row = {"recipient": recipient, "state": state, "via": "session-link"}
                if state == "replied" and child["id"] in relayed:
                    row["reply_message_id"] = child["id"]
                elif state == "replied":
                    reason = "the reply arrived but its text was not stored"
            elif "decision" in entry:
                state, reason, _child = entry["decision"]
                if state == "started" and digest not in relay_pending:
                    state, reason = "uncertain", "dispatched without a recorded outcome"
                row = {"recipient": recipient, "state": state, "via": "session-link"}
            else:
                continue
            if reason:
                row["reason"] = reason
            rows[recipient] = row
        for entry in broadcast.values():
            value = entry.get("outcome")
            if value is None:
                continue
            recipient = value["recipient"]
            if recipient in rows:
                continue
            mapped = {"replied": "replied", "started": "started", "not_sent": "unavailable",
                      "failed": "unavailable", "already_recorded": "uncertain"}.get(value.get("state"), "uncertain")
            if mapped == "started":
                # Broadcast relays are settled by the relay records above.
                mapped = "uncertain"
            row = {"recipient": recipient, "state": mapped, "via": "broadcast"}
            if type(value.get("reason")) is str:
                row["reason"] = value["reason"][:200]
            if mapped == "replied" and type(value.get("reply_message_id")) is str:
                row["reply_message_id"] = value["reply_message_id"]
            rows[recipient] = row
        for entry in broadcast.values():
            if "started" in entry and "outcome" not in entry:
                # Reserved, no outcome: the broadcast's own record says unknown.
                rows.setdefault("broadcast-target:" + entry["started"]["id"], {
                    "recipient": None, "state": "uncertain", "via": "broadcast",
                    "reason": "delivery attempt reserved without an outcome"})
        if model:
            recipient = message["refs"][0]
            if "replied" in model:
                rows[recipient] = {"recipient": recipient, "state": "replied", "via": "model",
                                   "reply_message_id": model["replied"]["id"]}
            elif "failure" in model:
                rows[recipient] = {"recipient": recipient, "state": "unavailable", "via": "model",
                                   "reason": "model reply unavailable"}
            elif "started" in model:
                rows[recipient] = {"recipient": recipient, "state": "uncertain", "via": "model",
                                   "reason": "request started without a recorded outcome"}
        delivery = sorted(rows.values(), key=lambda row: str(row["recipient"]))
        states[message["id"]] = {"state": _overall(delivery), "delivery": delivery}
    return states, relayed


def relay_pending_digests(owner):
    """Digests the owner's relay still holds queued or executing; nothing else."""
    relay = getattr(owner, "native_recipient_relay", None)
    if relay is None:
        return frozenset()
    with relay._channel_lock:
        return frozenset(relay._pending_jobs)


__all__ = ["STATES", "artifact_digest", "project_delivery", "relay_pending_digests",
           "relayed_reply_text"]
