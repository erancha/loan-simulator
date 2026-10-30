import type { ReactNode } from 'react'

/** A span the model wrapped in double asterisks, as Markdown marks bold. */
const BOLD = /\*\*(.+?)\*\*/gs

/**
 * A reply's text with its **marked** spans in bold. Only this one mark is read: the reply stays
 * plain text otherwise, and an unclosed mark (a reply still streaming) shows as typed.
 *
 * A marked span alone on its line is a section heading: it renders as a block whose own margin
 * replaces the line breaks after it, so a heading sits half a line above its text rather than a
 * whole empty line.
 */
export function withBold(text: string): ReactNode[] {
  // split puts each captured span at an odd index, between the plain runs around it.
  const parts = text.split(BOLD)
  const isHeading = (index: number) => {
    const before = parts[index - 1]
    const after = parts[index + 1]
    return (before === '' || before.endsWith('\n')) && (after === '' || after.startsWith('\n'))
  }
  return parts.map((part, index) => {
    if (index % 2 === 0) return index > 0 && isHeading(index - 1) ? part.replace(/^\n+/, '') : part
    return isHeading(index) ? (
      <strong key={index} className="reply-heading">
        {part}
      </strong>
    ) : (
      <strong key={index}>{part}</strong>
    )
  })
}
