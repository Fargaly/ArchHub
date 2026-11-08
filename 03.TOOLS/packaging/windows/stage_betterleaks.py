"""Fetch the pinned Betterleaks Windows release and stage betterleaks.exe.

Betterleaks is the MIT-licensed secrets scanner from the Gitleaks authors
(https://github.com/betterleaks/betterleaks, v1.9.0). MIT permits
redistribution, so the release carries the binary. The archive SHA-256 is the
one published in that release's checksums.txt.
"""
from __future__ import annotations

import hashlib
from http.client import IncompleteRead
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import time
from urllib.error import HTTPError, URLError
import urllib.request
import zipfile


def fetch_betterleaks(destination, *, pin_path=Path(__file__).with_name("betterleaks-pin.json")):
    destination = Path(destination)
    pin = json.loads(Path(pin_path).read_text(encoding="utf-8"))
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Betterleaks staging destination must be empty")
    with tempfile.TemporaryDirectory(prefix="archhub-betterleaks-") as tmp:
        folder = Path(tmp)
        checksums = _download(pin["checksums_url"], folder / "checksums.txt", 8192)
        archive = _download(pin["url"], folder / pin["asset"], 16_777_216)
        _require_published_hash(checksums.read_text(encoding="utf-8"), pin["asset"], pin["sha256"])
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != pin["sha256"]:
            raise ValueError("Betterleaks archive SHA-256 differs from the published pin")
        return _stage(archive, destination, pin, digest)


def _download(url, dest, limit, *, timeout: int = 60,
              waits: tuple[int, ...] = (5, 15, 30, 60, 120)):
    if not str(url).startswith("https://github.com/betterleaks/betterleaks/releases/download/v"):
        raise ValueError("Betterleaks download URL is not a pinned GitHub release")
    request = urllib.request.Request(url, headers={"User-Agent": "ArchHub-release"})
    for attempt in range(len(waits) + 1):
        try:
            size = 0
            with dest.open("wb") as output, urllib.request.urlopen(request, timeout=timeout) as response:
                expected = response.headers.get("Content-Length")
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        raise ValueError("Betterleaks download exceeds the pinned size")
                    output.write(chunk)
                if expected is not None and size < int(expected):
                    raise IncompleteRead(b"", int(expected) - size)
            break
        except (URLError, TimeoutError, ConnectionError, IncompleteRead) as error:
            dest.unlink(missing_ok=True)
            if isinstance(error, HTTPError) and not (error.code == 429 or 500 <= error.code < 600):
                raise
            if attempt == len(waits):
                raise
            time.sleep(waits[attempt])
    return dest


def _require_published_hash(checksums, asset, expected):
    for line in checksums.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == asset:
            if parts[0].lower() != expected:
                raise ValueError("Published Betterleaks checksum differs from the pin")
            return
    raise ValueError("Published checksum file has no row for the pinned Betterleaks asset")


def _stage(archive, destination, pin, digest):
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in entry.filename
                    or ":" in entry.filename or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("Unsafe Betterleaks archive entry")
        binaries = [entry for entry in entries
                    if not entry.is_dir() and PurePosixPath(entry.filename).name == "betterleaks.exe"]
        if len(binaries) != 1:
            raise ValueError("Betterleaks archive must contain exactly one betterleaks.exe")
        if binaries[0].file_size > 32_000_000:
            raise ValueError("Betterleaks executable exceeds 32 MiB")
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / "betterleaks.exe"
        with package.open(binaries[0]) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)
    with target.open("rb") as source:
        binary_digest = hashlib.file_digest(source, "sha256").hexdigest()
    if binary_digest != pin["executable_sha256"]:
        raise ValueError("Betterleaks executable SHA-256 differs from the pin")
    manifest = {"version": pin["version"], "archive_sha256": digest,
                "executable_sha256": binary_digest, "source_url": pin["url"],
                "license": pin["license"]}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("usage: stage_betterleaks.py <destination>")
    fetch_betterleaks(sys.argv[1])
