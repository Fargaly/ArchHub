"""Deterministic T0 export of the universal website Cell lens.

The exporter is a read-only release boundary over the same website, route,
CloudRoute, UI, and stylesheet Cells served by the application.  It refuses
unsafe graph state; it does not sanitize a second website implementation into
looking public.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from .cell_protocols import read_relation
from .cell_website import (
    PUBLIC_WEBSITE_ROUTES,
    project_universal_website_document,
    read_universal_website,
)
from .universal_cell import NULL_CELL_ID, InvalidCell


PUBLIC_ROUTES = PUBLIC_WEBSITE_ROUTES
PUBLICATION_TIER = "T0 PUBLIC"
EXPORT_FORMAT = "archhub-universal-cell-site-v2"


class SiteExportError(ValueError):
    """The graph cannot be projected into a safe public artifact."""


_PRIVATE_PATTERNS = (
    (re.compile(r"(?i)[a-z]:[\\/]+users[\\/]"), "local user path"),
    (re.compile(r"(?i)file://"), "local file URL"),
    (re.compile(
        r"(?i)(?:00\.governance|20\.clients|30\.knowledge|40\.media|"
        r"50\.tooling|60\.personal|70\.handoffs|90\.archive)"
    ), "non-public workspace area"),
    (re.compile(r"(?i)12\.production"), "legacy application path"),
    (re.compile(r"(?i)op://"), "secret capability reference"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)ARCHHUB_GRAND_MAP_PATH|authority\.json|node-native-wip"),
     "private runtime authority"),
)

PACKAGE_JSON = """{
  "name": "archhub-node-native-public-site",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "build": "node build.mjs"
  }
}
"""

HOSTING_JSON = """{
  "d1": null,
  "r2": null
}
"""

WRANGLER_JSON = """{
  "$schema": "node_modules/wrangler/config-schema.json",
  "name": "archhub-node-native-public-site",
  "compatibility_date": "2026-07-13",
  "main": "./dist/server/index.js",
  "assets": {
    "directory": "./dist/client",
    "binding": "ASSETS",
    "html_handling": "auto-trailing-slash",
    "not_found_handling": "404-page"
  }
}
"""

BUILD_MJS = r"""import { createHash } from "node:crypto";
import { readFile, writeFile, mkdir, rm } from "node:fs/promises";
import { dirname, join } from "node:path";

const canonical = (value) => {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  }
  return value;
};
const digest = (value) => createHash("sha256").update(value).digest("hex");
const source = JSON.parse(await readFile("site-export.json", "utf8"));
const sealed = { ...source };
delete sealed.export_sha256;
const actualExportHash = digest(JSON.stringify(canonical(sealed)));
if (actualExportHash !== source.export_sha256) throw new Error("site export seal is invalid");
if (source.format !== "archhub-universal-cell-site-v2") throw new Error("unsupported site export format");
if (source.publication_tier !== "T0 PUBLIC") throw new Error("site export is not T0 PUBLIC");
if (Object.keys(source.routes).length !== 7) throw new Error("site export must contain seven routes");

await rm("dist", { recursive: true, force: true });
await mkdir("dist/client", { recursive: true });
for (const [assetPath, contents] of Object.entries(source.assets)) {
  const target = join("dist/client", assetPath);
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, contents, "utf8");
}
for (const [route, record] of Object.entries(source.routes)) {
  if (digest(record.html) !== record.html_sha256) throw new Error(`route seal is invalid: ${route}`);
  if (record.output_path.includes("..") || record.output_path.startsWith("/")) {
    throw new Error(`unsafe route output path: ${record.output_path}`);
  }
  const target = join("dist/client", record.output_path);
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, record.html, "utf8");
}
const redirect = "<!doctype html><meta charset=\"utf-8\"><meta http-equiv=\"refresh\" content=\"0;url=/website\"><title>ArchHub</title><a href=\"/website\">ArchHub</a>";
const missing = "<!doctype html><meta charset=\"utf-8\"><title>Not found</title><h1>Not found</h1><p><a href=\"/website\">Return to ArchHub</a></p>";
await writeFile("dist/client/index.html", redirect, "utf8");
await writeFile("dist/client/404.html", missing, "utf8");
await mkdir("dist/server", { recursive: true });
await writeFile("dist/server/index.js", `export default {\n  async fetch(request, env) {\n    if (!env.ASSETS) return new Response("Static assets unavailable", { status: 503 });\n    return env.ASSETS.fetch(request);\n  }\n};\n`, "utf8");
await mkdir("dist/.openai", { recursive: true });
await writeFile("dist/.openai/hosting.json", await readFile(".openai/hosting.json", "utf8"), "utf8");
await writeFile("dist/build-manifest.json", JSON.stringify({
  format: source.format,
  export_sha256: source.export_sha256,
  publication_tier: source.publication_tier,
  routes: Object.keys(source.routes).sort()
}, null, 2) + "\n", "utf8");
"""

README = """# ArchHub public graph export

This project is a sealed static projection of the seven public website Cell
roots. `site-export.json` is generated by `nodelang.site_export`; `build.mjs`
verifies every route and the complete export before writing `dist/`.

The deployment boundary is intentionally static. It contains no application
runtime, Brain, private Grand Map, authentication, billing, database, storage,
credentials, or live cloud resource identifiers. Those capabilities remain
honest website states until their governed graph gates are connected.
"""


def _canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def _digest_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scan_public_text(value, label):
    for pattern, description in _PRIVATE_PATTERNS:
        match = pattern.search(value)
        if match:
            raise SiteExportError(
                "%s contains %s: %s" % (label, description, match.group(0)))


def _static_document(document):
    style_matches = tuple(re.finditer(
        r"<style>(.*?)</style>", document, flags=re.DOTALL
    ))
    if len(style_matches) != 1:
        raise SiteExportError(
            "projected website document must have exactly one graph stylesheet"
        )
    if re.search(r"<script\b", document, flags=re.IGNORECASE):
        raise SiteExportError("projected website document contains a script")
    for attribute in (
        "data-action", "data-edit", "data-edit-port", "data-download",
        "data-navigate",
    ):
        if re.search(r"\s%s=\"" % re.escape(attribute), document):
            raise SiteExportError(
                "projected website document contains mutation/runtime hooks"
            )
    style_match = style_matches[0]
    stylesheet = style_match.group(1)
    html = document[:style_match.start()] + (
        '<link rel="stylesheet" href="/assets/site.css">') + document[style_match.end():]
    return html, stylesheet


def _output_path(route):
    return route.strip("/") + "/index.html"


def _cell_record(snapshot, root_id):
    try:
        cell = snapshot.cells[root_id]
    except KeyError as exc:
        raise InvalidCell("website export source Cell is missing") from exc
    return {
        "id": cell.id,
        "link0": cell.link0,
        "link1": cell.link1,
        "atom_hex": cell.atom.hex(),
    }


def _terminal_text(snapshot, root_id, label):
    record = _cell_record(snapshot, root_id)
    if record["link0"] != NULL_CELL_ID or record["link1"] != NULL_CELL_ID:
        raise InvalidCell("%s must be a terminal Cell" % label)
    try:
        return bytes.fromhex(record["atom_hex"]).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCell("%s must be UTF-8" % label) from exc


def _relation_record(snapshot, root_id, *, budget=2_000):
    try:
        root = snapshot.cells[root_id]
    except KeyError as exc:
        raise InvalidCell("website export relation root is missing") from exc
    return {
        "root": {
            "id": root.id,
            "atom_hex": root.atom.hex(),
        },
        "members": [
            {
                "index": index,
                "role": member.role_id,
                "participant": member.participant_id,
            }
            for index, member in enumerate(
                read_relation(snapshot, root_id, budget=budget)
            )
        ],
    }


def _source_fingerprint(snapshot, verified, route, static_html):
    source_roots = {
        "route": verified.route_roots[route],
        "page": verified.page_roots[route],
        "http_route": verified.cloud_route_roots[route],
        "stylesheet": verified.stylesheet_root,
        "title": verified.route_title_roots[route],
    }
    statement = {
        "route_relation": _relation_record(snapshot, source_roots["route"]),
        "http_route_relation": _relation_record(
            snapshot, source_roots["http_route"], budget=256
        ),
        "page_render_sha256": _digest_text(static_html),
        "page_root": source_roots["page"],
        "stylesheet_cell": _cell_record(snapshot, source_roots["stylesheet"]),
        "title_cell": _cell_record(snapshot, source_roots["title"]),
    }
    if route == "/website":
        statement["domain_bindings"] = [
            _relation_record(snapshot, binding.root_id, budget=64)
            for _, binding in sorted(verified.domain_binding_roots.items())
        ]
    return source_roots, hashlib.sha256(_canonical_bytes(statement)).hexdigest()


def _verified_website(store, registry):
    required = (
        "website", "application_root", "roles", "ui_protocol", "map",
        "cloud_route_protocol",
    )
    if any(not hasattr(registry, name) for name in required):
        raise SiteExportError(
            "site export requires the universal application registry"
        )
    try:
        return read_universal_website(
            store.snapshot(),
            registry.website.protocol,
            registry.website.root_id,
            ui_protocol=registry.ui_protocol,
            application_root=registry.application_root,
            application_member_role=registry.roles["member"],
            map_registry=registry.map,
            cloud_route_protocol=registry.cloud_route_protocol,
            published_lifecycle_root=registry.website.lifecycle_root,
            read_action_root=registry.website.read_action_root,
        )
    except (InvalidCell, KeyError, TypeError) as exc:
        raise SiteExportError(
            "universal website verification failed: %s" % exc
        ) from exc


def build_site_export(store, registry):
    """Return a sealed public payload from the verified universal website."""
    verified = _verified_website(store, registry)
    snapshot = store.snapshot()
    publication_tier = _terminal_text(
        snapshot, verified.classification_root, "website classification"
    ).strip().upper()
    if publication_tier != PUBLICATION_TIER:
        raise SiteExportError(
            "website publication tier must be %s, got %s"
            % (PUBLICATION_TIER, publication_tier or "EMPTY")
        )
    if set(verified.route_roots) != set(PUBLIC_ROUTES):
        raise SiteExportError(
            "website route registry must contain exactly seven public routes"
        )

    records = {}
    shared_stylesheet = None
    for route in PUBLIC_ROUTES:
        try:
            projected = project_universal_website_document(
                store,
                verified,
                route,
                application_root=registry.application_root,
                application_member_role=registry.roles["member"],
                map_registry=registry.map,
                cloud_route_protocol=registry.cloud_route_protocol,
            )
        except InvalidCell as exc:
            raise SiteExportError(
                "route %s failed universal projection: %s" % (route, exc)
            ) from exc
        static_html, stylesheet = _static_document(projected)
        if shared_stylesheet is None:
            shared_stylesheet = stylesheet
        elif shared_stylesheet != stylesheet:
            raise SiteExportError("website routes do not share one graph stylesheet")
        _scan_public_text(static_html, route)
        source_roots, source_fingerprint = _source_fingerprint(
            snapshot, verified, route, static_html
        )
        records[route] = {
            "html": static_html,
            "html_sha256": _digest_text(static_html),
            "output_path": _output_path(route),
            "root_node": verified.page_roots[route],
            "source_fingerprint": source_fingerprint,
            "source_roots": source_roots,
        }

    _scan_public_text(shared_stylesheet or "", "shared stylesheet")
    payload = {
        "assets": {"assets/site.css": shared_stylesheet},
        "format": EXPORT_FORMAT,
        "application_root": registry.application_root,
        "website_root": verified.root_id,
        "website_fingerprint": hashlib.sha256(_canonical_bytes({
            "website": _relation_record(snapshot, verified.root_id),
            "protocol": _relation_record(snapshot, verified.protocol.root_id),
            "classification": _cell_record(
                snapshot, verified.classification_root
            ),
            "lifecycle": _cell_record(snapshot, verified.lifecycle_root),
        })).hexdigest(),
        "publication_tier": PUBLICATION_TIER,
        "routes": records,
    }
    _scan_public_text(_canonical_bytes(payload).decode("ascii"), "site export")
    payload["export_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return payload


def write_public_site(store, registry, project_dir):
    """Write the sealed graph export and dependency-free hosting scaffold."""
    project = Path(project_dir)
    project.mkdir(parents=True, exist_ok=True)
    (project / ".openai").mkdir(parents=True, exist_ok=True)
    payload = build_site_export(store, registry)
    hosting = json.loads(HOSTING_JSON)
    hosting_path = project / ".openai" / "hosting.json"
    if hosting_path.is_file():
        existing = json.loads(hosting_path.read_text(encoding="utf-8"))
        for key in ("project_id", "d1", "r2"):
            if key in existing:
                hosting[key] = existing[key]
    files = {
        "site-export.json": json.dumps(payload, sort_keys=True, indent=2,
                                       ensure_ascii=True) + "\n",
        "package.json": PACKAGE_JSON,
        "build.mjs": BUILD_MJS,
        "wrangler.jsonc": WRANGLER_JSON,
        ".openai/hosting.json": json.dumps(
            hosting, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        ".gitignore": "dist/\nnode_modules/\n",
        "README.md": README,
    }
    for relative, contents in files.items():
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8", newline="\n")
    return payload


def _build_public_seed_application():
    """Build export input from the bundled T0-safe seed, never local authority."""
    from .map_import import PUBLIC_MAP_PATH
    from .universal_application import build_universal_application

    return build_universal_application(PUBLIC_MAP_PATH)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[1] / "public_site"),
    )
    args = parser.parse_args(argv)
    store, registry = _build_public_seed_application()
    payload = write_public_site(store, registry, args.output)
    print(json.dumps({
        "format": payload["format"],
        "publication_tier": payload["publication_tier"],
        "routes": len(payload["routes"]),
        "export_sha256": payload["export_sha256"],
        "output": str(Path(args.output).resolve()),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
