"""One-click entry points for remote MCP clients.

These clients connect to ArchHub's existing cloud MCP endpoint through their own
UI and OAuth flow. ArchHub opens the client-owned add surface; it never prints a
token or asks the person to paste a URL in Studio.
"""
from __future__ import annotations

from urllib.parse import urlparse


MCP_URL = "https://api.archhub.io/mcp"

_TARGETS = {
    "notion": {
        "provider": "notion",
        "label": "Notion",
        "open_url": "https://www.notion.so/profile/connections",
        "flow": "notion-custom-mcp",
        "prefill": False,
    },
    "gemini": {
        "provider": "gemini",
        "label": "Gemini",
        "open_url": "https://gemini.google.com/settings/connected-apps",
        "flow": "gemini-custom-app",
        "prefill": False,
    },
}


class RemoteMcpClientRefused(ValueError):
    """Unsupported or unsafe remote MCP client request."""


def _safe_https(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username and not parsed.password


def install_target(provider: str) -> dict:
    key = str(provider or "").strip().lower()
    target = _TARGETS.get(key)
    if not target:
        raise RemoteMcpClientRefused("unsupported MCP client")
    if not _safe_https(target["open_url"]):
        raise RemoteMcpClientRefused("MCP client target is not a safe HTTPS URL")
    return {**target, "mcp_url": MCP_URL, "ok": True}


__all__ = ["MCP_URL", "RemoteMcpClientRefused", "install_target"]
