"""Localhost endpoint for the single clean ArchHub graph owner."""

from __future__ import annotations

import argparse
import os
import urllib.request
import urllib.error
import sys
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Type

from .cell_secret_keys import WindowsDpapiSigningKeyProvider
from .clean_coordination_host import (
    CleanCoordinationHost,
    SignedCoordinationRequest,
)
from .runtime_caller_capability import WindowsDpapiCallerKeyStore
from .clean_boot_surface import BootSurface
from .unified_authority_runtime import default_runtime_root, open_current_authority
from .universal_cell import DatabaseOwnerConflict, InvalidCell


MAX_REQUEST_BYTES = 64 * 1024


class _CoordinationServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, handler, host: CleanCoordinationHost):
        self.coordination_host = host
        super().__init__(address, handler)


class CleanCoordinationRequestHandler(BaseHTTPRequestHandler):
    server: _CoordinationServer

    def log_message(self, _format: str, *_args: object) -> None:
        return None

    def _write(self, status: int, payload: object) -> None:
        body = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _admit_local_request(self) -> bool:
        origin = self.headers.get("Origin")
        if origin not in {None, "http://127.0.0.1", "http://localhost"}:
            self._write(403, {"ok": False, "error": "origin denied"})
            return False
        expected_port = self.server.server_address[1]
        host = self.headers.get("Host", "")
        if host not in {
            "127.0.0.1:%s" % expected_port,
            "localhost:%s" % expected_port,
        }:
            self._write(403, {"ok": False, "error": "host denied"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._write(404, {"ok": False, "error": "not found"})
            return
        if not self._admit_local_request():
            return
        authority = self.server.coordination_host.authority
        self._write(200, {
            "ok": True,
            "graph_id": authority.manifest.graph_id,
            "revision": authority.store.revision,
        })

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/coordination":
            self._write(404, {"ok": False, "error": "not found"})
            return
        if not self._admit_local_request():
            return
        try:
            size = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            size = -1
        if size < 0 or size > MAX_REQUEST_BYTES:
            self._write(413, {"ok": False, "error": "request size denied"})
            return
        try:
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            request = SignedCoordinationRequest.from_payload(payload)
            result = self.server.coordination_host.dispatch(request)
        except (InvalidCell, UnicodeError, json.JSONDecodeError) as exc:
            self._write(400, {"ok": False, "error": str(exc)})
            return
        except Exception:
            self._write(500, {"ok": False, "error": "coordination failed closed"})
            return
        self._write(200, result)


def _service_boot_note(line: str) -> None:
    try:
        from pathlib import Path as _Path
        root = _Path(os.environ.get("LOCALAPPDATA", "")) / "ArchHub" / "unified-authority"
        if root.is_dir():
            with (root / "boot-timing.log").open("a", encoding="utf-8") as log:
                log.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  boot phase: " + line + chr(10))
    except Exception:
        pass


def build_service(
    host: str = "127.0.0.1",
    *,
    port: int,
    handler: Type[CleanCoordinationRequestHandler] = (
        CleanCoordinationRequestHandler
    ),
    runtime_root,
) -> tuple[_CoordinationServer, object]:
    if host != "127.0.0.1" or type(port) is not int or not 1024 <= port <= 65535:
        raise InvalidCell("clean coordination bind address is invalid")
    provider = WindowsDpapiSigningKeyProvider(
        WindowsDpapiSigningKeyProvider.default_path()
    )
    # The root is REQUIRED, with no default here. A library that defaults
    # to the founder's live generation makes owning production the thing
    # that happens when a caller says nothing -- and the owner fence cannot
    # help, because a court that acquires a free live lock, asserts, and
    # exits was a perfectly legitimate owner for its whole short life, and
    # took the founder's service down when it left. Only the entry point
    # below is allowed to name the live graph.
    # The port is required for the same reason the root is, and the pair
    # is worse than either alone: a caller who says nothing would take its
    # own graph and the founder's port. During any restart window that
    # binds 8474 successfully, backed by a throwaway fixture, and every
    # agent reaching it enrols against a temp directory and is told ok.
    _opening = time.monotonic()
    location = open_current_authority(runtime_root, provider)
    _service_boot_note(
        "open_current_authority %.1fs" % (time.monotonic() - _opening)
    )
    try:
        _binding = time.monotonic()
        key_store = WindowsDpapiCallerKeyStore(
            WindowsDpapiCallerKeyStore.default_path()
        )
        graph_host = CleanCoordinationHost(location.authority, key_store)
        service = build_bound_service(graph_host, host, port, handler=handler)
        _service_boot_note(
            "bind coordination %.1fs" % (time.monotonic() - _binding)
        )
    except Exception:
        location.authority.store.close()
        raise
    return service, location


def build_bound_service(
    graph_host: CleanCoordinationHost,
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    handler: Type[CleanCoordinationRequestHandler] = (
        CleanCoordinationRequestHandler
    ),
) -> _CoordinationServer:
    """Bind an already-open authority host; port zero is test-only ephemeral."""
    if (
        host != "127.0.0.1"
        or type(port) is not int
        or port < 0
        or port > 65535
        or (port != 0 and port < 1024)
    ):
        raise InvalidCell("clean coordination bind address is invalid")
    return _CoordinationServer((host, port), handler, graph_host)


def _healthy_owner_is_serving(host: str, port: int) -> bool:
    """True when a live instance already answers /health on this address."""
    try:
        with urllib.request.urlopen(
            "http://%s:%d/health" % (host, port), timeout=3
        ) as response:
            return json.loads(response.read().decode("utf-8")).get("ok") is True
    except Exception:
        return False


def _build_canvas_server(location, host: str, port: int):
    """Stand the browser canvas over the SAME owned authority.

    One process, one lock, two surfaces. The canvas opens -- never installs
    -- its subsystems: an owner is an operator, and installation is a
    migration someone runs deliberately.
    """
    from .application_server import ApplicationServer
    from .clean_browser_authority import open_clean_browser_authority
    from .runtime_caller_capability import WindowsDpapiCallerKeyStore
    from .unified_authority import composition_root

    import time as _time
    _at = _time.perf_counter()
    _steps = []

    def _step(name):
        nonlocal _at
        now = _time.perf_counter()
        _steps.append((name, now - _at))
        _at = now

    authority = location.authority
    key_store = WindowsDpapiCallerKeyStore(
        WindowsDpapiCallerKeyStore.default_path()
    )
    caller = key_store.bind_bootstrap(authority, "founder.bootstrap")
    _step("bind caller")
    browser = open_clean_browser_authority(authority, caller=caller)
    _step("browser authority")
    provider = WindowsDpapiSigningKeyProvider(
        WindowsDpapiSigningKeyProvider.default_path()
    )
    # The canvas opens on the Grand Map, not on whichever member happens
    # to be first inside it. Descending one level picked an arbitrary
    # document region whose own members are a level deeper still, so every
    # relation it carried pointed at something the canvas never drew: a
    # screen of unconnected cards and hundreds of wires with no endpoints.
    scope = composition_root(authority, "Grand Map", caller=caller)
    _step("grand map scope")
    # Which region the canvas opens on is an operator's choice, and this is
    # the entry point where naming one is a declaration rather than a trap.
    chosen = os.environ.get("ARCHHUB_CANVAS_SCOPE", "").strip()
    if chosen:
        scope = chosen
    # This is where the machines ArchHub may reach are named. An owner
    # standing up a runtime declares its adapters; a library that picked
    # them for itself would be a runtime that could touch a host nobody
    # chose. Adding a host is adding a line here, and a host absent from
    # this map is a host this runtime cannot reach at all.
    from .clean_office_adapter import invoke as reach_office
    from .clean_revit_adapter import invoke as reach_revit

    adapters = {
        "revit": reach_revit,
        "word": reach_office,
        "excel": reach_office,
        "powerpoint": reach_office,
    }

    def reach_host(op_id, arguments):
        host = str(op_id).split(".", 1)[0]
        adapter = adapters.get(host)
        if adapter is None:
            raise InvalidCell(
                "this runtime declares no adapter for %r; it reaches %s"
                % (host, ", ".join(sorted(adapters)))
            )
        return adapter(op_id, arguments)

    server = ApplicationServer.from_unified_authority(
        authority,
        browser_authority=browser,
        scope_caller=caller,
        scope_root=scope,
        authority_key_provider=provider,
        host=host,
        port=port,
        host_invoker=reach_host,
    )
    _step("application server")
    # What standing the canvas costs, step by step, in the same log the
    # owner keeps its boot phases in.
    try:
        with (location.root / "boot-timing.log").open(
            "a", encoding="utf-8"
        ) as log:
            log.write("%s  canvas detail: %s%s" % (
                _time.strftime("%Y-%m-%d %H:%M:%S"),
                "  ".join("%s %.1fs" % item for item in _steps),
                chr(10),
            ))
    except OSError:
        pass
    return server


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8474)
    parser.add_argument("--canvas-port", type=int, default=8475)
    parser.add_argument(
        "--await-lock-seconds",
        type=float,
        default=120.0,
        help=(
            "how long a successor waits for a stopping predecessor to "
            "release the graph lock before refusing to start"
        ),
    )
    parser.add_argument(
        "--root",
        default="",
        help="runtime root to own (defaults to the founder's runtime)",
    )
    parser.add_argument(
        "--no-canvas",
        action="store_true",
        help="serve coordination only (a graph without canvas subsystems)",
    )
    args = parser.parse_args()
    # A supervisor restarts this unconditionally. Without these two exits a
    # second instance starts, blocks forever on the generation owner lock the
    # first one holds, and never binds: a live process serving nothing, which
    # is worse than no process because /health cannot report it.
    if _healthy_owner_is_serving(args.host, args.port):
        print(
            "clean coordination service already serving on %s:%d"
            % (args.host, args.port),
            file=sys.stderr,
        )
        return 0
    # How long a start takes is a fact about this runtime, and it is the
    # one nobody could get: the process runs under pythonw with no
    # console, so a slow start looked identical to a hung one from
    # outside. Each phase is timed and written where an operator can read
    # it afterwards.
    started_at = time.monotonic()
    phases: list[tuple[str, float]] = []

    # A boot that says nothing for thirteen minutes is indistinguishable
    # from a boot that has died, and under pythonw there is no console to
    # say it to. Every phase announces itself where an operator can read it
    # WHILE it runs, and the same file records the failure that ends it --
    # a silent exit is how the last four restarts looked from outside.
    def _boot_log_path() -> Path:
        return (
            Path(args.root) if args.root else default_runtime_root()
        ) / "boot-timing.log"

    def _say(message: str) -> None:
        print(message, file=sys.stderr, flush=True)
        try:
            path = _boot_log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write("%s  %s%s" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"), message, chr(10)))
        except OSError:
            pass

    def _begin(label: str) -> None:
        if boot_surface is not None:
            boot_surface.progress.begin(label)
        _say("... %s (%.1fs since launch)" % (
            label, time.monotonic() - started_at))

    def _mark(label: str, since: float) -> float:
        now = time.monotonic()
        phases.append((label, now - since))
        if boot_surface is not None:
            boot_surface.progress.finish(label)
        _say("done %s in %.1fs" % (label, now - since))
        return now

    _say("clean owner starting (pid %d, port %d, canvas %d)" % (
        os.getpid(), args.port, args.canvas_port))
    # A start that shows nothing cannot be told from a start that failed.
    # The progress page takes the canvas port first and hands it back the
    # moment the real canvas can serve, so opening a graph is visible from
    # the first second instead of ninety seconds of silence.
    boot_surface = None
    if not args.no_canvas:
        try:
            boot_surface = BootSurface(args.host, args.canvas_port).start()
        except OSError as exc:
            _say("boot surface not stood: %s" % exc)
    _begin("open authority and bind coordination")

    # A successor that asks for the graph the instant the predecessor is
    # told to stop loses the race and dies, and the operator sees only a
    # program that did not come back. The predecessor releases the OS lock
    # when its process ends, so the successor waits for the LOCK rather
    # than for a liveness ping: a ping answers while the holder is still
    # shutting down, and it stops answering long before the lock is free.
    #
    # Waiting is refused, not extended, when the holder is a working owner:
    # taking over from a healthy predecessor is not recovery, it is two
    # owners fighting. That case exits distinctly and says which pid holds
    # it, so a supervisor reuses the running owner instead of restarting.
    def _surfaces_answer() -> bool:
        for url in (
            "http://%s:%d/health" % (args.host, args.port),
            "http://%s:%d/" % (args.host, args.canvas_port),
        ):
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    response.read(1)
                return True
            except urllib.error.HTTPError:
                return True
            except Exception:
                continue
        return False

    def _open_owning_the_graph():
        deadline = time.monotonic() + max(0.0, args.await_lock_seconds)
        announced = False
        while True:
            try:
                return build_service(
                    args.host,
                    port=args.port,
                    runtime_root=(
                        Path(args.root)
                        if args.root else default_runtime_root()
                    ),
                )
            except DatabaseOwnerConflict as exc:
                if _surfaces_answer():
                    _say("REFUSED a live owner already serves this graph; "
                         "reuse it or stop it first: %s" % exc)
                    raise SystemExit(78)
                if time.monotonic() >= deadline:
                    raise
                if not announced:
                    _say("... waiting up to %.0fs for the previous owner to "
                         "release the graph lock" % args.await_lock_seconds)
                    announced = True
                time.sleep(1.0)

    try:
        service, location = _open_owning_the_graph()
    except DatabaseOwnerConflict as exc:
        _say("FAILED cannot own the graph: %s" % exc)
        return 75
    except OSError as exc:
        _say("FAILED cannot bind %s:%d: %s" % (args.host, args.port, exc))
        return 76
    # Both surfaces or neither. A half-serving owner holding the lock is
    # worse than no owner: it blocks recovery while delivering nothing, and
    # from outside it looks healthy because something answers. Any failure
    # past this point releases the lock and exits distinctly.
    opened_at = _mark("open authority and bind coordination", started_at)
    canvas = None
    if not args.no_canvas:
        _begin("stand the canvas surface")
        if boot_surface is not None:
            boot_surface.hand_over()
            boot_surface = None
        try:
            canvas = _build_canvas_server(
                location, args.host, args.canvas_port
            ).start()
        except Exception as exc:
            _say("FAILED cannot stand the canvas surface: %s" % exc)
            service.server_close()
            location.authority.store.close()
            return 77
        _mark("stand the canvas surface", opened_at)
        total = time.monotonic() - started_at
        report = "  ".join(
            "%s %.1fs" % (label, seconds) for label, seconds in phases
        )
        print(
            "canvas serving on %s after %.1fs (%s)" % (
                canvas.page_url, total, report
            ),
            file=sys.stderr,
        )
        # Under pythonw there is no console, so a URL printed to stderr is
        # a URL nobody can open. The canvas now needs its key, so write the
        # exact address next to the service's own boot log -- inside the
        # user's profile, which is where the key belongs and where no other
        # user's browser can reach it.
        try:
            from pathlib import Path as _Path
            note = (
                _Path(os.environ.get("LOCALAPPDATA", ""))
                / "ArchHub" / "unified-authority"
            )
            if note.is_dir():
                (note / "canvas-url.txt").write_text(
                    canvas.page_url + chr(10), encoding="utf-8"
                )
        except OSError:
            pass
        try:
            log = Path(
                args.root
            ) if args.root else default_runtime_root()
            (log / "boot-timing.log").open("a", encoding="utf-8").write(
                "%.1fs total  " % total + report + chr(10)
            )
        except OSError:
            pass
    # Both-or-neither holds at runtime too, and the watcher is the MAIN
    # thread: if the watcher dies the process dies and the OS releases the
    # lock, so "who watches the watchdog" bottoms out in process death
    # rather than in another thread. Liveness is a bounded probe of each
    # SURFACE, not thread aliveness -- a wedged thread is alive and serving
    # nothing, the exact state last night's dead-pid descriptor taught.
    # Teardown is ordered: the canvas socket closes before coordination, so
    # there is no window where the canvas answers while coordination
    # refuses and two agents see different halves of one owner.
    serve_thread = threading.Thread(
        target=lambda: service.serve_forever(poll_interval=0.25),
        name="clean-owner-coordination",
        daemon=True,
    )
    serve_thread.start()

    def _surface_answers(url: str) -> bool:
        try:
            # A cold projection over a five-million-cell graph legitimately
            # takes tens of seconds; a bound of ten made the watchdog shoot
            # a healthy owner three probes into its first paint.
            with urllib.request.urlopen(url, timeout=90) as response:
                response.read(1)
                return True
        except urllib.error.HTTPError:
            # An HTTP status is an answer; refusing unauthenticated
            # requests is the canvas surface working, not failing.
            return True
        except Exception:
            return False

    coordination_url = "http://%s:%d/health" % (args.host, args.port)
    # The canvas endpoint needs an authenticated browser session, which a
    # watchdog has no business holding: every probe was refused and logged
    # as an error, so the owner wrote 94,919 "authenticated browser session
    # required" lines into its own gesture log between 2026-08-19 and
    # 2026-08-25 -- eleven megabytes that buried every real error under a
    # failure that was the surface working. The stylesheet is served from
    # the graph without a session, so a 200 there proves the same thing the
    # probe was actually asking: this surface is up and reading the graph.
    canvas_url = None if canvas is None else (
        canvas.url + "/api/universal/stylesheet"
    )
    failed_probes = 0
    exit_code = 0
    try:
        while True:
            time.sleep(5.0)
            if not serve_thread.is_alive():
                print("clean owner: coordination worker stopped",
                      file=sys.stderr)
                exit_code = 78
                break
            healthy = _surface_answers(coordination_url) and (
                canvas_url is None or _surface_answers(canvas_url)
            )
            if healthy:
                failed_probes = 0
                continue
            failed_probes += 1
            if failed_probes >= 3:
                print(
                    "clean owner: a surface stopped answering bounded "
                    "probes; taking the whole owner down for restart",
                    file=sys.stderr,
                )
                exit_code = 78
                break
    except KeyboardInterrupt:
        exit_code = 130
    finally:
        if canvas is not None:
            canvas.close()
        service.shutdown()
        service.server_close()
        location.authority.store.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CleanCoordinationRequestHandler",
    "MAX_REQUEST_BYTES",
    "build_bound_service",
    "build_service",
]
