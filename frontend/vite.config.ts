import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { buildInfoDefines } from './buildInfo.ts'

const AGENT = 'http://localhost:8101'

export default defineConfig({
  plugins: [react()],
  define: buildInfoDefines(),
  server: { proxy: { '/api': AGENT } },
  // The demo is a second page: the real app over a recorded check (src/demo/).
  build: { rolldownOptions: { input: ['index.html', 'demo.html'] } },
})
