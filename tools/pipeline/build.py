"""Build admission: whole-tree ratchet plus zero errors in the owned change set.

Optional command after ``--`` executes only after admission. The Windows release
builder calls this preflight before it creates or packages any output.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools import ratchet
from tools.pipeline import pre_commit, strict_check


def release_context(message, author):
    """Preserve the landed author's recorded explanation, including prose bodies."""
    context = pre_commit.trailers(message)
    context["author"] = author
    if not context.get("intent"):
        owner = re.match(r"^([A-Z][A-Z0-9_]+):[ \t]+\S", message)
        if owner:
            context["intent"] = owner.group(1)
    if not context.get("why"):
        lines = message.partition("\n")[2].splitlines()
        # A terminal metadata footer is not an author's explanation.
        while lines and (not lines[-1].strip() or re.match(r"^[A-Za-z][A-Za-z0-9-]*:", lines[-1])):
            lines.pop()
        body = "\n".join(line for line in lines
                         if not re.match(r"^[\w-]+-by:|^Intent:|^Why:", line, re.IGNORECASE)).strip()
        if body:
            context["why"] = body
    return context


def registration_context(root, parent, commit, paths, context):
    """A new intent registers under the existing registration owner, never itself."""
    registry = 'evidence/acompiler-intents.json'
    if paths != [registry]:
        return context
    try:
        before = json.loads(strict_check.git(root, 'show', f'{parent}:{registry}'))
        after = json.loads(strict_check.git(root, 'show', f'{commit}:{registry}'))
        prior, added = before['intents'], after['intents']
        declared = context.get('intent')
        if (declared in prior or declared not in added
                or {k: v for k, v in before.items() if k != 'intents'} != {k: v for k, v in after.items() if k != 'intents'}
                or any(added.get(key) != value for key, value in prior.items())):
            return context
    except (strict_check.CompilerFailure, ValueError, KeyError, TypeError):
        return context
    return {**context, 'intent': 'ACOMPILER2B'}


def admit_sequence(root, base):
    """Replay immutable landed changes with their own authority and metrics."""
    head = strict_check.git(root, "rev-parse", "HEAD").decode().strip()
    strict_check.git(root, "merge-base", "--is-ancestor", base, head)
    if strict_check.git(root, "diff", "--name-only", head, "--").strip():
        raise ValueError("release tree differs from HEAD; commit the pending change before release")
    untracked = strict_check.git(root, "ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")
    if any(path and Path(path).suffix.lower() not in strict_check.NON_CODE for path in untracked):
        raise ValueError("release tree contains uncommitted source files")
    commits = strict_check.git(root, "rev-list", "--reverse", "--first-parent", f"{base}..{head}").decode().splitlines()
    for commit in commits:
        parent = strict_check.git(root, "rev-parse", f"{commit}^").decode().strip()
        paths = strict_check.git(root, "diff", "--no-renames", "--name-only", "-z", parent, commit, "--").decode().split("\0")
        paths = sorted(path for path in paths if path)
        overlay = {}
        for path in paths:
            present = strict_check.git(root, "ls-tree", "-z", commit, "--", path)
            overlay[path] = None
            if present:
                raw = strict_check.git(root, "show", f"{commit}:{path}")
                try:
                    overlay[path] = raw.decode("utf-8")
                except UnicodeError:
                    if Path(path).suffix.lower() not in strict_check.NON_CODE:
                        raise
                    overlay[path] = ""  # Non-executable asset, never substitute today's bytes.
        message = strict_check.git(root, "show", "-s", "--format=%B", commit).decode("utf-8")
        author = strict_check.git(root, "show", "-s", "--format=%an", commit).decode("utf-8").strip()
        recorded = release_context(message, author)
        context = registration_context(root, parent, commit, paths, recorded)
        if context.get('intent') != recorded.get('intent'):
            print(f"ACOMPILER REGISTRATION {commit}: ACOMPILER2B (declared {recorded.get('intent')})", flush=True)
        result = strict_check.check_files(root, paths, overlay=overlay, revision=parent, context=context,
                                          committed_history=True)
        strict_check.print_diagnostics(result)
        print(f"ACOMPILER COMMIT {commit}: {'PASS' if result['ok'] else 'FAIL'}", flush=True)
        if not result["ok"]:
            return 1
    return 0


def main(argv=None):
    args_list = list(sys.argv[1:] if argv is None else argv)
    split = args_list.index("--") if "--" in args_list else len(args_list)
    command = args_list[split + 1:]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--context")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--base")
    scope.add_argument("--commit")
    args = parser.parse_args(args_list[:split])
    root = Path(args.root).resolve()
    try:
        base = args.base
        if base is None and args.commit is None:
            baseline = json.loads((root / "evidence" / "acompiler.json").read_text(encoding="utf-8"))
            base = baseline["base_revision"]
            if not isinstance(base, str) or not base:
                raise ValueError("compiler baseline needs base_revision for build/land ownership")
            status = admit_sequence(root, base)
            if status:
                return status
            # Keep the final whole-tree ratchets and exact HEAD admission.
            args.commit = "HEAD"
        gate = ["compare", str(root), str(root / "evidence" / "ratchet.json"), "--whole-tree"]
        gate += ["--commit", args.commit] if args.commit is not None else ["--base", base]
        if args.context:
            gate += ["--context", args.context]
        status = ratchet.main(gate)
        if status:
            return status
        return subprocess.run(command, cwd=root, check=False).returncode if command else 0
    except (strict_check.CompilerFailure, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"ACOMPILER BUILD REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
