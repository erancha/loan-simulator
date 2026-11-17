import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import type { CheckEvent } from '../api/types.ts'
import { OFFER_SOURCES } from '../copy.ts'
import {
  awaitingAvis,
  offerAwaiting,
  optionFixed36,
  optionOfferFixed,
  optionPrime36,
  recommendationPrime,
  REFERENCE_DECISION,
  withSeq,
} from '../test/fixtures.ts'
import { buildCard } from './card.ts'
import { initialState, reduce } from './events.ts'
import { RecommendationCard } from './RecommendationCard.tsx'
import { AWAITING_ONLY, EMPTY_CARD, EXAMPLES_NOTE, awaitingNote } from './copy.ts'
import { wholeText } from '../test/wholeText.ts'

function modelOf(...events: CheckEvent[]) {
  return buildCard(events.reduce(reduce, initialState))
}

const reference = modelOf(optionPrime36, optionFixed36, recommendationPrime, optionOfferFixed)

test('the reference model shows the decision and both labelled options', () => {
  render(<RecommendationCard model={reference} />)
  expect(screen.getByText(wholeText(REFERENCE_DECISION)).closest('.decision')).toHaveTextContent(
    'מה מחפשים',
  )

  const preferred = screen.getByText('מועדפת').closest('article')!
  expect(preferred).toHaveClass('option', 'option-preferred')
  expect(within(preferred).getByText(wholeText('904 ₪ בחודש'))).toBeInTheDocument()
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

test('a real offer shows its price under its payment, and an example does not', () => {
  render(<RecommendationCard model={reference} />)
  const offer = screen.getByRole('region', { name: 'הצעות חדשות, עוד לא נכללו בהמלצה' })
  expect(within(offer).getByText(wholeText('ריבית: כ-3,040 ₪ על 29,000 ₪'))).toHaveClass(
    'option-price',
  )
  expect(
    within(offer).getByText(
      wholeText('6.9% היום — מתחת לריבית הממוצעת בבנקים להלוואה צרכנית, כ-7.9% (נכון ל-08/2026)'),
    ),
  ).toHaveClass('option-price')
  const example = screen.getByText('מועדפת').closest('article')!
  expect(example.querySelector('.option-price')).toBeNull()
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

test('a recommendation on examples names every source of real offers and what to ask them', () => {
  render(<RecommendationCard model={modelOf(optionPrime36, optionFixed36, recommendationPrime)} />)
  const next = screen.getByRole('heading', { name: 'מה הלאה' }).closest('section')
  expect(next).toHaveTextContent(OFFER_SOURCES)
  expect(next).toHaveTextContent('"הצעה מגוף מלווה"')
  expect(next).toHaveTextContent('בכל הצעה כדאי לבקש')
})

test('options before a recommendation show without a decision or fold', () => {
  render(<RecommendationCard model={modelOf(optionPrime36)} />)
  expect(screen.getByRole('region', { name: 'האפשרויות שנבדקו' })).toBeInTheDocument()
  expect(screen.queryByText('למה המספרים האלה')).not.toBeInTheDocument()
  expect(screen.queryByText('מועדפת')).not.toBeInTheDocument()
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

test('the next-step title flashes while the recommendation rests on examples', () => {
  render(<RecommendationCard model={modelOf(optionPrime36, optionFixed36, recommendationPrime)} />)
  expect(screen.getByRole('heading', { name: 'מה הלאה' })).toHaveClass('attention-flash')
})

test('no next step once the card shows a real offer', () => {
  const recommendationOffer = withSeq(
    {
      ...recommendationPrime,
      data: { ...recommendationPrime.data, preferred: optionOfferFixed.data, alternative: null },
    },
    8,
  )
  const { unmount } = render(
    <RecommendationCard model={modelOf(optionOfferFixed, recommendationOffer)} />,
  )
  expect(screen.queryByRole('heading', { name: 'מה הלאה' })).not.toBeInTheDocument()
  unmount()

  render(<RecommendationCard model={reference} />)
  expect(screen.queryByRole('heading', { name: 'מה הלאה' })).not.toBeInTheDocument()
})

test('a check whose only offers await shows the awaiting line in place of a recommendation', () => {
  render(<RecommendationCard model={modelOf(offerAwaiting(1, awaitingAvis))} />)
  expect(screen.getByText(AWAITING_ONLY)).toBeInTheDocument()
  expect(screen.queryByText(EMPTY_CARD)).not.toBeInTheDocument()
})

test('awaiting offers are noted under the options of a recommendation', () => {
  render(
    <RecommendationCard
      model={modelOf(
        optionPrime36,
        optionFixed36,
        recommendationPrime,
        offerAwaiting(20, awaitingAvis),
      )}
    />,
  )
  const note = screen.getByText(awaitingNote(awaitingAvis.lender))
  expect(note).toHaveClass('awaiting-note')
  expect(screen.queryByText(AWAITING_ONLY)).not.toBeInTheDocument()
  expect(
    screen.getByText('חלופה').closest('article')!.compareDocumentPosition(note) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy()
  expect(
    note.compareDocumentPosition(screen.getByText(recommendationPrime.data.reasoning)) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy()
})

test('a check with nothing shows the empty card', () => {
  render(<RecommendationCard model={modelOf()} />)
  expect(screen.getByText(EMPTY_CARD)).toBeInTheDocument()
})
