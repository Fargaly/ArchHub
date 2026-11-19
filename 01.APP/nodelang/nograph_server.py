"""NOGRAPH server: the same Studio, served from plain files. No graph is opened.

Strangler pattern (2026-10-28): every route the Studio calls is answered here by
the owner that holds that data as a plain file or one small SQLite file.

  Canvas      .archhub documents            session_files.SessionFiles
  Workshop    workshop/messages.sqlite3     workshop_mailbox + Workshop
  Router      settings/router.json + router.sqlite   model_router / settings_owner
  Hosts       live broker sessions/*.json   pipeline_engines.probe_connectors
  Settings    settings/<name>.json          this module (one file per owner)

The universal graph journal is never opened and application_server is never
imported. Routes whose data lived only in the graph answer an empty read or a
plain ``not_available`` refusal the Studio already shows as a notice.
"""
from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import tempfile
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from .http_server import QuietThreadingHTTPServer, local_browser_admission_error

def _mouse_double_click_ms():
    # Match the user's Windows accessibility setting. Browser-only hosts use the platform default.
    if os.name == 'nt':
        return int(ctypes.windll.user32.GetDoubleClickTime())
    return 500


STUDIO_DIR = Path(__file__).resolve().parent / 'studio'
MAX_BODY = 1024 * 1024
SESSION_BODY = 9 * 1024 * 1024
COOKIE = 'archhub_studio'
# Cloud relay node: its typed parameters.
RELAY_NODE = {'id': 'cloud.relay', 'params': {'close_timeout_seconds': 6.0}}
WORKSHOP_PATH = '/api/universal/workshop'
ROUTER_FILE = 'router.json'


_SERVER = None  # the running NoGraphServer (one per app process)


class Refused(Exception):
    def __init__(self, message, status=409, *, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


def not_available(what):
    return {'ok': False, 'status': 'not_available',
            'error': what + ' is unavailable in this release.'}


class JsonFile:
    """One settings owner = one small JSON file, replaced atomically."""

    def __init__(self, path, default):
        from .session_files import _METADATA_LOCK
        self.path, self.default, self.lock = Path(path), default, _METADATA_LOCK

    def read(self):
        from .user_paths import strip_test_write
        with self.lock:
            try:
                return strip_test_write(json.loads(self.path.read_text(encoding='utf-8')))
            except FileNotFoundError:
                return json.loads(json.dumps(self.default))

    def write(self, value):
        from .user_paths import stamp_test_write
        from .session_files import _metadata_io
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=self.path.parent, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(stamp_test_write(value), stream, ensure_ascii=False, indent=1)
                _metadata_io(os.replace, temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return value


    def update(self, changes, remove=()):
        with self.lock:
            value = {**self.read(), **changes}
            for key in remove:
                value.pop(key, None)
            return self.write(value)


def _refresh_opencode_plugin(state_dir, environment=None):
    """An older ArchHub Workshop plugin for OpenCode is rewritten in the current format at start.

    Only the installed app's own server does it: a server on any other state folder (a test, a second
    copy) never touches the person's OpenCode folder. Returns the registration row, or None when skipped."""
    from .assistant_registration import refresh_opencode_plugin
    from .client_mcp_installation import RegistrationRefused
    from .user_paths import state_directory
    env = dict(os.environ if environment is None else environment)
    if 'ARCHHUB_TEST_STATE_DIR' in env or 'ARCHHUB_STATE_DIR' in env:
        return None
    if os.path.normcase(os.path.abspath(str(state_dir))) != os.path.normcase(os.path.abspath(str(state_directory(env)))):
        return None
    try:
        result = refresh_opencode_plugin(env)
    except (OSError, ValueError, RegistrationRefused) as failed:
        print('OpenCode Workshop plugin refresh failed: %s' % failed, flush=True)
        return None
    if result.get('state') == 'registration_unconfirmed':
        print('OpenCode Workshop plugin refresh unconfirmed: %s' % result.get('reason'), flush=True)
    return result


class Cached:
    """A probe refreshed off the request path; None until its first answer."""

    def __init__(self, seconds, probe):
        self.seconds, self.probe, self.value, self.at, self.running = seconds, probe, None, 0.0, False
        self.lock = threading.Lock()
        self.generation = 0

    def get(self):
        with self.lock:
            stale = time.time() - self.at >= self.seconds
            if stale and not self.running:
                self.running = True
                threading.Thread(target=self._run, args=(self.generation,), name='archhub-nograph-probe', daemon=True).start()
        return self.value

    def reset(self, value):
        with self.lock:
            self.generation += 1
            self.value, self.at = value, 0.0

    def _run(self, generation):
        try:
            value = self.probe()
        except Exception:  # noqa: BLE001 - a failed probe keeps the last answer
            value = self.value
        with self.lock:
            if generation == self.generation:
                self.value, self.at = value, time.time()
            self.running = False


class NoGraphServer:
    def __init__(self, state_dir, *, host='127.0.0.1', port=0, engines=None, agent_source=None):
        _STORE_VERSION_CLOSED[0] = False  # a new server may keep a store watcher again
        self.state_dir = Path(state_dir)
        self.settings_dir = self.state_dir / 'settings'
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        self.engines = engines
        self.browser_bootstrap_token = secrets.token_urlsafe(32)
        self.browser_session_token = secrets.token_urlsafe(32)
        self.browser_csrf_token = secrets.token_urlsafe(32)
        self._cookie_token = secrets.token_urlsafe(32)
        self._bootstrap_used = False
        self._halted = threading.Event()
        self._stop_epoch = 0                  # bumped by Stop everything and by app close; never goes back
        self._closing = threading.Event()     # set by app close; never cleared
        self.studio_first_run = False
        # The launcher binds these exactly as it did for the old server.
        self.native_file_picker = self.native_folder_picker = self.native_save_file_picker = None
        self.native_window_handle = None
        self.application_update = None
        files = lambda name, default: JsonFile(self.settings_dir / (name + '.json'), default)
        self.files = {name: files(name, default) for name, default in (
            ('workspaces', {'roots': []}), ('mods', {'packages': {}, 'enabled': {}}),
            ('companion', {'mode': 'idle', 'x': None, 'y': None, 'pinned': False}),
            ('social', {'state': {}}), ('community', {}), ('hosts', {'disabled': []}), ('project-files', {'files': []}),
            ('settings', {'settingsScope': 'User'}))}
        self._hosts = Cached(30.0, self._probe_hosts)
        self._local = Cached(10.0, self._probe_local)
        self._account_key = None
        self._account = None
        self._account_lock = threading.Lock()
        self._session = Cached(30.0, self._probe_session)
        self._live_agents = Cached(5.0, agent_source if agent_source is not None else self._probe_agents)
        self._providers = Cached(30.0, self._probe_providers)
        self._models = Cached(45.0, self._probe_models)
        self._workshop_agents = Cached(5.0, self._probe_workshop_agents)
        self._messages = Cached(1.0, _list_messages)
        self._opencode = {}
        self._chat_turns = set()  # threads answering /api/router/chat right now; an update waits for them
        self._terminals = None
        self._agents_api = None
        self.httpd = QuietThreadingHTTPServer((host, port), self._handler())
        global _SERVER
        _SERVER = self
        self.thread = None
        self.cloud_relay = None
        self._relay_lock = threading.Lock()
        # Who holds the relay and the trigger service: taken briefly by close() and by the warm-up when it hands over
        # what it made, never while a relay is being started (close() must not wait for a slow start).
        self._owned_lock = threading.Lock()

    def busy_reason(self):
        """Why an update restart must wait now, read from this desktop's own live work; None when idle.

        Workshop agents run around the clock in their own processes; counting them
        would mean the update never installs. They get the normal restart notice.
        """
        if getattr(self, '_canvas_jobs', 0):
            return 'A canvas run is in progress; the update waits for it to finish.'
        if getattr(getattr(self, 'triggers', None), 'running', None):
            return 'An automation is running; the update waits for it to finish.'
        if self._chat_turns:
            return 'A chat answer is still arriving; the update waits for it to finish.'
        if getattr(self, '_unsaved_views', None):
            return 'A canvas has unsaved changes or an unresolved save conflict; save or choose Keep/Discard first.'
        return None

    # -- lifecycle (same surface the launcher used) ------------------------
    @property
    def port(self):
        return self.httpd.server_address[1]

    @property
    def public_url(self):
        return 'http://127.0.0.1:%d' % self.port

    def start(self):
        # Load read owners before accepting HTTP, rather than on the first click.
        from importlib import import_module
        for module in ('workshop_api', 'baboom_nograph', 'settings_owner', 'session_files', 'model_catalogue',
                       'model_router', 'agent_runtime_registry', 'host_exec', 'site_export'):
            import_module('.' + module, __package__)
        from .model_router import request_profiles
        request_profiles()
        self._messages.value = _list_messages()
        self._messages.at = time.time()
        self._session.value = self._read_session()
        self.triggers = None  # F38: TriggerService scans session files; build it after listen
        self.thread = threading.Thread(target=self.httpd.serve_forever, name='archhub-nograph-http', daemon=True)
        self.thread.start()
        port_file = self.state_dir / "nograph-http-port"
        port_file.write_text("%d\n" % self.port, encoding="ascii")
        # Hosts and local probes are Cached: start their background refresh without blocking listen.
        self._hosts.get()
        self._local.get()
        # F38 / SLOWHOME: cloud relay and TriggerService must not hold "server up" for tens of seconds.
        threading.Thread(target=self._warm_after_listen, name='archhub-nograph-warm', daemon=True).start()
        threading.Thread(target=_refresh_opencode_plugin, args=(self.state_dir,), name='archhub-opencode-plugin',
                         daemon=True).start()
        return self

    def _warm_after_listen(self):
        """Finish non-admission work after HTTP is already answering Home."""
        try:
            self.ensure_cloud_relay()
        except Exception as refused:  # noqa: BLE001 - Home stays up; relay is optional warm-up
            print('  cloud relay: warm-up skipped -- %s' % refused, flush=True)
        try:
            if self._closing.is_set():
                return  # closing: the warm-up makes nothing more
            from .canvas_triggers import TriggerService
            service = TriggerService(pause_settings=self.files['settings'])
            if not self._own('triggers', service):
                return
            service.refresh()
        except Exception as refused:  # noqa: BLE001 - schedules arm when ready; boot must not wait
            print('  triggers   : warm-up skipped -- %s' % refused, flush=True)

    def _own(self, name, made):
        """Hand what the warm-up made to the server (relay or trigger service); True when the server now owns it.

        Owned by the server's lifecycle: once close() has started, nothing is attached and what was made is closed
        here, since close() has already passed it by."""
        with self._owned_lock:
            if not self._closing.is_set():
                setattr(self, name, made)
                return True
        try:
            made.close(**({'timeout_seconds': RELAY_NODE['params']['close_timeout_seconds']} if name == 'cloud_relay' else {}))
        except Exception as stuck:  # noqa: BLE001 - closing the app goes on
            print('  %s: made during close, did not stop -- %s' % (name, stuck), flush=True)
        return False

    def health_check(self):
        import sqlite3
        from urllib.request import urlopen
        from .session_files import sessions_directory
        from .library_engines import LIBRARY_ITEM_ENGINES
        limits = LIBRARY_ITEM_ENGINES['tool_workshop']['params']
        for path in self.settings_dir.glob('*.json'):
            json.loads(path.read_text(encoding='utf-8'))
        sessions_directory()
        database = self.state_dir / 'workshop' / 'messages.sqlite3'
        if database.exists():
            with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=limits['preflight_database_ms'] / 1000) as connection:
                if connection.execute('PRAGMA quick_check').fetchone() != ('ok',):
                    return False
        with urlopen(self.public_url + '/api/alive', timeout=limits['worker_join_ms'] / 1000) as response:
            return response.status == 204 and self.thread.is_alive()

    def ensure_cloud_relay(self, *, restart=False):
        """Remote agents reach this PC's brokers through the existing cloud relay (cloud_relay.py).

        Same account session (Credential Manager, by reference) and the same recorded
        cloud-publish consent as before; without both start_cloud_relay returns None.
        Host reads, gated effects (canvas.run, host.exec, connector.call) and
        Workshop send/read are claimed. Each claimed call still passes decide().
        """
        with self._relay_lock:
            if self._closing.is_set():
                return None  # closing: no relay is started or attached any more
            held = self.cloud_relay
            if held is not None and not restart and not held._stop.is_set():
                return held
            if held is not None:
                try:
                    held.close(timeout_seconds=RELAY_NODE['params']['close_timeout_seconds'])
                except Exception as stuck:  # noqa: BLE001 - a stuck old worker must not block a new one
                    print('  cloud relay: old worker did not stop -- %s' % stuck, flush=True)
            try:
                from .cloud_relay import HOST_EFFECT, HOST_READ, McpWorkshopAgents, start_cloud_relay
                from .workshop_mailbox import profile_database
                agents = McpWorkshopAgents(mailbox_path=profile_database())
                made = start_cloud_relay(
                    state_dir=self.state_dir, respond=lambda _text: {}, execute=lambda _text: {},
                    app_kinds=(HOST_READ, HOST_EFFECT), workshop_caller=agents.call)
            except Exception as refused:  # noqa: BLE001
                print('  cloud relay: not started -- %s' % refused, flush=True)
                made = None
            if made is None:
                with self._owned_lock:
                    self.cloud_relay = None
                return None
            return made if self._own('cloud_relay', made) else None

    def close(self):
        self._closing.set()   # admission is closed for good, and every admitted request is cancelled
        self._stop_epoch += 1
        from .acp_client import close_all
        close_all()   # no agent this app started outlives it
        with self._owned_lock:  # after this, the warm-up attaches nothing (_own closes what it makes)
            triggers, self.triggers = getattr(self, 'triggers', None), None
            relay, self.cloud_relay = self.cloud_relay, None
        if triggers is not None:
            triggers.close()
        if relay is not None:
            try:
                relay.close(timeout_seconds=RELAY_NODE['params']['close_timeout_seconds'])
            except Exception as stuck:  # noqa: BLE001 - closing the app goes on
                print('  cloud relay: did not stop -- %s' % stuck, flush=True)
        _close_store_version()  # its sqlite connection must be closed on the thread that opened it
        self.httpd.shutdown()
        self.httpd.server_close()
        try:
            (self.state_dir / "nograph-http-port").unlink(missing_ok=True)
        except OSError as stuck:
            print('  nograph    : live port was not cleared (%s)' % type(stuck).__name__, flush=True)
        from .brain_files import close as close_brain
        close_brain()

    def opencode_status(self, executable):
        """OpenCode auth/run readiness off the request path, 30 s like the old server's cache: the 5 s
        Providers poll must not start the OpenCode CLI twice per poll (385 MB opencode.exe at idle)."""
        from .model_router import probe_opencode_status
        probe = self._opencode.setdefault(str(executable), Cached(30.0, lambda: probe_opencode_status(executable)))
        return probe.get() or {'installed': bool(executable)}  # until the first answer: installed, nothing claimed

    def is_halted(self):
        return self._halted.is_set()

    def admit_chat(self):
        """Admits one chat request (refused while stopped or closing) and returns its `cancelled`: true for good once
        Stop everything or app close happens after this point. Resume clears the halted flag, never this."""
        epoch = self._stop_epoch   # read before the halted check: a Stop in between either refuses or cancels
        if self._closing.is_set():
            raise Refused('ArchHub is closing.', 403)
        if self._halted.is_set():
            raise Refused('Stopped by you. Press Resume to continue.', 403)
        return lambda: self._closing.is_set() or self._stop_epoch != epoch

    def halt_all(self):
        self._stop_epoch += 1
        self._halted.set()
        from .acp_client import close_all
        close_all()   # Stop everything ends every agent this app started; the next send starts one again

    def resume_all(self):
        self._halted.clear()

    # -- probes -------------------------------------------------------------
    @staticmethod
    def _probe_agents():
        from .agent_runtime_registry import discover_runtime_processes
        return discover_runtime_processes()

    @staticmethod
    def _probe_workshop_agents():
        from .workshop_live import live_agents
        return live_agents(with_status=True)

    @staticmethod
    def _probe_models():
        from .cloud_relay import load_cloud_session
        from .model_catalogue import groups_with_routes, held_model_groups_read_only
        held = held_model_groups_read_only(load_cloud_session())
        return groups_with_routes(held) if held is not None else {'ok': True, 'groups': [], 'count': 0}

    def _probe_providers(self):
        from .model_router import provider_rows, find_assistant
        from .cloud_relay import load_cloud_session
        states = self._local.get()
        return provider_rows(cloud_session=load_cloud_session(),
            local_probe=lambda _host, port: None if states is None else states.get(int(port)),
            cli_probe=find_assistant, opencode_status_probe=self.opencode_status)

    def _probe_session(self):
        from .cloud_signin import session_summary
        summary = session_summary()
        if summary.get('signed_in'):
            self.ensure_cloud_relay()
        return self._read_session()

    @staticmethod
    def _read_session():
        from .cloud_signin import read_cloud_session, sign_in_state
        from .cloud_session import _account_key, cloud_session_path
        held = read_cloud_session(cloud_session_path())
        state = sign_in_state(session=held)
        return {**state, '_cache_key': _account_key(held)
                if state.get('signed_in') else ''}

    def account_read(self):
        with self._account_lock:
            return self._account_read()

    def _account_read(self):
        from .settings_owner import AccountFiles, SettingsOwner, cloud_call
        from .cloud_signin import read_cloud_session
        from .cloud_session import cloud_session_path, _account_key
        state = self._session.get() or {}
        key = state.get('_cache_key', '') if state.get('signed_in') else ''
        if not key:
            self._account_key, self._account = None, None
            return {'accountChecking': self._session.running}
        if self._account_key != key:
            store = AccountFiles(self.settings_dir / 'account.json')
            root = 'cached-read:' + key

            def refresh():
                held = read_cloud_session(cloud_session_path())
                if not held.get('token') or _account_key(held) != key:
                    raise Refused('Account changed during refresh.')
                value = SettingsOwner(store, cloud=lambda *args, **kwargs: cloud_call(
                    *args, **kwargs, session=held)).read()
                if self._read_session().get('_cache_key') != key:
                    raise Refused('Account changed during refresh.')
                try:
                    store.write(root, value)
                except (OSError, ValueError):
                    value = {**value, 'controlErrors': {**value.get('controlErrors', {}),
                             'accountCache': 'Account read succeeded; its offline copy could not be saved.'}}
                return value

            self._account = Cached(30.0, refresh)
            self._account.value = store.read(root)
            self._account_key = key
        return {**(self._account.get() or {}), 'accountChecking': self._account.running}

    @staticmethod
    def _probe_hosts():
        from .pipeline_engines import probe_connectors
        return list(probe_connectors())

    @staticmethod
    def _probe_local():
        from .model_router import probe_local_runtimes
        return probe_local_runtimes()

    # -- HTTP ----------------------------------------------------------------
    def _handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            disable_nagle_algorithm = True

            def log_message(self, *_args):
                return

            def send_json(self, status, payload, headers=()):
                raw = json.dumps(payload, separators=(',', ':'), default=str).encode('utf-8')
                if status == 200:
                    # RFC 9110 conditional read: an unchanged answer to a Studio poll is a bodiless 304.
                    etag = '"%s"' % hashlib.sha256(raw).hexdigest()[:32]
                    headers = (*headers, ('ETag', etag))
                    if self.headers.get('If-None-Match') == etag:
                        status, raw = 304, b''
                try:
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Length', str(len(raw)))
                    for name, value in headers:
                        self.send_header(name, value)
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    self.close_connection = True  # the client hung up; nothing can be sent

            def body(self, limit=MAX_BODY):
                length = int(self.headers.get('Content-Length') or 0)
                if length < 0 or length > limit:
                    self.close_connection = True
                    raise Refused('Request body exceeds the allowed size.', 413)
                raw = self.rfile.read(length) if length else b''
                self._body_read = True
                return json.loads(raw.decode('utf-8') or '{}') if raw else {}

            def cookie(self):
                for part in (self.headers.get('Cookie') or '').split(';'):
                    name, _, value = part.strip().partition('=')
                    if name == COOKIE:
                        return value
                return ''

            def admitted(self):
                token, csrf = self.headers.get('X-ArchHub-Session') or '', self.headers.get('X-ArchHub-CSRF') or ''
                return (hmac.compare_digest(token, owner.browser_session_token)
                        and hmac.compare_digest(csrf, owner.browser_csrf_token))

            def do_GET(self):
                self.dispatch('GET')

            def do_POST(self):
                self.dispatch('POST')

            def dispatch(self, method):
                self._body_read = False
                parsed = urlparse(self.path)
                path = parsed.path
                try:
                    if method == "GET" and path == "/api/alive":
                        # Loopback liveness for a second launch. No session, no body.
                        self.send_response(204)
                        self.end_headers()
                        return
                    denied = local_browser_admission_error(self.headers, owner.port)
                    if denied:
                        raise Refused(denied, 403)
                    if method == 'GET' and path == '/favicon.ico':
                        from .site_export import BRAND_DIR
                        owner._send_bytes(self, (BRAND_DIR / 'favicon.ico').read_bytes(), 'image/x-icon')
                        return
                    if method == 'GET' and (path in ('/', '/studio', '/studio/') or path.startswith('/studio/')):
                        owner._studio(self, parsed)
                        return
                    if method == 'GET' and (path == '/assets/fonts.css' or path.startswith('/assets/fonts/')):
                        owner._font(self, path)
                        return
                    if method == 'GET' and path == '/assets/baboom/spritesheet.png':
                        # The one BABOOM atlas, the companion window's own file: his panel header draws him from it.
                        from .baboom_native_runtime import default_baboom_sprite_atlas_path
                        owner._send_bytes(self, default_baboom_sprite_atlas_path().read_bytes(), 'image/png')
                        return
                    if path == '/baboom/turn' and method == 'POST':
                        # The app's BABOOM turn door (loopback, per-boot token): any agent's connector reaches it.
                        from .baboom_nograph import accept_turn
                        turn = self.body()
                        self.send_json(200, accept_turn(self.headers.get('X-ArchHub-BABOOM'), turn.get('text'), turn.get('message_id')))
                        return
                    if path == '/baboom/companion' and method == 'POST':
                        # BABOOM's own companion process (loopback, per-boot token it was started with).
                        from .baboom_companion_process import HEADER, door
                        self.send_json(200, door(self.headers.get(HEADER), self.body()))
                        return
                    if path == '/api/universal/session' and method == 'POST':
                        owner._sign_in(self)
                        return
                    if not self.admitted():
                        raise Refused('Browser session required. Reopen ArchHub.', 403)
                    if path == '/api/router/chat':
                        turn = threading.get_ident()
                        owner._chat_turns.add(turn)
                        try:
                            owner._router_chat(self)
                        finally:
                            owner._chat_turns.discard(turn)
                        return
                    route = ROUTES.get(path) or (BRAIN if path.startswith('/api/universal/brain-') else None)
                    if route is None:
                        raise Refused('No such route.', 404)
                    if method == 'GET' and path in POST_ONLY:
                        raise Refused('This action needs a POST from the Studio.', 405)
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    body = self.body(SESSION_BODY if path == '/api/session-files' else MAX_BODY) if method == 'POST' else None
                    writes = isinstance(body, dict) and (
                        path in ('/api/session-files', '/api/session-model') and body.get('action') not in _SESSION_READ_ACTIONS
                        or path == WORKSHOP_PATH and (body.get('action') != 'data-api' or body.get('function') not in _WORKSHOP_READ_FUNCTIONS))
                    if writes:
                        _drop_column()  # a write can change a task row (its path, plan, messages, status)
                    result = route[1](owner, SimpleNamespace(method=method, path=path, query=query, body=body, handler=self))
                    if writes:
                        _drop_column()  # and a read on another thread during the write must not stay shared
                    self.send_json(200, result if isinstance(result, dict) else {'ok': True, 'result': result})
                except Refused as refusal:
                    if method == 'POST' and not self._body_read:
                        # Unread POST bytes can reset the socket before Windows receives the refusal.
                        self.close_connection = True
                        try:
                            length = int(self.headers.get('Content-Length') or 0)
                            if 0 < length <= (SESSION_BODY if path == '/api/session-files' else MAX_BODY):
                                from .library_engines import LIBRARY_ITEM_ENGINES
                                deadline = time.monotonic() + LIBRARY_ITEM_ENGINES['tool_workshop']['params']['worker_join_ms'] / 1000
                                while length > 0:
                                    remaining = deadline - time.monotonic()
                                    if remaining <= 0:
                                        break
                                    self.connection.settimeout(remaining)
                                    chunk = self.rfile.read1(min(length, 65536))
                                    if not chunk:
                                        break
                                    length -= len(chunk)
                        except (OSError, ValueError):
                            self.close_connection = True
                    body = {'ok': False, 'error': str(refusal)}
                    if refusal.code:
                        body['code'] = refusal.code
                    self.send_json(refusal.status, body)
                except (ValueError, TypeError, KeyError, OSError, RecursionError) as error:
                    self.send_json(400, {'ok': False, 'error': str(error) or type(error).__name__})
                except Exception as error:  # noqa: BLE001 - every owner failure is an answer, never a dropped socket
                    self.send_json(500, {'ok': False, 'error': '%s: %s' % (type(error).__name__, error)})

        return Handler

    # -- page, assets, session ---------------------------------------------
    def _studio(self, handler, parsed):
        name = parsed.path[len('/studio'):].lstrip('/') if parsed.path.startswith('/studio') else ''
        target = (STUDIO_DIR / (name or 'studio.html')).resolve()
        if STUDIO_DIR not in target.parents or not target.is_file():
            raise Refused('no such file', 404)
        headers = []
        raw = target.read_bytes()
        if target.suffix == '.html':
            bootstrap = (parse_qs(parsed.query).get('bootstrap') or [''])[0]
            known = hmac.compare_digest(handler.cookie(), self._cookie_token)
            if bootstrap and not self._bootstrap_used and hmac.compare_digest(bootstrap, self.browser_bootstrap_token):
                self._bootstrap_used, known = True, True
                headers.append(('Set-Cookie', '%s=%s; HttpOnly; SameSite=Strict; Path=/' % (COOKIE, self._cookie_token)))
            if not known:
                raise Refused('desktop bootstrap is required', 403)
            from .library_engines import LIBRARY_ITEM_ENGINES
            from .settings_owner import dock_layout
            raw = raw.replace(b'/*__ARCHHUB_BOOT__*/ null', json.dumps({
                'token': self.browser_session_token, 'csrf': self.browser_csrf_token,
                'first_run': self.studio_first_run is True,
                'mouse_double_click_ms': _mouse_double_click_ms(),
                'home_load_ms': LIBRARY_ITEM_ENGINES['tool_workshop']['params'].get('home_load_ms', 3000),
                # The dock is drawn from his one saved layout at the first frame: no default layout shows first.
                'dock_layout': dock_layout(settings=self.files['settings'])['dockLayout'],
                'workshop': {'root': 'app:workshop', 'scope': 'app:workshop'}, 'nograph': True}).encode('utf-8'))
            headers += [('Content-Security-Policy', "default-src 'none'; connect-src 'self'; img-src 'self' data:; "
                         "style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'self' 'unsafe-inline' "
                         "'unsafe-eval'; frame-ancestors 'none'"), ('X-Frame-Options', 'DENY')]
        kind = ('text/html; charset=utf-8' if target.suffix == '.html' else 'text/javascript; charset=utf-8'
                if target.suffix in ('.js', '.jsx') else mimetypes.guess_type(str(target))[0] or 'application/octet-stream')
        self._send_bytes(handler, raw, kind, headers)

    def _font(self, handler, path):
        from .site_export import BRAND_DIR, FONT_DIR, FONT_FACES, FONTS_CSS
        if path == '/assets/fonts.css':
            self._send_bytes(handler, FONTS_CSS.encode('utf-8'), 'text/css; charset=utf-8')
            return
        face = path[len('/assets/fonts/'):]
        if face not in {row[0] for row in FONT_FACES}:
            raise Refused('font not found', 404)
        self._send_bytes(handler, (BRAND_DIR / FONT_DIR / face).read_bytes(), 'font/woff2')

    @staticmethod
    def _send_bytes(handler, raw, kind, headers=()):
        handler.send_response(200)
        handler.send_header('Content-Type', kind)
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.send_header('Content-Length', str(len(raw)))
        for name, value in headers:
            handler.send_header(name, value)
        handler.end_headers()
        handler.wfile.write(raw)

    def _sign_in(self, handler):
        # A page reload re-reads its session: same-origin script, custom header, the bootstrap cookie.
        if handler.headers.get('X-ArchHub-Sign-In') != '1' or not hmac.compare_digest(handler.cookie(), self._cookie_token):
            raise Refused('Reopen ArchHub from its launcher.', 403)
        handler.body()
        handler.send_json(200, {'ok': True, 'token': self.browser_session_token, 'csrf': self.browser_csrf_token})

    def _router_chat(self, handler):
        body = handler.body()
        cancelled = self.admit_chat()
        streaming = False

        def event(value):
            nonlocal streaming
            if not streaming:
                handler.send_response(200)
                handler.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                handler.send_header('Cache-Control', 'no-store')
                handler.send_header('Connection', 'close')
                handler.end_headers()
                handler.close_connection = True
                streaming = True
            handler.wfile.write(('data: ' + json.dumps(value) + '\n\n').encode('utf-8'))
            handler.wfile.flush()
        try:
            event({'result': _chat(body, lambda text: event({'delta': text}), lambda step: event({'step': step}),
                                   cancelled=cancelled)})
        except Exception as error:  # noqa: BLE001 - the composer shows the refusal text
            message = str(error) or 'The router is unavailable. Check provider availability.'
            if streaming:
                event({'error': message})
            else:
                raise Refused(message, 400) from error

    # -- owners used by several routes --------------------------------------
    def terminals(self):
        if self._terminals is None:
            from .terminal_sessions import TerminalSessions
            root = self.workspace_built_in() or str(self.state_dir / 'terminal')
            self._terminals = TerminalSessions(root, create=True)
        return self._terminals

    def agents_api(self):
        if self._agents_api is None:
            from .app_agents import AgentsAPI
            from .workshop_mailbox import _local_transport
            try:
                transport = _local_transport()
            except Exception:  # noqa: BLE001 - Workshop runtime absent: listAgentSessions says so
                transport = None
            self._agents_api = AgentsAPI(transport=transport)
        return self._agents_api

    @staticmethod
    def workspace_built_in():
        try:
            from .workspace_roots_catalogue import built_in_path
            return built_in_path()
        except Exception:  # noqa: BLE001 - no governed tree on this machine
            return ''


def _ask_baboom(prompt, context=''):
    """The composer's BABOOM turn: Goose with its tools; a profiling row like any model route."""
    import uuid
    from .baboom_nograph import ask
    from .model_router import request_profiles
    started = time.monotonic()
    record = {'id': str(uuid.uuid4()), 'ts': time.time(), 'agent': 'BABOOM', 'model': 'goose', 'provider': 'Goose',
              'tokens': None, 'ms': 0, 'outcome': 'refused'}
    try:
        result = ask(prompt, context)
        record.update(model=result['via'].get('model', 'goose'), outcome='answered')
    finally:
        record['ms'] = int((time.monotonic() - started) * 1000)
        request_profiles(record)
    steps = ''.join('\n\u2022 %s: %s' % (s.get('tool'), s.get('status')) for s in result.get('steps', []))
    return {'ok': True, 'answer': result['text'] + steps, 'provider': 'BABOOM (Goose)', 'model': record['model'],
            'request_id': record['id'], 'applied': [], 'steps': result.get('steps', [])}


def _chat(body, on_delta, on_step=lambda step: None, cancelled=lambda: False):
    """One composer turn. @agents go live into those sessions (or are started over ACP when not running);
    no mention goes to BABOOM or the model. With a task, the question, the answer and every later reply are that task's thread."""
    import re
    from .model_router import composer_chat
    prompt = str(body.get('prompt') or '')
    task = body.get('task') or None
    task_context = ''
    if task is not None:
        from .workshop_mailbox import application_history
        from .workshop_tasks import get
        with application_history() as history:
            if type(task) is not str or get(history, task) is None:
                raise ValueError('This session is no longer in the Workshop. Reopen it from Home.')
            from .workshop_tasks import _bound_messages
            messages = _bound_messages(history, task)
            task_context = '\n\n'.join('%s: %s' % (m['who'], m['text']) for m in messages if m['text'])
    handles = [h.casefold() for h in re.findall(r'(?<![\w@])@([A-Za-z0-9][\w.-]*)', prompt)]
    from .acp_client import agent_for
    if agent_for(body.get('agent')) and (body.get('continue') is True or not handles):
        # the composer's agent picker only STARTS a chat agent (or is refused); it never messages a joined session:
        # that is the typed @handle's route alone. continue=True: the message is for this thread's running chat, and that
        # chat owns it, @words included (text, never a route); if that chat ended it is refused, never restarted
        try:
            return _ask_installed(agent_for(body['agent']), prompt, task, on_delta, on_step, cancelled,
                                  resume_only=body.get('continue') is True)
        except Exception:
            if task is not None and body.get('fresh') is True and body.get('continue') is not True:
                _archive_if_empty(task)   # a refused start leaves no empty session behind; only one made for this start
            raise
    if handles:
        return _route_to_agents(prompt, handles, body.get('reply_to') or None, task=task, on_delta=on_delta, on_step=on_step,
                                cancelled=cancelled)
    if body.get('agent', 'BABOOM') == 'BABOOM':
        # BABOOM answers or says why it cannot (which brain, what failed); it never falls through to another model
        try:
            result = _ask_baboom(prompt, task_context)
        except Exception:
            if task is not None and body.get('fresh') is True:
                _archive_if_empty(task)   # like a refused agent start: no empty session made for this start is left behind
            raise
    else:
        result = composer_chat(body, on_delta=on_delta)
    try:
        from .workshop_live import record_answer
        record_answer(prompt, result['answer'], result['model'], task=task)
    except Exception as error:  # noqa: BLE001 - the answer stands even if history is busy
        result['history_error'] = str(error)
    return result


def _archive_if_empty(task):
    """A session made for a chat start that was refused (the composer says so: fresh=True), with nothing in its thread,
    leaves the active list. An existing session is never archived by a failed start, and neither is any session whose
    canvas holds a node of its own (the fixed nodes every canvas has do not count), whatever flags the request carried."""
    from .workshop_mailbox import application_history
    from .session_files import read_document
    from . import workshop_tasks
    with application_history() as history:
        row = next((r for r in workshop_tasks.column(history) if r['id'] == task), None)
        if row is None or row['agentLog'] or row['fileMessages'] or row.get('messages'):
            return
        try:
            nodes = read_document(row['sessionPath'])['nodes'] if row.get('sessionPath') else []
        except (OSError, ValueError):
            return   # a canvas that cannot be read is kept
        if not any(not node.get('fixed') for node in nodes):
            workshop_tasks.archive(history, task)


def _route_to_agents(prompt, handles, reply_to=None, task=None, on_delta=lambda text: None, on_step=lambda step: None,
                     cancelled=lambda: False):
    """@mentions: one Workshop message from Ahmed, pushed live to joined agents; an installed agent that is not
    running is started over ACP for this thread and its answer streams back. A profiling row per recipient."""
    from .acp_client import agent_for
    from .workshop_live import live_agents
    live = {a['handle'] for a in live_agents()}
    starting = [h for h in handles if h not in live and h != 'everyone' and agent_for(h)]
    rest = [h for h in handles if h not in starting]
    answers = [_ask_installed(agent_for(h), prompt, task, on_delta, on_step, cancelled) for h in starting]
    if rest and (not answers or any(h in live or h == 'everyone' for h in rest)):
        answers.append(_inject(prompt, rest, reply_to, task))
    elif rest:
        answers.append({'answer': '\n'.join('✗ @%s · no joined agent with this name' % h for h in rest), 'steps': []})
    if len(answers) == 1:
        return answers[0]
    return {**answers[0], 'answer': '\n\n'.join(a['answer'] for a in answers),
            'steps': [s for a in answers for s in a.get('steps') or []]}


def _ask_installed(agent, prompt, task, on_delta, on_step, cancelled=lambda: False, resume_only=False):
    """One message to an installed agent over the one ACP client; the settled reply is recorded once in the thread."""
    import uuid
    from . import acp_client
    from .model_router import request_profiles
    from .workshop_live import record_answer
    started, name = time.monotonic(), acp_client.label(agent)
    record = {'id': str(uuid.uuid4()), 'ts': time.time(), 'agent': name, 'model': 'agent session',
              'provider': 'acp:' + agent, 'tokens': None, 'ms': 0, 'outcome': 'refused'}
    on_step({'who': name})   # the live row names who is answering before the first word
    # One state row under the user's line (R&D thread study): starting, then answering; after quiet_seconds with
    # no word it says so. It is said from the asking thread's own poll, and the agent is never stopped for it.
    state, phase = {'id': 'agent-state', 'tool': name, 'status': 'starting…'}, ['starting']
    on_step(dict(state))
    halted = _SERVER.is_halted if _SERVER is not None else (lambda: False)

    def stopped():
        if phase[0] == 'starting' and time.monotonic() - started > acp_client.ACP_NODE['params']['quiet_seconds']:
            phase[0] = 'quiet'
            on_step({**state, 'status': 'not responding'})
        return halted()

    def delta(text):
        if phase[0] != 'answering':
            phase[0] = 'answering'
            on_step({**state, 'status': 'answering'})
        on_delta(text)

    def agent_step(step):   # any step from the agent is life: it is working, so it is never "not responding"
        if phase[0] in ('starting', 'quiet'):
            phase[0] = 'working'
            on_step({**state, 'status': 'working…'})
        on_step(step)
    try:
        reply = acp_client.ask(agent, prompt, task=task, on_delta=delta, on_step=agent_step, stopped=stopped,
                               cancelled=cancelled, resume_only=resume_only)
        record['outcome'] = 'answered'
    finally:
        record['ms'] = int((time.monotonic() - started) * 1000)
        request_profiles(record)
    # The settled message carries its steps as lines, the same shape as a BABOOM answer (_ask_baboom).
    steps = ''.join('\n• %s: %s' % (s.get('tool'), s.get('status')) for s in reply['steps'])
    result = {'ok': True, 'answer': reply['text'] + steps, 'text': reply['text'], 'provider': name, 'model': 'ACP',
              'request_id': record['id'], 'applied': [], 'steps': reply['steps'], 'ms': record['ms']}
    try:
        record_answer(prompt, result['answer'], name, task=task, to=name)
    except Exception as error:  # noqa: BLE001 - the answer stands even if history is busy
        result['history_error'] = str(error)
    return result


def _inject(prompt, handles, reply_to=None, task=None):
    """Joined agents: one Workshop message from Ahmed, pushed live (direct injection, as before)."""
    import uuid
    from .model_router import request_profiles
    from .workshop_live import send_as_founder
    started = time.monotonic()
    sent = send_as_founder(prompt, handles, reply_to=reply_to, task=task)
    for row in sent['deliveries']:
        request_profiles({'id': str(uuid.uuid4()), 'ts': time.time(), 'agent': str(row.get('agent')), 'model': 'agent session',
                          'provider': 'workshop:' + str(row.get('channel')), 'tokens': None, 'ms': row.get('ms') or 0,
                          'outcome': row['state'] if row['state'] == 'delivered' else 'failed: ' + str(row.get('reason'))[:80]})
    lines = ['%s %s%s' % ('✓' if r['state'] == 'delivered' else '✗', r.get('agent'),
                          (' · %d ms' % r['ms']) if r['state'] == 'delivered' else ' · ' + str(r.get('reason')))
             for r in sent['deliveries']] + ['✗ @%s · no joined agent with this name' % h for h in sent['unknown']]
    return {'ok': True, 'answer': '\n'.join(lines), 'provider': 'Workshop', 'model': 'live injection',
            'request_id': sent['message_id'], 'applied': [], 'deliveries': sent['deliveries'],
            'ms': int((time.monotonic() - started) * 1000)}


# ---------------------------------------------------------------- routes --
def _action(req, default=None):
    body = req.body if isinstance(req.body, dict) else {}
    return body.get('action', default), body


def record_edit_state(s, body):
    """One Studio view's report: does it hold an unsaved edit, a failed save or an unresolved Keep/Discard?

    Kept per view and file, so one view's clean report never clears another view's draft. Each view numbers
    its reports; an older number than the last one seen is refused, so a late clean report cannot undo a
    newer dirty one. busy_reason holds every automatic update restart while any entry is dirty.
    """
    view, path, seq = body.get('view'), body.get('file') or '', body.get('seq')
    if type(view) is not str or not view or type(path) is not str or type(seq) is not int or isinstance(seq, bool):
        raise Refused('An edit report needs its view, file and sequence number.', 400)
    lock = s.__dict__.setdefault('_edit_lock', threading.Lock())
    with lock:
        seen = s.__dict__.setdefault('_edit_seq', {})
        dirty = s.__dict__.setdefault('_unsaved_views', set())
        if seq <= seen.get(view, -1):
            return {'ok': True, 'accepted': False, 'reason': 'stale report', 'unsaved': bool(dirty)}
        seen[view] = seq
        retired = body.get('retire')
        if type(retired) is str and retired and retired != view:
            # The same browser tab reloaded: its previous page is gone and this page now speaks for it
            # (a recovered draft is reported dirty by this page itself). Never a silent drop of a live page.
            for stale in [entry for entry in dirty if entry[0] == retired]:
                dirty.discard(stale)
            seen[retired] = float('inf')  # nothing late from the old page can re-add an entry
        key = (view, path)
        if body.get('unsaved') is True:
            dirty.add(key)
        else:
            dirty.discard(key)
        resolves = body.get('resolves')
        if type(resolves) is str and resolves and resolves != view and body.get('resolved') in ('keep', 'discard'):
            # A later view durably recovered and kept (or explicitly discarded) THAT page's exact draft. Only this
            # releases a closed page's hold: a clean save of the same file elsewhere may carry different edits.
            dirty.discard((resolves, path))
        return {'ok': True, 'accepted': True, 'unsaved': bool(dirty)}


def r_session_files(s, req):
    from .canvas_documents import CanvasSaveConflict
    from .session_files import SessionFiles
    from .enforce import guard_effect
    action = (req.body or {}).get('action')
    if action == 'edit_state':
        return record_edit_state(s, req.body or {})
    if s.is_halted():
        raise Refused('Stopped by you. Press Resume to continue.', 403)
    canvas_job = action in ('run', 'solve')
    if canvas_job:
        s._canvas_jobs = getattr(s, '_canvas_jobs', 0) + 1
    try:
        result = SessionFiles().dispatch(req.body, invoke=guard_effect, picker=s.native_file_picker,
                                         save_picker=s.native_save_file_picker, stopped=s.is_halted)
    except CanvasSaveConflict as conflict:
        raise Refused(str(conflict), 400, code='canvas_save_conflict') from conflict
    finally:
        if canvas_job:
            s._canvas_jobs -= 1
    if action in ('save', 'autosave', 'open') and getattr(s, 'triggers', None) is not None:
        threading.Thread(target=s.triggers.refresh, name='archhub-triggers', daemon=True).start()
    return result


def r_commands(s, req):
    from .command_registry import payload
    return payload()


def r_documentation(s, req):
    from .site_export import project_documentation
    import re
    root = Path(__file__).resolve().parents[1]
    source = root.parent / '04.DOCS' / 'SPEC.md' if root.name == '01.APP' else root / 'docs' / 'SPEC.md'
    text = source.read_text(encoding='utf-8').split('## 2. Terms', 1)[1].split('\n## ', 1)[0]
    glossary = [{'term': term, 'definition': ' '.join(definition.split())}
                for term, definition in re.findall(r'^- \*\*([^*]+):\*\* (.*?)(?=\n- \*\*|\Z)', text, re.M | re.S)]
    return {'ok': True, **project_documentation(), 'glossary': glossary}


def r_router_settings(s, req):
    from .settings_owner import SettingsOwner
    owner = SettingsOwner(None, dependencies=object())
    if req.method == 'GET' or not req.body:
        return {'ok': True, **owner.routerSettings(refresh_catalogue=req.query.get('refresh_catalogue') == ['1']),
                'live_agents': s._live_agents.get() or {'processes': [], 'complete': False}}
    return {'ok': True, **owner.setRouterSettings(req.body)}


def r_chat_agents(_s, _req):
    """Which chat agents the composer's picker can START (acp_client.chat_agents): looked up on PATH now, nothing started."""
    from .acp_client import chat_agents
    return {'ok': True, 'agents': chat_agents()}


# The System graph is logic only: the owners of this server, wired by what feeds what.
SYSTEM_OWNERS = (
    ('owner:canvas', 'Canvas', 'Session files', 'Documents/ArchHub/*.archhub (Settings: sessions folder)', ['workshop']),
    ('owner:library', 'Node library', 'Session files', 'library_engines + pipeline_engines', ['canvas']),
    ('owner:workshop', 'Workshop', 'Workshop', 'workshop/messages.sqlite3', ['router']),
    ('owner:workshop', 'Workshop', 'Workshop', 'workshop/ (native injection)', ['workshop']),
    ('owner:router', 'Router', 'Router', 'settings/router.json', ['profiling']),
    ('owner:profiling', 'Profiling', 'Router', 'settings/router.sqlite', []),
    ('owner:brokers', 'Brokers', 'Hosts', 'broker sessions/*.json + BridgeAuth', ['canvas']),
    ('owner:settings', 'Settings', 'Settings', 'settings/*.json', ['router']),
    ('owner:secrets', 'Secrets', 'Settings', 'Windows Credential Manager (by reference)', ['router']),
    ('owner:social', 'Social media', 'Social', 'settings/social.json', ['workshop']),
    ('owner:community', 'Community', 'Social', 'settings/community.json', []),
)


def r_canvas(s, req):
    ids = {owner[0].split(':')[1]: owner[0] for owner in SYSTEM_OWNERS}
    nodes = [{'id': root, 'label': label, 'kind': 'Owner', 'category': group, 'group': group, 'application': True,
              'x': 80 + index % 3 * 300, 'y': 80 + index // 3 * 200,
              'params': [{'label': 'stored in', 'value': store, 'editable': False}],
              'ports': [{'id': 'in', 'name': 'in', 'side': 'target'}, {'id': 'out', 'name': 'out', 'side': 'source'}]}
             for index, (root, label, group, store, _feeds) in enumerate(SYSTEM_OWNERS)]
    wires = [{'id': root + '->' + ids[target], 'source': root, 'target': ids[target],
              'source_interface': 'out', 'target_interface': 'in'}
             for root, _label, _group, _store, feeds in SYSTEM_OWNERS for target in feeds]
    from .community_owner import bindings
    return {'ok': True, 'revision': 0, 'root': 'app:system', 'canvas_root': 'app:system', 'graph_id': 'app:system',
            'scope': {'current': 'app:system', 'current_label': 'System graph'}, 'nodes': nodes, 'wires': wires,
            'catalog': [], 'interaction_projection': {'bindings': bindings()}, 'viewport': {'x': 0, 'y': 0, 'zoom': 1}}


def r_canvas_op(s, req):
    body = req.body or {}
    op, args = body.get('op'), body.get('args') or []
    if op == 'project_schedules':
        return {'ok': True, 'result': _schedules()}
    if op == 'automation_pause':
        service = getattr(s, 'triggers', None)
        if service is None:
            raise Refused('Schedules are available while the app is open.')
        if args:
            if s.is_halted():
                raise Refused('Stopped by you. Press Resume to continue.', 403)
            if type(args) is not list or len(args) != 1:
                raise Refused('Choose Pause all or Resume all.')
            paused = service.set_paused(args[0])
            return {'ok': True, 'result': {'paused': paused, 'schedules': _schedules()}}
        return {'ok': True, 'result': {'paused': service.paused}}
    if op in ('add_schedule', 'set_schedule_enabled', 'set_schedule_time', 'remove_schedule'):
        if s.is_halted():
            raise Refused('Stopped by you. Press Resume to continue.', 403)
        if getattr(s, 'triggers', None) is None:
            raise Refused('Schedules are available while the app is open.')
        return {'ok': True, 'result': s.triggers.change_schedule(op, args)}
    from .community_owner import CommunityOwner
    if op in CommunityOwner.PUBLIC:
        return {'ok': True, 'result': CommunityOwner(s.files['community']).dispatch(op, list(args))}
    if op == 'provider_sign_in':
        from .model_router import ModelRouteRefused, sign_in_launch
        try:
            return {'ok': True, 'result': sign_in_launch(str(args[0] if args else ''))}
        except (ModelRouteRefused, OSError) as refused:
            raise Refused(str(refused))
    if op in _MCP_OPS:
        if op not in ('mcp_servers',) and s.is_halted():
            raise Refused('Stopped by you. Press Resume to continue.', 403)
        return {'ok': True, 'result': _mcp_op(op, list(args))}
    reads = {'list_skills': [],
             'project_state': {'versions': [], 'modelReview': {'operation': '', 'results': [], 'issues': []}, 'dismissed': []}}
    if op in reads:
        return {'ok': True, 'result': reads[op]}
    if op == 'library_ports':
        from .session_files import catalogue
        return {'ok': True, 'result': catalogue()}
    if op == 'add_interface_element':
        if s.is_halted():
            raise Refused('Stopped by you. Press Resume to continue.', 403)
        from uuid import uuid4
        from . import canvas_documents
        from . import session_files
        kind = args[0] if args else None
        if kind not in ('Button', 'Card', 'Text'):
            raise Refused('Choose Button, Card or Text.')
        interface_path = session_files.SessionFiles().current_path()
        if not interface_path:
            raise Refused('Open a workflow before adding an interface element.')
        if len(args) > 1 and session_files.local_path(args[1]) != session_files.local_path(interface_path):
            raise Refused('The open workflow changed. Reopen it before adding an element.', 409)
        item = next(row for row in session_files.catalogue() if row['id'] == 'ui_element')
        identity = str(uuid4())

        def place(document):
            document['nodes'].append({
                'id': identity, 'type': item['engine'], 'item': item['id'], 'title': kind,
                'params': {**item['params'], 'element': kind, 'label': kind, 'value': kind},
                'paramDefs': item['paramDefs'], 'position': {'x': 80, 'y': 100},
            })
            return [identity]

        canvas_documents.edit(interface_path, 'Studio', 'Add interface element', place, solve_changed=False)
        return {'ok': True, 'result': {'id': identity}}
    if op == 'fork_node':
        from .session_files import SessionFiles, read_document
        from .canvas_documents import edit
        from .agent_work import fork
        path = SessionFiles().current_path()
        if not path:
            raise Refused('Open a task workflow before forking.')
        changed = []
        def change(document):
            changed.extend(fork(document, args[0]))
            return []
        edit(path, 'Studio', 'Fork from here', change, solve_changed=False)
        return {'ok': True, 'result': {'id': changed[0] if changed else '', 'ids': changed, 'document': read_document(path)}}
    files = s.files['project-files']
    if op == 'project_files':
        return {'ok': True, 'result': files.read()['files']}
    if op == 'add_file':
        path, kind = str(args[0]), str(args[1] if len(args) > 1 else 'Project file')
        if not Path(path).is_absolute():
            raise Refused('Choose an absolute local file.')
        row = {'id': 'file:' + secrets.token_hex(8), 'name': Path(path).name, 'path': path, 'kind': kind}
        held = files.read()
        held['files'] = [r for r in held['files'] if r['path'] != path] + [row]
        files.write(held)
        return {'ok': True, 'result': row}
    return not_available('Canvas operation "%s"' % op)


def r_node_library(s, req):
    if req.query.get('templates') == ['1']:
        # Starters (Book ch.12) plus every saved skill. A skill is {id:'skill:<id>', title, path}.
        from .starters import listing
        from .session_files import skill_template_rows
        return {'ok': True, 'templates': [*listing(s._hosts.get() or []), *skill_template_rows()]}
    from .library_engines import engine_categories, library_catalogue
    groups = library_catalogue()
    return {'ok': True, 'groups': groups, 'categories': engine_categories(groups), 'wire_parameters': []}


def r_graph_only(what):
    return lambda s, req: not_available(what)


def r_hosts(s, req):
    rows = s._hosts.get()
    if rows is None:
        return {'ok': True, 'hosts': [], 'connectors': [], 'probing': True}
    disabled = set(s.files['hosts'].read()['disabled'])
    # Plate 083: one plain status per program; the probe's own wording stays in 'reason' for agents.
    rows = [{**row, 'enabled': row.get('id') not in disabled, 'enabled_state': 'confirmed',
             'detail': _plain_status(row.get('state')), 'reason': row.get('detail', '')} for row in rows]
    try:
        from .connector_operation_evidence import operation_rows
        operations = operation_rows(rows)
    except Exception:  # noqa: BLE001
        operations = []
    return {'ok': True, 'connectors': rows, 'operations': operations,
            'hosts': [{'id': r['id'], 'name': r['name'], 'port': '', 'state': r['state'], 'file': r.get('detail', '')}
                      for r in rows if r.get('drive') and r.get('state') in ('connected', 'listening')]}


# -- Custom MCP servers: owner custom_mcp, file settings/mcp_servers.json, secrets in Credential Manager --
_MCP_OPS = ('mcp_servers', 'add_mcp_server', 'remove_mcp_server', 'set_mcp_server_enabled',
            'discover_mcp_tools', 'reconnect_mcp', 'prepare_mcp_tool', 'import_mcp_tool', 'sign_in_mcp_server')
_MCP_SEEN = {}  # id -> (status, tools) from the last Discover; a view cache, the file stays the truth


def _mcp_rows():
    from . import custom_mcp
    rows = []
    for row in custom_mcp.servers():
        status, tools = _MCP_SEEN.get(row['id'], ('Not checked', []))
        rows.append({'id': row['id'], 'name': row['name'], 'transport': row['transport'],
                     'where': row.get('url') or ' '.join([row.get('command', ''), *row.get('args', [])]),
                     'enabled': row.get('enabled', True), 'secrets': len(row.get('env', [])) + len(row.get('headers', [])),
                     'signedIn': row.get('auth') == 'oauth',
                     'status': status if row.get('enabled', True) else 'Off', 'tools': tools})
    return rows


def _mcp_op(op, args):
    from . import custom_mcp
    try:
        if op == 'add_mcp_server':
            added = custom_mcp.add(args[0] if args else '')
            checks = {}
            for row in added:
                try:  # saved either way; the row and this answer say Sign in needed or why it failed
                    _mcp_discover(row['id'])
                    checks[row['id']] = 'ok'
                except custom_mcp.McpRefused as failed:
                    checks[row['id']] = str(failed)
            return {'added': [row['id'] for row in added], 'checks': checks, 'servers': _mcp_rows()}
        if op == 'remove_mcp_server':
            custom_mcp.remove(str(args[0] if args else ''))
            _MCP_SEEN.pop(str(args[0] if args else ''), None)
        elif op == 'set_mcp_server_enabled':
            custom_mcp.set_enabled(str(args[0]), bool(args[1]) if len(args) > 1 else True)
        elif op in ('discover_mcp_tools', 'reconnect_mcp'):
            if len(args) > 1 and args[1] not in ('Tools', None, ''):
                raise custom_mcp.McpRefused('Only tools become nodes. Resources and prompts are not imported yet.')
            _mcp_discover(str(args[0] if args else ''))
        elif op in ('prepare_mcp_tool', 'import_mcp_tool'):
            return _mcp_import(str(args[0]), str(args[1]), prepare=op == 'prepare_mcp_tool')
        elif op == 'sign_in_mcp_server':
            server_id = str(args[0] if args else '')
            _MCP_SEEN[server_id] = ('Signing in… finish it in your browser', [])
            threading.Thread(target=_mcp_sign_in, args=(server_id,), name='archhub-mcp-sign-in', daemon=True).start()
    except (custom_mcp.McpRefused, IndexError) as refused:
        raise Refused(str(refused) or 'Name the tool server.')
    return _mcp_rows()


def _mcp_discover(server_id):
    from . import custom_mcp
    row = next((r for r in custom_mcp.servers() if r['id'] == server_id), None)
    if row is None:
        raise custom_mcp.McpRefused('No such tool server.')
    try:
        tools = custom_mcp.list_tools(row)
        _MCP_SEEN[server_id] = ('%d tools' % len(tools), [{'id': t['name'], 'name': t['title'] or t['name'],
                                                            'inputs': t['inputs']} for t in tools])
    except custom_mcp.McpRefused as failed:
        needs = custom_mcp.SIGN_IN_NEEDED in str(failed)
        _MCP_SEEN[server_id] = ('Sign in needed' if needs else 'Connection failed', [])
        raise custom_mcp.McpRefused(str(failed) if needs else 'Connection failed: %s' % failed)


def _mcp_sign_in(server_id):
    """Browser sign-in off the request path (it waits for the person); the status row tells the outcome."""
    from . import custom_mcp
    try:
        custom_mcp.sign_in(server_id)
        _mcp_discover(server_id)
    except custom_mcp.McpRefused as failed:
        if _MCP_SEEN.get(server_id, ('',))[0].startswith('Signing in'):
            _MCP_SEEN[server_id] = ('Sign-in failed: %s' % failed, [])


def _mcp_import(server_id, tool, *, prepare=False):
    """Build the connector node. Studio adds it through its own open document's editor."""
    from uuid import uuid4
    from . import canvas_documents, session_files
    from .custom_mcp import PREFIX
    item = next(row for row in session_files.catalogue() if row['id'] == 'connector_call')
    identity = str(uuid4())

    node = {
        'id': identity, 'type': item['engine'], 'item': item['id'], 'title': tool,
        'params': {**item['params'], 'connector': PREFIX + server_id, 'action': tool},
        'paramDefs': item.get('paramDefs', []), 'position': {'x': 80, 'y': 100},
    }
    if prepare:
        return {'node': node}
    path = session_files.SessionFiles().current_path()
    if not path:
        raise Refused('Open a canvas before adding a tool.')

    def place(document):
        document['nodes'].append(node)
        return [identity]

    canvas_documents.edit(path, 'Studio', 'Add ' + tool, place, solve_changed=False)
    return {'id': identity}


def _plain_status(state):
    if state in ('connected', 'listening'):
        return 'Connected'
    if state in ('needs-sign-in', 'needs-key'):
        return 'Sign in to connect'
    if state == 'off':
        return 'No connector'
    if state == 'absent':
        return 'Not installed'
    return 'Installed · not running'


def r_providers(s, req):
    if req.path.endswith('/models'):
        from .settings_owner import read_router_settings
        result = s._models.get() or {'ok': True, 'groups': [], 'count': 0}
        route = read_router_settings()['default_model']  # same pair application_server._default_agent_model answers
        return {**result, 'selected_route': route, 'default_route': route, 'default_source': ROUTER_FILE,
                'refreshing': s._models.running}
    return {'ok': True, 'providers': s._providers.get() or [], 'refreshing': s._providers.running}


# -- Workshop: the room is workshop/messages.sqlite3; delivery is Workshop --
def _declarations():
    from .workshop_mailbox import application_history, read_declarations
    with application_history(read_only=True) as history:
        return read_declarations(history._db, include_archived=True)


# One Studio poll asks listTasks and then listNotifications, which needs the same column: built once, shared for
# COLUMN_SHARE_S. Any Workshop write through this server drops it; another process's write shows on the next poll.
COLUMN_SHARE_S = 2.0
_COLUMN = {}
_COLUMN_LOCK = threading.Lock()
_COLUMN_GENERATION = [0]  # moves on every drop: a column built across a write is not kept
# The Workshop owner's kept read-only watcher (F419) tells whether any connection committed since the column was
# built. Its sqlite connection belongs to the thread that opened it, so one worker thread owns it and answers reads.
_STORE_VERSION_WORKER = None
_STORE_WATCH = []
_STORE_VERSION_CLOSED = [False]  # set by server close: a late poll builds no new worker or watcher


def _close_store_version():
    """Close the kept store watcher on its own worker thread, then stop the worker (app close, test teardown)."""
    global _STORE_VERSION_WORKER
    with _COLUMN_LOCK:
        _STORE_VERSION_CLOSED[0] = True
        worker, _STORE_VERSION_WORKER = _STORE_VERSION_WORKER, None
        _COLUMN.clear()
    if worker is None:
        return
    from .library_engines import LIBRARY_ITEM_ENGINES

    def close():
        while _STORE_WATCH:
            _STORE_WATCH.pop()[1].close()
    try:
        worker.submit(close).result(timeout=LIBRARY_ITEM_ENGINES['tool_workshop']['params']['worker_join_ms'] / 1000)
    except Exception as stuck:  # noqa: BLE001 - closing the app goes on; the worker is still stopped below
        logging.getLogger(__name__).warning('Workshop store watcher did not close: %s', stuck)
    worker.shutdown(wait=True)


def _store_version():
    """The store's commit counter (PRAGMA data_version on the kept watcher); None when it cannot be read."""
    global _STORE_VERSION_WORKER
    from concurrent.futures import ThreadPoolExecutor
    from .library_engines import LIBRARY_ITEM_ENGINES
    # The Workshop node's own join budget: a store read slower than that leaves the column unshared, never blocked.
    budget = LIBRARY_ITEM_ENGINES['tool_workshop']['params']['worker_join_ms'] / 1000

    def read():
        from .workshop_mailbox import profile_database, store_watch
        store = str(profile_database())
        if _STORE_WATCH and _STORE_WATCH[0][0] != store:  # another store (profile switch, a second server): reopen
            _STORE_WATCH.pop()[1].close()
        if not _STORE_WATCH:
            _STORE_WATCH.append((store, store_watch(budget)))
        try:
            return (store, _STORE_WATCH[0][1].version())  # a column of another store never matches
        except Exception:  # noqa: BLE001 - a broken watcher is reopened on the next read
            _STORE_WATCH.pop()[1].close()
            raise

    with _COLUMN_LOCK:
        if _STORE_VERSION_CLOSED[0]:
            return None  # closing or closed: the column is built fresh and not shared
        if _STORE_VERSION_WORKER is None:
            _STORE_VERSION_WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix='archhub-store-version')
        worker = _STORE_VERSION_WORKER
    try:
        return worker.submit(read).result(timeout=budget)
    except Exception as unreadable:  # noqa: BLE001 - unknown version: the column is built fresh
        logging.getLogger(__name__).debug('Workshop store version unreadable: %s', unreadable)
        return None
_SESSION_READ_ACTIONS = frozenset(('head', 'read', 'catalogue', 'initial', 'validate', 'agent-history',  # session-files
                                   'list', 'get', 'links', 'runs', 'setting'))  # session-model
_WORKSHOP_READ_FUNCTIONS = frozenset(('listTasks', 'listWorkshopMessages', 'listApprovals', 'listNotifications',
                                      'listLiveAgents', 'listAgentsWorking', 'readWatcher', 'readDesktop', 'readHostSkills'))


def _list_tasks(include_archived=False):
    """The Work column: the Workshop tasks table (claimed atomically by agents with task.claim)."""
    import copy
    from .workshop_mailbox import application_history
    from .workshop_tasks import column
    key, version = include_archived is True, _store_version()
    with _COLUMN_LOCK:
        held = _COLUMN.get(key)
        # Shared only while no connection committed since it was built, and never longer than the 2 s backstop.
        if held and version is not None and held[2] == version and time.monotonic() - held[0] < COLUMN_SHARE_S:
            return copy.deepcopy(held[1])
        generation = _COLUMN_GENERATION[0]
    with application_history() as history:
        rows = column(history, include_archived=key)
    with _COLUMN_LOCK:
        if generation == _COLUMN_GENERATION[0] and version is not None:
            _COLUMN[key] = (time.monotonic(), copy.deepcopy(rows), version)
    return rows


def _drop_column():
    with _COLUMN_LOCK:
        _COLUMN.clear()
        _COLUMN_GENERATION[0] += 1


def _open_task_graph(task, path=None):
    """Open the task's own session file. The Workshop task row holds the path; the file holds the work."""
    from .workshop_mailbox import application_history
    from .workshop_tasks import open_session
    try:
        with application_history() as history:
            return open_session(history, task, path)
    except ValueError as refused:
        return {'ok': False, 'error': str(refused)}


def _rename_task(task, title):
    """The founder renames the selected task. The row title is the record."""
    from .workshop_mailbox import application_history
    from .workshop_tasks import rename
    try:
        with application_history() as history:
            return rename(history, task, title)
    except ValueError as refused:
        return {'ok': False, 'error': str(refused)}


def _create_task(s, title, agent='', workspace='', parent=''):
    """The studio's new task: one Workshop row and the .archhub file that is its session."""
    from .workshop_mailbox import application_history
    from .workshop_tasks import create_session
    try:
        with application_history() as history:
            zoom = s.files['settings'].read().get('appearanceDefaultZoom', 100)
            return create_session(history, title, zoom=zoom / 100, agent=agent, workspace=workspace, parent=parent)
    except ValueError as refused:
        return {'ok': False, 'error': str(refused)}


def _set_task_session(task, values):
    """Parameters, plan, agents and progress land in that task's file."""
    from .workshop_mailbox import application_history
    from .workshop_tasks import update_session
    try:
        with application_history() as history:
            return update_session(history, task, values)
    except ValueError as refused:
        return {'ok': False, 'error': str(refused)}


def _pin_task_message(task, message, pinned):
    from .workshop_mailbox import application_history
    from .workshop_tasks import pin_message
    with application_history() as history:
        return pin_message(history, task, message, pinned)


def _attach_task_notes(task, text):
    from .workshop_mailbox import application_history, attach_meeting_notes
    with application_history() as history:
        return attach_meeting_notes(history, task, text)


def _checkpoint_task(task, checkpoint=None, label=None, *, restore=False):
    from .workshop_mailbox import application_history
    from .workshop_tasks import checkpoint_session
    try:
        if restore and (not isinstance(checkpoint, str) or not checkpoint):
            raise ValueError('Choose a checkpoint to restore')
        with application_history() as history:
            return checkpoint_session(history, task, checkpoint, label)
    except ValueError as refused:
        return {'ok': False, 'error': str(refused)}


def _set_task_status(task, status):
    from .workshop_mailbox import application_history
    from .workshop_tasks import set_status
    try:
        with application_history() as history:
            if not set_status(history, str(task), status):
                return {'ok': False, 'error': 'No such Workshop task'}
    except ValueError as refused:
        return {'ok': False, 'error': str(refused)}
    return next(row for row in _list_tasks() if row['id'] == task)


def _archive_task(task):
    """Delete task in the Canvas menu: the task owner's archive. It leaves the active list; its session file stays readable."""
    from .workshop_mailbox import application_history
    from .workshop_tasks import archive, TaskNotFound
    try:
        with application_history() as history:
            if not archive(history, str(task)):
                return {'ok': False, 'error': 'The task changed while archiving it. Retry.'}
    except TaskNotFound:
        return {'ok': False, 'error': 'No such Workshop task'}
    return {'ok': True, 'task': str(task)}


def _list_agents():
    """One named row per agent app (Book Ch.9 / F32), filled with live process and declaration state."""
    from .agent_runtime_registry import AGENT_APPS, RUNTIMES
    observed = _SERVER._live_agents.get() or {'processes': [], 'complete': False}
    declared = [row for row in _declarations() if row.get('current')]
    live = {}
    for process in observed['processes']:
        runtime = process['runtime']
        row = live.get(runtime)
        if row is None:
            mine = [r for r in declared if (r.get('runtime') or r.get('app')) == runtime]
            busy = [r for r in mine if r.get('status') == 'working']
            if busy:
                task = busy[0].get('task') or 'Working — task not reported'
            else:
                task = 'Idle'
            row = live[runtime] = {
                'id': runtime, 'runtime': runtime,
                'name': dict(AGENT_APPS).get(runtime) or RUNTIMES.get(runtime, {}).get('label', runtime),
                'session_count': 0,
                'presence': 'working' if busy else 'idle',
                'status_text': 'Working' if busy else 'Idle',
                'task': task,
                'model': 'Model not reported',
                'sessions': [{'root': r['root'], 'task': r.get('task'), 'status': r.get('status'),
                              'request_id': r.get('request_id', r['root'])} for r in mine],
                'observation_complete': observed['complete'], 'evidence': 'process',
            }
        row['session_count'] += 1
    rows = []
    for app_id, label in AGENT_APPS:
        row = live.pop(app_id, None)
        if row is None:
            mine = [r for r in declared if (r.get('runtime') or r.get('app')) == app_id]
            busy = [r for r in mine if r.get('status') == 'working']
            if busy:
                presence, status_text, task = 'working', 'Working', busy[0].get('task') or 'Working — task not reported'
            elif mine:
                presence, status_text, task = 'idle', 'Idle', 'Idle'
            else:
                presence, status_text, task = 'stopped', 'Not running', 'Connect'
            row = {
                'id': app_id, 'runtime': app_id, 'name': label,
                'session_count': len(mine), 'presence': presence, 'status_text': status_text,
                'task': task, 'model': 'Model not reported',
                'sessions': [{'root': r['root'], 'task': r.get('task'), 'status': r.get('status'),
                              'request_id': r.get('request_id', r['root'])} for r in mine],
                'observation_complete': observed['complete'], 'evidence': 'roster',
            }
        else:
            row['name'] = label
        rows.append(row)
    # Observed runtimes outside the Settings roster stay available to Workshop views.
    rows.extend(live.values())
    return rows


def _list_messages(before=None):
    from .workshop_api import WorkshopAPI
    from .workshop_live import deliveries, FOUNDER
    from .workshop_mailbox import application_history
    api = WorkshopAPI(None, SimpleNamespace(subject_root='app:founder'), 'app:workshop', 'app:workshop',
                      guard=lambda: None, request_id='', route=WORKSHOP_PATH)
    page = api.listWorkshopMessages(before)
    with application_history() as history:
        live = deliveries(history, [m['id'] for m in page['messages']])
        from .workshop_mailbox import read_declarations
        names = {row['agent']: row.get('display_name') or row['agent'] for row in read_declarations(history._db, include_archived=True)}
    from .baboom_nograph import own_session
    baboom = own_session()
    for message in page['messages']:
        message['live'] = live.get(message['id'], [])
        # Display only: the stored "To <session label>:" header stays the routing address; the room shows who received it.
        header, newline, body = message['text'].partition('\n')
        if newline and header.startswith('To ') and header.endswith(':'):
            labels = [names.get(label.strip(), 'Everyone' if label.strip() == '*' else label.strip()) for label in header[3:-1].split(',')]
            message.update(raw=message['text'], to=', '.join(dict.fromkeys(d['agent'] for d in message['live'] if d.get('agent'))) or ', '.join(labels),
                           text=__import__('re').sub(r'^(?:@[\w.-]+\s+)+', '', body))
        # No pending state (founder 2026-10-28): delivery is the per-recipient live rows only.
        message.pop('state', None)
        message['delivery'] = []
        if baboom and message.get('sender_key') == baboom:
            message['who'] = 'BABOOM'
        if message.get('author') == FOUNDER:
            message.update(who=FOUNDER, sender_key='app:founder', viewer_key='app:founder')
    return page


def _schedules():
    from datetime import datetime
    from .canvas_triggers import next_delay, _off
    from .session_files import last_automation_runs, read_document
    service = getattr(_SERVER, 'triggers', None)
    if service is None:
        return []
    armed = _live_triggers(_SERVER)
    labels = {'succeeded': 'Completed', 'waiting-for-approval': 'Waiting for approval',
              'unconfirmed': 'Unconfirmed', 'failed': 'Failed', 'declined': 'Declined'}
    rows = []
    for path in service.workflows():
        try:
            document = read_document(path)
        except (OSError, ValueError):
            continue
        runs = last_automation_runs(path, document['id'])
        for node in document['nodes']:
            kind, node_id, params = node['type'], node['id'], node['params']
            if kind not in ('trigger.schedule', 'trigger.file'):
                continue
            enabled = not _off(params.get('armed', True))
            live = (path, node_id) in armed
            daily = kind == 'trigger.schedule' and params.get('every_seconds') in (None, '', '0', 0)
            delay = next_delay(params) if kind == 'trigger.schedule' else None
            if daily:
                display_time = params.get('daily_at') or '08:00'
            elif delay is not None:
                display_time = f'Every {delay / 60:g} min' if delay % 60 == 0 else f'Every {delay:g} sec'
            else:
                display_time = 'On change in ' + str(params.get('folder'))
            last = runs.get(node_id)
            if last:
                status = labels[last['state']]
                try:
                    status += ' · ' + datetime.fromtimestamp(last.get('end') or last.get('at')).strftime('%H:%M')
                except Exception:  # Only the saved timestamp can be malformed here.
                    status += ' · time unavailable'
                last = {**last, 'status': status}
            rows.append({'id': path + '#' + node_id, 'title': (node.get('title') or kind) + ' · ' + Path(path).stem,
                         'time': display_time, 'daily': daily, 'enabled': enabled, 'kind': kind, 'path': path,
                         'nextInSeconds': round(delay) if live and delay is not None else None,
                         'lastResult': last})
    return rows


def _read_desktop():
    service = getattr(_SERVER, 'triggers', None)
    return {'owner': 'app:desktop', 'program': '', 'stage': 'Watching', 'taskId': None, 'offers': [],
            'schedules': _schedules(), 'automationsPaused': service.paused if service is not None else None}


def _send_to_baboom(description, options=None):
    from .workshop_mailbox import call
    target = (options or {}).get('provider') or 'BABOOM'
    sent = call('send', {'to': str(target), 'text': str(description)}, {})
    return {'id': sent['message_id'], 'title': str(description).splitlines()[0][:120], 'status': 'PLANNED', 'ok': True}


def _host_skills(request_id=''):
    from .host_skill_owner import HostSkillOwner
    return HostSkillOwner(_SERVER.state_dir, request_id)


def _watcher(request_id=''):
    from .watcher_owner import WatcherOwner
    return WatcherOwner(_SERVER.state_dir, request_id)


def _answer_approval(request_id, kind, root, digest, decision):
    from .hook_decision import decide
    if kind in ('ask', 'canvas'):
        return decide({'approval': 'ask', 'id': root, 'digest': digest, 'decision': decision})
    owners = {'hostskills': _host_skills, 'watcher': _watcher}
    if kind not in owners:
        raise ValueError('This approval kind is not served here.')
    return decide({'approval': kind, 'owner': owners[kind](request_id), 'id': root, 'digest': digest,
                   'decision': decision})


def _workshop_item_exists(identity):
    """A Workshop task or message id, answered by the Workshop owner's own file."""
    from .workshop_mailbox import ROOM, application_history
    with application_history() as history:
        db = history._db
        if db.execute("SELECT 1 FROM messages WHERE conversation_id=? AND id=?", (ROOM, identity)).fetchone():
            return True
        tasks = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workshop_tasks'").fetchone()
        return bool(tasks and db.execute("SELECT 1 FROM workshop_tasks WHERE id=?", (identity,)).fetchone())


def _social():
    from .social_surface import SocialSurface
    return SocialSurface(_SERVER.files['social'], task_exists=_workshop_item_exists)


def _list_approvals():
    from .hook_decision import ask_reviews
    return _watcher().reviews() + _host_skills().reviews() + ask_reviews() + _social().reviews()


# Studio action -> owner method; each owner keeps one plain file under settings/.
OWNER_ACTIONS = {
    'importHostSkill': (_host_skills, lambda o, value: o.import_skill(value)),
    'inspectConnectorBundle': (_host_skills, lambda o, upload: o.inspect(upload)),
    'configureConnectorBundle': (_host_skills, lambda o, root, key, value: o.configure(root, key, value)),
    'installConnectorBundle': (_host_skills, lambda o, root: o.request(root, 'install')),
    'setHostSkillEnabled': (_host_skills, lambda o, root, enabled: o.set_enabled(root, enabled)),
    'auditHostSkill': (_host_skills, lambda o, root: o.audit(root)),
    'setWatcherHost': (_watcher, lambda o, host: o.set_host(host)),
    'setWatcherView': (_watcher, lambda o, view: o.set_view(view)),
    'editWall': (_watcher, lambda o, y: o.edit(y)),
    'addDimension': (_watcher, lambda o, values: o.annotate('dimension', values)),
    'addMark': (_watcher, lambda o, values: o.annotate('mark', values)),
    'addComment': (_watcher, lambda o, values: o.annotate('comment', values)),
    'proposeWatcherEdit': (_watcher, lambda o: o.propose()),
    'discardWatcherChanges': (_watcher, lambda o: o.discard()),
    # Every Approve/Deny card goes through the one decision (hook_decision.decide).
    'answerApproval': (str, lambda request_id, kind, root, digest, decision: _answer_approval(request_id, kind, root, digest, decision)),
}


def _list_notifications():
    from .settings_owner import notification_reads
    from hashlib import sha256
    read = notification_reads(settings=_SERVER.files['settings'])
    result = []
    def add(kind, identity, text, task=''):
        key = kind + ':' + sha256(str(identity).encode()).hexdigest()
        result.append({'id': key, 'text': text, 'taskId': task, 'read': key in read})
    for card in _list_approvals():
        if card.get('status') == 'pending':
            add('approval', card['id'], card.get('title') or 'Approval needed', card.get('taskId') or card.get('work') or '')
    for task in _list_tasks():
        for activity in task.get('activity') or []:
            if activity.get('status') == 'Error':
                add('failed', task['id'] + ':' + activity['id'], task['title'] + ': a step failed', task['id'])
        replies = [row for row in task.get('agentLog') or [] if row.get('who') != 'You']
        if replies:
            last = replies[-1]
            add('message', last['id'], task['title'] + ': ' + str(last.get('text') or '')[:200], task['id'])
    return {'notifications': result[-100:]}


def _read_notification(identity):
    from .settings_owner import notification_reads
    if not any(row['id'] == identity for row in _list_notifications()['notifications']):
        raise ValueError('This notification is no longer current.')
    notification_reads(identity, settings=_SERVER.files['settings'])
    return {**_list_notifications(), 'receipt': {'id': identity, 'read': True}}


WORKSHOP_READS = {
    'listTasks': lambda *a: _list_tasks(a[0] if a else False),
    'renameTask': _rename_task,
    'openTaskGraph': _open_task_graph,
    'setTaskSession': _set_task_session,
    'pinTaskMessage': _pin_task_message,
    'attachMeetingNotes': _attach_task_notes,
    'checkpointTask': lambda task, label=None: _checkpoint_task(task, label=label),
    'restoreTaskCheckpoint': lambda task, checkpoint: _checkpoint_task(task, checkpoint, restore=True),
    'setTaskStatus': _set_task_status,
    'archiveTask': _archive_task,
    'listAgentsWorking': lambda *a: _list_agents(),
    'listWorkshopMessages': lambda before=None, *a: (_SERVER._messages.get()
        if before is None else _list_messages(before)),
    'listApprovals': lambda *a: _list_approvals(),
    'listNotifications': _list_notifications,
    'readNotification': _read_notification,
    'readWatcher': lambda *a: _watcher().read(),
    'readDesktop': lambda *a: _read_desktop(),
    'readHostSkills': lambda *a: _host_skills().read(),
    'getAgentSurface': lambda *a: {'learning': {}},
    'getGraphMetadata': lambda *a: {},
    'refreshOfficeAwareness': lambda *a: [],
    'sendToBaboom': _send_to_baboom,
    'listLiveAgents': lambda *a: _SERVER._workshop_agents.get() or [],
}


def r_workshop(s, req):
    if req.method == 'GET':
        return {'ok': True, **s._messages.get(), 'refreshing': s._messages.running}
    action, body = _action(req)
    if action == 'data-api':
        function = body.get('function')
        if function in OWNER_ACTIONS:
            factory, method = OWNER_ACTIONS[function]
            try:
                return {'ok': True, 'result': method(factory(body.get('request_id') or ''), *(body.get('args') or []))}
            except (ValueError, TypeError) as refused:
                return {'ok': True, 'result': {'ok': False, 'error': str(refused)}}
        if function == 'createTask':
            return {'ok': True, 'result': _create_task(s, *(body.get('args') or []))}
        handler = WORKSHOP_READS.get(function)
        if handler is None:
            return {'ok': True, 'result': not_available('Workshop "%s"' % function)}
        return {'ok': True, 'result': handler(*(body.get('args') or []))}
    if action == 'agent-channel':
        from .app_agents import dispatch
        try:
            return dispatch(s.agents_api(), body, guard=lambda: None)
        except RuntimeError as error:
            raise Refused(str(error)) from error
    return not_available('Workshop action "%s"' % action)


def r_workshop_model_approval(s, req):
    if req.method == 'GET':
        return {'ok': True, 'expired': True, 'approved': False, 'input_digest': '', 'revision': 0}
    return not_available('Model delegation approval')


def r_native_agents(s, req):
    return {'ok': True, 'agents': _list_agents()}


# (runtime, native id) -> (time looked, path or None). Finding a transcript walks ~/.codex/sessions (rglob) or
# ~/.claude/projects for every declared agent on every 5 s poll; a found file is kept while it exists, a miss for 60 s.
_TRANSCRIPTS = {}


def _has_transcript(runtime, native_id):
    from .agent_status import transcript_path
    key, now = (runtime, native_id), time.monotonic()
    held = _TRANSCRIPTS.get(key)
    if held and (held[1] is not None and held[1].is_file() or held[1] is None and now - held[0] < 60):
        return held[1] is not None
    found = transcript_path(runtime, native_id)
    _TRANSCRIPTS[key] = (now, found)
    return found is not None


def r_agents_canvas(s, req):
    """A read-only System view of the existing roster, task bindings and Workshop messages."""
    from .workshop_mailbox import application_history, read_declarations, ROOM
    from .workshop_tasks import rows, _declared_id
    from .session_files import read_document
    roster = _list_agents()
    sessions, tasks, wires = [], {}, []
    with application_history(read_only=True) as history:
        declarations = [r for r in read_declarations(history._db) if r.get('current')]
        held = {r['id']: r for r in rows(history, settle=False)}
        for row in declarations:
            task = held.get(row.get('work')) or held.get(row.get('request_id')) or held.get(_declared_id(row['session'])) or held.get(row['root'])
            message = history._db.execute(
                'SELECT id,content,created_at FROM messages WHERE conversation_id=? AND author=? ORDER BY sequence DESC LIMIT 1',
                (ROOM, row['agent'] + ' [' + row['session'] + ']')).fetchone()
            session = {'id': row['root'], 'name': row.get('display_name') or row['agent'],
                       'vendor': row.get('runtime') or row.get('app') or '', 'status': row['status'],
                       'task': task['id'] if task else None, 'taskTitle': task['title'] if task else '',
                       'message': {'id': message[0], 'text': message[1].partition('\n')[2] or message[1], 'at': message[2]} if message else None,
                       'hasTranscript': _has_transcript(row.get('runtime'), row.get('native_session_id'))}
            sessions.append(session)
            if task and task['id'] not in tasks:
                path = task.get('session_path')
                workflow, count, error = False, 0, ''
                if path:
                    try:
                        document = read_document(path)
                        workflow = document.get('properties', {}).get('taskContext', {}).get('task') == task['id']
                        count = sum(bool(n.get('params', {}).get('workshop_step')) for n in document['nodes'])
                    except (OSError, ValueError) as refused:
                        error = str(refused)
                tasks[task['id']] = {'id': task['id'], 'title': task['title'], 'status': task['status'],
                                     'path': path if workflow else None, 'steps': count, 'error': error}
            if task and tasks[task['id']]['path']:
                wires.append({'id': row['root'] + ':task', 'from': row['root'], 'to': task['id'],
                              'fromPort': 'task', 'toPort': 'task', 'type': 'event'})
        for runtime in roster:
            # Roster placeholders (idle / not running) are Settings rows only; do not invent Workshop sessions.
            if runtime.get('evidence') != 'process':
                continue
            if not any(row['vendor'] == runtime['runtime'] for row in sessions):
                sessions.append({'id': 'runtime:' + runtime['id'], 'name': runtime['name'], 'vendor': runtime['runtime'],
                                 'status': runtime['presence'], 'task': None, 'taskTitle': '', 'message': None})
        for task in held.values():
            if task['id'] not in tasks and not task.get('archived'):
                tasks[task['id']] = {'id': task['id'], 'title': task['title'], 'status': task['status'],
                                     'path': task.get('session_path'), 'steps': 0, 'error': ''}
    return {'ok': True, 'agents': roster, 'sessions': sessions, 'tasks': list(tasks.values()), 'wires': wires}


def r_agents_transcript(s, req):
    from .agent_status import read_transcript
    from .workshop_mailbox import application_history, read_declarations
    session = (req.body or {}).get('session')
    with application_history(read_only=True) as history:
        row = next((r for r in read_declarations(history._db) if r['root'] == session), None)
    if row is None:
        raise Refused('This agent session is no longer available.', 404)
    return {'ok': True, **read_transcript(row.get('runtime'), row.get('native_session_id'))}


# -- Settings: one JSON file per owner; secrets stay in Windows Credential Manager --
def _secrets():
    from .settings_owner import SettingsOwner
    return SettingsOwner._secrets(None)


def r_settings_action(s, req):
    from .settings_owner import SettingsOwner, read_router_settings
    body = req.body or {}
    function, args = body.get('function'), body.get('args') or []
    companion = s.files['companion']
    settings = s.files['settings']
    from .access_owner import FUNCTIONS as ACCESS_FUNCTIONS, access_action
    if function in ACCESS_FUNCTIONS:
        return {'ok': True, 'result': access_action(settings, function, list(args))}
    if function == 'exposeSettingsPage':
        if len(args) != 1:
            raise Refused('Choose a Settings page.')
        return {'ok': True, 'result': SettingsOwner.exposeSettingsPage(args[0])}
    if function in ('readSessionsFolder', 'setSessionsFolder'):
        from .session_files import sessions_directory, set_sessions_directory
        moved = []
        if function == 'setSessionsFolder':
            path = args[0] if args else None
            if not path and s.native_folder_picker:
                path = s.native_folder_picker('Sessions folder')
            if path:
                moved = set_sessions_directory(path)
        return {'ok': True, 'result': {'sessionsFolder': str(sessions_directory()), 'moved': moved}}
    if function == 'readUpdatePolicySettings':
        # What the updater really uses for each update setting: the saved value, else its catalogue default.
        from . import application_update as update_owner
        from .pipeline_engines import UPDATE_POLICY_SETTINGS
        from .settings_owner import _APPLICATION_SETTING_SPECS, _application_setting_default
        saved = update_owner.saved_application_settings(s.state_dir)
        effective = {}
        for key in UPDATE_POLICY_SETTINGS:
            value = saved.get(key, _application_setting_default(key))
            effective[key] = bool(value) if _APPLICATION_SETTING_SPECS[key][0] == 'boolean' else value
        return {'ok': True, 'result': effective}
    if function in ('readApplicationSettings', 'setApplicationSetting'):
        # The Workshop settings the policy reads (application_update.saved_application_settings): one owner,
        # settings/settings.json. A value outside its Settings spec is refused, never stored.
        from .application_update import save_application_setting, saved_application_settings
        if function == 'setApplicationSetting':
            if len(args) != 2:
                raise Refused('Choose one Workshop setting and its value.')
            try:
                save_application_setting(args[0], args[1], s.state_dir)
            except ValueError as refused:
                raise Refused(str(refused)) from None
        return {'ok': True, 'result': saved_application_settings(s.state_dir)}
    if function in ('readCanvasTabs', 'setCanvasTabs'):
        from .settings_owner import canvas_tabs
        return {'ok': True, 'result': canvas_tabs(function, args, settings)}
    if function in ('readHomeLayout', 'setHomeLayout'):
        from .settings_owner import home_layout
        return {'ok': True, 'result': home_layout(function, args, settings)}
    if function in ('readDockLayout', 'setDockLayout'):
        from .settings_owner import dock_layout
        return {'ok': True, 'result': dock_layout(function, args, settings)}
    if function in ('readLibraryCollapsed', 'setLibraryCollapsed'):
        from .library_engines import LIBRARY_PRESENTATION, LIBRARY_TREE
        categories = list(dict.fromkeys(category for category, _ in LIBRARY_PRESENTATION))
        tree = [{'id': row, 'label': label, 'icon': icon, 'categories': list(shown)}
                for row, label, icon, shown in LIBRARY_TREE]
        if function == 'setLibraryCollapsed':
            groups = args[0] if args else None
            if (not isinstance(groups, list) or len(groups) > len(categories) or any(
                    group not in categories for group in groups)):
                raise Refused('Choose valid Library categories.')
            settings.update({'libraryCollapsed': list(dict.fromkeys(groups))})
        # Until he opens or closes a category himself, the tree starts closed (the design's first look).
        return {'ok': True, 'result': {'libraryCollapsed': settings.read().get('libraryCollapsed', [row['id'] for row in tree]),
                                      'libraryCategories': categories, 'libraryTree': tree}}
    if function in ('readSessionListFilters', 'setSessionListFilter'):
        filters = settings.read().get('sessionListFilters', {})
        if function == 'setSessionListFilter':
            if len(args) != 2 or args[0] != 'home' or args[1] not in ('all', 'workflow', 'agent-session'):
                raise Refused('Choose a session list and filter.')
            filters = {**filters, args[0]: args[1]}
            settings.update({'sessionListFilters': filters})
        return {'ok': True, 'result': {'sessionListFilters': filters}}
    if function in ('readControls', 'setAppearance'):
        from .settings_owner import appearance_settings
        appearance = appearance_settings(function, args, settings)
        rows = appearance['appearanceSettings']
        if function == 'setAppearance':
            return {'ok': True, 'result': appearance}
    if function == 'readControls':
        from .settings_owner import dock_layout as one_dock_layout
        result = {'companion': companion.read(), 'providerPreferences': read_router_settings()['providerPreferences'],
                  'controlErrors': {}, 'providerModels': {},
                  'appearanceSettings': rows, 'homeLayout': settings.read().get('homeLayout', {}),
                  'dockLayout': one_dock_layout(settings=settings)['dockLayout']}
        try:
            result['secrets'] = _secrets()
        except Exception:  # noqa: BLE001
            result['secrets'] = []
            result['controlErrors']['secrets'] = 'Connected account index could not be read. Refresh Connections.'
        return {'ok': True, 'result': result}
    if function in ('readPermissions', 'setPermissions'):
        # Run mode and per-tool modes: parameters the one decision (hook_decision.decide) reads.
        from .hook_decision import read_permissions, write_permissions, RUN_MODES, TOOL_MODES
        path = s.settings_dir / 'permissions.json'
        try:
            values = (read_permissions(path=path) if function == 'readPermissions'
                      else write_permissions(args[0] if args else None, path=path))
        except ValueError as refused:
            raise Refused(str(refused)) from refused
        return {'ok': True, 'result': {**values, 'runModes': list(RUN_MODES), 'toolModes': list(TOOL_MODES)}}
    if function == 'setCompanionState':
        written = companion.write({**companion.read(), **(args[0] if args else {})})
        from .baboom_companion_process import settings_changed
        settings_changed()  # BABOOM, in its own process, applies the change now
        return {'ok': True, 'result': {'companion': written}}
    if function == 'setProviderModel':
        return {'ok': True, 'result': SettingsOwner(None, dependencies=object()).setProviderModel(*args)}
    if function == 'disconnectSecret':
        from .model_router import revoke_social_credential
        row = next((r for r in _secrets() if r['id'] == (args[0] if args else None)), None)
        if row is None:
            raise Refused('Choose an existing connected account, then retry.')
        result = revoke_social_credential({key: row[key] for key in ('vault_entry', 'provider', 'account_id')})
        return {'ok': True, 'result': {**result, 'secrets': _secrets()}}
    if function == 'hostPrograms':
        from .host_exec import programs
        return {'ok': True, 'result': {'programs': programs()}}
    if function == 'hostProgramState':
        from .host_exec import programs as program_choices, program_state
        key = args[0] if args else ''
        if key in ('python', 'acad-core'):
            return {'ok': True, 'result': program_state(key)}  # Local executable paths only.
        row = next((row for row in s._hosts.get() or [] if row['id'] == {'acad': 'autocad', 'office': 'excel'}.get(key, key)), {})
        label = next((row['label'] for row in program_choices() if row['id'] == key), '')
        state = _plain_status(row.get('state')) if row else 'Checking'
        return {'ok': True, 'result': {'id': key, 'label': label, 'state': state,
                                     'reachable': row.get('state') == 'connected'}}
    if function == 'connectorActions':
        from .host_exec import ConnectorUnreachable, connector_actions, connectors
        name = args[0] if args else ''
        try:
            actions = connector_actions(name)
            error = ''
        except ConnectorUnreachable as refused:
            actions = []
            error = str(refused)
        return {'ok': True, 'result': {'connectors': connectors(), 'actions': actions, 'error': error}}
    if function == 'connectorPreview':
        from .host_exec import connector_preview
        payload = args[0] if args and isinstance(args[0], dict) else {}
        return {'ok': True, 'result': connector_preview(
            payload.get('connector'), payload.get('action'), payload.get('args'))}
    if function == 'openProgram':
        # The first-run "Open Revit": start the newest installed Revit (Autodesk installs one folder per year).
        if (args[0] if args else '') != 'revit':
            raise Refused('Only Revit can be opened from here.')
        found = max(Path(os.environ.get('ProgramFiles', r'C:\Program Files'), 'Autodesk').glob('Revit 20[0-9][0-9]/Revit.exe'),
                    default=None)
        if found is None:
            raise Refused('Revit is not installed on this PC.')
        os.startfile(str(found))  # noqa: S606 - the founder pressed Open; the installed program starts
        return {'ok': True, 'result': {'opened': str(found)}}
    if function == 'setSettingsScope':
        return {'ok': True, 'result': settings.update({'settingsScope': args[0] if args else 'User'})}
    local = {'ok': True, 'settingsScope': settings.read().get('settingsScope', 'User'), 'workspacePolicies': {}}
    if function == 'readOperations':
        return {'ok': True, 'result': {**local, 'dependencies': []}}
    if function in SettingsOwner.ACCOUNT:
        if function == 'read':
            return {'ok': True, 'result': {**local, **s.account_read()}}
        # Account, office, team and billing are the ArchHub cloud's; local preferences are one plain file.
        from .settings_owner import AccountFiles, CloudRouteUnavailable
        owner = SettingsOwner(AccountFiles(s.settings_dir / 'account.json'))
        try:
            result = owner.dispatch(function, list(args))
            if s._account is not None:
                s._account.at = 0.0
            return {'ok': True, 'result': result}
        except (ValueError, CloudRouteUnavailable, OSError) as refused:
            raise Refused(str(refused)) from refused
    return {'ok': True, 'result': not_available('Settings "%s"' % function)}


def r_workspace_roots(s, req):
    action, body = _action(req, 'list')
    store = s.files['workspaces']
    held = store.read()
    if not held['roots'] and not held.get('imported_legacy'):
        # One-time carry-over of the folders registered before NOGRAPH (~/.archhub/workspace-roots.json).
        from .workspace_roots_catalogue import default_snapshot_path
        legacy = default_snapshot_path()
        try:
            old = json.loads(legacy.read_text(encoding='utf-8')).get('roots') or []
        except (OSError, ValueError):
            old = []
        held['roots'] = [{'root_id': 'workspace:' + str(r.get('id') or secrets.token_hex(6)),
                          'label': Path(str(r['path'])).name, 'path': str(r['path']),
                          'privacy': r.get('privacy', 'private'), 'state': 'registered', 'available': True}
                         for r in old if r.get('path')]
        held['imported_legacy'] = True
        store.write(held)
    if action == 'browse':
        picker = s.native_folder_picker
        return {'ok': True, 'path': str(picker('Choose a workspace folder') or '') if picker else ''}
    if action == 'register':
        path = Path(str(body.get('path') or ''))
        if not path.is_absolute() or not path.is_dir():
            raise Refused('Choose an existing local folder.')
        row = {'root_id': 'workspace:' + secrets.token_hex(6), 'label': path.name, 'path': str(path),
               'privacy': body.get('privacy', 'private'), 'state': 'registered', 'available': True}
        held['roots'] = [r for r in held['roots'] if r['path'] != str(path)] + [row]
        store.write(held)
        return {'ok': True, 'root': row}
    if action == 'unregister':
        held['roots'] = [r for r in held['roots'] if r['root_id'] != body.get('id')]
        store.write(held)
        return {'ok': True}
    built_in = s.workspace_built_in()
    roots = [{**r, 'available': Path(r['path']).is_dir()} for r in held['roots']]
    return {'ok': True, 'roots': roots, 'revision': len(roots),
            'built_in': {'id': 'workspace:archhub', 'label': 'ArchHub', 'path': built_in, 'removable': False,
                         'available': bool(built_in) and Path(built_in).is_dir()} if built_in else None,
            'health': {'state': 'current', 'message': 'Workspaces are read from settings/workspaces.json.'}}


def r_pick_file(s, req):
    body = req.body or {}
    if s.native_file_picker is None:
        return {'ok': True, 'path': '', 'note': 'no native picker in this runtime'}
    return {'ok': True, 'path': str(s.native_file_picker(str(body.get('title') or 'Choose a file'), str(body.get('filter') or '')) or '')}


def _mods_rows(store):
    from .domains.selfext import SHIPPED_MOD_ROWS
    held = store.read()
    rows = []
    for base in SHIPPED_MOD_ROWS:
        enabled = held['enabled'].get(str(base['id']), bool(base.get('enabled', True)))
        row = json.loads(json.dumps(base))
        for node in row.get('nodes', []):
            params = held.get('params', {}).get(str(base['id']), {})
            node['params'] = {key: params.get(key, value) for key, value in node.get('params', {}).items()}
        rows.append({**row, 'enabled': enabled, 'status': 'built-in' if enabled else 'off',
                     'fired_today': held.get('fired_today', {}).get(str(base['id']), 0)})
    built_in = len(rows)
    for manifest in held['packages'].values():
        enabled = held['enabled'].get(manifest['id'], True)
        rows.append({**manifest, 'enabled': enabled, 'status': 'Installed' if enabled else 'off'})
    return {'installed': len(rows) - built_in, 'built_in': built_in, 'failed': 0, 'rows': rows}


def r_mods(s, req):
    from .domains.selfext import review_mod_package
    action, body = _action(req, 'state')
    store = s.files['mods']
    held = store.read()
    if action == 'browse':
        picker = s.native_folder_picker
        return {'ok': True, 'path': str(picker('Choose an ArchHub mod folder') or '') if picker else ''}
    if action == 'review':
        return {'ok': True, 'review': review_mod_package(body.get('path') or '')}
    mod_id = str(body.get('id') or '')
    if action == 'install':
        manifest = review_mod_package(body.get('path') or '')
        if manifest['digest'] != body.get('reviewed_digest'):
            raise Refused('The package changed. Review the current manifest before installing.')
        held['packages'][manifest['id']] = manifest
        held['enabled'][manifest['id']] = True
        mod_id = manifest['id']
    elif action in ('enable', 'retry'):
        held['enabled'][mod_id] = True if action == 'retry' else bool(body.get('enabled'))
    elif action == 'remove':
        if mod_id not in held['packages']:
            raise Refused('Built-in protection mods stay installed. Disable their optional behavior in Settings.')
        held['packages'].pop(mod_id)
    elif action != 'state':
        raise Refused('unknown mods action')
    store.write(held)
    rows = _mods_rows(store)
    return {'ok': True, 'mods': rows, 'mod': next((r for r in rows['rows'] if str(r['id']) == mod_id), None)}


def r_application_update(s, req):
    from .application_update import application_update_action, application_update_status
    return application_update_status(s) if req.method == 'GET' else application_update_action(s, req.body)


def r_cloud_session(s, req):
    summary = s._session.get() or {'signed_in': False, 'email': '', 'state': 'signed_out'}
    return {'ok': True, **{key: value for key, value in summary.items() if key != '_cache_key'},
            'checking': s._session.running}


def r_cloud_signin(s, req):
    from .cloud_signin import METHODS, begin, current_status
    if req.method == 'GET':
        status = current_status()
        if status.get('phase') == 'done':
            s._session.at = 0.0
            s._session.get()
        return {'ok': True, **status}
    method = str((req.body or {}).get('method') or 'google')
    if method not in METHODS:
        raise Refused('sign-in method must be google')
    return {'ok': True, **begin(method)}


def r_cloud_signout(s, req):
    from .cloud_signin import sign_out
    result = sign_out()
    with s._account_lock:
        s._session.reset({'signed_in': False, 'email': '', 'state': 'signed_out', '_cache_key': ''})
        s._account_key, s._account = None, None
    return {'ok': True, **result}


def r_cloud_publish_consent(s, req):
    from .cloud_publish_consent import read_cloud_publish_consent, record_cloud_publish_consent, withdraw_cloud_publish_consent
    from .cloud_session import signed_in_cloud_account
    account = signed_in_cloud_account() or ''
    if req.method == 'POST':
        allow = (req.body or {}).get('allow')
        if type(allow) is not bool:
            raise Refused('Consent must be allowed or withdrawn.', 400)
        if allow and '@' not in account:
            raise Refused('Sign in before allowing cloud publish.')
        record_cloud_publish_consent(s.state_dir, account=account) if allow else withdraw_cloud_publish_consent(s.state_dir)
        s.ensure_cloud_relay(restart=True)
    return {'ok': True, **read_cloud_publish_consent(s.state_dir, account)}


def r_social_connections(s, req):
    from . import social_connections
    return {'ok': True, 'items': social_connections.rows()}


def r_social_connection(s, req):
    from . import social_connections
    if req.method == 'GET':
        return {'ok': True, 'connection': social_connections.connection((req.query.get('provider') or [''])[0])}
    body = req.body or {}
    provider, action = body.get('provider'), body.get('action')
    if action == 'start':
        return {'ok': True, 'connection': social_connections.start(provider)}
    if action == 'cancel':
        return {'ok': True, 'connection': social_connections.cancel(provider)}
    if action == 'finish':
        # The account the provider itself confirmed goes into the protected store; nothing is typed.
        return {'ok': True, 'connection': social_connections.finish(
            None, {k: v for k, v in body.items() if k != 'action'}, require_admission=lambda: None)}
    raise Refused('Choose start, finish or cancel provider sign-in.')


def r_social_finish(provider):
    """LinkedIn / Meta sign-in finish: enroll the account (or Page) the provider returned."""
    def route(s, req):
        from . import cloud_social_oauth
        from .social_custody import enroll_social_account
        body = req.body or {}
        signin = __import__('nodelang.social_%s_signin' % provider, fromlist=['take_verified'])
        with signin._current_lock:
            local = signin._current
        via_cloud = cloud_social_oauth._CURRENT.get(provider) is not None and (
            local is None or local.__class__.__module__ == cloud_social_oauth.__name__)
        try:
            if provider == 'linkedin':
                account_id, token = (cloud_social_oauth.take_verified if via_cloud else lambda _p: signin.take_verified())('linkedin')
                record = {'provider': 'linkedin', 'account_id': account_id,
                          'vault_entry': 'social-linkedin-' + account_id.rsplit(':', 1)[1], 'token': token}
            else:
                if set(body) != {'page_id'}:
                    raise Refused('Meta finish requires one selected Page.')
                selected = (cloud_social_oauth.take_verified_page if via_cloud else signin.take_verified_page)(body['page_id'])
                record = {'provider': 'meta', 'account_id': selected['page']['id'],
                          'vault_entry': 'social-meta-page-' + selected['page']['id'], 'token': selected['page_token']}
        except cloud_social_oauth.SocialGrantNotReady as waiting:
            raise Refused(str(waiting)) from waiting
        return {'ok': True, **enroll_social_account(None, record, require_admission=lambda: None, verified=True)}
    return route


def r_social_credential(s, req):
    """An operator-declared social token goes straight into the protected store (format 1)."""
    from .model_router import save_social_credential
    return {'ok': True, **save_social_credential(req.body or {}, verified=False)}


def r_social_credentials(s, req):
    from .model_router import list_social_credentials
    return {'ok': True, **list_social_credentials()}


def r_social_credential_remove(s, req):
    from .model_router import revoke_social_credential
    body = req.body or {}
    return {'ok': True, **revoke_social_credential({k: body.get(k) for k in ('vault_entry', 'provider', 'account_id')})}


def r_social_signin(provider):
    def route(s, req):
        module = __import__('nodelang.social_%s_signin' % provider, fromlist=['current_status'])
        if req.method == 'GET':
            return {'ok': True, **module.current_status()}
        if req.body == {'cancel': True}:
            return {'ok': True, **module.cancel_current()}
        from .cloud_social_oauth import start
        return {'ok': True, **start(provider)}
    return route


def r_social_surface(s, req):
    body = req.body or {}
    return {'ok': True, **_social().dispatch(body.get('op'), body.get('args') or [])}


def r_social_approvals(s, req):
    return {'ok': True, 'items': _social().pending()}


def r_social_approve(s, req):
    """The user's Approve or Deny on one exact post: the one decision (hook_decision.decide)."""
    from .hook_decision import decide
    body = req.body or {}
    root, digest, word = body.get('delegation'), body.get('input_digest'), body.get('decision')
    card = decide({'approval': 'social', 'owner': _social(), 'id': root, 'digest': digest, 'decision': word})
    decided = 'denied' if card['status'] == 'denied' else 'approved'
    return {'ok': True, 'delegation': root, 'input_digest': digest, 'decision': decided, 'status': card['status'],
            'card': card, **({'message': card['error']} if card.get('error') else {})}


def r_interaction(s, req):
    """Owner-declared commands (community_owner.bindings); every other graph interaction is retired."""
    from .community_owner import COMMANDS, CommunityOwner
    body = req.body or {}
    control = body.get('control')
    if control in COMMANDS and body.get('interaction') == 'owner:community:' + control:
        out = CommunityOwner(s.files['community']).command(control, body.get('event_facts') or [])
        return {'ok': True, 'result': {**out['result'], 'community': out['community']}}
    return not_available('Graph interaction')


def r_provider_key(s, req):
    from .model_router import save_provider_key
    return {'ok': True, **save_provider_key(req.body or {})}


def r_notion_connect(s, req):
    from .host_brokers import notion_connect
    out, label = notion_connect({}, {})
    return {'ok': bool(out.get('ok', True)), 'label': label}


def r_terminal(s, req):
    from .terminal_sessions import TerminalRefused
    terminals = s.terminals()
    try:
        if req.method == 'GET':
            return {'ok': True, **terminals.output((req.query.get('id') or [''])[0], int((req.query.get('since') or ['0'])[0] or 0))}
        action, body = _action(req)
        if action == 'stop':
            return {'ok': True, **terminals.stop(body.get('id'))}
        if action == 'start':
            return {'ok': True, **terminals.start(body.get('cwd'))}
        if action == 'input':
            return {'ok': True, **terminals.write(body.get('id'), body.get('text'))}
    except TerminalRefused as refused:
        raise Refused(str(refused)) from refused
    raise Refused('Terminal action must be start, input or stop.')


def r_studio_surface(s, req):
    """The Studio's open screen, held in memory for the desktop companion (Settings hides the pet)."""
    from . import baboom_nograph
    surface = (req.body or {}).get('surface') if req.method == 'POST' else None
    if surface is not None:
        if not isinstance(surface, str) or len(surface) > 200:
            raise ValueError('surface must be a short screen name')
        baboom_nograph.set_studio_surface(surface)
    return {'ok': True, 'surface': baboom_nograph.studio_surface()}


def r_boot(s, req):
    return {'ok': True, 'ready': True, 'nograph': True}


BRAIN_TOOLS = {'/api/universal/brain-forget': 'brain.delete_fact', '/api/universal/brain-edit': 'brain.edit_fact',
               '/api/universal/brain-publish': 'brain.publish', '/api/universal/brain-remember': 'brain.write'}


def r_brain(s, req):
    """The Brain tab: export, remember, edit, forget, publish -- one owner (brain_files without a graph)."""
    import secrets
    from .pipeline_engines import BrainSilent, _brain_call
    body = req.body if isinstance(req.body, dict) else {}
    try:
        if req.path == '/api/universal/brain-export':
            try:
                wanted = max(1, min(int(body.get('limit') or 500), 100000))
            except (TypeError, ValueError):
                wanted = 500
            return {'ok': True, 'facts': json.loads(_brain_call('brain.list_facts', {'limit': wanted}))}
        tool = BRAIN_TOOLS.get(req.path)
        if tool is None:
            return not_available('Brain "%s"' % req.path.rsplit('/', 1)[-1])
        if tool == 'brain.write':
            said = str(body.get('text') or '').strip()
            if not said:
                return {'ok': False, 'error': 'nothing to remember'}
            arguments = {'ops': [{'op': 'add', 'fragment': {'id': 'remember:' + secrets.token_hex(8), 'kind': 'fact', 'text': said}}]}
        else:
            arguments = {'fragment_id': str(body.get('id') or '').strip(), **({'text': body.get('text')} if 'text' in body else {})}
        return json.loads(_brain_call(tool, arguments))
    except BrainSilent as silent:
        return {'ok': False, 'error': 'Brain not answering: %s' % str(silent)[:200]}


def r_stop(s, req):
    (s.halt_all if req.path == '/stop-all' else s.resume_all)()
    return {'ok': True, 'stopped': s.is_halted()}


BRAIN = ('Brain', r_brain)
# path -> (owner, handler). Every route the Studio calls (studio/api.js + screens).
# ------------------------------------------------ session model (ONE BUILD 1) --
def _live_triggers(s):
    """Trigger nodes allowed to run automatically, as (path, node) pairs."""
    service = getattr(s, 'triggers', None)
    if service is None:
        return set()
    with service.lock:
        return set() if service.paused else {(row['path'], row['node']) for row in service.armed}


def _mark_live(fields, live):
    for trigger in fields['automation']:
        trigger['live'] = (fields['path'], trigger['node']) in live
    return fields


def r_session_model(s, req):
    """Every session-model field, read and set through its owners: the .archhub file (session_files), the
    run history beside it, the task table (members, lease) and the trigger service (live timers)."""
    from . import session_files as files
    action, body = _action(req)
    if action == 'list':
        listed, live = files.list_sessions(), _live_triggers(s)
        for group in listed['groups']:
            for row in group['sessions']:
                _mark_live(row, live)
        return listed
    path = str(files.local_path(str(body.get('path') or '')))
    if action == 'get':
        return {'ok': True, 'session': _mark_live(files.session_fields(files.read_document(path), path), _live_triggers(s))}
    if action == 'links':
        return {'ok': True, 'links': files.link_states(files.read_document(path), path)}
    if action == 'runs':
        limit = body.get('limit', 200)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise Refused('Choose 1 to 1000 runs.')
        return {'ok': True, 'runs': files.read_runs(path, limit)}
    if action == 'setting':
        return {'ok': True, **files.resolve_setting(files.read_document(path), body.get('id'))}
    if s.is_halted():
        raise Refused('Stopped by you. Press Resume to continue.', 403)
    if action == 'set':
        values = body.get('values')
        fields = files.set_session_fields(path, values)
        if isinstance(values, dict) and 'automation' in values and getattr(s, 'triggers', None) is not None:
            s.triggers.refresh()
        return {'ok': True, 'session': _mark_live(fields, _live_triggers(s))}
    if action == 'approve-run':
        if getattr(s, 'triggers', None) is None:
            raise Refused('Triggers run only while the app is open.')
        return {'ok': True, 'outcome': s.triggers.approve(path, body.get('run'))}
    raise Refused('Unknown session model action.', 404)


ROUTES = {
    '/api/session-model': ('session_files (.archhub + runs beside it) + workshop_tasks + canvas_triggers', r_session_model),

    '/api/commands': ('command_registry', r_commands),
    '/api/router/settings': ('settings/router.json + router.sqlite', r_router_settings),
    '/api/router/chat-agents': ('acp_client.AGENTS + PATH (read only)', r_chat_agents),
    '/api/documentation': ('site_export + SPEC.md terms', r_documentation),
    '/api/session-files': ('session_files (.archhub)', r_session_files),
    '/api/universal/canvas': ('System graph (logic only)', r_canvas),
    '/api/universal/canvas-op': ('session reads + settings/project-files.json', r_canvas_op),
    '/api/universal/node-library': ('library_engines', r_node_library),
    '/api/universal/node-create': ('graph only', r_graph_only('Creating a node this way')),
    '/api/universal/run-graph': ('graph only', r_graph_only('This kind of run (press Run on the open workflow)')),
    '/api/universal/set-property': ('graph only', r_graph_only('Graph property editing')),
    '/api/universal/interaction': ('community_owner commands (settings/community.json)', r_interaction),
    '/api/universal/gesture': ('graph only', r_graph_only('Graph gesture')),
    '/api/universal/focus': ('graph only', r_graph_only('Graph focus')),
    '/api/universal/select': ('graph only', r_graph_only('Graph selection')),
    '/api/universal/connect': ('graph only', r_graph_only('Graph wiring')),
    '/api/universal/graph-open': ('graph only', r_graph_only('Opening this way (open an .archhub workflow file)')),
    '/api/universal/agent': ('graph only', r_graph_only('Graph agent run (use the composer)')),
    '/api/universal/work': ('graph only', r_graph_only('Graph Work items')),
    '/api/universal/workshop-work-assign': ('graph only', r_graph_only('Graph Work assignment')),
    '/api/universal/workshop-native': ('graph only', r_graph_only('Graph Work publication')),
    '/api/universal/native-contact': ('graph only', r_graph_only('Graph native contact binding')),
    '/api/universal/mcp-client-install': ('graph only', r_graph_only('MCP client install from the old Workshop page')),
    WORKSHOP_PATH: ('workshop/messages.sqlite3 + Workshop', r_workshop),
    '/api/universal/workshop-model-approval': ('graph only (read: expired)', r_workshop_model_approval),
    '/api/universal/native-agents': ('agent_runtime_registry + declarations', r_native_agents),
    '/api/universal/agents-canvas': ('Workshop derived System view', r_agents_canvas),
    '/api/universal/agents-transcript': ('agent_status bounded native transcript reader', r_agents_transcript),
    '/api/universal/hosts': ('pipeline_engines.probe_connectors + settings/hosts.json', r_hosts),
    '/api/universal/providers': ('model_router.provider_rows', r_providers),
    '/api/universal/models': ('model_catalogue (held) + router.json', r_providers),
    '/api/universal/settings-action': ('settings/*.json + Credential Manager', r_settings_action),
    '/api/universal/workspace-roots': ('settings/workspaces.json', r_workspace_roots),
    '/api/universal/pick-file': ('native picker', r_pick_file),
    '/api/universal/mods': ('settings/mods.json + selfext review', r_mods),
    '/api/universal/application-update': ('application_update', r_application_update),
    '/api/universal/cloud-session': ('cloud_signin (cloud.json)', r_cloud_session),
    '/api/universal/cloud-signin': ('cloud_signin', r_cloud_signin),
    '/api/universal/cloud-signout': ('cloud_signin', r_cloud_signout),
    '/api/universal/cloud-publish-consent': ('cloud_publish_consent', r_cloud_publish_consent),
    '/api/universal/social-connections': ('social_connections', r_social_connections),
    '/api/universal/social-connection': ('social_connections', r_social_connection),
    '/api/universal/social-credentials': ('Credential Manager index', r_social_credentials),
    '/api/universal/social-credential': ('protected store', r_social_credential),
    '/api/universal/social-credential-remove': ('Credential Manager', r_social_credential_remove),
    '/api/universal/social-linkedin-signin': ('social_linkedin_signin', r_social_signin('linkedin')),
    '/api/universal/social-meta-signin': ('social_meta_signin', r_social_signin('meta')),
    '/api/universal/social-linkedin-finish': ('protected store', r_social_finish('linkedin')),
    '/api/universal/social-meta-finish': ('protected store', r_social_finish('meta')),
    '/api/universal/social-linkedin-app': ('ArchHub cloud', r_graph_only('LinkedIn app configuration (ArchHub cloud owns it)')),
    '/api/universal/social-meta-app': ('ArchHub cloud', r_graph_only('Meta app configuration (ArchHub cloud owns it)')),
    '/api/universal/social-approvals': ('social_surface (settings/social.json)', r_social_approvals),
    '/api/universal/social-approve': ('social_surface + hook_decision', r_social_approve),
    '/api/universal/social-surface': ('social_surface (settings/social.json)', r_social_surface),
    '/api/universal/provider-key': ('Credential Manager', r_provider_key),
    '/api/universal/notion-connect': ('host_brokers.notion_connect', r_notion_connect),
    '/api/universal/terminal': ('terminal_sessions', r_terminal),
    '/api/universal/boot': ('this server', r_boot),
    '/api/universal/studio-surface': ('memory (companion presence)', r_studio_surface),
    '/api/universal/brain-export': BRAIN,
    '/stop-all': ('this server', r_stop),
    '/resume': ('this server', r_stop),
}
# Effects never run on a GET (a link or prefetch must not open a sign-in or a picker).
POST_ONLY = frozenset({
    '/api/session-files', '/api/session-model', '/api/universal/canvas-op', '/api/universal/settings-action', '/api/universal/workspace-roots',
    '/api/universal/pick-file', '/api/universal/mods', '/api/universal/cloud-signout', '/api/universal/social-credential-remove',
    '/api/universal/social-surface', '/api/universal/studio-surface', '/api/universal/provider-key', '/api/universal/notion-connect', '/stop-all', '/resume',
    '/api/universal/social-credential', '/api/universal/social-linkedin-finish', '/api/universal/social-meta-finish',
    '/api/universal/social-approve', '/api/universal/interaction',
} | {path for path, (owner, _handler) in ROUTES.items() if owner == 'graph only'})
