# ArchHub

ArchHub is a visual node app: blocks wired on a canvas, saved as `.archhub` files. It works with any agent installed on the PC. Nothing runs until you press Run, unless you set an explicit trigger.

## Links

<!-- PUBLIC LINKS:BEGIN -->
| Surface | Link |
| --- | --- |
| repo | [GitHub repository](https://github.com/Fargaly/ArchHub) |
| release | [Latest release](https://github.com/Fargaly/ArchHub/releases/latest) |
| site | [Website](https://archhub.io) |
| docs | [Getting started](https://archhub.io/docs/getting-started/) |
| community | [Community](https://archhub.io/community/) |
| baboom | [BABOOM](https://baboom.archhub.io) |
| notion | [Notion](https://www.fargool.com/archhub) |
| issues | [Report a problem](https://github.com/Fargaly/ArchHub/issues) |
| discuss | [GitHub Discussions](https://github.com/Fargaly/ArchHub/discussions) |
| font-license | [Font licence](https://openfontlicense.org) |
| font-source | [JetBrains Mono source](https://github.com/JetBrains/JetBrainsMono) |
<!-- PUBLIC LINKS:END -->

| Find | Open |
| --- | --- |
| Desktop source | [nodelang](01.APP/nodelang/) |
| Website source and exporter | [build_site.py](03.TOOLS/packaging/website/build_site.py) · [publish instructions](03.TOOLS/packaging/README.md) |
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
