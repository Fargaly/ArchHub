from __future__ import annotations

import pytest

from nodelang import KINDS, Store, relation_sources, relation_stages, relation_targets, validate_store
from nodelang.domains.community import (
    DEFAULT_ARTIFACTS,
    DEFAULT_MEMBERS,
    DEFAULT_PEERS,
    GRAND_MAP_CAPABILITIES,
    build_community_domain,
    invitation_allowed,
    moderation_decision,
    rewire_artifact_owner,
    rewire_share_membership,
    rewire_subscription,
    rewire_membership,
    set_artifact_parameter,
    set_member_parameter,
    set_peer_evidence,
    set_reputation,
    share_allowed,
    sync_allowed,
)
from nodelang.laws_effect import FrozenNode, apply_effect, dry_run


def _build():
    store = Store()
    domain = build_community_domain(store)
    return store, domain


def _pairs(store: Store) -> set[tuple[str, str]]:
    pairs = set()
    for node in store.nodes.values():
        if node["kind"] != "wire":
            continue
        for source in relation_sources(store.nodes, node):
            for target in relation_targets(store.nodes, node):
                pairs.add((source["node_id"], target["node_id"]))
    return pairs


def test_community_is_one_open_table_and_covers_the_full_grand_map_domain():
    store, domain = _build()

    assert validate_store(store) is True
    assert {node["kind"] for node in store.nodes.values()} <= KINDS
    assert store.nodes[domain["session"]]["kind"] == "session"
    assert domain["authority"] == "Grand Map / community"
    assert set(domain["capabilities"]) == set(GRAND_MAP_CAPABILITIES)
    assert len(GRAND_MAP_CAPABILITIES) == 19

    for capability in domain["capabilities"].values():
        assert store.open(capability)
    for owner in (
        domain["community"], domain["members"]["founder"],
        domain["peers"]["peer-firm"], domain["artifacts"]["shared-pattern"],
        domain["policy"], domain["scope_policy"],
    ):
        assert all(store.nodes[pid]["kind"] == "param"
                   for pid in store.nodes[owner]["params"].values())

    pairs = _pairs(store)
    assert (domain["members"]["founder"], domain["community"]) in pairs
    assert (domain["community"], domain["peers"]["peer-firm"]) in pairs
    assert (domain["artifacts"]["shared-pattern"],
            domain["provenance"]["shared-pattern"]) in pairs


def test_share_is_consent_privacy_ownership_and_evidence_gated_and_rewirable():
    store, domain = _build()

    assert share_allowed(store, domain, "shared-pattern") is False
    set_member_parameter(store, domain, "founder", "consent_to_share", True)
    set_artifact_parameter(store, domain, "shared-pattern", "approved", True)
    set_artifact_parameter(store, domain, "shared-pattern", "pii_redacted", True)
    assert share_allowed(store, domain, "shared-pattern") is True

    rewire_artifact_owner(store, domain, "shared-pattern", "architect")
    assert share_allowed(store, domain, "shared-pattern") is False
    rewire_share_membership(store, domain, "shared-pattern", "architect")
    assert share_allowed(store, domain, "shared-pattern") is False
    set_member_parameter(store, domain, "architect", "consent_to_share", True)
    assert share_allowed(store, domain, "shared-pattern") is True

    set_artifact_parameter(store, domain, "shared-pattern", "scope", "GLOBAL")
    assert share_allowed(store, domain, "shared-pattern") is False
    set_artifact_parameter(store, domain, "shared-pattern", "aggregate_only", True)
    assert share_allowed(store, domain, "shared-pattern") is True
    assert validate_store(store) is True


def test_invitation_requires_wired_authority_consent_approval_and_evidence():
    store, domain = _build()
    assert invitation_allowed(store, domain) is False

    set_member_parameter(store, domain, "founder", "consent_to_share", True)
    fields = domain["invitation_params"]
    for name, value in (
        ("approved", True),
        ("approved_by", "founder"),
        ("approved_at", "2026-07-13T01:00:00Z"),
        ("signature_evidence", "external signer capability verified"),
        ("idempotency_key", "invite-primary-v1"),
    ):
        store.edit(fields[name], ["body", "floor", "value"], value, actor="founder")
    assert invitation_allowed(store, domain) is True

    source = relation_sources(store.nodes, store.nodes[domain["inviter_relation"]])[0]
    from nodelang.laws_relation import rewire_endpoint
    rewire_endpoint(store, domain["inviter_relation"], source["endpoint_param"],
                    node_id=domain["members"]["architect"], actor="founder")
    assert invitation_allowed(store, domain) is False
    assert store.nodes[domain["invite_capability"]]["kind"] == "secret_ref"
    assert store.pull(domain["invite_capability"]).startswith("op://")


def test_federation_sync_is_explicit_evidence_gated_idempotent_and_frozen():
    store, domain = _build()
    peer = "peer-firm"
    assert sync_allowed(store, domain, peer) is False
    set_peer_evidence(
        store, domain, peer,
        health="online", health_observed_at="2026-07-13T02:00:00Z",
        health_evidence="HTTP 200 signed outbox response", authorized=True,
        authorization_observed_at="2026-07-13T02:00:01Z",
        authorization_evidence="external capability accepted",
    )
    fields = domain["federation_params"]
    for name, value in (
        ("approved", True), ("approved_by", "founder"),
        ("approved_at", "2026-07-13T02:00:02Z"),
        ("idempotency_key", "community-sync-v1"),
        ("sync_evidence", "dry-run converged with no USER rows"),
        ("sync_observed_at", "2026-07-13T02:00:03Z"),
    ):
        store.edit(fields[name], ["body", "floor", "value"], value, actor="founder")
    assert sync_allowed(store, domain, peer) is True

    for action, effect in domain["sync_effects"][peer].items():
        plan = dry_run(store, effect)
        assert plan["change"]["action"] == action
        with pytest.raises(FrozenNode):
            apply_effect(store, effect, {})
        dispatch = domain["sync_dispatch_relations"][peer][action]
        stages = relation_stages(store.nodes, store.nodes[dispatch])
        assert [(stage["mode"], stage["node_id"]) for stage in stages] == [
            ("guard", domain["sync_gates"][peer])
        ]

    store.edit(fields["idempotency_key"], ["body", "floor", "value"], "", actor="founder")
    assert sync_allowed(store, domain, peer) is False
    assert validate_store(store) is True


def test_join_marketplace_matching_and_fairness_are_real_gated_frozen_plans():
    store, domain = _build()

    join = domain["join_request_params"]
    for name, value in (
        ("member_id", "new-member"), ("invite_verified", True),
        ("consent", True), ("approved", True), ("approved_by", "founder"),
        ("approved_at", "2026-07-13T04:00:00Z"),
        ("verification_evidence", "signature and expiry verified"),
        ("idempotency_key", "join-new-member-v1"),
    ):
        store.edit(join[name], ["body", "floor", "value"], value, actor="founder")
    assert bool(store.pull(domain["join_gate"])) is True
    assert dry_run(store, domain["join_effect"])["change"]["action"] == "join"

    set_member_parameter(store, domain, "founder", "consent_to_share", True)
    set_artifact_parameter(store, domain, "shared-pattern", "approved", True)
    set_artifact_parameter(store, domain, "shared-pattern", "pii_redacted", True)
    marketplace = domain["marketplace_params"]
    store.edit(marketplace["approved"], ["body", "floor", "value"], True, actor="founder")
    store.edit(marketplace["evidence"], ["body", "floor", "value"],
               "listing reviewed", actor="founder")
    assert dry_run(store, domain["marketplace_effects"]["shared-pattern"])["change"]["action"] == "install"

    fingerprint = domain["fingerprint_params"]
    for name, value in (("fingerprint_ref", "sha256:abc"), ("similarity", 0.9),
                        ("evidence", "principal-angle computation evidence"),
                        ("approved", True)):
        store.edit(fingerprint[name], ["body", "floor", "value"], value, actor="founder")
    assert bool(store.pull(domain["fingerprint_gate"])) is True

    fairness = domain["fairness_params"]
    for name, value in (("candidate_quality", 0.8), ("group_weight", 0.5),
                        ("evidence", "group allocation calculation"),
                        ("approved", True)):
        store.edit(fairness[name], ["body", "floor", "value"], value, actor="founder")
    assert bool(store.pull(domain["fairness_gate"])) is True
    assert dry_run(store, domain["fairness_effect"])["change"]["action"] == "promote"
    for effect in (domain["join_effect"],
                   domain["marketplace_effects"]["shared-pattern"],
                   domain["fairness_effect"]):
        with pytest.raises(FrozenNode):
            apply_effect(store, effect, {})
    assert validate_store(store) is True


def test_moderation_uses_rewirable_reputation_and_visible_thresholds():
    store, domain = _build()
    contribution = "incoming-pattern"
    assert moderation_decision(store, domain, contribution) == "reject"

    params = domain["contribution_params"][contribution]
    for name, value in (
        ("confidence", 0.8), ("pii_redacted", True),
        ("provenance_verified", True),
        ("observed_at", "2026-07-13T03:00:00Z"),
        ("evidence", "signed contribution envelope"),
    ):
        store.edit(params[name], ["body", "floor", "value"], value, actor="moderator")
    set_reputation(
        store, domain, "peer-firm", 0.8,
        observed_at="2026-07-13T03:00:01Z", evidence="ten verified contributions",
    )
    assert moderation_decision(store, domain, contribution) == "accept"

    store.edit(domain["policy_params"]["accept_threshold"],
               ["body", "floor", "value"], 0.9, actor="moderator")
    assert moderation_decision(store, domain, contribution) == "quarantine"
    store.edit(domain["policy_params"]["quarantine_threshold"],
               ["body", "floor", "value"], 0.85, actor="moderator")
    assert moderation_decision(store, domain, contribution) == "reject"
    assert validate_store(store) is True


def test_subscription_rewiring_changes_authoritative_target_without_fallback():
    peer_two = dict(DEFAULT_PEERS[0])
    peer_two.update({
        "id": "peer-two", "display_name": "Peer two",
        "actor_url": "https://peer-two.example/actor",
        "capability_ref": "op://archhub/community/peer-two",
    })
    store = Store()
    domain = build_community_domain(store, peers=[DEFAULT_PEERS[0], peer_two])
    relation = domain["subscriptions"]["peer-firm"]
    assert relation_targets(store.nodes, store.nodes[relation])[0]["node_id"] == \
        domain["peers"]["peer-firm"]

    rewire_subscription(store, domain, "peer-firm", "peer-two", actor="founder")
    targets = relation_targets(store.nodes, store.nodes[relation])
    assert [item["node_id"] for item in targets] == [domain["peers"]["peer-two"]]
    assert relation not in store.nodes[domain["peers"]["peer-firm"]]["relations"]
    assert relation in store.nodes[domain["peers"]["peer-two"]]["relations"]
    assert validate_store(store) is True


def test_membership_rewire_is_authoritative_and_provenance_is_append_only():
    store, domain = _build()
    relation = domain["memberships"]["founder"]
    assert relation_sources(store.nodes, store.nodes[relation])[0]["node_id"] == \
        domain["members"]["founder"]
    rewire_membership(store, domain, "founder", "architect", actor="founder")
    assert relation_sources(store.nodes, store.nodes[relation])[0]["node_id"] == \
        domain["members"]["architect"]
    assert relation not in store.nodes[domain["members"]["founder"]]["relations"]
    assert relation in store.nodes[domain["members"]["architect"]]["relations"]

    provenance = domain["provenance"]["shared-pattern"]
    frozen_params = list(store.nodes[provenance]["params"].values())
    assert frozen_params and all(store.nodes[pid]["meta"]["frozen"] for pid in frozen_params)
    with pytest.raises(FrozenNode):
        store.edit(frozen_params[0], ["body", "floor", "value"], "rewritten past")
    assert validate_store(store) is True


def test_raw_secrets_are_rejected_and_no_live_state_is_fabricated():
    unsafe_peer = dict(DEFAULT_PEERS[0])
    unsafe_peer["access_token"] = "plaintext-token"
    with pytest.raises(ValueError, match="secret_ref|secret"):
        build_community_domain(Store(), peers=[unsafe_peer])

    bad_ref = dict(DEFAULT_PEERS[0])
    bad_ref["capability_ref"] = "plaintext-key"
    with pytest.raises(ValueError, match="op://"):
        build_community_domain(Store(), peers=[bad_ref])

    unsafe_artifact = dict(DEFAULT_ARTIFACTS[0])
    unsafe_artifact["private_key"] = "raw-key"
    with pytest.raises(ValueError, match="secret_ref|secret"):
        build_community_domain(Store(), artifacts=[unsafe_artifact])

    store, domain = _build()
    assert store.pull(domain["peer_params"]["peer-firm"]["health"]) == "unknown"
    assert store.pull(domain["peer_params"]["peer-firm"]["authorized"]) is False
    assert sync_allowed(store, domain, "peer-firm") is False
    assert all(store.nodes[effect]["meta"]["frozen"] is True
               for effects in domain["sync_effects"].values()
               for effect in effects.values())
    assert all(store.nodes[effect]["meta"]["frozen"] is True
               for effect in domain["share_effects"].values())
    assert "plaintext-token" not in repr(store.nodes)
    assert "raw-key" not in repr(store.nodes)


def test_parameter_edits_and_rewires_are_append_only_audited():
    store, domain = _build()
    before = sum(node["kind"] == "history" for node in store.nodes.values())
    set_member_parameter(store, domain, "founder", "display_name", "Studio Founder")
    set_artifact_parameter(store, domain, "shared-pattern", "confidence", 0.95)
    rewire_artifact_owner(store, domain, "shared-pattern", "architect")
    after = sum(node["kind"] == "history" for node in store.nodes.values())

    assert store.pull(domain["member_params"]["founder"]["display_name"]) == "Studio Founder"
    assert store.pull(domain["artifact_params"]["shared-pattern"]["confidence"]) == 0.95
    assert after >= before + 3
    assert validate_store(store) is True
