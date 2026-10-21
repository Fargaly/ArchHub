# ArchHub

One visual workspace for architecture, engineering and construction.
The desktop app brings Studio, Workshop, Brain, connectors and BABOOM together.
BABOOM is the companion; supported AI providers are engines it can route work to.

| Area | Purpose |
| --- | --- |
| [01.APP](01.APP/README.md) | Desktop packages, native bridges, installer and packaging |
| [02.TESTS](02.TESTS/README.md) | Python, JavaScript and Workshop checks |
| [03.TOOLS](03.TOOLS/README.md) | Compiler, pipeline, infrastructure and editor configuration |
| [04.DOCS](04.DOCS/README.md) | Indexed product and engineering documentation |
| [05.EVIDENCE](05.EVIDENCE/README.md) | Small versioned policy inputs; generated runs stay out of Git |
| [06.CLOUD](06.CLOUD/README.md) | Cloud backend and public website source |

[Latest Windows release](https://github.com/Fargaly/ArchHub/releases/latest) · [Website](https://archhub.io/) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md).
GitHub discovers the release workflow in the platform-required `.github/workflows` folder.

## Install and update

Download `ArchHub-Setup-0.exe` from the latest release and run it.
The updater uses this repository's release feed and verifies the published
installer hash. A hash checks integrity; it does not establish a signed release.
Keep the repository name and release asset names stable when organising source.

## One source

This checkout owns the desktop app, website, cloud services, documentation and
packaging. Native package names stay unchanged. Workspace navigation points to
this source; it does not create another app or checkout.

Public source is separate from user graphs, credentials, company records and
client projects. Build and test evidence describes its exact revision and scope;
this README does not claim every target feature is complete.

## Licence

No root licence file was found in the audited public revision. The owner must
select the licence before a licence grant is added here. No licence is selected
by this documentation patch.
