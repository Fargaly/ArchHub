"""Coherence courts for the WIP remote-device/session authority record."""

from pathlib import Path

from nodelang.cell_cloud_sessions import (
    DEFAULT_PROOF_REPLAY_CAPACITY,
    DEFAULT_PROOF_REPLAY_RETENTION_SECONDS,
)
from nodelang.cell_dpop import JoseRfc9449ProofVerifier


ROOT = Path(__file__).resolve().parents[2]




def test_replay_policy_record_matches_the_candidate_runtime_envelope():
    verifier = JoseRfc9449ProofVerifier()
    assert DEFAULT_PROOF_REPLAY_CAPACITY == 1024
    assert DEFAULT_PROOF_REPLAY_RETENTION_SECONDS == 15.0
    assert verifier.replay_retention_seconds == 15.0
