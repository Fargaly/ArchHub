"""The skill library is the same on every machine that runs ArchHub."""
from __future__ import annotations

from pathlib import Path

from nodelang import pipeline_engines as engines


def test_catalogue_reads_the_shipped_library_when_home_has_none(tmp_path, monkeypatch):
    shipped = tmp_path / "app" / "skills" / "claude" / "ponytail"
    shipped.mkdir(parents=True)
    (shipped / "SKILL.md").write_text("---\nname: ponytail\ndescription: >\n  Forces the laziest\n  solution that works.\n---\n", encoding="utf-8")
    fake_module = tmp_path / "app" / "nodelang" / "pipeline_engines.py"
    fake_module.parent.mkdir(parents=True)
    monkeypatch.setattr(engines, "__file__", str(fake_module))
    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path / "nohome"))
    out, note = engines.skills_catalogue({}, {})
    names = [(r["source"], r["name"]) for r in out["out"]]
    assert ("claude", "ponytail") in names, "a colleague with no ~/.claude still sees the shipped library"
    desc = next(r["description"] for r in out["out"] if r["name"] == "ponytail")
    assert desc == "Forces the laziest solution that works.", "a folded YAML description is joined, not a lone >"


def test_installer_ships_no_builder_home_skills():
    # installer/build_release.ps1: "No installed state, builder-home skills,
    # PyInstaller runtime, or implicit sibling checkout enters this package."
    # The builder's ~/.claude and ~/.codex skill folders are private to that
    # machine (AGENTS.md hard rule 7); the catalogue still reads a shipped
    # {app}/skills library when one is packaged from governed source.
    iss = (Path(engines.__file__).resolve().parents[1] / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    assert r'.claude\skills' not in iss
    assert r'.codex\skills' not in iss
    assert 'GetEnv("USERPROFILE")' not in iss
