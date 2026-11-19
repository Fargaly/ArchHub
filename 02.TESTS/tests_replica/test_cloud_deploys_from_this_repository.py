"""The live cloud (archhub-cloud) deploys from this repository.

12.PRODUCTION is retired; 06.CLOUD/cloud_backend/ lives here. The court runs the REAL deploy.ps1 with an inert
flyctl that only records what it is asked, in a minimal child environment (no inherited credentials; flyctl
resolves only to the inert shim, checked first), and a local stand-in for its required public health address, so
nothing is deployed and no network is used. It then checks the build the deploy asked for: the context, the Dockerfile and ignore file it passed, that
every file the Dockerfile copies is in that context and survives the ignore file, and that the app it starts is
among them. The inert transport reports no new release, so the script stops before its live health check.
"""
from fnmatch import fnmatch
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "06.CLOUD" / "cloud_backend"
RECORDER = r'''
import json, sys
args = sys.argv[2:]
with open(sys.argv[1], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\n")
answers = {("auth", "whoami"): "tester@example.invalid", ("apps", "list"): '[{"Name": "archhub-cloud"}]',
           ("volumes", "list"): '[{"Name": "archhub_data"}]', ("releases",): '[{"Version": 1, "Status": "complete"}]'}
for key, text in answers.items():
    if tuple(args[:len(key)]) == key:
        print(text)
'''


class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _admitted(relative, patterns):
    """Docker ignore rules: the last matching pattern wins; '!' re-admits; a directory pattern covers its files."""
    keep = True
    for pattern in patterns:
        negate, rule = pattern.startswith("!"), pattern.lstrip("!").rstrip("/")
        if rule == "**" or fnmatch(relative, rule) or relative.startswith(rule + "/"):
            keep = negate
    return keep


def _inert_environment(tmp_path, log):
    """A minimal child environment: PATH is the inert flyctl directory plus only what pwsh itself needs; no
    inherited variables, so no provider credential (FLY_API_TOKEN, FLY_ACCESS_TOKEN, ...) can reach the script."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "recorder.py").write_text(RECORDER, encoding="utf-8")
    if os.name == "nt":
        shim = bin_dir / "flyctl.cmd"
        shim.write_text('@echo off\r\n"%s" "%s" "%s" %%*\r\n' % (sys.executable, bin_dir / "recorder.py", log), encoding="ascii")
        system = os.environ.get("SystemRoot", r"C:\Windows")
        base = [str(Path(system) / "System32"), system]                     # cmd.exe runs the .cmd shim
        env = {"SystemRoot": system, "ComSpec": str(Path(system) / "System32" / "cmd.exe"), "PATHEXT": ".COM;.EXE;.BAT;.CMD"}
    else:
        shim = bin_dir / "flyctl"
        shim.write_text('#!/bin/sh\nexec "%s" "%s" "%s" "$@"\n' % (sys.executable, bin_dir / "recorder.py", log), encoding="utf-8")
        shim.chmod(0o755)
        base, env = ["/usr/bin", "/bin"], {}
    pwsh = shutil.which("pwsh")
    assert pwsh, "PowerShell 7 runs deploy.ps1"
    env["PATH"] = os.pathsep.join([str(bin_dir), str(Path(pwsh).parent), *base])
    for name in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
        (tmp_path / name).mkdir()
        env[name] = str(tmp_path / name)
    return pwsh, shim, env


def test_cloud_deploy_builds_from_cloud_backend_in_this_repository(tmp_path):
    assert "12.PRODUCTION" not in (BACKEND / "deploy.ps1").read_text(encoding="utf-8")
    log = tmp_path / "flyctl-calls.jsonl"
    pwsh, shim, env = _inert_environment(tmp_path, log)
    quiet = dict(cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    # The exact environment the deploy runs in resolves flyctl to the inert shim, and to nothing else.
    resolved = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command",
                               "(Get-Command flyctl -All -ErrorAction Stop).Source"], **quiet)
    assert resolved.returncode == 0 and [Path(line.strip()) for line in resolved.stdout.splitlines() if line.strip()] == [shim], \
        resolved.stdout + resolved.stderr
    # deploy.ps1 refuses to start unless its public health address answers 200 (step 0), so a local one stands in.
    server = HTTPServer(("127.0.0.1", 0), _Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        run = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-File", str(BACKEND / "deploy.ps1"), "-SkipSecrets",
                              "-NonInteractive", "-PublicHealthUrl", "http://127.0.0.1:%d/healthz" % server.server_port], **quiet)
    finally:
        server.shutdown()
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    deploys = [call for call in calls if call[:1] == ["deploy"]]
    assert len(deploys) == 1, run.stdout + run.stderr
    assert "REFUSED: release failed" in run.stdout, run.stdout + run.stderr   # the inert transport made no release
    options = dict(zip(deploys[0][2::2], deploys[0][3::2]))
    context, dockerfile, ignorefile = Path(deploys[0][1]), Path(options["--dockerfile"]), Path(options["--ignorefile"])
    assert context.resolve() == ROOT.resolve() and options["-a"] == "archhub-cloud"
    assert re.search(r"^app\s*=\s*['\"]archhub-cloud['\"]", Path(options["--config"]).read_text(encoding="utf-8"), re.M)

    patterns = [line.strip() for line in ignorefile.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    copied = []
    for source in re.findall(r"^COPY (\S+) \S+$", dockerfile.read_text(encoding="utf-8"), re.M):
        path = context / source
        assert path.exists(), source + " is not in the build context"
        files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        sent = [f for f in files if _admitted(f.relative_to(context).as_posix(), patterns)]
        assert sent, source + " is excluded by " + ignorefile.name
        copied += [f.name for f in sent]
    # uvicorn main:app needs main.py; pip needs requirements.txt; the shared defaults module comes with them.
    assert {"main.py", "requirements.txt", "openrouter_defaults.py"} <= set(copied)
