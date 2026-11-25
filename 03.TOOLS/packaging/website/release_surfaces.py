"""Propagate one published release to every surface, and check that they agree.

One source: the GitHub Latest release (its notes and ## Build block), the site design
(data/design.json) and 04.DOCS/DECISIONS.md. Surfaces: CHANGELOG.md and archhub.io,
in-app documentation (site_export), the Notion ArchHub page, the Cockpit (cloud
version) and the 10.PRODUCT area READMEs above this checkout.

Run from the repository root (stdlib only):

    python 03.TOOLS/packaging/website/release_surfaces.py write [--areas DIR]
    python 03.TOOLS/packaging/website/release_surfaces.py notion-status
    python 03.TOOLS/packaging/website/release_surfaces.py check [--areas DIR]
    python 03.TOOLS/packaging/website/release_surfaces.py research-rows --res 075 077 078 [--publish]

write rewrites the Cockpit version (06.CLOUD/cloud_backend/fly.toml) and, when the
area folders exist (the release machine), their README.md files. notion-status prints
the Status section the Notion refresh job pastes. research-rows prints (or with --publish
creates) Research Library rows for R&D mirrors, skipping res ids already there. check exits 1 naming every surface
that disagrees with the released BUILD_ID and notes; an unreadable surface fails too.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_changelog  # noqa: E402

ROOT = sync_changelog.ROOT
HERE = Path(__file__).resolve().parent
FLY_TOML = ROOT / "06.CLOUD/cloud_backend/fly.toml"
DECISIONS = ROOT / "04.DOCS/DECISIONS.md"
DESIGN = HERE / "data/design.json"
SITE = "https://archhub.io"
CLOUD = "https://api.archhub.io"
NOTION_ROOT = "358f57b4e72f81f99f50ffaa2cdea4be"
REPO_URL = "https://github.com/Fargaly/ArchHub"
RELEASE_SURFACES_NODE = {'id': 'website.release_surfaces', 'params': {'request_seconds': 30, 'fly_seconds': 90}}
RESEARCH = Path("30.KNOWLEDGE/32.RESEARCH/32.03-ARCHHUB-RD")
RESEARCH_DB = "collection://02f1b178-0e65-4379-904a-387a219e8730"  # the existing Research Library
AREA_PAGE = "https://app.notion.com/p/3eef57b4e72f81d7b3bceea7f92139f1"  # Areas / ArchHub & Products
SYNTHESIS_PAGE = "https://app.notion.com/p/3f1f57b4e72f8104b370d307fbe30dcf"
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
# A build named in prose: a build id, a parenthesised revision, or "<Month> N stable build".
BUILD_MENTION = re.compile(r"\b20\d{6}-\d{4,6}(?:-[\w]+)*?-([0-9a-f]{7,40})\b|\(([0-9a-f]{8,40})\)"
                           rf"|\b((?:{MONTHS}) \d{{1,2}} stable build)\b")
LINK = re.compile(r"\]\(([^)\s]+)\)")
# The sign-in contract every released build documents (SPEC §9.5), and the retired optional-sign-in wording.
SIGNIN_REQUIRED = "Desktop work needs an internet connection and a verified"
SIGNIN_STALE = ("sign in later", "without an account", "sign-in is optional")

# The area READMEs: purpose and links (relative to the area folder) stay as the coordinator set them.
AREAS = {
    "12.WEBSITE": ("Website", "PUBLIC navigation. README-only entry above the single source checkout.", [
        ("Open source", "../11.ARCHHUB-APP/06.CLOUD/public_site/README.md"),
        ("Source authority", "../11.ARCHHUB-APP/01.APP/nodelang/site_export.py"),
        ("Release sync", "../11.ARCHHUB-APP/.github/workflows/site-release-sync.yml"),
        ("Propagation", "../11.ARCHHUB-APP/03.TOOLS/packaging/website/release_surfaces.py")],
        "Live: https://archhub.io", "web", "Code and generated assets remain in 11.ARCHHUB-APP."),
    "13.COCKPIT-CLOUD": ("Cockpit and cloud", "PUBLIC navigation. README-only entry above the single source checkout.", [
        ("Open source", "../11.ARCHHUB-APP/06.CLOUD/cloud_backend/"),
        ("Cockpit (cloud)", "../11.ARCHHUB-APP/06.CLOUD/cloud_backend/cockpit_assets/admin.html"),
        ("Cockpit (app)", "../11.ARCHHUB-APP/01.APP/nodelang/studio/cockpit.html")],
        "Live: https://api.archhub.io", "cloud", "Code and generated assets remain in 11.ARCHHUB-APP."),
    "14.DOCS": ("Public documentation", "PUBLIC navigation. README-only entry above the single source checkout.", [
        ("Open source", "../11.ARCHHUB-APP/04.DOCS/"),
        ("Decisions", "../11.ARCHHUB-APP/04.DOCS/DECISIONS.md"),
        ("Authority", "../11.ARCHHUB-APP/04.DOCS/AUTHORITY.md"),
        ("Website docs", "../11.ARCHHUB-APP/06.CLOUD/public_site/README.md"),
        ("In-app docs", "../11.ARCHHUB-APP/01.APP/nodelang/site_export.py")],
        "", "docs", "Code and generated assets remain in 11.ARCHHUB-APP."),
    "15.RELEASES": ("Release manifests", "PUBLIC navigation. README-only entry above the single source checkout.", [
        ("Release workflow", "../11.ARCHHUB-APP/.github/workflows/release.yml"),
        ("Source authority", "../11.ARCHHUB-APP/VERSION"),
        ("Changelog", "../11.ARCHHUB-APP/CHANGELOG.md")],
        "Releases: https://github.com/Fargaly/ArchHub/releases", "release",
        "Signed/issued/deployed status must be read from the release owner; folder presence does not "
        "establish a release. No installers are stored here."),
}
AREA_FILES = {"README.md", "REGISTER.md"}


def released(releases: list[dict] | None = None) -> dict:
    """The newest published stable release, reduced to what the surfaces show."""
    rows = sync_changelog.fetch_releases() if releases is None else releases
    if not rows:
        raise SystemExit("GitHub returned no published release")
    newest = max(rows, key=lambda row: row["published_at"])
    body = newest.get("body") or ""
    build = sync_changelog.field(body, "BUILD_ID") or sync_changelog.build_id(newest["tag_name"])
    return {"build_id": build, "tag": newest["tag_name"], "notes": sync_changelog.release_bullets(body),
            "source": sync_changelog.field(body, "SOURCE_REVISION"), "built_at": sync_changelog.field(body, "BUILT_AT")}


def latest_decision(text: str | None = None) -> str:
    text = DECISIONS.read_text(encoding="utf-8") if text is None else text
    heads = re.findall(r"^## (D-\d+.*)$", text, re.M)
    return max(heads, key=lambda h: int(re.match(r"D-(\d+)", h)[1])) if heads else "none recorded"


def design_digest() -> str:
    return hashlib.sha256(DESIGN.read_bytes()).hexdigest()[:12] if DESIGN.exists() else "missing"


def site_heading(build: str) -> str:
    """The changelog heading build_site.py renders for a build id."""
    d = re.match(r"(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})", build)
    return f"{d[1]}-{d[2]}-{d[3]} · {d[4]}:{d[5]}" if d else build


def foreign_builds(text: str, rel: dict) -> list[str]:
    """Builds named in prose that are not the released one."""
    found = []
    for match in BUILD_MENTION.finditer(text):
        token = match[1] or match[2]
        if match[3] or not (rel["build_id"].endswith(token) or (rel["source"] or "-").startswith(token)
                            or token.startswith(rel["build_id"].rsplit("-", 1)[-1])):
            found.append(match[0])
    return found


def docs_problems(text: str, rel: dict) -> list[str]:
    """Other builds named, retired optional-sign-in wording, or the account-required wording missing."""
    flat = re.sub(r"\s+", " ", text)
    problems = foreign_builds(flat, rel) + [phrase for phrase in SIGNIN_STALE if phrase in flat.lower()]
    return problems + ([] if SIGNIN_REQUIRED in flat else ["account-required sign-in wording missing"])


def docs_text(revision: str | None) -> str | None:
    """The in-app guides at the released revision; None when that revision cannot be read (never the working tree)."""
    if not revision:
        return None
    shown = subprocess.run(["git", "-C", str(ROOT), "show", f"{revision}:01.APP/nodelang/site_export.py"],
                           capture_output=True, text=True, encoding="utf-8")
    return templates_text(shown.stdout) if shown.returncode == 0 else None


def templates_text(source: str) -> str:
    """The guide templates (site_export._DOCS_TEMPLATES) from source text, never imported."""
    tree = ast.parse(source)
    value = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                 and getattr(node.targets[0], "id", "") == "_DOCS_TEMPLATES")
    return json.dumps(ast.literal_eval(value.args[0]), ensure_ascii=False)


def unreadable(what: str, exc: BaseException) -> None:
    """Name the unreadable surface on stderr; the caller reports it as failed, never as agreeing."""
    print(f"unreadable {what}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return None


def fetch(url: str) -> str | None:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "archhub-release-surfaces"})
        with urllib.request.urlopen(request, timeout=RELEASE_SURFACES_NODE['params']['request_seconds']) as response:
            return response.read().decode("utf-8", "replace")
    except OSError as exc:
        return unreadable(url, exc)


def notion_page() -> str | None:
    """The Notion root page through the app's own Notion client (the release machine's grant)."""
    try:
        sys.path.insert(0, str(ROOT / "01.APP"))
        from nodelang import notion_mcp
        return json.dumps(notion_mcp.call_tool("notion-fetch", {"id": NOTION_ROOT}), ensure_ascii=False)
    except Exception as exc:  # any client, grant or network failure means the page was not read
        return unreadable("Notion", exc)


def fly_release(app: str) -> dict | None:
    """Version and time of the newest Fly release; the deploying user is never read out."""
    flyctl = shutil.which("flyctl") or shutil.which("fly")
    if not flyctl:
        return None
    run = subprocess.run([flyctl, "releases", "-a", app, "--json"], capture_output=True, text=True,
                         timeout=RELEASE_SURFACES_NODE['params']['fly_seconds'])
    try:
        rows = json.JSONDecoder().raw_decode(run.stdout.lstrip())[0]
        return {"version": rows[0]["Version"], "at": rows[0]["CreatedAt"]}
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        return unreadable(app, exc)


def cloud_health(get=fetch) -> dict:
    try:
        return json.loads(get(CLOUD + "/healthz") or "{}")
    except ValueError:
        return {}


def notion_status(rel: dict) -> str:
    url = f"{REPO_URL}/releases/tag/{rel['tag']}"
    lines = [f"- **Updated:** {rel['built_at'][:10] or 'unknown'}.",
             f"- **Current build:** {rel['build_id']} ([release notes]({url}), always [latest]({REPO_URL}/releases/latest))."]
    lines += [f"  - {note}" for note in rel["notes"]] or ["  - This release publishes the Build block only."]
    lines += [f"- **Latest decision:** {latest_decision()}.", f"- **Design source:** design.json {design_digest()}."]
    return "\n".join(lines)


def area_readme(name: str, rel: dict, live: dict) -> str:
    title, tier, links, tail, kind, note = AREAS[name]
    current = {
        "web": lambda: "Deployed: archhub-web Fly release %s." % (live.get("web") or "not readable on this machine"),
        "cloud": lambda: "Deployed: archhub-cloud Fly release %s, commit %s, version %s." % (
            live.get("cloud") or "not readable on this machine",
            live.get("cloud_commit") or "not reported", live.get("cloud_version") or "not reported"),
        "docs": lambda: "In-app docs ship with build %s; latest decision %s." % (rel["build_id"], latest_decision()),
        "release": lambda: "GitHub Latest: %s (BUILD_ID %s)." % (rel["tag"], rel["build_id"]),
    }[kind]()
    nav = " · ".join([f"[{label}]({target})" for label, target in links] + ([tail] if tail else []))
    return (f"# {title}\n\nOwner: ArchHub product. Tier: {tier}\n\n{nav}\n\n"
            f"{current}\n\n{note}\n\n_Generated by release_surfaces.py; edit the generator, not this file._\n")


def live_state(get=fetch) -> dict:
    web, cloud = fly_release("archhub-web"), fly_release("archhub-cloud")
    health = cloud_health(get)
    return {"web": web and f"v{web['version']} ({web['at']})", "cloud": cloud and f"v{cloud['version']} ({cloud['at']})",
            "cloud_commit": (health.get("commit") or "")[:8], "cloud_version": health.get("version")}


def default_areas() -> Path | None:
    for candidate in (ROOT.parent, *ROOT.parents):
        if (candidate / "12.WEBSITE").is_dir():
            return candidate
    return None


def write(rel: dict, areas: Path | None, live: dict | None = None) -> list[str]:
    changed = []
    text = FLY_TOML.read_text(encoding="utf-8")
    updated = re.sub(r'(?m)^(\s*ARCHHUB_VERSION\s*=\s*)"[^"]*"', rf'\g<1>"{rel["build_id"]}"', text)
    if updated != text:
        FLY_TOML.write_text(updated, encoding="utf-8")
        changed.append(str(FLY_TOML.relative_to(ROOT)))
    if areas:
        live = live_state() if live is None else live
        for name in AREAS:
            path = areas / name / "README.md"
            path.parent.mkdir(exist_ok=True)
            content = area_readme(name, rel, live)
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                path.write_text(content, encoding="utf-8")
                changed.append(str(path))
    return changed


def check(rel: dict, areas: Path | None, get=fetch, notion=notion_page) -> list[tuple[str, bool, str]]:
    build, results = rel["build_id"], []

    def court(surface, ok, detail):
        results.append((surface, bool(ok), detail))

    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    entry = log.split(f"## {build}\n", 1)[1].split("\n## ", 1)[0] if f"## {build}\n" in log else ""
    missing = [n for n in rel["notes"] if n not in entry]
    court("changelog", entry and not missing, "missing heading" if not entry else f"{len(missing)} note(s) missing")

    download = get(SITE + "/download.json")
    try:
        live_build = json.loads(download or "{}").get("build_id")
    except ValueError:
        live_build = None
    court("website download", live_build == build, f"serves {live_build}")
    page = get(SITE + "/changelog/") or ""
    court("website changelog", site_heading(build) in page, f"heading {site_heading(build)!r} " + ("found" if site_heading(build) in page else "absent"))
    docs_page = get(SITE + "/docs/getting-started/")
    stale = docs_problems(html.unescape(re.sub(r"<[^>]+>", " ", docs_page or "")), rel)
    court("website docs", docs_page and not stale, "unreadable" if docs_page is None else f"problems: {stale[:4]}")

    guides = docs_text(rel["source"])
    stale = docs_problems(guides or "", rel)
    court("in-app docs", guides is not None and not stale,
          f"revision {rel['source'][:8] or '(none)'} unreadable" if guides is None else f"problems at {rel['source'][:8]}: {stale[:4]}")

    page = notion()
    current = re.search(r"Current build:\S*\s*([^\s(\\]+)", page or "")
    court("notion", current and current[1] == build, "unreadable" if page is None else f"current build {current and current[1]}")

    pinned = re.search(r'ARCHHUB_VERSION\s*=\s*"([^"]*)"', FLY_TOML.read_text(encoding="utf-8"))
    health = cloud_health(get)
    court("cockpit", pinned and pinned[1] == build and health.get("version") == build,
          f"fly.toml {pinned and pinned[1]}, live {health.get('version')}")

    if areas:
        for name in AREAS:
            folder = areas / name
            readme = folder / "README.md"
            text = readme.read_text(encoding="utf-8") if readme.exists() else ""
            extra = sorted(p.name for p in folder.iterdir() if p.name not in AREA_FILES) if folder.is_dir() else ["missing folder"]
            broken = [t for t in LINK.findall(text) if "://" not in t and not (folder / t.split("#")[0]).exists()]
            fresh = name != "15.RELEASES" or build in text
            court(f"area {name}", text and not extra and not broken and fresh,
                  f"extra {extra}, broken links {broken}, names release {fresh}")
    return results


def research_dir() -> Path | None:
    for candidate in ROOT.parents:
        folder = candidate / RESEARCH
        if folder.is_dir():
            return folder
    return None


def research_row(path: Path) -> dict:
    """One Research Library row from an R&D mirror (archhub-claude-doc-res-NNN-<date>.md)."""
    res, date = re.search(r"res-(\d+)-(\d{4}-\d{2}-\d{2})", path.name).groups()
    text = path.read_text(encoding="utf-8")
    heading = re.search(r"^## (.+)$", text, re.M)
    today = re.search(r"^\*\*(?:Today|What changed)\.\*\*\s*(.+)$", text, re.M)
    proposal = re.search(r"^### Proposals\s*\n(?:.*\n){2}\|\s*([^|]+)\|", text, re.M)
    return {"res": f"res-{res}", "properties": {
        "Name": f"{heading[1].strip() if heading else path.stem} (res-{res})",
        "Key takeaway": today[1].strip() if today else "See the synthesis section.",
        "How to apply": proposal[1].strip() if proposal else "No proposal in this synthesis.",
        "Field": "Other", "Read depth": "Full text", "Status": "Read",
        "date:Read on:start": date, "date:Read on:is_datetime": 0,
        "Area": json.dumps([AREA_PAGE])},
        "content": f"Synthesis section: {SYNTHESIS_PAGE}"}


def posted_research(query=None) -> set[str] | None:
    """res ids already in the Research Library (title suffix "(res-NNN)"); None when Notion is unreadable."""
    try:
        if query is None:
            sys.path.insert(0, str(ROOT / "01.APP"))
            from nodelang import notion_mcp
            query = notion_mcp.call_tool
        sql = f'SELECT "Name" FROM "{RESEARCH_DB}" WHERE "Name" LIKE \'%(res-%\''
        answer = query("notion-query-data-sources", {"data": {"mode": "sql", "data_source_urls": [RESEARCH_DB], "query": sql}})
        return research_ids(answer)
    except Exception as exc:  # any client, grant or network failure means de-duplication is unverified
        return unreadable("Research Library", exc)


def research_ids(answer: dict) -> set[str] | None:
    """res ids in any Notion tool answer: structuredContent rows, or the JSON text in content[].text
    (notion-search answers carry only text, with results[].title like "R&D: 2026-11-23 (res-075)").
    None when no part is a recognisable results list, so de-duplication is unverified, never zero."""
    rows, recognised = [], False
    structured = (answer.get("structuredContent") or {}).get("results")
    if isinstance(structured, list):
        rows, recognised = list(structured), True
    for part in answer.get("content", []):
        try:
            found = json.loads(part.get("text", "")).get("results")
        except (ValueError, AttributeError) as exc:
            unreadable("Notion text part", exc)
            continue
        if isinstance(found, list):
            rows, recognised = rows + found, True
    if not recognised:
        return None
    return {m for row in rows if isinstance(row, dict) for key in ("Name", "title")
            for m in re.findall(r"\((res-\d+)\)", str(row.get(key, "")))}


def publish_research(rows: list[dict], posted: set[str] | None) -> None:
    """Create the rows; refused unless the posted set was read from a recognised Notion answer."""
    if posted is None:
        raise SystemExit("refused: cannot de-duplicate while Notion is unreadable")
    from nodelang import notion_mcp
    if rows:
        notion_mcp.call_tool("notion-create-pages", {
            "parent": {"type": "data_source_id", "data_source_id": RESEARCH_DB.split("//")[1]},
            "pages": [{"properties": r["properties"], "content": r["content"]} for r in rows]})
    print(f"published {len(rows)} row(s)")


def research_rows(ids: list[str], folder: Path, posted: set[str] | None) -> list[dict]:
    rows = []
    for number in ids:
        match = sorted(folder.glob(f"archhub-claude-doc-res-{int(number):03d}-*.md"))
        if not match:
            raise SystemExit(f"no mirror for res-{int(number):03d} in {folder}")
        row = research_row(match[-1])
        if posted is None or row["res"] not in posted:
            rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("write", "notion-status", "check", "research-rows"))
    parser.add_argument("--areas", type=Path, help="10.PRODUCT folder holding 12.WEBSITE..15.RELEASES")
    parser.add_argument("--res", nargs="*", default=[], help="research ids for research-rows, e.g. 075 077 078")
    parser.add_argument("--publish", action="store_true", help="research-rows: create the rows (default prints them)")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.action == "research-rows":
        folder = research_dir()
        if not folder:
            raise SystemExit(f"{RESEARCH} not found above this checkout")
        posted = posted_research()
        rows = research_rows(args.res, folder, posted)
        print(f"dedup: {'unverified (Notion unreadable)' if posted is None else f'{len(posted)} res rows already posted'}; "
              f"{len(rows)} to write")
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        if args.publish:
            publish_research(rows, posted)
        return 0
    rel = released()
    areas = args.areas or default_areas()
    if args.action == "notion-status":
        print(notion_status(rel))
        return 0
    if args.action == "write":
        changed = write(rel, areas)
        print(f"{rel['build_id']}: " + (", ".join(changed) if changed else "every written surface already current"))
        if not areas:
            print("area READMEs skipped: no 12.WEBSITE folder above this checkout (run on the release machine)")
        return 0
    results = check(rel, areas)
    for surface, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {surface}: {detail}")
    failed = [surface for surface, ok, _ in results if not ok]
    print(f"{rel['build_id']}: {len(results) - len(failed)}/{len(results)} surfaces agree")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
