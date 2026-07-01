import { defineConfig } from 'vite'

export default defineConfig({
  // No React plugin needed — we're using Babel standalone in the browser
  // Vite serves index.html and static assets as-is
  server: {
    port: 5183,
    open: true,
  },
  // Prevent Vite from trying to process the .jsx files as modules
  // They are loaded by Babel standalone as plain scripts
  optimizeDeps: {
    include: [],
  },
})
