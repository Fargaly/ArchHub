"""Read-only BABOOM surface sourced from the active Universal runtime."""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Protocol


RUNTIME_PROJECTION_TIMEOUT_SECONDS = 3.0


class _RuntimeStatusClient(Protocol):
    def request(
        self,
        method: str,
        path: str,
        body: dict[str, object] | None = None,
        *,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        ...


def _canonical_node_authority_root() -> Path:
    product_root = Path(__file__).resolve().parents[3]
    root = product_root / "13.NODE-LANGUAGE"
    if not root.is_dir():
        raise FileNotFoundError(str(root))
    text = str(root)
    if text not in sys.path:
        sys.path.insert(0, text)
    return root


def _active_runtime_client() -> _RuntimeStatusClient:
    _canonical_node_authority_root()
    from nodelang.application_machine_transport import (  # type: ignore
        UniversalRuntimeClient,
        default_runtime_descriptor_path,
    )
    from nodelang.cell_secret_keys import (  # type: ignore
        WindowsDpapiSigningKeyProvider,
    )

    provider = WindowsDpapiSigningKeyProvider(
        WindowsDpapiSigningKeyProvider.default_path()
    )
    return UniversalRuntimeClient(default_runtime_descriptor_path(), provider)


def _runtime_baboom_context(
    runtime_client: _RuntimeStatusClient | None = None,
) -> dict[str, object]:
    client = runtime_client or _active_runtime_client()
    return client.request(
        "GET",
        "/api/universal/baboom-context",
        response_timeout_seconds=RUNTIME_PROJECTION_TIMEOUT_SECONDS,
    )


def baboom_context_projection(
    *,
    runtime_client: _RuntimeStatusClient | None = None,
) -> dict[str, Any]:
    """Return the canonical BABOOM context lens without opening a side store."""
    context = _runtime_baboom_context(runtime_client)
    work = context.get("work")
    if not isinstance(work, dict):
        raise RuntimeError("Universal runtime did not expose BABOOM work context")
    workshop = context.get("workshop")
    if not isinstance(workshop, dict):
        raise RuntimeError("Universal runtime did not expose BABOOM workshop context")
    return {
        "ok": True,
        "node_native": True,
        "mode": "canonical-graph-projection",
        "authority": "Universal Cell graph runtime",
        "transport_source": "10.PRODUCT/13.NODE-LANGUAGE",
        "context_lens": context.get("context_lens"),
        "root_id": context.get("context_lens"),
        "revision": context.get("revision"),
        "work_counts": work,
        "work_total": work.get("total", 0),
        "workshop": workshop,
        "attention": context.get("attention", {}),
        "presence": context.get("presence", {}),
        "device": context.get("device", {}),
        "suggestion": context.get("suggestion", ""),
        "source": "active-universal-runtime",
    }


__all__ = ["baboom_context_projection"]
