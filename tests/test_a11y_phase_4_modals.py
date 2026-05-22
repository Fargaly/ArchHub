"""AgDR-0015 Phase 4 — modal a11y (ARIA roles + focus trap).

Tests pin: every Phase-4 modal carries `role="dialog"` +
`aria-modal="true"` + `aria-labelledby="<id>"`. The `_useModalA11y`
hook is wired to each modal's panel ref so initial focus lands,
Tab cycles inside, and Escape closes.
"""
from __future__ import annotations

import re
from pathlib import Path

JSX = Path(__file__).resolve().parents[1] / "app" / "web_ui" / "studio-lm.jsx"


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


def test_modal_a11y_hook_defined():
    """The shared modal-a11y hook lives once + is exported via
    closure to every modal. Pins: initial-focus, Tab cycle, Escape."""
    src = _src()
    assert "_useModalA11y" in src
    # Tab cycle implementation token (we early-return when NOT Tab).
    assert "e.key !== 'Tab'" in src
    # Escape-to-close branch.
    assert "e.key === 'Escape'" in src


def test_group_dialog_has_dialog_role():
    src = _src()
    assert 'aria-labelledby="lm-group-dialog-title"' in src
    assert 'id="lm-group-dialog-title"' in src


def test_save_skill_dialog_has_dialog_role():
    src = _src()
    assert 'aria-labelledby="lm-save-skill-dialog-title"' in src
    assert 'id="lm-save-skill-dialog-title"' in src


def test_create_node_modal_has_dialog_role():
    src = _src()
    assert 'aria-labelledby="lm-create-node-modal-title"' in src
    assert 'id="lm-create-node-modal-title"' in src


def test_ai_node_modal_has_dialog_role():
    src = _src()
    assert 'aria-labelledby="lm-ai-node-modal-title"' in src
    assert 'id="lm-ai-node-modal-title"' in src


def test_at_least_four_dialog_roles_present():
    """Pin the floor count so future modal additions either get
    wired up OR explicitly document why they're out of scope."""
    src = _src()
    count = src.count('role="dialog"')
    assert count >= 4, (
        f"Phase-4 modals expect ≥4 role=\"dialog\" attrs, got {count}")
    # Same number of aria-modal="true" + aria-labelledby anchors.
    assert src.count('aria-modal="true"') >= 4
    assert src.count('aria-labelledby=') >= 4


def test_every_dialog_role_has_aria_modal():
    """A `role="dialog"` without `aria-modal="true"` is an a11y bug —
    screen readers don't trap focus for non-modal dialogs. Per-line
    check guards against drift."""
    src = _src()
    lines = src.splitlines()
    missing: list[tuple[int, str]] = []
    for i, line in enumerate(lines, 1):
        if 'role="dialog"' in line:
            # Check the next 3 lines for aria-modal (multi-line JSX
            # often splits attrs across lines).
            window = "\n".join(lines[i - 1:i + 3])
            if 'aria-modal="true"' not in window:
                missing.append((i, line.strip()[:120]))
    assert not missing, (
        "role=\"dialog\" missing aria-modal=\"true\":\n" +
        "\n".join(f"  L{n}: {s}" for n, s in missing))


def test_modal_panels_attach_ref_to_hook():
    """The hook returns a ref; each modal must spread `ref={modalRef}`
    onto its inner panel div. Without the ref, focus trap is dead."""
    src = _src()
    # Each of the 4 modals must call _useModalA11y exactly once.
    hook_calls = src.count("_useModalA11y(")
    assert hook_calls >= 4, (
        f"expected ≥4 _useModalA11y calls (one per modal), got {hook_calls}")
    # And the ref is attached to the panel.
    assert "ref={modalRef}" in src
