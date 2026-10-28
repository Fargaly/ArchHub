"""Desktop entry aliases and physical dependencies for the installed launcher.

Every supported launch executes nodelang/launcher.py, including module callers.
Importing this module never constructs an application or opens a window.
"""
from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys
from .clean_boot_surface import BootSurface


def arm_update(state_directory, application_directory, database_path, content_path, *, expected_build):
    """Compose the launcher's existing recovery owner after its final close."""
    from .application_update_recovery import arm_update as arm_closed_update

    return arm_closed_update(state_directory, application_directory, database_path, content_path,
                             expected_build=expected_build)


def create_boot_surface(host, port, *, expected):
    """Compose the one desktop boot transport before its application owner opens."""
    return BootSurface(host, port, expected=expected)

def create_workshop_transport(state_directory):
    """Compose the packaged transport without starting a worker or another owner."""
    from .workshop_transport import WorkshopTransport

    if getattr(sys, 'frozen', False):
        node_executable = None  # Transport resolves the bundled runtime only.
    else:
        declared = os.environ.get('WORKSHOP_NODE')
        bundled = Path(__file__).resolve().parents[1] / 'runtime' / 'node.exe'
        if declared:
            node_executable = declared
        elif bundled.is_file():
            node_executable = bundled
        else:
            # Source-only callers must explicitly supply their installed toolchain.
            return None
    return WorkshopTransport(
        node_executable=node_executable,
        state_dir=Path(state_directory).resolve() / 'workshop',
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
    """Attach local coordination to the desktop's existing application owner."""
    import threading
    from urllib.parse import urlsplit
    from .clean_coordination_host import CleanCoordinationHost
    from .clean_coordination_service import build_bound_service
    existing = getattr(server, '_coordination_surface', None)
    if existing is not None:
        return existing
    graph_host = CleanCoordinationHost(server)
    endpoint = os.environ.get('ARCHHUB_COORDINATION_ENDPOINT', 'http://127.0.0.1:8474/coordination')
    parsed = urlsplit(endpoint)
    if (parsed.hostname != '127.0.0.1' or parsed.scheme != 'http' or parsed.path != '/coordination'
            or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment):
        raise ValueError('coordination endpoint must be a declared loopback endpoint')
    service = build_bound_service(graph_host, port=parsed.port if parsed.port is not None else 8474)
    server._coordination_surface = service
    thread = threading.Thread(target=service.serve_forever, name='ArchHub coordination surface', daemon=True)
    thread.start()
    server._coordination_thread = thread
    return service


def main():
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "nodelang/launcher.py"),
                   run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
