#!/usr/bin/env node
/**
 * build-info.js — regenerates src/data/build-info.json, the committed
 * static facts the marketing site stamps at build time:
 *   - git_sha / git_date  : provenance for the per-page freshness footer
 *   - connectors / operations : the REAL connector + op counts on the home
 *     page, derived from app/connectors/ source (no daemon, no app boot).
 *
 * This is part of the OPTIONAL `npm run refresh-content` maintainer step — it
 * is NOT in the deploy build. The committed build-info.json is what `astro
 * build` reads. A maintainer re-runs this to refresh the numbers after the
 * app's connectors change, then commits the updated JSON.
 *
 * Counting method (matches app/connectors/base.py load_all_connectors() +
 * Connector.build_ops()):
 *   - connectors = the modules registered in load_all_connectors()'s `modules`
 *     list — each *_connector.py whose class self-registers. We count the
 *     distinct host prefixes of declared ops (one host == one connector),
 *     which equals the registered-connector count.
 *   - operations = distinct `op_id="host.name"` string literals across those
 *     connector modules (each ConnectorOp carries a unique op_id).
 * If app/connectors/ is not reachable (e.g. running outside the monorepo),
 * the previous committed counts are preserved rather than zeroed.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execSync } from 'node:child_process';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = path.resolve(__dirname, '..');
const REPO_ROOT = path.resolve(WEB_ROOT, '..');
const CONNECTORS_DIR = path.join(REPO_ROOT, 'app', 'connectors');
const OUT = path.join(WEB_ROOT, 'src', 'data', 'build-info.json');

function git(cmd, fallback) {
  try {
    return execSync(`git ${cmd}`, { cwd: REPO_ROOT, encoding: 'utf8' }).trim();
  } catch {
    return fallback;
  }
}

/**
 * Count connectors + operations from the real connector source. Mirrors how
 * the app registers them, so the marketing numbers can never drift from the
 * shipped product.
 */
function countConnectors() {
  if (!fs.existsSync(CONNECTORS_DIR)) return null;
  const files = fs
    .readdirSync(CONNECTORS_DIR)
    .filter((f) => f.endsWith('_connector.py'));
  const opIds = new Set();
  const hosts = new Set();
  const opIdRe = /op_id\s*=\s*["']([a-zA-Z0-9_.]+)["']/g;
  for (const f of files) {
    const src = fs.readFileSync(path.join(CONNECTORS_DIR, f), 'utf8');
    let m;
    while ((m = opIdRe.exec(src)) !== null) {
      const id = m[1];
      opIds.add(id);
      const host = id.split('.', 1)[0];
      if (host) hosts.add(host);
    }
  }
  if (opIds.size === 0) return null;
  return { connectors: hosts.size, operations: opIds.size };
}

function readPrev() {
  try {
    return JSON.parse(fs.readFileSync(OUT, 'utf8'));
  } catch {
    return {};
  }
}

function main() {
  const prev = readPrev();
  const counts = countConnectors();
  const sha = git('rev-parse --short HEAD', prev.git_sha || 'unknown');
  const dateIso = git('log -1 --format=%cI', prev.git_date || new Date().toISOString());

  const payload = {
    git_sha: sha,
    git_date: dateIso,
    generated_at: new Date().toISOString(),
    source: 'scripts/build-info.js (npm run refresh-content)',
    connectors: counts ? counts.connectors : (prev.connectors ?? 0),
    operations: counts ? counts.operations : (prev.operations ?? 0),
    connectors_source: 'app/connectors/*_connector.py (distinct op_id host prefixes + ids)',
  };

  fs.writeFileSync(OUT, JSON.stringify(payload, null, 2) + '\n', 'utf8');
  console.log(
    `[build-info] wrote ${path.relative(REPO_ROOT, OUT)} — sha=${payload.git_sha} ` +
      `connectors=${payload.connectors} operations=${payload.operations}` +
      (counts ? '' : ' (counts preserved — app/connectors not reachable)'),
  );
}

main();
