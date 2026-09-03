"""Published lifecycle authority for graph-held proof replay policy.

This module does not store policy or lifecycle state. It interprets the exact
Cloud Session policy relation through the existing generic Versioned Asset and
court-attestation protocols.
"""
from __future__ import annotations

from .cell_attestations import AttestationProtocol, CourtAttestationBroker
from .cell_catalog import AssemblyProtocol
from .cell_cloud_sessions import (
    CloudSessionProtocol,
    ProofReplayPolicyReleaseEvidence,
    read_proof_replay_policy,
)
from .cell_lifecycle import (
    LifecycleProtocol,
    read_lifecycle_instance,
    read_revision,
    state_heads,
)
from .universal_cell import InvalidCell, Snapshot


class PublishedProofReplayPolicyVerifier:
    """Admit one exact court-evidenced Published replay-policy revision."""

    def __init__(
        self,
        assembly_protocol: AssemblyProtocol,
        lifecycle_protocol: LifecycleProtocol,
        attestation_protocol: AttestationProtocol,
        attestation_broker: CourtAttestationBroker,
        promotion_court_root: str,
        expected_lifecycle_instance_root: str,
    ) -> None:
        if (
            not isinstance(expected_lifecycle_instance_root, str)
            or not expected_lifecycle_instance_root
        ):
            raise InvalidCell(
                "replay policy lifecycle authority anchor is invalid"
            )
        self._assembly = assembly_protocol
        self._lifecycle = lifecycle_protocol
        self._attestation = attestation_protocol
        self._attestation_broker = attestation_broker
        self._promotion_court_root = promotion_court_root
        self._expected_lifecycle_instance_root = (
            expected_lifecycle_instance_root
        )

    def _verify_promotion(
        self,
        snapshot: Snapshot,
        instance_root: str,
        revision_root: str,
        expected_state_root: str,
    ):
        revision = read_revision(
            snapshot, self._lifecycle, revision_root
        )
        if (
            revision.state_root != expected_state_root
            or len(revision.predecessor_roots) != 1
            or not revision.evidence_roots
        ):
            raise InvalidCell(
                "replay policy promotion provenance is incomplete"
            )
        predecessor_root = revision.predecessor_roots[0]
        parameters = {
            "asset": instance_root,
            "targetState": expected_state_root,
        }
        digest = snapshot.cells[
            revision.content_digest_root
        ].atom.decode("ascii")
        for evidence_root in revision.evidence_roots:
            try:
                self._attestation_broker.verify(
                    snapshot,
                    self._attestation,
                    evidence_root,
                    expected_court_root=self._promotion_court_root,
                    expected_subject_name=predecessor_root,
                    expected_subject_digest=digest,
                    expected_parameters=parameters,
                    max_age_seconds=float("inf"),
                )
                return revision
            except (InvalidCell, PermissionError, KeyError):
                continue
        raise InvalidCell(
            "replay policy promotion has no admitted court evidence"
        )

    def verify(
        self,
        snapshot: Snapshot,
        protocol: CloudSessionProtocol,
    ) -> ProofReplayPolicyReleaseEvidence:
        instance_root = protocol.proof_replay_policy_lifecycle_root
        if instance_root is None:
            raise InvalidCell(
                "replay policy has no lifecycle authority wire"
            )
        if instance_root != self._expected_lifecycle_instance_root:
            raise InvalidCell(
                "replay policy lifecycle authority wire was substituted"
            )
        instance = read_lifecycle_instance(
            snapshot,
            self._assembly,
            self._lifecycle,
            instance_root,
        )
        published_heads = state_heads(
            snapshot,
            self._lifecycle,
            instance.state_pointers[self._lifecycle.states["published"]],
        )
        if len(published_heads) != 1:
            raise InvalidCell(
                "replay policy requires one Published revision"
            )
        published = self._verify_promotion(
            snapshot,
            instance_root,
            published_heads[0],
            self._lifecycle.states["published"],
        )
        shared = self._verify_promotion(
            snapshot,
            instance_root,
            published.predecessor_roots[0],
            self._lifecycle.states["shared"],
        )
        wip = read_revision(
            snapshot,
            self._lifecycle,
            shared.predecessor_roots[0],
        )
        if (
            wip.state_root != self._lifecycle.states["wip"]
            or wip.content_root != protocol.proof_replay_policy_root
            or shared.content_root != wip.content_root
            or published.content_root != wip.content_root
            or shared.content_digest_root != wip.content_digest_root
            or published.content_digest_root != wip.content_digest_root
        ):
            raise InvalidCell(
                "Published replay policy does not preserve one graph revision"
            )
        policy = read_proof_replay_policy(snapshot, protocol)
        return ProofReplayPolicyReleaseEvidence(
            policy_root=policy.root_id,
            lifecycle_instance_root=instance_root,
            wip_revision_root=wip.root_id,
            shared_revision_root=shared.root_id,
            published_revision_root=published.root_id,
            capacity=policy.capacity,
            retention_seconds=policy.retention_seconds,
        )


__all__ = ["PublishedProofReplayPolicyVerifier"]
