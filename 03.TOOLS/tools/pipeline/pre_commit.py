"""Shared human/agent commit admission; commit-msg binds final intent trailers."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path[:0] = [str(Path(__file__).resolve().parents[3] / area) for area in ("01.APP", "02.TESTS", "03.TOOLS", "06.CLOUD")]

from tools.pipeline import strict_check
from tools.pipeline import record_observation


def trailers(message):
    result = {}
    for key in ("Intent", "Why"):
        matches = re.findall(r"(?mi)^" + key + r":\s*(.+?)\s*$", message)
        if matches:
            result[key.lower()] = matches[-1]
    return result


def paired_hook_exists(root):
    hooks = strict_check.git(root, "config", "--path", "--get", "core.hooksPath").decode().strip()
    path = Path(hooks)
    if not path.is_absolute():
        path = Path(root) / path
    metadata = json.loads((path / "previous.json").read_text(encoding="utf-8"))
    return hashlib.sha256((path / "commit-msg").read_bytes()).hexdigest() == metadata["commit_msg_sha256"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--phase", choices=("pre-commit", "commit-msg"), default="pre-commit")
    parser.add_argument("--commit-message")
    parser.add_argument("--context")
    parser.add_argument("--paired-hook", action="store_true", help="installer's verified commit-msg pairing")
    args = parser.parse_args(argv)
    try:
        record_observation.clear_receipt(args.root)
        context_path = args.context or os.environ.get("ARCHHUB_INTENT_CONTEXT")
        context = json.loads(Path(context_path).read_text(encoding="utf-8")) if context_path else {}
        if args.phase == "commit-msg":
            if not args.commit_message:
                raise strict_check.CompilerFailure("commit-msg requires the final message file")
            context.update(trailers(Path(args.commit_message).read_text(encoding="utf-8")))
            context["author"] = strict_check.git(args.root, "var", "GIT_AUTHOR_IDENT").decode("utf-8").split("<", 1)[0].strip()
        admitted_tree = strict_check.git(args.root, "write-tree").decode().strip()
        result = strict_check.check_changed(args.root, context=context)
        if "conduct_events" in context and not result.get("selected"):
            conduct = strict_check.check_conduct(args.root, context)
            result["diagnostics"].extend(conduct["diagnostics"])
            result["ok"] = result["ok"] and conduct["ok"]
        if (args.phase == "pre-commit" and args.paired_hook and not context.get("intent")
                and any(item["code"] == "E0100" for item in result["diagnostics"])):
            # Git obtains the final edited message after pre-commit. The paired
            # commit-msg hook rechecks every diagnostic and never defers intent.
            if not paired_hook_exists(args.root):
                raise strict_check.CompilerFailure("mandatory commit-msg compiler hook is missing or modified")
            result["diagnostics"] = [item for item in result["diagnostics"] if item["code"] != "E0100"]
            result["ok"] = not result["diagnostics"]
        strict_check.print_diagnostics(result)
        if args.phase == "commit-msg" and result["ok"] and result.get("selected"):
            result["admitted_tree"] = admitted_tree
            record_observation.admit(args.root, result)
        print("ACOMPILER COMMIT PASS" if result["ok"] else "ACOMPILER COMMIT REFUSED")
        return 0 if result["ok"] else 1
    except (strict_check.CompilerFailure, OSError, ValueError) as exc:
        print(f"ACOMPILER COMMIT REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
