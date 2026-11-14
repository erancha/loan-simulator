import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'
import { buildInfoDefines } from './buildInfo.ts'

export default defineConfig({
  plugins: [react()],
  define: buildInfoDefines(),
  test: {
    environment: 'jsdom',
    pool: 'threads',
    globals: false,
    setupFiles: './src/test/setup.ts',
  },
})
