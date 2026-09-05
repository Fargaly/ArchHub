#!/usr/bin/env node
/**
 * check-site.js — the public site's invariant tests.
 *
 * There is no test runner in this project (package.json has no dependencies
 * beyond astro + mdx), so these are plain assertions over the source files.
 * Run with:  node scripts/check-site.js
 *
 * Every check here exists because the live site got one of these wrong: a
 * social card that came through blank, no robots.txt or sitemap, a raw
 * web-server 404, a footer date months older than the deployment, links to
 * pages that do not hold the thing they promise, invented telemetry on the
 * home page, tier names that matched neither the backend nor the repo, and a
 * hosting hostname shipped in the page source.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const REPO = path.resolve(WEB, '..');

let failures = 0;
let checks = 0;

function ok(name) {
  checks += 1;
  console.log(`  ok   ${name}`);
}
function fail(name, detail) {
  checks += 1;
  failures += 1;
  console.log(`  FAIL ${name}\n       ${detail}`);
}
function assert(cond, name, detail) {
  if (cond) ok(name);
  else fail(name, detail);
}
function group(title) {
  console.log(`\n${title}`);
}
function read(rel) {
  return fs.readFileSync(path.join(WEB, rel), 'utf8');
}
function exists(rel) {
  return fs.existsSync(path.join(WEB, rel));
}
function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

const PAGES_DIR = path.join(WEB, 'src', 'pages');
const pageFiles = walk(PAGES_DIR).filter((f) => f.endsWith('.astro'));
const docFiles = fs
  .readdirSync(path.join(WEB, 'src', 'content', 'docs'))
  .filter((f) => f.endsWith('.md'));
const docSlugs = docFiles.map((f) => f.replace(/\.md$/, ''));

/** Every route the built site actually serves. */
function routeSet() {
  const routes = new Set();
  for (const f of pageFiles) {
    const rel = path.relative(PAGES_DIR, f).split(path.sep).join('/');
    if (rel === '404.astro') continue;
    if (rel.includes('[')) continue;
    let route = '/' + rel.replace(/\.astro$/, '');
    route = route.replace(/\/index$/, '');
    routes.add(route === '' ? '/' : route);
  }
  for (const slug of docSlugs) routes.add(`/docs/${slug}`);
  return routes;
}
const ROUTES = routeSet();

// -- 1. Open Graph: a share must not come through blank -------------------
group('Open Graph / social card');
{
  const base = read('src/layouts/Base.astro');
  const required = [
    'property="og:type"',
    'property="og:title"',
    'property="og:description"',
    'property="og:url"',
    'property="og:image"',
    'property="og:image:width"',
    'property="og:image:height"',
    'name="twitter:card"',
    'name="twitter:image"',
  ];
  const missing = required.filter((t) => !base.includes(t));
  assert(missing.length === 0, 'every Open Graph and Twitter tag is present', `missing: ${missing.join(', ')}`);

  const m = base.match(/const ogImage = '([^']+)'/);
  assert(!!m, 'Base.astro declares an og image', 'no ogImage constant found');
  const ogUrl = m ? m[1] : '';
  assert(
    ogUrl.endsWith('.png') || ogUrl.endsWith('.jpg'),
    'the og image is a raster file',
    `og image is ${ogUrl} — social crawlers do not rasterise SVG, so the card renders blank`,
  );
  const ogFile = ogUrl.replace('https://archhub.io', 'public');
  assert(exists(ogFile), 'the og image file is committed', `${ogFile} is missing`);
  if (exists(ogFile)) {
    const buf = fs.readFileSync(path.join(WEB, ogFile));
    const isPng = buf.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
    assert(isPng, 'the og image really is a PNG', 'PNG signature not found');
    if (isPng) {
      const w = buf.readUInt32BE(16);
      const h = buf.readUInt32BE(20);
      assert(w === 1200 && h === 630, 'the og image is 1200x630', `it is ${w}x${h}`);
      const dw = /og:image:width" content="(\d+)"/.exec(base);
      const dh = /og:image:height" content="(\d+)"/.exec(base);
      assert(
        dw && dh && Number(dw[1]) === w && Number(dh[1]) === h,
        'the declared og:image size matches the file',
        `declared ${dw && dw[1]}x${dh && dh[1]}, file ${w}x${h}`,
      );
    }
  }
}

// -- 2. robots.txt + sitemap ---------------------------------------------
group('robots.txt and sitemap');
{
  assert(exists('public/robots.txt'), 'robots.txt is committed', 'public/robots.txt is missing');
  if (exists('public/robots.txt')) {
    const robots = read('public/robots.txt');
    assert(/^User-agent:\s*\*/m.test(robots), 'robots.txt has a User-agent rule', robots.slice(0, 120));
    assert(
      robots.includes('Sitemap: https://archhub.io/sitemap.xml'),
      'robots.txt points at the sitemap',
      'no absolute Sitemap: line',
    );
  }

  assert(exists('src/pages/sitemap.xml.js'), 'the sitemap endpoint exists', 'src/pages/sitemap.xml.js is missing');
  if (exists('src/pages/sitemap.xml.js')) {
    const sm = read('src/pages/sitemap.xml.js');
    assert(
      sm.includes("getCollection('docs')"),
      'the sitemap enumerates docs from the collection',
      'docs are not read from the content collection, so a new doc would be missed',
    );
    const listed = new Set(
      [...sm.matchAll(/path: '([^']+)'/g)].map((x) => x[1].replace(/\/$/, '') || '/'),
    );
    const priv = new Set(['/account', '/brain']);
    const expected = [...ROUTES].filter((r) => !r.startsWith('/docs/') && !priv.has(r));
    const missing2 = expected.filter((r) => !listed.has(r));
    assert(missing2.length === 0, 'every public page is in the sitemap', `not listed: ${missing2.join(', ')}`);
    const stale = [...listed].filter((r) => !ROUTES.has(r));
    assert(stale.length === 0, 'the sitemap lists no dead routes', `no such page: ${stale.join(', ')}`);
    for (const p of priv) {
      assert(!listed.has(p), `${p} is kept out of the sitemap`, 'signed-in surfaces should not be crawled');
    }
  }
}

// -- 3. The 404 page is ours, and the server actually serves it ----------
group('404 page');
{
  assert(exists('src/pages/404.astro'), 'the site has its own 404 page', 'src/pages/404.astro is missing');
  if (exists('src/pages/404.astro')) {
    const nf = read('src/pages/404.astro');
    assert(
      nf.includes("import Base from '../layouts/Base.astro'"),
      'the 404 page uses the site layout',
      'it does not import Base.astro, so it carries no nav, footer or design',
    );
    assert(/href="\/"/.test(nf), 'the 404 page offers a way back', 'no link to the home page');
  }
  assert(
    exists('httpd.conf'),
    'an httpd config is committed',
    'web/httpd.conf is missing, so BusyBox serves its own built-in 404 body',
  );
  if (exists('httpd.conf')) {
    assert(/^E404:404\.html$/m.test(read('httpd.conf')), 'httpd.conf maps 404 to our page', 'no E404:404.html line');
  }
  assert(
    /COPY httpd\.conf/.test(read('Dockerfile')),
    'the image ships the httpd config',
    'Dockerfile does not COPY httpd.conf into the serve stage',
  );
}

// -- 4. No hosting hostname in the shipped site --------------------------
group('API host');
{
  const shipped = [...walk(path.join(WEB, 'src')), ...walk(path.join(WEB, 'public'))];
  const offenders = shipped.filter((f) => fs.readFileSync(f, 'utf8').includes('fly.dev'));
  assert(
    offenders.length === 0,
    'the site never names the fly.dev host',
    `still points at fly.dev: ${offenders.map((f) => path.relative(WEB, f)).join(', ')}`,
  );
  assert(
    read('public/auth.js').includes('https://api.archhub.io'),
    'the auth client calls api.archhub.io',
    'auth.js does not use the published API host',
  );
}

// -- 5. One version story -------------------------------------------------
group('version');
{
  const changelog = fs.readFileSync(path.join(REPO, 'CHANGELOG.md'), 'utf8');
  const newest = /^##\s+\[([^\]]+)\]/m.exec(changelog);
  assert(!!newest, 'CHANGELOG.md has a newest release', 'no release heading parsed');
  const appVersion = newest ? newest[1] : null;
  const packagingLabel = fs.readFileSync(path.join(REPO, 'VERSION'), 'utf8').trim();

  assert(exists('src/lib/release.js'), 'the one version story has a single source', 'src/lib/release.js is missing');
  const rel = read('src/lib/release.js');
  assert(rel.includes('readChangelog'), 'the app version is read from CHANGELOG.md', 'release.js does not read the changelog');
  assert(rel.includes("'VERSION'"), 'the packaging label is read from the VERSION file', 'release.js does not read VERSION');
  assert(
    rel.includes('ArchHub-Setup-${packagingLabel}.exe'),
    'the installer filename is derived from the packaging label',
    'the installer name is hardcoded and can drift from VERSION',
  );

  const prose = [...pageFiles, ...docFiles.map((f) => path.join(WEB, 'src/content/docs', f))];
  const bad = [];
  for (const f of prose) {
    const text = fs.readFileSync(f, 'utf8');
    for (const mm of text.matchAll(/\bv(\d+\.\d+\.\d+)\b/g)) {
      if (mm[1] !== appVersion) bad.push(`${path.relative(WEB, f)}: v${mm[1]}`);
    }
    if (text.includes('ArchHub-Setup-') && !text.includes(`ArchHub-Setup-${packagingLabel}.exe`)) {
      bad.push(`${path.relative(WEB, f)}: installer name does not match VERSION (${packagingLabel})`);
    }
  }
  assert(bad.length === 0, 'no page or doc states a version the changelog contradicts', bad.join('; '));

  // Wherever the beta packaging label appears, the changelog is named too, so
  // a reader is never left with the label as the product's version.
  const installerDocs = docFiles
    .map((f) => [f, fs.readFileSync(path.join(WEB, 'src/content/docs', f), 'utf8')])
    .filter((pair) => pair[1].includes(`ArchHub-Setup-${packagingLabel}.exe`));
  const unexplained = installerDocs.filter((pair) => !pair[1].includes('/changelog')).map((pair) => pair[0]);
  assert(
    unexplained.length === 0,
    'the packaging label is always explained against the changelog',
    `these name the installer without pointing at the release series: ${unexplained.join(', ')}`,
  );
}

// -- 6. No invented measurements -----------------------------------------
group('honest numbers');
{
  const home = read('src/pages/index.astro');
  const invented = ['LAST 7 DAYS', 'P50 · ALL HOSTS', 'recovered sessions', 'median recovery', 'session #2841'];
  const found = invented.filter((s) => home.includes(s));
  assert(found.length === 0, 'the home page quotes no telemetry it never measured', `still present: ${found.join(', ')}`);
  assert(
    home.includes('ILLUSTRATION') || home.includes('Illustration'),
    'the recovery panel is labelled as a drawing',
    'the mocked log and timings are not marked as an illustration',
  );
  assert(
    /class="k">\{connectors\}</.test(home) && /class="k">\{operations\}</.test(home),
    'the self-heal figures come from counted source',
    'the stat tiles are not wired to build-info counts',
  );
}

// -- 7. Pricing agrees with the backend catalog --------------------------
group('pricing');
{
  const pricing = JSON.parse(read('src/data/pricing.json'));
  const page = read('src/pages/pricing.astro');
  assert(
    page.includes("import pricing from '../data/pricing.json'"),
    'the pricing page reads the extracted catalog',
    'tiers are not sourced from pricing.json',
  );
  const names = pricing.tiers.map((t) => t.name);
  const notReal = ['Pro', 'Enterprise'].filter((n) => !names.includes(n));
  const rendered = page.split('---').slice(2).join('---');
  const leaked = notReal.filter((n) => new RegExp('\\b' + n + '\\b').test(rendered));
  assert(leaked.length === 0, 'the page names no tier the backend does not have', `invented tiers still rendered: ${leaked.join(', ')}`);
  assert(names.join(',') === 'Solo,Studio,Firm', 'the catalog holds the three real tiers', `pricing.json has: ${names.join(', ')}`);
  assert(
    page.includes('{t.price_per_seat}') && page.includes('{t.price_per_seat_annual}'),
    'prices are rendered from the catalog',
    'the page hardcodes prices instead of reading them',
  );
}

// -- 8. Footer links go where they say -----------------------------------
group('footer links');
{
  const base = read('src/layouts/Base.astro');
  assert(!/>Discord</.test(base), 'the footer does not advertise a Discord', 'there is no Discord server, so the link cannot lead to one');
  const roadmap = /<a href="([^"]+)"[^>]*>Roadmap<\/a>/.exec(base);
  assert(!!roadmap, 'the footer has a Roadmap link', 'no Roadmap link found');
  if (roadmap) {
    assert(/ROADMAP\.md/.test(roadmap[1]), 'the Roadmap link goes to the roadmap', `it points at ${roadmap[1]}`);
  }
}

// -- 9. The footer date comes from the build -----------------------------
group('build stamp');
{
  const base = read('src/layouts/Base.astro');
  assert(
    !/builtDate = \(buildInfo\.git_date/.test(base),
    'the footer date is not a committed git date',
    'builtDate still echoes build-info.json, so a redeploy keeps the old date',
  );
  assert(/const builtDate = new Date\(\)/.test(base), 'the footer date is stamped at build time', 'builtDate is not derived from the build');
}

// -- 10. Every internal link resolves ------------------------------------
group('internal links');
{
  const sources = [
    ...pageFiles,
    path.join(WEB, 'src/layouts/Base.astro'),
    ...docFiles.map((f) => path.join(WEB, 'src/content/docs', f)),
  ];
  const broken = [];
  for (const f of sources) {
    const text = fs.readFileSync(f, 'utf8');
    const hrefs = [
      ...[...text.matchAll(/href="(\/[^"#?]*)"/g)].map((m) => m[1]),
      ...[...text.matchAll(/\]\((\/[^)#?]*)\)/g)].map((m) => m[1]),
    ];
    for (const h of hrefs) {
      const route = h.replace(/\/$/, '') || '/';
      if (route.includes('$')) continue;
      if (ROUTES.has(route)) continue;
      if (route === '/sitemap.xml' || route === '/robots.txt') continue;
      if (route.startsWith('/og.') || route.startsWith('/favicon') || route === '/auth.js') continue;
      broken.push(`${path.relative(WEB, f)} -> ${h}`);
    }
  }
  assert(broken.length === 0, 'no internal link points at a missing page', broken.join('; '));

  const home = read('src/pages/index.astro');
  assert(
    !/Browse the live skill library/.test(home),
    'the home page does not promise a skill library it has no page for',
    'the live-skill-library link is still on the page',
  );
  const gallery = read('src/pages/gallery.astro');
  assert(
    /No packs published yet/.test(gallery),
    'the gallery states its empty state plainly',
    'the empty gallery does not say that nothing has been published',
  );
}

// -- 11. Doc claims that contradict the live backend ---------------------
group('doc claims');
{
  const docs = docFiles.map((f) => [f, fs.readFileSync(path.join(WEB, 'src/content/docs', f), 'utf8')]);
  const paragraphs = (t) => t.split(/\r?\n\s*\r?\n/);
  const googleOff = docs
    .filter((pair) => paragraphs(pair[1]).some((para) =>
      /google/i.test(para) && /not switched on|not configured|coming soon/i.test(para)))
    .map((pair) => pair[0]);
  assert(
    googleOff.length === 0,
    'no doc says Google sign-in is switched off',
    `Google sign-in is live; these still say otherwise: ${googleOff.join(', ')}`,
  );

  const scoopCmd = docs.filter((pair) => /scoop install https?:\/\//.test(pair[1])).map((pair) => pair[0]);
  assert(
    scoopCmd.length === 0,
    'no doc hands out a scoop command that fails',
    `the published manifest hash does not match the published installer: ${scoopCmd.join(', ')}`,
  );
}

console.log(`\n${failures === 0 ? 'PASS' : 'FAIL'} — ${checks - failures}/${checks} checks passed`);
process.exit(failures === 0 ? 0 : 1);
