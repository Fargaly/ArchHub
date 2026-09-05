/**
 * release.js — the site's ONE version story, resolved at build time.
 *
 * Why this exists: the site used to tell two contradicting stories. /changelog
 * read CHANGELOG.md and showed v1.6.7 as the newest release, while the docs
 * told people to download `ArchHub-Setup-0.exe` and said "the version label is
 * 0". A visitor could not tell which number was the product's version.
 *
 * The truth is that they are two different labels:
 *   - appVersion      — the release series in CHANGELOG.md (1.6.7)
 *   - packagingLabel  — the repo-root VERSION file (0), which names the GitHub
 *                       release tag (v0) and the installer filename
 *                       (ArchHub-Setup-0.exe) while the product is in open beta
 * Every page and doc now reads these from here, so the site says the same
 * thing everywhere and cannot drift when either label moves.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readChangelog } from './changelog.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const GITHUB_REPO = 'https://github.com/Fargaly/ArchHub';

/**
 * Locate the repo-root VERSION file. Same probing shape as changelog.js:
 * Vite bundles this module during `astro build`, so `import.meta.url` cannot
 * be trusted to still point at web/src/lib.
 */
function resolveVersionPath() {
  const candidates = [
    path.resolve(__dirname, '..', '..', '..', 'VERSION'), // web/src/lib -> repo root (dev)
    path.resolve(process.cwd(), '..', 'VERSION'),         // cwd = web/ -> repo root (astro build)
    path.resolve(process.cwd(), 'VERSION'),               // cwd = repo root
    path.resolve(__dirname, '..', '..', 'VERSION'),       // bundled one level shallower
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return candidates[0];
}

function readPackagingLabel() {
  try {
    const raw = fs.readFileSync(resolveVersionPath(), 'utf8').trim();
    return raw || null;
  } catch {
    return null;
  }
}

/**
 * The single release fact-set every page and the docs quote.
 * `appVersion` is null when CHANGELOG.md cannot be read — callers fall back to
 * naming the download only, rather than printing a made-up number.
 */
export function releaseInfo() {
  const { ok, releases } = readChangelog(1);
  const appVersion = ok && releases.length ? releases[0].version : null;
  const appDate = ok && releases.length ? releases[0].date : null;
  const packagingLabel = readPackagingLabel();
  const tag = packagingLabel ? `v${packagingLabel}` : null;
  const installerFile = packagingLabel ? `ArchHub-Setup-${packagingLabel}.exe` : null;
  return {
    appVersion,
    appDate,
    packagingLabel,
    tag,
    installerFile,
    latestReleaseUrl: `${GITHUB_REPO}/releases/latest`,
    downloadUrl: tag && installerFile
      ? `${GITHUB_REPO}/releases/download/${tag}/${installerFile}`
      : `${GITHUB_REPO}/releases/latest`,
    /**
     * One sentence the whole site reuses, so the two labels are never shown
     * apart. Reads: "Release 1.6.7 - the installer is published as
     * ArchHub-Setup-0.exe on the v0 open-beta tag."
     */
    get sentence() {
      if (this.appVersion && this.installerFile && this.tag) {
        return `Release ${this.appVersion} — the installer is published as ${this.installerFile} on the ${this.tag} open-beta tag.`;
      }
      if (this.installerFile) return `The installer is published as ${this.installerFile}.`;
      return 'The installer is published on the GitHub releases page.';
    },
  };
}
