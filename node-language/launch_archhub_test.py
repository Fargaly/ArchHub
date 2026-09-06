"""ArchHub TEST launcher -- one double-click, the windowed desktop app.

Boots the universal cell application on a PERSISTENT store under
%LOCALAPPDATA%/ArchHub-Test (your live graph is never touched) and opens
it in its own application window. Close the window to stop ArchHub TEST.
"""
import faulthandler
import os, sys, time, traceback
from pathlib import Path

# This machine's documented QtWebEngine failure: GPU compositing
# collapses the render process and takes the whole window down with no
# Python traceback. Software rendering is the fix that held.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
os.environ.setdefault("QT_OPENGL", "software")

sys.path.insert(0, str(Path(__file__).parent))

# pythonw has no console: stdout/stderr vanish and a crash is invisible.
# Everything this launcher says goes to a file the founder can open.
_log_dir = Path(
    os.environ.get("ARCHHUB_TEST_STATE_DIR")
    or (Path(os.environ["LOCALAPPDATA"]) / "ArchHub-Test")
)
_log_dir.mkdir(parents=True, exist_ok=True)
_log_path = _log_dir / "launcher.log"
_log = open(_log_path, "a", encoding="utf-8", buffering=1)
sys.stdout = _log
sys.stderr = _log


# pythonw has no console and stdout is the log file above, so a boot that
# refuses -- Qt missing, WebEngine refusing the GPU, a port held -- was a
# window that never opened and a colleague with nothing to send. The log
# keeps the full traceback; the colleague gets its last line and where the
# log is, in a box he can read.
def _message_box(message):
    """The only window a person without a console ever sees.

    Every refusal on the boot path goes through here. A launch that ends
    without one is a double-click that did nothing, and the colleague is left
    with nothing to read and nothing to send.
    """
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, 'ArchHub', 0x10)
        return True
    except Exception:
        return False


def _tell_the_person(kind, value, tb):
    traceback.print_exception(kind, value, tb)
    try:
        last = ''.join(traceback.format_exception_only(kind, value)).strip().splitlines()[-1]
        message = 'ArchHub could not open.' + chr(10) + chr(10) + last[:300]
        message += chr(10) + chr(10) + 'The full log is at:' + chr(10) + str(_log_path)
        message += chr(10) + chr(10) + 'Send that file to Ahmed.'
        _message_box(message)
    except Exception:
        pass
sys.excepthook = _tell_the_person
print("=== launch", time.strftime("%Y-%m-%d %H:%M:%S"), "===")
faulthandler.enable(file=_log)

state_dir = Path(
    os.environ.get("ARCHHUB_TEST_STATE_DIR")
    or (Path(os.environ["LOCALAPPDATA"]) / "ArchHub-Test")
)
state_dir.mkdir(parents=True, exist_ok=True)
state_path = state_dir / "archhub-test.universal.sqlite3"

def _force_foreground(handle) -> bool:
    """Make Windows actually bring our window forward.

    Qt's showNormal/raise_/activateWindow are the whole story on other
    desktops. On Windows a process that does not own the foreground cannot
    take it: SetForegroundWindow is refused and the taskbar button flashes
    instead. The founder clicked the tray icon and nothing happened
    (2026-09-06). The documented way round it is to attach our input queue to
    the foreground window's thread for the moment of the call, which is what
    every app that restores from a tray does.
    """
    try:
        import ctypes as _ct

        user32 = _ct.windll.user32
        kernel32 = _ct.windll.kernel32
        handle = int(handle)
        if not handle:
            return False
        SW_RESTORE = 9
        if user32.IsIconic(handle):
            user32.ShowWindow(handle, SW_RESTORE)
        user32.ShowWindow(handle, SW_RESTORE)
        ours = kernel32.GetCurrentThreadId()
        front = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
        attached = bool(front and front != ours
                        and user32.AttachThreadInput(front, ours, True))
        try:
            user32.BringWindowToTop(handle)
            user32.SetForegroundWindow(handle)
            user32.SetActiveWindow(handle)
        finally:
            if attached:
                user32.AttachThreadInput(front, ours, False)
        return bool(user32.IsWindowVisible(handle))
    except Exception:
        return False


def _front_running_archhub():
    """Bring an ArchHub window already on this desktop to the front.

    Launching ArchHub while it lives in the tray must SHOW it (Chrome,
    Claude Desktop): the founder double-clicked the icon and saw nothing
    (2026-09-04, the studio window sat hidden behind close-to-tray).
    True means a window of ours was found and raised.
    """
    try:
        import ctypes as _ct
        _u = _ct.windll.user32
        _shown = []

        def _each(handle, _lparam):
            length = _u.GetWindowTextLengthW(handle)
            title = _ct.create_unicode_buffer(length + 1)
            _u.GetWindowTextW(handle, title, length + 1)
            klass = _ct.create_unicode_buffer(256)
            _u.GetClassNameW(handle, klass, 256)
            if title.value == "ArchHub" and "QWindowIcon" in klass.value:
                # Same Windows foreground rule as the tray click: without the
                # input-queue attach the call is refused and the button blinks.
                _force_foreground(handle)
                _shown.append(handle)
            return True

        _u.EnumWindows(_ct.WINFUNCTYPE(_ct.c_bool, _ct.c_void_p, _ct.c_void_p)(_each), 0)
        return bool(_shown)
    except Exception:
        return False


def _held_port_outcome(port, front_running_archhub, tell_the_person):
    """Answer a held lock port with words, never with a silent exit.

    A colleague double-clicked ArchHub on a machine where the port was
    already taken -- a copy left running under another account, a stale
    process, any program that happened to sit on it -- and got nothing at
    all: no window, no message, every single time. Two different situations
    hide behind one refusal to bind, and each needs its own answer.
    """
    if front_running_archhub():
        return "another ArchHub is already running; brought its window to the front"
    tell_the_person(
        "ArchHub is already open, or port %d on this machine is being used by "
        "another program." % port
        + chr(10) + chr(10)
        + "Nothing was found to bring to the front, so ArchHub stopped here "
          "rather than fight the other copy for the same graph."
        + chr(10) + chr(10)
        + "If ArchHub is not already open, wait a few seconds and open it "
          "again. If it still refuses, set the environment variable "
          "ARCHHUB_TEST_LOCK_PORT to a free port number (%d, for example) "
          "and open ArchHub again." % (port + 1)
    )
    return ("port %d is held and no ArchHub window answered; the person was told "
            "about ARCHHUB_TEST_LOCK_PORT" % port)


# ONE app. A second double-click fronts nothing and starts nothing --
# the socket is the cheapest cross-process mutex Windows respects.
import socket as _socket
_lock_port = int(os.environ.get("ARCHHUB_TEST_LOCK_PORT", "48611"))
_instance_lock = _socket.socket()
# NEVER SO_REUSEADDR here: on Windows it PERMITS binding a port another
# process already holds, which silently disables the single-instance
# mutex and lets a second app fight the first for the database.
if hasattr(_socket, "SO_EXCLUSIVEADDRUSE"):
    _instance_lock.setsockopt(
        _socket.SOL_SOCKET, _socket.SO_EXCLUSIVEADDRUSE, 1
    )
for _attempt in range(12):
    try:
        _instance_lock.bind(("127.0.0.1", _lock_port))
        break
    except OSError:
        # A dying previous instance still holds the port for a moment.
        # Reopening right after closing must WORK, so wait it out rather
        # than exiting silently and leaving the founder with no window.
        time.sleep(0.5)
else:
    # Say so in the log AND on the screen: a launch that exits without a word
    # leaves an orphan header, reads as a crash, and gives the person nothing
    # to act on.
    print("  lock       : port %d is already held" % _lock_port, flush=True)
    print("  window     : %s"
          % _held_port_outcome(_lock_port, _front_running_archhub, _message_box),
          flush=True)
    sys.exit(0)

# listdir membership: Path.exists() returns False on a Windows sharing
# violation (a dying prior instance still holds the handle), which would
# mislabel a warm store as a first boot.
# The server reads the staged-update marker from here (BABOOM's "Restart now").
os.environ["ARCHHUB_STATE_DIR"] = str(state_dir)
first_boot = state_path.name not in os.listdir(state_dir)
if first_boot:
    for stale in state_dir.glob(state_path.name + "*"):
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass

if not first_boot:
    # Rolling backups, like Revit's: a silent copy at every launch,
    # last TWO kept -- insurance, not a museum.
    import shutil
    backups = state_dir / "backups"
    backups.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    try:
        shutil.copy2(state_path, backups / ("%s.%s" % (state_path.name, stamp)))
        aged = sorted(backups.glob(state_path.name + ".*"))
        for old_copy in aged[:-2]:
            old_copy.unlink(missing_ok=True)
    except OSError:
        pass

print("ArchHub TEST")
print("  graph store :", state_path)
print("  first boot  :", first_boot, "(first boot builds the graph, ~1-2 min)")
print("  booting ...", flush=True)

from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.pipeline_engines import PIPELINE_ENGINES

# The runtime-pipe signing secret and descriptor live beside the store;
# they are what lets BABOOM (and any governed agent) bind a signed
# session against THIS runtime.
_pipe_secret_path = state_dir / "runtime-pipe.secret"
if not _pipe_secret_path.is_file():
    import secrets as _secrets
    _pipe_secret_path.write_bytes(_secrets.token_bytes(32))
# The brain (and every other governed client) authenticates to the pipe
# with the machine's DPAPI key at its DEFAULT path. Using a private
# secret here would make this runtime unreachable to them -- which is
# exactly why brain writes were failing.
from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider

machine_key_provider = WindowsDpapiSigningKeyProvider(
    WindowsDpapiSigningKeyProvider.default_path()
)
descriptor_path = state_dir / "runtime-descriptor.json"

# Quiet update, the Chrome way: a build the previous run downloaded and
# verified is applied now, before anything boots, and this launcher hands
# over to the freshly installed one. The graph is never touched.
try:
    from nodelang.quiet_update import apply_staged as _apply_staged
    _applied = _apply_staged(state_dir, Path(__file__).resolve().parent)
    if _applied.get("applied"):
        print("  update     : installed build %s; relaunching" % _applied.get("build_id"), flush=True)
        import subprocess as _sp
        _sp.Popen(["wscript.exe", str(Path(__file__).resolve().parent / "ArchHub.vbs")], close_fds=True, creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
        raise SystemExit(0)
    elif _applied.get("reason") == "nothing staged":
        # Nothing was staged while the app last ran: look once now, quickly,
        # so a close-and-open lands a build published in the meantime.
        from nodelang.quiet_update import stage_if_newer as _stage_now
        _staged = _stage_now(state_dir, Path(__file__).resolve().parent)
        if _staged.get("staged"):
            _applied = _apply_staged(state_dir, Path(__file__).resolve().parent)
            if _applied.get("applied"):
                print("  update     : installed build %s; relaunching" % _applied.get("build_id"), flush=True)
                import subprocess as _sp
                _sp.Popen(["wscript.exe", str(Path(__file__).resolve().parent / "ArchHub.vbs")], close_fds=True, creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
                raise SystemExit(0)
    else:
        print("  update     : %s" % _applied.get("reason"), flush=True)
except SystemExit:
    raise
except Exception as _update_refusal:
    print("  update     : not applied -- %s" % _update_refusal, flush=True)

started = time.perf_counter()

def _boot():
    # The boot is sampled while it runs: boot-profile.log beside launcher.log
    # says where the seconds went (the founder's boot reached 694s and nobody
    # could name what it was doing).
    from nodelang.boot_profile import profile_boot
    return profile_boot(_boot_unsampled, state_dir=state_dir)

def _boot_unsampled():
    return ApplicationServer(
        universal_state_path=state_path,
        pipeline_effect_engines=PIPELINE_ENGINES,
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=machine_key_provider,
    ).start()

def _release_own_fence(refusal) -> None:
    """A failed _boot() can leave this process holding the store fence twice over:
    the .owner.lock file AND an in-memory path set. Both must go or every retry
    fails on ourselves."""
    if "already owned by this same process" not in str(refusal):
        return
    try:
        from nodelang.universal_cell import InterprocessOwnerFence as _Fence
        key = os.path.normcase(os.path.realpath(os.path.abspath(str(state_path))))
        with _Fence._process_guard:
            _Fence._process_paths.discard(key)
    except Exception:
        pass
    for stale in state_dir.glob(state_path.name + ".owner.lock"):
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass

boot_refusal = None
try:
    server = _boot()
except Exception as refusal:
    boot_refusal = refusal
    # SELF-HEALING BOOT. A desktop that refuses to open over local state
    # it could rebuild is a locked door, not a security posture. The
    # suspect universe is QUARANTINED -- never destroyed -- and a fresh
    # one is born; the refusal is printed, not swallowed.
    # A lock held by a dying predecessor clears on its own; retrying once
    # costs a second and saves the founder's whole graph from being set
    # aside for a transient.
    import gc

    gc.collect()
    # A failed first attempt can leave OUR OWN owner fence behind; the
    # conflict then names this very process. Releasing our own lock is
    # honest -- it is nobody else's.
    _release_own_fence(refusal)
    # A transient (a predecessor still closing its WAL, a lock not yet
    # released, an I/O hiccup) is retried for a while; it is never a
    # reason to set the founder's graph aside -- a fresh graph on the
    # same disk would fail the same way, and the founder would open
    # an empty canvas over 300 MB of his own work.
    for _open_attempt in range(6):
        time.sleep(1.5)
        try:
            server = _boot()
            print("  recovered  : the saved graph opened on attempt %d"
                  % (_open_attempt + 2), flush=True)
            boot_refusal = None
            break
        except Exception as again:
            boot_refusal = again
            # Each failed attempt can leave OUR OWN fence behind; without
            # clearing it every later attempt fails on ourselves.
            _release_own_fence(again)
if boot_refusal is not None and any(
    mark in str(boot_refusal)
    for mark in ("disk I/O error", "database is locked", "already owned", "unable to open",
                 "held by another live process", "owner fence could not be taken")
):
    print("  could not open the saved graph: %s"
          % str(boot_refusal).splitlines()[-1][:160], flush=True)
    print("  the graph is kept in place; this is a transient, not corruption."
          " Close every ArchHub process and launch again.", flush=True)
    raise boot_refusal
if boot_refusal is not None:
    print("  could not open the saved graph: %s"
          % str(boot_refusal).splitlines()[-1][:160])
    set_aside = state_dir / ("set-aside-%s" % time.strftime("%Y%m%d-%H%M%S"))
    set_aside.mkdir(parents=True, exist_ok=True)
    for stale in state_dir.glob(state_path.name + "*"):
        try:
            stale.rename(set_aside / stale.name)
        except OSError:
            pass
    print("  old data kept in %s -- starting a fresh graph ..." % set_aside.name)
    server = _boot()
print(f"  booted in {time.perf_counter()-started:.0f}s", flush=True)

# Every user gets their own brain. The daemon on :8473 is what BABOOM, the
# memory panel and every agent speak to; on a machine that has none, the
# shipped personal_brain package is started here, hidden, once.
def _brain_answers(port=8473, timeout=1.5, strict=False) -> bool:
    """True only when the thing on this port is really our brain.

    A bare TCP connect said yes to ANY listener. On a shared machine that
    made ArchHub hand its memory to a stranger's service that happened to
    sit on 8473. The brain speaks MCP over /mcp, so ask it in MCP and read
    the answer; anything that cannot answer in MCP is not the brain.
    Kept short because this runs on the boot path.
    """
    import json as _json
    import urllib.error as _err
    import urllib.request as _req

    if strict:
        # Ask for WORK. Measured on the founder's daemon at 04:20 on
        # 2026-09-06: initialize answered in 0.0 s while every tools/call hung,
        # so a handshake-only probe reported a brain that could do nothing as
        # healthy. brain.health is the cheapest real tool (about 1.8 s well).
        ask = _json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "brain.health", "arguments": {}},
        }).encode("utf-8")
    else:
        ask = _json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "archhub-launcher", "version": "1"},
            },
        }).encode("utf-8")
    request = _req.Request(
        "http://127.0.0.1:%d/mcp" % port, data=ask,
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
        method="POST",
    )
    try:
        with _req.urlopen(request, timeout=timeout) as answer:
            body = answer.read(4096).decode("utf-8", "replace")
    except _err.HTTPError as refusal:
        # An MCP endpoint that refuses this call still refuses in MCP, and
        # that refusal identifies it just as well as a success would.
        try:
            body = refusal.read(4096).decode("utf-8", "replace")
        except Exception:
            return False
    except Exception as unanswered:
        # A BUSY brain is not an absent one. The daemon serves every agent on
        # this machine and a heavy tool call holds it for tens of seconds; a
        # short probe that timed out was read as "no brain" and the watchdog
        # started another one, twice in a row (2026-09-06 launcher.log). When
        # something still holds the port, leave it alone: only an unheld port,
        # or a listener that answers and is not MCP, means start our own.
        if strict:
            # The watchdog asks strictly: it needs to know whether the daemon
            # SPOKE, not whether something is still on the port. A held port
            # answers the boot question ("is a brain there") and cannot answer
            # this one ("is it still working").
            return False

        if isinstance(unanswered, (TimeoutError, OSError)) and _port_held(port):
            return True
        return False
    if "jsonrpc" not in body:
        return False
    if strict:
        # A tool answer, or a refusal that only a working dispatcher can make.
        return '"result"' in body or '"error"' in body
    return any(mark in body for mark in
               ("protocolVersion", "serverInfo", "capabilities", '"error"'))


def _port_held(port) -> bool:
    """Whether anything at all is listening there, in a few milliseconds."""
    import socket as _sk

    probe = _sk.socket()
    probe.settimeout(0.4)
    try:
        return probe.connect_ex(("127.0.0.1", int(port))) == 0
    except Exception:
        return False
    finally:
        probe.close()


def _ensure_brain() -> str:
    import subprocess as _sp
    # The brain serves /mcp. Only an answer in MCP counts as a brain being
    # there -- never start a second one on it, and never talk to a stranger.
    def _alive() -> bool:
        return _brain_answers()
    if _alive():
        return "answering on :8473"
    app_dir = Path(__file__).resolve().parent
    if not (app_dir / "personal_brain" / "__init__.py").is_file():
        return "no brain package shipped beside this launcher"
    env = dict(os.environ); env["PYTHONPATH"] = str(app_dir) + os.pathsep + env.get("PYTHONPATH", "")
    # The brain's Workshop tools need the governed workspace root. A machine
    # that has one (the founder's 00.ARCHUB) gets it; a stranger's install
    # has none and the brain keeps those tools fail-closed, as it should.
    if not env.get("ARCHHUB_WORKSPACE_ROOT"):
        for candidate in (Path.home() / "00.ARCHUB", Path(os.environ.get("USERPROFILE", "")) / "00.ARCHUB"):
            if (candidate / "AGENTS.md").is_file():
                env["ARCHHUB_WORKSPACE_ROOT"] = str(candidate)
                break
    windowless = Path(sys.executable).with_name("pythonw.exe")
    exe = str(windowless if windowless.exists() else sys.executable)
    # The daemon's own words survive it: a crash leaves its last lines in
    # state_dir/brain.log instead of vanishing with a windowless process
    # (2026-09-05: the brain went silent with nothing to read).
    brain_log = open(state_dir / "brain.log", "ab")
    _sp.Popen([exe, "-m", "personal_brain.server", "--http", "8473"], env=env, cwd=str(app_dir), close_fds=True,
              stdin=_sp.DEVNULL, stdout=brain_log, stderr=brain_log,
              creationflags=getattr(_sp, "DETACHED_PROCESS", 0) | getattr(_sp, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(_sp, "CREATE_NO_WINDOW", 0))
    for _ in range(20):
        time.sleep(0.5)
        if _alive():
            return "started on :8473"
    return "started, not answering yet on :8473"

try:
    print("  brain      : %s" % _ensure_brain(), flush=True)
except Exception as _brain_refusal:
    print("  brain      : not started -- %s" % _brain_refusal, flush=True)


# Two minutes was far too eager. A brain that has just started spends its
# first minutes pushing the whole store to the cloud, and the write lock it
# holds makes a health probe time out -- so the watchdog killed it, the new one
# started the same sync, and it killed that one too: 46 restarts in an hour on
# the founder's machine (launcher.log, 2026-09-06). Ten minutes of continuous
# silence is a wedge; anything shorter is work.
_WEDGED_CHECKS_BEFORE_REPLACING = 30  # thirty checks at 20 s: ten minutes
_BRAIN_SETTLING_SECONDS = 600.0       # never replace one younger than this


def _replace_a_wedged_brain(port=8473) -> str:
    """Stop a daemon that holds the port and has stopped answering.

    Holding the port used to be proof enough that the brain was there, which
    it is for a BUSY daemon and is not for a WEDGED one: the founder was left
    with a listener that answered nothing for the rest of the session. After
    two minutes of silence from something that still holds the port, it is not
    busy any more. Only a process that is really serving this port is stopped.
    """
    import subprocess as _sp

    stopped = []
    try:
        listing = _sp.run(
            ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
            timeout=15, creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
        for line in listing.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] == "TCP" and parts[-2] == "LISTENING"                     and parts[1].endswith(":%d" % port):
                stopped.append(parts[-1])
    except Exception as exc:
        return "could not find what holds :%d (%s)" % (port, str(exc)[:60])
    for pid in dict.fromkeys(stopped):
        try:
            _sp.run(["taskkill", "/PID", pid, "/F"], capture_output=True,
                    timeout=15, creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
        except Exception:
            pass
    return "stopped the wedged holder of :%d (pid %s)" % (
        port, ", ".join(dict.fromkeys(stopped)) or "none found")


def _watch_brain() -> None:
    """Keep the brain online for as long as ArchHub runs.

    Starting it once at boot left the founder with a dead :8473 the moment
    the daemon fell over (2026-09-05, 16:20). Every 20 s: if nothing answers
    on the port, start it again and say so in the launch log. A daemon that
    holds the port but has answered nothing for two minutes is wedged, not
    busy, and is replaced rather than waited on forever.
    """
    import threading as _t
    import time as _time

    def loop() -> None:
        import time as _clock

        silent = 0
        started_watching = _clock.monotonic()
        while True:
            _time.sleep(20)
            try:
                outcome = str(_ensure_brain())
            except Exception as exc:
                outcome = "watch failed (%s)" % str(exc)[:80]
            if outcome.startswith("answering"):
                # _brain_answers treats a held port as alive, so reaching here
                # does not yet mean the daemon spoke. Ask it directly.
                if _brain_answers(timeout=12.0, strict=True):
                    silent = 0
                    continue
                silent += 1
                young = (_clock.monotonic() - started_watching) < _BRAIN_SETTLING_SECONDS
                if silent >= _WEDGED_CHECKS_BEFORE_REPLACING and not young:
                    silent = 0
                    started_watching = _clock.monotonic()
                    print("  brain      : %s (watchdog)" % _replace_a_wedged_brain(),
                          flush=True)
                continue
            silent = 0
            print("  brain      : %s (watchdog)" % outcome, flush=True)

    _t.Thread(target=loop, name="archhub-brain-watch", daemon=True).start()


_watch_brain()
print("  URL:", server.bootstrap_url, flush=True)


def _publish_map_to_cloud():
    """Push this graph's projection to the founder's 24/7 cloud cockpit.

    The cockpit is the map and the map is the graph -- so the cloud
    surface shows what the founder's application actually holds, and
    keeps showing the last known state when the desktop is closed.
    """
    import json
    import urllib.request

    # The website promises nothing leaves this machine. The upload runs
    # only when this machine holds an explicit consent record; deleting
    # that file closes the path again.
    from nodelang.cloud_publish_consent import cloud_publish_allowed
    if not cloud_publish_allowed(state_dir):
        return "off (no consent recorded; nothing left this machine)"
    cloud = (
        Path(os.environ["APPDATA"]) / "ArchHub" / "brain" / "cloud.json"
    )
    if not cloud.is_file():
        return "no cloud session on this machine"
    held = json.loads(cloud.read_text(encoding="utf-8"))
    token = held.get("token")
    base = held.get("cloud_base_url") or "https://archhub-cloud.fly.dev"
    if not token:
        return "cloud session carries no token"
    from nodelang.universal_pipeline import project_atlas_map

    script = project_atlas_map(
        server.universal_store, server.universal_registry
    )
    body = script.split("window.ATLAS_MAP = ", 1)[1]
    body = body.rsplit("; window.ATLAS_LIVE", 1)[0].encode("utf-8")
    request = urllib.request.Request(
        base.rstrip("/") + "/founder/map-state", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=25) as answer:
        return json.loads(answer.read().decode("utf-8"))


try:
    print("  cloud map  :", _publish_map_to_cloud(), flush=True)
except Exception as _refusal:
    print("  cloud map  : not published (%s)" % str(_refusal)[:90], flush=True)

# Announce THIS runtime as the machine's active universal runtime, so
# the brain, BABOOM and any governed agent reach the founder's live
# graph instead of a dead descriptor from a previous life.
_active_runtime = (
    Path(os.environ["LOCALAPPDATA"]) / "ArchHub" / "active-universal-runtime.json"
)
_previous_active = None
if os.environ.get("ARCHHUB_TEST_STATE_DIR"):
    # A verification run opens its OWN graph in its own state directory.
    # Announcing it would point the brain, BABOOM and every governed
    # agent on this machine at a throwaway database -- checking the
    # application must never move the founder's wiring onto it.
    print("  runtime    : not announced (verification run keeps the "
          "machine binding)", flush=True)
else:
    try:
        _active_runtime.parent.mkdir(parents=True, exist_ok=True)
        _previous_active = (
            _active_runtime.read_bytes() if _active_runtime.is_file() else None
        )
        _active_runtime.write_bytes(descriptor_path.read_bytes())
        print("  runtime    : announced as the machine's active universal "
              "runtime", flush=True)
    except OSError as _refusal:
        _previous_active = None
        print("  runtime    : could not announce (%s)" % _refusal, flush=True)

# The founder's first canvas: the wall pipeline plus the brain and BABOOM
# nodes, seeded idempotently and run once so every card opens carrying a
# real answer instead of a blank.
try:
    from nodelang.universal_pipeline import (
        run_universal_pipeline,
        seed_wall_pipeline,
    )
    # Seeding reads the canvas, then writes to it; a commit landing in
    # between makes the write's expected revision stale. That is ordinary
    # optimistic concurrency, and its answer is to re-read and try again
    # -- the seed is idempotent, so a retry adds nothing twice. Without
    # this a FRESH INSTALL opened with an empty canvas.
    for attempt in range(10):
        try:
            seed_wall_pipeline(
                server.universal_store, server.universal_registry
            )
            break
        except Exception as clash:
            # Only a revision clash is worth retrying. Anything else is a real
            # refusal and must surface at once instead of being slept over
            # four times. Four tries 0.4 s apart also lost to the boot's own
            # writers (the runtime announcement, the first map push): the
            # canvas came up empty with "expected revision 25791, current
            # revision is 25792". Ten tries with growing backoff outlast them.
            if "expected revision" not in str(clash) or attempt == 9:
                raise
            time.sleep(0.25 * (attempt + 1))
    outcome = run_universal_pipeline(
        server.universal_store,
        server.universal_registry,
        effect_engines=PIPELINE_ENGINES,
    )
    print("  pipeline   : %d node(s) ran" % outcome["ran"], flush=True)
except Exception as refusal:
    # A refusal nobody can locate is a refusal nobody can fix: name the
    # exact call that raised, not only its message.
    where = traceback.format_exc().strip().splitlines()
    spot = [line.strip() for line in where if "line " in line][-1:] or [""]
    print("  pipeline   : not seeded -- %s (%s)" % (refusal, spot[0]),
          flush=True)

if os.environ.get("ARCHHUB_TEST_NO_OPEN"):
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
    raise SystemExit(0)

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtWebEngineCore import QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView

app = QApplication(sys.argv)
app.setApplicationName("ArchHub")
app.setOrganizationName("ArchHub")

profile_root = state_dir / "web-profile"
profile_root.mkdir(parents=True, exist_ok=True)
profile = QWebEngineProfile.defaultProfile()
profile.setPersistentStoragePath(str(profile_root))
profile.setCachePath(str(profile_root / "cache"))

class _ArchHubWindow(QMainWindow):
    """Closing the window hides it: ArchHub keeps running in the background
    (the brain, BABOOM, the agents) exactly like Chrome or Claude Desktop, and
    the tray icon brings it back or quits it for real."""
    quitting = False

    def closeEvent(self, event):
        if self.quitting or getattr(self, "_tray", None) is None:
            return super().closeEvent(event)
        event.ignore()
        self.hide()
        try:
            self._tray.showMessage("ArchHub keeps running", "Open it again from the tray icon; Quit is there too.")
        except Exception:
            pass


window = _ArchHubWindow()
window.setWindowTitle("ArchHub")
# The brand icon, and a distinct AppUserModelID so the taskbar shows
# ArchHub rather than grouping under python's default.
import ctypes
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ArchHub.Test")
from PyQt6.QtGui import QIcon
# The installer ships archhub.ico beside this file; the 12.PRODUCTION tree
# exists only on the founder workstation, so it is the fallback, not the
# first look -- a colleague window carried the default python icon.
_icon_candidates = (
    Path(__file__).resolve().parent / "archhub.ico",
    Path(__file__).resolve().parents[1]
    / "12.PRODUCTION" / "app" / "assets" / "archhub.ico",
)
_icon_path = next((c for c in _icon_candidates if c.is_file()), _icon_candidates[0])
if _icon_path.is_file():
    app.setWindowIcon(QIcon(str(_icon_path)))
    window.setWindowIcon(QIcon(str(_icon_path)))
window.resize(1480, 920)
window.setMinimumSize(960, 640)
view = QWebEngineView(window)
window.setCentralWidget(view)
# The bootstrap lands on / to mint the session cookie, then the window
# lives on the studio face.
_booted = {"done": False}
def _to_studio(ok):
    if ok and not _booted["done"]:
        _booted["done"] = True
        view.load(QUrl(server.public_url + "/studio"))
view.loadFinished.connect(_to_studio)
# The studio's Browse buttons open THIS window's native file dialog; the
# chosen path goes back over the same origin. Runs on the Qt thread.
def _pick_file(title, name_filter):
    from PyQt6.QtWidgets import QFileDialog
    result = {}
    done = threading.Event()
    def ask():
        chosen, _ = QFileDialog.getOpenFileName(
            window, title, "", name_filter or "All files (*.*)")
        result["path"] = chosen
        done.set()
    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0, ask)
    done.wait(120)
    return result.get("path", "")
import threading
server.native_file_picker = _pick_file
# A dead render process reloads instead of leaving a dead window.
def _revive(_status, _code):
    print("  render process died -- reloading", flush=True)
    from PyQt6.QtCore import QTimer
    QTimer.singleShot(300, lambda: view.load(
        QUrl(server.public_url + "/studio")))
view.page().renderProcessTerminated.connect(_revive)
view.load(QUrl(server.bootstrap_url))
window.show()

# The tray icon: the visible sign that ArchHub is running in the background.
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

def _tray_open():
    from PyQt6.QtCore import QTimer as _QT
    window.showNormal(); window.raise_(); window.activateWindow()

    def _settle():
        # Qt alone leaves the window behind everything else on Windows. The
        # foreground dance runs after Qt has applied the state rather than
        # the same instant as showNormal(), restores once more if something
        # minimized the window meanwhile, and says where the window ended up
        # so the launcher log is the receipt (2026-09-06: a screen-capture
        # tool minimizing every window it was not allowed to see made the
        # window look minimized by us; the receipt settles that question).
        _force_foreground(window.winId())
        try:
            import ctypes
            user32 = ctypes.windll.user32
            handle = int(window.winId())
            if user32.IsIconic(handle):
                user32.ShowWindow(handle, 9)
            rect = (ctypes.c_long * 4)()
            user32.GetWindowRect(handle, ctypes.byref(rect))
            print("  show       : window %dx%d at %d,%d iconic=%s" % (
                rect[2] - rect[0], rect[3] - rect[1], rect[0], rect[1],
                bool(user32.IsIconic(handle))), flush=True)
        except Exception as failed:
            print("  show       : receipt unavailable: %s" % failed, flush=True)

    _QT.singleShot(150, _settle)

def _tray_check_updates():
    import threading as _t
    _t.Thread(target=_stage_once, name="archhub-update-check", daemon=True).start()
    _tray.showMessage("ArchHub", "Checking for a newer build; BABOOM will offer Restart now if there is one.")

def _tray_restart_to_update():
    import subprocess as _sp
    window.quitting = True
    _sp.Popen(["wscript.exe", str(Path(__file__).resolve().parent / "ArchHub.vbs")], close_fds=True, creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
    app.quit()

def _tray_quit():
    window.quitting = True
    app.quit()


def _watch_quit_request() -> None:
    """Quit cleanly when asked from outside, so the tray icon goes with us.

    Every update this week ended with the process being killed, and Windows
    keeps a dead process's tray icon until the mouse crosses it: the founder
    clicked ArchHub in the tray and nothing opened, because that icon belonged
    to a process that was gone (14 of them in one day, 2026-09-06). A file in
    the state directory is the ask; the app quits the way the menu quits.
    """
    from PyQt6.QtCore import QTimer as _QT

    marker = state_dir / "quit-request"
    # The same file-shaped ask brings the window up: an updater, a colleague
    # script or a verification run can open ArchHub the way the tray click
    # does, on the Qt thread, without touching the window from outside
    # (an external ShowWindow leaves Qt believing the widget is hidden).
    shower = state_dir / "show-request"
    # A marker written before THIS process started was meant for the copy that
    # is already gone. Leaving it made a freshly installed build read it and
    # quit itself the moment it finished booting (2026-09-06 13:19). Clear it
    # once, at startup, before anyone watches for it.
    try:
        if marker.is_file():
            marker.unlink()
    except Exception:
        pass
    try:
        if shower.is_file():
            shower.unlink()
    except Exception:
        pass

    def _look():
        if shower.is_file():
            try:
                shower.unlink()
            except Exception:
                pass
            print("  show       : asked from outside; bringing the window up", flush=True)
            _tray_open()
        if marker.is_file():
            try:
                marker.unlink()
            except Exception:
                pass
            print("  quit       : asked from outside; leaving cleanly", flush=True)
            _tray_quit()

    timer = _QT(app)
    timer.setInterval(2000)
    timer.timeout.connect(_look)
    timer.start()
    app._archhub_quit_watch = timer

def _tray_menu_about_to_show():
    _restart_action.setVisible((state_dir / "updates" / "staged.json").is_file())

if QSystemTrayIcon.isSystemTrayAvailable():
    _tray = QSystemTrayIcon(app.windowIcon(), app)
    _tray.setToolTip("ArchHub - running")
    _menu = QMenu()
    _menu.addAction("Open ArchHub", _tray_open)
    _menu.addAction("Check for updates now", _tray_check_updates)
    _restart_action = _menu.addAction("Restart to install the update", _tray_restart_to_update)
    _menu.addSeparator()
    _menu.addAction("Quit ArchHub", _tray_quit)
    _menu.aboutToShow.connect(_tray_menu_about_to_show)
    _tray.setContextMenu(_menu)
    _tray.activated.connect(lambda reason: _tray_open() if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
    _tray.show()
    window._tray = _tray
    _watch_quit_request()
    # The notify card lands on this tray. Engines run on worker threads and
    # Qt widgets belong to this one, so the ask crosses over as a queued
    # signal rather than a direct call.
    from PyQt6.QtCore import QObject as _QObject, pyqtSignal as _signal
    from nodelang.library_engines import set_notify_surface

    class _Notifier(_QObject):
        asked = _signal(str, str)

    _notifier = _Notifier(app)
    _notifier.asked.connect(lambda title, message: _tray.showMessage(title, message))
    set_notify_surface(lambda title, message: _notifier.asked.emit(str(title), str(message)))
    app.setQuitOnLastWindowClosed(False)
    print("  tray       : icon shown (close hides to tray; Quit is in the menu)", flush=True)
else:
    print("  tray       : no system tray on this desktop", flush=True)
# A window that opens BEHIND the founder's other windows reads as "the
# app didn't open". Every launch lands on top, once.
window.raise_()
window.activateWindow()

# BABOOM: the ambient companion, attached through the SAME signed
# agent-session path any governed agent uses. A failure to attach is
# printed honestly and never fakes a companion.
baboom_host = None
try:
    from nodelang.baboom_attach import attach_baboom_companion
    from nodelang.application_machine_transport import MachineTransportError
    # The runtime pipe comes up a beat after the HTTP server on a busy
    # machine. One attempt printed "universal runtime did not respond" and
    # left the founder with no companion for the whole session; a short
    # retry is what every client of a just-started service does.
    _attach_error = None
    for _attempt in range(6):
        try:
            # A retry is the same launcher, not a second process: connect()
            # binds the session identity before start() can time out, so a
            # retry under the same id is refused as "already bound". Each
            # attempt therefore carries its own id; the abandoned binding
            # expires on its own lease.
            baboom_host, baboom_window = attach_baboom_companion(
                server,
                state_dir=state_dir,
                descriptor_path=descriptor_path,
                key_provider=machine_key_provider,
                external_session_id=(
                    "founder-desktop-baboom" if _attempt == 0
                    else "founder-desktop-baboom:retry-%d" % _attempt
                ),
            )
            break
        except Exception as exc:
            text = str(exc)
            if "did not respond" not in text and "already bound" not in text:
                raise
            _attach_error = exc
            time.sleep(2.5)
    else:
        raise _attach_error
    # Where BABOOM actually lands, every time it changes. The founder has
    # twice reported it missing while the app said it was drawing.
    try:
        controller = getattr(baboom_window, "controller", None) or getattr(baboom_host, "controller", None)
        if controller is not None and hasattr(controller, "watch_geometry"):
            controller.watch_geometry(state_dir / "baboom-geometry.log")
    except Exception:
        pass
    baboom_window.show()
    # show() only makes the widget exist; projection is what makes BABOOM
    # actually draw itself and follow the graph.
    baboom_window.start_projection()
    # The cockpit drives THIS application: instructions typed into the cloud
    # ask bar are claimed here, put to BABOOM through its own signed session,
    # and answered back; the live map projection is re-published as it changes.
    try:
        from nodelang.cloud_relay import start_cloud_relay as _start_relay
        from nodelang.universal_pipeline import project_atlas_map as _atlas

        _controller = getattr(baboom_window, "controller", None) or getattr(baboom_host, "controller", None)
        _respond = (lambda u: _controller.respond(u)) if _controller is not None else (lambda u: baboom_host.respond_input(u))
        _execute = (lambda u: _controller.execute(u)) if _controller is not None else (lambda u: baboom_host.execute_input(u))
        cloud_relay = _start_relay(
            appdata=Path(os.environ["APPDATA"]), state_dir=state_dir,
            respond=_respond, execute=_execute,
            map_script=lambda: _atlas(server.universal_store, server.universal_registry),
            hosts=lambda: server._host_rows(),
        )
        print("  cockpit    :", "relay on (%s)" % cloud_relay.base_url if cloud_relay else "relay off (no cloud session or consent)", flush=True)
    except Exception as _relay_error:
        print("  cockpit    : relay failed (%s)" % str(_relay_error)[:120], flush=True)
    # Say honestly whether the companion has anything to draw: a host
    # with no snapshot, or a screen too crowded for a clear placement,
    # hides itself -- and a silent hide reads as "BABOOM is broken".
    from PyQt6.QtCore import QTimer as _QTimer

    def _report_companion():
        snapshot = getattr(baboom_host, "latest_snapshot", None)
        if snapshot is None:
            print("  BABOOM     : attached, waiting for its first snapshot",
                  flush=True)
            return
        visible = baboom_window.isVisible()
        rect = baboom_window.geometry()
        print("  BABOOM     : drawing=%s at %dx%d+%d+%d" % (
            visible, rect.width(), rect.height(), rect.x(), rect.y()),
            flush=True)
    _QTimer.singleShot(6000, _report_companion)
    print("  BABOOM     : attached (signed agent session)", flush=True)
except Exception as refusal:
    print("  BABOOM     : not attached -- %s" % refusal, flush=True)
    # The cockpit relay used to live inside the BABOOM block, so a companion
    # that failed to attach took the founder's whole cockpit with it: every
    # control on the web read "waiting for the app push" and nothing said why
    # (2026-09-06 00:27, "runtime device proof challenge is invalid"). They are
    # separate failures now. Without BABOOM the relay answers from the server
    # itself, so questions and engine runs still work; only the companion's own
    # voice is missing.
    try:
        from nodelang.cloud_relay import start_cloud_relay as _start_relay_alone
        from nodelang.universal_application import (
            respond_universal_baboom_utterance as _respond_alone,
        )
        from nodelang.universal_pipeline import project_atlas_map as _atlas_alone

        _context = server.universal_registry.authorization.session.context()

        def _answer_without_baboom(utterance):
            return _respond_alone(
                server.universal_store, server.universal_registry,
                utterance=utterance, authentication_context=_context,
            )

        def _refuse_without_baboom(utterance):
            # Reads are safe from here; an ACT must go through the companion's
            # signed session and the application's mutation lock, so the
            # cockpit is told plainly rather than acting unsigned.
            return {
                "command": {"intent": "open-question", "payload": utterance},
                "response": {
                    "kind": "companion-absent",
                    "summary": ("BABOOM did not attach on this launch, so the app can "
                                "answer but cannot act. Reopen ArchHub to restore it."),
                    "data": {},
                },
            }

        cloud_relay = _start_relay_alone(
            appdata=Path(os.environ["APPDATA"]), state_dir=state_dir,
            respond=_answer_without_baboom, execute=_refuse_without_baboom,
            map_script=lambda: _atlas_alone(server.universal_store, server.universal_registry),
            hosts=lambda: server._host_rows(),
        )
        if cloud_relay is not None:
            print("  cockpit    : relay on, answers only (BABOOM did not attach)",
                  flush=True)
    except Exception as relay_refusal:
        print("  cockpit    : relay off -- %s" % relay_refusal, flush=True)

# While the founder works, look once for a newer release and stage it for
# the next launch. Never applied here; never blocks the window.
def _stage_update_quietly():
    # First look two minutes after boot, then every thirty minutes: a build
    # published while the app is open is staged within the half hour and
    # installed by the next close-and-open, or by the Restart button.
    time.sleep(120)
    while True:
        _stage_once()
        time.sleep(1800)

def _stage_once():
    try:
        from nodelang.quiet_update import stage_if_newer
        outcome = stage_if_newer(state_dir, Path(__file__).resolve().parent)
        print("  update     : %s%s" % (outcome.get("reason"), " (build %s)" % outcome["build_id"] if outcome.get("build_id") else ""), flush=True)
    except Exception as refusal:
        print("  update     : check failed -- %s" % refusal, flush=True)

import threading as _threading
_threading.Thread(target=_stage_update_quietly, name="archhub-quiet-update", daemon=True).start()

try:
    code = app.exec()
except BaseException:
    traceback.print_exc()
    code = 1
finally:
    if baboom_host is not None:
        try:
            baboom_host.stop()
        except Exception:
            pass
    # Leaving a descriptor behind that points at a dead pipe is what
    # made every brain write fail; put back whatever was there before.
    try:
        if _previous_active is None:
            _active_runtime.unlink(missing_ok=True)
        else:
            _active_runtime.write_bytes(_previous_active)
    except OSError:
        pass
    server.close()
raise SystemExit(code)
