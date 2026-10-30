"""The release gate's installed-build mode installs into a temp profile, never the founder's account."""
from pathlib import Path

import pytest

from tools.real_app_check import installed_build as ib

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "03.TOOLS" / "installer"


def _isolated(tmp_path):
    dirs = ib.profile_dirs(tmp_path / "work")
    text = ib.isolated_script((INSTALLER / "ArchHub.iss").read_text(encoding="utf-8"), INSTALLER, dirs,
                              r"C:\Py\python.exe", tmp_path / "work")
    return dirs, text


def test_the_real_installer_script_is_pointed_entirely_into_the_temp_profile(tmp_path):
    dirs, text = _isolated(tmp_path)
    every = text + "".join(p.read_text(encoding="utf-8-sig") for p in (tmp_path / "work").glob("*.iss"))
    for constant in ("{localappdata}", "{userappdata}", "{autodesktop}", "{group}"):
        assert constant not in every
    assert "DefaultDirName=%s\\ArchHub" % dirs["LOCALAPPDATA"] in text
    assert "CreateUninstallRegKey=no" in text and ib.GATE_APP_ID in text
    assert "B6C0E10F-1F8E-4AAB-9A8F-4F2E3A2C4BAE" not in text  # never the shipped Apps & Features entry
    assert "RemoveRetiredRuntimeTask(CleanCoordinationTask)" not in text  # no schtasks against the real account
    assert "Result := 'C:\\Py\\python.exe';" in text
    # every nested include is the redirected copy, so ISPP never reads an original that names the real account
    includes = [line.split('"')[1] for line in every.splitlines() if line.startswith("#include")]
    assert includes and all(Path(path).parent == tmp_path / "work" for path in includes)


def test_clean_removes_only_a_folder_the_gate_created(tmp_path):
    foreign = tmp_path / "someone-else"
    foreign.mkdir()
    with pytest.raises(ValueError):
        ib.clean(foreign)
    assert foreign.is_dir()
    _isolated(tmp_path)
    (tmp_path / "work" / "ArchHub.isolated.iss").write_text("x", encoding="utf-8")
    ib.clean(tmp_path / "work")
    assert not (tmp_path / "work").exists()


def test_the_manifest_check_catches_a_changed_installed_file(tmp_path):
    release, app = tmp_path / "release", tmp_path / "app"
    (app / "nodelang").mkdir(parents=True)
    release.mkdir()
    (app / "nodelang" / "a.py").write_bytes(b"one")
    import hashlib
    digest = hashlib.sha256(b"one").hexdigest()
    (release / "source-manifest.tsv").write_text(
        "ARCHHUB_RELEASE_SOURCE_MANIFEST_V2\nsource\tpath\tbytes\tsha256\nselected\tnodelang/a.py\t3\t%s\n" % digest,
        encoding="utf-8")
    assert ib.manifest_check(release, app) == {"checked": 1, "mismatched": [], "ok": True}
    (app / "nodelang" / "a.py").write_bytes(b"two")
    assert ib.manifest_check(release, app)["mismatched"] == ["nodelang/a.py"]
