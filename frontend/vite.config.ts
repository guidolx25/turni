/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Spec §7 (v1.11) namespaces the whole API under /api, so dev needs exactly one
// proxy entry. It used to need one per top-level router, and those entries were
// also what made `/swaps` ambiguous in dev: the proxy claimed it before
// react-router could, so the client route and the endpoint fought over the name.
//
// `/healthz` is deliberately absent. It lives outside /api (§11: the host's
// probe points at it) and the frontend never calls it.
const backend = { target: 'http://127.0.0.1:8000', changeOrigin: true }
const apiPrefixes = ['/api']

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
