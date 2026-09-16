# ArchHub public website image: the Cell website, exported to static files
# and served by BusyBox httpd.
#
# One source: nodelang/cell_website.py, exported by nodelang/site_export.py
# (the same exporter that writes public_site/site-export.json).  The frozen
# 12.PRODUCTION/web Astro site is not built here.
#
# Build context: the 13.NODE-LANGUAGE repository root, filtered by
# packaging/website/.dockerignore (fly.toml build.ignorefile): only nodelang/,
# packaging/website/httpd.conf and packaging/website/offer.json are sent to
# the builder.  Deploy from the repository root:
#
#   flyctl deploy . --config packaging/website/fly.toml \
#       --build-arg OFFER_SHA256=<sha256 of the offer record>
#
# packaging/website/offer.json is the canonical offer record of
# app:users:accounts:offer as nodelang/cell_accounts.py publishes it, a JSON
# object {"availability", "pricing-visible", "public-label"}, written next to
# this file before the build; it is gitignored, never tracked.  The exporter
# recomputes the record's sha256 and refuses to build unless it equals
# OFFER_SHA256, so a wrong or stale record fails the build instead of
# reaching archhub.io.

# ---- build stage: export the Cell website to /site/dist -------------------
FROM python:3.12-slim AS build
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /build
# The export path imports exactly these third-party packages (proven by
# running the exporter in a clean 3.12 venv); the ranges follow requirements.txt.
RUN python -m pip install --no-cache-dir \
        "rpds-py>=0.30,<1" "cryptography>=48,<49" "httpx>=0.28.1,<1"
# nodelang carries the public map seed (nodelang/data/public_runtime_map.json);
# the export builds from that seed, never from local authority.
COPY nodelang /build/nodelang
COPY packaging/website/offer.json /offer/offer.json
ARG OFFER_SHA256
RUN test -f /build/nodelang/data/public_runtime_map.json \
    && test -n "$OFFER_SHA256" \
    && python -m nodelang.site_export --offer /offer/offer.json --offer-sha256 "$OFFER_SHA256" --origin https://archhub.io --output /site

# ---- serve stage: BusyBox httpd on port 3000 (fly.toml internal_port) ------
FROM lipanski/docker-static-website:2.1.0
COPY --from=build /site/dist .
# Our own httpd.conf: a missing URL gets the exported 404.html instead of
# the built-in BusyBox body.  httpd refuses to serve its own config file.
COPY packaging/website/httpd.conf ./httpd.conf
CMD ["/busybox", "httpd", "-f", "-v", "-p", "3000", "-c", "httpd.conf"]
