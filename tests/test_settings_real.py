"""SETTINGS-REAL — every flagged Settings control is REAL or honestly gone.

The founder caught Settings controls that "look active but do nothing"
('nothing for show only'). This suite is the RED->GREEN gate that pins each
flagged control to a REAL effect:

  * a WIRED control's handler calls a real save / probe / MCP tool / bridge
    slot — never a pass / no-op / "(deferred)" messagebox; and
  * a REMOVED fake control is actually gone (no dead widget, no dead write).

Verdicts proven here (per control):
  1. Language dropdown ............ REMOVED  (no i18n exists — fake selector)
  2. Default model ................ REAL     (writes default_model, read by
                                              studio_shell model strip + chat)
  3. Show local models ............ WIRED    (-> real hide_local_models flag)
  4. Accessibility font/contrast/SR REAL     (#96 + 2026-06-03: applied live
                                              via __archhubApplyA11y)
  5. Brain Subscribe .............. WIRED    (-> brain.community_subscribe)
  6. Connected-agents setup btn ... WIRED    (-> personal_brain.installer)
  7. Keys & Secrets Test buttons .. WIRED    (-> real per-provider HTTP probe)
  8. Profile name/email/firm ...... WIRED    (-> bridge.save_profile/get_profile)

Proven RED against pre-fix HEAD via `git stash` (see PR body). These tests fail
on the old settings_dialog.py and pass on the fix.

Offscreen-safe: only construction needs a QApplication; network probes are
monkeypatched so nothing hits the wire, and QMessageBox is patched so no modal
ever blocks.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


# ── Qt fixture ────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def qapp():
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication
    import sys as _sys
    return QApplication.instance() or QApplication(_sys.argv)


@pytest.fixture(autouse=True)
def _no_modal(monkeypatch):
    """Stop every QMessageBox from blocking the suite (the old fake handlers
    popped modals; the new ones may too on success)."""
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QMessageBox
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name,
                            staticmethod(lambda *a, **k: None), raising=False)
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
        raising=False,
    )


# A throwaway bridge that records slot calls so we can prove a handler routed
# through a REAL bridge slot rather than doing nothing.
class _RecordingBridge:
    def __init__(self):
        self.calls = []

    # Profile slots (real in bridge.py).
    def get_profile(self):
        self.calls.append(("get_profile", ()))
        return "{}"

    def save_profile(self, payload_json):
        self.calls.append(("save_profile", (payload_json,)))
        return '{"ok": true, "profile": {}}'


class _ParentWithBridge:
    """Minimal stand-in for the dialog parent that exposes `.bridge` so
    _bridge_call finds it (walks .parent(), but a tab stores _parent_dlg and
    _bridge_call also reads `.bridge` directly)."""
    def __init__(self, bridge):
        self.bridge = bridge

    def parent(self):
        return None

    def notify_changed(self):
        pass

    def focus_section(self, *_a, **_k):
        return True


# ─────────────────── 1. Language dropdown REMOVED ──────────────────────
def test_language_dropdown_removed(qapp):
    """The fake multi-language QComboBox is gone — no i18n exists, so a
    language selector could only ever be a lie. GeneralTab must not carry a
    `_lang` combo any more, and there must be NO remaining English/Español/…
    combo on the tab."""
    from PyQt6.QtWidgets import QComboBox
    from settings_dialog import GeneralTab
    tab = GeneralTab(_ParentWithBridge(_RecordingBridge()))
    assert not hasattr(tab, "_lang"), (
        "GeneralTab still has a `_lang` widget — the fake language selector "
        "was not removed."
    )
    # No combo on the tab should contain the old language item set.
    langs = {"Español", "Français", "Deutsch", "日本語", "中文"}
    for combo in tab.findChildren(QComboBox):
        texts = {combo.itemText(i) for i in range(combo.count())}
        assert not (texts & langs), (
            f"A language combo survived removal: {texts & langs}"
        )


def test_no_language_setting_written(qapp):
    """`settings_dialog` must not persist a `language` setting anywhere — it
    was a dead write (read back only by this dialog, applied to nothing)."""
    import settings_dialog
    src = inspect.getsource(settings_dialog)
    assert 'save_setting("language"' not in src and \
           "save_setting('language'" not in src, (
        "settings_dialog still writes a dead `language` setting."
    )


# ─────────────────── 2. Default model REAL ─────────────────────────────
def test_default_model_persists_real_key(qapp, monkeypatch):
    """Saving General must persist `default_model` — the SAME key
    studio_shell reads for the model strip + chat fallback. Proves the
    dropdown takes effect (not show-only)."""
    import settings_dialog
    saved = {}
    monkeypatch.setattr(settings_dialog, "save_setting",
                        lambda k, v: saved.__setitem__(k, v))
    from settings_dialog import GeneralTab
    tab = GeneralTab(_ParentWithBridge(_RecordingBridge()))
    tab._save()
    assert "default_model" in saved, (
        "General._save did not persist default_model — the default-model "
        "dropdown is show-only."
    )


# ─────────────────── 3. Show-local-models WIRED ────────────────────────
def test_show_local_models_writes_real_hide_flag(qapp, monkeypatch):
    """The 'Show local models' checkbox must drive the REAL `hide_local_models`
    flag the model picker honours (inverted), and must NOT write the dead
    `show_local_models` key the picker stopped reading."""
    import settings_dialog
    saved = {}
    monkeypatch.setattr(settings_dialog, "save_setting",
                        lambda k, v: saved.__setitem__(k, v))
    from settings_dialog import ProvidersTab
    tab = ProvidersTab(_ParentWithBridge(_RecordingBridge()))
    assert hasattr(tab, "_on_toggle_local"), (
        "ProvidersTab is missing _on_toggle_local — the local-models toggle "
        "is not wired to the real flag."
    )
    # Uncheck => hide_local_models True ; check => False. Drive both.
    tab._on_toggle_local(False)
    assert saved.get("hide_local_models") is True
    tab._on_toggle_local(True)
    assert saved.get("hide_local_models") is False
    assert "show_local_models" not in saved, (
        "The toggle still writes the dead `show_local_models` key."
    )


# ─────────────────── 4. Accessibility font/contrast/SR REAL ────────────
def test_accessibility_all_four_applied_in_jsx():
    """VERIFY (not fix): the React apply point applies ALL FOUR a11y prefs,
    so the Accessibility controls genuinely take effect (the #96 +
    2026-06-03 work). Reads studio-lm.jsx — the runtime that consumes the
    persisted prefs via bridge.get_a11y_prefs."""
    jsx = (APP_ROOT / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    assert "__archhubApplyA11y" in jsx
    # font size -> root zoom; contrast -> high-contrast class; SR -> sr class.
    assert "lm-reduce-motion" in jsx
    assert ".zoom" in jsx or "style.zoom" in jsx, (
        "font_size is not applied as a root zoom — a11y font control would be "
        "show-only."
    )
    assert "lm-high-contrast" in jsx, "contrast pref is not applied."
    assert "lm-sr-optimized" in jsx, "screen-reader pref is not applied."


def test_accessibility_docstring_not_lying():
    """The AccessibilityTab docstring must AFFIRM all four prefs are applied
    live (the corrected, non-lying state), not the old 'persist-only, font/
    contrast/SR not applied yet' claim. We assert the affirmative marker is
    present AND the old deferral sentence is gone."""
    from settings_dialog import AccessibilityTab
    doc = AccessibilityTab.__doc__ or ""
    assert "APPLIED LIVE" in doc, (
        "AccessibilityTab docstring no longer affirms the four prefs are "
        "applied live."
    )
    # The specific old lie was that font/contrast/SR 'PERSIST but are not
    # applied yet'. That sentence must be gone.
    assert "PERSIST but are\n          not applied yet" not in doc and \
           "PERSIST but are not applied yet" not in doc, (
        "AccessibilityTab docstring still carries the stale 'persist-only, "
        "not applied yet' lie about working controls."
    )


# ─────────────────── 5. Brain Subscribe WIRED ──────────────────────────
def test_brain_subscribe_calls_real_mcp_tool(qapp, monkeypatch):
    """BrainTab Subscribe must call the REAL daemon tool
    brain.community_subscribe — not pop a '(deferred)' messagebox."""
    from settings_dialog import BrainTab
    # Neutralize the network probe BrainTab fires on construction.
    monkeypatch.setattr(BrainTab, "_mcp_call",
                        lambda self, tool, args=None, **k: {"ok": False},
                        raising=True)
    tab = BrainTab(_ParentWithBridge(_RecordingBridge()))

    seen = []
    def _rec(self, tool, args=None, **k):
        seen.append((tool, args or {}))
        if tool == "brain.community_subscribe":
            return {"ok": True, "subscription": {
                "actor_url": (args or {}).get("actor_url"),
                "display_name": "Peer"}}
        # community_list (fired by _render_communities afterward)
        return {"ok": True, "subscriptions": []}
    monkeypatch.setattr(BrainTab, "_mcp_call", _rec, raising=True)
    tab._sub_url.setText("https://peer.example/actor")
    tab._on_subscribe()
    tools_called = [t for t, _a in seen]
    assert "brain.community_subscribe" in tools_called, (
        "Subscribe did not call brain.community_subscribe — it is still the "
        "old deferred no-op."
    )
    sub_args = dict(next(a for t, a in seen if t == "brain.community_subscribe"))
    assert sub_args.get("actor_url") == "https://peer.example/actor"


def test_brain_subscribe_source_has_no_deferred_stub():
    """The old handler popped a `Subscribe (deferred)` info box and never
    called a tool. That deferred-modal marker must be gone and the real tool
    name must be present."""
    from settings_dialog import BrainTab
    src = inspect.getsource(BrainTab._on_subscribe)
    assert '"Subscribe (deferred)"' not in src and \
           "'Subscribe (deferred)'" not in src, (
        "_on_subscribe still pops the old 'Subscribe (deferred)' messagebox."
    )
    assert "brain.community_subscribe" in src


# ─────────────────── 6. Connected-agents setup WIRED ───────────────────
def test_agents_setup_invokes_real_installer(qapp, monkeypatch):
    """The connected-agents setup button must run the REAL brain installer
    (personal_brain.installer.install_all), not pop a description of a missing
    OAuth flow. We inject a fake installer module and assert it's driven."""
    from settings_dialog import BrainTab
    monkeypatch.setattr(BrainTab, "_mcp_call",
                        lambda self, tool, args=None, **k: {"ok": False},
                        raising=True)
    tab = BrainTab(_ParentWithBridge(_RecordingBridge()))

    import types
    calls = {}
    fake_pb = types.ModuleType("personal_brain")
    fake_inst = types.ModuleType("personal_brain.installer")
    fake_inst.detect_clients = lambda: calls.setdefault("detect", True) and [] or ["codex"]  # noqa
    def _detect():
        calls["detect"] = True
        return ["codex", "claude_code"]
    def _install_all(**k):
        calls["install_all"] = True
        return [{"client": "codex"}, {"client": "claude_code"}]
    fake_inst.detect_clients = _detect
    fake_inst.install_all = _install_all
    fake_pb.installer = fake_inst
    monkeypatch.setitem(sys.modules, "personal_brain", fake_pb)
    monkeypatch.setitem(sys.modules, "personal_brain.installer", fake_inst)

    tab._on_chatgpt_setup()
    assert calls.get("detect") and calls.get("install_all"), (
        "Agents-setup button did not drive personal_brain.installer — it is "
        "still the old deferred messagebox."
    )


def test_agents_setup_source_references_installer():
    from settings_dialog import BrainTab
    src = inspect.getsource(BrainTab._on_chatgpt_setup)
    assert "install_all" in src and "detect_clients" in src, (
        "_on_chatgpt_setup no longer references the real installer."
    )


# ─────────────────── 7. Keys & Secrets Test buttons WIRED ──────────────
def test_secrets_has_real_probe_per_provider(qapp):
    """Every KEY_ROWS slug must have a REAL probe in SecretsTab._PROBES —
    no slug may fall through to a 'stub probe' box."""
    from settings_dialog import SecretsTab
    probes = getattr(SecretsTab, "_PROBES", None)
    assert isinstance(probes, dict) and probes, (
        "SecretsTab._PROBES is missing — Test buttons are not wired to real "
        "probes."
    )
    slugs = {slug for slug, *_ in SecretsTab.KEY_ROWS}
    missing = slugs - set(probes)
    assert not missing, f"No real Test probe for: {sorted(missing)}"


def test_secrets_test_button_hits_real_http_probe(qapp, monkeypatch):
    """Clicking Test must dispatch to a probe that builds a REAL authenticated
    request to the provider endpoint — proven by capturing the URL the shared
    _http_probe is asked to fetch (no network: it's monkeypatched)."""
    from settings_dialog import SecretsTab
    tab = SecretsTab(_ParentWithBridge(_RecordingBridge()))

    seen = {}
    def _fake_http(url, headers, *, ok_label="", timeout=6.0):
        seen["url"] = url
        seen["headers"] = headers
        return True, "ok"
    monkeypatch.setattr(SecretsTab, "_http_probe",
                        staticmethod(_fake_http), raising=True)
    # Pretend every provider resolves to a raw token value.
    monkeypatch.setattr(SecretsTab, "_resolver_source",
                        staticmethod(lambda slug, env: ("inline", "tok-123")),
                        raising=True)

    checks = {
        "openai":     "api.openai.com",
        "openrouter": "openrouter.ai",
        "google":     "generativelanguage.googleapis.com",
        "github":     "api.github.com",
        "notion":     "api.notion.com",
        "anthropic":  "api.anthropic.com",
    }
    for slug, host in checks.items():
        seen.clear()
        tab._on_test(slug, slug.title(), "x")
        assert host in seen.get("url", ""), (
            f"Test {slug} did not hit its real endpoint ({host}); "
            f"got {seen.get('url')!r}."
        )


def test_secrets_no_stub_probe_text():
    from settings_dialog import SecretsTab
    src = inspect.getsource(SecretsTab._on_test)
    assert "Stub probe" not in src, (
        "SecretsTab._on_test still contains the 'Stub probe' fake response."
    )


# ─────────────────── 8. Profile WIRED to real bridge slot ──────────────
def test_profile_saves_through_bridge_slot(qapp):
    """General profile Save must route through the REAL bridge.save_profile
    slot (which writes profile.json + is the store the first-run prompt uses),
    not only a private file write."""
    from settings_dialog import GeneralTab
    bridge = _RecordingBridge()
    tab = GeneralTab(_ParentWithBridge(bridge))
    tab._name.setText("Ada Lovelace")
    tab._email.setText("ada@firm.com")
    tab._save()
    slot_names = [c[0] for c in bridge.calls]
    assert "save_profile" in slot_names, (
        "General._save never called bridge.save_profile — the profile fields "
        "don't reach the real profile store."
    )


# ─────────────────── contract intact (must stay green) ─────────────────
def test_tabs_contract_unchanged():
    """The 12-entry TABS contract must survive this lane untouched."""
    from settings_dialog import SettingsDialog
    expected = [
        "General", "Providers", "Secrets", "Hosts", "Memory", "Brain",
        "Permissions", "Storage", "Shortcuts", "Accessibility", "About",
        "Account",
    ]
    actual = [label for label, _cls in SettingsDialog.TABS]
    assert actual == expected
    assert len(SettingsDialog.TABS) == 12
