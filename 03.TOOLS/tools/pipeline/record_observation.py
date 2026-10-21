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
from datetime import datetime, timezone
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.pipeline.strict_check import CompilerFailure, git, selected_files

METRICS = {"files", "lines", "ratchet_deltas", "tests_removed", "languages", "scope_spread", "rule_hits"}


def receipt_path(root):
    if not (Path(root) / ".git").exists():
        return Path(root) / "evidence" / ".acompiler-admission.json"
    return Path(git(root, "rev-parse", "--path-format=absolute", "--git-path", "acompiler-admission.json").decode().strip())


def history_path(root):
    if not (Path(root) / ".git").exists():
        return Path(root) / "evidence" / ".acompiler-observations.json"
    return Path(git(root, "rev-parse", "--path-format=absolute", "--git-path", "acompiler-observations.json").decode().strip())


def alert_path(root):
    return history_path(root).with_name("acompiler-alerts.json")


def reserve_notices(root, context, observation):
    """Daily offers are accounted even when the proposed change is refused."""
    if not isinstance(observation, dict) or not observation.get("notices"):
        return
    author, day = context.get("author", ""), context.get("day", "")
    if not author or not day:
        observation["notices"] = []
        return
    with receipt_lock(root):
        path = alert_path(root)
        states = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        previous = states.get(author, {})
        used = previous.get("used", 0) if previous.get("day") == day else 0
        budget = observation["daily_alert_budget"]
        notices = observation["notices"][:max(0, budget - used)]
        states[author] = {"day": day, "used": used + len(notices)}
        _write_json(path, states)
        observation.update(notices=notices, alert_state=states[author])


def load_history(root, revision="HEAD", *, include_local=True):
    """Committed policy history plus locally recorded successful effects.

    The pending versioned baseline and caller history never grant admission.
    Git metadata makes post-commit history available before its export commits.
    """
    relative = "05.EVIDENCE/acompiler-baseline.json" if (Path(root) / "05.EVIDENCE").is_dir() else "evidence/acompiler-baseline.json"
    baseline = {"schema_version": 1, "history": [], "authors": {}}
    if (Path(root) / ".git").exists():
        if not git(root, "ls-tree", "-z", revision, "--", relative):
            relative = "evidence/acompiler-baseline.json"
        if git(root, "ls-tree", "-z", revision, "--", relative):
            baseline = json.loads(git(root, "show", f"{revision}:{relative}"))
    elif (Path(root) / relative).is_file():
        baseline = json.loads((Path(root) / relative).read_text(encoding="utf-8"))
    if not include_local:
        return baseline
    local_path = history_path(root)
    if local_path.is_file():
        local = json.loads(local_path.read_text(encoding="utf-8"))
        if local.get("schema_version") != 1 or not isinstance(local.get("history"), list) or not isinstance(local.get("authors"), dict):
            raise CompilerFailure("invalid local author observation history")
        known = {row.get("action_id", row.get("commit")) for row in baseline.get("history", [])}
        for row in local["history"]:
            identity = row.get("action_id", row.get("commit"))
            if identity and identity not in known:
                baseline.setdefault("history", []).append(row)
                known.add(identity)
        baseline.setdefault("authors", {}).update(local["authors"])
    notices = alert_path(root)
    if notices.is_file():
        for author, state in json.loads(notices.read_text(encoding="utf-8")).items():
            baseline.setdefault("authors", {}).setdefault(author, {}).setdefault("deviation_state", {})["alert_state"] = state
    return baseline


def _save_history(root, baseline):
    # Metadata first: an interruption before the export leaves a durable event.
    _write_json(history_path(root), baseline)
    _write_json(Path(root) / ("05.EVIDENCE" if (Path(root) / "05.EVIDENCE").is_dir() else "evidence") / "acompiler-baseline.json", baseline)


def baseline_state(observation):
    """Persist measurements, not a copied source of editable notice policy."""
    return {key: value for key, value in observation.items()
            if key not in {"daily_alert_budget", "notification_only_budget", "notices"}}


def record_action(root, pending, result):
    """Record only a compiler-admitted action with exact physical readback."""
    try:
        _record_action(root, pending, result)
    except (OSError, ValueError, RuntimeError) as error:
        # The effect has already happened. Keep its exact receipt and prohibit
        # treating this result as an unapplied refusal eligible for replay.
        result.update(ok=False, effect_applied=True, bookkeeping_pending=str(error))


def _record_action(root, pending, result):
    if not result.get("ok") or result.get("content_sha256") != result.get("readback_sha256"):
        raise CompilerFailure("action has no admitted exact readback")
    context, observation = result["measured_context"], result["observation"]
    if set(context.get("metrics", {})) != METRICS or set(observation.get("metrics", {})) != METRICS:
        raise CompilerFailure("action has incomplete measured author metrics")
    author = context["author"]
    if observation.get("author") != author or not author:
        raise CompilerFailure("action observation has no matching author")
    with receipt_lock(root):
        baseline = load_history(root)
        baseline.setdefault("history", []).append({"action_id": str(uuid.uuid4()), "author": author,
            "target": pending["target"], "content_sha256": result["content_sha256"],
            "metrics": context["metrics"], "intent": context["intent"], "why": context.get("why", ""),
            "observed_at": datetime.now(timezone.utc).isoformat(), "method_changes": observation.get("method_changes", [])})
        baseline.setdefault("authors", {}).setdefault(author, {})["deviation_state"] = baseline_state(observation)
        _save_history(root, baseline)


@contextmanager
def receipt_lock(root):
    receipt = receipt_path(root)
    receipt.parent.mkdir(parents=True, exist_ok=True)
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
    commit = git(root, "rev-parse", "HEAD").decode().strip()
    tree = git(root, "rev-parse", f"{commit}^{{tree}}").decode().strip()
    baseline = load_history(root)
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
    baseline.setdefault("authors", {}).setdefault(author, {})["deviation_state"] = baseline_state(receipt["observation"])
    _save_history(root, baseline)
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
