import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: './openapi.json',
  output: { path: './src/lib/client', postProcess: ['prettier'] },
  plugins: ['@hey-api/client-fetch'],
});
