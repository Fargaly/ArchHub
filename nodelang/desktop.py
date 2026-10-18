"""Desktop entry aliases and physical dependencies for the installed launcher.

Every supported launch executes launch_archhub_test.py, including module callers.
Importing this module never constructs an application or opens a window.
"""
from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys
from .clean_boot_surface import BootSurface


def create_boot_surface(host, port, *, expected):
    """Compose the one desktop boot transport before its application owner opens."""
    return BootSurface(host, port, expected=expected)

def create_workshop_transport(state_directory):
    """Compose the packaged transport without starting a worker or another owner."""
    from .session_link_transport import SessionLinkTransport

    if getattr(sys, 'frozen', False):
        node_executable = None  # Transport resolves the bundled runtime only.
    else:
        declared = os.environ.get('SESSION_LINK_NODE')
        bundled = Path(__file__).resolve().parents[1] / 'runtime' / 'node.exe'
        if declared:
            node_executable = declared
        elif bundled.is_file():
            node_executable = bundled
        else:
            # Source-only callers must explicitly supply their installed toolchain.
            return None
    return SessionLinkTransport(
        node_executable=node_executable,
        state_dir=Path(state_directory).resolve() / 'session-link',
        # Starting ArchHub from an agent shell does not attach that agent.
        # Product dispatch receives host authority only through attach_host.
        env={'CODEX_APP_TOOLS_PIPE_PATH': '', 'CODEX_THREAD_ID': ''},
    )


def create_social_execution_arguments():
    """One physical host/custody composition for both desktop entry points."""
    from .social_http_host import SocialHttpHost
    from .social_custody import social_credential, social_account_binding_verifier

    return {'social_execution_host': SocialHttpHost(social_credential),
            'social_account_binding_verifier': social_account_binding_verifier}



def bind_coordination_surface(server, state_directory):
    """Attach the old coordination API to this owner's very same CellStore.

    There is no second opener or ApplicationServer. Transport keys secure
    commands; cloud_session remains the source of signed-in account identity.
    """
    import threading
    from urllib.parse import urlsplit
    from .persistence import selected_application_generation, _application_generation_directory
    if not selected_application_generation(server.universal_state_path):
        return None
    from .runtime_caller_capability import WindowsDpapiCallerKeyStore
    from .clean_coordination_host import CleanCoordinationHost
    from .clean_coordination_service import build_bound_service
    from .clean_office_adapter import invoke as office
    from .clean_revit_adapter import invoke as revit
    from .clean_model_adapter import CleanModelAdapter
    database = Path(server.universal_state_path)
    generation = _application_generation_directory(database)
    authority = getattr(server.universal_store, '_signed_commit_authority', None)
    if authority is None:
        raise ValueError('selected application has no bound signed commit owner')
    adapters = {'revit': revit, 'word': office, 'excel': office, 'powerpoint': office,
                'model': CleanModelAdapter(server.model_execution_broker)}
    def reach_host(operation, arguments):
        host = str(operation).split('.', 1)[0]
        if host not in adapters:
            raise ValueError('this runtime declares no adapter for ' + host)
        return adapters[host](operation, arguments)
    from . import commit_intent
    with commit_intent.declare(commit_intent.MIGRATION, actor='app:archhub',
            reason='install changed coordination catalogue in the one application owner'):
        graph_host = CleanCoordinationHost(authority,
            WindowsDpapiCallerKeyStore(WindowsDpapiCallerKeyStore.default_path()),
            host_invoker=reach_host, runtime_root=generation.parent.parent)
    endpoint = os.environ.get('ARCHHUB_COORDINATION_ENDPOINT', 'http://127.0.0.1:8474/coordination')
    parsed = urlsplit(endpoint)
    if parsed.hostname != '127.0.0.1' or parsed.scheme != 'http' or parsed.path != '/coordination':
        raise ValueError('coordination endpoint must be a declared loopback endpoint')
    service = build_bound_service(graph_host, port=parsed.port if parsed.port is not None else 8474)
    server._coordination_surface = service
    thread = threading.Thread(target=service.serve_forever, name='ArchHub coordination surface', daemon=True)
    thread.start()
    server._coordination_thread = thread
    return service


def main():
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "launch_archhub_test.py"),
                   run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
