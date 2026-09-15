"""Explicit assembly for the packaged, graph-connected BABOOM projection.

Creating this assembly does not connect a device, start a heartbeat, show a
window, or activate voice.  A caller must pass the normal device-proof
credential provider and perform its controlled runtime handoff separately.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .baboom_native_companion import (
    BaboomNativeCompanionController,
    create_baboom_native_companion_window,
    foreground_application_windows,
)
from .baboom_native_host import BaboomNativeHost, BaboomNativeTransport
from .baboom_visual_assets import BaboomSpriteAtlas, inspect_baboom_sprite_atlas_v2


def default_baboom_sprite_atlas_path() -> Path:
    """Return the packaged transparent BABOOM atlas, never a desktop-local path."""
    path = Path(__file__).resolve().parent / "data" / "baboom" / "spritesheet.png"
    if not path.is_file():
        raise RuntimeError("The packaged BABOOM sprite atlas is unavailable")
    return path


def create_baboom_native_runtime(
    transport: BaboomNativeTransport,
    *,
    external_session_id: str,
    device_credential_provider: Callable[[Mapping[str, object]], Mapping[str, object]],
    atlas_path: Path | None = None,
    position_path: Path | None = None,
) -> tuple[BaboomNativeHost, Any]:
    """Assemble one dormant projection; the graph remains the only authority."""
    host = create_baboom_native_host(
        transport,
        external_session_id=external_session_id,
        device_credential_provider=device_credential_provider,
    )
    return host, create_baboom_native_projection(
        host, atlas_path=atlas_path, position_path=position_path
    )


def create_baboom_native_host(
    transport: BaboomNativeTransport,
    *,
    external_session_id: str,
    device_credential_provider: Callable[[Mapping[str, object]], Mapping[str, object]],
) -> BaboomNativeHost:
    """Prepare the transport host without constructing any Qt object."""
    return BaboomNativeHost(
        transport,
        external_session_id=external_session_id,
        device_credential_provider=device_credential_provider,
        activity_provider=foreground_application_windows,
    )


def create_baboom_native_projection(
    host: BaboomNativeHost,
    *,
    atlas_path: Path | None = None,
    position_path: Path | None = None,
) -> Any:
    """Build the existing companion on the caller's Qt GUI thread."""
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        raise RuntimeError("BABOOM projection requires the application GUI thread")
    selected_path = atlas_path or default_baboom_sprite_atlas_path()
    atlas: BaboomSpriteAtlas = inspect_baboom_sprite_atlas_v2(selected_path)
    controller = BaboomNativeCompanionController(host, atlas)
    return create_baboom_native_companion_window(
        controller, position_path=position_path
    )


__all__ = [
    "create_baboom_native_runtime",
    "create_baboom_native_host",
    "create_baboom_native_projection",
    "default_baboom_sprite_atlas_path",
]
