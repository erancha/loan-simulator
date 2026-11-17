/**
 * A getByText matcher for text the page splits into several elements, as a reply or a card does
 * when it colours its values: it finds the innermost element whose whole text matches.
 */
export function wholeText(expected: string | RegExp) {
  const matches = (text: string | null) =>
    text !== null && (typeof expected === 'string' ? text === expected : expected.test(text))
  return (_content: string, element: Element | null) =>
    element !== null &&
    matches(element.textContent) &&
    [...element.children].every((child) => !matches(child.textContent))
}
