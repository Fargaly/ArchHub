"""UPDATERWORKS: the real hand-off, end to end, in a throwaway profile.

A local release feed on 127.0.0.1 serves a real Inno Setup installer built here
with ISCC. The updater downloads and verifies it, then the real hidden helper
(`quiet_update.py --apply-staged APP --relaunch`) waits for a desktop that still
holds the profile, runs the real Setup /VERYSILENT into a temp install folder,
relaunches ArchHub.vbs through wscript and settles on the boot acknowledgment.
A process standing in for Revit keeps a file under the install folder open the
whole time and must survive. No window may appear. Nothing outside tmp_path is
written: every profile variable points into it.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from nodelang import quiet_update as qu
from nodelang.host_addin_retarget import HEADER, save_receipt

ROOT = Path(__file__).resolve().parents[2]
QUIET_UPDATE = ROOT / "01.APP" / "nodelang" / "quiet_update.py"
ISCC = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe"
INSTALLED = ("20261119-0904-665c785", "2026-11-19T05:04:00Z")
OFFERED = ("20261120-0100-aaaaaaa", "2026-11-19T21:00:00Z")
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

pytestmark = [pytest.mark.skipif(os.name != "nt", reason="Windows hand-off"),
              pytest.mark.skipif(not ISCC.is_file(), reason="Inno Setup 6 ISCC.exe is required")]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _windowless_python() -> str:
    python = Path(sys.executable)
    candidate = python.with_name("pythonw.exe")
    return str(candidate if candidate.is_file() else python)


def _build_installer(work: Path, *, fail: bool) -> Path:
    """A tiny real Inno installer that lays down what ArchHub.iss proves at the end: payload, manifest, receipt, BUILD_ID."""
    payload = work / "payload"
    (payload / "nodelang").mkdir(parents=True)
    # Setup's manifest must cover the three product roots, as host_addin_retarget.manifest_rows requires.
    files = {"nodelang/payload.py": b"BUILD = %r\n" % OFFERED[0].encode(),
             "app/index.html": b"<!doctype html><title>court</title>\n",
             "bridges/rhino/court_bridge.py": b"# court bridge\n"}
    for relative, data in files.items():
        (payload / relative).parent.mkdir(parents=True, exist_ok=True)
        (payload / relative).write_bytes(data)
    raw = ("%s\npath\tsha256\n" % HEADER + "".join(
        "%s\t%s\n" % (relative, _sha(data)) for relative, data in files.items())).encode("utf-8")
    (payload / "source-manifest.tsv").write_bytes(raw)
    (payload / "BUILD_METADATA.json").write_text(json.dumps(
        {"format": 1, "build_id": OFFERED[0], "built_at": OFFERED[1]}) + "\n", encoding="utf-8")
    save_receipt(payload, raw, {}, ())
    script = work / "tiny.iss"
    script.write_text("\n".join([
        "[Setup]",
        "AppName=ArchHub Handoff Court", "AppVersion=1", "AppId=ArchHubHandoffCourt",
        r"DefaultDirName={localappdata}\ArchHubHandoffCourt", "PrivilegesRequired=lowest",
        "Uninstallable=no", "CreateUninstallRegKey=no",
        "CloseApplications=no", "RestartApplications=no", "DisableDirPage=yes", "DisableProgramGroupPage=yes",
        "DisableReadyPage=yes", "DisableFinishedPage=yes", "DisableWelcomePage=yes",
        "OutputDir=" + str(work / "out"), "OutputBaseFilename=" + qu.ASSET_NAME[:-4], "Compression=none",
        "[Files]",
        'Source: "%s\\nodelang\\payload.py"; DestDir: "{app}\\nodelang"; Flags: ignoreversion' % payload,
        'Source: "%s\\app\\index.html"; DestDir: "{app}\\app"; Flags: ignoreversion' % payload,
        'Source: "%s\\bridges\\rhino\\court_bridge.py"; DestDir: "{app}\\bridges\\rhino"; Flags: ignoreversion' % payload,
        'Source: "%s\\source-manifest.tsv"; DestDir: "{app}"; Flags: ignoreversion' % payload,
        'Source: "%s\\BUILD_METADATA.json"; DestDir: "{app}"; Flags: ignoreversion' % payload,
        'Source: "%s\\installed-source-state.json"; DestDir: "{app}"; Flags: ignoreversion' % payload,
        "[Code]",
        "function InitializeSetup(): Boolean;",
        "begin",
        "  Result := %s;" % ("False" if fail else "True"),
        "end;",
        # As ArchHub.iss: BUILD_ID is published last, freshly written, after every file is in place.
        "procedure CurStepChanged(CurStep: TSetupStep);",
        "begin",
        "  if CurStep = ssPostInstall then",
        "    if not SaveStringToFile(ExpandConstant('{app}\\BUILD_ID'), '%s', False) then" % OFFERED[0],
        "      RaiseException('BUILD_ID could not be saved');",
        "end;", ""]), encoding="utf-8")
    subprocess.run([str(ISCC), "/Q", str(script)], check=True, creationflags=HIDDEN, timeout=300)
    return work / "out" / qu.ASSET_NAME


def _installed_app(folder: Path, state: Path) -> Path:
    (folder / "bridges" / "revit").mkdir(parents=True)
    (folder / "BUILD_ID").write_text(INSTALLED[0], encoding="ascii")
    (folder / "BUILD_METADATA.json").write_text(json.dumps(
        {"format": 1, "build_id": INSTALLED[0], "built_at": INSTALLED[1]}) + "\n", encoding="utf-8")
    (folder / "bridges" / "revit" / "ArchHub.Revit.dll").write_bytes(b"MZ court bridge")
    # The relaunch runs the REAL launcher.py start path (profile lock, pre-boot update apply/recovery,
    # then the desktop) from a copy of the real nodelang. Only the Qt window module is replaced: it
    # records the build it booted and acknowledges it exactly as the real confirm_boot does.
    import shutil
    shutil.copytree(ROOT / "01.APP" / "nodelang", folder / "nodelang",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (folder / "nodelang" / "nograph_launcher.py").write_text("\n".join([
        '"""Court stand-in for the Qt desktop: no window."""',
        "import time",
        "from pathlib import Path",
        "",
        "",
        "def run(state_dir, instance_lock=None, serve_launch_requests=None):",
        "    from .quiet_update import confirm_when_free, installed_build_id",
        "    app = Path(__file__).resolve().parents[1]",
        "    with (app / 'launches.txt').open('a') as log:",
        "        log.write(installed_build_id(app) + ' booted\\n')",
        "    confirm_when_free(Path(state_dir), app)",
        "    time.sleep(3)",
        "    return 0", ""]), encoding="utf-8")
    (folder / "ArchHub.vbs").write_text(
        'Set sh = CreateObject("WScript.Shell")\r\n'
        'WScript.Quit sh.Run("""%s"" -s ""%s""", 0, True)\r\n'
        % (_windowless_python(), folder / "nodelang" / "launcher.py"), encoding="ascii")
    return folder


class _Feed(BaseHTTPRequestHandler):
    release, installer = b"", b""

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        body = _Feed.release if path == "/latest" else _Feed.installer if path.endswith("/" + qu.ASSET_NAME) else None
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def _visible_windows(pids: set[int]) -> list[str]:
    """Visible top-level windows owned by any process of this court's tree."""
    user = ctypes.WinDLL("user32", use_last_error=True)
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user.IsWindowVisible(hwnd):
            found.append("pid %d hwnd %d" % (pid.value, hwnd))
        return True

    user.EnumWindows(each, 0)
    return found


def _court_pids(root_pid: int, tree: Path) -> set[int]:
    import psutil
    pids = set()
    try:
        pids |= {p.pid for p in psutil.Process(root_pid).children(recursive=True)} | {root_pid}
    except psutil.Error:
        pass
    for process in psutil.process_iter(["pid", "exe", "cmdline"]):
        text = " ".join([process.info.get("exe") or ""] + list(process.info.get("cmdline") or []))
        if str(tree).lower() in text.lower():
            pids.add(process.info["pid"])
    return pids


@pytest.mark.parametrize("fail", [False, True], ids=["installs-and-reopens", "setup-fails-old-build-reopens"])
def test_real_handoff_installs_hidden_keeps_revit_and_settles(tmp_path, monkeypatch, fail):
    (tmp_path / "workshop").mkdir()
    monkeypatch.setenv("WORKSHOP_STATE_DIR", str(tmp_path / "workshop"))
    for name in ("USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "ARCHHUB_TEST_STATE_DIR", "WORKSHOP_STATE_DIR"):
        assert Path(os.environ[name]).is_relative_to(tmp_path), name + " is not isolated"
    state = Path(os.environ["ARCHHUB_TEST_STATE_DIR"])
    app = _installed_app(tmp_path / "install", state)
    installer = _build_installer(tmp_path / "build", fail=fail)
    _Feed.installer = installer.read_bytes()

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Feed)
    port = server.server_address[1]
    _Feed.release = json.dumps({
        "tag_name": "build-" + OFFERED[0], "draft": False, "prerelease": False,
        "body": "## Build\nBUILD_ID: %s\nBUILT_AT: %s\nSHA256 %s: %s\n" % (
            OFFERED[0], OFFERED[1], qu.ASSET_NAME, _sha(_Feed.installer)),
        "assets": [{"name": qu.ASSET_NAME, "size": len(_Feed.installer),
                    "browser_download_url": "http://127.0.0.1:%d/download/%s" % (port, qu.ASSET_NAME)}],
    }).encode("utf-8")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("ARCHHUB_UPDATE_FEED", "http://127.0.0.1:%d/latest" % port)
    revit = desktop = helper = None
    try:
        staged = qu.check_for_update(state, app)
        assert staged["staged"] is True and staged["status"] == "staged", staged

        # Revit keeps its bridge DLL open from the install folder for the whole install.
        revit = subprocess.Popen([sys.executable, "-c",
            "import sys, time; f = open(sys.argv[1], 'rb'); time.sleep(600)",
            str(app / "bridges" / "revit" / "ArchHub.Revit.dll")], creationflags=HIDDEN)
        # The desktop that asked for the restart still holds the profile for a few seconds.
        desktop = subprocess.Popen([sys.executable, "-c",
            "import sys, time; sys.path.insert(0, sys.argv[1]);"
            "from nodelang.profile_instance import ProfileInstance; l = ProfileInstance();"
            "assert l.handle is not None; time.sleep(4); l.close()", str(ROOT / "01.APP")], creationflags=HIDDEN)
        time.sleep(1.0)
        assert qu._desktop_running()
        started = time.monotonic()
        errors = (tmp_path / "helper-stderr.txt").open("wb")
        helper = subprocess.Popen([_windowless_python(), "-s", str(QUIET_UPDATE),
                                   "--apply-staged", str(app), "--relaunch"], creationflags=HIDDEN, close_fds=True,
                                  stdout=errors, stderr=errors)
        windows = []
        while helper.poll() is None and time.monotonic() - started < 240:
            windows += _visible_windows(_court_pids(helper.pid, tmp_path))
            time.sleep(0.1)
        assert helper.poll() is not None, "hand-off did not finish within 240 s"
        assert windows == [], windows
        assert revit.poll() is None, "the Revit stand-in was stopped"
        # After a failed Setup the old build is reopened fire-and-forget; give that launch time to start.
        deadline = time.monotonic() + 60
        while not (app / "launches.txt").is_file() and time.monotonic() < deadline:
            time.sleep(0.2)
        marker = json.loads((state / "updates" / "staged.json").read_text(encoding="utf-8"))
        log = (state / "logs" / "updates.log").read_text(encoding="utf-8")
        errors.close()
        launcher_log = state / "logs" / "launcher.log"
        launcher_text = launcher_log.read_text(encoding="utf-8", errors="replace") if launcher_log.is_file() else ""
        evidence = "marker=%s\nupdates.log=%s\nhelper=%s\nlauncher.log tail=%s" % (
            marker, log, (tmp_path / "helper-stderr.txt").read_text(errors="replace"), launcher_text[-3000:])
        assert (app / "launches.txt").is_file(), "ArchHub was never relaunched\n" + evidence
        launches = (app / "launches.txt").read_text().splitlines()
        if fail:
            assert helper.returncode == 1, evidence
            # Recorded as failed: the real launcher.py start opens the old build and does not run Setup again.
            assert marker["phase"] == "rolled_back" and marker["build_id"] == OFFERED[0], evidence
            assert (app / "BUILD_ID").read_text() == INSTALLED[0]
            assert launches == [INSTALLED[0] + " booted"], evidence
            assert log.count("installer failed (exit") == 1, evidence
            assert "install failed" not in launcher_text and "installed build" not in launcher_text, evidence
        else:
            assert helper.returncode == 0, evidence
            assert marker["phase"] == "confirmed" and marker["build_id"] == OFFERED[0], evidence
            assert (app / "BUILD_ID").read_text() == OFFERED[0]
            assert launches[-1] == OFFERED[0] + " booted", evidence
            assert "update: installed %s" % OFFERED[0] in log and "update: confirmed %s" % OFFERED[0] in log
    finally:
        server.shutdown()
        for process in (helper, desktop, revit):
            if process is not None and process.poll() is None:
                process.terminate()  # only this court's own children
                process.wait(10)
