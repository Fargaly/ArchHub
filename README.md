# ArchHub

ArchHub is one persistent, governed, visual graph computer for architecture,
engineering and construction work.

The application, its Brain, Cockpit, Grand Map, website, governance, sessions,
AI work and every domain are regions and lenses of the same graph, not separate
products exchanging copies. Every persisted fact is a composition of one record:

```text
Cell { id, link0, link1, atom }
```

Status: work in progress. `SPEC.md` is the normative target, not a completion
claim. What an exact build has passed is recorded in revision-bound evidence
(`evidence/current-evidence.json`), not in this page.

## Install

Windows only. Download `ArchHub-Setup-0.exe` from the latest release:

<https://github.com/Fargaly/ArchHub/releases/latest>

Run it and open the **ArchHub** shortcut. Application files live in
`%LOCALAPPDATA%\ArchHub`; your graph is kept separately and is not replaced by
installing or updating.

## Updates

The installed application checks the GitHub `releases/latest` record of this
repository. An update is offered only when the release names its build and
publishes the SHA-256 of `ArchHub-Setup-0.exe`; the download is verified
against that hash before it can be applied. The published hash proves byte
integrity, not a signed release. An applied update is accepted only after the
new build boots successfully; until then recovery stays available.

Releases are built by `.github/workflows/release.yml`, which is started by hand
for a reviewed commit. Nothing is published automatically on push.

## One source

This repository is the single source for ArchHub: kernel, application, Studio
canvas, adapters, website, installer and packaging. The public website is
generated from the Cell website in `nodelang/cell_website.py`; it is not a
separate site.

The retired v1 application (the earlier "parametric AEC chat" app) is kept,
unchanged, on the `archive/v1-main` branch.

## Read these first

| file | what it settles |
|------|-----------------|
| `AUTHORITY.md` | which source wins when two disagree |
| `SPEC.md` | what ArchHub is, and the acceptance courts that define "done" (section 11) |
| `RESEARCH-UNIVERSAL-CELL.md` | why the record has this shape |

## Settings and terminals

Every enabled Settings control writes the one source its effect reads, or it
is not drawn (`tests_js/studio_settings_real_controls.test.cjs`):

| control | source | effect |
|---------|--------|--------|
| Theme accent, restore | graph Personal Settings | the Studio redraws in the saved accent |
| BABOOM startup | graph, owner only | BABOOM starts or not at the next launch |
| Model pick (composer chip) | graph `composer_model` | Send, BABOOM, Think and Vision cards use it |
| Cloud publish consent (Account) | `cloud-publish.consent.json` beside the graph, owner only | allowed by the signed-in account: the cloud relay starts at launch; withdrawn, signed out or another account signed in: it stops at its next poll |
| OpenRouter key, social credentials | Windows DPAPI secrets store | provider routing and connector nodes read them |
| Sign in, cockpit link | `cloud.json` | the account the cloud and the relay use |
| Brain rewrite, forget, export | the brain | the fact changes in the brain |

Opening Settings reads only cached or local records: the host list from the
30 s background host probe (the first read after launch says the probe is
still running), the LM Studio/Ollama state from a 10 s background probe
(`checking` until it answers), the consent record and the sign-in record. The
brain is read only when the Brain tab opens, outside the graph lock, with a
4 s budget; a silent brain shows "Brain not answering" and blocks nothing.
The Account identity row states the sign-in record (`cloud_signin.sign_in_state`),
never this page's stored copy.

Removed as ornamental in the same change: Permissions AUTO/ASK/BLOCK switches,
per-host switches, spend cap and meters, sync folder, invented Profile fields,
unbound shortcuts. Per-operation permissions, spend caps, an update channel
and notification settings do not exist in this build.

A **Terminal** card (library `terminal`, engine `library.terminal`) opens a
real shell (`cmd.exe`) STARTED in its `cwd` folder, which must resolve inside
this ArchHub's terminal folder: `workspace` beside the graph
(`%LOCALAPPDATA%\ArchHub\workspace` on a desktop install), or the workspace
root the entry point names. Only the start folder is checked; the running
shell is not a sandbox and can reach anything the Windows user can. Only the
application owner may start one: the terminal route needs `execute` and the
owner, and a canvas Run binds the card with the same check (any other run,
including a Workshop workflow, refuses the card). Output streams into the
card, input is line by line, Stop kills the shell and everything it started
(a Windows Job object with kill-on-close). At most four run at once, each for
at most an hour, below normal priority, 256 KB of output kept. On a canvas Run
the card runs its `command` once and the shell exits (60 s limit); the graph
lock is not held while it runs. Sessions are not saved: they end when ArchHub
closes. Owner: `nodelang/terminal_sessions.py`.

## Layout

| folder | contents |
|--------|----------|
| `nodelang/` | graph kernel, application services, Studio canvas, agent transport |
| `desktop/` | the shell that opens the canvas as an application window |
| `app/`, `bridges/` | credential-store code and host connectors |
| `installer/`, `packaging/`, `infrastructure/` | installer, dependency assets, deployment recipes |
| `public_site/` | static export of the Cell website |
| `tests_replica/`, `tests_domains/`, `tests_js/`, `tests/` | acceptance courts and fixtures |
| `evidence/` | generator for the revision-bound evidence record |
| `tools/` | scripts that drive the graph from outside |
| `legacy_engine/` | superseded engine; nothing in `nodelang/` depends on it |

## Running the courts

```bash
python -m pytest tests_replica -q
```

Courts run against a replica graph, never a live user graph.
