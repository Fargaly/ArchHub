# ArchHub

One visual workspace for architecture, engineering and construction.
The desktop app brings Studio, Workshop, Brain, connectors and BABOOM together.
BABOOM is the companion; supported AI providers are engines it can route work to.

| Find | Open |
| --- | --- |
| Install the Windows app | [Latest release](https://github.com/Fargaly/ArchHub/releases/latest) |
| Website | [archhub.io](https://archhub.io/) |
| Documentation | [Getting started](https://archhub.io/04.DOCS/getting-started/) |
| Desktop source | [nodelang](01.APP/nodelang/) |
| Website source and exporter | [public_site](06.CLOUD/public_site/) · [site_export.py](01.APP/nodelang/site_export.py) |
| Cockpit and cloud source | [cloud_backend](06.CLOUD/cloud_backend/) |
| Tests | [02.TESTS](02.TESTS/) |
| Build, installer and compiler tools | [03.TOOLS](03.TOOLS/) |
| Evidence | [05.EVIDENCE](05.EVIDENCE/) |
| Contribute | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Security | [SECURITY.md](SECURITY.md) |
| Source documentation | [04.DOCS/README.md](04.DOCS/README.md) |
| Catalogue reference | [04.DOCS/CATALOGUE.md](04.DOCS/CATALOGUE.md) |

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
