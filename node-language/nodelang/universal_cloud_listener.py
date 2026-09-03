"""Explicit TLS listener factory for a graph-governed Universal cloud gateway.

The FastAPI gateway owns only a bounded physical transport surface.  This
module owns only the equally physical HTTPS listener configuration.  It does
not create a graph, issue identity, provision a device, retain a token, or
start a process during construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import ssl

import uvicorn

from .universal_cloud_gateway import UniversalCloudGateway


_HOST = re.compile(
    r"^(?:\d{1,3}(?:\.\d{1,3}){3}|[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)$"
)


@dataclass(frozen=True, slots=True)
class UniversalCloudTlsListener:
    """Non-secret direct-TLS listener parameters supplied by deployment."""

    host: str
    port: int
    certificate_file: Path
    private_key_file: Path


def _regular_file(value: Path, label: str) -> Path:
    path = Path(value)
    if not path.is_file():
        raise ValueError("cloud TLS %s must name a regular file" % label)
    return path.resolve()


def validate_universal_cloud_tls_listener(
    listener: UniversalCloudTlsListener,
) -> UniversalCloudTlsListener:
    """Reject listener shapes that would hide transport behavior or secrets."""
    if not isinstance(listener, UniversalCloudTlsListener):
        raise TypeError("Universal cloud listener configuration is required")
    host = listener.host
    if (
        not isinstance(host, str)
        or host != host.strip()
        or not _HOST.fullmatch(host)
    ):
        raise ValueError("cloud TLS host is invalid")
    if not isinstance(listener.port, int) or not 1 <= listener.port <= 65535:
        raise ValueError("cloud TLS port is invalid")
    certificate = _regular_file(listener.certificate_file, "certificate")
    private_key = _regular_file(listener.private_key_file, "private key")
    if certificate == private_key:
        raise ValueError("cloud TLS certificate and private key must be separate files")
    return UniversalCloudTlsListener(host, listener.port, certificate, private_key)


def create_universal_cloud_tls_server(
    gateway: UniversalCloudGateway,
    listener: UniversalCloudTlsListener,
) -> uvicorn.Server:
    """Build, but do not start, the direct-TLS runtime server.

    Uvicorn reload/workers would fork or reload process-held Agent Session and
    native-login capabilities.  Cross-process durability belongs to the graph
    deployment, so this physical adapter is intentionally a single process.
    A terminating proxy is not supported here: proxy headers would become a
    second unverified identity boundary ahead of DPoP.
    """
    if not isinstance(gateway, UniversalCloudGateway):
        raise TypeError("Universal cloud TLS listener requires a gateway")
    checked = validate_universal_cloud_tls_listener(listener)
    config = uvicorn.Config(
        gateway.app,
        host=checked.host,
        port=checked.port,
        access_log=False,
        log_level="warning",
        use_colors=False,
        reload=False,
        workers=1,
        proxy_headers=False,
        forwarded_allow_ips="",
        server_header=False,
        date_header=False,
        timeout_keep_alive=5,
        ssl_certfile=str(checked.certificate_file),
        ssl_keyfile=str(checked.private_key_file),
        ssl_version=ssl.PROTOCOL_TLS_SERVER,
    )
    return uvicorn.Server(config)


__all__ = [
    "UniversalCloudTlsListener",
    "create_universal_cloud_tls_server",
    "validate_universal_cloud_tls_listener",
]
