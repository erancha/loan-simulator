import { Fragment, type ReactNode } from 'react'

/** A span the model wrapped in double asterisks, as Markdown marks bold. */
const BOLD = /\*\*(.+?)\*\*/gs

/**
 * An amount in shekels, a percentage or a number of months, as the model writes them: "38,610 ₪",
 * "7.9%", the 60 of "60 חודשים" and of "מספר החודשים: 60".
 */
const VALUE = /(\d[\d,.]*\s?₪|\d[\d.]*%|\d+(?= חודשים)|(?<=החודשים: )\d+)/g

/**
 * A reply's text with its **marked** spans in bold. Only this one mark is read: the reply stays
 * plain text otherwise, and an unclosed mark (a reply still streaming) shows as typed.
 *
 * A marked span alone on its line is a section heading: it renders as a block whose own margin
 * replaces the line breaks after it, so a heading sits half a line above its text rather than a
 * whole empty line.
 *
 * run renders each run of text between and inside the marks; by default the text itself.
 */
export function withBold(
  text: string,
  run: (text: string) => ReactNode = (text) => text,
): ReactNode[] {
  // split puts each captured span at an odd index, between the plain runs around it.
  const parts = text.split(BOLD)
  const isHeading = (index: number) => {
    const before = parts[index - 1]
    const after = parts[index + 1]
    return (before === '' || before.endsWith('\n')) && (after === '' || after.startsWith('\n'))
  }
  return parts.map((part, index) => {
    if (index % 2 === 0) {
      const plain = index > 0 && isHeading(index - 1) ? part.replace(/^\n+/, '') : part
      return <Fragment key={index}>{run(plain)}</Fragment>
    }
    return isHeading(index) ? (
      <strong key={index} className="reply-heading">
        {run(part)}
      </strong>
    ) : (
      <strong key={index}>{run(part)}</strong>
    )
  })
}

/**
 * A reply as withBold renders it, with every amount, percentage and number of months in the
 * colour of a value, so a person skimming a long reply finds its figures.
 */
export function withValues(text: string): ReactNode[] {
  return withBold(text, (run) =>
    // split puts each captured value at an odd index, between the plain runs around it.
    run.split(VALUE).map((part, index) =>
      index % 2 === 0 ? (
        part
      ) : (
        <span key={index} className="reply-value">
          {part}
        </span>
      ),
    ),
  )
}
