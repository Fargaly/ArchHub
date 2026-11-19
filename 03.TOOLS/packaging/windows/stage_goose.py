"""Stage goose.exe built from pinned source (build_goose.py). Never downloads, builds or installs."""
from __future__ import annotations

import json
from pathlib import Path
import shutil

from build_goose import OURS, PIN, archhub_patches, check_lock, inputs, load_pin, sha


def stage_goose(build, destination, *, archhub_rev, pin_path=PIN, ours=OURS):
    """Check the build against this source revision, its engine inputs, the pin, the ordered patch series and its
    receipt, then copy it into an empty folder. A cached build from another revision or other inputs is refused."""
    build, destination = Path(build), Path(destination)
    pin = load_pin(pin_path)
    receipt = json.loads((build / "receipt.json").read_text(encoding="utf-8"))
    if (receipt.get("version"), receipt.get("upstream_commit")) != (pin["version"], pin["commit"]):
        raise ValueError("Goose build is not from the pinned version and commit")
    if receipt.get("patches") != archhub_patches(ours, pin_path):
        raise ValueError("Goose build patches differ from the declared patches (names, digests or order)")
    if receipt.get("archhub_rev") != archhub_rev or receipt.get("inputs") != inputs(pin_path):
        raise ValueError("Goose build was made from another ArchHub revision or other engine inputs")
    check_lock(Path(ours) / "Cargo.lock", pin)
    if receipt.get("cargo_lock_sha256") != pin["cargo_lock_sha256"]:
        raise ValueError("Goose build Cargo.lock differs from the pinned lock")
    if sha(build / "goose.exe") != receipt.get("executable_sha256") or sha(build / "LICENSE") != receipt.get("license_sha256"):
        raise ValueError("Goose build files differ from its receipt")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Goose staging destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("goose.exe", "LICENSE", "receipt.json"):
        shutil.copyfile(build / name, destination / name)
    manifest = {"version": pin["version"], "source_commit": pin["commit"], "archhub_rev": receipt["archhub_rev"],
                "executable_sha256": receipt["executable_sha256"], "source_url": pin["repository"]}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build")
    parser.add_argument("destination")
    parser.add_argument("--archhub-rev", required=True)
    args = parser.parse_args()
    stage_goose(args.build, args.destination, archhub_rev=args.archhub_rev)
