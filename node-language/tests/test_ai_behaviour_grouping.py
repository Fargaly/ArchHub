"""ai_behaviour grouping + per-host defaults.

v1.0.2 refactor — `_DEFAULT_RULES` flat tuple → per-host `_FAMILY_DEFAULTS`
dict + `tools_grouped_by_host()` helper. These tests pin the behaviour
the Settings UI relies on so a future tool-registry change can't quietly
break the dropdowns.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


class TestFamilyDefaults:
    def test_revit_execute_is_ask(self):
        from ai_behaviour import _default_policy_for
        assert _default_policy_for("revit_execute_csharp") == "ask"

    def test_revit_ping_is_allow(self):
        from ai_behaviour import _default_policy_for
        assert _default_policy_for("revit_ping") == "allow"

    def test_outlook_list_is_allow(self):
        from ai_behaviour import _default_policy_for
        assert _default_policy_for("outlook_list_inbox") == "allow"

    def test_outlook_set_categories_is_ask(self):
        from ai_behaviour import _default_policy_for
        assert _default_policy_for("outlook_set_categories") == "ask"

    def test_outlook_execute_python_is_ask(self):
        from ai_behaviour import _default_policy_for
        # COM escape hatch — never silently allow.
        assert _default_policy_for("outlook_execute_python") == "ask"

    def test_unknown_family_uses_generic_rules(self):
        from ai_behaviour import _default_policy_for
        # New host family not in _FAMILY_DEFAULTS — generic suffix rules
        # should still classify execute_python as ask.
        assert _default_policy_for("rhino_execute_python") == "ask"
        assert _default_policy_for("rhino_list_layers") == "allow"

    def test_unknown_suffix_falls_through_to_allow(self):
        from ai_behaviour import _default_policy_for
        # A completely unrecognised pattern is permissive — user can
        # tighten via Settings if they care.
        assert _default_policy_for("random_thing_that_doesnt_exist") == "allow"


class TestFamilyHelpers:
    def test_family_of_extracts_prefix(self):
        from ai_behaviour import _family_of
        assert _family_of("revit_ping") == "revit"
        assert _family_of("outlook_list_inbox") == "outlook"
        assert _family_of("nothing") == "nothing"

    def test_suffix_of_extracts_rest(self):
        from ai_behaviour import _suffix_of
        assert _suffix_of("revit_ping") == "ping"
        assert _suffix_of("outlook_list_inbox") == "list_inbox"
        assert _suffix_of("nothing") == ""


class TestGroupedByHost:
    def test_returns_dict_keyed_by_family(self):
        from ai_behaviour import tools_grouped_by_host
        g = tools_grouped_by_host()
        assert isinstance(g, dict)
        # We always have revit + outlook tools registered at module load.
        assert "revit" in g
        assert "outlook" in g

    def test_each_tool_carries_metadata(self):
        from ai_behaviour import tools_grouped_by_host
        g = tools_grouped_by_host()
        for tools in g.values():
            for t in tools:
                assert "name" in t
                assert "description" in t
                assert t["policy"] in ("allow", "ask", "deny")
                assert t["default"] in ("allow", "ask", "deny")
                assert isinstance(t["overridden"], bool)

    def test_preferred_order_revit_first(self):
        from ai_behaviour import tools_grouped_by_host
        g = tools_grouped_by_host()
        keys = list(g.keys())
        # revit comes before outlook in the preferred order — confirms
        # the explicit ordering rather than insertion order.
        assert keys.index("revit") < keys.index("outlook")


class TestHostDisplayLabel:
    def test_known_families(self):
        from ai_behaviour import host_display_label
        assert host_display_label("revit") == "Revit"
        assert host_display_label("acad") == "AutoCAD"
        assert host_display_label("max") == "3ds Max"
        assert host_display_label("outlook") == "Outlook (classic)"
        assert host_display_label("_local") == "ArchHub (local)"

    def test_unknown_family_title_cased(self):
        from ai_behaviour import host_display_label
        assert host_display_label("rhino") == "Rhino"
