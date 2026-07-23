#!/usr/bin/env python
"""Shrink-only privacy ratchet for the public product tree.

The identifiers are stored as hashes so this guard does not create another
clear-text copy of the client/project terms it prevents from widening.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parent.parent

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


def _tracked_files(repo: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=repo,
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


def private_identifier_hits(text: str) -> int:
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


def scan_public_tree(repo: Path = REPO) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    hit_count = 0
    for relative in _tracked_files(repo):
        path_hits = private_identifier_hits(relative)
        content_hits = private_identifier_hits(_safe_text(repo / relative))
        total = path_hits + content_hits
        if not total:
            continue
        files.append({
            "path": relative,
            "path_hits": path_hits,
            "content_hits": content_hits,
            "total_hits": total,
        })
        hit_count += total
    return {
        "schema": "archhub-public-privacy-ratchet/v1",
        "baseline_file_count": BASELINE_FILE_COUNT,
        "baseline_hit_count": BASELINE_HIT_COUNT,
        "file_count": len(files),
        "hit_count": hit_count,
        "ok": len(files) <= BASELINE_FILE_COUNT and hit_count <= BASELINE_HIT_COUNT,
        "files": files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail if private client/project identifier debt widens."
    )
    parser.add_argument("--repo", default=str(REPO))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = scan_public_tree(Path(args.repo).resolve())
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            "[public-privacy-ratchet] "
            f"files={report['file_count']}/{report['baseline_file_count']} "
            f"hits={report['hit_count']}/{report['baseline_hit_count']}"
        )
    if not report["ok"]:
        print(
            "[public-privacy-ratchet] private identifier debt widened; "
            "use neutral synthetic placeholders in T0 public source.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
