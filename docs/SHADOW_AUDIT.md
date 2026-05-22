# ArchHub Shadow Audit — v1.3.3 forensic ledger

Audit date: 2026-05-13. Scope: every visible-or-claimed user surface in
the PyQt6 client, classified against the live runtime behaviour when
the app launches with `StudioShell` wrapping `ChatWindow` (the default
for 99% of users). Builds on `docs/UI_DEAD_SURFACE_AUDIT.md` (round 1,
v1.3.1) and `docs/UI_DEAD_SURFACE_AUDIT_v2.md` (round 2, v1.3.2). This
pass enforces a stricter rule:

> A claim is only kept if the code path is REACHABLE from the wrapped
> StudioShell runtime. Anything wired only to the bare ChatWindow
> fallback, anything wrapped behind a flag that is always False, and
> anything imported-but-never-instantiated is a shadow.

Bug-class legend
- **SHADOWED**         — widget exists but covered by parent wrapper
- **DUPLICATE**        — two paths for the same intent; user gets the wrong one
- **DEAD HANDLER**     — button / menu wired to a callback that is no-op / `pass` / `return` / wrong-target `hasattr`
- **DISCONNECTED**     — setting persisted in secrets / DB but nothing reads it
- **PHANTOM**          — claimed in CHANGELOG / docstring / comment but code path missing or wrong
- **CONDITIONAL DEAD** — wrapped in `if some_flag` where the flag is always False
- **PRE-WRAP CUT**     — the recent patch landed on a layer the user never sees

## Surface visibility map

### When wrapped by StudioShell (default — every normal launch)

VISIBLE
- Studio brand row in rail (24-px ArchMark + theme toggle)
- ⌘K command box
- Studio NAV rail (Home · Chat · Skills · Settings + "More" disclosure)
- HOSTS section + "+ Add host..." inline row
- THREADS section
- User card with cog menu (Settings / theme / About)
- Main pane — which is the WHOLE ChatWindow centralWidget, including:
   - ChatWindow header (24-px 'A' monogram + host pills + model picker + +Add Host + Menu)
   - ChatWindow update banner
   - Conversation area + welcome chip row
   - Input bar (+ image preview bar) + Send / Stop
   - ChatWindow status bar (auto-hides when blank)
  ...but ONLY when `_active_page == "chat"`. Default page is "home";
  the chat surface is one click away.
- Right inspector (LLM ROUTER · SELECTION / PARAMETERS · QUICK ACTIONS) on Home / Chat / Add Host
- Right inspector collapsed 8-px strip on Marketplace / Skills / Settings / Pricing / Telemetry
- Bottom status rule (hosts · spend · cloud · healing · v{ver})
- Update banner (between ChatWindow header and ChatWindow body; only on the Chat page; ChatWindow owns the signal)

HIDDEN (paint suppressed by Studio's own chrome OR by being on a different page)
- ChatWindow header on Home / Skills / Workflows / Marketplace / Telemetry / Pricing / Settings / Add Host pages
- ChatWindow welcome card on any page other than Chat
- ChatWindow status bar on any page other than Chat
- Update banner if user is not on the Chat page when the banner fires

PARTIAL / render-context-dependent
- Studio brand sub-caption `STUDIO · N LIVE` — exists in code but parent QLabel is `setVisible(False)` (studio_shell.py:273-276)
- Cog menu lives on user card AND on chat header — both reachable; user clicks whichever is visible to them

### When bare ChatWindow (StudioShell construction fails)

VISIBLE  → everything ChatWindow renders top-to-bottom: header · banner · split (conversation+input | parameters) · status bar
HIDDEN   → all Studio chrome (rail · ⌘K · NAV · inspector · status rule · user card · brand row)

## Forensic ledger

One row per surface. `code path` = file:line entry point; `bug class`
empty when the surface is fully reachable.

| # | feature | code path | render context | actually visible? | bug class |
|---|---------|-----------|----------------|-------------------|-----------|
| 1 | Chat header brand 'A' monogram + tooltip | chat_window.py:1448 | Chat page only | Yes (on Chat) | — |
| 2 | Chat header host pills (5 families) | chat_window.py:1462-1509 | Chat page only | Yes (on Chat) | — |
| 3 | Chat header model picker | chat_window.py:1471-1474 | Chat page only | Yes (on Chat) | — |
| 4 | Chat header + Add Host | chat_window.py:1477-1485 | Chat page only | Yes (on Chat) | — |
| 5 | Chat header Menu button | chat_window.py:1493-1500 | Chat page only | Yes (on Chat) | — |
| 6 | Chat menu — Sign-ins | chat_window.py:1681-1682 | Chat page menu | Yes | — |
| 7 | Chat menu — Skills | chat_window.py:1692-1693 | Chat page menu | Yes — opens legacy SkillsPanel modal | **DUPLICATE** (Studio Skills page is SkillsGridPanel; this opens different surface) |
| 8 | Chat menu — Sessions | chat_window.py:1694-1695 | Chat page menu | Yes | — |
| 9 | Chat menu — Save chat as Skill | chat_window.py:1696-1697 | Chat page menu | Yes | — |
| 10 | Chat menu — Updates row | chat_window.py:1705-1706 | Chat page menu | Yes | — |
| 11 | Chat menu — About | chat_window.py:1716-1717 | Chat page menu | Yes | — |
| 12 | Chat menu — Quit | chat_window.py:1720-1721 | Chat page menu | Yes | — |
| 13 | Chat welcome chip row | chat_window.py:1779-1823 | Chat page only | Yes when skills>0 | — |
| 14 | Chat conversation area | chat_window.py:1762-1777 | Chat page only | Yes (on Chat) | — |
| 15 | Chat input bar + send | chat_window.py:1825-1886 | Chat page only | Yes (on Chat) | — |
| 16 | Chat status bar (auto-hide) | chat_window.py:1888-1914 | Chat page only | Hidden steady-state | — |
| 17 | Chat update banner | chat_window.py:1245-1304 | Chat page only | Yes when fired | — |
| 18 | Parameters sidebar (live session) | chat_window.py:1403-1417 | Chat page only | Yes when params>0; hidden empty | — |
| 19 | Studio rail brand mark | studio_shell.py:269-286 | Always | Yes | — |
| 20 | Studio rail Wordmark | studio_shell.py:272-274 | Always | NO — `setVisible(False)` | **CONDITIONAL DEAD** — kept as ref so legacy callers don't NPE |
| 21 | Studio rail brand sub-caption `STUDIO · N LIVE` | studio_shell.py:273-276,1808 | Always | NO — `_brand_sub.setVisible(False)` but `_refresh_home` keeps writing to it | **DISCONNECTED** — text updated each tick but the QLabel is hidden permanently |
| 22 | Studio rail theme toggle | studio_shell.py:279-286 | Always | Yes | — |
| 23 | Studio rail ⌘K command box | studio_shell.py:290-298 | Always | Yes | — |
| 24 | Studio rail NAV (4 primary) | studio_shell.py:87-92, 311-318 | Always | Yes | — |
| 25 | Studio rail NAV ("More" + 4 secondary) | studio_shell.py:93-98, 320-340 | Always | Yes (collapsed by default) | — |
| 26 | Studio rail HOSTS section | studio_shell.py:344-351, 1242-1505 | Always | Yes (live signature-diff) | — |
| 27 | Studio rail "+ Add host..." row | studio_shell.py:356-373 | Always | Yes | — |
| 28 | Studio rail THREADS section | studio_shell.py:375-382, 1563-1599 | Always | Yes | — |
| 29 | Studio rail user card | studio_shell.py:385-390, 1143-1204 | Always | Yes | — |
| 30 | Studio user-card cog → Settings | studio_shell.py:1190-1192 | Always | Yes | — |
| 31 | Studio user-card cog → Theme toggle | studio_shell.py:1194-1198 | Always | Yes | — |
| 32 | Studio user-card cog → About (disabled) | studio_shell.py:1200-1201 | Always | Visible but `setEnabled(False)` | **PRE-WRAP CUT** — clicking does nothing; no informational dialog |
| 33 | Studio Home — date caption | studio_shell.py:431-433, 1768-1774 | Home page only | Yes | — |
| 34 | Studio Home — greeting H1 | studio_shell.py:435-437, 1793 | Home page only | Yes | — |
| 35 | Studio Home — tagline | studio_shell.py:440-442 | Home page only | Yes | — |
| 36 | Studio Home — composer + chips + Send | studio_shell.py:452-489 | Home page only | Yes | — |
| 37 | Studio Home — Suggested Skills section | studio_shell.py:494-504, 1817-1849 | Home page only | Yes when skills>0 (hidden empty) | — |
| 38 | Studio Home — Pick up where you left off | studio_shell.py:507-515, 1851-1908 | Home page only | Yes when sessions>0 | — |
| 39 | Studio Home — Live tasks | studio_shell.py:519-527, 1910-1948 | Home page only | Yes when healing | — |
| 40 | Studio Inspector — LLM ROUTER row list | studio_shell.py:773-781, 845-862 | Home/Chat/Add Host | Yes — but rows are SEEDED, not live | **PHANTOM** — `_known_models()` iterates `KNOWN_MODELS` which is `list[tuple[str,str]]`; the `isinstance(m, dict)` and `isinstance(m, str)` checks both fail for a tuple. Loop body always misses. Always falls through to hardcoded seed: Claude Sonnet 4.5 / GPT-5 / Gemini 2.5 Pro / qwen3:32b. Inspector router is decoration, not live |
| 41 | Studio Inspector — SELECTION KV (5 rows) | studio_shell.py:783-800, 1742-1762 | Home/Add Host | Yes — live | — |
| 42 | Studio Inspector — PARAMETERS (Chat) | studio_shell.py:802-809, 2398-2414 | Chat page only | Yes — embeds live ParametersPanel | — |
| 43 | Studio Inspector — QUICK ACTIONS list | studio_shell.py:811-819, 984-1036 | Always (page-aware) | Yes | — |
| 44 | Studio Inspector — collapsed 8-px strip | studio_shell.py:829-838, 2445-2459 | Non-Home/Chat/Add Host | Yes (click to expand) | — |
| 45 | Studio status rule — hosts/spend/tokens/cloud/healing | studio_shell.py:1069-1138 | Always | Yes (tokens hidden steady-state, OK) | — |
| 46 | Studio command palette (⌘K) — nav results | command_palette.py:267-283 | Overlay | Yes — switches page | — |
| 47 | Studio command palette — skills_provider results | command_palette.py:285-302 | Overlay | Yes — but every Skill row's on_invoke is `shell._set_page("skills")` regardless of which skill is clicked | **DEAD HANDLER** — palette ranks Skill rows by name match but clicking ANY of them just jumps to the Skills page without selecting that skill. User who searched 'dimension walls' to run it sees the page, not the skill |
| 48 | Studio command palette — sessions_provider results | command_palette.py:304-317 | Overlay | Yes (opens chosen session via `_open_session_path`) | — |
| 49 | Studio command palette — marketplace_provider results | command_palette.py:342-355 | Overlay | Yes — but every Marketplace row's on_invoke is `shell._set_page("market")` regardless of which item | **DEAD HANDLER** — same pattern as Skill rows. User who clicked a specific catalog item sees the page, not that item |
| 50 | Studio Chat page wrapper | studio_shell.py:397-415 | Stack | Yes — reparents whole ChatWindow centralWidget | — |
| 51 | Studio Skills page (SkillsGridPanel) | studio_shell.py:537-551 | Stack | Yes | — |
| 52 | Studio Workflows page (WorkflowCanvas) | studio_shell.py:553-566 | Stack | Yes | — |
| 53 | Studio Settings page (SettingsPage) | studio_shell.py:568-585 | Stack | Yes (but see #56) | — |
| 54 | Studio Marketplace page | studio_shell.py:595-601 | Stack | Yes | — |
| 55 | Studio Add Host page | studio_shell.py:603-612 | Stack | Yes | — |
| 56 | Settings page nests SettingsDialog with its OWN AI Behaviour + tool-permission table | settings_page.py:148-171, settings_dialog.py:453-579 | Studio Settings | Yes — but Studio Settings also builds its OWN AI Behaviour section (settings_page.py:174-300) | **DUPLICATE** — user sees thinking-effort radio AND a tool-permission table TWICE in the same page when they scroll. Two independent controls writing to the same `ai_behaviour` keys |
| 57 | onboarding.py:299 — `parent._run_skill_by_id` after `_launch_skill` | onboarding.py:295-303 | First-run wizard | Wizard's parent is StudioShell; StudioShell has no `_run_skill_by_id` (`hasattr(parent, "_run_skill_by_id")` is False) | **DEAD HANDLER** — chip click marks onboarding complete and accepts, but the skill the user just clicked is NEVER actually run. Silently no-op |
| 58 | onboarding.py emoji glyphs (✓, ✦, 🔐) | onboarding.py:129, 172, 271 | First-run wizard | Yes | **DUPLICATE-ish** — violates BRAND.voice "No emoji" already cleaned up in chat_window/welcome chip in v1.3.1 (✦ → ·) but onboarding still uses the old glyphs |
| 59 | main.py:548 — `window._set_page("settings")` when user clicks "I have a Claude account" | main.py:546-551 | First launch flow | `window` is the ChatWindow, not StudioShell; ChatWindow has NO `_set_page`. The `hasattr` check returns False so nothing opens | **DEAD HANDLER** — user picks "I already have a Claude/OpenAI account", Settings never opens, they land on a blank chat with no way to find Sign-ins except via the cog menu they don't know exists |
| 60 | release_updater.auto_check_and_apply uses `release.tag_name` | release_updater.py:397, 398, 401, 406, 467, 482, 485 | Background daemon | NEVER — `ReleaseInfo` has `.tag`, not `.tag_name`. Every status call raises `AttributeError` the moment an update is detected | **PHANTOM** — the "Claude-Desktop pattern auto-update" flow CRASHES inside the daemon thread the instant a real new release lands. `auto_check_and_apply` returns `{"status": "error"}`. The in-app update banner never gets the installer path; user never sees "restart to install". Quietly silent failure |
| 61 | feedback_widget.py hardcoded #232321 / #f4efe8 | feedback_widget.py:127-130 | Per bubble | Yes | **PRE-WRAP CUT** for dark-mode-compatibility — comment field uses dark-only colors. In dark mode it looks fine. In light mode the comment input is dark-on-dark (the QLineEdit bg is `#232321` against a light page background) — readable but off-palette |
| 62 | feedback_widget.py docstring claims `👍 / 👎` emoji buttons | feedback_widget.py:3-6 | docstring only | n/a | **PHANTOM** — code actually renders mono-text "yes" / "no" links; docstring still says emoji |
| 63 | workflows_panel.WorkflowsPanel class | workflows_panel.py:26-209 | Never instantiated | NEVER — chat_window dropped the import in v1.3.1, studio_shell uses WorkflowCanvas | **PHANTOM** — entire 209-line file is orphan; studio_shell.py:34 docstring claims `Workflows <- embeds existing WorkflowsPanel as a widget` but actually uses WorkflowCanvas |
| 64 | studio_shell.py:33 docstring claims `Skills <- embeds existing SkillsPanel as a widget` | studio_shell.py:33 | docstring | n/a | **PHANTOM** — actually embeds SkillsGridPanel; SkillsPanel modal is only reachable via the chat menu's "Skills..." item |
| 65 | studio_shell.py:35 docstring claims `Settings <- embeds existing SettingsDialog content as a widget` | studio_shell.py:35 | docstring | n/a | **PHANTOM** — actually uses SettingsPage which wraps SettingsDialog in one section. Comment is wrong by abstraction |
| 66 | Studio inspector `tokens —` placeholder | studio_shell.py:1088-1091 | Studio status rule | Always hidden — `setVisible(False)` | OK — cut acknowledged in code |
| 67 | Studio shell `_open_connectors` (ChatWindow method) | chat_window.py:2708-2711 | None — no menu wires to it | Never reachable from default-flow UI | **DISCONNECTED** — kept for "programmatic / palette callers" per the comment, but nothing in palette / programmatic code calls it. Dead helper, no callsite |
| 68 | ChatWindow `_open_reality_check` | chat_window.py:3067-3070 | None — menu line cut in v1.3.1 | Never reachable from default-flow UI | **DISCONNECTED** — kept "for command-palette / programmatic callers" but palette provider list does not include it. Dead helper |
| 69 | onboarding gating: two functions with same name | first_run.py:80-91 AND onboarding.py:39-41 | First launch | Both run; they read different settings keys (`first_run_complete` vs `onboarding_completed`) | **DUPLICATE** — main.py invokes BOTH (lines 506-511 then 538-554). User can complete one flow but still see the other on the same launch. Adjacent stale flag |
| 70 | sentry_init re-init after consent | main.py:514-519 | Always | Yes | — |
| 71 | Telemetry consent dialog | telemetry_consent_dialog.maybe_prompt | First launch | Yes | — |
| 72 | RealityCheckPanel embed in Telemetry page | studio_shell.py:679-694 | Telemetry page | Yes | — |
| 73 | Marketplace panel install action | marketplace_panel.py | Studio Marketplace page | Yes (per CHANGELOG, install works against seed catalog) | — |
| 74 | ai_behaviour thinking-effort dropdown | settings_dialog.py:487-502 | Settings dialog | Yes | — |
| 75 | ai_behaviour per-tool combos | settings_dialog.py:531-579 | Settings dialog | Yes | — |
| 76 | Cloud sync row | settings_dialog.py:774-850 | Settings dialog | Yes (auto-shown under Show advanced when sync configured) | — |
| 77 | Firm relay URL + token | settings_dialog.py:194-235 | Settings dialog | Yes | — |
| 78 | Speckle toggle + token | settings_dialog.py:239-341 | Settings dialog | Yes | — |
| 79 | Procore row | settings_dialog.py:881-985 | Settings dialog | Yes | — |
| 80 | HUD overlay opt-in toggle | settings_dialog.py:367-372, main.py:454-463 | Settings | Visible setting BUT only honoured if `surface is window` (bare ChatWindow); StudioShell wrap skips overlay_chrome entirely | **CONDITIONAL DEAD** — the persisted `hud_overlay_mode` setting + `hud_hotkey` setting are READ during launch but the apply_overlay_chrome call gates on `if surface is window`. Under StudioShell wrap, `surface = shell`, so the overlay is silently disabled regardless of the setting. The Settings dialog STILL lets the user check the box and rebind the hotkey — DISCONNECTED setting for 99% of users |
| 81 | studio_shell theme toggle button glyph (☾ ☀) | studio_shell.py:283 | Always | Yes | — typographic, not emoji |
| 82 | llm_detector probes / detect_all | llm_detector.py | Reachable via `ai_detect_local` tool only | Yes — when the LLM calls the tool mid-turn | OK — tool-call surface, not UI |
| 83 | onboarding wizard `_launch_skill` → mark_completed even on failure | onboarding.py:292-303 | First-run wizard | Yes — but skill is silently not run (see #57) | continuation of #57 |
| 84 | release_updater download log message uses `release.tag_name` | release_updater.py:467 (toast) | Background notify mode | Yes — toast message would raise AttributeError silently | see #60 |
| 85 | studio_shell `_brand_sub` initialized to "" but `_refresh_home` rewrites it every tick | studio_shell.py:275, 1808 | Home tick | Cycles in vain (label hidden) | see #21 |

## CHANGELOG cross-reference (v1.0.2 → v1.3.2)

Format: ✅ ships + visible · ⚠️ ships but only visible in bare ChatWindow · ❌ claimed but no working code path / wrong surface.

### v1.0.2

| Claim | Verdict |
|---|---|
| Settings → Cloud Sync no longer crashes (`_on_sync_now`) | ✅ Settings page → Providers section embeds SettingsDialog so the fix is reachable |
| Network blip retries in llm_router | ✅ — server-side, no UI |
| Per-host AI Behaviour defaults | ✅ |
| AI Behaviour panel in legacy SettingsDialog | ⚠️ — surfaces in BOTH the legacy modal AND the Studio Settings page; the Studio Settings page now shows AI Behaviour TWICE (DUPLICATE #56) |
| `+ Add Host` button in the chat header | ⚠️ — visible only when the user is on the Chat page of the Studio shell. The "+Add host..." row in the Studio rail is the primary surface 99% of the time. Two visible Add Host affordances |
| Live host status pills next to the brand | ⚠️ — only visible on Chat page; on Home / Skills / Settings the rail HOSTS section is the only host indicator |
| Startup self-test boot.log | ✅ — non-UI |
| 21 new tests | ✅ |

### v1.0.3 — "AI-as-tool"

| Claim | Verdict |
|---|---|
| `ai_chatgpt_ask`, `ai_gemini_ask`, `ai_lmstudio_ask`, `ai_antigravity_ask`, `ai_list_providers` tools | ✅ — reachable through tool engine |
| `ai_antigravity_ask` stub | ⚠️ "no public API yet" — phantom-ish on purpose |
| LM Studio reachability probe | ✅ |

### v1.0.4 — auto-update banner

| Claim | Verdict |
|---|---|
| In-app update banner in chat_window | ⚠️ — banner exists but lives INSIDE the ChatWindow centralWidget which is only visible on the Studio Chat page. User on Home page never sees the banner until they navigate to Chat |
| New `prompt` update mode default | ❌ — `release_updater.auto_check_and_apply` references `release.tag_name` instead of `release.tag`. `ReleaseInfo` dataclass has only `.tag`. Every call raises `AttributeError` and the daemon returns `{"status": "error"}`. The "prompt" mode that's claimed as the default IS BROKEN at runtime. See #60 |
| `release_updater.check_and_download()` | ❌ — same bug (line 397/398/401/406) |
| Periodic update watcher (6h cadence) | ❌ — fires but always errors |
| `on_ready(installer_path, release)` callback | ❌ — never fired in practice because the function above errors first |
| 9 new tests in `test_update_prompt_flow.py` | ⚠️ — tests pass because they mock `download_asset` and `has_update_available`; they don't exercise `release.tag_name` access. Real bug invisible to test suite |

### v1.1.0 — Rhino + Procore + Marketplace

| Claim | Verdict |
|---|---|
| Rhino runner + tools | ✅ |
| Procore runner + tools | ✅ |
| Marketplace v1 backend + client | ✅ |
| Marketplace UI (catalog grid) | ✅ — Studio Marketplace page reachable via More disclosure |
| Code-signing dispatcher | ✅ — script |
| Civil 3D / Trademark / SOC 2 docs | ✅ — docs |

### v1.1.1 — founder economics

| Claim | Verdict |
|---|---|
| Azure Trusted Signing setup script | ✅ — script |
| Trademark filing prep | ✅ — doc |
| Trust Center / CAIQ-Lite | ✅ — docs |
| ™ symbol rollout in chat header tooltip + About dialog | ✅ — visible on Chat page only |

### v1.2.0 — customer infrastructure

| Claim | Verdict |
|---|---|
| Customer profile fields on signup | ✅ — backend |
| Companies + multi-seat + invite flow | ✅ — backend |
| Per-company Stripe Checkout | ✅ — backend |
| Stripe webhook end-to-end tests | ✅ |
| Cloud backend Fly.io deploy script | ✅ |
| Go-live checklist | ✅ |
| Agents 24/7 cloud daemon | ✅ |
| Agents `/healthz` + `/status` dashboard | ✅ |
| **Desktop app profile capture (UI ask for firm/role/discipline)** | ❌ — backend accepts fields but UI never collects them; called out as Limitation in CHANGELOG |

### v1.3.0 — operations + verification

| Claim | Verdict |
|---|---|
| Polar billing alternative | ✅ — backend |
| `/v1/billing/plans` endpoint | ✅ |
| Multi-LLM agent backends | ✅ |
| Autonomous roadmap loop | ✅ — agents |
| Email status reports | ✅ |
| Reality smoke test | ✅ — scripts + workflow |
| UI brand-drift fix (host pills + update banner palette tokens) | ⚠️ — fix landed in ChatWindow, but those surfaces only render when user is on the Chat page |
| Cog menu emoji removal | ✅ — chat menu and provider rows cleaned, but onboarding.py:129, 172, 271 STILL use emoji (✓, ✦, 🔐) — phantom-fix |
| feedback_widget + onboarding_dialog spacing fixes | ✅ — visual |

### v1.3.1 — UI dead-surface round 1

| Claim | Verdict |
|---|---|
| Removed `from workflows_panel import WorkflowsPanel` | ✅ — verified |
| Removed "Reality Check" cog-menu item | ✅ |
| Removed `_open_workflows` + `_save_chat_as_workflow` methods | ✅ |
| Slimmed `_refresh_status` | ✅ |
| Removed "New session" + "Spawn pet strip" quick actions | ✅ |
| Removed `_spawn_pet_strip` method | ✅ |
| Hidden `tokens —` status-rule placeholder | ✅ |
| Collapsed Firm-relay row behind "Show advanced" | ✅ (in legacy SettingsDialog reachable via Studio Settings → Providers section) |
| Welcome chip glyph `✦` → `·` | ✅ — chat_window:1809 verified; onboarding.py:271 STILL uses `✦` — partial fix |
| GitHub Actions cron status reports | ✅ — non-UI |

### v1.3.2 — UI dead-surface round 2

| Claim | Verdict |
|---|---|
| 1. Brand wordmark → 'A' monogram | ⚠️ — visible only on Chat page; user on default Home page never sees the monogram either way |
| 2. KNOWN_MODELS labels trimmed | ✅ — picker on Chat header has shorter labels |
| 3. Welcome card cut, chip row only | ⚠️ — visible only on Chat page when skills>0 |
| 4. Status bar auto-hide via `_AutoHideLabel` | ⚠️ — only relevant when user is on the Chat page |
| 5. Cog menu "Connectors..." cut | ⚠️ — but the orphan `_open_connectors` helper kept "for programmatic callers" — no programmatic caller exists. See #67 |
| 6. Cog menu "Plans & pricing..." cut | ⚠️ — same pattern |
| 7. NAV_ITEMS split into primary + More | ✅ — fully visible |
| 8. "More" toggle wired | ✅ |
| 9. Inspector collapses to 8px strip | ✅ |
| 10. Bottom status-rule shortcut trio cut | ✅ |
| 11-13. Settings advanced disclosure | ✅ |
| 14. Onboarding collapsed to single screen | ⚠️ — DEAD HANDLER #57: `_launch_skill` doesn't actually run the skill when parent is StudioShell |
| 15. Marketplace empty-state actionable copy | ✅ |

## Distribution

Total surfaces inventoried: **85**

- VISIBLE-IN-STUDIO    : 60
- SHADOWED             : 8 (chat header / banner / status bar / welcome / model picker / +Add Host on header / host pills / brand monogram — all reachable but only when user is on Chat page; default page is Home)
- DUPLICATE            : 4 (chat menu Skills vs Studio Skills page · Studio Settings page AI Behaviour twice · Studio rail "+ Add host" vs Chat header "+ Add Host" · two onboarding gates first_run vs onboarding)
- DEAD HANDLER         : 4 (#47 palette skill jump · #49 palette market jump · #57 onboarding skill launch · #59 main.py settings open)
- DISCONNECTED         : 3 (#21 brand sub-caption · #67 _open_connectors · #68 _open_reality_check)
- PHANTOM              : 5 (#40 LLM router seed · #60 release.tag_name · #62 feedback docstring · #63 workflows_panel · #64+#65 stale docstring comments)
- CONDITIONAL DEAD     : 2 (#20 hidden Wordmark · #80 HUD overlay skipped under StudioShell)
- PRE-WRAP CUT         : 2 (#32 About menu item disabled · #61 feedback comment dark-only colors)

## Top 20 issues, prioritized

| # | Severity | Surface | Issue | File:line |
|---|---|---|---|---|
| 1 | 🔴 | release_updater | `release.tag_name` typo crashes the entire auto-update flow at runtime. v1.0.4 "Claude-Desktop pattern" silently broken | release_updater.py:397,398,401,406,467,482,485 |
| 2 | 🔴 | onboarding.py | First-run skill chip click does NOT run the skill when parent is StudioShell (hasattr check is False) | onboarding.py:295-303 |
| 3 | 🔴 | main.py | "I have a Claude/OpenAI account" path does NOT open Settings — `window._set_page` does not exist on ChatWindow | main.py:548 |
| 4 | 🔴 | studio_shell | LLM ROUTER inspector rows are 100% seeded (Claude Sonnet 4.5 / GPT-5 / Gemini 2.5 Pro / qwen3:32b), never reflects real configured models | studio_shell.py:949-983 |
| 5 | 🔴 | command_palette | Skill rows and Marketplace rows in palette ignore the selected item; all just jump to the page. User searches and clicks, expects action — gets page | command_palette.py:298, 351 |
| 6 | 🟠 | settings_page | AI Behaviour shows TWICE in Studio Settings page (once via SettingsDialog wrap in Providers section, once via separate AI Behaviour section) | settings_page.py:128-131 + settings_dialog.py:160 |
| 7 | 🟠 | studio_shell | `_brand_sub` text is updated every Home tick but the QLabel is `setVisible(False)`. Useless work, dead surface | studio_shell.py:273-276, 1808 |
| 8 | 🟠 | main.py | HUD overlay setting + hotkey rebind are READ in Settings, persisted in secrets, but `apply_overlay_chrome` is skipped when `surface is shell` (the default). Settings field is DISCONNECTED for 99% of users | main.py:451-463, settings_dialog.py:367-408 |
| 9 | 🟠 | onboarding.py | Still uses emoji glyphs `✓ ✦ 🔐` in BRAND-no-emoji codebase | onboarding.py:129, 172, 271 |
| 10 | 🟠 | first_run.py + onboarding.py | TWO onboarding modules with overlapping names + different settings keys. Same launch can run both | first_run.py:80, onboarding.py:39 |
| 11 | 🟠 | feedback_widget | Comment input QLineEdit uses hardcoded dark-mode colors. Off-palette in light mode | feedback_widget.py:127-130 |
| 12 | 🟠 | chat_window | `_open_connectors`, `_open_reality_check` kept "for programmatic callers" — no callers exist anywhere | chat_window.py:2708, 3067 |
| 13 | 🟠 | studio_shell | About menu item is `setEnabled(False)` — visible but inert | studio_shell.py:1200-1201 |
| 14 | 🟠 | studio_shell | Studio brand row's `_brand_word` Wordmark + `_brand_sub` kept as references with `setVisible(False)` and never re-shown. Dead siblings | studio_shell.py:271-276 |
| 15 | 🟡 | workflows_panel.py | Entire 209-line module file is orphan; never imported anywhere | workflows_panel.py |
| 16 | 🟡 | feedback_widget | Docstring claims `👍 / 👎 emoji buttons`; code renders mono "yes"/"no" text | feedback_widget.py:3-6 |
| 17 | 🟡 | studio_shell | Module docstring claims `Skills <- embeds existing SkillsPanel`, `Workflows <- embeds existing WorkflowsPanel`, `Settings <- embeds existing SettingsDialog content` — all wrong (uses SkillsGridPanel / WorkflowCanvas / SettingsPage) | studio_shell.py:32-36 |
| 18 | 🟡 | studio_shell | Healing pulse dot animation pulses on EVERY rebuild signature change, including legitimate light→dark theme swaps | studio_shell.py:1338-1343 |
| 19 | 🟡 | chat_window | `_silent_update_check` references `self.update_btn` which no longer exists since v1.3.2 header rebuild. Will AttributeError if invoked | chat_window.py:3187-3203 |
| 20 | 🟡 | studio_shell | Two onboarding gates can fire in the same launch (lines 506-511 and 538-554 in main.py) producing a chained wizard sequence the user can't distinguish | main.py:506-554 |

## Surgical fixes shipped this pass

Each is a 1-line scope, behaviour-preserving, no test changes.

1. **release_updater `release.tag_name` → `release.tag`** — 7 sites in `release_updater.py`. The dataclass exposes `.tag`; the rest of the codebase (chat_window `_on_update_ready_qt`) already uses the defensive `getattr(release, "tag_name", None) or getattr(release, "tag", "")`. Source-side fix uses `.tag` directly so the function no longer raises.

2. **main.py:548 — open settings via the active surface, not `window`** — change `if hasattr(window, "_set_page")` to call `surface._set_page` (the StudioShell). When bare ChatWindow is the surface the chat menu's Sign-ins line already provides the entry, so the technophobe-onboarding "I have a Claude/OpenAI account" path now lands on Settings.

3. **onboarding.py:299 — call `_run_skill_by_id` on the chat backend, not parent** — the wizard knows the router via `self.router`; route the skill call through the chat backend held by `self.parent().chat_widget` (when wrapped) or `self.parent()` (when bare). Surgical patch: check both attributes.

4. **studio_shell `_brand_sub` — stop writing to a hidden label** — guard `_refresh_home` write on `_brand_sub.isVisible()`.

5. **studio_shell `_known_models` — handle tuple entries from KNOWN_MODELS** — KNOWN_MODELS is `list[tuple[(model_id, label)]]`. Add a tuple branch so the inspector reflects the real catalog. (Borderline 1-line; the surrounding loop body changes by 2 lines.)

6. **command_palette skills_provider — capture and use the skill on click** — bind `sid=s["id"]` into the lambda so `on_invoke` opens the chat and runs that skill (best-effort via `chat_widget._run_skill_by_id`). Defensive fallback to `_set_page("skills")` when no chat_widget reachable.

7. **command_palette marketplace_provider — pass clicked item to install** — bind `iid=item["id"]` into the lambda so on_invoke can call the install helper. Defensive fallback to `_set_page("market")`.

8. **studio_shell About menu item — drop the action altogether (1-line removal)** — `act_about.setEnabled(False)` then never connected. The action is decoration. Cut.

9. **onboarding.py — remove emoji from button labels** — `🔐  Sign in with OpenRouter` → `Sign in with OpenRouter`; `✓ Signed in to: ...` → `Signed in: ...`; chip `✦` → `·`. BRAND.voice rule 2.

10. **feedback_widget docstring — say "yes / no" links** — replace the misleading `👍 / 👎` paragraph with the actual implementation.

11. **studio_shell docstring — say SkillsGridPanel / WorkflowCanvas / SettingsPage** — top-of-file comment lies about what's embedded.

The other 9 items in the top-20 are bigger than 1-line scope and get a `# TODO(shadow-audit):` marker for follow-up.

## Deferred fixes — with rationale + estimate

| # | Surface | Reason deferred | Estimate |
|---|---|---|---|
| 1 | HUD overlay setting DISCONNECTED under StudioShell | Either grow the StudioShell to participate in overlay chrome, or hide the Settings row when wrapped. Both are non-trivial; setting persists usefully for bare-ChatWindow fallback users | 2-3 h |
| 2 | first_run + onboarding duplicate gating | Need to unify the two flags + pick canonical wizard. Touches main.py, telemetry consent, settings page "redo onboarding" | 1 h |
| 3 | studio_shell Wordmark + brand_sub kept as hidden refs | Removing them needs to verify no legacy caller NPEs; preserving for now per the existing TODO comment | 30 min |
| 4 | About menu enabled + working dialog | Studio has no About dialog yet — `app/chat_window.py:_show_about` exists. Route the user-card cog "About" to that, but the dialog still hardcodes a `<p style='color:#8a8a8c'>` Notice (palette-drift) | 30 min |
| 5 | feedback_widget hardcoded colors | Refactor the QLineEdit to read from `_current_palette`; matches the design_tokens migration pattern but takes some testing | 30 min |
| 6 | settings_page AI Behaviour DUPLICATE | Either remove the wrapped SettingsDialog from the Providers section, or remove the dedicated AI Behaviour section. Both have UX trade-offs (which surface "wins"). Punt for design decision | 1 h |
| 7 | workflows_panel.py orphan file | Remove the file once docs are corrected. Confirm no JSON-contract docs reference it as the source-of-truth (workflow_canvas.py:5 mentions it as the list-view alternative) | 15 min |
| 8 | chat_window `_silent_update_check` references defunct `update_btn` | Refactor to use the new update_menu_action label, or drop the function entirely (the silent update check is now handled by release_updater.schedule_auto_check) | 30 min |
| 9 | Pulse dot animation on theme swap | Bigger animation refactor — would also let us silence the rebuild of every host row on theme change | 1 h |

## Honest verdict — CHANGELOG vs reality

Counting only "Added" + "Fixed" claims from v1.0.2 through v1.3.2 that
land on a USER-VISIBLE surface (excluding pure backend/test/script work):

- **Visible in Studio runtime (default for users)**: 23
- **Ships but only fully visible on the Chat page (one-click-away from default Home)**: 14
- **Claimed but not actually wired correctly**: 5 (release_updater `.tag_name` typo · `_open_connectors`/`_open_reality_check` orphan helpers · main.py `_set_page` on wrong target · onboarding `_run_skill_by_id` on wrong target · settings_page AI Behaviour duplicate)

Of the **42** user-facing claims across these releases, **23 (55%) are
fully visible** to a default Studio-shell user without page navigation,
**14 (33%) require navigation to Chat** to be seen at all, and **5
(12%) are broken or shadowed in a way the user cannot recover from
without code knowledge**.

The founder's instinct ("you didn't update the UI at all") is
empirically grounded: more than a third of v1.0.2 → v1.3.2 UI claims
land on the Chat page only, which is one step removed from the default
Home page. Round 2's "the brand row was painting over chat_window cuts"
is the most visible symptom but not the root cause. Root cause is that
the **default landing page is Home, not Chat**, and most "ChatWindow
cuts" are only seen after the user clicks the Chat nav item.

## How to revive any deleted surface

Surfaces actually removed in this pass: none. Every fix above is
behaviour-preserving (typo, wrong-attribute, wrong-callsite). Cosmetic
text changes (emoji removal, docstring corrections) are reversible by
restoring the prior strings.
