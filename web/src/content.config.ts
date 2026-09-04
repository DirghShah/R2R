import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const blog = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/blog' }),
  schema: z.object({
    title: z.string(),
    // Doubles as the meta description, so write it for a search result.
    description: z.string(),
    published: z.date(),
    updated: z.date().optional(),
  }),
});

export const collections = { blog };
