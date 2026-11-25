"""release_surfaces.py: one release propagates to every surface, and the check names each one that disagrees.

Network, Notion and Fly are replaced by fakes; files are written only under tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "03.TOOLS/packaging/website"))
import release_surfaces as rs  # noqa: E402

BODY = ("- WhatsApp Business supports inbox reads for linked numbers.\n"
        "- The desktop keeps a verified sign-in through a brief connection failure.\n\n"
        "## Build\nBUILD_ID: 20261125-1227-0d3464c\nBUILT_AT: 2026-11-25T09:01:38Z\n"
        "SHA256 ArchHub-Setup-0.exe: " + "b" * 64 + "\nSOURCE_REVISION: 0d3464c786933c5156f04b4a3bdedf26e00ad27e\n")
RELEASES = [{"tag_name": "build-20261124-1422-7a222b2", "published_at": "2026-11-24T14:00:00Z", "body": "## Build\nBUILD_ID: 20261124-1422-7a222b2\n"},
            {"tag_name": "build-20261125-1227-0d3464c", "published_at": "2026-11-25T09:30:00Z", "body": BODY}]


def test_released_reads_the_newest_build_block_and_unheaded_notes():
    rel = rs.released(RELEASES)
    assert rel["build_id"] == "20261125-1227-0d3464c"
    assert rel["source"].startswith("0d3464c7")
    assert rel["notes"][0].startswith("WhatsApp Business")


def test_changelog_entry_keeps_notes_written_above_the_build_block():
    entry = rs.sync_changelog.entry_from_release(RELEASES[1])
    assert "- WhatsApp Business supports inbox reads for linked numbers." in entry
    assert "Published build" not in entry


def test_foreign_builds_flags_other_builds_only():
    rel = rs.released(RELEASES)
    text = "The November 20 stable build (9d03226d) differs from 20261124-0344-a4980b0; this is 20261125-1227-0d3464c (0d3464c7)."
    assert rs.foreign_builds(text, rel) == ["November 20 stable build", "(9d03226d)", "20261124-0344-a4980b0"]


def test_current_in_app_docs_name_no_other_build():
    rel = rs.released(RELEASES)
    assert rs.foreign_builds(rs.docs_text(None), rel) == []


def test_check_passes_when_every_surface_agrees_and_fails_each_that_does_not(tmp_path, monkeypatch):
    rel = rs.released(RELEASES)
    fly = tmp_path / "fly.toml"
    fly.write_text('[env]\n  ARCHHUB_VERSION = "0"\n', encoding="utf-8")
    monkeypatch.setattr(rs, "FLY_TOML", fly)
    monkeypatch.setattr(rs, "ROOT", tmp_path)
    monkeypatch.setattr(rs, "docs_text", lambda revision: "guides for this build")
    (tmp_path / "CHANGELOG.md").write_text("## Next build\n\n## " + rel["build_id"] + "\n\n"
                                           + "".join(f"- {n}\n" for n in rel["notes"]), encoding="utf-8")
    pages = {rs.SITE + "/download.json": json.dumps({"build_id": rel["build_id"]}),
             rs.SITE + "/changelog/": "<h2>2026-11-25 · 12:27</h2>",
             rs.SITE + "/docs/getting-started/": "<p>Build 20261125-1227-0d3464c</p>",
             rs.CLOUD + "/healthz": json.dumps({"ok": True, "version": rel["build_id"]})}
    notion = lambda: "Current build:** 20261125-1227-0d3464c ([download]"  # noqa: E731
    areas = tmp_path / "areas"
    areas.mkdir()
    rs.write(rel, areas, live={"web": "v63", "cloud": "v117", "cloud_commit": "ba485de7", "cloud_version": rel["build_id"]})
    (areas / "11.ARCHHUB-APP").mkdir()
    for _, _, links, *_ in rs.AREAS.values():
        for _, target in links:
            path = areas / "12.WEBSITE" / target
            path.parent.mkdir(parents=True, exist_ok=True)
            if not target.endswith("/"):
                path.write_text("x", encoding="utf-8")
    assert 'ARCHHUB_VERSION = "20261125-1227-0d3464c"' in fly.read_text(encoding="utf-8")

    results = rs.check(rel, areas, get=pages.get, notion=notion)
    assert [s for s, ok, _ in results if not ok] == []

    stale = dict(pages)
    stale[rs.SITE + "/changelog/"] = "<h2>2026-11-24 · 03:44</h2>"
    stale[rs.SITE + "/docs/getting-started/"] = "<p>The November 20 stable build (9d03226d)</p>"
    (areas / "12.WEBSITE" / "notes.txt").write_text("loose", encoding="utf-8")
    (areas / "14.DOCS" / "README.md").write_text("[gone](../11.ARCHHUB-APP/missing.md)", encoding="utf-8")
    failed = [s for s, ok, _ in rs.check(rel, areas, get=stale.get, notion=lambda: None) if not ok]
    assert failed == ["website changelog", "website docs", "notion", "area 12.WEBSITE", "area 14.DOCS"]


def test_area_readme_never_carries_the_fly_user_and_keeps_links_relative():
    rel = rs.released(RELEASES)
    text = rs.area_readme("13.COCKPIT-CLOUD", rel, {"cloud": "v117 (2026-11-25T10:17:20Z)", "cloud_commit": "ba485de7",
                                                    "cloud_version": rel["build_id"]})
    assert "v117" in text and "ba485de7" in text and "@" not in text
    assert all(not t.startswith(("/", "C:")) for t in rs.LINK.findall(text) if "://" not in t)


def test_research_rows_skip_posted_ids_and_follow_the_library_schema(tmp_path):
    for n, day in (("075", "2026-11-23"), ("077", "2026-11-24")):
        (tmp_path / f"archhub-claude-doc-res-{n}-{day}.md").write_text(
            f"# ArchHub R&D: {day}\n\n## R&D: {day}\n**Today.** Free models listed.\n\n### Proposals\n"
            "| Proposal | For whom |\n|---|---|\n| Drop the dead slug | users |\n", encoding="utf-8")
    query = lambda tool, args: {"structuredContent": {"results": [{"Name": "R&D: 2026-11-23 (res-075)"}]}}  # noqa: E731
    posted = rs.posted_research(query)
    assert posted == {"res-075"}
    rows = rs.research_rows(["075", "077"], tmp_path, posted)
    assert [r["res"] for r in rows] == ["res-077"]
    props = rows[0]["properties"]
    assert props["Name"] == "R&D: 2026-11-24 (res-077)"
    assert props["How to apply"] == "Drop the dead slug"
    assert props["Status"] == "Read" and props["date:Read on:start"] == "2026-11-24"
    with pytest.raises(SystemExit):
        rs.research_rows(["099"], tmp_path, posted)
