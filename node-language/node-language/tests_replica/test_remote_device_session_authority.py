"""Coherence courts for the WIP remote-device/session authority record."""

from pathlib import Path

from nodelang.cell_cloud_sessions import (
    DEFAULT_PROOF_REPLAY_CAPACITY,
    DEFAULT_PROOF_REPLAY_RETENTION_SECONDS,
)
from nodelang.cell_dpop import JoseRfc9449ProofVerifier


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_RECORD = ROOT / "REMOTE-DEVICE-SESSION-AUTHORITY.md"


def test_replay_policy_record_is_wip_and_forbids_startup_self_publication():
    text = AUTHORITY_RECORD.read_text(encoding="utf-8")
    prose = " ".join(text.split())
    assert "Status: WIP" in text
    assert "this released design decision" not in text
    assert "They do not promote it." in prose
    assert "startup cannot impersonate that action" in prose
    assert "This record does not release the candidate policy." in prose


def test_replay_policy_record_matches_the_candidate_runtime_envelope():
    text = AUTHORITY_RECORD.read_text(encoding="utf-8")
    prose = " ".join(text.split())
    verifier = JoseRfc9449ProofVerifier()
    assert DEFAULT_PROOF_REPLAY_CAPACITY == 1024
    assert DEFAULT_PROOF_REPLAY_RETENTION_SECONDS == 15.0
    assert verifier.replay_retention_seconds == 15.0
    assert "1,024 slots" in text
    assert "10 seconds with 5 seconds of future" in prose
    assert "15-second retention envelope" in prose
