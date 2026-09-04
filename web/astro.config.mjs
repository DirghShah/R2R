// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// `site` feeds canonical URLs and the sitemap. Update it — and the Sitemap line
// in public/robots.txt — when a custom domain replaces the Vercel subdomain.
export default defineConfig({
  site: 'https://nosh.vercel.app',
  integrations: [sitemap()],
  build: { inlineStylesheets: 'auto' },
});
