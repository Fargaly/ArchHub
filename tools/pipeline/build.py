"""Build admission: whole-tree ratchet plus zero errors in the owned change set.

Optional command after ``--`` executes only after admission. The Windows release
builder calls this preflight before it creates or packages any output.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools import ratchet


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
        gate = ["compare", str(root), str(root / "evidence" / "ratchet.json"), "--whole-tree"]
        gate += ["--commit", args.commit] if args.commit is not None else ["--base", base]
        if args.context:
            gate += ["--context", args.context]
        status = ratchet.main(gate)
        if status:
            return status
        return subprocess.run(command, cwd=root, check=False).returncode if command else 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"ACOMPILER BUILD REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
