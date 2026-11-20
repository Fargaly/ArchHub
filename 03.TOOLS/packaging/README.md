Build-time compilation, licenses and platform packaging helpers.

## Website publish step

The one public links source is `03.TOOLS/packaging/links.json`; its reader is
`03.TOOLS/packaging/links.py`. The generated README Links table, every page footer
and the Community destinations all read it. Edit addresses there and regenerate
the README table. The repository, latest release, website, Docs, Community,
and BABOOM are linked from that source. Issues and Discussions are listed
there too. Publishing this site does not update the content of external surfaces;
the coordinator reconciles those at release time.

The active generator is `03.TOOLS/packaging/website/build_site.py` (stdlib only).
It reads `CHANGELOG.md`, the links reader, selected literal in-app documentation
from `01.APP/nodelang/site_export.py`, and existing licensed fonts. It never
imports the application, catalogue runtime or retired Cell graph. The previous
`cell_website.py` publication path was removed; its instructions survive in Git
history, not as a second publisher.

The page layout follows frozen `archhub-directions-v48/site.html`. The four
1600 × 1000 PNG screens under `website/assets/` are headless renders of that
design's `index.html`: Home, Canvas, Library and the Session node with its thread.
Captions identify design/example data rather than completed work. The generator
copies these assets and root branding into its output. The Docker build includes
both asset directories and retains the coordinator's runtime static COPY.
Public release notes omit source lines and commit identifiers; `CHANGELOG.md`
keeps them. Exact build, installer name and SHA-256 come from the newest release's own `release.json`, which `/download.json` redirects to.

At release time, fill the empty `Next build` section of `CHANGELOG.md` with the
actual build id and release notes, or replace that heading with the build id.
Keep the newest entry first. Notes describe Git changes, not unverified installed
behavior. Pass the exact published installer's build id, asset URL and SHA-256
from the verified release; they label the build line shown before the page reads
the newest release. The Download button itself is GitHub's fixed latest-release
address and `/download.json` is a redirect to the newest release's own
`release.json`, so both follow every release without a redeploy. Do not invent a
hash or label one build's installer with another build id.

From a clean checkout of the reviewed website commit, put the exact Git revision
in `$WebsiteSource` and the verified published release values in `$BuildId`,
`$InstallerUrl` and `$InstallerSha256`. Use a new `$OutputFolder` outside the
checkout for the deploy context:

```powershell
if ((git rev-parse HEAD).Trim() -cne $WebsiteSource) { throw 'Website source revision differs.' }
if (git status --porcelain --untracked-files=all) { throw 'Website checkout must be clean.' }
if (Test-Path -LiteralPath $OutputFolder) { throw 'Choose a new website output folder.' }
$SiteTools = '03.TOOLS/packaging/website'
python -B "$SiteTools/export_catalogue.py"
if ($LASTEXITCODE -ne 0) { throw 'Public catalogue export failed.' }
python -B "$SiteTools/build_site.py" --build-id $BuildId --installer-url $InstallerUrl --sha256 $InstallerSha256 --output $OutputFolder --deploy-context
if ($LASTEXITCODE -ne 0) { throw 'Public site build or identity scan failed.' }
```

Review all four pages in the output folder and confirm each footer and build id.
The output also includes `404.html` and font assets. A preview is not deployment.
The builder scans all generated HTML before writing the Fly context. The
generated serving configuration lives alongside the public `site/` directory.
The image serves that directory with Caddy, which sends
`/download.json` to the latest release record, redirects `/baboom` to
baboom.archhub.io, and proxies BABOOM chat and sign-in.

The coordinator deploys that output after review:

```powershell
flyctl deploy $OutputFolder --config (Join-Path $OutputFolder 'fly.toml')
```

After publication, read back Home, Docs, Community and Changelog on the public
site, check their build line, that Download and `/download.json` lead to the
newest release, and all footer destinations. Confirm the GitHub release and BABOOM
references agree before announcing them.
The website-and-links builder only prepares branch commits and a local preview;
it does not push, publish, deploy or install.
