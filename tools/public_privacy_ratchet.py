#!/usr/bin/env python
"""Shrink-only privacy ratchet for the public product tree."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parent.parent

TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[- ][A-Za-z0-9]+)*")


def default_policy_path(repo: Path = REPO) -> Path:
    workspace = repo.parent.parent
    return (
        workspace
        / "30.KNOWLEDGE"
        / "strategy"
        / "courts"
        / "public-privacy-ratchet-policy.private.json"
    )


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


def load_policy(policy_path: Path) -> dict[str, Any]:
    if not policy_path.is_file():
        raise FileNotFoundError(str(policy_path))
    data = json.loads(policy_path.read_text(encoding="utf-8"))
    identifiers = data.get("identifiers")
    if not isinstance(identifiers, list) or not identifiers:
        raise ValueError("privacy policy must contain a non-empty identifiers list")
    normalized = {
        re.sub(r"[^A-Za-z0-9]", "", str(identifier)).upper()
        for identifier in identifiers
    }
    normalized.discard("")
    if not normalized:
        raise ValueError("privacy policy identifiers normalize to an empty set")
    return {
        "schema": data.get("schema", "archhub-public-privacy-ratchet-policy/v1"),
        "baseline_file_count": int(data["baseline_file_count"]),
        "baseline_hit_count": int(data["baseline_hit_count"]),
        "normalized_identifiers": normalized,
        "policy_path": str(policy_path),
    }


def private_identifier_hits(text: str, identifiers: set[str]) -> int:
    hits = 0
    for token in _normalized_tokens(text):
        if token in identifiers:
            hits += 1
    return hits


def _safe_text(path: Path) -> str:
    data = path.read_bytes()
    if b"\0" in data[:4096]:
        return ""
    return data.decode("utf-8", errors="ignore")


def scan_public_tree(
    repo: Path = REPO,
    *,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    policy = load_policy(policy_path or default_policy_path(repo))
    files: list[dict[str, Any]] = []
    hit_count = 0
    for relative in _tracked_files(repo):
        identifiers = policy["normalized_identifiers"]
        path_hits = private_identifier_hits(relative, identifiers)
        content_hits = private_identifier_hits(_safe_text(repo / relative), identifiers)
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
        "policy_schema": policy["schema"],
        "policy_path": policy["policy_path"],
        "policy_storage": "private",
        "baseline_file_count": policy["baseline_file_count"],
        "baseline_hit_count": policy["baseline_hit_count"],
        "file_count": len(files),
        "hit_count": hit_count,
        "ok": (
            len(files) <= policy["baseline_file_count"]
            and hit_count <= policy["baseline_hit_count"]
        ),
        "files": files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail if private client/project identifier debt widens."
    )
    parser.add_argument("--repo", default=str(REPO))
    parser.add_argument("--policy", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    policy_path = Path(args.policy).resolve() if args.policy else None
    try:
        report = scan_public_tree(repo, policy_path=policy_path)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(
            "[public-privacy-ratchet] privacy policy unavailable or invalid: "
            f"{exc}",
            file=sys.stderr,
        )
        return 1
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
