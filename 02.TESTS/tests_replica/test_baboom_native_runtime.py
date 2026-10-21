"""Courts for dormant packaged BABOOM runtime assembly."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from nodelang.baboom_native_runtime import (
    create_baboom_native_runtime,
    default_baboom_sprite_atlas_path,
)


class _Transport:
    def __init__(self) -> None:
        self.agent_session_root = ""
        self.bind_calls = 0

    def bind_agent_session(self, **kwargs):
        self.bind_calls += 1
        raise AssertionError("dormant BABOOM assembly must not bind a session")


def test_packaged_baboom_runtime_uses_the_product_atlas_and_does_not_start():
    app = QApplication.instance() or QApplication([])
    atlas = default_baboom_sprite_atlas_path()
    assert atlas.name == "spritesheet.png"
    transport = _Transport()

    host, window = create_baboom_native_runtime(
        transport,
        external_session_id="baboom-runtime-assembly-court",
        device_credential_provider=lambda challenge: {"proof": "approved"},
    )
    try:
        assert host.running is False
        assert transport.bind_calls == 0
        assert not window.isVisible()
        app.processEvents()
    finally:
        window.close()
