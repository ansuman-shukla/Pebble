import path from 'path';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  envDir: '..',
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    port: 5180,
    strictPort: true,
    watch: {
      ignored: ['**/playwright-report/**', '**/test-results/**'],
    },
  },
  build: {
    target: 'es2022',
  },
});
