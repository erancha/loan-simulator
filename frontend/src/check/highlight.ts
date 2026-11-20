/**
 * The highlight of a card the page just brought into view: an outline that fades.
 */

/** The class whose animation draws the highlight. */
const CARD_FOCUS = 'card-focus'

export function highlight(card: HTMLElement) {
  // Removing the class and reading the layout restarts the highlight for a second request.
  card.classList.remove(CARD_FOCUS)
  void card.offsetWidth
  card.classList.add(CARD_FOCUS)
}
