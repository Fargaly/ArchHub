import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';

// Build model (decoupled from any live daemon):
//   - File-based routing (src/pages/*.astro → /<page>)
//   - Static output — `astro build` reads ONLY committed content under
//     src/content/ (build-info.json, pricing.json, skills-export.json) +
//     public/ (the /brain viz). No prebuild, no daemon, deployable anywhere.
//   - The freshness footer is stamped at build time in src/layouts/Base.astro
//     from src/content/build-info.json (git sha + date).
//   - Maintainers refresh committed content with `npm run refresh-content`
//     (regenerates build-info/pricing/skills + copies the brain viz).

export default defineConfig({
  site: 'https://archhub.io',
  output: 'static',
  integrations: [mdx()],
  build: {
    format: 'directory',
  },
  vite: {
    // No client-side state; pure static. Pricing/skills resolved at build.
    ssr: { noExternal: [] },
  },
});
