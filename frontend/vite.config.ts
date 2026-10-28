import path from 'path';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The browser only calls its own origin; vite (dev and preview) forwards /api (and the live WebSocket) to the backend.
const apiProxy = {
  '/api': {
    target: process.env.PEBBLE_API_TARGET ?? 'http://localhost:8100',
    ws: true,
  },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  envDir: '..',
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5180,
    strictPort: true,
    proxy: apiProxy,
    watch: {
      ignored: ['**/playwright-report/**', '**/test-results/**'],
    },
  },
  preview: {
    proxy: apiProxy,
  },
  build: {
    target: 'es2022',
  },
});
