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
`community/index.html`, `signin/index.html`, `assets/site.css`, `404.html`,
`robots.txt` and `sitemap.xml`, in Python, with root paths and rewritten
hrefs. It writes nothing else. `dist/` stays untracked (see `.gitignore`).
`404.html` is the one page typed in `site_export.py`, not projected from
the graph.

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
