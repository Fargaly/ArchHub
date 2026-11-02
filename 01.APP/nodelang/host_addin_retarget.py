"""Point this install's Revit add-in and AutoCAD bundle at the newest bridge.

The installer runs this after the new DLLs are in
bridges/<host>/<year>/<build-id>/. It never starts Revit or AutoCAD. A
registration refusal is printed and is not an install failure: the previous
registration still names a DLL the setup did not replace.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("  host add-in: install directory required")
        return 1
    root = Path(argv[0])
    if not root.is_dir():
        print("  host add-in: install directory is missing")
        return 1
    sys.path.insert(0, str(root))
    import colleague_setup
    try:
        colleague_setup.register_revit_add_ins(root)
        colleague_setup.register_autocad_add_ins(root)
    except Exception as exc:  # noqa: BLE001 - the new DLLs are already installed
        print("  host add-in: not retargeted (%s)" % type(exc).__name__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
