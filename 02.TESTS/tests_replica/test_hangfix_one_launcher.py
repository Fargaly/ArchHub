"""One launcher. A dead lock holder is taken over; a live answering one stays.

A process that is not this product's launcher is never stopped, so a held
bridge in Revit or AutoCAD is not a reason to close that host.
"""
import ast
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "01.APP" / "nodelang" / "launcher.py"


def _functions():
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    defs = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    namespace = {"Path": Path, "time": time, "os": __import__("os"), "sys": sys, "__file__": str(LAUNCHER)}
    exec(compile(ast.Module(body=defs, type_ignores=[]), str(LAUNCHER), "exec"), namespace)
    return namespace


def test_a_live_answering_launcher_is_left_and_a_silent_one_is_stopped():
    decision = _functions()["_lock_takeover_decision"]
    assert decision(True, True, True, 3600, True) == "leave"
    assert decision(True, True, False, 10, True) == "leave"
    assert decision(True, True, False, 120, True) == "stop"
    assert decision(False, False, False, 0, False) == "bind"
    assert decision(False, False, False, 0, True) == "leave"


def test_a_foreign_holder_stays_and_a_dead_holder_lets_the_new_launch_bind():
    functions = _functions()
    release = functions["_release_unanswering_holder"]
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import socket,sys,time\n"
         "s=socket.socket()\n"
         "s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)\n"
         "s.bind(('127.0.0.1', int(sys.argv[1])))\n"
         "s.listen(1)\n"
         "time.sleep(30)\n",
         str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                watch = socket.socket()
                watch.bind(("127.0.0.1", port))
                watch.close()
            except OSError:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("the foreign holder never bound the lock port")
        assert release(port, Path(".")) is False
        assert holder.poll() is None
    finally:
        holder.kill()
        holder.wait(timeout=5)
    assert release(port, Path(".")) is True
    taken = socket.socket()
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            taken.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        taken.bind(("127.0.0.1", port))
        taken.listen(1)
    finally:
        taken.close()
