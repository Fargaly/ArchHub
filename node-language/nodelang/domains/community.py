"""Node-native Community and Federation domain.

The domain is an inspectable composition over the one node table. Community
records, memberships, consent, ownership, invitations, subscriptions,
provenance, reputation, moderation, federation, and every effect gate are
ordinary nodes joined by first-class relation nodes. External work remains a
frozen plan until an explicit approval and timestamped evidence are present.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..core import Store, relation_sources
from ..laws_relation import rewire_endpoint


SCOPE_LEVELS = {"USER": 0, "FIRM": 1, "COMMUNITY": 2, "GLOBAL": 3}

GRAND_MAP_CAPABILITIES = (
    "community_share_card",
    "community_tier_gate",
    "community_redaction_promote",
    "community_firm_outbox",
    "community_subscribe",
    "community_poller",
    "community_incoming_eval",
    "community_quarantine",
    "community_create_group",
    "community_join_code",
    "community_fanout_export",
    "community_fanout_apply",
    "community_marketplace",
    "community_watershed",
    "nl_comm_federation",
    "community_prov_ledger",
    "community_trust_egtrl",
    "community_fingerprint_match",
    "community_fair_propagation",
)

DEFAULT_MEMBERS = (
    {
        "id": "founder",
        "display_name": "Founder",
        "role": "owner",
        "role_rank": 3,
        "active": True,
        "consent_to_share": False,
        "joined_at": "",
    },
    {
        "id": "architect",
        "display_name": "Architect",
        "role": "member",
        "role_rank": 1,
        "active": True,
        "consent_to_share": False,
        "joined_at": "",
    },
)

DEFAULT_PEERS = (
    {
        "id": "peer-firm",
        "display_name": "Peer firm",
        "actor_url": "https://peer.example/actor",
        "health": "unknown",
        "health_observed_at": "",
        "health_evidence": "",
        "authorized": False,
        "authorization_observed_at": "",
        "authorization_evidence": "",
        "capability_ref": "op://archhub/community/peer-firm",
    },
)

DEFAULT_ARTIFACTS = (
    {
        "id": "shared-pattern",
        "title": "Shared pattern",
        "artifact_kind": "pattern",
        "owner": "founder",
        "scope": "COMMUNITY",
        "shareable": True,
        "approved": False,
        "aggregate_only": False,
        "pii_redacted": False,
        "secrets_stripped": True,
        "confidence": 0.8,
        "provenance_ref": "",
        "content_ref": "",
    },
)

DEFAULT_CONTRIBUTIONS = (
    {
        "id": "incoming-pattern",
        "title": "Incoming pattern",
        "peer": "peer-firm",
        "confidence": 0.0,
        "pii_redacted": False,
        "provenance_verified": False,
        "content_ref": "",
        "observed_at": "",
        "evidence": "",
    },
)

_SECRET_WORDS = (
    "password", "passwd", "secret", "credential", "api_key", "apikey",
    "access_token", "refresh_token", "private_key", "signing_key", "token",
)


def _identifier(value: Any, label: str) -> str:
    clean = str(value).strip()
    if not clean:
        raise ValueError("%s must be a non-empty string" % label)
    return clean


def _reject_raw_secrets(value: Any, path: str = "input") -> None:
    if isinstance(value, Mapping):
        for raw_name, item in value.items():
            name = str(raw_name).casefold().replace("-", "_")
            child = "%s.%s" % (path, raw_name)
            safety_assertion = name in {"secrets_stripped", "strip_secrets"} \
                and isinstance(item, bool)
            if not safety_assertion and any(word in name for word in _SECRET_WORDS):
                if not (name.endswith("_ref") and str(item).startswith("op://")):
                    raise ValueError(
                        "%s may contain a raw secret; use an op:// secret_ref" % child
                    )
            _reject_raw_secrets(item, child)
    elif isinstance(value, (list, tuple, set)):
        for index, item in enumerate(value):
            _reject_raw_secrets(item, "%s[%d]" % (path, index))


def _scope(value: Any) -> int:
    if isinstance(value, str):
        key = value.strip().upper()
        if key not in SCOPE_LEVELS:
            raise ValueError("scope must be one of %s" % ", ".join(SCOPE_LEVELS))
        return SCOPE_LEVELS[key]
    level = int(value)
    if level not in SCOPE_LEVELS.values():
        raise ValueError("scope must match the editable scope policy")
    return level


def _param(store: Store, title: str, value: Any, actor: str) -> str:
    return store.add("param", title, floor={"op": "value", "value": value}, actor=actor)


def _record_group(
    store: Store, title: str, values: Mapping[str, Any], actor: str
) -> tuple[str, str, dict[str, str]]:
    params = {name: _param(store, name, value, actor) for name, value in values.items()}
    record = store.add(
        "op", "%s record" % title,
        floor={"op": "merge", "fn": "record", "keys": list(params)}, actor=actor,
    )
    for name, param_id in params.items():
        store.wire(param_id, record, title="%s -> %s" % (name, title), actor=actor)
    group = store.add(
        "group", title, inner=list(params.values()) + [record], params=params, actor=actor
    )
    return group, record, params


def _field(
    store: Store, source: str, name: str, title: str, inner: list[str], actor: str
) -> str:
    node = store.add("op", title, floor={"op": "field", "path": name}, actor=actor)
    wire = store.wire(source, node, title="%s supplies %s" % (title, name), actor=actor)
    inner.extend([node, wire])
    return node


def _compare(
    store: Store, left: str, right: str, cmp: str, title: str,
    inner: list[str], actor: str,
) -> str:
    node = store.add("op", title, floor={"op": "compare", "cmp": cmp}, actor=actor)
    inner.extend([
        node,
        store.wire(left, node, title="%s / left" % title, actor=actor),
        store.wire(right, node, title="%s / right" % title, actor=actor),
    ])
    return node


def _all(
    store: Store, conditions: Iterable[str], title: str, inner: list[str], actor: str
) -> str:
    conditions = list(conditions)
    if not conditions:
        raise ValueError("a gate needs at least one condition")
    node = store.add("op", title, floor={"op": "math", "fn": "*"}, actor=actor)
    inner.append(node)
    for condition in conditions:
        inner.append(store.wire(condition, node, title="%s condition" % title, actor=actor))
    return node


def _any(
    store: Store, conditions: Iterable[str], title: str, inner: list[str], actor: str
) -> str:
    conditions = list(conditions)
    if not conditions:
        raise ValueError("an any gate needs at least one condition")
    total = store.add("op", "%s total" % title, floor={"op": "math", "fn": "+"}, actor=actor)
    zero = _param(store, "%s zero" % title, 0, actor)
    inner.extend([total, zero])
    for condition in conditions:
        inner.append(store.wire(condition, total, title="%s option" % title, actor=actor))
    return _compare(store, total, zero, ">", title, inner, actor)


def _relation(
    store: Store, source: str, target: str, title: str,
    source_port: str, target_port: str, actor: str, *, gate: str | None = None,
) -> str:
    stages = [{"node_id": gate, "mode": "guard", "role": "gate"}] if gate else None
    return store.relation([
        {"role": "source", "direction": "out", "node_id": source,
         "port_id": source_port, "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": target,
         "port_id": target_port, "cardinality": "one"},
    ], title=title, stages=stages, actor=actor)


def _source_endpoint(store: Store, relation_id: str) -> str:
    sources = relation_sources(store.nodes, store.nodes[relation_id])
    if len(sources) != 1:
        raise ValueError("relation %s must have exactly one source" % relation_id)
    return str(sources[0]["endpoint_param"])


def _frozen_effect(
    store: Store, title: str, target: str, change: Mapping[str, Any],
    gate: str, sink: str, actor: str,
) -> tuple[str, str]:
    effect = store.add(
        "op", title,
        floor={"op": "effect", "target": target, "change": dict(change)},
        frozen=True, actor=actor,
    )
    relation = _relation(
        store, effect, sink, "%s dispatch" % title, "plan", "external_effect",
        actor, gate=gate,
    )
    return effect, relation


def _member_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = {"id", "display_name", "role", "role_rank", "active",
                "consent_to_share", "joined_at"}
    if set(raw) != required:
        raise ValueError("member fields mismatch")
    return {
        "id": _identifier(raw["id"], "member id"),
        "display_name": str(raw["display_name"]),
        "role": _identifier(raw["role"], "member role"),
        "role_rank": int(raw["role_rank"]),
        "active": bool(raw["active"]),
        "consent_to_share": bool(raw["consent_to_share"]),
        "joined_at": str(raw["joined_at"]),
    }


def _peer_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "id", "display_name", "actor_url", "health", "health_observed_at",
        "health_evidence", "authorized", "authorization_observed_at",
        "authorization_evidence", "capability_ref",
    }
    if set(raw) != required:
        raise ValueError("peer fields mismatch")
    ref = _identifier(raw["capability_ref"], "peer capability reference")
    if not ref.startswith("op://"):
        raise ValueError("peer capability reference must start with op://")
    return {
        "id": _identifier(raw["id"], "peer id"),
        "display_name": str(raw["display_name"]),
        "actor_url": str(raw["actor_url"]),
        "health": str(raw["health"]).strip().casefold() or "unknown",
        "health_observed_at": str(raw["health_observed_at"]),
        "health_evidence": str(raw["health_evidence"]),
        "authorized": bool(raw["authorized"]),
        "authorization_observed_at": str(raw["authorization_observed_at"]),
        "authorization_evidence": str(raw["authorization_evidence"]),
        "capability_ref": ref,
    }


def build_community_domain(
    store: Store,
    *,
    members: Iterable[Mapping[str, Any]] = DEFAULT_MEMBERS,
    peers: Iterable[Mapping[str, Any]] = DEFAULT_PEERS,
    artifacts: Iterable[Mapping[str, Any]] = DEFAULT_ARTIFACTS,
    contributions: Iterable[Mapping[str, Any]] = DEFAULT_CONTRIBUTIONS,
    community: Mapping[str, Any] | None = None,
    actor: str = "community-domain",
) -> dict[str, Any]:
    """Build the complete Community/Federation authority in ``store``."""
    raw = {
        "members": [dict(item) for item in members],
        "peers": [dict(item) for item in peers],
        "artifacts": [dict(item) for item in artifacts],
        "contributions": [dict(item) for item in contributions],
        "community": dict(community or {}),
    }
    _reject_raw_secrets(raw)

    scope_policy, _, scope_params = _record_group(
        store, "Community scope policy", SCOPE_LEVELS, actor
    )
    policy_values = {
        "minimum_confidence": 0.6,
        "dp_epsilon": 1.0,
        "maximum_raw_scope": SCOPE_LEVELS["COMMUNITY"],
        "global_requires_aggregate": True,
        "minimum_inviter_rank": 2,
        "accept_threshold": 0.7,
        "quarantine_threshold": 0.4,
        "reputation_decay": 0.95,
        "quarantine_ttl_days": 14,
        "auto_release": False,
        "refuse_user_scope_fanout": True,
        "sync_idempotent": True,
        "fingerprint_match_threshold": 0.8,
        "fairness_minimum_share": 0.1,
    }
    policy, _, policy_params = _record_group(
        store, "Community governance policy", policy_values, actor
    )

    community_values = {
        "id": "primary-community",
        "name": "My Studio",
        "transport": "disk",
        "base_url": "",
        "owner": "founder",
        "created_at": "",
        "federation_status": "offline",
    }
    community_values.update(dict(community or {}))
    community_values["id"] = _identifier(community_values["id"], "community id")
    community_values["owner"] = _identifier(community_values["owner"], "community owner")
    community_group, community_record, community_params = _record_group(
        store, "Community: %s" % community_values["name"], community_values, actor
    )

    member_groups: dict[str, str] = {}
    member_records: dict[str, str] = {}
    member_params: dict[str, dict[str, str]] = {}
    memberships: dict[str, str] = {}
    for raw_member in raw["members"]:
        record = _member_record(raw_member)
        member_id = record["id"]
        if member_id in member_groups:
            raise ValueError("member ids must be unique")
        group, assembled, params = _record_group(
            store, "Community member: %s" % record["display_name"], record, actor
        )
        member_groups[member_id] = group
        member_records[member_id] = assembled
        member_params[member_id] = params
        memberships[member_id] = _relation(
            store, group, community_group, "Membership: %s" % member_id,
            "member", "members", actor,
        )
    if community_values["owner"] not in member_groups:
        raise ValueError("community owner must be a member")
    owner_relation = _relation(
        store, member_groups[community_values["owner"]], community_group,
        "Community ownership", "owner", "owned_community", actor,
    )

    external_sink, _, external_sink_params = _record_group(
        store, "External Community Boundary",
        {"state": "not connected", "observed_at": "", "evidence": ""}, actor,
    )

    peer_groups: dict[str, str] = {}
    peer_records: dict[str, str] = {}
    peer_params: dict[str, dict[str, str]] = {}
    peer_capabilities: dict[str, str] = {}
    subscriptions: dict[str, str] = {}
    reputation_groups: dict[str, str] = {}
    reputation_params: dict[str, dict[str, str]] = {}
    for raw_peer in raw["peers"]:
        record = _peer_record(raw_peer)
        peer_id = record.pop("id")
        capability_ref = record.pop("capability_ref")
        if peer_id in peer_groups:
            raise ValueError("peer ids must be unique")
        group, assembled, params = _record_group(
            store, "Federated peer: %s" % record["display_name"],
            {"id": peer_id, **record}, actor,
        )
        capability = store.add(
            "secret_ref", "Peer authorization capability: %s" % peer_id,
            floor={"op": "secret_ref", "ref": capability_ref}, actor=actor,
        )
        capability_param = store.add(
            "param", "capability_ref",
            floor={"op": "reference", "target": capability}, actor=actor,
        )
        group_params = dict(store.nodes[group]["params"])
        group_params["capability_ref"] = capability_param
        store.edit(group, ["params"], group_params, actor=actor)
        store.edit(group, ["body", "inner"],
                   store.nodes[group]["body"]["inner"] + [capability, capability_param],
                   actor=actor)
        peer_groups[peer_id] = group
        peer_records[peer_id] = assembled
        peer_params[peer_id] = params
        peer_capabilities[peer_id] = capability
        subscriptions[peer_id] = _relation(
            store, community_group, group, "Subscription: %s" % peer_id,
            "subscriber", "peer_outbox", actor,
        )
        reputation_group, _, rep_params = _record_group(
            store, "Reputation: %s" % peer_id,
            {"score": 0.0, "evidence": "", "observed_at": "",
             "decay": policy_values["reputation_decay"]}, actor,
        )
        reputation_groups[peer_id] = reputation_group
        reputation_params[peer_id] = rep_params
        _relation(
            store, group, reputation_group, "Peer reputation: %s" % peer_id,
            "subject", "reputation", actor,
        )

    artifact_groups: dict[str, str] = {}
    artifact_params: dict[str, dict[str, str]] = {}
    ownership_relations: dict[str, str] = {}
    share_membership_relations: dict[str, str] = {}
    share_gates: dict[str, str] = {}
    share_gate_groups: dict[str, str] = {}
    share_effects: dict[str, str] = {}
    share_dispatch_relations: dict[str, str] = {}
    provenance_groups: dict[str, str] = {}
    provenance_relations: dict[str, str] = {}
    for raw_artifact in raw["artifacts"]:
        required = {
            "id", "title", "artifact_kind", "owner", "scope", "shareable",
            "approved", "aggregate_only", "pii_redacted", "secrets_stripped",
            "confidence", "provenance_ref", "content_ref",
        }
        if set(raw_artifact) != required:
            raise ValueError("artifact fields mismatch")
        artifact_id = _identifier(raw_artifact["id"], "artifact id")
        owner_id = _identifier(raw_artifact["owner"], "artifact owner")
        if owner_id not in member_groups:
            raise ValueError("unknown artifact owner %r" % owner_id)
        values = dict(raw_artifact)
        values["scope"] = _scope(values["scope"])
        values["confidence"] = float(values["confidence"])
        artifact, _, params = _record_group(
            store, "Community artifact: %s" % values["title"], values, actor
        )
        artifact_groups[artifact_id] = artifact
        artifact_params[artifact_id] = params
        owner_wire = _relation(
            store, member_groups[owner_id], artifact,
            "Artifact ownership: %s" % artifact_id, "owner", "artifact", actor,
        )
        membership_wire = _relation(
            store, member_groups[owner_id], community_group,
            "Share membership proof: %s" % artifact_id,
            "member", "share_community", actor,
        )
        ownership_relations[artifact_id] = owner_wire
        share_membership_relations[artifact_id] = membership_wire

        gate_inner: list[str] = []
        owner_id_field = _field(store, owner_wire, "id", "Share owner id", gate_inner, actor)
        member_id_field = _field(
            store, membership_wire, "id", "Share member id", gate_inner, actor
        )
        owner_consent = _field(
            store, owner_wire, "consent_to_share", "Owner consent", gate_inner, actor
        )
        member_active = _field(
            store, membership_wire, "active", "Membership active", gate_inner, actor
        )
        owner_match = _compare(
            store, owner_id_field, member_id_field, "==", "Owner is wired member",
            gate_inner, actor,
        )
        raw_scope_allowed = _compare(
            store, params["scope"], policy_params["maximum_raw_scope"], "<=",
            "Artifact scope allowed", gate_inner, actor,
        )
        global_scope = _compare(
            store, params["scope"], scope_params["GLOBAL"], "==",
            "Artifact uses global scope", gate_inner, actor,
        )
        positive_dp = _compare(
            store, policy_params["dp_epsilon"], _param(store, "zero epsilon", 0, actor),
            ">", "Differential privacy configured", gate_inner, actor,
        )
        global_aggregate_allowed = _all(
            store, [global_scope, params["aggregate_only"],
                    policy_params["global_requires_aggregate"], positive_dp],
            "Global aggregate route allowed", gate_inner, actor,
        )
        scope_allowed = _any(
            store, [raw_scope_allowed, global_aggregate_allowed],
            "Community scope route allowed", gate_inner, actor,
        )
        confidence_ok = _compare(
            store, params["confidence"], policy_params["minimum_confidence"], ">=",
            "Artifact confidence allowed", gate_inner, actor,
        )
        gate = _all(
            store,
            [owner_consent, member_active, owner_match, params["shareable"],
             params["approved"], params["pii_redacted"],
             params["secrets_stripped"], scope_allowed, confidence_ok],
            "Community share decision", gate_inner, actor,
        )
        gate_group = store.add(
            "group", "Share gate: %s" % artifact_id,
            inner=gate_inner, params={
                "minimum_confidence": policy_params["minimum_confidence"],
                "maximum_raw_scope": policy_params["maximum_raw_scope"],
            }, actor=actor,
        )
        share_gates[artifact_id] = gate
        share_gate_groups[artifact_id] = gate_group
        effect, dispatch = _frozen_effect(
            store, "Publish artifact: %s" % artifact_id,
            "community-outbox:%s" % artifact_id,
            {"artifact_id": artifact_id, "action": "publish",
             "scope": values["scope"], "content_ref": values["content_ref"]},
            gate, external_sink, actor,
        )
        share_effects[artifact_id] = effect
        share_dispatch_relations[artifact_id] = dispatch
        provenance, _, provenance_params = _record_group(
            store, "Provenance: %s" % artifact_id,
            {"was_attributed_to": owner_id,
             "was_derived_from": values["provenance_ref"],
             "was_generated_by": "community_share_card",
             "evidence": "", "recorded_at": ""}, actor,
        )
        provenance_groups[artifact_id] = provenance
        for param_id in provenance_params.values():
            store.apply_op({"op": "freeze", "id": param_id, "actor": actor})
        provenance_relations[artifact_id] = _relation(
            store, artifact, provenance, "Artifact provenance: %s" % artifact_id,
            "entity", "provenance_record", actor,
        )

    invite_values = {
        "id": "default-invitation",
        "role": "member",
        "ttl_hours": 72,
        "approved": False,
        "approved_by": "",
        "approved_at": "",
        "signature_evidence": "",
        "idempotency_key": "",
    }
    invitation, _, invitation_params = _record_group(
        store, "Community invitation", invite_values, actor
    )
    invite_capability = store.add(
        "secret_ref", "Invitation signing capability",
        floor={"op": "secret_ref", "ref": "op://archhub/community/invite-signing"},
        actor=actor,
    )
    inviter_id = community_values["owner"]
    inviter_relation = _relation(
        store, member_groups[inviter_id], invitation, "Invitation issuer",
        "issuer", "invitation", actor,
    )
    inviter_membership = _relation(
        store, member_groups[inviter_id], community_group, "Inviter membership proof",
        "member", "invite_community", actor,
    )
    invite_inner: list[str] = []
    inviter_rank = _field(store, inviter_relation, "role_rank", "Inviter rank", invite_inner, actor)
    inviter_active = _field(store, inviter_membership, "active", "Inviter active", invite_inner, actor)
    inviter_consent = _field(
        store, inviter_relation, "consent_to_share", "Inviter consent", invite_inner, actor
    )
    inviter_id_field = _field(
        store, inviter_relation, "id", "Invitation issuer id", invite_inner, actor
    )
    member_id_field = _field(
        store, inviter_membership, "id", "Inviter membership id", invite_inner, actor
    )
    inviter_matches_membership = _compare(
        store, inviter_id_field, member_id_field, "==",
        "Invitation issuer is wired member", invite_inner, actor,
    )
    rank_ok = _compare(
        store, inviter_rank, policy_params["minimum_inviter_rank"], ">=",
        "Inviter rank allowed", invite_inner, actor,
    )
    empty = _param(store, "empty", "", actor)
    evidence_ok = _compare(
        store, invitation_params["signature_evidence"], empty, "!=",
        "Invitation signature evidence exists", invite_inner, actor,
    )
    key_ok = _compare(
        store, invitation_params["idempotency_key"], empty, "!=",
        "Invitation idempotency key exists", invite_inner, actor,
    )
    approved_by_ok = _compare(
        store, invitation_params["approved_by"], empty, "!=",
        "Invitation approver exists", invite_inner, actor,
    )
    approved_at_ok = _compare(
        store, invitation_params["approved_at"], empty, "!=",
        "Invitation approval timestamp exists", invite_inner, actor,
    )
    invite_gate = _all(
        store, [inviter_active, inviter_consent, inviter_matches_membership, rank_ok,
                invitation_params["approved"], approved_by_ok, approved_at_ok,
                evidence_ok, key_ok],
        "Invitation permission", invite_inner, actor,
    )
    invite_gate_group = store.add(
        "group", "Invitation gate", inner=invite_inner,
        params={"minimum_inviter_rank": policy_params["minimum_inviter_rank"]},
        actor=actor,
    )
    invite_effect, invite_dispatch = _frozen_effect(
        store, "Issue signed invitation", "community-invitation",
        {"invitation_id": invite_values["id"], "action": "issue_join_code",
         "capability_ref": "op://archhub/community/invite-signing"},
        invite_gate, external_sink, actor,
    )
    join_request, _, join_request_params = _record_group(
        store, "Community join request",
        {"member_id": "", "invite_verified": False, "consent": False,
         "approved": False, "approved_by": "", "approved_at": "",
         "verification_evidence": "", "idempotency_key": ""}, actor,
    )
    join_inner: list[str] = []
    join_empty = _param(store, "empty", "", actor)
    join_checks = [join_request_params["invite_verified"],
                   join_request_params["consent"], join_request_params["approved"]]
    for name in ("member_id", "approved_by", "approved_at",
                 "verification_evidence", "idempotency_key"):
        join_checks.append(_compare(
            store, join_request_params[name], join_empty, "!=",
            "Join %s exists" % name, join_inner, actor,
        ))
    join_gate = _all(
        store, join_checks, "Community join permission", join_inner, actor
    )
    join_gate_group = store.add(
        "group", "Community join gate", inner=join_inner, actor=actor
    )
    join_effect, join_dispatch = _frozen_effect(
        store, "Apply community membership", "community-membership",
        {"action": "join", "community_id": community_values["id"]},
        join_gate, external_sink, actor,
    )

    contribution_groups: dict[str, str] = {}
    contribution_params: dict[str, dict[str, str]] = {}
    contributor_relations: dict[str, str] = {}
    moderation_gates: dict[str, dict[str, str]] = {}
    moderation_groups: dict[str, str] = {}
    moderation_effects: dict[str, str] = {}
    moderation_dispatch_relations: dict[str, str] = {}
    quarantine_records: dict[str, str] = {}
    for raw_contribution in raw["contributions"]:
        required = {"id", "title", "peer", "confidence", "pii_redacted",
                    "provenance_verified", "content_ref", "observed_at", "evidence"}
        if set(raw_contribution) != required:
            raise ValueError("contribution fields mismatch")
        contribution_id = _identifier(raw_contribution["id"], "contribution id")
        peer_id = _identifier(raw_contribution["peer"], "contribution peer")
        if peer_id not in peer_groups:
            raise ValueError("unknown contribution peer %r" % peer_id)
        contribution, _, params = _record_group(
            store, "Incoming contribution: %s" % raw_contribution["title"],
            {**raw_contribution, "confidence": float(raw_contribution["confidence"])},
            actor,
        )
        contribution_groups[contribution_id] = contribution
        contribution_params[contribution_id] = params
        contributor = _relation(
            store, reputation_groups[peer_id], contribution,
            "Contributor reputation: %s" % contribution_id,
            "reputation", "incoming_contribution", actor,
        )
        contributor_relations[contribution_id] = contributor
        moderation_inner: list[str] = []
        reputation = _field(
            store, contributor, "score", "Observed contributor reputation",
            moderation_inner, actor,
        )
        score = store.add(
            "op", "Incoming trust score", floor={"op": "math", "fn": "avg"}, actor=actor
        )
        moderation_inner.extend([
            score,
            store.wire(reputation, score, title="Reputation -> trust score", actor=actor),
            store.wire(params["confidence"], score, title="Confidence -> trust score", actor=actor),
        ])
        accept_score = _compare(
            store, score, policy_params["accept_threshold"], ">=",
            "Accept threshold reached", moderation_inner, actor,
        )
        quarantine_score = _compare(
            store, score, policy_params["quarantine_threshold"], ">=",
            "Quarantine threshold reached", moderation_inner, actor,
        )
        accept = _all(
            store, [accept_score, params["pii_redacted"],
                    params["provenance_verified"]],
            "Incoming contribution accepted", moderation_inner, actor,
        )
        moderation = store.add(
            "group", "Moderation: %s" % contribution_id,
            inner=moderation_inner, params={
                "accept_threshold": policy_params["accept_threshold"],
                "quarantine_threshold": policy_params["quarantine_threshold"],
            }, actor=actor,
        )
        moderation_groups[contribution_id] = moderation
        moderation_gates[contribution_id] = {
            "accept": accept, "quarantine": quarantine_score, "score": score,
        }
        quarantine, _, _ = _record_group(
            store, "Quarantine record: %s" % contribution_id,
            {"status": "pending", "ttl_days": policy_values["quarantine_ttl_days"],
             "auto_release": policy_values["auto_release"], "decision_evidence": ""},
            actor,
        )
        quarantine_records[contribution_id] = quarantine
        _relation(
            store, contribution, quarantine,
            "Contribution quarantine path: %s" % contribution_id,
            "candidate", "quarantine", actor, gate=quarantine_score,
        )
        effect, dispatch = _frozen_effect(
            store, "Import accepted contribution: %s" % contribution_id,
            "community-import:%s" % contribution_id,
            {"contribution_id": contribution_id, "action": "import",
             "content_ref": str(raw_contribution["content_ref"])},
            accept, external_sink, actor,
        )
        moderation_effects[contribution_id] = effect
        moderation_dispatch_relations[contribution_id] = dispatch

    federation_values = {
        "direction": "bidirectional",
        "merge": "lww_by_hlc",
        "carry_hlc": True,
        "refuse_user_scope": True,
        "export_scopes": ["FIRM", "COMMUNITY"],
        "limit": 10000,
        "approved": False,
        "approved_by": "",
        "approved_at": "",
        "idempotency_key": "",
        "sync_evidence": "",
        "sync_observed_at": "",
    }
    federation, _, federation_params = _record_group(
        store, "Federation and fanout", federation_values, actor
    )
    federation_relations: dict[str, str] = {}
    sync_gates: dict[str, str] = {}
    sync_gate_groups: dict[str, str] = {}
    sync_effects: dict[str, dict[str, str]] = {}
    sync_dispatch_relations: dict[str, dict[str, str]] = {}
    for peer_id, peer in peer_groups.items():
        federation_relations[peer_id] = _relation(
            store, peer, federation, "Federation peer: %s" % peer_id,
            "peer", "federation", actor,
        )
        sync_inner: list[str] = []
        healthy = _field(
            store, federation_relations[peer_id], "health", "Peer health", sync_inner, actor
        )
        authorized = _field(
            store, federation_relations[peer_id], "authorized", "Peer authorization",
            sync_inner, actor,
        )
        health_evidence = _field(
            store, federation_relations[peer_id], "health_evidence",
            "Peer health evidence", sync_inner, actor,
        )
        auth_evidence = _field(
            store, federation_relations[peer_id], "authorization_evidence",
            "Peer authorization evidence", sync_inner, actor,
        )
        online = _param(store, "online", "online", actor)
        empty_sync = _param(store, "empty", "", actor)
        healthy_ok = _compare(
            store, healthy, online, "==", "Peer observed online", sync_inner, actor
        )
        health_evidence_ok = _compare(
            store, health_evidence, empty_sync, "!=", "Health evidence exists",
            sync_inner, actor,
        )
        health_observed_at = _field(
            store, federation_relations[peer_id], "health_observed_at",
            "Peer health observation timestamp", sync_inner, actor,
        )
        auth_observed_at = _field(
            store, federation_relations[peer_id], "authorization_observed_at",
            "Peer authorization observation timestamp", sync_inner, actor,
        )
        auth_evidence_ok = _compare(
            store, auth_evidence, empty_sync, "!=", "Authorization evidence exists",
            sync_inner, actor,
        )
        health_observed_ok = _compare(
            store, health_observed_at, empty_sync, "!=",
            "Health observation timestamp exists", sync_inner, actor,
        )
        auth_observed_ok = _compare(
            store, auth_observed_at, empty_sync, "!=",
            "Authorization observation timestamp exists", sync_inner, actor,
        )
        sync_observed_ok = _compare(
            store, federation_params["sync_observed_at"], empty_sync, "!=",
            "Sync observation timestamp exists", sync_inner, actor,
        )
        sync_evidence_ok = _compare(
            store, federation_params["sync_evidence"], empty_sync, "!=",
            "Sync evidence exists", sync_inner, actor,
        )
        idempotency_ok = _compare(
            store, federation_params["idempotency_key"], empty_sync, "!=",
            "Sync idempotency key exists", sync_inner, actor,
        )
        gate = _all(
            store, [healthy_ok, authorized, health_evidence_ok, auth_evidence_ok,
                    health_observed_ok, auth_observed_ok,
                    federation_params["approved"], sync_observed_ok,
                    sync_evidence_ok, idempotency_ok,
                    policy_params["refuse_user_scope_fanout"],
                    policy_params["sync_idempotent"]],
            "Federation sync permission", sync_inner, actor,
        )
        sync_gates[peer_id] = gate
        sync_gate_groups[peer_id] = store.add(
            "group", "Federation gate: %s" % peer_id, inner=sync_inner, actor=actor
        )
        export_effect, export_dispatch = _frozen_effect(
            store, "Fanout export: %s" % peer_id, "community-export:%s" % peer_id,
            {"peer": peer_id, "action": "export", "scopes": ["FIRM", "COMMUNITY"],
             "merge": "lww_by_hlc"}, gate, external_sink, actor,
        )
        apply_effect, apply_dispatch = _frozen_effect(
            store, "Fanout apply: %s" % peer_id, "community-apply:%s" % peer_id,
            {"peer": peer_id, "action": "apply", "merge": "lww_by_hlc",
             "refuse_user_scope": True}, gate, external_sink, actor,
        )
        poll_effect, poll_dispatch = _frozen_effect(
            store, "Poll peer outbox: %s" % peer_id, "community-poll:%s" % peer_id,
            {"peer": peer_id, "action": "poll", "interval_sec": 900,
             "max_per_tick": 50}, gate, external_sink, actor,
        )
        sync_effects[peer_id] = {
            "export": export_effect, "apply": apply_effect, "poll": poll_effect,
        }
        sync_dispatch_relations[peer_id] = {
            "export": export_dispatch, "apply": apply_dispatch, "poll": poll_dispatch,
        }

    marketplace, _, marketplace_params = _record_group(
        store, "Community marketplace",
        {"price_model": "free", "install_target": "library", "rating": 0.0,
         "downloads": 0, "approved": False, "evidence": ""}, actor,
    )
    listing_relations = {
        artifact_id: _relation(
            store, artifact, marketplace, "Marketplace listing: %s" % artifact_id,
            "listed_artifact", "marketplace", actor, gate=share_gates[artifact_id],
        ) for artifact_id, artifact in artifact_groups.items()
    }
    marketplace_inner: list[str] = []
    marketplace_empty = _param(store, "empty", "", actor)
    marketplace_evidence_ok = _compare(
        store, marketplace_params["evidence"], marketplace_empty, "!=",
        "Marketplace evidence exists", marketplace_inner, actor,
    )
    marketplace_effects: dict[str, str] = {}
    marketplace_dispatch_relations: dict[str, str] = {}
    for artifact_id in artifact_groups:
        gate = _all(
            store, [share_gates[artifact_id], marketplace_params["approved"],
                    marketplace_evidence_ok],
            "Marketplace install permission: %s" % artifact_id,
            marketplace_inner, actor,
        )
        effect, dispatch = _frozen_effect(
            store, "Install marketplace artifact: %s" % artifact_id,
            "community-library:%s" % artifact_id,
            {"action": "install", "artifact_id": artifact_id,
             "target": "library"}, gate, external_sink, actor,
        )
        marketplace_effects[artifact_id] = effect
        marketplace_dispatch_relations[artifact_id] = dispatch
    marketplace_gate_group = store.add(
        "group", "Marketplace installation gates", inner=marketplace_inner, actor=actor
    )
    fingerprint, _, fingerprint_params = _record_group(
        store, "Private peer matching",
        {"fingerprint_ref": "", "method": "svd", "similarity": 0.0,
         "evidence": "", "approved": False}, actor,
    )
    fingerprint_gate_inner: list[str] = []
    fingerprint_score_ok = _compare(
        store, fingerprint_params["similarity"],
        policy_params["fingerprint_match_threshold"], ">=",
        "Private peer match threshold", fingerprint_gate_inner, actor,
    )
    fingerprint_empty = _param(store, "empty", "", actor)
    fingerprint_ref_ok = _compare(
        store, fingerprint_params["fingerprint_ref"], fingerprint_empty, "!=",
        "Fingerprint reference exists", fingerprint_gate_inner, actor,
    )
    fingerprint_evidence_ok = _compare(
        store, fingerprint_params["evidence"], fingerprint_empty, "!=",
        "Fingerprint evidence exists", fingerprint_gate_inner, actor,
    )
    fingerprint_gate = _all(
        store, [fingerprint_score_ok, fingerprint_ref_ok,
                fingerprint_evidence_ok, fingerprint_params["approved"]],
        "Private peer match permission", fingerprint_gate_inner, actor,
    )
    fingerprint_group = store.add(
        "group", "Private peer match decision", inner=fingerprint_gate_inner, actor=actor
    )
    fairness, _, fairness_params = _record_group(
        store, "Fair propagation",
        {"group_weight": 1.0, "candidate_quality": 0.0,
         "minimum_share": policy_values["fairness_minimum_share"],
         "evidence": "", "approved": False}, actor,
    )
    fairness_score = store.add(
        "op", "Fair propagation score", floor={"op": "math", "fn": "*"}, actor=actor
    )
    store.wire(fairness_params["group_weight"], fairness_score, actor=actor)
    store.wire(fairness_params["candidate_quality"], fairness_score, actor=actor)
    fairness_gate_inner: list[str] = [fairness_score]
    fairness_empty = _param(store, "empty", "", actor)
    fairness_score_ok = _compare(
        store, fairness_score, fairness_params["minimum_share"], ">=",
        "Fair propagation threshold", fairness_gate_inner, actor,
    )
    fairness_evidence_ok = _compare(
        store, fairness_params["evidence"], fairness_empty, "!=",
        "Fairness evidence exists", fairness_gate_inner, actor,
    )
    fairness_gate = _all(
        store, [fairness_score_ok, fairness_evidence_ok, fairness_params["approved"]],
        "Fair propagation permission", fairness_gate_inner, actor,
    )
    fairness_group = store.add(
        "group", "Fair propagation decision", inner=fairness_gate_inner, actor=actor
    )
    fairness_effect, fairness_dispatch = _frozen_effect(
        store, "Promote fairly selected knowledge", "community-fair-propagation",
        {"action": "promote", "selection": "fairness-constrained"},
        fairness_gate, external_sink, actor,
    )

    capability_nodes = {
        "community_share_card": store.add(
            "group", "Share to Community", inner=list(share_gate_groups.values()) +
            list(share_effects.values()), actor=actor),
        "community_tier_gate": scope_policy,
        "community_redaction_promote": policy,
        "community_firm_outbox": store.add(
            "group", "Firm outbox", inner=list(share_dispatch_relations.values()), actor=actor),
        "community_subscribe": store.add(
            "group", "Peer subscriptions", inner=list(subscriptions.values()), actor=actor),
        "community_poller": store.add(
            "group", "Community poller",
            inner=[effects["poll"] for effects in sync_effects.values()] +
            [relations["poll"] for relations in sync_dispatch_relations.values()] +
            list(sync_gate_groups.values()), actor=actor),
        "community_incoming_eval": store.add(
            "group", "Incoming pattern judge", inner=list(moderation_groups.values()), actor=actor),
        "community_quarantine": store.add(
            "group", "Quarantine buffer", inner=list(quarantine_records.values()), actor=actor),
        "community_create_group": community_group,
        "community_join_code": store.add(
            "group", "Join-code issue and verify",
            inner=[invitation, invite_capability, invite_gate_group, invite_effect,
                   join_request, join_gate_group, join_effect], actor=actor),
        "community_fanout_export": store.add(
            "group", "Fanout export",
            inner=[effects["export"] for effects in sync_effects.values()] +
            [relations["export"] for relations in sync_dispatch_relations.values()] +
            list(sync_gate_groups.values()), actor=actor),
        "community_fanout_apply": store.add(
            "group", "Fanout apply",
            inner=[effects["apply"] for effects in sync_effects.values()] +
            [relations["apply"] for relations in sync_dispatch_relations.values()] +
            list(sync_gate_groups.values()), actor=actor),
        "community_marketplace": store.add(
            "group", "Community marketplace capability",
            inner=[marketplace, marketplace_gate_group] +
            list(listing_relations.values()) + list(marketplace_effects.values()) +
            list(marketplace_dispatch_relations.values()), actor=actor),
        "community_watershed": federation,
        "nl_comm_federation": store.add(
            "group", "Federation across users",
            inner=list(federation_relations.values()) + list(sync_gate_groups.values()), actor=actor),
        "community_prov_ledger": store.add(
            "group", "Provenance ledger", inner=list(provenance_groups.values()), actor=actor),
        "community_trust_egtrl": store.add(
            "group", "Decentralized trust", inner=list(reputation_groups.values()), actor=actor),
        "community_fingerprint_match": store.add(
            "group", "Private peer matching capability",
            inner=[fingerprint, fingerprint_group], actor=actor),
        "community_fair_propagation": store.add(
            "group", "Fairness-constrained promotion",
            inner=[fairness, fairness_group, fairness_effect], actor=actor),
    }
    if set(capability_nodes) != set(GRAND_MAP_CAPABILITIES):
        raise AssertionError("Community Grand Map capability coverage drifted")

    domain_session = store.add(
        "session", "Community and Federation Domain",
        inner=list(capability_nodes.values()) + [
            scope_policy, policy, community_group, owner_relation,
            *member_groups.values(), *memberships.values(),
            *peer_groups.values(), *peer_capabilities.values(),
            *artifact_groups.values(), *ownership_relations.values(),
            *contribution_groups.values(), *contributor_relations.values(),
            external_sink,
        ], actor=actor,
    )
    return {
        "session": domain_session,
        "authority": "Grand Map / community",
        "capabilities": capability_nodes,
        "scope_policy": scope_policy,
        "scope_params": scope_params,
        "policy": policy,
        "policy_params": policy_params,
        "community": community_group,
        "community_record": community_record,
        "community_params": community_params,
        "members": member_groups,
        "member_records": member_records,
        "member_params": member_params,
        "memberships": memberships,
        "owner_relation": owner_relation,
        "peers": peer_groups,
        "peer_records": peer_records,
        "peer_params": peer_params,
        "peer_capabilities": peer_capabilities,
        "subscriptions": subscriptions,
        "reputations": reputation_groups,
        "reputation_params": reputation_params,
        "artifacts": artifact_groups,
        "artifact_params": artifact_params,
        "ownership_relations": ownership_relations,
        "share_membership_relations": share_membership_relations,
        "share_gates": share_gates,
        "share_gate_groups": share_gate_groups,
        "share_effects": share_effects,
        "share_dispatch_relations": share_dispatch_relations,
        "provenance": provenance_groups,
        "provenance_relations": provenance_relations,
        "invitation": invitation,
        "invitation_params": invitation_params,
        "invite_capability": invite_capability,
        "inviter_relation": inviter_relation,
        "inviter_membership": inviter_membership,
        "invite_gate": invite_gate,
        "invite_gate_group": invite_gate_group,
        "invite_effect": invite_effect,
        "invite_dispatch": invite_dispatch,
        "join_request": join_request,
        "join_request_params": join_request_params,
        "join_gate": join_gate,
        "join_gate_group": join_gate_group,
        "join_effect": join_effect,
        "join_dispatch": join_dispatch,
        "contributions": contribution_groups,
        "contribution_params": contribution_params,
        "contributor_relations": contributor_relations,
        "moderation_gates": moderation_gates,
        "moderation_groups": moderation_groups,
        "moderation_effects": moderation_effects,
        "moderation_dispatch_relations": moderation_dispatch_relations,
        "quarantine": quarantine_records,
        "federation": federation,
        "federation_params": federation_params,
        "federation_relations": federation_relations,
        "sync_gates": sync_gates,
        "sync_gate_groups": sync_gate_groups,
        "sync_effects": sync_effects,
        "sync_dispatch_relations": sync_dispatch_relations,
        "marketplace": marketplace,
        "marketplace_params": marketplace_params,
        "listing_relations": listing_relations,
        "marketplace_gate_group": marketplace_gate_group,
        "marketplace_effects": marketplace_effects,
        "marketplace_dispatch_relations": marketplace_dispatch_relations,
        "fingerprint": fingerprint,
        "fingerprint_params": fingerprint_params,
        "fingerprint_gate": fingerprint_gate,
        "fairness": fairness,
        "fairness_params": fairness_params,
        "fairness_score": fairness_score,
        "fairness_gate": fairness_gate,
        "fairness_effect": fairness_effect,
        "fairness_dispatch": fairness_dispatch,
        "external_sink": external_sink,
        "external_sink_params": external_sink_params,
    }


def set_member_parameter(
    store: Store, domain: Mapping[str, Any], member_id: str, name: str, value: Any,
    *, actor: str = "community-domain",
) -> str:
    params = domain["member_params"][member_id]
    if name not in params:
        raise KeyError("unknown member parameter %r" % name)
    if name in ("active", "consent_to_share"):
        value = bool(value)
    if name in ("role_rank",):
        value = int(value)
    return store.edit(str(params[name]), ["body", "floor", "value"], value, actor=actor)


def set_artifact_parameter(
    store: Store, domain: Mapping[str, Any], artifact_id: str, name: str, value: Any,
    *, actor: str = "community-domain",
) -> str:
    params = domain["artifact_params"][artifact_id]
    if name not in params:
        raise KeyError("unknown artifact parameter %r" % name)
    if name == "scope":
        value = _scope(value)
    elif name == "confidence":
        value = float(value)
    elif name in {"shareable", "approved", "aggregate_only", "pii_redacted",
                  "secrets_stripped"}:
        value = bool(value)
    return store.edit(str(params[name]), ["body", "floor", "value"], value, actor=actor)


def set_peer_evidence(
    store: Store, domain: Mapping[str, Any], peer_id: str, *, health: str,
    health_observed_at: str, health_evidence: str, authorized: bool,
    authorization_observed_at: str, authorization_evidence: str,
    actor: str = "community-domain",
) -> None:
    if health not in {"online", "offline", "unknown"}:
        raise ValueError("health must be online, offline, or unknown")
    if health != "unknown" and (not health_observed_at or not health_evidence):
        raise ValueError("observed health needs timestamped evidence")
    if authorized and (not authorization_observed_at or not authorization_evidence):
        raise ValueError("authorization needs timestamped evidence")
    params = domain["peer_params"][peer_id]
    values = {
        "health": health,
        "health_observed_at": health_observed_at,
        "health_evidence": health_evidence,
        "authorized": bool(authorized),
        "authorization_observed_at": authorization_observed_at,
        "authorization_evidence": authorization_evidence,
    }
    for name, value in values.items():
        store.edit(str(params[name]), ["body", "floor", "value"], value, actor=actor)


def set_reputation(
    store: Store, domain: Mapping[str, Any], peer_id: str, score: float,
    *, observed_at: str, evidence: str, actor: str = "community-domain",
) -> None:
    score = float(score)
    if not 0.0 <= score <= 1.0:
        raise ValueError("reputation score must be between 0 and 1")
    if not observed_at or not evidence:
        raise ValueError("reputation needs timestamped evidence")
    params = domain["reputation_params"][peer_id]
    for name, value in (("score", score), ("observed_at", observed_at),
                        ("evidence", evidence)):
        store.edit(str(params[name]), ["body", "floor", "value"], value, actor=actor)


def rewire_membership(
    store: Store, domain: Mapping[str, Any], membership_owner: str, member_id: str,
    *, actor: str = "community-domain",
) -> str:
    if member_id not in domain["members"]:
        raise KeyError("unknown member %r" % member_id)
    relation_id = str(domain["memberships"][membership_owner])
    return rewire_endpoint(
        store, relation_id, _source_endpoint(store, relation_id),
        node_id=str(domain["members"][member_id]), actor=actor,
    )


def rewire_artifact_owner(
    store: Store, domain: Mapping[str, Any], artifact_id: str, member_id: str,
    *, actor: str = "community-domain",
) -> str:
    if member_id not in domain["members"]:
        raise KeyError("unknown member %r" % member_id)
    relation_id = str(domain["ownership_relations"][artifact_id])
    return rewire_endpoint(
        store, relation_id, _source_endpoint(store, relation_id),
        node_id=str(domain["members"][member_id]), actor=actor,
    )


def rewire_share_membership(
    store: Store, domain: Mapping[str, Any], artifact_id: str, member_id: str,
    *, actor: str = "community-domain",
) -> str:
    if member_id not in domain["members"]:
        raise KeyError("unknown member %r" % member_id)
    relation_id = str(domain["share_membership_relations"][artifact_id])
    return rewire_endpoint(
        store, relation_id, _source_endpoint(store, relation_id),
        node_id=str(domain["members"][member_id]), actor=actor,
    )


def rewire_subscription(
    store: Store, domain: Mapping[str, Any], subscription_id: str, peer_id: str,
    *, actor: str = "community-domain",
) -> str:
    if peer_id not in domain["peers"]:
        raise KeyError("unknown peer %r" % peer_id)
    relation_id = str(domain["subscriptions"][subscription_id])
    targets = [item for item in store.endpoints(relation_id)
               if item.get("role") == "target"]
    if len(targets) != 1:
        raise ValueError("subscription needs exactly one target")
    return rewire_endpoint(
        store, relation_id, str(targets[0]["endpoint_param"]),
        node_id=str(domain["peers"][peer_id]), actor=actor,
    )


def share_allowed(store: Store, domain: Mapping[str, Any], artifact_id: str) -> bool:
    return bool(store.pull(str(domain["share_gates"][artifact_id])))


def invitation_allowed(store: Store, domain: Mapping[str, Any]) -> bool:
    return bool(store.pull(str(domain["invite_gate"])))


def sync_allowed(store: Store, domain: Mapping[str, Any], peer_id: str) -> bool:
    return bool(store.pull(str(domain["sync_gates"][peer_id])))


def moderation_decision(
    store: Store, domain: Mapping[str, Any], contribution_id: str
) -> str:
    gates = domain["moderation_gates"][contribution_id]
    if bool(store.pull(str(gates["accept"]))):
        return "accept"
    if bool(store.pull(str(gates["quarantine"]))):
        return "quarantine"
    return "reject"


__all__ = [
    "SCOPE_LEVELS", "GRAND_MAP_CAPABILITIES", "DEFAULT_MEMBERS",
    "DEFAULT_PEERS", "DEFAULT_ARTIFACTS", "DEFAULT_CONTRIBUTIONS",
    "build_community_domain", "set_member_parameter", "set_artifact_parameter",
    "set_peer_evidence", "set_reputation", "rewire_membership",
    "rewire_artifact_owner", "rewire_share_membership", "rewire_subscription",
    "share_allowed", "invitation_allowed", "sync_allowed",
    "moderation_decision",
]
