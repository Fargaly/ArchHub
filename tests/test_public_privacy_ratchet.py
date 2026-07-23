from __future__ import annotations

import sys
from pathlib import Path


TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import public_privacy_ratchet as ratchet  # noqa: E402


def test_public_private_identifier_debt_is_shrink_only():
    report = ratchet.scan_public_tree()

    assert report["file_count"] <= ratchet.BASELINE_FILE_COUNT, (
        "Public private-identifier debt widened. Run the private audit in "
        "30.KNOWLEDGE/strategy/courts before changing the public tree."
    )
    assert report["hit_count"] <= ratchet.BASELINE_HIT_COUNT, (
        "Public private-identifier occurrence count widened. Replace new "
        "examples with neutral synthetic project placeholders."
    )


def test_public_privacy_ratchet_cli_reports_current_baseline(capsys):
    assert ratchet.main([]) == 0
    output = capsys.readouterr().out
    assert "[public-privacy-ratchet]" in output
    assert "files=" in output
    assert "hits=" in output


def test_public_privacy_ratchet_is_wired_to_local_hooks():
    pre_commit = (ratchet.REPO / ".githooks" / "pre-commit").read_text(
        encoding="utf-8"
    )
    pre_push = (ratchet.REPO / ".githooks" / "pre-push").read_text(
        encoding="utf-8"
    )

    for hook in (pre_commit, pre_push):
        assert "tools/public_privacy_ratchet.py" in hook
        assert "python unavailable; blocking" in hook
        assert "gate script missing; blocking" in hook
