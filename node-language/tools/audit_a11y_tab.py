"""Audit the Settings dialog — tab CONTRACT + sidebar accessibility.

Two complementary checks, both against one headless SettingsDialog:

A. 12-TAB BACK-COMPAT CONTRACT (`dlg._tabs` shim). The dialog was rebuilt
   to a 5-section sidebar, but a flat `_tabs` shim preserves the historical
   tab order that JSX/bridge deep-links + founder muscle-memory rely on.
   AccessibilityTab is pinned at index 9, between Shortcuts(8) and About(10).
   `Account` was appended after About on 2026-05-31 -> 12 tabs (was 11), and
   `tests/test_settings_dialog_tabs.py` pins `len(SettingsDialog.TABS) == 12`.

B. SIDEBAR ACCESSIBILITY (`dlg._nav`). The visible 5-section QListWidget:
   each nav row exposes a CLEAN accessible name (the section title, NOT the
   decorative glyph prefix), the list carries an accessibleName, every
   back-compat `focus_section()` deep-link keyword resolves (with a bogus
   keyword rejected), and the Accessibility page is reachable with named
   controls.

Boots a transient, unparented QApplication + SettingsDialog headless.
Exit 0 on green, 1 on any deviation. Safe to run alongside a live app.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# settings_dialog uses sibling-module imports (`from secrets_store import …`)
# expected to resolve from inside `app/`. Mirror that: app/ first, then repo.
sys.path.insert(0, str(REPO / "app"))
sys.path.insert(0, str(REPO))

# Headless render so this never pops a window or needs a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.settings_dialog import SettingsDialog  # noqa: E402

# Decorative glyphs used as sidebar icons — must NOT appear in accessible text.
_GLYPHS = "◐◈✦⛓⚙◑◒◓"

# The pinned tab CONTRACT (back-compat flat order). 12 tabs since 2026-05-31.
_EXPECTED_TAB_COUNT = 12
_A11Y_TAB_INDEX = 9   # Accessibility, between Shortcuts(8) and About(10)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    dlg = SettingsDialog()
    ok = True

    def check(cond: bool, msg: str) -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
        if not cond:
            ok = False

    # ── A. 12-tab back-compat contract (dlg._tabs) ───────────────────────
    print("tab contract (dlg._tabs back-compat shim):")
    tabs = getattr(dlg, "_tabs", None)
    if tabs is None:
        check(False, "_tabs back-compat shim present")
    else:
        count = tabs.count()
        labels = [tabs.tabText(i) for i in range(count)]
        print(f"  tab_count={count}")
        for i, lbl in enumerate(labels):
            print(f"    {i}: {lbl}")
        a11y_idx = labels.index("Accessibility") if "Accessibility" in labels else -1
        print(f"  accessibility_index={a11y_idx}")
        ordered = (
            len(labels) > _A11Y_TAB_INDEX + 1
            and labels[8] == "Shortcuts"
            and labels[9] == "Accessibility"
            and labels[10] == "About"
        )
        print(f"  between_shortcuts_and_about={ordered}")
        check(count == _EXPECTED_TAB_COUNT,
              f"tab contract has {_EXPECTED_TAB_COUNT} tabs")
        check(a11y_idx == _A11Y_TAB_INDEX,
              f"Accessibility at index {_A11Y_TAB_INDEX}")
        check(ordered,
              "Accessibility sits between Shortcuts(8) and About(10)")
        # The shim must mirror the canonical SettingsDialog.TABS the pytest pins.
        check(len(getattr(SettingsDialog, "TABS", [])) == _EXPECTED_TAB_COUNT,
              f"SettingsDialog.TABS has {_EXPECTED_TAB_COUNT} entries")

    # ── B. Sidebar accessibility (dlg._nav) ──────────────────────────────
    nav = getattr(dlg, "_nav", None)
    print(f"\nsidebar a11y (dlg._nav): present={nav is not None}")
    if nav is None:
        check(False, "sidebar _nav present")
    else:
        rows = nav.count()
        expected = [s[0] for s in SettingsDialog.SECTIONS]  # section titles
        print(f"  nav_rows={rows} expected={len(expected)}")
        check(rows == len(expected), f"nav has {len(expected)} section rows")
        check(bool(nav.accessibleName()),
              f"nav list has accessibleName ({nav.accessibleName()!r})")

        print("  nav rows — accessible name must be the clean title (no glyph):")
        for i in range(rows):
            it = nav.item(i)
            disp = it.text()
            acc = it.data(Qt.ItemDataRole.AccessibleTextRole)
            acc = (acc if isinstance(acc, str) else "") or ""
            title = expected[i] if i < len(expected) else "?"
            clean = bool(acc) and not any(g in acc for g in _GLYPHS)
            print(f"    row {i}: display={disp!r} accessible={acc!r}")
            check(clean and acc == title,
                  f"row {i} announces clean {title!r} (not the glyph)")

        # Deep-link integrity: every back-compat keyword resolves.
        print("  focus_section deep-links:")
        keywords = sorted(set(getattr(SettingsDialog, "SECTION_TO_TAB", {}).keys()))
        for kw in keywords:
            check(bool(dlg.focus_section(kw)), f"focus_section({kw!r}) resolves")
        check(dlg.focus_section("zzz_not_a_section") is False,
              "focus_section rejects an unknown keyword")

        # Accessibility page reachable + its controls named.
        print("  accessibility page:")
        check(dlg.focus_section("accessibility") is True,
              "Accessibility page reachable via focus_section")
        a11y = getattr(dlg, "_tab_widgets", {}).get("Accessibility")
        if a11y is not None:
            named = []
            for attr in ("_font_pick", "_contrast_pick", "_reduce_motion",
                         "_sr_opt", "_save_btn"):
                w = getattr(a11y, attr, None)
                if w is not None:
                    named.append(bool(w.accessibleName()))
            check(bool(named) and all(named),
                  f"Accessibility controls carry accessibleName ({sum(named)}/{len(named)})")
        else:
            check(False, "Accessibility tab widget present")

    print(f"\nPASS={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
