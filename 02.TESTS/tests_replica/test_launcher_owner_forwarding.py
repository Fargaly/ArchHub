"""A second launch reaches the running launcher through the real owner check: real processes, real loopback port."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PYTHONW = Path(sys.executable).with_name("pythonw.exe")   # the installed VBS launches pythonw.exe

# Stands in for the installed launcher: the same process shape (installed interpreter, -E -s, absolute launcher path,
# one flag). It listens on loopback, publishes its port, and records the first launch request it receives.
OWNER = """import pathlib, socket
here = pathlib.Path(__file__).parent
listener = socket.socket()
listener.bind(("127.0.0.1", 0))
listener.listen(1)
listener.settimeout(60)
(here / "port.tmp").write_text(str(listener.getsockname()[1]), encoding="ascii")
(here / "port.tmp").replace(here / "port")
connection, _ = listener.accept()
connection.settimeout(10)
data = b""
while not data.endswith(b"\\n"):
    chunk = connection.recv(8192)
    if not chunk:
        break
    data += chunk
(here / "received.json").write_bytes(data)
"""

# The second launch: the shipped launcher functions (owner check, forwarding) with this product root.
SECOND = """import ast, pathlib, sys
source = pathlib.Path(sys.argv[1])
tree = ast.parse(source.read_text(encoding="utf-8"))
keep = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Import))
        or (isinstance(node, ast.ImportFrom) and node.module in ("dataclasses", "pathlib"))]
f = {"__file__": sys.argv[2], "__name__": "second_launch"}
exec(compile(ast.Module(body=keep, type_ignores=[]), str(source), "exec"), f)
sys.exit(0 if f["_forward_launch_arguments"](int(sys.argv[3]), sys.argv[4:]) else 7)
"""


def _owner(root, *flags):
    script = root / "nodelang" / "launcher.py"
    script.parent.mkdir(parents=True)
    script.write_text(OWNER, encoding="utf-8")
    if not PYTHONW.is_file():
        pytest.skip("no pythonw.exe beside this interpreter")
    process = subprocess.Popen([str(PYTHONW), "-E", "-s", str(script), *flags], cwd=root, creationflags=NO_WINDOW)
    deadline = time.monotonic() + 30
    while not (script.parent / "port").exists():
        assert process.poll() is None and time.monotonic() < deadline, "the owner did not start"
        time.sleep(0.05)
    return process, int((script.parent / "port").read_text(encoding="ascii"))


def _second_launch(product_root, port, *arguments):
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "01.APP"), *sys.path])}
    return subprocess.run([sys.executable, "-c", SECOND, str(ROOT / "01.APP/nodelang/launcher.py"),
                           str(product_root / "nodelang" / "launcher.py"), str(port), *arguments],
                          capture_output=True, text=True, timeout=60, env=environment, creationflags=NO_WINDOW)


def _received(root, process):
    process.wait(timeout=30)
    return json.loads((root / "nodelang" / "received.json").read_bytes())


@pytest.mark.skipif(os.name != "nt", reason="the installed launcher is Windows-only")
def test_ask_baboom_reaches_a_launcher_the_update_reopened_in_the_tray(tmp_path):
    root = tmp_path / "ArchHub"
    owner, port = _owner(root, "--tray")
    try:
        second = _second_launch(root, port, "--baboom")
        assert second.returncode == 0, second.stdout + second.stderr   # exits 0 only once the request was sent
        assert _received(root, owner) == ["--baboom"]
    finally:
        owner.kill()


@pytest.mark.skipif(os.name != "nt", reason="the installed launcher is Windows-only")
@pytest.mark.parametrize("where,flag", [
    ("elsewhere", "--tray"),     # a foreign program: same interpreter and flag, not this product's launcher
    ("ArchHub", "--anything"),   # this launcher with a launch shape the owner check does not admit
])
def test_an_unverified_owner_receives_nothing(tmp_path, where, flag):
    owner_root = tmp_path / where
    owner, port = _owner(owner_root, flag)
    try:
        second = _second_launch(tmp_path / "ArchHub", port, "--baboom")
        assert second.returncode == 7, second.stdout + second.stderr   # refused: _forward_launch_arguments is False
        with socket.create_connection(("127.0.0.1", port), 5) as probe:
            probe.sendall(b'["probe"]\n')
        assert _received(owner_root, owner) == ["probe"]   # the first and only request is ours, not the second launch
    finally:
        owner.kill()
