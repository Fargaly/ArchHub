"""Install paired compiler hooks without replacing existing hook behavior."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.pipeline.strict_check import CompilerFailure, git, node_timeout


def install(root, *, runner=None):
    root = Path(root).resolve()
    hooks = Path(git(root, "rev-parse", "--path-format=absolute", "--git-path", "hooks").decode().strip())
    destination = Path(git(root, "rev-parse", "--path-format=absolute", "--git-path", "acompiler-hooks").decode().strip())
    previous = subprocess.run(["git", "-C", str(root), "config", "--path", "--get", "core.hooksPath"], capture_output=True, text=True, timeout=node_timeout())
    if previous.returncode not in (0, 1):
        raise CompilerFailure("cannot read existing shared Git hook configuration")
    if previous.stdout.strip():
        hooks = Path(previous.stdout.strip())
        if not hooks.is_absolute():
            hooks = root / hooks
    if hooks.resolve() == destination.resolve():
        metadata = json.loads((destination / "previous.json").read_text(encoding="utf-8"))
        hooks = Path(metadata["hooks"])
    destination.mkdir(parents=True, exist_ok=True)
    runner = Path(runner).resolve() if runner else Path(__file__).with_name("pre_commit.py").resolve()
    quote = lambda path: shlex.quote(str(path).replace("\\", "/"))
    for name in ("pre-commit", "commit-msg", "post-commit"):
        prior = hooks / name
        script = "#!/bin/sh\nset -e\n"
        if prior.is_file():
            script += f"{quote(prior)} \"$@\"\n"
        if name == "post-commit":
            observer = Path(__file__).with_name("record_observation.py").resolve()
            script += f"exec {quote(sys.executable)} {quote(observer)} --root {quote(root)}\n"
        else:
            script += f"exec {quote(sys.executable)} {quote(runner)} --root {quote(root)} --phase {name}"
            script += " --paired-hook\n" if name == "pre-commit" else " --commit-message \"$1\"\n"
        target = destination / name
        target.write_text(script, encoding="utf-8", newline="\n")
        target.chmod(0o755)
    metadata = {"hooks": str(hooks), "commit_msg_sha256": hashlib.sha256((destination / "commit-msg").read_bytes()).hexdigest()}
    (destination / "previous.json").write_text(json.dumps(metadata), encoding="utf-8")
    # Enable only after both complete hooks are on disk.
    git(root, "config", "core.hooksPath", str(destination))
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    try:
        print(install(args.root))
        return 0
    except (CompilerFailure, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ACOMPILER HOOK INSTALL REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
