import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/** Local backend (FastAPI): the dev server relays the API and its WebSockets to it */
const BACKEND = 'http://127.0.0.1:8417';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: BACKEND, ws: true },
    },
  },
  test: {
    environment: 'happy-dom',
    include: ['src/tests/**/*.test.{ts,tsx}'],
  },
});
