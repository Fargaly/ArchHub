/**
 * changelog.js — build-time reader for the repo's real CHANGELOG.md.
 *
 * Parses the Keep-a-Changelog format used by ../CHANGELOG.md:
 *   ## [1.3.2] — 2026-05-13      (release heading; em-dash or hyphen)
 *   ### Section                  (subsection inside a release)
 *   ...body...
 *
 * Returns the most recent `limit` releases as structured objects so the Astro
 * page can render them. Pure Node fs read at build time — no daemon, no
 * network. Honest + sourced: every entry on /changelog is text that exists in
 * CHANGELOG.md.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Locate the repo-root CHANGELOG.md. During `astro build` this module gets
 * bundled by Vite, so `import.meta.url` no longer points at web/src/lib —
 * the old hard-coded "three up" resolved to web/CHANGELOG.md (ENOENT) and the
 * page silently rendered "source unavailable". We probe a list of candidates
 * (module-relative AND cwd-relative — `astro build` runs from web/) and use the
 * first that exists, so the changelog renders no matter where the build runs.
 */
function resolveChangelogPath() {
  const candidates = [
    path.resolve(__dirname, '..', '..', '..', 'CHANGELOG.md'), // web/src/lib → repo root (dev)
    path.resolve(process.cwd(), '..', 'CHANGELOG.md'),         // cwd = web/ → repo root (astro build)
    path.resolve(process.cwd(), 'CHANGELOG.md'),               // cwd = repo root
    path.resolve(__dirname, '..', '..', 'CHANGELOG.md'),       // bundled one level shallower
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return candidates[0]; // fall back to the canonical path for a clear ENOENT error
}

const CHANGELOG_PATH = resolveChangelogPath();

// Matches "## [1.3.2] — 2026-05-13" / "## [1.3.2] - 2026-05-13".
const RELEASE_RE = /^##\s+\[([^\]]+)\]\s*[—-]\s*(.+?)\s*$/;
// Matches "### Section title".
const SECTION_RE = /^###\s+(.+?)\s*$/;

/**
 * Read + parse CHANGELOG.md. Returns { ok, releases:[{version, date,
 * sections:[{heading, lines:[...]}]}], error }.
 */
export function readChangelog(limit = 6) {
  let raw;
  try {
    raw = fs.readFileSync(CHANGELOG_PATH, 'utf8');
  } catch (e) {
    return { ok: false, releases: [], error: `CHANGELOG.md unreadable: ${e.message}` };
  }

  const lines = raw.split(/\r?\n/);
  const releases = [];
  let cur = null; // current release
  let sec = null; // current section within the release

  for (const line of lines) {
    const rel = RELEASE_RE.exec(line);
    if (rel) {
      cur = { version: rel[1], date: rel[2], sections: [] };
      releases.push(cur);
      sec = null;
      if (releases.length > limit) break; // stop once we have limit+1 sighted
      continue;
    }
    if (!cur) continue; // preamble before first release
    const s = SECTION_RE.exec(line);
    if (s) {
      sec = { heading: s[1], lines: [] };
      cur.sections.push(sec);
      continue;
    }
    if (sec) sec.lines.push(line);
  }

  // Keep only the first `limit` releases (the break above may have started a
  // limit+1th to detect the boundary).
  const trimmed = releases.slice(0, limit);

  // Compact each section + coalesce wrapped lines into real bullet items.
  for (const r of trimmed) {
    for (const s of r.sections) {
      while (s.lines.length && s.lines[0].trim() === '') s.lines.shift();
      while (s.lines.length && s.lines[s.lines.length - 1].trim() === '') s.lines.pop();
      s.bullets = toBullets(s.lines);
    }
    // Drop empty sections (heading with no body).
    r.sections = r.sections.filter((s) => s.bullets.length > 0);
  }

  return { ok: true, releases: trimmed, error: null };
}

/**
 * Turn raw markdown lines into display bullets. A new bullet starts on a
 * markdown list marker ("- ", "* ", "1. ") or a markdown table row; any
 * non-marker line is treated as a continuation of the previous bullet and
 * joined to it (so a hard-wrapped sentence renders as ONE item, not several).
 * Blank lines and table separator rows (|---|) are dropped.
 */
function toBullets(lines) {
  const bullets = [];
  const isMarker = (l) => /^\s*([-*]|\d+\.)\s+/.test(l);
  const isTableRow = (l) => /^\s*\|/.test(l);
  const isTableSep = (l) => /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(l) && l.includes('-');
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '');
    if (line.trim() === '') continue;
    if (isTableSep(line)) continue;
    if (isMarker(line)) {
      bullets.push(line.replace(/^\s*([-*]|\d+\.)\s+/, '').trim());
    } else if (isTableRow(line)) {
      bullets.push(line.replace(/^\s*\|/, '').replace(/\|\s*$/, '').replace(/\s*\|\s*/g, ' · ').trim());
    } else if (bullets.length > 0) {
      // Continuation of the previous bullet — join with a space.
      bullets[bullets.length - 1] = `${bullets[bullets.length - 1]} ${line.trim()}`.trim();
    } else {
      // Leading prose with no preceding bullet — make it its own item.
      bullets.push(line.trim());
    }
  }
  return bullets.filter((b) => b.length > 0);
}
