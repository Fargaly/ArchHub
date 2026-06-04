# ArchHub web

The marketing + docs site for ArchHub. Static Astro 4 site.

**Key property: the deploy build is a pure `astro build` with NO live daemon.**
All content the pages need is COMMITTED under `src/data/` + `public/`. A
maintainer regenerates that committed content from live sources with
`npm run refresh-content` — that step is optional and never runs during deploy.

## Quick start

```bash
npm install      # uses the committed package-lock.json
npm run build    # pure `astro build` — no daemon, no network. Output → dist/
npm run preview  # serve dist/ locally on :4321
```

## Deploy (founder — ONE action to go live)

The site deploys to Fly.io (consistent with `cloud_backend`). The config is in
`web/Dockerfile` (multi-stage: Node builds, BusyBox httpd serves `dist/`) +
`web/fly.toml`.

```bash
cd web
fly launch --no-deploy     # first time only: creates the app, keep this fly.toml
fly deploy                 # builds + ships the static site
fly certs add archhub.io   # attach the custom domain AFTER DNS points at the Fly app
```

That's it — no secrets, no volume, no env. The three remaining founder-only
bits are: (a) authorizing the Fly deploy / spend, (b) pointing the `archhub.io`
DNS at the Fly app + running `fly certs add`, (c) the pricing-model + brand/hero
copy decisions (the site renders whatever `cloud_backend/billing.py` says).

## Refreshing committed content (maintainer, optional)

When the app's connectors, pricing, brain graph, or community skills change,
regenerate the committed content and commit the diff:

```bash
npm run refresh-content
git diff web/src/data web/public/brain   # review, then commit
```

`refresh-content` runs four sub-steps (each independent — one failing does not
abort the rest):

1. **`build-info.js`** — writes `src/data/build-info.json`: git sha + date (for
   the per-page footer) and the REAL connector + operation counts, derived from
   `app/connectors/*_connector.py`. No daemon, no app boot.
2. **`copy-brain-viz.js`** — copies the in-app brain graph
   (`app/web_ui/brain-graph.html` + `brain-graph-data.json`) into
   `public/brain/` so `/brain` is a build-stable route.
3. **`extract_pricing.py`** — writes `src/data/pricing.json` from
   `cloud_backend/config.py` (needs `../cloud_backend`). Best-effort.
4. **`from-brain.js`** — writes `src/data/skills-export.json` from
   `brain.skill_export` (needs the brain daemon on :8473). Best-effort; if the
   daemon is down the existing committed export is left untouched (no zeroing).

## Pages

| Route        | File                        | Source of content                                         |
|--------------|-----------------------------|-----------------------------------------------------------|
| `/`          | `src/pages/index.astro`     | Hero + 3 pillars; connector/op counts from `build-info.json` |
| `/features`  | `src/pages/features.astro`  | `src/data/skills-export.json` (honest empty state when 0) |
| `/pricing`   | `src/pages/pricing.astro`   | `src/data/pricing.json` (from `cloud_backend/billing.py`) |
| `/community` | `src/pages/community.astro` | Honest "federation not yet active" state (no fake leaderboard) |
| `/security`  | `src/pages/security.astro`  | Static prose; references `docs/CAIQ_LITE.md` + `docs/TRUST_CENTER.md` |
| `/changelog` | `src/pages/changelog.astro` | Build-time read of the repo's real `CHANGELOG.md`         |
| `/brain`     | `public/brain/index.html`   | The real in-app brain-graph viz (copied verbatim)         |

## Footer freshness

Every page footer shows `built from commit <sha> on <date>`, stamped at build
time in `src/layouts/Base.astro` from `src/data/build-info.json`. (This replaced
a brittle post-build HTML rewrite that always printed "unknown" because it
couldn't match Astro's scoped `data-astro-cid` attributes.)

## Env vars (only for the optional refresh-content step)

| Var                 | Default     | Purpose                              |
|---------------------|-------------|--------------------------------------|
| `BRAIN_HOST`        | `127.0.0.1` | Brain MCP daemon host                |
| `BRAIN_PORT`        | `8473`      | Brain MCP daemon port                |
| `BRAIN_SKILL_SCOPE` | `community` | Scope passed to `brain.skill_export` |
| `BRAIN_SKILL_LIMIT` | `100`       | Max skills pulled per refresh        |

## What's NOT in scope here

- No CMS — committed JSON under `src/data/` is the content; the brain is the
  upstream source the refresh step pulls from.
- No analytics — the cloud backend handles per-user telemetry separately.
- No client-side state — every page is pre-rendered static HTML.
