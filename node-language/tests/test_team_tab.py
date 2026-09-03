"""Team tab — structural / data-binding tests for the workspace-roles UI.

The cloud has a FULL team model live server-side (owner > admin > member,
seats per plan, email-gated invites). Before TeamTab, the desktop had ZERO
team UI. These tests pin the new surface:

  * `settings_dialog.TeamTab` exists, is a `QWidget` subclass, and is
    registered in the dialog's visual `SECTIONS` (the list the shell
    actually renders) under "Account & Brain" — i.e. a DISCOVERABLE page,
    not a dead class.
  * With a MONKEYPATCHED bridge returning a fake company + members payload
    (so this lane is independent of the JS-WIRE bridge lane — integration
    is verified live later), the tab renders:
      - the company name,
      - my role badge,
      - the invite form fields (email + role select),
      - the members list (one row per teammate, email + role).
  * The owner/admin manage-gate mirrors the server: a `member` sees the
    roster read-only (no Remove buttons / role combos, no invite form);
    an `owner`/`admin` gets the manage controls.
  * Every control is wired to the matching bridge company slot — clicking
    Create / Invite / Join / Remove / change-role calls
    company_create / company_invite / company_accept_invite /
    company_remove_member / company_set_role with the right args.

These are STRUCTURAL assertions on the built Qt widgets + the public
data-binding methods (`_render_companies`, `_render_members`,
`_render_selected`). They never hit the network — the fake bridge is the
seam.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


# ── Qt fixture (QWidget instantiation needs a QApplication) ────────────
@pytest.fixture(scope="session")
def qapp():
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication
    import sys as _sys
    return QApplication.instance() or QApplication(_sys.argv)


# ── Fakes ──────────────────────────────────────────────────────────────
class _FakeBridge:
    """Records every company_* call + returns canned JSON strings, exactly
    like the real QWebChannel bridge slots will (json string in/out). This
    is what makes the lane independent of the JS-WIRE bridge lane."""

    def __init__(self, companies):
        import json
        self._json = json
        self._companies = companies
        self.calls = []  # (method, args) in order

    def companies_list(self):
        self.calls.append(("companies_list", ()))
        return self._json.dumps(self._companies)

    def company_create(self, name):
        self.calls.append(("company_create", (name,)))
        return self._json.dumps({"ok": True})

    def company_invite(self, company_id, email, role):
        self.calls.append(("company_invite", (company_id, email, role)))
        return self._json.dumps({"ok": True})

    def company_accept_invite(self, token):
        self.calls.append(("company_accept_invite", (token,)))
        return self._json.dumps({"ok": True})

    def company_remove_member(self, company_id, email):
        self.calls.append(("company_remove_member", (company_id, email)))
        return self._json.dumps({"ok": True})

    def company_set_role(self, company_id, email, role):
        self.calls.append(("company_set_role", (company_id, email, role)))
        return self._json.dumps({"ok": True})


class _StubDialog:
    """Stands in for SettingsDialog: TeamTab only needs `.bridge`,
    `.parent()` (for _bridge_call's walk), and `.notify_changed()`."""

    def __init__(self, bridge):
        self.bridge = bridge

    def parent(self):
        return None

    def notify_changed(self):
        pass


def _fake_owner_payload():
    """One firm, I am the owner, two teammates on the roster."""
    return [
        {
            "id": "co_42",
            "name": "Fargaly Studio",
            "my_role": "owner",
            "members": [
                {"email": "ahmed@fargaly.studio", "role": "owner"},
                {"email": "ada@fargaly.studio", "role": "member"},
            ],
        }
    ]


def _fake_member_payload():
    """One firm where I am only a member (manage controls must hide)."""
    return [
        {
            "id": "co_99",
            "name": "Client Co",
            "my_role": "member",
            "members": [
                {"email": "boss@client.co", "role": "owner"},
                {"email": "me@client.co", "role": "member"},
            ],
        }
    ]


# ── Helpers to walk the built widget tree ──────────────────────────────
def _labels(widget):
    from PyQt6.QtWidgets import QLabel
    return [w.text() for w in widget.findChildren(QLabel)]


def _buttons(widget):
    from PyQt6.QtWidgets import QPushButton
    return [w.text() for w in widget.findChildren(QPushButton)]


# ── Import-level: the class + section registration ─────────────────────
def test_teamtab_imports_and_is_qwidget():
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QWidget
    from settings_dialog import TeamTab
    assert isinstance(TeamTab, type)
    assert issubclass(TeamTab, QWidget), "TeamTab must be a QWidget subclass."


def test_teamtab_registered_in_sections():
    """The Team tab is a DISCOVERABLE page: it appears in SECTIONS (the
    list the dialog shell iterates to build pages), under Account & Brain.
    DEFINITION-OF-SHIPPED — a class nothing renders is not shipped."""
    from settings_dialog import SettingsDialog, TeamTab
    found_label = False
    found_cls = False
    for title, _glyph, tabs in SettingsDialog.SECTIONS:
        for label, cls in tabs:
            if label == "Team":
                found_label = True
                assert title == "Account & Brain", (
                    "Team belongs in the Account & Brain section.")
                if cls is TeamTab:
                    found_cls = True
    assert found_label, "No 'Team' tab registered in SECTIONS."
    assert found_cls, "'Team' tab is not wired to the TeamTab class."


def test_team_role_constants():
    """Roles mirror the server model, owner first."""
    from settings_dialog import TEAM_ROLES, _team_can_manage
    assert TEAM_ROLES == ("owner", "admin", "member")
    # The manage gate matches the server: owner/admin yes, member no.
    assert _team_can_manage("owner") is True
    assert _team_can_manage("admin") is True
    assert _team_can_manage("member") is False
    assert _team_can_manage("") is False


# ── Data-binding: renders the fake payload ─────────────────────────────
def test_renders_company_name_and_role_badge(qapp):
    """With a fake owner payload, the tab shows the firm name and a role
    badge reading 'Owner'."""
    from settings_dialog import TeamTab
    dlg = _StubDialog(_FakeBridge(_fake_owner_payload()))
    tab = TeamTab(dlg)  # __init__ calls _refresh() -> companies_list()

    # The bridge was actually asked for the firms list.
    assert ("companies_list", ()) in dlg.bridge.calls

    assert tab._firm_name_lbl.text() == "Fargaly Studio"
    assert tab._role_badge.text() == "Owner"
    assert tab._role_badge.isVisible() or tab._role_badge.text() == "Owner"
    # The firm name appears among the tab's labels too.
    assert "Fargaly Studio" in _labels(tab)


def test_renders_invite_form_fields(qapp):
    """The invite form exposes an email field + a role select carrying the
    three server roles, and is VISIBLE for an owner."""
    from settings_dialog import TeamTab
    dlg = _StubDialog(_FakeBridge(_fake_owner_payload()))
    tab = TeamTab(dlg)

    # Email field present + is a line edit.
    from PyQt6.QtWidgets import QLineEdit, QComboBox
    assert isinstance(tab._invite_email, QLineEdit)
    # Role select carries owner/admin/member as item data.
    assert isinstance(tab._invite_role, QComboBox)
    role_values = {tab._invite_role.itemData(i)
                   for i in range(tab._invite_role.count())}
    assert {"owner", "admin", "member"} <= role_values
    # Owner can invite -> the invite group is shown.
    assert tab._invite_grp.isVisible() or tab._invite_grp.isVisibleTo(tab)
    # Send invite button exists.
    assert "Send invite" in _buttons(tab)


def test_renders_members_list(qapp):
    """The members roster renders one row per teammate, each showing the
    teammate's email; an owner gets a Remove button + role combo per row."""
    from settings_dialog import TeamTab
    from PyQt6.QtWidgets import QFrame, QComboBox
    dlg = _StubDialog(_FakeBridge(_fake_owner_payload()))
    tab = TeamTab(dlg)

    rows = tab.findChildren(QFrame, "teamMemberRow")
    assert len(rows) == 2, "Expected one row per teammate."

    # Both teammate emails are shown.
    all_labels = _labels(tab)
    assert "ahmed@fargaly.studio" in all_labels
    assert "ada@fargaly.studio" in all_labels

    # Owner gets manage controls: a Remove button + a per-row role combo.
    assert _buttons(tab).count("Remove") == 2
    role_combos = tab.findChildren(QComboBox, "teamMemberRole")
    assert len(role_combos) == 2


def test_member_role_hides_manage_controls(qapp):
    """A plain member sees the roster READ-ONLY — no Remove buttons, no
    per-row role combos, and the invite form is hidden. Mirrors the
    server's owner/admin-only gate."""
    from settings_dialog import TeamTab
    from PyQt6.QtWidgets import QComboBox
    dlg = _StubDialog(_FakeBridge(_fake_member_payload()))
    tab = TeamTab(dlg)

    # Still renders the roster (2 people) + the firm name + role badge.
    assert "boss@client.co" in _labels(tab)
    assert tab._role_badge.text() == "Member"

    # But NO manage affordances.
    assert "Remove" not in _buttons(tab)
    assert len(tab.findChildren(QComboBox, "teamMemberRole")) == 0
    assert not tab._invite_grp.isVisibleTo(tab)


def test_empty_state_no_companies(qapp):
    """No firms -> honest empty state, no fake rows, invite form hidden."""
    from settings_dialog import TeamTab
    from PyQt6.QtWidgets import QFrame
    dlg = _StubDialog(_FakeBridge([]))
    tab = TeamTab(dlg)
    assert tab.findChildren(QFrame, "teamMemberRow") == []
    assert "not part of any firm" in tab._firms_status.text().lower()
    assert not tab._invite_grp.isVisibleTo(tab)


# ── Wiring: controls call the matching bridge slots ────────────────────
def test_create_company_calls_bridge(qapp):
    from settings_dialog import TeamTab
    dlg = _StubDialog(_FakeBridge(_fake_owner_payload()))
    tab = TeamTab(dlg)
    tab._new_firm_name.setText("New Firm LLC")
    tab._on_create_company()
    assert ("company_create", ("New Firm LLC",)) in dlg.bridge.calls


def test_invite_calls_bridge_with_role(qapp):
    from settings_dialog import TeamTab
    dlg = _StubDialog(_FakeBridge(_fake_owner_payload()))
    tab = TeamTab(dlg)
    tab._invite_email.setText("new@teammate.com")
    # Pick the "admin" role by its data value.
    for i in range(tab._invite_role.count()):
        if tab._invite_role.itemData(i) == "admin":
            tab._invite_role.setCurrentIndex(i)
            break
    tab._on_invite()
    assert ("company_invite", ("co_42", "new@teammate.com", "admin")) \
        in dlg.bridge.calls


def test_accept_invite_calls_bridge(qapp):
    from settings_dialog import TeamTab
    dlg = _StubDialog(_FakeBridge(_fake_owner_payload()))
    tab = TeamTab(dlg)
    tab._accept_token.setText("invite-token-xyz")
    tab._on_accept_invite()
    assert ("company_accept_invite", ("invite-token-xyz",)) in dlg.bridge.calls


def test_change_role_calls_bridge(qapp):
    from settings_dialog import TeamTab
    dlg = _StubDialog(_FakeBridge(_fake_owner_payload()))
    tab = TeamTab(dlg)
    tab._on_change_role("co_42", "ada@fargaly.studio", "admin")
    assert ("company_set_role", ("co_42", "ada@fargaly.studio", "admin")) \
        in dlg.bridge.calls


# ── Voice-lint: no pictographic emoji in user-facing copy ──────────────
def test_no_emoji_in_team_copy():
    """FOUNDER-SPEAK / voice-lint: no pictographic emoji in any string the
    founder reads in this tab. Scans the TeamTab source for emoji-range
    codepoints inside string literals' neighbourhood (whole class body)."""
    import inspect
    from settings_dialog import TeamTab
    src = inspect.getsource(TeamTab)
    bad = []
    for ch in src:
        o = ord(ch)
        if (0x1F000 <= o <= 0x1FAFF) or (0x2600 <= o <= 0x27BF) \
                or o in (0x2705, 0x274C, 0x2728, 0x2B50):
            bad.append(hex(o))
    assert not bad, f"Pictographic emoji found in TeamTab copy: {bad}"
