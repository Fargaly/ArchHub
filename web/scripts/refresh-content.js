#!/usr/bin/env node
/**
 * refresh-content.js — the OPTIONAL maintainer step (`npm run refresh-content`).
 *
 * The deploy build is pure `astro build` and reads only COMMITTED static
 * content under src/content/ + public/. This script regenerates that committed
 * content from live sources so a maintainer can refresh + commit it. It is NOT
 * part of `prebuild` / the deploy build — the website builds with NO daemon.
 *
 * It runs, in order, each sub-step independently (a failure in one does not
 * abort the others — e.g. the brain daemon being down still lets the connector
 * counts + changelog refresh):
 *   1. build-info.js          — git sha/date + real connector/op counts (no daemon)
 *   2. copy-brain-viz.js      — copy the in-app brain graph + data into public/brain/
 *   3. extract_pricing.py     — pricing.json from cloud_backend (needs ../cloud_backend)
 *   4. export_web_data.py     — skills-export.json + contributors.json from the
 *                               brain store (REAL community skills WITH success
 *                               stats + the derived contributor leaderboard).
 *                               Reads brain.db directly so it captures the
 *                               per-skill stats the MCP export omits.
 *
 * Steps 3 + 4 are best-effort: if their source is unavailable the existing
 * committed JSON is left untouched (honest, no zeroing). The legacy
 * scripts/from-brain.js (MCP-wire skill pull, no stats) remains available as
 * `npm run from-brain` for environments without the brain Python package.
 */

import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function run(label, cmd, args, { required }) {
  console.log(`\n[refresh-content] → ${label}`);
  const r = spawnSync(cmd, args, {
    cwd: __dirname,
    stdio: 'inherit',
    shell: false,
  });
  if (r.error) {
    console.warn(`[refresh-content]   ${label} could not start: ${r.error.message}`);
    return false;
  }
  if (r.status !== 0) {
    const msg = `[refresh-content]   ${label} exited ${r.status}`;
    if (required) console.error(msg + ' (required)');
    else console.warn(msg + ' — keeping previously committed content');
    return false;
  }
  return true;
}

const node = process.execPath;
const python = process.platform === 'win32' ? 'python' : 'python3';

// 1. Always-available: provenance + connector counts (no external services).
run('build-info (git sha + connector counts)', node, ['build-info.js'], { required: true });

// 2. Always-available: copy the real in-app brain viz into public/brain/.
run('copy-brain-viz (app/web_ui → public/brain)', node, ['copy-brain-viz.js'], { required: true });

// 3. Best-effort: pricing from cloud_backend.
run('extract_pricing (cloud_backend/billing.py)', python, ['extract_pricing.py'], { required: false });

// 4. Best-effort: REAL community skills (with success stats) + the derived
//    contributor leaderboard, read straight from brain.db. The exporter lives
//    at repo-root tools/export_web_data.py; resolve it relative to this script
//    (web/scripts → ../../tools).
const exporter = path.resolve(__dirname, '..', '..', 'tools', 'export_web_data.py');
run('export_web_data (brain → skills-export.json + contributors.json)',
    python, [exporter], { required: false });

console.log('\n[refresh-content] done. Review `git diff web/src/data web/public/brain` and commit.');
