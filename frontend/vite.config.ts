import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/v1': 'http://localhost:6006',
      '/chat': 'http://localhost:6006',
      '/auth': 'http://localhost:6006',
      '/health': 'http://localhost:6006',
    },
  },
})
