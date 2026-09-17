# ArchHub public website export

The website has one source: the Cell website in `nodelang/cell_website.py`,
exported by `nodelang/site_export.py`. `site-export.json` is the sealed
static projection it writes; it is generated, never edited by hand. This
README is the one hand-maintained, tracked file here: the exporter writes
no README.

`write_public_site(store, registry, project_dir, *, offer, offer_sha256,
origin)` writes exactly `<output>/site-export.json`, `<output>/.gitignore`
and `<output>/dist/` holding `index.html`, `features/index.html`,
`pricing/index.html`, `changelog/index.html`, `security/index.html`,
`community/index.html`, `signin/index.html`, `assets/site.css`,
`assets/fonts.css`, `404.html`, `robots.txt`, `sitemap.xml`, one redirect
page for each retired address of the old site, the brand files
`favicon.ico`, `favicon.svg` and `og.png`, and the font files and their
licences under `assets/fonts/`, copied byte for byte from
`nodelang/data/website/`, in Python, with root paths and rewritten hrefs.
It writes nothing else. `dist/` stays untracked (see `.gitignore`).
`404.html`, `assets/fonts.css` and the redirect pages are the only files
typed in `site_export.py`, not projected from the graph.

Every page loads the three font families the graph stylesheet names from
`assets/fonts.css` on the same site, because the stylesheet may not fetch
anything itself; no page asks another host for a font. Each font is the Latin
subset, in woff2, that fontTools 4.62.1 cut from a local font file: Instrument
Serif Version 1.000 regular and italic and JetBrains Mono Version 2.211
regular from their TTF files, and Inter Version 4.001 from the `Inter.woff2`
that Blender 5.1 ships, held at optical size 14 over weights 400 to 600. The
name table of each font says it is under the SIL Open Font License 1.1; that
licence, headed by the copyright line of the same name table, travels beside
the fonts as `OFL-InstrumentSerif.txt`, `OFL-Inter.txt` and
`OFL-JetBrainsMono.txt`. Every page links `favicon.ico` and `favicon.svg`;
with an origin every page also names `og.png` as its share image.
`site-export.json` records each copied file by size and sha256, and the
writer refuses a file whose bytes no longer match.

The export is refused unless the graph offers a released download and every
page links it; `site-export.json` records that download's revision, address
and sha256. A new website graph receives `cell_website.PUBLIC_RELEASE`
through `cell_website_meta.record_release`, `hold_artifact` and
`offer_download`, and the pages read the address back from the graph. An
address that does not name its revision, such as a `releases/latest` link,
is refused. A graph whose website already exists is read, not rebuilt, so it
keeps the pages it was built with.

The retired addresses are the pages the old site answered at (`/docs/` and
its five guides, `/gallery/`, `/account/`, `/brain/`); BusyBox httpd has no
redirect directive, so each one is a static page that refreshes to the
closest live page and names it as canonical.

The `--offer` file is the canonical offer record of
`app:users:accounts:offer` as `nodelang/cell_accounts.py` publishes it: a
JSON object `{"availability", "pricing-visible", "public-label"}`.
`site_export` recomputes
`hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"),
ensure_ascii=True).encode("utf-8")).hexdigest()` and refuses unless it
equals `--offer-sha256` and equals what `cell_accounts.published_offer()`
would publish for that record. `site_export` maps the record to the website
offer `{"display": public-label, "monetary": pricing-visible == "true"}` for
`cell_website.offer_display_text`.

Regenerate from the repository root. Write the record to
`packaging/website/offer.json` (gitignored) and export with its digest:

    python -c "import hashlib,json;from nodelang.cell_accounts import BETA_OFFER as o;b=json.dumps(o,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8');open('packaging/website/offer.json','wb').write(b);print(hashlib.sha256(b).hexdigest())"
    python -m nodelang.site_export --offer packaging/website/offer.json --offer-sha256 <sha256 printed above> --origin https://archhub.io --output public_site

The image in `packaging/website/Dockerfile` runs the same export and serves
`dist/` with BusyBox httpd on Fly (`packaging/website/fly.toml`).

The deployment boundary is intentionally static. It contains no application
runtime, Brain, private Grand Map, authentication, billing, database, storage,
credentials, or live cloud resource identifiers.
