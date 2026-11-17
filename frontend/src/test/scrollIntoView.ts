import { vi } from 'vitest'

// The property as the test environment defines it: absent in jsdom, which has no layout.
const ORIGINAL = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView')

/** Stands in a mock for scrollIntoView on every element; restoreScrollIntoView undoes it. */
export function stubScrollIntoView() {
  const scrolled = vi.fn()
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    configurable: true,
    writable: true,
    value: scrolled,
  })
  return scrolled
}

export function restoreScrollIntoView() {
  if (ORIGINAL === undefined) delete (Element.prototype as Partial<Element>).scrollIntoView
  else Object.defineProperty(Element.prototype, 'scrollIntoView', ORIGINAL)
}
