# ArchHub

The Universal Cell kernel and the canvas that runs on it. One persisted
shape — `Cell(id, link0, link1, atom)` — an append-only journal, and an
application projected out of the graph rather than written beside it.

## Read these first, in this order

| file | what it settles |
|------|-----------------|
| `AUTHORITY.md` | which document wins when two disagree |
| `SPEC.md` | what the thing is, and §11 — the seventeen acceptance courts that define "done" |
| `RESEARCH-UNIVERSAL-CELL.md` | why the shape is this shape |

Nothing here is finished because it looks finished. A slice is done when
its applicable courts in `SPEC.md` §11 pass against its exact revision.

## Founder decisions in force (2026-09-15/16)

Recorded here so that no page in this checkout contradicts them. They are
decisions; what has landed is stated per item from the live tree and the
installed build, not implied by the decision. Source record:
`70.HANDOFFS/claude-codex-link-20260914/runtime-adapter-recovery/717-coordinator-state-20260916.txt`
(lines 26-32) and `70.HANDOFFS/archhub-integrated-repair-20260909/DELIVERY-STATUS.md`
(lines 7, 12, 14, 15, 41). Line numbers below were read from the working tree
at HEAD `b914892` (2026-09-16 20:46; `f61ac9b` is four commits below it).

- One source for everything: this checkout. The website's single source is
  the Cell website in `nodelang/cell_website.py`: `PUBLIC_WEBSITE_ROUTES`
  (`:26-34`: `/website`, `/website/features`, `/website/pricing`,
  `/website/changelog`, `/website/security`, `/website/community`,
  `/website/signin`), `read_universal_website` (`:690`) and
  `project_universal_website_document` (`:868`). `nodelang/application_server.py`
  serves those routes from that module (imports `:248-251`), and
  `nodelang/site_export.py` (imports `:17-21`; `build_site_export` `:291-362`;
  `write_public_site` `:365-393`) projects them into
  `public_site/site-export.json`, which `public_site/build.mjs` verifies and
  seals into `dist/`. `public_site/README.md` states that this static export
  carries no runtime, Brain, authentication, billing or database.
  `nodelang/website.py` (`build_website`, `:100`) is the older builder used
  only by `nodelang/application.py` (`:38`, `:2009`); it is neither served by
  the application server nor exported, and its plan cards (`:195-201`) are
  on no served or exported route. The Astro site in `../12.PRODUCTION/web`
  is frozen and is retired after cutover by a tagged git removal
  (recoverable, no hard delete): 717 record line 28. That tree still
  received commit `49db67b` on 2026-09-16 20:41; the freeze is the record's
  word, not a git lock. No record freezes `../12.PRODUCTION/landing` (three
  files, last commit `c8ea60c` of 2026-05-18); its status is unrecorded.
  Deploying `dist/` is a separate credential-bound step and is not claimed
  here (`DELIVERY-STATUS.md` row "NEXT (2026-09-16 evening, Claude717)").
- The cockpit owns product settings.
- Pricing is hidden. There is one offer record, `app:users:accounts:offer`
  (`nodelang/cell_accounts.py:31`, `OFFER_ROOT`; `:39-43`, `BETA_OFFER`:
  `availability` `free-during-beta`, `pricing-visible` `false`,
  `public-label` `Free during beta`). The launcher hands it to the cockpit
  relay (`launch_archhub_test.py:1114-1117`, `_cockpit_offer` calling
  `published_offer`; `:1129`; `nodelang/cloud_relay.py:348-352`) and the
  cockpit shows it with an edit control
  (`nodelang/studio/atlas-cockpit.jsx:456-466`) that relays
  `set offer public-label to "..."` through `/founder/api/command`;
  the `DELIVERY-STATUS.md` row "DONE landed 2026-09-16 12:27 - cockpit
  lane" records that the command handler behind that control does not exist
  yet, so the app refuses rather than pretends. Landed in source at commit
  `b026613` and included in the installed and published build
  `20260916-2105-b914892` (below). No price is published anywhere: the
  served and exported `/website/pricing` route is titled by
  `offer_display_text` (`nodelang/cell_website.py:263-276`, default
  `OFFER_DEFAULT_DISPLAY` "Free during beta", `:260`) and says "No plan,
  checkout, subscription or commercial promise is offered yet."
  (`:290-297`); `public_site/site-export.json` carries "Free during beta"
  three times and no plan name or price literal;
  `tests_replica/test_node_native_website.py:74` holds the route to that
  text. Both `ensure_universal_website` calls
  (`nodelang/universal_application.py:12767-12778`, `:15677-15688`) pass no
  `offer`, so the website shows the module default rather than a read of
  the offer record; wiring the record into the website build is not landed.
  The internal tier vocabulary `free`, `pro`, `firm`, `founder`
  (`cell_accounts.py:33`, `TIERS`) is an account attribute, not a published
  plan. The cloud backend in `../12.PRODUCTION` (`cloud_backend/main.py:1195`
  `GET /v1/offer`; `:1218` `/v1/billing/plans` with no tiers; `:1300`
  checkout `403 checkout_closed`; commit `a7a9f75`) matches this in source;
  its deployment is not claimed.
- Both founder emails are valid: `ahmed.fargaly98@gmail.com` and
  `ahmedfargale@gmail.com` (`nodelang/cell_accounts.py:36`,
  `FOUNDER_EMAILS`), held in the founders relation
  `app:users:accounts:founders` (`:29`, `FOUNDERS_ROOT`; `:114`,
  `_append_founders`, append-only). `../12.PRODUCTION/cloud_backend/config.py:467`
  (`founder_emails`) accepts both in source.
- Brain: port the store and sync into this checkout first; keep the
  server-side search as it is for now; skills stay unencrypted; review is
  internal only; the website keeps the truthful M0 privacy sentence (717
  record line 31). None of that port has landed: `personal_brain/` here holds
  four files (`__init__.py`, `ambient_policy.py`, `hook_coverage.py`,
  `installer.py`) and no store, sync or server. The legacy daemon in
  `../12.PRODUCTION/personal-brain-mcp` is what runs: the Startup entry
  `ArchHub-Brain.vbs` starts `pythonw.exe -m personal_brain.service supervise
  --port 8473` (717 record line 4: restarted 2026-09-16 11:00:22, pid 42508).
  The M0 sentence the website is to carry reads: "When cloud sync is on,
  ArchHub keeps a copy of your brain on our servers so it can reach your
  other devices and your firm. That copy is not end-to-end encrypted, and
  ArchHub's systems can read it. Recognised API-key formats are blocked from
  upload. Deleting your cloud brain removes your personal copy; entries you
  shared with a firm are not removed." Its text lives in the `/website/security`
  card "04 What cloud sync holds" (`nodelang/cell_website.py:314`, commit
  `063b3ae`) and in the sealed export `public_site/site-export.json`; no
  deployment of that export is claimed, so it is on no public website today.
  The frozen `../12.PRODUCTION/web/src/pages/security.astro:46` and
  `brain.astro:34` carry the same text in source (commit `49db67b`).
- BABOOM persistent startup control, approved as designed (717 record line
  32: next launch, fail-closed, owner-only, `app:agent-body:baboom`, relay
  reads allowed while off). Landed in source at commit `f61ac9b`, first
  installed as build `20260916-1740-f61ac9b` (17:47, boot 72 s) and now
  installed as `20260916-2105-b914892` (`%LOCALAPPDATA%\ArchHub\BUILD_ID`
  written 20:53; `%LOCALAPPDATA%\ArchHub-Test\boot-profile.log` "boot 67s";
  `launcher.log` "BABOOM : attached (signed agent session)"). Publicly
  released 20:58 as GitHub release `build-20260916-2105-b914892`
  (`DELIVERY-STATUS.md` row "DONE installed 2026-09-16 20:53"); Settings,
  the persistent control and the installed native-agent path are not
  accepted (row "BLOCKED / OPEN"). What the code does, including what it
  reads when no record exists, is in `BABOOM.md`.
- The founder is handed no manual tasks.
- Governed-write enrollment defects A, A2, B and C (2026-09-16) and the
  working enrollment recipe are recorded in `docs/NATIVE-OWNER-RECOVERY.md`;
  the installed hooks still pass the `claude-code` alias
  (`~/.claude/settings.json` lines 74, 85 and 136).

## Where the work is

| folder | what lives there |
|--------|------------------|
| `nodelang/` | graph kernel, application services, Studio and agent transport adapters |
| `app/`, `bridges/`, `archhub.ico` | application credential-store code, host connectors and owned icon |
| `personal_brain/` | retained read-only hook-observation dependency with inert package initialization; no Brain server (four files). The brain store and sync are to be ported here first (founder decision 2026-09-15/16, above); until that lands, the legacy daemon in `../12.PRODUCTION/personal-brain-mcp` runs from its own Startup entry on port 8473 |
| `tests_replica/` | the courts. Run against a replica graph, not the live one. |
| `tests_domains/`, `tests_js/`, `tests/` | domain fixtures, the jsdom interaction probe, and one replica-server court |
| `evidence/` | `build_current_evidence.py` → `current-evidence.json`, the record that binds a green claim to a source hash |
| `desktop/` | the shell that opens the canvas as an application window |
| `installer/`, `packaging/`, `infrastructure/` | selected installer, dependency assets and deployment recipes |
| `public_site/`, `docs/` | `public_site/`: the sealed static projection of the Cell website (`nodelang/cell_website.py` routes, written by `nodelang/site_export.py` as `site-export.json`, sealed by `build.mjs` into `dist/`); deploying `dist/` is a separate credential-bound step, not claimed here. `docs/`: this checkout's pages |
| `domain_sessions/` | saved graph sessions used as fixtures |
| `tools/` | scripts that drive the graph from outside: servers, sweeps, one-shot builders |
| `legacy_engine/` | the superseded engine (`node_lang.py`) and everything that imports it. Not the kernel. Nothing in `nodelang/` depends on it. |

## Running it

Open the installed **ArchHub** shortcut. The selected release path is
`.github/workflows/release.yml` → `installer/build_release.ps1` →
`installer/ArchHub.iss`. The installed `ArchHub.vbs` runs
`launch_archhub_test.py`; that historical filename is the current desktop entry,
not an isolated test application. The secondary PyInstaller recipe is not the
selected updater artifact.

The current source launcher prepares a private Python environment at
`%LOCALAPPDATA%\ArchHub\.venv`. Setup uses isolated pip and excludes inherited
Python paths and user-site packages. Later launches validate that environment
and a readiness marker tied to `BUILD_ID` and the requirements hash before
opening the application through its own `pythonw.exe`. The marker is a setup
cache, not a signature or proof that all installed application files are intact.

Updates reuse the environment and apply the shipped dependency constraints
before recording the new build as ready. A missing or redirected environment
component fails visibly; setup does not delete an existing environment or fall
back to shared packages. A damaged environment needs explicit repair; rerunning
the installer alone is not established as repairing it. Failed dependency setup
leaves its error window open. These source changes await installed acceptance.

The existing installation preserves its graph at
`%LOCALAPPDATA%\ArchHub-Test\archhub-test.universal.sqlite3`.
Its adjacent runtime descriptor identifies the owner; the normal launcher
announces that same signed owner in
`%LOCALAPPDATA%\ArchHub\active-universal-runtime.json` for agent clients.
Explicit isolated runs use separate state and do not replace that announcement.
Ports are deployment details; use the authenticated handoff from the selected
owner instead of assuming a fixed URL. Keep its access credential local.

Only one process may own an instance database. Starting a separate coordination
service against another graph is not the installed application workflow.
For approved external SQLite inspection, use URI
`mode=ro` with the live database and its WAL available. Do not use
`immutable=1` on a database that can change, and never open it for writing
behind the owner's back.

## Workshop integration

Workshop uses the existing Session Link transport in `nodelang/session_link/`.
The application owns agent admission, node wiring, approved work, indexed
conversation records and results. Session Link carries addressed requests and
replies; it does not create a second Workshop or Brain authority.

The connection flow is: authenticate the existing native agent session → obtain
its application-instance scope → delegate the exact existing host connection →
attach it to that session → route approved messages through its channel.
Multiple agents share the Workshop, with bounded per-session channels and no
idle process per channel. Disconnecting one agent must leave others connected.
Parent-shell identity is cleared when the application creates its transport.

These connection changes are under integration; source code and passing checks
do not imply they are present in an installed release. The transport contract,
provider limitations and lifecycle ordering are documented in
[`nodelang/session_link/README.md`](nodelang/session_link/README.md).
Real acceptance requires addressed native replies and a reviewed work artifact
inside the installed Workshop, plus save/reopen without replacing instance state.

## Packaging and recovery status

Connector assets, credential-store code and the physical hook observer now live
in this canonical checkout. The observer reuses three existing modules under an
inert `personal_brain` namespace; importing it does not load the legacy server,
storage or cloud components. Only `observe_runtime_compliance` is admitted by the
application court. Retained installer/repair/monitor functions are legacy code,
not supported application entrypoints. Observation of configuration does not
prove that a native hook executed.

The source launcher no longer starts a separate Brain on port 8473, polls it or
kills a port holder. Brain belongs to the existing application instance owner.
The selected installer now consumes only this canonical checkout; no component
checkout or `ComponentsRoot` parameter remains. Installed acceptance is open. Credentials
stay in user custody; only generic credential-store code enters the package.

Updates must preserve instance identity and user data, retain a verified recovery
path, and activate reviewed package bytes. Starting a backend alone does not
prove desktop, Workshop, connectors, settings or update acceptance. Maintain
revision-bound evidence and explicit remaining gaps for the installed artifact.

The source updater explicitly disables installer-driven application closing and
restarting, in both installer defaults and its silent invocation. ArchHub's own
admitted save/stop/update handoff controls its lifecycle; unrelated applications
must remain running. `/NORESTART` alone only prevents a system reboot. See the
[Inno Setup command-line contract](https://jrsoftware.org/ishelp/topic_setupcmdline.htm).
This source repair is not an installed behavior claim or a diagnosis of a prior closure.

### Build a reviewed local candidate

Application files live in `%LOCALAPPDATA%\ArchHub`; the existing user's graph
remains in `%LOCALAPPDATA%\ArchHub-Test`. Updating application files is not a
reason to replace or recreate that database.

An update is downloaded and hash-verified before it can be applied. The selected
restart/update action hands off saved state to the installer. Installer success
means the update is awaiting a successful new boot, not already accepted: setup
or boot failure leaves recovery and the staged package available for
reconciliation. Do not repeatedly run an installer whose outcome is uncertain.
The fixed `ArchHub-Setup-0.exe` filename is the updater asset name; build identity
and ordering come from release metadata, not that suffix.

From the canonical checkout, use the existing builder's
`-PrepareCandidateManifest` mode with a `candidate-*` build ID and a new
`-OutputDirectory` under governed product WIP or handoffs, outside the source
checkout. It inventories admitted source serially and writes a V2 candidate
manifest and its SHA256 without compiling or launching the application.

Review that inventory, then invoke `installer/build_release.ps1` with the same
`-BuildId`, the saved `-LocalCandidateManifest`, its
`-LocalCandidateManifestSha256`, and a different new `-OutputDirectory`.
The build requires installed Inno Setup 6 and the pinned Windows x64 Node
24.13.0 executable. Changed source bytes invalidate the inventory: prepare and
review a fresh one. V1 manifests and second-source rows are rejected.

Candidate preparation is not package acceptance. Public releases retain the
clean committed-input checks and explicit publishing action. Building a local
candidate does not install, publish or change a running user's instance.

## Running the courts

```bash
python -m pytest tests_replica -q
```

`pyproject.toml` sets `pythonpath = ["."]` and a court holds it there, so
top-level packages import by name: `nodelang`, `tools`, `legacy_engine`.

Two timing logs answer "why was that slow", both under the authority
directory: `boot-timing.log` (per boot phase) and `gesture-timing.log`
(per projection, with the lens split by phase).
