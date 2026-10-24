"""Build admission: whole-tree ratchet plus zero errors in the owned change set.

Optional command after ``--`` executes only after admission. The Windows release
builder calls this preflight before it creates or packages any output.
"""
from __future__ import annotations

import argparse
import hashlib
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
    registry = paths[0] if paths in (['evidence/acompiler-intents.json'], ['05.EVIDENCE/acompiler-intents.json']) else ''
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


def compiler_identity(root):
    """Compiler bytes and pipeline; intent data is keyed per resolved request."""
    digest = hashlib.sha256()
    digest.update(Path(strict_check._command(root)[0]).read_bytes())
    listing = strict_check.git(root, "ls-files", "-z", "--", "tools/archhub-compiler", "tools/pipeline",
                               "tools/ratchet.py", "03.TOOLS/tools/archhub-compiler", "03.TOOLS/tools/pipeline", "03.TOOLS/tools/ratchet.py").decode()
    for path in sorted(p for p in listing.split("\0") if p):
        digest.update(path.encode() + b"\0" + strict_check.git(root, "show", f"HEAD:{path}"))
    return digest.hexdigest()


def admission_identity(identity, registry, context):
    """Track resolved current authority and every HEAD-pinned external input."""
    intent = context.get("intent")
    authority = {key: value for key, value in registry.items() if key != "intents"}
    authority["intents"] = {intent: registry.get("intents", {}).get(intent)} if intent else {}
    authority["external_entrypoints"] = {key: entry["external_entrypoints"]
        for key, entry in registry.get("intents", {}).items() if "external_entrypoints" in entry}
    return strict_check.source_digest({"compiler": identity, "authority": authority})


def admitted_record(root):
    """Per-machine record of commits this compiler identity already admitted; lives in the compiler's ignored build dir."""
    path = root / ("03.TOOLS/tools" if (root / "03.TOOLS/tools").is_dir() else "tools") / "archhub-compiler" / "target" / "admitted.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return path, data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return path, {}


def admit_sequence(root, base):
    """Replay immutable landed changes with their own authority and metrics.

    Parent authority is immutable; resolved current entries and every HEAD-pinned
    external input also affect admission. Unrelated registrations preserve hits.
    """
    identity = compiler_identity(root)
    record_path, admitted = admitted_record(root)
    head = strict_check.git(root, "rev-parse", "HEAD").decode().strip()
    strict_check.git(root, "merge-base", "--is-ancestor", base, head)
    if strict_check.git(root, "diff", "--name-only", head, "--").strip():
        raise ValueError("release tree differs from HEAD; commit the pending change before release")
    untracked = strict_check.git(root, "ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")
    if any(path and Path(path).suffix.lower() not in strict_check.NON_CODE for path in untracked):
        raise ValueError("release tree contains uncommitted source files")
    commits = strict_check.git(root, "rev-list", "--reverse", "--first-parent", f"{base}..{head}").decode().splitlines()
    registry_paths = strict_check.git(root, "ls-tree", "-r", "--name-only", head, "--",
                                      "evidence/acompiler-intents.json", "05.EVIDENCE/acompiler-intents.json").decode().splitlines()
    if len(registry_paths) > 1:
        raise ValueError("ambiguous intent registry")
    registry = json.loads(strict_check.git(root, "show", f"{head}:{registry_paths[0]}")) if registry_paths else {}
    for commit in commits:
        parent = strict_check.git(root, "rev-parse", f"{commit}^").decode().strip()
        paths = strict_check.git(root, "diff", "--no-renames", "--name-only", "-z", parent, commit, "--").decode().split("\0")
        paths = sorted(path for path in paths if path)
        message = strict_check.git(root, "show", "-s", "--format=%B", commit).decode("utf-8")
        author = strict_check.git(root, "show", "-s", "--format=%an", commit).decode("utf-8").strip()
        recorded = release_context(message, author)
        context = registration_context(root, parent, commit, paths, recorded)
        commit_identity = admission_identity(identity, registry, context)
        if admitted.get(commit) == commit_identity:
            print(f"ACOMPILER COMMIT {commit}: PASS (admitted by this compiler before)", flush=True)
            continue
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
        if context.get('intent') != recorded.get('intent'):
            print(f"ACOMPILER REGISTRATION {commit}: ACOMPILER2B (declared {recorded.get('intent')})", flush=True)
        result = strict_check.check_files(root, paths, overlay=overlay, revision=parent, context=context,
                                          committed_history=True)
        strict_check.print_diagnostics(result)
        print(f"ACOMPILER COMMIT {commit}: {'PASS' if result['ok'] else 'FAIL'}", flush=True)
        if not result["ok"]:
            return 1
        admitted[commit] = commit_identity
        record_path.write_text(json.dumps(admitted, indent=1, sort_keys=True), encoding="utf-8")
    return 0


def main(argv=None):
    args_list = list(sys.argv[1:] if argv is None else argv)
    split = args_list.index("--") if "--" in args_list else len(args_list)
    command = args_list[split + 1:]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(strict_check.PRODUCT_ROOT))
    parser.add_argument("--context")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--base")
    scope.add_argument("--commit")
    args = parser.parse_args(args_list[:split])
    root = Path(args.root).resolve()
    try:
        base = args.base
        if base is None and args.commit is None:
            baseline = json.loads((root / ("05.EVIDENCE" if (root / "05.EVIDENCE").is_dir() else "evidence") / "acompiler.json").read_text(encoding="utf-8"))
            base = baseline["base_revision"]
            if not isinstance(base, str) or not base:
                raise ValueError("compiler baseline needs base_revision for build/land ownership")
            status = admit_sequence(root, base)
            if status:
                return status
            # Keep the final whole-tree ratchets and exact HEAD admission.
            args.commit = "HEAD"
        gate = ["compare", str(root), str(root / ("05.EVIDENCE" if (root / "05.EVIDENCE").is_dir() else "evidence") / "ratchet.json"), "--whole-tree"]
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
