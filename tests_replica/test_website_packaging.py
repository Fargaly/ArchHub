"""Static courts for the public website package.

The website has one source, the Cell website exported by
nodelang.site_export.  packaging/website builds that export inside a Python
stage and serves the rendered dist/ with BusyBox httpd on Fly; public_site/
tracks the sealed export, its hand-maintained README and .gitignore, and
nothing that hosts it.  These courts read the files as text and ask git
about the tree: no docker build, no application build, no
application_server.
"""
from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packaging" / "website"
DOCKERFILE = PACKAGE / "Dockerfile"
HTTPD_CONF = PACKAGE / "httpd.conf"
FLY_TOML = PACKAGE / "fly.toml"
DOCKERIGNORE = PACKAGE / ".dockerignore"
PUBLIC_SITE = ROOT / "public_site"
OFFER_RECORD = "packaging/website/offer.json"
BUILD_BASE = "python:3.12-slim"
SERVE_IMAGE = "lipanski/docker-static-website:2.1.0"
EXPORT_FLAGS = (
    "python -m nodelang.site_export",
    "--offer /offer/offer.json",
    "--offer-sha256",
    "$OFFER_SHA256",
    "--origin https://archhub.io",
    "--output /site",
)
# The build context sent to the builder: everything out, then exactly the
# three inputs the Dockerfile COPYs, minus compiled Python.
CONTEXT_RULES = (
    "*",
    "!nodelang/",
    "!packaging/website/httpd.conf",
    "!packaging/website/offer.json",
    "nodelang/**/__pycache__/",
)
HOSTING_WORDS = (
    "worker", "cloudflare", "wrangler", "build.mjs", "package.json",
    ".openai", "node_modules",
)
TRACKED_PUBLIC_SITE = (
    "public_site/.gitignore",
    "public_site/README.md",
    "public_site/site-export.json",
)
PUBLIC_SITE_FILES = (".gitignore", "README.md", "site-export.json")
README_SENTENCES = (
    "the exporter writes no README",
    "`write_public_site(store, registry, project_dir, *, offer, "
    "offer_sha256, origin)` writes exactly `<output>/site-export.json`, "
    "`<output>/.gitignore` and `<output>/dist/`",
    "`assets/fonts.css`, `404.html`, `robots.txt`, `sitemap.xml`, one "
    "redirect page for each retired address of the old site, the brand files "
    "`favicon.ico`, `favicon.svg` and `og.png`, and the font files and their "
    "licences under `assets/fonts/`, copied byte for byte from "
    "`nodelang/data/website/`, in Python, with root paths and rewritten "
    "hrefs. It writes nothing else.",
    "`404.html`, `assets/fonts.css` and the redirect pages are the only files "
    "typed in `site_export.py`, not projected from the graph.",
    "no page asks another host for a font.",
    "The export is refused unless the graph offers a released download",
    "The `--offer` file is the canonical offer record of "
    "`app:users:accounts:offer` as `nodelang/cell_accounts.py` publishes it: "
    "a JSON object `{\"availability\", \"pricing-visible\", \"public-label\"}`.",
    "refuses unless it equals `--offer-sha256` and equals what "
    "`cell_accounts.published_offer()` would publish for that record.",
    "maps the record to the website offer `{\"display\": public-label, "
    "\"monetary\": pricing-visible == \"true\"}` for "
    "`cell_website.offer_display_text`.",
    "python -m nodelang.site_export --offer packaging/website/offer.json "
    "--offer-sha256 <sha256 printed above> --origin https://archhub.io "
    "--output public_site",
    "packaging/website/Dockerfile",
    "packaging/website/fly.toml",
)


def _meaningful(source):
    return tuple(
        line.strip()
        for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _git(*args):
    """git's stdout and return code, or a skip where git cannot answer."""
    try:
        probe = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        pytest.skip("git is not available: %s" % exc)
    if probe.returncode == 128:
        pytest.skip("not a git work tree: %s" % probe.stderr.strip())
    return probe.stdout, probe.returncode


def test_website_image_exports_the_cell_site_then_serves_dist_with_busybox_httpd():
    source = DOCKERFILE.read_text(encoding="utf-8")
    meaningful = _meaningful(source)
    stages = tuple(line for line in meaningful if line.startswith("FROM "))

    assert stages == ("FROM %s AS build" % BUILD_BASE, "FROM %s" % SERVE_IMAGE)
    for forbidden in ("ADD ", "curl ", "wget ", "sudo", "COPY . ", "latest"):
        assert forbidden not in source, forbidden
    assert "COPY nodelang /build/nodelang" in meaningful
    assert "COPY packaging/website/offer.json /offer/offer.json" in meaningful
    assert "ARG OFFER_SHA256" in meaningful
    build_stage = "\n".join(meaningful[: meaningful.index("FROM %s" % SERVE_IMAGE)])
    assert 'test -n "$OFFER_SHA256"' in build_stage
    export_line = [line for line in meaningful if "nodelang.site_export" in line]
    assert len(export_line) == 1, export_line
    for flag in EXPORT_FLAGS:
        assert flag in export_line[0], flag
    assert "COPY --from=build /site/dist ." in meaningful
    assert "COPY packaging/website/httpd.conf ./httpd.conf" in meaningful
    assert meaningful[-1].startswith("CMD ")
    command = json.loads(meaningful[-1][len("CMD "):])
    assert command == [
        "/busybox", "httpd", "-f", "-v", "-p", "3000", "-c", "httpd.conf",
    ]


def test_httpd_conf_hands_missing_urls_to_the_exported_404_page():
    assert _meaningful(HTTPD_CONF.read_text(encoding="utf-8")) == (
        ".ico:image/x-icon",
        ".woff2:font/woff2",
        ".xml:application/xml",
        "E404:404.html",
    )


def test_fly_config_serves_port_3000_from_the_website_dockerfile():
    parsed = tomllib.loads(FLY_TOML.read_text(encoding="utf-8"))

    assert parsed["app"] == "archhub-web"
    # flyctl joins build.dockerfile and build.ignorefile with the directory
    # holding fly.toml.
    dockerfile = (FLY_TOML.parent / parsed["build"]["dockerfile"]).resolve()
    assert dockerfile == DOCKERFILE.resolve()
    ignorefile = (FLY_TOML.parent / parsed["build"]["ignorefile"]).resolve()
    assert ignorefile == DOCKERIGNORE.resolve()
    service = parsed["http_service"]
    assert service["internal_port"] == 3000
    assert service["force_https"] is True
    assert len(service["checks"]) == 1
    assert service["checks"][0]["method"] == "GET"
    assert service["checks"][0]["path"] == "/"
    for absent in ("env", "mounts", "services", "processes"):
        assert absent not in parsed, absent


def test_build_context_admits_only_nodelang_httpd_conf_and_the_offer_record():
    rules = _meaningful(DOCKERIGNORE.read_text(encoding="utf-8"))

    assert rules[0] == "*"
    assert rules == CONTEXT_RULES


def test_offer_record_is_ignored_never_tracked():
    _stdout, ignored = _git("check-ignore", "-q", "--", OFFER_RECORD)
    assert ignored == 0, "%s is not gitignored" % OFFER_RECORD
    tracked, _rc = _git("ls-files", "--", OFFER_RECORD)
    assert tracked.strip() == "", tracked


def test_public_site_tracks_only_the_sealed_export_its_readme_and_gitignore():
    stdout, _rc = _git("ls-files", "--", "public_site")
    tracked = tuple(sorted(
        line.strip() for line in stdout.splitlines() if line.strip()
    ))
    assert tracked == TRACKED_PUBLIC_SITE
    # The working tree, not only the index: a plain `git apply` deletes the
    # scaffold files but leaves them in the index, a regeneration could write
    # them back, and dist/ is the only untracked entry the export leaves.
    present = tuple(sorted(
        path.name for path in PUBLIC_SITE.iterdir() if path.name != "dist"
    ))
    assert present == PUBLIC_SITE_FILES, present
    ignored = (PUBLIC_SITE / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "dist/" in ignored


def test_public_site_readme_describes_the_one_source_and_the_offer_record():
    readme = (PUBLIC_SITE / "README.md").read_text(encoding="utf-8")
    lowered = readme.lower()
    flowed = " ".join(readme.split())

    for word in HOSTING_WORDS:
        assert word not in lowered, word
    for sentence in README_SENTENCES:
        assert sentence in flowed, sentence
