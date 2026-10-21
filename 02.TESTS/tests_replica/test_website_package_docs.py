"""Package inventory and byte-preserving archival of retired v1 documentation."""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ISCC = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")


def test_installer_file_list_excludes_stale_v1_documentation():
    """Resolve local [Files] globs, then inspect destinations actually packaged."""
    text = (ROOT / "03.TOOLS/installer/ArchHub.iss").read_text(encoding="utf-8")
    section = text.split("[Files]", 1)[1].split("[InstallDelete]", 1)[0]
    destinations = []
    for source, destination in re.findall(r'Source: "([^"\n]+)"; DestDir: "([^"\n]+)"', section):
        if not source.startswith("..\\"):
            continue  # Compiler-supplied runtime/wheels/metadata, not repo docs.
        source = source[3:].replace("\\", "/")
        if source.endswith("/*"):
            prefix = source[:-2]
            for file in (ROOT / prefix).rglob("*"):
                if file.is_file():
                    destinations.append(destination + "\\" + file.relative_to(ROOT / prefix).as_posix())
        else:
            assert (ROOT / source).is_file(), source
            destinations.append(destination + "\\" + Path(source).name)
    forbidden = {"{app}\\readme.md", "{app}\\quickstart.md", "{app}\\version"}
    assert destinations
    assert not forbidden.intersection(value.lower() for value in destinations)
    assert not [value for value in destinations if value.lower().startswith("{app}\\docs\\")]


def test_retired_docs_are_not_an_active_handwritten_copy():
    for name in ("SETUP.txt", "SETUP.bat", "GAPS.md", "NODE-LANGUAGE-VISUAL-GUIDE.md",
                 "NODE-LANGUAGE-100-LAYER-ARCHITECTURE.md", "INTERACTION-LOCALITY-AUTHORITY-PLAN.md"):
        assert not (ROOT / name).exists(), name
    assert not any(p.is_file() for p in (ROOT / "04.DOCS" / "archive").rglob("*"))


@pytest.mark.skipif(sys.platform != "win32" or not ISCC.is_file(), reason="needs Inno Setup 6 on Windows")
def test_v1_docs_archive_preserves_bytes_and_refuses_changed_files(tmp_path):
    """Compile only the real archive helper; run it against a fake install root."""
    root = tmp_path / "ArchHub"
    root.mkdir()
    old = b"# ArchHub (v1.4.0-alpha)\n"
    (root / "README.md").write_bytes(old)
    (root / "QUICKSTART.md").write_bytes(b"personal notes changed since v1\n")
    (root / "VERSION").write_bytes(b"0\n")
    (root / "BUILD_ID").write_bytes(b"real-current-build\n")
    (root / "graph.sqlite3").write_bytes(b"keep graph")
    helper = ROOT / "03.TOOLS/installer/legacy_sweep.iss"
    script = tmp_path / "docs-court.iss"
    digest = hashlib.sha256(old).hexdigest()
    script.write_text(
        "[Setup]\nAppName=ArchHubDocsCourt\nAppVersion=1\nCreateAppDir=no\n"
        "Uninstallable=no\nPrivilegesRequired=lowest\nOutputDir=%s\n"
        "OutputBaseFilename=docs-court\n\n[Code]\n#include \"%s\"\n"
        "function InitializeSetup(): Boolean;\nvar Root: String;\nbegin\n"
        "Root := ExpandConstant('{param:root}');\n"
        "ArchiveLegacyDocFile(Root, 'README.md', '%s');\n"
        "ArchiveLegacyDocFile(Root, 'QUICKSTART.md', '%s');\n"
        "ArchiveLegacyDocFile(Root, 'VERSION', '%s');\n"
        "Result := False;\nend;\n" % (tmp_path, helper, digest, digest, hashlib.sha256(b"0\n").hexdigest()),
        encoding="utf-8")
    built = subprocess.run([str(ISCC), "/Q", str(script)], capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stdout + built.stderr
    exe = tmp_path / "docs-court.exe"
    def run():
        subprocess.run([str(exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", f"/root={root}"], timeout=60)
    run()
    target = root / ".retired-v1-docs/README.md"
    assert target.read_bytes() == old
    assert not (root / "README.md").exists()
    assert (root / "QUICKSTART.md").read_bytes() == b"personal notes changed since v1\n"
    assert (root / "VERSION").read_bytes() == b"0\n"
    assert (root / "BUILD_ID").read_bytes() == b"real-current-build\n"
    assert (root / "graph.sqlite3").read_bytes() == b"keep graph"
    # Archive collisions and checkouts are retained, never overwritten or swept.
    (root / "README.md").write_bytes(old)
    target.write_bytes(b"prior archive")
    run()
    assert (root / "README.md").read_bytes() == old
    assert target.read_bytes() == b"prior archive"
    target.unlink()
    (root / ".git").mkdir()
    run()
    assert (root / "README.md").read_bytes() == old
    assert not target.exists()
