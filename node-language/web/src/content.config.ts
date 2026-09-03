// Astro 6 Content Layer collections.
//
// The `docs` collection renders the committed user documentation under
// src/content/docs/*.md as real pages at /docs and /docs/<slug>. Pure static
// (glob loader over the filesystem) — no daemon, deployable anywhere, matching
// the rest of this site's build model (see astro.config.mjs).
//
// Schema: every doc needs a `title`; `description` (used for the listing blurb
// + SEO) and `order` (controls listing order) are optional. `key` is an
// optional legacy slug some docs carry in frontmatter — declared here so the
// collection accepts it rather than erroring on unknown frontmatter.
import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const docs = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/docs' }),
  schema: z.object({
    title: z.string(),
    description: z.string().optional(),
    order: z.number().optional(),
    key: z.string().optional(),
  }),
});

export const collections = { docs };
