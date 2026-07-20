/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Spec §7 mounts the API at root (no /api prefix); one proxy entry per prefix.
const backend = { target: 'http://127.0.0.1:8000', changeOrigin: true }
const apiPrefixes = [
  '/auth',
  '/me',
  '/weeks',
  '/schedule',
  '/export',
  '/constraints',
  '/swaps',
  '/notifications',
  '/sacrifice',
  '/admin',
  '/root',
  '/healthz',
]

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Single deployable (spec §9): FastAPI serves built assets in prod. In dev,
    // proxy to the backend so the frontend uses same-origin paths either way.
    proxy: Object.fromEntries(apiPrefixes.map((prefix) => [prefix, backend])),
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
  },
})
