# ArchHub marketing/docs site — static Astro build served by a tiny BusyBox
# httpd. Two stages: (1) Node builds the pure-static site (NO daemon needed —
# `astro build` reads committed content under src/content/ + public/), then
# (2) the built dist/ is copied into a ~150 KB static image.
#
# Deploy (founder, one action): `cd web && fly deploy` (after `fly launch
# --no-deploy` once to create the app + pick a name). Consistent with
# cloud_backend which also deploys to Fly.

# ---- build stage -----------------------------------------------------------
FROM node:20-alpine AS build
WORKDIR /app

# Install deps from the committed lockfile for reproducibility.
COPY package.json package-lock.json ./
RUN npm ci

# Build the static site. prebuild is gone — this is pure `astro build`.
COPY . .
RUN npm run build

# ---- serve stage -----------------------------------------------------------
# lipanski/docker-static-website is BusyBox httpd — tiny, no shell server,
# serves a directory of static files. Listens on $PORT (default 3000); Fly's
# http_service.internal_port matches it (see fly.toml).
FROM lipanski/docker-static-website:2.1.0
COPY --from=build /app/dist .
# httpd.conf is optional; the base image serves ./ on 3000 by default.
CMD ["/busybox", "httpd", "-f", "-v", "-p", "3000"]
