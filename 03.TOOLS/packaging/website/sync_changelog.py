"""Sync CHANGELOG.md from published GitHub releases.

Run from the repository root (stdlib only):

    python 03.TOOLS/packaging/website/sync_changelog.py

Set GH_TOKEN in the environment to use the authenticated GitHub API quota.

Keeps the empty ``## Next build`` slot, writes every published stable build as a
heading (newest first), and preserves older hand-written entries that are not
on GitHub. Release bodies that only carry the Build block become honest
published-build rows. Changes, known gaps and verification scope are copied
when present. Source lines stay in CHANGELOG.md for the repository; the public site
strips them at build time.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CHANGELOG = ROOT / "CHANGELOG.md"
API = "https://api.github.com/repos/Fargaly/ArchHub/releases"
SYNC_CHANGELOG_NODE = {'id': 'website.sync_changelog', 'params': {'request_seconds': 60}}
BUILD_HEADING = re.compile(r"^## (20\d{6}-(?:\d{4}-[0-9a-f]+|\d{6}-[1-9]\d*-[1-9]\d*-[0-9a-f]{40}))\s*$", re.M)


def fetch_releases(token: str | None = None) -> list[dict]:
    if token is None:
        token = os.environ.get("GH_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "archhub-changelog-sync"}
    rows: list[dict] = []
    page = 1
    while True:
        request = urllib.request.Request(f"{API}?per_page=100&page={page}", headers=headers)
        if token:
            request.add_unredirected_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(request, timeout=SYNC_CHANGELOG_NODE['params']['request_seconds']) as response:
            batch = json.load(response)
        if not batch:
            break
        rows.extend(item for item in batch
                    if item.get("published_at") and not item.get("draft") and not item.get("prerelease"))
        if len(batch) < 100:
            break
        page += 1
    return rows


def build_id(tag: str) -> str:
    return tag[6:] if tag.startswith("build-") else tag


def field(body: str, name: str) -> str:
    match = re.search(rf"^{name}:\s*(.+)$", body, re.M)
    return match.group(1).strip() if match else ""


def section_lines(body: str, heading: str) -> list[str]:
    match = re.search(rf"^## {re.escape(heading)}[ \t]*\r?\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    return match.group(1).splitlines() if match else []


def section_bullets(body: str, heading: str) -> list[str]:
    return [line[2:].strip() for line in section_lines(body, heading) if line.startswith("- ")]


def entry_from_release(release: dict) -> str:
    identity = build_id(release["tag_name"])
    body = release.get("body") or ""
    changed = section_bullets(body, "What changed") or section_bullets(body, "Changes")
    gaps = section_bullets(body, "Known gaps")
    lines = [f"## {identity}", ""]
    if changed:
        lines.extend(f"- {item}" for item in changed)
        if gaps:
            lines.append("- Known gaps: " + "; ".join(gaps))
    else:
        source = field(body, "SOURCE_REVISION")
        sha = re.search(r"^SHA256 ArchHub-Setup-0\.exe:\s*([0-9a-fA-F]{64})", body, re.M)
        built = field(body, "BUILT_AT")
        short = source[:7] if source else identity.split("-")[-1]
        lines.append(f"- Published build {identity} (source {short}).")
        if sha:
            lines.append(f"- Installer SHA-256: `{sha.group(1).lower()}`.")
        if built:
            lines.append(f"- Built at {built}.")
    verification = " ".join(line.strip().removeprefix("- ") for line in section_lines(body, "Verification scope")
                            if line.strip())
    if verification:
        lines.append(f"- Verification scope: {verification}")
    source = field(body, "SOURCE_REVISION")
    if source:
        lines.extend(["", f"Source: {source[:8]}."])
    lines.append("")
    return "\n".join(lines)


def existing_entries(text: str) -> dict[str, str]:
    parts = re.split(r"(?m)^## ", text)
    found: dict[str, str] = {}
    for part in parts[1:]:
        title, _, body = part.partition("\n")
        title = title.strip()
        if title == "Next build" or not BUILD_HEADING.fullmatch(f"## {title}"):
            continue
        found[title] = f"## {title}\n{body}".rstrip() + "\n"
    return found


def sync(token: str | None = None) -> str:
    releases = fetch_releases(token)
    if not releases:
        raise SystemExit("GitHub returned no releases")
    current = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else "# Changelog\n\n## Next build\n"
    preserved = existing_entries(current)
    written: list[str] = []
    seen: set[str] = set()
    for release in releases:
        identity = build_id(release["tag_name"])
        if identity in seen or not BUILD_HEADING.fullmatch(f"## {identity}"):
            continue
        seen.add(identity)
        # Prefer the GitHub release body for builds GitHub still lists.
        written.append(entry_from_release(release))
    for identity, block in preserved.items():
        if identity not in seen:
            written.append(block if block.endswith("\n") else block + "\n")
    updated = "# Changelog\n\n## Next build\n\n" + "\n".join(written)
    if not updated.endswith("\n"):
        updated += "\n"
    if updated != current:
        CHANGELOG.write_text(updated, encoding="utf-8")
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    text = sync()
    heads = BUILD_HEADING.findall(text)
    print(f"CHANGELOG.md: {len(heads)} release entries; newest {heads[0] if heads else 'none'}")


if __name__ == "__main__":
    main()
