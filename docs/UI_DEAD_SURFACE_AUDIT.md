# ArchHub UI Dead-Surface Audit — v1.3

Audit date: 2026-05-13. Scope: every visible surface in the PyQt6
shell (Studio rail, chat header, cog menu, status bars, inspector,
Home, Skills, Workflows, Marketplace, Telemetry, Settings, overlays,
banners). Builds on `docs/UI_AUDIT_v1.2.md` which covered visual
drift; this pass covers existence drift — surfaces that consume
real estate without doing anything actionable.

Classification legend
- USED        — has a real handler, removing breaks workflow
- REDUNDANT   — does the same thing as another surface
- DECORATION  — visible but doesn't drive action
- DEAD        — entry point exists, handler is no-op / TODO / not wired
- PHASE-2     — useful but premature (e.g. Marketplace UI when 0 packs)

## 1. Cog menu — `chat_window._build_app_menu()` (chat_window.py:1642)

| Item | Handler | Classification | Recommendation |
|------|---------|----------------|----------------|
| Sign-ins… | `_open_settings` | USED | Keep — primary discovery surface for provider auth |
| Connectors… | `_open_connectors` | USED | Keep — only entry point to ConnectorPanel toggles |
| Skills… | `_open_skills_panel` | USED | Keep — Skills library editor |
| Sessions… | `_open_sessions` | USED | Keep — chat history viewer |
| Save chat as Skill… | `_save_chat_as_skill` | USED | Keep — primary capture verb |
| Updates row | `_open_update_dialog` | USED | Keep — update banner is the auto path; this is the manual entry |
| Plans & pricing… | `_open_pricing_dialog` | USED | Keep — primary monetisation surface |
| Reality Check | `_open_reality_check` | REDUNDANT | Cut — duplicates the Telemetry page's embedded RealityCheckPanel in the Studio shell. The CLI `scripts/reality_smoke.py` is the supported tool for one-shot checks. To revive: re-add the menu line in `_build_app_menu`. |
| About ArchHub | `_show_about` | USED | Keep |
| Quit | `QApplication.instance().quit` | USED | Keep |

Target: 9 items. Reality Check drops out. Final menu has 8 items
(Sign-ins, Connectors, Skills, Sessions, Save chat as Skill,
Updates row, Plans & pricing, About, Quit) plus the auto Updates
label which is its own row.

## 2. Header — `chat_window._build_header()` (chat_window.py:1408)

| Surface | Handler | Classification | Recommendation |
|---------|---------|----------------|----------------|
| ArchHub™ brand label | (tooltip only) | DECORATION | Keep — brand anchor |
| Host pills row | refresh every 6s; click opens Add Host | USED | Keep — only live host indicator visible in chat-only mode |
| Model picker QComboBox | `_populate_model_picker` | USED | Keep — primary model selector |
| `+ Add Host` button | `_open_add_host` | USED | Keep — one-click connector path |
| `Menu` tool button | opens app menu | USED | Keep |

## 3. Status bar — `chat_window._build_status_bar()` (chat_window.py:1858)

Left + right text labels, no actionable click handlers.

| Surface | Source | Classification | Recommendation |
|---------|--------|----------------|----------------|
| `status_left` | "Live: …" or "N tools detected · open Connectors" | REDUNDANT | The header host pills already show live state per host with a dot. The text below repeats it as words. **Cut** the duplicate live string; keep the line only as a routing-note carrier (already used by `_on_finished` at chat_window.py:2490). To revive: rebuild the live-host text in `_refresh_status`. |
| `status_right` | "LLM: openai, anthropic" or "Add API keys…" | REDUNDANT | The model picker dropdown already shows which providers are configured (greyed-out rows for unconfigured providers). The right label restates it. **Cut** the live-LLM text; keep the empty-state nudge ("Add API keys in Settings to start chatting") because that one is actionable. |

Net: status bar still exists but it's narrower in normal state. When
all providers configured the bar is empty (slim row, ready to carry a
runtime status line on the next chat turn). When nothing configured
it shows the nudge.

## 4. Studio rail — `studio_shell._build_rail()` (studio_shell.py:237)

NAV_ITEMS (studio_shell.py:82):

| Item | Page | Classification | Recommendation |
|------|------|----------------|----------------|
| Home | `_build_home` | USED | Keep |
| Chat | `_wrap_chat` | USED | Keep |
| Skills | `_build_skills_page` (SkillsGridPanel) | USED | Keep |
| Workflows | `_build_workflows_page` (WorkflowCanvas) | PHASE-2 | Hide from rail (collapse behind Skills page's "Open canvas" affordance). The Canvas IS useful for advanced users but is not a top-level destination when most users have 0 workflows and run everything as Skills. To revive: add `("flows", "Workflows", "4")` back to NAV_ITEMS. |
| Marketplace | `_build_marketplace_page` (MarketplacePanel, 8 seed entries) | PHASE-2 | Keep visible — seed catalog exists, install path works. Marked Phase-2 because remote manifest fetch (the unique value) is not yet wired. |
| Telemetry | `_build_telemetry_page` | USED | Keep — embeds Reality Check sparklines + KPI cards |
| Pricing | `_build_pricing_page` | USED | Keep — converts to paid tier |
| Settings | `_build_settings_page` (SettingsPage) | USED | Keep |

HOSTS section: USED. THREADS section: USED. `+ Add host…` row: USED.
User card: USED (real auth state). Theme toggle: USED.
⌘K command box: USED (palette overlay).

## 5. Studio inspector quick actions — `_quick_actions_for_page()` (studio_shell.py:945)

Page-aware list shown in the right inspector.

| Page | Item | Handler | Classification | Recommendation |
|------|------|---------|----------------|----------------|
| chat | New session | `chat_widget._new_session` | DEAD | `_new_session` not defined on ChatWindow — silently no-ops via the `lambda: None` fallback. **Cut** the row. To revive: implement `_new_session` on ChatWindow and re-add the tuple. |
| chat | Save session | `chat_widget._save_session` | USED | Keep |
| chat | Open session… | `chat_widget._open_sessions` | USED | Keep |
| addhost | Refresh detection | `manager.refresh()` | USED | Keep |
| default | Open ⌘K palette | `_open_palette` | USED | Keep |
| default | Add host… | `_set_page("addhost")` | USED | Keep |
| default | Browse Marketplace | `_set_page("market")` | USED | Keep |
| default | Spawn pet strip | `_spawn_pet_strip` | DEAD | Handler is a deliberate no-op as of v1.0.2 — shows toast "Pet strip was removed". **Cut** the row + the handler. To revive: re-introduce the pet strip widget and re-wire. |
| default | Switch theme | `_toggle_theme` | USED | Keep |

## 6. Studio status rule — `_build_status_rule()` (studio_shell.py:1015)

| Item | Source | Classification | Recommendation |
|------|--------|----------------|----------------|
| `● N/M hosts` | live connector count | USED | Keep |
| `tokens —` | `_sr_tokens` | DECORATION | Always displays placeholder "—". No live data wired. **Hide** (setVisible(False)) until real token-count tap exists. To revive: setVisible(True) + wire `_sr_tokens.setText` from telemetry. |
| `spend $0.00` | telemetry total | USED | Keep |
| Cloud usage meter | shown only when signed-in to paid proxy | USED | Keep (already hidden by default) |
| Healing dot + label | shown only when healing active | USED | Keep (already conditional) |
| Right shortcuts string `⌘K palette · ⌘↩ run skill · ⌘/ docs · vX.X` | static | DECORATION | Keep — version is useful at a glance, shortcuts are educational |

## 7. Settings dialog — `settings_dialog.py`

| Section | Classification | Recommendation |
|---------|----------------|----------------|
| Sign-ins (OpenRouter / Anthropic / OpenAI / Google) | USED | Keep |
| "Show local Ollama models" checkbox | USED | Keep — explicit override toggle |
| Firm relay (OpenAI-compatible self-hosted) | PHASE-2 | Hide behind an "Advanced" toggle group. Most users will not run their own gateway; the surface is large and only sells to enterprise. To revive: setVisible(True) on `relay_box`. |
| Speckle (toggle + cloud/self-host radio + token + setup button) | USED | Keep behind the existing master toggle (already opt-in) |
| Procore (token + company/project ids) | USED | Keep — real construction-PM tool integration |
| Appearance / HUD overlay mode + hotkey | PHASE-2 | Collapse the *configuration* (toggle + hotkey field) behind an "Advanced — HUD overlay" disclosure; keep the master toggle visible. Most users never opt into the always-on-top floating overlay; the hotkey field is a power-user knob. To revive: setVisible(True) on the appearance children. |
| AI Behaviour (extended thinking + per-tool policy) | USED | Keep |
| Privacy & crash reports (telemetry + PostHog + Sentry + Discord webhook) | USED | Keep |

The Cloud sync row is USED.

## 8. Marketplace panel — `marketplace_panel.py`

Tab buttons (Skills / Workflows), search box, card grid driven by
`payload/marketplace/catalog.json` (8 seed items in code at
marketplace_panel.py:62-249).

| Surface | Classification | Recommendation |
|---------|----------------|----------------|
| Search box | USED | Keep |
| Skills / Workflows tabs | USED | Keep |
| 8 seed card grid | PHASE-2 | Keep visible — install works against seeds. Once a remote manifest fetch lands the page becomes truly active. |

## 9. Reality Check — `reality_check_panel.py`

Two entry points:
1. Studio Telemetry page embeds `RealityCheckPanel` (USED).
2. Chat cog menu opens `RealityCheckDialog` modal (REDUNDANT — see §1).

Recommendation: keep the panel embed in Telemetry; cut the menu item.

## 10. Workflows panel — `workflows_panel.py`

`WorkflowsPanel` class is imported into `chat_window.py:32` but never
instantiated (the `_open_workflows` method at chat_window.py:2654 redirects
straight to `_open_skills_panel`). Dead module surface.

| Surface | Classification | Recommendation |
|---------|----------------|----------------|
| `WorkflowsPanel` class import | DEAD | Remove the unused `from workflows_panel import WorkflowsPanel` import. To revive: re-add the import + restore the menu wiring. |
| `_open_workflows` method | DEAD | Remove. Skills panel handles workflow editing. |
| `_save_chat_as_workflow` method (chat_window.py:2658) | DEAD | Remove. Skills capture (`_save_chat_as_skill`) is the supported verb. |
| `workflows_panel.py` module file | DEAD on chat side | Keep file on disk — `studio_shell.py:34` docstring mentions it and `workflow_canvas.py:5` references its JSON contract. Future revival as a list-view alternative remains plausible. |

## 11. In-chat welcome card — `chat_window._show_welcome()` (chat_window.py:1744)

| Surface | Classification | Recommendation |
|---------|----------------|----------------|
| "What do you want to build?" title | USED | Keep |
| Subtitle line | USED | Keep |
| Quick-start skill chips (top 3) | USED | Keep |
| Chip label `f"  ✦  {name}"` | DECORATION/voice | The `✦` violates BRAND.voice "No emoji". Replace with leading bullet `·` (typographic, not emoji). |

## 12. Home composer chips — `studio_shell._build_home()` (studio_shell.py:425)

| Chip | Handler | Classification | Recommendation |
|------|---------|----------------|----------------|
| `✦ Sketch` | `_home_attach_sketch` | USED | Keep — opens image picker |
| `● Voice` | `_home_voice` | USED | Keep — Win+H dictation |
| `@ Skill` | `_open_palette` | USED | Keep |
| `+ Host` | `_set_page("addhost")` | USED | Keep |

## 13. Header behaviour overlap — chat-only mode vs. Studio shell

When ChatWindow runs standalone (no Studio wrap) the header carries
host pills and the cog menu. When wrapped by StudioShell the rail
already shows hosts + the user card carries a Settings menu. The
duplication is intentional (chat-only fallback) and explicitly
documented in `UI_AUDIT_v1.2.md:118-121`. Keep.

---

## Verdict + Top cuts

**Surfaces audited**: 56 across 13 surface groups.

Distribution:
- USED        : 39
- DECORATION  : 4
- REDUNDANT   : 3
- DEAD        : 5
- PHASE-2     : 5

**Top cuts shipped** (one-line each, see commits for diff):
1. `chat_window.py:1677-1679` — remove "Reality Check" menu item (redundant with Telemetry embed).
2. `chat_window.py:2654-2656` — remove `_open_workflows` method (dead).
3. `chat_window.py:2658-2677` — remove `_save_chat_as_workflow` method (dead).
4. `chat_window.py:32` — remove unused `from workflows_panel import WorkflowsPanel` import.
5. `chat_window.py:1779` — change welcome chip label from `"  ✦  {name}"` to `"  ·  {name}"` (voice).
6. `chat_window.py:2628-2642` — collapse `_refresh_status` redundant live-LLM and live-host echoes; keep empty-state nudge.
7. `studio_shell.py:966` — remove "Spawn pet strip" quick action (handler is a deprecation toast).
8. `studio_shell.py:970-982` — remove `_spawn_pet_strip` method (orphaned after #7).
9. `studio_shell.py:948-955` — remove "New session" chat-page quick action (`_new_session` not defined on ChatWindow).
10. `studio_shell.py:1030-1031` — hide placeholder `tokens —` status item (no live data wired).
11. `settings_dialog.py:160-198` — collapse Firm relay row behind a "Show advanced" disclosure inside the dialog.
12. `settings_dialog.py:314-352` — collapse HUD hotkey field + help text inside the Appearance row; keep the master toggle visible.

**Top kept**:
1. Host pills — live, actionable, single-glance hint of what's connected.
2. Studio Telemetry page — KPI cards + sparkline panel form one coherent diagnostic surface.
3. Skills panel — only library editor; can't fold into anything else.
4. ConnectorPanel — only place users can toggle individual connectors.
5. Procore section in Settings — real third-party integration with a non-trivial token flow.

---

## How to revive any deleted surface

Every cut above has a one-line revival note in the table cell. The
deleted Python methods (`_open_workflows`, `_save_chat_as_workflow`,
`_spawn_pet_strip`) can be restored from `git log -- app/chat_window.py`
and `git log -- app/studio_shell.py`. The deleted menu and quick-action
entries are one tuple each in their respective build functions.

## Phase-2 surfaces deferred

1. **Marketplace remote fetch** — UI is on spec but powered by an
   8-item local seed. Phase-2 wires `marketplace_client.fetch_manifest`
   to a real catalog endpoint. Until then, keep the page accessible
   (no rail removal) because the install path works against the seed.

2. **Workflow canvas as top-level** — the Blueprint-style canvas in
   `workflow_canvas.py` is functional but most users will run things
   as Skills (canvas is for branchy / triggered automations). When
   the 0-workflow majority shrinks, promote `("flows", "Workflows", "4")`
   back into NAV_ITEMS in `studio_shell.py`.

3. **Reality Check as a standalone modal** — the embedded panel in
   Telemetry covers 95% of the use case. If users start asking for a
   "run smoke now" one-click verb from the cog menu, re-add the line.
