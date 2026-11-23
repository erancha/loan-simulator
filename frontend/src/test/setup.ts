import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(cleanup)

// jsdom has no layout, so it has no ResizeObserver; tests that need to trigger one stub their own.
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// jsdom has no layout, so it has no scrollIntoView; a test that checks a scroll spies on this no-op.
Element.prototype.scrollIntoView = () => {}
