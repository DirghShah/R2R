// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// `site` feeds canonical URLs and the sitemap. The apex is canonical, not www —
// keep this in sync with the primary domain set in Vercel, and with the Sitemap
// line in public/robots.txt.
export default defineConfig({
  site: 'https://noshmap.app',
  integrations: [sitemap()],
  build: { inlineStylesheets: 'auto' },
});
