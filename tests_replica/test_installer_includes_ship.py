"""Court: every installer/*.iss that ArchHub.iss #includes (at any depth) is admitted by
build_release.ps1's snapshot allowlist, so a release build never refuses or drops it
(host_file_staging.iss was missing once; c291be7)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "installer"


def _includes(path, seen=None):
    seen = set() if seen is None else seen
    for name in re.findall(r'(?m)^\s*#include\s+"([^"]+\.iss)"', path.read_text(encoding="utf-8")):
        included = (path.parent / name).resolve()
        if included not in seen:
            seen.add(included)
            _includes(included, seen)
    return seen


def test_every_included_iss_is_in_the_release_allowlist():
    build = (INSTALLER / "build_release.ps1").read_text(encoding="utf-8")
    included = _includes(INSTALLER / "ArchHub.iss")
    assert included, "ArchHub.iss includes nothing: the court would prove nothing"
    missing = []
    for path in sorted(included):
        relative = path.relative_to(ROOT).as_posix()
        assert relative.startswith("installer/"), relative
        if "'%s'" % relative not in build:
            missing.append(relative)
    assert missing == [], "add to build_release.ps1's allowlist: %s" % missing
