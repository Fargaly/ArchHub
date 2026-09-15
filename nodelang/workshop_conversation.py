"""Disposable conversation projection of the admitted Workshop graph.

Reading this lens neither enrolls agents nor installs definitions. Message
history remains graph-owned; creation revisions are ordering, not delivery
cursors (a draft may be sent at a later revision).
"""
from __future__ import annotations
import heapq
from .cell_protocols import read_relation

from .unified_authority import (
    composition_root, published_definition_named, read_scope_level, read_instance_definition,
)
from .universal_cell import InvalidCell


def workshop_descriptors(authority, lens, *, caller):
    """Offer the existing Workshop only when its identity is on this canvas."""
    try:
        root = composition_root(authority, "Workshop", caller=caller)
    except InvalidCell as exc:
        if str(exc) != "application requires one composition with that label":
            raise
        return []
    visible = {node["root_id"] for node in lens["nodes"]}
    if root != lens["scope_root"] and root not in visible:
        return []
    return [{"root": root, "label": "Workshop"}]


def read_workshop_conversation(authority, root, *, caller, limit=100):
    """Read a bounded window, including late sends and revised message states."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise InvalidCell("Workshop conversation limit is invalid")
    if root != composition_root(authority, "Workshop", caller=caller):
        raise InvalidCell("Workshop conversation root is not admitted")
    revision = authority.store.revision
    definition = published_definition_named(
        authority, "Coordination message", caller=caller,
    )
    # Refuse an oversized projection rather than grow an unbounded poll.
    level = read_scope_level(authority, root, scope_root=root, caller=caller, budget=20_000)
    connections = {}
    for relation in level.relations.values():
        sources = [value for role, value in relation.participants if role == "source"]
        targets = [value for role, value in relation.participants if role == "target"]
        name = relation.properties.get("connection")
        if name not in {"sender", "recipient", "reply-to"}:
            continue
        if len(sources) != 1 or len(targets) != 1:
            raise InvalidCell("Workshop message connection is invalid")
        row = connections.setdefault(sources[0], {})
        if name in row:
            raise InvalidCell("Workshop message connection is duplicated")
        row[name] = targets[0]
    messages = []
    message_count = 0
    for message_root, instance in level.instances.items():
        if definition is None or instance.get("definition") != definition:
            continue
        values = instance.get("values", {})
        state = values.get("state")
        # A message is assembled across signed commits. Incomplete drafts
        # are not delivered messages and must not break the live transcript.
        if state in {"draft", "cancelled"}:
            continue
        ends = connections.get(message_root, {})
        if state not in {"sent", "read", "acted"} or not {"sender", "recipient"} <= ends.keys():
            raise InvalidCell("Workshop delivered message is incomplete")
        if any(type(values.get(key)) is not str for key in ("body", "category")):
            raise InvalidCell("Workshop message content is invalid")
        message = {
            "root": message_root, "sender_root": ends["sender"],
            "recipient_root": ends["recipient"], "reply_to_root": ends.get("reply-to"),
            "body": values["body"], "category": values["category"], "state": state,
            "created_revision": authority.store.cell_created_revision(message_root),
        }
        message_count += 1
        entry = (message["created_revision"], message_root, message)
        if len(messages) < limit:
            heapq.heappush(messages, entry)
        else:
            heapq.heappushpop(messages, entry)
    messages = [entry[2] for entry in sorted(messages)]
    participants = {row[key] for row in messages for key in ("sender_root", "recipient_root")}
    # Enrolled identities are compositions carrying a credential. Include
    # attached identities before they speak, without loading their credentials.
    for child in level.composition_roots:
        if child not in level.instances and any(
            member.role_id == authority.role("credential")
            for member in read_relation(authority.store.snapshot(), child, budget=4096)
        ):
            participants.add(child)
    execution_nodes = []
    definitions = {}
    for child, instance in level.instances.items():
        if instance.get("definition") == definition:
            continue
        key = (instance.get("definition"), instance.get("definition_revision"))
        contract = definitions.get(key)
        if contract is None:
            contract = read_instance_definition(authority, child, scope_root=root, caller=caller)
            definitions[key] = contract
        operation = contract.contracts["rules"].get("operation")
        if type(operation) is str and operation.strip():
            execution_nodes.append({"root":child, "label":instance.get("values", {}).get("label") or
                contract.contracts["presentation"].get("label") or operation, "operation":operation})
    if authority.store.revision != revision or level.revision != revision:
        raise InvalidCell("Workshop changed during the read; refresh to continue")
    return {
        "graph_id": authority.manifest.graph_id, "root": root, "revision": revision,
        "messages": messages, "has_older": message_count > limit,
        "execution_nodes": execution_nodes,
        "participants": [{"root": participant,
            "label": level.composition_labels.get(participant) or participant,
            "attached": participant in level.composition_roots,
        } for participant in sorted(participants)],
    }
