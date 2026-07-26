"""Normal-window desktop host for the persistent node-native application."""
from __future__ import annotations

import sys
import json
import os
import socket
from pathlib import Path
import urllib.request
from urllib.parse import urlsplit

from .application_machine_transport import (
    MachineTransportError,
    UniversalRuntimeClient,
    default_runtime_descriptor_path,
)
from .application_server import ApplicationServer
from .persistence import default_state_path
from .universal_application import UNIVERSAL_APPLICATION_SCHEMA_VERSION
from .runtime_credentials import BrowserCredentialVault
from .cell_secret_keys import WindowsDpapiSigningKeyProvider
from .runtime_gateway import GatewayError, RuntimeGateway


def runtime_lock_path():
    return default_state_path().with_name('desktop.lock')


class DesktopRuntime:
    def __init__(self, state_path=None, preferred_url='http://127.0.0.1:8482'):
        self.server = None
        self.gateway = None
        self._url = None
        self._external_bootstrap_url = None
        self._activation_candidate = None
        self._server_kwargs = None
        vault_path = (
            BrowserCredentialVault.default_path()
            if state_path is None
            else Path(state_path).with_name("browser-session-v1.dpapi")
        )
        credentials = BrowserCredentialVault(vault_path).load_or_create()
        if state_path is None and self._healthy(preferred_url, credentials.token):
            self._url = preferred_url
        elif state_path is None and self._attach_machine_authority():
            pass
        elif state_path is None and self._active_machine_authority_present():
            raise RuntimeError(
                "active Universal authority bridge is present but does not "
                "support visible browser handoff; restart the bridge through "
                "the authority path before opening a new normal-window session"
            )
        elif state_path is None and self._endpoint_is_listening(preferred_url):
            raise RuntimeError(
                "the visible ArchHub endpoint is occupied by an unverified or "
                "legacy host; complete a controlled authority handoff before "
                "starting a second node-native owner"
            )
        else:
            machine_descriptor_path = (
                Path(state_path).with_name("active-universal-runtime.json")
                if state_path is not None else None
            )
            self._server_kwargs = dict(
                host='127.0.0.1', port=0,
                state_path=state_path or default_state_path(), live_watch=True,
                enable_machine_transport=True,
                machine_descriptor_path=machine_descriptor_path,
                browser_session_credentials=credentials,
            )
            self.server = self._new_server()
            parsed = urlsplit(preferred_url)
            gateway_port = (
                int(parsed.port or 0) if state_path is None else 0
            )
            try:
                self.gateway = RuntimeGateway(
                    host='127.0.0.1',
                    port=gateway_port,
                    admission_timeout=120.0,
                    backend_timeout=60.0,
                    activation_verifier=self._verify_gateway_activation,
                )
            except OSError:
                self.gateway = RuntimeGateway(
                    host='127.0.0.1',
                    port=0,
                    admission_timeout=120.0,
                    backend_timeout=60.0,
                    activation_verifier=self._verify_gateway_activation,
                )

    def _new_server(self):
        if self._server_kwargs is None:
            raise RuntimeError("desktop runtime is attached to an external host")
        return ApplicationServer(**self._server_kwargs)

    def _verify_gateway_activation(self, backend):
        candidate = self._activation_candidate
        if candidate is None:
            raise GatewayError("desktop has no candidate runtime worker")
        if candidate.prove_runtime_backend_generation() != backend:
            raise GatewayError("candidate runtime proof does not match activation")

    @staticmethod
    def _healthy(url, token):
        try:
            state = DesktopRuntime.read_state(url, token=token)
            health = DesktopRuntime.read_universal_health(url, token=token)
            return (
                state.get('ok') is True
                and state.get('valid') is True
                and health.get('ok') is True
                and health.get('runtime') == 'app:archhub'
            )
        except Exception:
            return False

    @staticmethod
    def _endpoint_is_listening(url: str) -> bool:
        """Observe a local endpoint without attaching to or changing its host."""
        parsed = urlsplit(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.port is None
        ):
            return False
        try:
            with socket.create_connection(
                (parsed.hostname, parsed.port), timeout=0.35
            ):
                return True
        except OSError:
            return False

    def _attach_machine_authority(self):
        try:
            client = UniversalRuntimeClient(
                default_runtime_descriptor_path(),
                WindowsDpapiSigningKeyProvider(
                    WindowsDpapiSigningKeyProvider.default_path()
                ),
            )
            handoff = client.browser_handoff()
        except (MachineTransportError, OSError, ValueError):
            return False
        if (
            handoff.get('application') != 'app:archhub'
            or type(handoff.get('server_url')) is not str
            or type(handoff.get('document_url')) is not str
            or '?bootstrap=' not in handoff['document_url']
        ):
            return False
        parsed = urlsplit(handoff['server_url'])
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1':
            return False
        self._url = handoff['server_url']
        self._external_bootstrap_url = handoff['document_url']
        return True

    @staticmethod
    def _active_machine_authority_present():
        try:
            client = UniversalRuntimeClient(
                default_runtime_descriptor_path(),
                WindowsDpapiSigningKeyProvider(
                    WindowsDpapiSigningKeyProvider.default_path()
                ),
            )
            state = client.request(
                'GET', '/api/universal/work', {'projection': 'index'}
            )
        except (MachineTransportError, OSError, ValueError):
            return False
        return (
            state.get('application') == 'app:archhub'
            and state.get('registry') == 'app:governed-work-registry'
        )

    @staticmethod
    def read_state(url, token=None):
        headers = {}
        if token:
            headers['X-ArchHub-Session'] = token
        request = urllib.request.Request(
            url + '/api/state', headers=headers
        )
        return json.loads(urllib.request.urlopen(
            request, timeout=1.0).read())

    @staticmethod
    def read_universal_health(url, token=None):
        headers = {}
        if token:
            headers['X-ArchHub-Session'] = token
        request = urllib.request.Request(
            url + '/api/universal/health', headers=headers
        )
        return json.loads(urllib.request.urlopen(
            request, timeout=1.0).read())

    def start(self):
        if self.server is not None:
            self.server.start()
            self._activation_candidate = self.server
            try:
                self.gateway.start()
                self.gateway.activate(
                    self.server.prove_runtime_backend_generation()
                )
            except Exception:
                self.server.close()
                self.gateway.close()
                raise
        return self

    @property
    def url(self):
        return self._url or self.gateway.url

    @property
    def document_url(self):
        try:
            token = (
                self.server.browser_session_token
                if self.server is not None else None
            )
            schema = self.read_state(
                self.url, token=token
            ).get('schema_version')
        except Exception:
            schema = None
        return self.document_url_for(
            schema or UNIVERSAL_APPLICATION_SCHEMA_VERSION
        )

    def document_url_for(self, schema):
        if self._external_bootstrap_url is not None:
            base = self._external_bootstrap_url
            self._external_bootstrap_url = None
        else:
            base = (
                self.url + '/?bootstrap=' + self.server.browser_bootstrap_token
                if self.server is not None and self.server.browser_bootstrap_token
                else self.url + '/'
            )
        separator = '&' if '?' in base else '?'
        return base + separator + 'schema=' + str(schema)

    def handoff(self):
        """Replace the worker while preserving URL, session, and sole ownership."""
        if self.server is None or self.gateway is None:
            raise RuntimeError("external desktop runtime cannot be handed off here")
        active = self.server.prove_runtime_backend_generation()
        self.gateway.gate.begin_drain(active.generation, timeout=60.0)
        previous = self.server
        previous.close(preserve_browser_session=True)
        replacement = self._new_server().start()
        self._activation_candidate = replacement
        self.gateway.activate(replacement.prove_runtime_backend_generation())
        self.server = replacement
        return self

    def close(self):
        if self.server is not None:
            backend = self.gateway.gate.backend if self.gateway is not None else None
            if backend is not None:
                self.gateway.gate.begin_drain(
                    backend.generation, timeout=60.0
                )
            self.server.close()
        if self.gateway is not None:
            self.gateway.close()


def main():
    from PyQt6.QtCore import QLockFile, QTimer, QUrl
    from PyQt6.QtWidgets import QApplication, QMainWindow, QStackedWidget
    from PyQt6.QtWebEngineCore import QWebEngineProfile
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    app = QApplication(sys.argv)
    app.setApplicationName('ArchHub')
    app.setOrganizationName('ArchHub')
    lock_path = runtime_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        from .desktop_supervisor import write_lifecycle
        write_lifecycle('already-running')
        return 0

    from .desktop_supervisor import write_lifecycle
    write_lifecycle('running')

    profile_root = lock_path.parent / 'web-profile'
    profile_root.mkdir(parents=True, exist_ok=True)
    profile = QWebEngineProfile.defaultProfile()
    profile.setPersistentStoragePath(str(profile_root))
    profile.setCachePath(str(profile_root / 'cache'))

    runtime = DesktopRuntime().start()
    window = QMainWindow()
    window.setWindowTitle('ArchHub')
    window.resize(1480, 920)
    window.setMinimumSize(960, 640)
    stack = QStackedWidget(window)
    window.setCentralWidget(stack)
    window.show()

    loaded_schema = {'value': None}
    pending_schema = {'value': None}
    current_view = {'value': None}

    def stage_schema(schema):
        if not schema or pending_schema['value'] == schema:
            return
        pending_schema['value'] = schema
        candidate = QWebEngineView(stack)
        stack.addWidget(candidate)

        def finished(ok):
            if pending_schema['value'] != schema:
                stack.removeWidget(candidate)
                candidate.deleteLater()
                return
            pending_schema['value'] = None
            if not ok:
                stack.removeWidget(candidate)
                candidate.deleteLater()
                return
            previous = current_view['value']
            current_view['value'] = candidate
            loaded_schema['value'] = schema
            stack.setCurrentWidget(candidate)
            if previous is not None:
                stack.removeWidget(previous)
                previous.deleteLater()

        candidate.loadFinished.connect(finished)

        def terminated(_status, _code):
            if current_view['value'] is candidate:
                loaded_schema['value'] = None
                QTimer.singleShot(250, lambda: stage_schema(schema))

        candidate.page().renderProcessTerminated.connect(terminated)
        candidate.load(QUrl(runtime.document_url_for(schema)))

    initial_schema = runtime.read_state(runtime.url).get(
        'schema_version', UNIVERSAL_APPLICATION_SCHEMA_VERSION)
    stage_schema(initial_schema)

    schema_timer = QTimer(window)
    schema_timer.setInterval(5000)

    def refresh_schema():
        try:
            schema = runtime.read_state(runtime.url).get('schema_version')
        except Exception:
            return
        if schema and schema != loaded_schema['value']:
            stage_schema(schema)

    schema_timer.timeout.connect(refresh_schema)
    schema_timer.start()

    app.aboutToQuit.connect(runtime.close)
    try:
        code = app.exec()
        write_lifecycle('clean', exit_code=code)
        return code
    except Exception as exc:
        write_lifecycle('failed', exit_code=1, detail=type(exc).__name__)
        raise
    finally:
        lock.unlock()


if __name__ == '__main__':
    raise SystemExit(main())
