"""Courts for the machine that has never run ArchHub: a colleague first open.

Three ways the hand-off died on a machine that was not the founder desk.

The setup installed from requirements.txt, requirements.txt did not name
PyQt6, PyQt6-WebEngine or uvicorn, and the launcher imports all three on the
boot path: the setup finished, the app died on an import, and the person had
no window and no message.

The lock port was already held -- a stale copy, another account app on a
shared machine -- and the launcher exited without a word. The person
double-clicked and nothing happened, forever.

The brain check was a bare TCP connect to 8473, so any listener at all
counted as the brain and ArchHub then handed its memory to a stranger
service.
"""
from __future__ import annotations

import ast
import importlib.metadata as metadata
import importlib.util
import socket
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "launch_archhub_test.py"
REQUIREMENTS = ROOT / "requirements.txt"


# --- what the launch path actually imports, measured from the source --------

def _module_file(dotted: str):
    """The file inside this tree that a dotted name resolves to, or None."""
    plain = ROOT / (dotted.replace(".", "/") + ".py")
    if plain.is_file():
        return plain
    package = ROOT / dotted.replace(".", "/") / "__init__.py"
    if package.is_file():
        return package
    return None


def launch_path_third_party():
    """Every third-party module the launch path imports without a guard.

    Computed by following the import statements of the launcher through this
    tree, so a dependency added to the app cannot hide from this court.
    Imports inside a try block are skipped: those are the optional engines,
    and the app reports them as absent instead of dying.
    Returns dotted names, because PyQt6.QtWebEngineWidgets and
    PyQt6.QtWidgets come from two different distributions.
    """
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    reached = set()
    walked = set()

    def resolve(node, package: str) -> str:
        if not node.level:
            return node.module or ""
        parts = [p for p in package.split(".") if p]
        if node.level > 1:
            parts = parts[: len(parts) - (node.level - 1)]
        if node.module:
            parts = parts + node.module.split(".")
        return ".".join(parts)

    def take(target: str, guarded: bool) -> None:
        if not target or target.split(".")[0] in stdlib:
            return
        if _module_file(target) is not None:
            walk(target)
            return
        if _module_file(target.split(".")[0]) is not None:
            return
        if not guarded:
            reached.add(target)

    def statements(body, guarded: bool, package: str) -> None:
        for node in body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    take(alias.name, guarded)
            elif isinstance(node, ast.ImportFrom):
                take(resolve(node, package), guarded)
            elif isinstance(node, ast.Try):
                statements(node.body, True, package)
                for handler in node.handlers:
                    statements(handler.body, True, package)
                statements(node.orelse, True, package)
                statements(node.finalbody, True, package)
            elif isinstance(node, (ast.If, ast.With)):
                statements(node.body, guarded, package)
                statements(getattr(node, "orelse", []), guarded, package)

    def walk(dotted: str) -> None:
        if dotted in walked:
            return
        walked.add(dotted)
        path = _module_file(dotted)
        if path is None:
            return
        package = dotted if path.name == "__init__.py" else dotted.rpartition(".")[0]
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))
        statements(tree.body, False, package)

    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"), str(LAUNCHER))
    statements(tree.body, False, "")
    return reached, walked


def _canonical(name: str) -> str:
    return name.strip().lower().replace("_", "-").replace(".", "-")


def requirement_names():
    listed = set()
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = line
        for cut in "<>=!~[; ":
            name = name.split(cut, 1)[0]
        if name:
            listed.add(_canonical(name))
    return listed


_OWNER_INDEX = {}


def _owner_index():
    """Installed file path -> the distribution that ships it, built once.

    Scanning every distribution once per ambiguous module took a minute and
    a half, which is slow enough that nobody runs the court.
    """
    if not _OWNER_INDEX:
        for dist in metadata.distributions():
            name = dist.metadata["Name"]
            for held in dist.files or ():
                try:
                    _OWNER_INDEX.setdefault(
                        str(dist.locate_file(held)).lower(), name)
                except OSError:
                    continue
    return _OWNER_INDEX


def distributions_for(dotted: str):
    """Which installed distribution ships this module.

    Several distributions can share one top-level package: PyQt6 and
    PyQt6-WebEngine both live under PyQt6/, and listing only the first left
    the WebEngine import to fail on a clean machine. When the top level is
    ambiguous, ask which distribution owns this exact module file.
    """
    top = dotted.split(".")[0]
    candidates = set(metadata.packages_distributions().get(top) or ())
    if len(candidates) <= 1:
        return candidates or {top}
    try:
        spec = importlib.util.find_spec(dotted)
        origin = Path(spec.origin).resolve()
    except Exception:
        return candidates
    owner = _owner_index().get(str(origin).lower())
    return {owner} if owner else candidates


def test_requirements_names_every_package_the_launch_path_imports():
    reached, walked = launch_path_third_party()
    assert len(walked) > 20, (
        "the import walk did not descend into the application; it walked only %s"
        % sorted(walked)
    )
    assert reached, "the import walk found no third-party imports at all"
    listed = requirement_names()
    missing = sorted(
        module for module in reached
        if not {_canonical(d) for d in distributions_for(module)} & listed
    )
    assert not missing, (
        "the launch path imports %s, and requirements.txt names no distribution "
        "that provides them; a clean machine would finish setup and then die on "
        "the import with no window" % missing
    )


# --- the shipped functions themselves, without booting the application ------

def launcher_function(name: str):
    """Run the function the launcher actually ships.

    Importing launch_archhub_test would boot the whole application, so the
    definition is lifted out of the source and executed on its own.
    """
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"), str(LAUNCHER))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            namespace = {}
            exec(compile(ast.Module(body=[node], type_ignores=[]),
                         str(LAUNCHER), "exec"), namespace)
            return namespace[name]
    raise AssertionError("%s is no longer defined in %s" % (name, LAUNCHER.name))


def test_a_held_port_says_so_instead_of_exiting_in_silence():
    outcome = launcher_function("_held_port_outcome")
    said = []
    answer = outcome(48611, lambda: False, said.append)
    assert len(said) == 1, "a held port must put a message on the screen"
    message = said[0]
    assert "48611" in message, "the person is never told which port is held"
    assert "ARCHHUB_TEST_LOCK_PORT" in message, (
        "the person is never told how to move the port"
    )
    assert answer and "48611" in answer, "the log line must name the port too"


def test_our_own_app_is_fronted_rather_than_explained():
    outcome = launcher_function("_held_port_outcome")
    said = []
    answer = outcome(48611, lambda: True, said.append)
    assert said == [], (
        "when the running ArchHub was brought to the front there is nothing to "
        "explain away"
    )
    assert "front" in answer


def test_the_launcher_never_exits_the_lock_path_without_speaking():
    source = LAUNCHER.read_text(encoding="utf-8")
    lock = source[source.index("_instance_lock.bind"):]
    lock = lock[: lock.index("ARCHHUB_STATE_DIR")]
    exit_at = lock.index("sys.exit(0)")
    assert "_held_port_outcome" in lock[:exit_at], (
        "the held-port branch must say what happened before it exits"
    )


# --- the brain probe --------------------------------------------------------

class _OneAnswerListener:
    """A listener that answers one HTTP request with a fixed body, then stops.

    It stands in for whatever else might be sitting on the brain port.
    """

    def __init__(self, body: bytes, status: bytes = b"200 OK"):
        self._socket = socket.socket()
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(1)
        self.port = self._socket.getsockname()[1]
        self._body = body
        self._status = status
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            client, _ = self._socket.accept()
        except OSError:
            return
        try:
            client.settimeout(2.0)
            seen = b""
            while b"\r\n\r\n" not in seen:
                chunk = client.recv(65536)
                if not chunk:
                    break
                seen += chunk
            # Read exactly the body the request announced, no more.
            # Closing while the client was still sending reached it as a
            # reset and the probe read a good answer as a refusal; an
            # unbounded read instead blocked past the timeout of the probe.
            head, _, rest = seen.partition(b"\r\n\r\n")
            announced = 0
            for header in head.split(b"\r\n"):
                if header.lower().startswith(b"content-length:"):
                    announced = int(header.split(b":", 1)[1].strip())
            while len(rest) < announced:
                chunk = client.recv(65536)
                if not chunk:
                    break
                rest += chunk
            client.sendall(
                b"HTTP/1.1 " + self._status + b"\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(self._body)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + self._body
            )
        except OSError:
            pass
        finally:
            # Say goodbye before hanging up: a bare close can reach the
            # client as a reset and lose the answer already written.
            try:
                client.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            client.close()

    def close(self) -> None:
        self._socket.close()


def _free_port() -> int:
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    port = holder.getsockname()[1]
    holder.close()
    return port


def test_the_brain_check_rejects_a_listener_that_is_not_the_brain():
    answers = launcher_function("_brain_answers")
    stranger = _OneAnswerListener(b'{"status":"ok","service":"something else"}')
    try:
        assert answers(stranger.port, 2.0) is False, (
            "an open port that answers in plain HTTP was taken for the brain; "
            "ArchHub would hand its memory to a stranger"
        )
    finally:
        stranger.close()


def test_the_brain_check_accepts_an_answer_in_mcp():
    answers = launcher_function("_brain_answers")
    brain = _OneAnswerListener(
        b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18",'
        b'"serverInfo":{"name":"personal-brain","version":"1"}}}'
    )
    try:
        assert answers(brain.port, 2.0) is True
    finally:
        brain.close()


def test_the_brain_check_says_no_when_nothing_is_listening():
    answers = launcher_function("_brain_answers")
    assert answers(_free_port(), 1.0) is False
