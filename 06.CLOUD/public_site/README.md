# Public website export: historical location

The active static website generator is
[build_site.py](../../03.TOOLS/packaging/website/build_site.py).
See the [publish step](../../03.TOOLS/packaging/README.md#website-publish-step)
for the one links source, release inputs, preview and deployment commands.

Historical instructions in this README described a Cell-based export through
`cell_website.py` and `site_export.write_public_site`. That generator was removed
on 2026-11-07 (9afdeaa4). Those instructions remain in Git history; they are not
an active publication path. `site_export.py` still supplies in-app documentation;
the static generator reads selected literal documentation without starting the
application or loading a graph.

Generated output belongs in an untracked output folder, never here as a second
website source. The active export has Home, getting-started Docs, Community,
Changelog and a 404 page, with self-hosted fonts and their licences.
