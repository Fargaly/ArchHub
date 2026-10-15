"""Stage an already fetched pinned Goose archive. Never downloads or installs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import zipfile


def stage_goose(archive, destination, *, pin_path=Path(__file__).with_name("goose-pin.json")):
    archive, destination = Path(archive), Path(destination)
    pin = json.loads(Path(pin_path).read_text(encoding="utf-8"))
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != pin["sha256"]:
        raise ValueError("Goose archive SHA-256 differs from the version pin")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Goose staging destination must be empty")
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in entry.filename
                    or ":" in entry.filename or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("Unsafe Goose archive entry")
        binaries = [e for e in entries if PurePosixPath(e.filename).name == "goose.exe"]
        if len(binaries) != 1:
            raise ValueError("Goose archive must contain exactly one goose.exe")
        # Flatten only the binary's distribution directory, preserving DLLs
        # and its upstream notices. Never extract a desktop installer.
        prefix = PurePosixPath(binaries[0].filename).parent
        destination.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if entry.is_dir() or not path.is_relative_to(prefix):
                continue
            relative = path.relative_to(prefix)
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(entry) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    with (destination / "goose.exe").open("rb") as source:
        binary_digest = hashlib.file_digest(source, "sha256").hexdigest()
    manifest = {"version": pin["version"], "archive_sha256": digest,
                "executable_sha256": binary_digest, "source_url": pin["url"]}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    parser.add_argument("destination")
    args = parser.parse_args()
    stage_goose(args.archive, args.destination)
