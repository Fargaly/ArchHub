#!/usr/bin/env python3
"""Keep the scoop manifest's hash equal to the hash of the published file.

A hand-written hash in a manifest rots the moment the installer is rebuilt,
and scoop refuses the install with a verification failure rather than a
useful message. The founder's site shipped one that had been wrong for weeks.
The manifest is therefore GENERATED: run this after publishing a build, with
the installer that was published.

    python installer/scoop/refresh_manifest.py dist/ArchHub-Setup-0.exe

It reads the file, writes the hash, and prints what changed. It never guesses:
with no file it exits non-zero and says so.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

MANIFEST = pathlib.Path(__file__).resolve().parent / "archhub.json"


def refresh(installer: pathlib.Path) -> int:
    if not installer.is_file():
        print("no installer at %s" % installer)
        return 2
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    held = json.loads(MANIFEST.read_text(encoding="utf-8"))
    was = str(held.get("hash") or "")
    now = "sha256:%s" % digest
    if was == now:
        print("scoop manifest already matches %s" % installer.name)
        return 0
    held["hash"] = now
    MANIFEST.write_text(json.dumps(held, indent=2) + "\n", encoding="utf-8")
    print("scoop manifest %s -> %s" % (was[:23] or "(none)", now[:23]))
    return 0


if __name__ == "__main__":
    target = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(
        "dist/ArchHub-Setup-0.exe")
    raise SystemExit(refresh(target))
