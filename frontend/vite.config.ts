import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The production build is written into the Python package, which serves it.
// During development, API calls are proxied to `mi-homekit-bridge demo`.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../src/mi_homekit_bridge/static',
    emptyOutDir: true,
    chunkSizeWarningLimit: 900,
  },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8080' },
  },
})
