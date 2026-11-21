"""A small Inno Setup using the shipped product-license file entry and prune owner."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from nodelang import host_addin_retarget as prune

ROOT = Path(__file__).resolve().parents[2]


def test_setup_product_license(tmp_path_factory, monkeypatch):
    # Inno expands source paths before resolving .. on managed Windows checkouts.
    tmp_path = tmp_path_factory.mktemp("lic")
    compiler = shutil.which("ISCC") or "C:/Program Files (x86)/Inno Setup 6/ISCC.exe"
    if os.name != "nt" or not Path(compiler).is_file():
        pytest.skip("Windows Inno Setup required")
    payload = tmp_path / "payload"
    installer = payload / "installer"
    installer.mkdir(parents=True)
    license_bytes = (ROOT / "LICENSE.md").read_bytes()
    (payload / "LICENSE.md").write_bytes(license_bytes)
    notice = Path("packaging/windows/licenses/ArchHub-components-MIT.txt")
    (payload / notice).parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "03.TOOLS" / notice, payload / notice)
    for name in (prune.LEGACY_IDENTITY_FILE, "nodelang/data/baboom/persona.json", "app/__init__.py",
                 "app/credential_lock.py", "app/secrets_store.py", "bridges/rhino/archhub_mcp.py",
                 "bridges/blender/archhub_mcp/__init__.py", "bridges/sources/max_mcp/max_mcp_startup.py"):
        target = payload / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / "01.APP" / name).read_bytes())
    manifest = payload / "source-manifest.tsv"
    prune.write_manifest(payload, tmp_path / "hosts", manifest)
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    script = (ROOT / "03.TOOLS/installer/ArchHub.iss").read_text(encoding="utf-8")
    lines = [line for line in script.splitlines()
             if line.startswith(('Source: "..\\LICENSE.md";', 'Source: "..\\packaging\\windows\\licenses\\ArchHub-components-MIT.txt";'))]
    assert len(lines) == 2
    lines.append('Source: "..\\source-manifest.tsv"; DestDir: "{app}"; Flags: ignoreversion')
    for line in manifest.read_text().splitlines()[2:]:
        name = Path(line.split("\t")[0])
        if name.name == "LICENSE.md":
            continue
        src = Path("bridges/sources/max_mcp/max_mcp_startup.py") if name.name == "max_mcp_startup.py" else name
        lines.append(f'Source: "..\\{src}"; DestDir: "{{app}}\\{name.parent}"; Flags: ignoreversion')
    helper = Path(prune.__file__).resolve()
    iss = installer / "license.iss"
    iss.write_text(f"""[Setup]
AppName=ArchHub License Court
AppVersion=1
DefaultDirName={{param:dest}}
CreateUninstallRegKey=no
UsePreviousAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
CloseApplications=no
OutputBaseFilename=license-court
[Files]
""" + "\n".join(lines) + f"""
[Code]
procedure CurStepChanged(Step: TSetupStep);
var Args: String; Code: Integer;
begin
  if (Step <> ssInstall) and (Step <> ssPostInstall) then exit;
  if Step = ssInstall then Args := '--prepare "' + ExpandConstant('{{app}}') + '" "{manifest}"'
  else Args := '--prune "' + ExpandConstant('{{app}}') + '"';
  if not Exec('{sys.executable}', '-I -B "{helper}" ' + Args + ' {digest}', '', SW_HIDE, ewWaitUntilTerminated, Code)
     or (Code <> 0) then RaiseException('License owner refused: ' + IntToStr(Code));
end;
""", encoding="utf-8-sig")
    subprocess.run([compiler, "/Q", "/O" + str(tmp_path), str(iss)], check=True, timeout=90)
    old_lf = (payload / notice).read_bytes().replace(b"\r\n", b"\n")
    for case in ("fresh", "lf", "crlf", "modified", "linked", "linked-current", "modified-current", "open-reader"):
        profile = tmp_path / case
        root = profile / "ArchHub"
        root.mkdir(parents=True)
        monkeypatch.setenv("LOCALAPPDATA", str(profile))
        old = root / "LICENSE"
        legacy = old_lf.replace(b"\n", b"\r\n") if case == "crlf" else old_lf
        if case in ("lf", "crlf", "modified-current", "open-reader"):
            old.write_bytes(legacy)
        elif case == "modified":
            old.write_bytes(b"user-owned terms")
        elif case in ("linked", "linked-current"):
            outside = profile / "outside"
            outside.mkdir()
            (outside / "marker").write_bytes(b"keep")
            linked = old if case == "linked" else root / "LICENSE.md"
            subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(linked), str(outside)], check=True)
            if case == "linked-current":
                old.write_bytes(legacy)
        if case == "modified-current":
            (root / "LICENSE.md").write_bytes(b"custom current terms")
        setup = [str(tmp_path / "license-court.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES",
                 "/NORESTART", "/dest=" + str(root)]
        if case == "open-reader":
            with old.open("rb") as reader:
                subprocess.run(setup, check=True, timeout=90)
                assert reader.read() == legacy and old.exists()
                assert json.loads((root / prune.RECEIPT).read_bytes())["manifest"] == manifest.read_bytes().decode()
        result = subprocess.run(setup, timeout=90)
        if case == "linked-current":
            assert result.returncode != 0 and old.read_bytes() == legacy
            assert linked.is_junction() and (outside / "marker").read_bytes() == b"keep"
            continue
        if case == "modified-current":
            assert result.returncode != 0 and old.read_bytes() == legacy
            assert (root / "LICENSE.md").read_bytes() == b"custom current terms"
            continue
        assert result.returncode == 0
        assert json.loads((root / prune.RECEIPT).read_bytes())["manifest"] == manifest.read_bytes().decode()
        assert (root / "LICENSE.md").read_bytes() == license_bytes
        assert (root / "licenses" / notice.name).read_bytes() == (payload / notice).read_bytes()
        if case == "linked":
            assert old.is_junction() and (outside / "marker").read_bytes() == b"keep"
        elif case == "modified":
            assert old.read_bytes() == b"user-owned terms"
        else:
            assert not os.path.lexists(old)
