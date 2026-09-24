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
