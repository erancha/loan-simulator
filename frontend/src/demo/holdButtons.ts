/**
 * Disables every button of the page whose text is the label, including those the page draws
 * later, and returns the call that enables them again and stops watching. A button the page
 * itself disabled is left as it is.
 */
export function holdButtons(label: string): () => void {
  const held = new Set<HTMLButtonElement>()
  const hold = () => {
    for (const button of document.querySelectorAll('button')) {
      if (button.textContent === label && !button.disabled) {
        button.disabled = true
        held.add(button)
      }
    }
  }
  hold()
  const observer = new MutationObserver(hold)
  observer.observe(document.body, { childList: true, subtree: true })
  return () => {
    observer.disconnect()
    for (const button of held) button.disabled = false
    held.clear()
  }
}
