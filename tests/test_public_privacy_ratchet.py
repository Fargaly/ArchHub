from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent

# SHA-256 of normalized private project/client identifiers that are already
# present in the public tree. Keep this as hashes so the ratchet does not add
# another clear-text copy of the identifiers it is guarding.
PRIVATE_IDENTIFIER_HASHES = {
    "493d5894c1da538e2a67b24cadd01d62b2d128a17f77cec5936b0d0d9c521166",
    "b559372470502cdacaf304dfc002b294f70505da376613ae36a021e59f787728",
    "cce27e9d0f5982b59014662329ddcfcedc4365a1a7d6eb49264ccb0db60ac670",
    "ed7fe83450d58d71102b3f580993c4153d8d1b786ca7176f5051f1e70c4f1abf",
    "f57bbc61a7251611f64831d37f206a4e7250d8b5cb428e2f1625f12d0cc548cd",
}

TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[- ][A-Za-z0-9]+)*")
BASELINE_FILE_COUNT = 21
BASELINE_HIT_COUNT = 93


def _tracked_files() -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.splitlines()


def _normalized_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for match in TOKEN.finditer(text):
        token = re.sub(r"[^A-Za-z0-9]", "", match.group(0)).upper()
        if token:
            tokens.append(token)
    return tokens


def _private_identifier_hits(text: str) -> int:
    hits = 0
    for token in _normalized_tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if digest in PRIVATE_IDENTIFIER_HASHES:
            hits += 1
    return hits


def _safe_text(path: Path) -> str:
    data = path.read_bytes()
    if b"\0" in data[:4096]:
        return ""
    return data.decode("utf-8", errors="ignore")


def test_public_private_identifier_debt_is_shrink_only():
    file_count = 0
    hit_count = 0
    for relative in _tracked_files():
        path_hits = _private_identifier_hits(relative)
        content_hits = _private_identifier_hits(_safe_text(REPO / relative))
        total = path_hits + content_hits
        if total:
            file_count += 1
            hit_count += total

    assert file_count <= BASELINE_FILE_COUNT, (
        "Public private-identifier debt widened. Run the private audit in "
        "30.KNOWLEDGE/strategy/courts before changing the public tree."
    )
    assert hit_count <= BASELINE_HIT_COUNT, (
        "Public private-identifier occurrence count widened. Replace new "
        "examples with neutral synthetic project placeholders."
    )
