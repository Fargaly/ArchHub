"""The launcher starts no personal Brain daemon.

The application owns its Brain (founder decision 2026-09-15/16;
WORKSPACE-STANDARD :490 one Brain per instance). The retired personal-brain
daemon on :8473 is never started from here.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_launcher_starts_no_brain():
    src = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    for gone in ("_ensure_brain", "brain_supervisor_start", "personal_brain", "8473"):
        assert gone not in src, gone
    assert not (ROOT / "nodelang" / "brain_supervisor_start.py").exists()


def test_the_public_docs_describe_no_brain_service_on_this_machine():
    """The retired personal-brain daemon listened on 127.0.0.1:8473; the
    website must not send users looking for it."""
    from nodelang.website_docs_text import DOCS_PAGES
    for key, (title, lede, body) in DOCS_PAGES.items():
        text = "\n".join((title, lede, body))
        assert "8473" not in text, key
        assert "looks for a brain service" not in text, key
