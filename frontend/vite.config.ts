/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const apiTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8010'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3000,
    proxy: { '/api': { target: apiTarget, changeOrigin: true } },
  },
  preview: { port: 3000 },
  build: {
    rollupOptions: {
      output: {
        // Long-lived vendor chunks: app deploys don't invalidate them.
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (/recharts|d3-|victory-vendor|redux|immer|reselect/.test(id)) return 'charts'
          if (/motion|framer/.test(id)) return 'motion'
          if (/react-dom|react-router|scheduler|@tanstack/.test(id)) return 'react'
          return 'vendor'
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    // Break #9: render must be correct in a non-UK browser timezone.
    env: { TZ: 'Asia/Kolkata' },
  },
})
