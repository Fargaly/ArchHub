"""The broker review record and the release check that no shipped broker is unreviewed.

A host broker (Revit add-in, AutoCAD add-in, 3ds Max startup script) runs code
it is sent. Setup activates one only when the release carries an activation
{eligibility: reviewed-authenticated-broker, review_sha256} (nodelang/
host_broker_installation.py, nodelang/autocad_broker_installation.py,
colleague_setup.register_max_startup). That activation is the SHA-256 of one
review record, written by a person who is not the builder, deciding one exact
source. Nothing here writes a review or decides one; it only proves a supplied
record decides THIS source, and that every shipped entry carries it.

Review record, UTF-8 JSON, schema archhub-broker-review/v1:
* source_revision: the 40-64 lowercase hex revision the release compiles;
* bridges_tree_sha256: bridges_tree_sha256() of that revision's bridges/
  folder (print it with "python host_artifact_review.py digest <bridges>");
* reviewer: who reviewed it; decision: "approve-activation";
* hosts: the hosts approved, a subset of revit, autocad, max.

Command line (stdlib only, so the release script runs it by path):
  digest <bridges>                        print the tree digest to review
  check --index HOST_ARTIFACTS.json --review R --revision REV --bridges B
      exit 0 and list every reviewed entry, or exit 1 naming each unreviewed one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA = "archhub-broker-review/v1"
DECISION = "approve-activation"
ELIGIBILITY = "reviewed-authenticated-broker"
HOSTS = ("revit", "autocad", "max")
MAX_RECORD = 64 * 1024


class ReviewRefused(ValueError):
    """The supplied record does not decide activation of this exact source."""


def bridges_tree_sha256(root) -> str:
    """One digest over every file of bridges/, bytecode included: sorted "sha256  relative/path" lines.

    Nothing is skipped: a cached .pyc beside a reviewed script is loadable code too.
    """
    root = Path(root)
    lines = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        lines.append("%s  %s\n" % (hashlib.sha256(path.read_bytes()).hexdigest(), relative))
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def load_review(path, *, source_revision: str, bridges_root) -> dict:
    """The activation a valid record grants, and the hosts it approves; else ReviewRefused."""
    raw = Path(path).read_bytes()
    if len(raw) > MAX_RECORD:
        raise ReviewRefused("review record exceeds its size budget")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ReviewRefused("review record is not UTF-8 JSON") from None
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise ReviewRefused("review record schema is not %s" % SCHEMA)
    revision = record.get("source_revision")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40,64}", revision) or revision != source_revision:
        raise ReviewRefused("review record source revision is not the release revision %s" % source_revision)
    if record.get("bridges_tree_sha256") != bridges_tree_sha256(bridges_root):
        raise ReviewRefused("review record bridges tree digest does not match the shipped bridges")
    reviewer = record.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ReviewRefused("review record names no reviewer")
    if record.get("decision") != DECISION:
        raise ReviewRefused("review record decision is not %s" % DECISION)
    hosts = record.get("hosts")
    if (not isinstance(hosts, list) or not hosts or len(set(hosts)) != len(hosts)
            or not all(host in HOSTS for host in hosts)):
        raise ReviewRefused("review record hosts must be a non-empty subset of %s" % ", ".join(HOSTS))
    return {"activation": {"eligibility": ELIGIBILITY, "review_sha256": hashlib.sha256(raw).hexdigest()},
            "hosts": sorted(hosts), "reviewer": reviewer.strip()}


def check_index(index_path, review: dict) -> tuple[list[str], list[str]]:
    """(reviewed, unreviewed) entry names of one HOST_ARTIFACTS.json against one accepted review."""
    index_path = Path(index_path)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    activation, hosts = review["activation"], set(review["hosts"])
    reviewed, unreviewed = [], []

    def judge(name, host, ok):
        (reviewed if ok and host in hosts else unreviewed).append(name)

    for year, row in sorted((index.get("revit") or {}).items()):
        ok = isinstance(row, dict) and row.get("reviewed") is True
        if ok:
            try:
                raw = (index_path.parent / row["manifest"]).read_bytes()
                manifest = json.loads(raw)
                ok = (hashlib.sha256(raw).hexdigest() == row.get("sha256")
                      and manifest.get("activation") == activation
                      and manifest.get("runtime_closure_reviewed") is True)
            except (OSError, KeyError, TypeError, ValueError):
                ok = False
        judge("revit %s" % year, "revit", ok)
    for year, row in sorted((index.get("autocad") or {}).items()):
        judge("autocad %s" % year, "autocad",
              isinstance(row, dict) and row.get("reviewed") is True and row.get("activation") == activation)
    entry = index.get("max")
    if entry is not None:
        judge("max", "max", isinstance(entry, dict) and entry.get("reviewed") is True
              and entry.get("activation") == activation)
    return reviewed, unreviewed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="host_artifact_review")
    commands = parser.add_subparsers(dest="command", required=True)
    digest = commands.add_parser("digest")
    digest.add_argument("bridges")
    check = commands.add_parser("check")
    for name in ("--index", "--review", "--revision", "--bridges"):
        check.add_argument(name, required=True)
    args = parser.parse_args(argv)
    if args.command == "digest":
        print(bridges_tree_sha256(args.bridges))
        return 0
    try:
        review = load_review(args.review, source_revision=args.revision, bridges_root=args.bridges)
    except (OSError, ReviewRefused) as error:
        print("REFUSED: %s" % error)
        return 1
    reviewed, unreviewed = check_index(args.index, review)
    print("reviewed by %s: %s" % (review["reviewer"], ", ".join(reviewed) or "nothing"))
    if unreviewed:
        print("UNREVIEWED: %s" % ", ".join(unreviewed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())