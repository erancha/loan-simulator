import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const AGENT = 'http://localhost:8101'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': AGENT } },
})
