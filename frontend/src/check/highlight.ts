/**
 * Brief animations that draw the eye to an element: a fading outline on a card the page just
 * brought into view, and an arc sweeping the edge of a chip the page points to.
 */

/** The class whose animation draws a card's outline. */
const CARD_FOCUS = 'card-focus'
/** The class whose animation sweeps an arc around a chip's edge. */
const BORDER_SWEEP = 'border-sweep'

export function highlight(card: HTMLElement) {
  restart(card, CARD_FOCUS)
}

export function drawAttention(chip: HTMLElement) {
  restart(chip, BORDER_SWEEP)
}

/** Removing the class and reading the layout restarts its animation for a second request. */
function restart(element: HTMLElement, className: string) {
  element.classList.remove(className)
  void element.offsetWidth
  element.classList.add(className)
}
