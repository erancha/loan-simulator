import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import type { CheckEvent } from '../api/types.ts'
import { OFFER_SOURCES } from '../copy.ts'
import {
  optionFixed36,
  optionOfferFixed,
  optionPrime36,
  recommendationPrime,
  REFERENCE_DECISION,
} from '../test/fixtures.ts'
import { buildCard } from './card.ts'
import { initialState, reduce } from './events.ts'
import { RecommendationCard } from './RecommendationCard.tsx'
import { EXAMPLES_NOTE } from './copy.ts'

function modelOf(...events: CheckEvent[]) {
  return buildCard(events.reduce(reduce, initialState))
}

const reference = modelOf(optionPrime36, optionFixed36, recommendationPrime, optionOfferFixed)

test('the reference model shows the decision and both labelled options', () => {
  render(<RecommendationCard model={reference} />)
  expect(screen.getByText(REFERENCE_DECISION).closest('.decision')).toHaveTextContent('מה מחפשים')

  const preferred = screen.getByText('מומלצת').closest('article')!
  expect(preferred).toHaveClass('option', 'option-preferred')
  expect(within(preferred).getByText('904 ₪ בחודש')).toBeInTheDocument()
  expect(within(preferred).getByText('עד ~955 ₪ אם הריבית תעלה כמו ב-2022–2025')).toHaveClass(
    'chip',
    'chip-amber',
  )

  const alternative = screen.getByText('חלופה').closest('article')!
  expect(alternative).not.toHaveClass('option-preferred')
  expect(within(alternative).getByText('התשלום לא ישתנה')).toHaveClass('chip', 'chip-green')
})

test('options outside the recommendation sit in their titled group', () => {
  render(<RecommendationCard model={reference} />)
  const group = screen.getByRole('region', { name: 'הצעות חדשות, עוד לא נכללו בהמלצה' })
  expect(within(group).getByText('הצעה מבנק הפועלים · 02.11.2026')).toBeInTheDocument()
})

test('the reasoning stands apart from the figures', () => {
  render(<RecommendationCard model={reference} />)
  expect(screen.getByText(recommendationPrime.data.reasoning)).toHaveClass('reasoning')
})

test('the fold is open and lists totals; it can be closed', async () => {
  render(<RecommendationCard model={reference} />)
  const fold = screen.getByText('למה המספרים האלה').closest('details')!
  expect(fold).toHaveAttribute('open')
  const rows = within(fold).getAllByRole('row').map((row) => row.textContent)
  expect(rows).toHaveLength(4)
  expect(within(fold).getByRole('columnheader', { name: 'סך התשלומים בתנאים של היום' }))
    .toBeInTheDocument()
  expect(within(fold).getByRole('columnheader', { name: 'טווח בתרחישים' })).toBeInTheDocument()
  expect(rows[1]).toContain('32,547 ₪')
  expect(rows[1]).toContain('32,432–34,026 ₪ (לפי 85 תקופות מהעבר)')
  expect(rows[2]).toContain('32,667 ₪—')
  const rowHeaders = within(fold).getAllByRole('rowheader')
  expect(rowHeaders[0]).toHaveTextContent('לפי ריבית ממוצעת בבנקים')
  expect(rowHeaders[2]).toHaveTextContent('הצעה מבנק הפועלים · 02.11.2026')

  await userEvent.click(screen.getByText('למה המספרים האלה'))
  expect(fold).not.toHaveAttribute('open')
})

test('a recommendation names every source of real offers and what to ask them', () => {
  render(<RecommendationCard model={reference} />)
  const next = screen.getByRole('heading', { name: 'מה הלאה' }).closest('section')
  expect(next).toHaveTextContent(OFFER_SOURCES)
  expect(next).toHaveTextContent('"הצעה מגוף מלווה"')
  expect(next).toHaveTextContent('בכל הצעה כדאי לבקש')
})

test('options before a recommendation show without a decision or fold', () => {
  render(<RecommendationCard model={modelOf(optionPrime36)} />)
  expect(screen.getByRole('region', { name: 'האפשרויות שנבדקו' })).toBeInTheDocument()
  expect(screen.queryByText('למה המספרים האלה')).not.toBeInTheDocument()
  expect(screen.queryByText('מומלצת')).not.toBeInTheDocument()
})

test('no options: the empty line', () => {
  render(<RecommendationCard model={modelOf()} />)
  expect(
    screen.getByText('ההמלצה תופיע כאן אחרי שנכיר את ההלוואה.'),
  ).toBeInTheDocument()
})

test('a sample option carries a chip saying so and a real offer does not', () => {
  render(<RecommendationCard model={reference} />)

  const offer = screen.getAllByText('הצעה מבנק הפועלים · 02.11.2026')[0].closest('article')!
  expect(within(offer).queryByText('דוגמא')).not.toBeInTheDocument()
  const chips = screen.getAllByText('דוגמא').filter((chip) => chip.closest('article') !== null)
  expect(chips).toHaveLength(2)
  expect(chips[0]).toHaveClass('chip', 'chip-example')
  expect(chips[0].closest('article')).toHaveClass('option-example')
  expect(offer).not.toHaveClass('option-example')
})

test('a sample carries its chip in the totals table too, and a real offer does not', () => {
  render(<RecommendationCard model={reference} />)
  const rowHeaders = within(screen.getByRole('table')).getAllByRole('rowheader')

  expect(rowHeaders.map((header) => within(header).queryByText('דוגמא') !== null)).toEqual([
    true,
    true,
    false,
  ])
  expect(within(rowHeaders[0]).getByText('דוגמא')).toHaveClass('chip', 'chip-example')
})

test('a line above the options says what a sample is, once, only when one is shown', () => {
  const { unmount } = render(<RecommendationCard model={reference} />)
  expect(screen.getAllByText(EXAMPLES_NOTE)).toHaveLength(1)
  unmount()

  render(<RecommendationCard model={modelOf(optionOfferFixed)} />)
  expect(screen.queryByText(EXAMPLES_NOTE)).not.toBeInTheDocument()
})

test('no cushion text remains', () => {
  const { container } = render(<RecommendationCard model={reference} />)
  expect(container.textContent).not.toMatch(/כרית|מקדמה|בטחון/)
})
