/**
 * sitemap.xml — the site shipped without one, so nothing told a crawler which
 * pages exist or when they last changed.
 *
 * Built from the real route list at build time: the static pages under
 * src/pages plus one entry per doc in the `docs` content collection, so a new
 * doc file appears in the sitemap without anyone remembering to add it.
 *
 * /account and /brain are left out on purpose — they are signed-in surfaces
 * that render nothing for a crawler (robots.txt disallows them too).
 */
import { getCollection } from 'astro:content';

const SITE = 'https://archhub.io';

// path -> how often it is worth re-crawling. Kept next to the route so a new
// page cannot be added without deciding this.
export const STATIC_ROUTES = [
  { path: '/', changefreq: 'weekly', priority: '1.0' },
  { path: '/features/', changefreq: 'monthly', priority: '0.9' },
  { path: '/pricing/', changefreq: 'monthly', priority: '0.9' },
  { path: '/docs/', changefreq: 'weekly', priority: '0.9' },
  { path: '/security/', changefreq: 'monthly', priority: '0.7' },
  { path: '/gallery/', changefreq: 'weekly', priority: '0.7' },
  { path: '/community/', changefreq: 'weekly', priority: '0.7' },
  { path: '/changelog/', changefreq: 'weekly', priority: '0.7' },
  { path: '/signin/', changefreq: 'yearly', priority: '0.5' },
];

function urlEntry({ path, changefreq, priority }, lastmod) {
  return [
    '  <url>',
    `    <loc>${SITE}${path}</loc>`,
    `    <lastmod>${lastmod}</lastmod>`,
    `    <changefreq>${changefreq}</changefreq>`,
    `    <priority>${priority}</priority>`,
    '  </url>',
  ].join('\n');
}

export async function GET() {
  const lastmod = new Date().toISOString().slice(0, 10);
  const docs = await getCollection('docs');
  const docRoutes = docs
    .map((d) => ({ path: `/docs/${d.id}/`, changefreq: 'monthly', priority: '0.8' }))
    .sort((a, b) => a.path.localeCompare(b.path));

  const body =
    '<?xml version="1.0" encoding="UTF-8"?>\n' +
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
    [...STATIC_ROUTES, ...docRoutes].map((r) => urlEntry(r, lastmod)).join('\n') +
    '\n</urlset>\n';

  return new Response(body, {
    headers: { 'Content-Type': 'application/xml; charset=utf-8' },
  });
}
