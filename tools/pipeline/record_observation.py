"""Record admitted change observations after the exact Git tree commits.

Admission receipts are short lived Git metadata. The versioned author history
is evidence/acompiler-baseline.json; its post-commit update is intentional
working-tree bookkeeping for the next commit.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import sys
import tempfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.pipeline.strict_check import CompilerFailure, git, selected_files

METRICS = {"files", "lines", "ratchet_deltas", "tests_removed", "languages", "scope_spread", "rule_hits"}


def receipt_path(root):
    return Path(git(root, "rev-parse", "--path-format=absolute", "--git-path", "acompiler-admission.json").decode().strip())


@contextmanager
def receipt_lock(root):
    receipt = receipt_path(root)
    lock = receipt.with_suffix(".lock")
    with lock.open("x", encoding="utf-8"):
        pass
    try:
        yield receipt
    finally:
        lock.unlink(missing_ok=True)


def clear_receipt(root):
    with receipt_lock(root) as receipt:
        receipt.unlink(missing_ok=True)


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def admit(root, result):
    """Persist a receipt only for real measured, successful compiler admission."""
    with receipt_lock(root) as receipt:
        return _admit(root, result, receipt)


def _admit(root, result, receipt_file):
    receipt_file.unlink(missing_ok=True)
    context, observation = result.get("context"), result.get("observation")
    if result.get("ok") is not True or result.get("diagnostics") or not isinstance(context, dict) or not isinstance(observation, dict):
        raise CompilerFailure("no successful measured compiler admission to record")
    author = context.get("author")
    actual_author = git(root, "var", "GIT_AUTHOR_IDENT").decode("utf-8").split("<", 1)[0].strip()
    if not author or author != actual_author or observation.get("author") != author:
        raise CompilerFailure("admission author does not match the Git author")
    metrics = context.get("metrics", {})
    if set(metrics) != METRICS or any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in metrics.values()):
        raise CompilerFailure("admission is missing measured change metrics")
    if set(observation.get("metrics", {})) != METRICS:
        raise CompilerFailure("admission is missing author baseline observations")
    tree = git(root, "write-tree").decode().strip()
    if result.get("admitted_tree") != tree:
        raise CompilerFailure("index tree changed during compiler admission")
    if result.get("selected") != selected_files(root) or context.get("files") != result.get("selected"):
        raise CompilerFailure("admission does not cover the exact staged file set")
    receipt = {"schema_version": 1, "tree": tree,
               "author": author, "intent": context.get("intent", ""), "why": context.get("why", ""),
               "metrics": metrics, "observation": observation}
    _write_json(receipt_file, receipt)
    return receipt


def record(root):
    with receipt_lock(root) as receipt:
        return _record(root, receipt)


def _record(root, receipt_file):
    root = Path(root).resolve()
    baseline_path = root / "evidence" / "acompiler-baseline.json"
    commit = git(root, "rev-parse", "HEAD").decode().strip()
    tree = git(root, "rev-parse", f"{commit}^{{tree}}").decode().strip()
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.is_file() else {"schema_version": 1, "history": [], "authors": {}}
    if any(row.get("commit") == commit for row in baseline.get("history", [])):
        if receipt_file.is_file():
            previous = json.loads(receipt_file.read_text(encoding="utf-8"))
            if previous.get("tree") == tree:
                receipt_file.unlink(missing_ok=True)
        return False
    if not receipt_file.is_file():
        raise CompilerFailure("committed tree has no compiler admission receipt")
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    if receipt.get("schema_version") != 1 or receipt.get("tree") != tree:
        raise CompilerFailure("committed tree differs from the compiler-admitted index tree")
    author = git(root, "show", "-s", "--format=%an", commit).decode("utf-8").strip()
    if receipt.get("author") != author:
        raise CompilerFailure("committed author differs from the compiler-admitted author")
    rows = baseline.setdefault("history", [])
    rows.append({"commit": commit, "author": author, "metrics": receipt["metrics"],
                 "intent": receipt["intent"], "why": receipt["why"],
                 "method_changes": receipt["observation"].get("method_changes", []),
                 "committed_at": git(root, "show", "-s", "--format=%aI", commit).decode().strip()})
    baseline.setdefault("authors", {}).setdefault(author, {})["deviation_state"] = receipt["observation"]
    _write_json(baseline_path, baseline)
    receipt_file.unlink(missing_ok=True)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    try:
        print("ACOMPILER AUTHOR OBSERVATION RECORDED" if record(args.root) else "ACOMPILER AUTHOR OBSERVATION ALREADY RECORDED")
        return 0
    except (CompilerFailure, OSError, ValueError, KeyError) as exc:
        print(f"ACOMPILER OBSERVATION REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
