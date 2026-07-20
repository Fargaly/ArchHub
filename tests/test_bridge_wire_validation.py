"""Canvas wire-drop validation keeps open custom type identities."""
from __future__ import annotations

import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def test_bridge_accepts_matching_custom_types_and_rejects_mismatch():
    from bridge import ArchHubBridge

    can_wire = ArchHubBridge.can_wire
    facade = "founder.geometry.facade-panel"
    assert can_wire(None, facade, facade, False, False)
    assert not can_wire(None, facade, "founder.image.material", False, False)


def test_bridge_accepts_explicit_custom_type_family():
    from bridge import ArchHubBridge

    assert ArchHubBridge.can_wire(
        None, "archhub.geometry.mesh", "archhub.geometry.*", False, False)
