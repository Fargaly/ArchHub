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

import hmac
import json
import mimetypes
import os
import secrets
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from .http_server import QuietThreadingHTTPServer, local_browser_admission_error

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
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def not_available(what):
    return {'ok': False, 'status': 'not_available',
            'error': what + ' is unavailable in this release.'}


class JsonFile:
    """One settings owner = one small JSON file, replaced atomically."""

    def __init__(self, path, default):
        self.path, self.default, self.lock = Path(path), default, threading.Lock()

    def read(self):
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return json.loads(json.dumps(self.default))

    def write(self, value):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=self.path.parent, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(value, stream, ensure_ascii=False, indent=1)
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return value


class Cached:
    """A probe refreshed off the request path; None until its first answer."""

    def __init__(self, seconds, probe):
        self.seconds, self.probe, self.value, self.at, self.running = seconds, probe, None, 0.0, False
        self.lock = threading.Lock()

    def get(self):
        with self.lock:
            stale = time.time() - self.at >= self.seconds
            if stale and not self.running:
                self.running = True
                threading.Thread(target=self._run, name='archhub-nograph-probe', daemon=True).start()
        return self.value

    def _run(self):
        try:
            value = self.probe()
        except Exception:  # noqa: BLE001 - a failed probe keeps the last answer
            value = self.value
        with self.lock:
            self.value, self.at, self.running = value, time.time(), False


class NoGraphServer:
    def __init__(self, state_dir, *, host='127.0.0.1', port=0, engines=None):
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
        self.studio_first_run = False
        # The launcher binds these exactly as it did for the old server.
        self.native_file_picker = self.native_folder_picker = self.native_save_file_picker = None
        self.native_window_handle = None
        self.application_update = None
        files = lambda name, default: JsonFile(self.settings_dir / (name + '.json'), default)
        self.files = {name: files(name, default) for name, default in (
            ('workspaces', {'roots': []}), ('mods', {'packages': {}, 'enabled': {}}),
            ('companion', {'mode': 'idle', 'x': None, 'y': None, 'pinned': False}),
            ('social', {'state': {}}), ('hosts', {'disabled': []}), ('project-files', {'files': []}),
            ('settings', {'settingsScope': 'User'}))}
        self._hosts = Cached(30.0, self._probe_hosts)
        self._local = Cached(10.0, self._probe_local)
        self._opencode = {}
        self._terminals = None
        self._agents_api = None
        self.httpd = QuietThreadingHTTPServer((host, port), self._handler())
        global _SERVER
        _SERVER = self
        self.thread = None
        self.cloud_relay = None
        self._relay_lock = threading.Lock()

    # -- lifecycle (same surface the launcher used) ------------------------
    @property
    def port(self):
        return self.httpd.server_address[1]

    @property
    def public_url(self):
        return 'http://127.0.0.1:%d' % self.port

    def start(self):
        self.thread = threading.Thread(target=self.httpd.serve_forever, name='archhub-nograph-http', daemon=True)
        self.thread.start()
        self._hosts.get()
        self._local.get()
        self.ensure_cloud_relay()
        from .canvas_triggers import TriggerService
        self.triggers = TriggerService()
        threading.Thread(target=self.triggers.refresh, name='archhub-triggers', daemon=True).start()
        return self

    def ensure_cloud_relay(self, *, restart=False):
        """Remote agents reach this PC's brokers through the existing cloud relay (cloud_relay.py).

        Same account session (Credential Manager, by reference) and the same recorded
        cloud-publish consent as before; without both start_cloud_relay returns None.
        Only host reads are claimed: the allowlisted read functions local agents use.
        """
        with self._relay_lock:
            held = self.cloud_relay
            if held is not None and not restart and not held._stop.is_set():
                return held
            if held is not None:
                try:
                    held.close(timeout_seconds=RELAY_NODE['params']['close_timeout_seconds'])
                except Exception as stuck:  # noqa: BLE001 - a stuck old worker must not block a new one
                    print('  cloud relay: old worker did not stop -- %s' % stuck, flush=True)
            try:
                from .cloud_relay import HOST_READ, start_cloud_relay
                self.cloud_relay = start_cloud_relay(
                    state_dir=self.state_dir, respond=lambda _text: {}, execute=lambda _text: {},
                    app_kinds=(HOST_READ,))
            except Exception as refused:  # noqa: BLE001
                print('  cloud relay: not started -- %s' % refused, flush=True)
                self.cloud_relay = None
            return self.cloud_relay

    def close(self):
        if getattr(self, 'triggers', None) is not None:
            self.triggers.close()
        relay, self.cloud_relay = self.cloud_relay, None
        if relay is not None:
            try:
                relay.close(timeout_seconds=RELAY_NODE['params']['close_timeout_seconds'])
            except Exception as stuck:  # noqa: BLE001 - closing the app goes on
                print('  cloud relay: did not stop -- %s' % stuck, flush=True)
        self.httpd.shutdown()
        self.httpd.server_close()
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

    def halt_all(self):
        self._halted.set()

    def resume_all(self):
        self._halted.clear()

    # -- probes -------------------------------------------------------------
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

            def log_message(self, *_args):
                return

            def send_json(self, status, payload, headers=()):
                raw = json.dumps(payload, separators=(',', ':'), default=str).encode('utf-8')
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
                parsed = urlparse(self.path)
                path = parsed.path
                try:
                    denied = local_browser_admission_error(self.headers, owner.port)
                    if denied:
                        raise Refused(denied, 403)
                    if method == 'GET' and (path in ('/', '/studio', '/studio/') or path.startswith('/studio/')):
                        owner._studio(self, parsed)
                        return
                    if method == 'GET' and (path == '/assets/fonts.css' or path.startswith('/assets/fonts/')):
                        owner._font(self, path)
                        return
                    if path == '/baboom/turn' and method == 'POST':
                        # The app's BABOOM turn door (loopback, per-boot token): any agent's connector reaches it.
                        from .baboom_nograph import accept_turn
                        turn = self.body()
                        self.send_json(200, accept_turn(self.headers.get('X-ArchHub-BABOOM'), turn.get('text'), turn.get('message_id')))
                        return
                    if path == '/api/universal/session' and method == 'POST':
                        owner._sign_in(self)
                        return
                    if not self.admitted():
                        raise Refused('Browser session required. Reopen ArchHub.', 403)
                    if path == '/api/router/chat':
                        owner._router_chat(self)
                        return
                    route = ROUTES.get(path) or (BRAIN if path.startswith('/api/universal/brain-') else None)
                    if route is None:
                        raise Refused('No such route.', 404)
                    if method == 'GET' and path in POST_ONLY:
                        raise Refused('This action needs a POST from the Studio.', 405)
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    body = self.body(SESSION_BODY if path == '/api/session-files' else MAX_BODY) if method == 'POST' else None
                    result = route[1](owner, SimpleNamespace(method=method, path=path, query=query, body=body, handler=self))
                    self.send_json(200, result if isinstance(result, dict) else {'ok': True, 'result': result})
                except Refused as refusal:
                    self.send_json(refusal.status, {'ok': False, 'error': str(refusal)})
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
            raw = raw.replace(b'/*__ARCHHUB_BOOT__*/ null', json.dumps({
                'token': self.browser_session_token, 'csrf': self.browser_csrf_token,
                'first_run': self.studio_first_run is True,
                'home_load_ms': LIBRARY_ITEM_ENGINES['tool_workshop']['params'].get('home_load_ms', 3000),
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
        from .model_router import composer_chat
        body = handler.body()
        if self.is_halted():
            raise Refused('Stopped by you. Press Resume to continue.', 403)
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
            import re
            prompt = str(body.get('prompt') or '')
            handles = [h.casefold() for h in re.findall(r'(?<![\w@])@([A-Za-z0-9][\w.-]*)', prompt)]
            if handles:
                # The composer is the router: @agents go live into those sessions, no mention goes to a model.
                result = _route_to_agents(prompt, handles, body.get('reply_to') or None)
            else:
                if body.get('agent', 'BABOOM') == 'BABOOM' and _baboom_brain() is not None:
                    result = _ask_baboom(prompt)
                else:
                    result = composer_chat(body, on_delta=lambda text: event({'delta': text}))
                try:
                    from .workshop_live import record_answer
                    record_answer(prompt, result['answer'], result['model'])
                except Exception as error:  # noqa: BLE001 - the answer stands even if history is busy
                    result['history_error'] = str(error)
            event({'result': result})
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


def _baboom_brain():
    from .baboom_nograph import brain
    return brain()


def _ask_baboom(prompt):
    """The composer's BABOOM turn: Goose with its tools; a profiling row like any model route."""
    import uuid
    from .baboom_nograph import ask
    from .model_router import request_profiles
    started = time.monotonic()
    record = {'id': str(uuid.uuid4()), 'ts': time.time(), 'agent': 'BABOOM', 'model': 'goose', 'provider': 'Goose',
              'tokens': None, 'ms': 0, 'outcome': 'refused'}
    try:
        result = ask(prompt)
        record.update(model=result['via'].get('model', 'goose'), outcome='answered')
    finally:
        record['ms'] = int((time.monotonic() - started) * 1000)
        request_profiles(record)
    steps = ''.join('\n\u2022 %s: %s' % (s.get('tool'), s.get('status')) for s in result.get('steps', []))
    return {'ok': True, 'answer': result['text'] + steps, 'provider': 'BABOOM (Goose)', 'model': record['model'],
            'request_id': record['id'], 'applied': [], 'steps': result.get('steps', [])}


def _route_to_agents(prompt, handles, reply_to=None):
    """@mentions: one Workshop message from Ahmed, pushed live; a profiling row per recipient."""
    import uuid
    from .model_router import request_profiles
    from .workshop_live import send_as_founder
    started = time.monotonic()
    sent = send_as_founder(prompt, handles, reply_to=reply_to)
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


def r_session_files(s, req):
    from .session_files import SessionFiles
    from .enforce import guard_effect
    if s.is_halted():
        raise Refused('Stopped by you. Press Resume to continue.', 403)
    result = SessionFiles().dispatch(req.body, invoke=guard_effect, picker=s.native_file_picker,
                                     save_picker=s.native_save_file_picker, stopped=s.is_halted)
    if (req.body or {}).get('action') in ('save', 'autosave', 'open') and getattr(s, 'triggers', None) is not None:
        threading.Thread(target=s.triggers.refresh, name='archhub-triggers', daemon=True).start()
    return result


def r_router_settings(s, req):
    from .settings_owner import SettingsOwner
    owner = SettingsOwner(None, dependencies=object())
    if req.method == 'GET' or not req.body:
        return {'ok': True, **owner.routerSettings()}
    return {'ok': True, **owner.setRouterSettings(req.body)}


# The System graph is logic only: the owners of this server, wired by what feeds what.
SYSTEM_OWNERS = (
    ('owner:canvas', 'Canvas', 'Session files', 'sessions-files/*.archhub', ['workshop']),
    ('owner:library', 'Node library', 'Session files', 'library_engines + pipeline_engines', ['canvas']),
    ('owner:workshop', 'Workshop', 'Workshop', 'workshop/messages.sqlite3', ['router']),
    ('owner:workshop', 'Workshop', 'Workshop', 'workshop/ (native injection)', ['workshop']),
    ('owner:router', 'Router', 'Router', 'settings/router.json', ['profiling']),
    ('owner:profiling', 'Profiling', 'Router', 'settings/router.sqlite', []),
    ('owner:brokers', 'Brokers', 'Hosts', 'broker sessions/*.json + BridgeAuth', ['canvas']),
    ('owner:settings', 'Settings', 'Settings', 'settings/*.json', ['router']),
    ('owner:secrets', 'Secrets', 'Settings', 'Windows Credential Manager (by reference)', ['router']),
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
    return {'ok': True, 'revision': 0, 'root': 'app:system', 'canvas_root': 'app:system', 'graph_id': 'app:system',
            'scope': {'current': 'app:system', 'current_label': 'System graph'}, 'nodes': nodes, 'wires': wires,
            'catalog': [], 'interaction_projection': {'bindings': []}, 'viewport': {'x': 0, 'y': 0, 'zoom': 1}}


def r_canvas_op(s, req):
    body = req.body or {}
    op, args = body.get('op'), body.get('args') or []
    if op == 'project_schedules':
        return {'ok': True, 'result': _schedules()}
    reads = {'list_skills': [], 'mcp_servers': [], 'community_state': {},
             'project_state': {'versions': [], 'modelReview': {'operation': '', 'results': [], 'issues': []}, 'dismissed': []}}
    if op in reads:
        return {'ok': True, 'result': reads[op]}
    if op == 'library_ports':
        from .session_files import catalogue
        return {'ok': True, 'result': catalogue()}
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
        # The nine built-in starters (Book ch.12); each opens as its own .archhub workflow.
        from .starters import listing
        return {'ok': True, 'templates': listing(s._hosts.get() or [])}
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
    from .model_router import provider_rows, find_assistant
    from .cloud_relay import load_cloud_session
    states = s._local.get()
    if req.path.endswith('/models'):
        from .settings_owner import read_router_settings
        from .model_catalogue import groups_with_routes, held_model_groups
        session = load_cloud_session()
        held = held_model_groups(session)
        result = groups_with_routes(held) if held is not None else {'ok': True, 'groups': [], 'count': 0}
        route = read_router_settings()['default_model']  # same pair application_server._default_agent_model answers
        return {**result, 'selected_route': route, 'default_route': route, 'default_source': ROUTER_FILE}
    return {'ok': True, 'providers': provider_rows(
        cloud_session=load_cloud_session(),
        local_probe=lambda _host, port: None if states is None else states.get(int(port)),
        cli_probe=find_assistant, opencode_status_probe=s.opencode_status)}


# -- Workshop: the room is workshop/messages.sqlite3; delivery is Workshop --
def _declarations():
    from .workshop_mailbox import application_history, read_declarations
    with application_history() as history:
        return read_declarations(history._db, include_archived=True)


def _list_tasks():
    """The Work column: the Workshop tasks table (claimed atomically by agents with task.claim)."""
    from .workshop_mailbox import application_history
    from .workshop_tasks import column
    with application_history() as history:
        return column(history)


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


def _list_agents():
    from .agent_runtime_registry import RUNTIMES, discover_runtime_processes
    observed = discover_runtime_processes()
    declared = [row for row in _declarations() if row.get('current')]
    rows = {}
    for process in observed['processes']:
        runtime = process['runtime']
        row = rows.get(runtime)
        if row is None:
            mine = [r for r in declared if (r.get('runtime') or r.get('app')) == runtime]
            busy = [r for r in mine if r.get('status') == 'working']
            row = rows[runtime] = {'id': runtime, 'runtime': runtime, 'name': RUNTIMES.get(runtime, {}).get('label', runtime),
                                   'session_count': 0, 'presence': 'working' if busy else 'idle',
                                   'status_text': 'Working' if busy else 'Idle',
                                   'task': busy[0].get('task') if busy else 'Idle', 'model': 'Model not reported',
                                   'sessions': [{'root': r['root'], 'task': r.get('task'), 'status': r.get('status'),
                                                 'request_id': r.get('request_id', r['root'])} for r in mine],
                                   'observation_complete': observed['complete'], 'evidence': 'process'}
        row['session_count'] += 1
    return list(rows.values())


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
    from .canvas_triggers import next_delay
    service = getattr(_SERVER, 'triggers', None)
    if service is None:
        return []
    rows = []
    for row in service.armed:
        last = next((f for f in reversed(service.fired) if (f['path'], f['node']) == (row['path'], row['node'])), None)
        params = row['params']
        every = params.get('every_seconds') if row['kind'] == 'trigger.schedule' else None
        rows.append({'id': row['path'] + '#' + row['node'], 'title': (row['title'] or row['kind']) + ' \u00b7 ' + Path(row['path']).stem,
                     'time': ('every %ss' % every) if every not in (None, '', '0') else params.get('daily_at') or ('on change in ' + str(params.get('folder'))),
                     'enabled': True, 'kind': row['kind'], 'path': row['path'],
                     'nextInSeconds': round(next_delay(params)) if row['kind'] == 'trigger.schedule' else None,
                     'lastResult': last})
    return rows


def _read_desktop():
    return {'owner': 'app:desktop', 'program': '', 'stage': 'Watching', 'taskId': None, 'offers': [], 'schedules': _schedules()}


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
    owners = {'hostskills': _host_skills, 'watcher': _watcher}
    if kind not in owners:
        from .universal_cell import InvalidCell
        raise InvalidCell('This approval kind is not served here.')
    return decide({'approval': kind, 'owner': owners[kind](request_id), 'id': root, 'digest': digest,
                   'decision': decision})


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


WORKSHOP_READS = {
    'listTasks': lambda *a: _list_tasks(),
    'setTaskStatus': _set_task_status,
    'listAgentsWorking': lambda *a: _list_agents(),
    'listWorkshopMessages': lambda before=None, *a: _list_messages(before),
    'listApprovals': lambda *a: _watcher().reviews() + _host_skills().reviews(),
    'listNotifications': lambda *a: {'notifications': []},
    'readWatcher': lambda *a: _watcher().read(),
    'readDesktop': lambda *a: _read_desktop(),
    'readHostSkills': lambda *a: _host_skills().read(),
    'getAgentSurface': lambda *a: {'learning': {}},
    'getGraphMetadata': lambda *a: {},
    'refreshOfficeAwareness': lambda *a: [],
    'sendToBaboom': _send_to_baboom,
    'listLiveAgents': lambda *a: __import__('nodelang.workshop_live', fromlist=['live_agents']).live_agents(with_status=True),
}


def r_workshop(s, req):
    if req.method == 'GET':
        return {'ok': True, **_list_messages()}
    action, body = _action(req)
    if action == 'data-api':
        function = body.get('function')
        if function in OWNER_ACTIONS:
            from .universal_cell import InvalidCell
            factory, method = OWNER_ACTIONS[function]
            try:
                return {'ok': True, 'result': method(factory(body.get('request_id') or ''), *(body.get('args') or []))}
            except (InvalidCell, TypeError) as refused:
                return {'ok': True, 'result': {'ok': False, 'error': str(refused)}}
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
    if function == 'readControls':
        result = {'companion': companion.read(), 'providerPreferences': read_router_settings()['providerPreferences'],
                  'controlErrors': {}, 'providerModels': {}}
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
        return {'ok': True, 'result': {'companion': companion.write({**companion.read(), **(args[0] if args else {})})}}
    if function == 'setProviderModel':
        return {'ok': True, 'result': SettingsOwner(None, dependencies=object()).setProviderModel(*args)}
    if function == 'disconnectSecret':
        from .model_router import revoke_social_credential
        row = next((r for r in _secrets() if r['id'] == (args[0] if args else None)), None)
        if row is None:
            raise Refused('Choose an existing connected account, then retry.')
        result = revoke_social_credential({key: row[key] for key in ('vault_entry', 'provider', 'account_id')})
        return {'ok': True, 'result': {**result, 'secrets': _secrets()}}
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
        return {'ok': True, 'result': settings.write({**settings.read(), 'settingsScope': args[0] if args else 'User'})}
    local = {'ok': True, 'settingsScope': settings.read().get('settingsScope', 'User'), 'workspacePolicies': {}}
    if function == 'readOperations':
        return {'ok': True, 'result': {**local, 'dependencies': []}}
    if function in SettingsOwner.ACCOUNT:
        # Account, office, team and billing are the ArchHub cloud's; local preferences are one plain file.
        from .settings_owner import AccountFiles, CloudRouteUnavailable
        from .universal_cell import InvalidCell
        owner = SettingsOwner(AccountFiles(s.settings_dir / 'account.json'))
        try:
            return {'ok': True, 'result': {**(local if function == 'read' else {}), **owner.dispatch(function, list(args))}}
        except (InvalidCell, CloudRouteUnavailable, OSError) as refused:
            if function == 'read':   # signed out: Settings still opens with the local values
                return {'ok': True, 'result': {**local, 'dependencies': [], 'controlErrors': {'account': str(refused)}}}
            raise Refused(str(refused)) from refused
    return {'ok': True, 'result': not_available('Settings "%s"' % function)}


def r_workspace_roots(s, req):
    action, body = _action(req, 'list')
    store = s.files['workspaces']
    held = store.read()
    if not held['roots'] and not held.get('imported_legacy'):
        # One-time carry-over of the folders registered before NOGRAPH (~/.archhub/workspace-roots.json).
        legacy = Path(os.environ.get('USERPROFILE') or str(Path.home())) / '.archhub' / 'workspace-roots.json'
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
        rows.append({**json.loads(json.dumps(base)), 'enabled': enabled, 'status': 'built-in' if enabled else 'off'})
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
    from .cloud_signin import session_summary
    summary = session_summary()
    if summary.get('signed_in'):
        s.ensure_cloud_relay()  # a sign-in made after start begins remote reach here
    return {'ok': True, **summary}


def r_cloud_signin(s, req):
    from .cloud_signin import METHODS, begin, current_status
    if req.method == 'GET':
        return {'ok': True, **current_status()}
    method = str((req.body or {}).get('method') or 'google')
    if method not in METHODS:
        raise Refused('sign-in method must be google')
    return {'ok': True, **begin(method)}


def r_cloud_signout(s, req):
    from .cloud_signin import sign_out
    return {'ok': True, **sign_out()}


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
    store = s.files['social']
    state = store.read()['state']
    if body.get('op') == 'get_state':
        return {'ok': True, 'state': state, 'result': state}
    return {'ok': True, 'state': state, 'result': not_available('Social operation "%s"' % body.get('op'))}


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
ROUTES = {
    '/api/router/settings': ('settings/router.json + router.sqlite', r_router_settings),
    '/api/session-files': ('session_files (.archhub)', r_session_files),
    '/api/universal/canvas': ('System graph (logic only)', r_canvas),
    '/api/universal/canvas-op': ('session reads + settings/project-files.json', r_canvas_op),
    '/api/universal/node-library': ('library_engines', r_node_library),
    '/api/universal/node-create': ('graph only', r_graph_only('Creating a node this way')),
    '/api/universal/run-graph': ('graph only', r_graph_only('This kind of run (press Run on the open workflow)')),
    '/api/universal/set-property': ('graph only', r_graph_only('Graph property editing')),
    '/api/universal/interaction': ('graph only', r_graph_only('Graph interaction')),
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
    '/api/universal/social-approvals': ('graph only (read: empty)', lambda s, req: {'ok': True, 'items': []}),
    '/api/universal/social-approve': ('graph only', r_graph_only('Social approval')),
    '/api/universal/social-surface': ('settings/social.json', r_social_surface),
    '/api/universal/provider-key': ('Credential Manager', r_provider_key),
    '/api/universal/notion-connect': ('host_brokers.notion_connect', r_notion_connect),
    '/api/universal/terminal': ('terminal_sessions', r_terminal),
    '/api/universal/boot': ('this server', r_boot),
    '/api/universal/brain-export': BRAIN,
    '/stop-all': ('this server', r_stop),
    '/resume': ('this server', r_stop),
}
# Effects never run on a GET (a link or prefetch must not open a sign-in or a picker).
POST_ONLY = frozenset({
    '/api/session-files', '/api/universal/canvas-op', '/api/universal/settings-action', '/api/universal/workspace-roots',
    '/api/universal/pick-file', '/api/universal/mods', '/api/universal/cloud-signout', '/api/universal/social-credential-remove',
    '/api/universal/social-surface', '/api/universal/provider-key', '/api/universal/notion-connect', '/stop-all', '/resume',
    '/api/universal/social-credential', '/api/universal/social-linkedin-finish', '/api/universal/social-meta-finish',
} | {path for path, (owner, _handler) in ROUTES.items() if owner == 'graph only'})
