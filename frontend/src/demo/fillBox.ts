import type { Entry } from './backend.ts'

/** Sets a box's value the way typing does, so the page's own React state takes it. */
function type(box: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const prototype = box instanceof HTMLInputElement ? HTMLInputElement : HTMLTextAreaElement
  const setter = Object.getOwnPropertyDescriptor(prototype.prototype, 'value')?.set
  if (setter === undefined) throw new Error('the browser exposes no value setter')
  setter.call(box, value)
  box.dispatchEvent(new Event('input', { bubbles: true }))
}

/**
 * Shows what the person typed in the page's box of that label, the latest one when a closed
 * question left an older one behind, and returns the call that empties it again.
 */
export function fillBox({ box: label, value }: Entry): () => void {
  const boxes = document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(
    `input[aria-label="${CSS.escape(label)}"], textarea[aria-label="${CSS.escape(label)}"]`,
  )
  const box = boxes.item(boxes.length - 1)
  if (box === null) throw new Error(`the page has no box labelled ${label}`)
  type(box, value)
  return () => {
    if (box.isConnected) type(box, '')
  }
}
