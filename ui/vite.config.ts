/// <reference types="vitest/config" />
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

const api = process.env.SERPENT_API ?? 'http://127.0.0.1:8971';

export default defineConfig({
  base: '/ui/',
  plugins: [svelte()],
  build: { outDir: '../src/serpent/ui_dist', emptyOutDir: true, target: 'es2022' },
  server: {
    proxy: Object.fromEntries(
      ['/api', '/admin', '/v1', '/p', '/healthz', '/readyz'].map((p) => [p, api]),
    ),
  },
  resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined,
  test: { environment: 'jsdom', include: ['src/**/*.test.ts'] },
});
