#!/usr/bin/env node
/**
 * copy-brain-viz.js — copies the REAL in-app brain graph visualisation
 *   app/web_ui/brain-graph.html      → web/public/brain/index.html
 *   app/web_ui/brain-graph-data.json → web/public/brain/brain-graph-data.json
 *
 * Astro copies everything under public/ verbatim into dist/, so /brain is a
 * build-stable route that survives `astro build` (unlike a generated page that
 * gets cleaned each build). The committed copies under public/brain/ are what
 * ships; this script (part of `npm run refresh-content`) refreshes them from
 * the in-app source so the marketing viz can never drift from the product's.
 *
 * The HTML fetches ./brain-graph-data.json relative to itself, which resolves
 * to /brain/brain-graph-data.json in the deployed site — both files sit in the
 * same public/brain/ folder, so the relative fetch works unchanged.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = path.resolve(__dirname, '..');
const REPO_ROOT = path.resolve(WEB_ROOT, '..');
const SRC_DIR = path.join(REPO_ROOT, 'app', 'web_ui');
const DST_DIR = path.join(WEB_ROOT, 'public', 'brain');

const COPIES = [
  ['brain-graph.html', 'index.html'],
  ['brain-graph-data.json', 'brain-graph-data.json'],
];

function main() {
  fs.mkdirSync(DST_DIR, { recursive: true });
  let n = 0;
  for (const [src, dst] of COPIES) {
    const from = path.join(SRC_DIR, src);
    const to = path.join(DST_DIR, dst);
    if (!fs.existsSync(from)) {
      console.warn(`[copy-brain-viz] source missing: ${path.relative(REPO_ROOT, from)} — skipping`);
      continue;
    }
    fs.copyFileSync(from, to);
    n += 1;
    console.log(`[copy-brain-viz] ${path.relative(REPO_ROOT, from)} → ${path.relative(REPO_ROOT, to)}`);
  }
  console.log(`[copy-brain-viz] copied ${n} file(s) into public/brain/`);
}

main();
