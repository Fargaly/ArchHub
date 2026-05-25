---
id: AgDR-0045
timestamp: 2026-05-25T00:00:00Z
agent: claude-code (Opus 4.7 · 1M ctx)
session: post-anti-lie-rebuild
trigger: founder pushback 2026-05-25 — "where is firm/community brain · this is shitty not-delivering · take a deep dive on all settings and how it links to brain"
status: executed
founder-signoff: pending — review prototype + this AgDR before slice 9 build
category: architecture
projects: [archhub, personal-brain-mcp]
supersedes: extends AgDR-0044
builds-on: [AgDR-0044]
---

# Settings × Brain — unified architecture

> Every settings surface in ArchHub now resolves through the brain. No
> per-feature pickle file. No JSON sprinkled across `~/.archhub/`. One
> store, four scopes (user / project / firm / community), one ACL.
> Settings sync across devices because the brain syncs. Settings
> sharing across firm seats because the brain shares. Settings federate
> across firms because the brain federates. THIS is what AgDR-0044's
> graph was for.

## Context

Founder identified the gap 2026-05-25: I shipped primitives for firm +
community brain (sync.py, acl.py, federation_server.py) but no RUNTIME
ran them. Settings stayed in scattered files, not in the brain. The
"shared memory across all my devices" promise is unrealised because
each Settings panel persists locally without scope, without ACL,
without sync.

This AgDR + slices 9-16 close the gap.

## Settings surface inventory

Every settings group in ArchHub today + the scope each item belongs in:

| Group | Item | Scope | Sync mode | Sensitive? |
|-------|------|-------|-----------|------------|
| **Identity** | display_name, email, avatar | user | cross-device | no |
| | locale, timezone | user | cross-device | no |
| | preferred_units (metric/imperial) | user | cross-device | no |
| **Models** | active provider | user | cross-device | no |
| | per-provider model id (anthropic.model = sonnet-4-7) | user | cross-device | no |
| | API keys (anthropic, openai, gemini, openrouter) | user | device-local OR reference | **YES — refs only in brain** |
| | per-model temperature, max_tokens | user | cross-device | no |
| **Connectors** | revit_mcp_endpoint, revit_auto_start | user | device-local (per-machine) | no |
| | acad / max / blender / outlook / speckle endpoints | user | device-local | no |
| | speckle.token | user | device-local OR reference | **YES — refs only** |
| | per-connector enabled toggle | user | cross-device | no |
| **Brain** | enabled (master) | user | cross-device | no |
| | daemon_port, autostart, sync_mode | user | device-local | no |
| | sync_folder (when cloud-folder mode) | user | device-local | no |
| | tuning toggles (R1-R4) | user | cross-device | no |
| | llm_critic provider | user | cross-device | no |
| **Skills** | each minted skill | user → project → firm → community | per-scope sync | depends on scope |
| | trigger phrases, examples | follows skill | follows skill | follows skill |
| **Secrets** | every `op://...` reference | user OR firm | reference-only (NEVER value) | **YES** |
| | resolver registry (1password, wcm, vault) | user | device-local | no |
| **Privacy** | telemetry_opt_in | user | cross-device | no |
| | allow_brain_outbound | user | cross-device | no |
| | redaction_strictness | user | cross-device | no |
| | community_subscriptions | user | cross-device | no |
| **Theme/UI** | dark_mode, accent_color, font_size | user | cross-device | no |
| | panel_layouts, pinned_skills | user | cross-device | no |
| **Firm** | firm_id | user | cross-device | no |
| | firm_role (admin/seat) | firm | firm sync | no |
| | firm_seats list | firm | firm sync | no |
| | firm_invite_keypair | firm | firm sync | **YES — private key local** |
| **Project** | active project_id, project_root | user | cross-device | no |
| | per-project model override | project | project sync | no |
| | per-project skill pins | project | project sync | no |
| | per-project secret refs | project | project sync | yes (refs only) |
| **Workflows** | each saved workflow (.archhub-workflow) | user → project → firm | per-scope sync | depends |
| | autostart workflows | user | cross-device | no |
| **Community** | subscribed community URLs | user | cross-device | no |
| | per-community reputation cache | community | federation | no |

## Scope semantics

Reusing AgDR-0044's 5-scope model, applied to settings:

| Scope | Visibility | Reads | Writes | Transport |
|-------|------------|-------|--------|-----------|
| `user` | private | owner only | owner only | device-local SQLite + cross-device via cloud-folder/Tailscale |
| `project` | shared_project | project members | project members | per-project Loro doc |
| `firm` | shared_company | firm seats | firm seats | Loro doc per firm (shared folder/Tailscale) |
| `community` | shared_public | subscribers | promoter (redacted) | Federation outbox + content-addressed pull |
| `global` | canonical | all | maintainers | OSS skill packs |

## Settings storage model

Each setting is a `Fragment(kind=setup)` in the brain:

```python
Fragment(
    id="setting:user.display_name",
    kind="setup",
    text="display_name = 'Ahmed Fargaly'",
    subject="user", predicate="display_name", object="Ahmed Fargaly",
    scope=Scope.USER,
    visibility=Visibility.PRIVATE,
    owner_user="fargaly",
    extra={
        "setting_key": "user.display_name",
        "ui_path": "Settings > Identity",
        "sync_mode": "cross-device",
        "value": "Ahmed Fargaly",   # for primitives; complex values JSON-encoded
        "value_type": "string",
    },
    provenance=Provenance(...),
)
```

Same Fragment system, same query, same sync. No new tables. Settings
ARE memory.

## Secrets — references only, NEVER values

Single Keys & Secrets settings panel. Every provider key stored as:

```python
Fragment(
    id="setting:secrets.anthropic_key",
    kind="secret_ref",
    text="op://personal/anthropic/api-key",
    scope=Scope.USER,
    extra={
        "ref": "op://personal/anthropic/api-key",
        "resolver": "1password",
        "ui_path": "Settings > Keys & Secrets > AI Providers",
        "last4_hint": "...x9k2",          # safe to show in UI
        "added_at": "2026-05-25T...",
        "verified_at": "2026-05-25T...",   # last successful resolve
    },
)
```

Resolvers (a ResolverRegistry maps protocol → handler):
- `op://` → 1Password CLI
- `wcm://` → Windows Credential Manager (current ArchHub default)
- `infisical://` → Infisical
- `vault://` → HashiCorp Vault
- `env://` → environment variable
- `file://` → file (lowest priority; warns)

Resolution happens at PreToolUse hook — value injected, scrubbed from
trace, never persisted.

## Sync architecture per scope

```
user-scope settings:
    cloud-folder mode:  brain.db inside iCloud/OneDrive/Dropbox →
                        Loro CRDT merges concurrent writes
    Tailscale mode:     other devices point BRAIN_HTTP_URL to primary
    Off mode:           device-local only

project-scope settings:
    Loro doc per project_id, lives inside the project folder
    Synced via whatever syncs the project (Speckle stream, Git LFS,
    cloud folder)

firm-scope settings:
    Loro doc per firm_id, lives in firm's shared folder
    OR firm's primary daemon on Tailscale
    Slice 10 ships the scheduled sync worker
    Slice 12 ships the federation daemon for cross-firm

community-scope settings:
    federation outbox publishes PATTERNS (FICAL) not raw settings
    consumers pull and import with reputation gating
```

## UI hierarchy

```
Settings (sidebar)
├── Identity            (user scope, cross-device)
├── Account             (user scope)
├── Models              (user, keys are secret_refs)
├── Connectors          (user, host endpoints device-local; tokens are refs)
├── Brain               (user, prototype shipped in brain-settings-2026-05-25.html)
├── Skills              (per-skill scope; UI shows scope badge)
├── Keys & Secrets      (user, refs only, with resolver picker)
├── Telemetry           (user, cross-device)
├── Privacy             (user, cross-device; bipartite ACL config)
├── Theme               (user, cross-device)
├── Firm                (NEW — Slice 9 ships this)
│   ├── Firm identity
│   ├── Invite teammate
│   ├── Seats list
│   └── Firm sync mode
├── Project             (user, with per-project sub-scope items)
└── Communities         (NEW — Slice 14 ships this)
    ├── Subscriptions list
    ├── Browse known communities
    └── Reputation panel
```

Every settings PANEL shows:
- per-row "scope badge" (USER / PROJECT / FIRM / COMMUNITY)
- per-row "sync mode" indicator (device / cloud / firm / federation)
- per-row "last synced" timestamp
- one-click "promote to shared" flow (calls brain.promote with redaction)

## Bridge slot inventory (Python → JSX)

New slots in `app/bridge.py`:

```python
@pyqtSlot(str, str, str, result=str)
def brain_setting_set(self, key: str, value_json: str, scope: str) -> str: ...

@pyqtSlot(str, result=str)
def brain_setting_get(self, key: str) -> str: ...

@pyqtSlot(result=str)
def brain_setting_list(self, scope: str = "") -> str: ...

@pyqtSlot(str, str, str, result=str)
def brain_setting_promote(self, key: str, target_scope: str, opts_json: str) -> str: ...

@pyqtSlot(str, str, result=str)
def brain_secret_ref_set(self, ref: str, opts_json: str) -> str: ...

@pyqtSlot(str, result=str)
def brain_secret_resolve(self, ref: str) -> str: ...   # returns masked OK or error

@pyqtSlot(result=str)
def brain_firm_create(self, name: str = "") -> str: ...

@pyqtSlot(str, result=str)
def brain_firm_invite_create(self, role: str = "seat") -> str: ...

@pyqtSlot(str, result=str)
def brain_firm_invite_accept(self, token: str) -> str: ...

@pyqtSlot(result=str)
def brain_firm_seats(self) -> str: ...

@pyqtSlot(str, str, result=str)
def brain_community_subscribe(self, actor_url: str, opts_json: str) -> str: ...

@pyqtSlot(result=str)
def brain_community_list(self) -> str: ...

@pyqtSlot(result=str)
def brain_sync_now(self) -> str: ...   # manual sync trigger

@pyqtSlot(result=str)
def brain_sync_status(self) -> str: ...   # last-sync ts per scope
```

## Slices 9-16 mapped to settings

| Slice | What it unlocks |
|-------|-----------------|
| 9 | Settings > Firm tab functional. Create firm. Invite teammate. Join firm via paste-token. |
| 10 | Scheduled sync worker — settings auto-sync across firm seats. |
| 11 | ACL enforcement on every brain.write — firm-scope writes need firm membership. |
| 12 | Federation daemon process — communities can be subscribed to + outbox publishes. |
| 13 | Nightly outbox publish — patterns flow out of the firm. |
| 14 | Settings > Communities functional. Browse + subscribe + reputation panel. |
| 15 | Reputation persists. Cold peer with vouch+identity accept-floor honoured. |
| 16 | Live verify — two daemons, two ArchHub instances, one minted skill crosses. |

## Migration

Existing settings (probably in QSettings INI or scattered JSON):

1. New `bridge.brain_settings_migrate()` slot walks every existing
   ArchHub setting; emits a Fragment per setting; writes via brain.write
   with `kind=setup` and inferred scope (mostly USER for v1).
2. After migration: all settings reads route through
   `brain.context(prompt='settings:<key>')` or
   `brain_setting_get(key)`.
3. Old settings files become read-only fallback for 2 weeks; then
   archived to `~/.archhub/legacy-settings/`.

## Risks

- **Settings churn during sync.** Toggling a setting fast across two
  devices = many writes. Mitigation: HLC timestamps + LWW for
  primitive-typed settings; debounce writes at 200ms.
- **Resolver failure on first launch.** Brain queries a secret ref;
  resolver fails (1Password locked) → tool call fails. Mitigation:
  ResolverRegistry returns a typed `ResolverError` with "Unlock
  1Password" prompt in UI.
- **Firm onboarding mass-write.** New seat joins firm = pulls entire
  firm settings graph (potentially thousands of fragments). Mitigation:
  initial pull as one snapshot, then incremental.
- **Backward compat.** ArchHub currently reads settings synchronously;
  brain is async. Mitigation: cache-on-read; settings are read into
  process memory at startup, written through to brain on change.

## Acceptance criteria

These EXACTLY are how shipping is verified per ANTI-LIE MANDATE:

1. Founder clicks Settings → Identity → changes display_name → restarts
   ArchHub on a SECOND machine → sees the new name. CDP screenshot.
2. Founder clicks Settings → Firm → Create Firm → invites teammate via
   pasted token on second device → second device joins, shows in
   Seats list on both. CDP screenshot.
3. Founder clicks Settings → Communities → Subscribe to a peer URL →
   patterns appear in the brain within 1 sync cycle. CDP screenshot.
4. Founder adds an Anthropic key in Settings → Keys & Secrets → it
   stores as `op://archhub/anthropic/api-key` (verified by inspecting
   brain.db — no plain key) → next Composer turn resolves it
   successfully. CDP screenshot.
