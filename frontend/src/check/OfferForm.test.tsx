import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Question } from '../api/types.ts'
import {
  OFFER_ADD_TRACK,
  OFFER_CONTINUE,
  OFFER_FIX_ABOVE,
  OFFER_LENDER_LABEL,
  OFFER_LENDER_MISSING,
  OFFER_LINKED,
  OFFER_MAX_TRACKS,
  OFFER_MONTHS_INVALID,
  OFFER_MONTHS_LABEL,
  OFFER_RATE_INVALID,
  OFFER_REMOVE_TRACK,
  offerKindBox,
  offerLine,
  offerRateBox,
} from './copy.ts'
import type { QuestionEntry } from './events.ts'
import { QuestionBubble } from './QuestionBubble.tsx'

type OfferQuestion = Extract<Question, { kind: 'offer' }>

const EMPTY: OfferQuestion = { kind: 'offer', lender: null, tracks: [], max_term_months: null }

const PENSION_FUND_LINE =
  'קיבלתי הצעה מגוף מלווה, קרן הפנסיה: (1) פריים פלוס 0.5%, לא צמוד למדד (2) ריבית קבועה 3.5%,' +
  ' צמוד למדד. לתקופה של עד 84 חודשים, בתשלומים חודשיים שווים.'

function form(question: OfferQuestion, live = true) {
  const entry: QuestionEntry = { id: 'q-1', role: 'question', question, leadIn: null, answered: !live }
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entry}
      live={live}
      finances={null}
      ceiling={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  return onAnswer
}

const lenderBox = () => screen.getByRole('textbox', { name: OFFER_LENDER_LABEL })
const monthsBox = () => screen.getByRole('textbox', { name: OFFER_MONTHS_LABEL })
const rateBox = (row: number) => screen.getByRole('textbox', { name: offerRateBox(row) })
const kindBox = (row: number) => screen.getByRole('combobox', { name: offerKindBox(row) })
const proceed = () => screen.getByRole('button', { name: OFFER_CONTINUE })

test('the worded offer names the lender, every track with its linkage, and the period', () => {
  const line = offerLine(
    'קרן הפנסיה',
    [
      { kind: 'prime_plus', rate: '0.5', linked: false },
      { kind: 'fixed', rate: '3.5', linked: true },
    ],
    84,
  )
  expect(line).toBe(PENSION_FUND_LINE)
  expect(offerLine('הבנק', [{ kind: 'prime_minus', rate: '0.25', linked: false }], 60)).toContain(
    '(1) פריים מינוס 0.25%, לא צמוד למדד.',
  )
})

test('an empty form marks the missing boxes and sends nothing', async () => {
  const user = userEvent.setup()
  const onAnswer = form(EMPTY)
  await user.click(proceed())
  expect(screen.getByText(OFFER_LENDER_MISSING)).toBeInTheDocument()
  expect(screen.getByText(OFFER_RATE_INVALID)).toBeInTheDocument()
  expect(screen.getByText(OFFER_MONTHS_INVALID)).toBeInTheDocument()
  expect(onAnswer).not.toHaveBeenCalled()
})

test('a filled form sends one line with the lender, every track and the period', async () => {
  const user = userEvent.setup()
  const onAnswer = form(EMPTY)
  await user.type(lenderBox(), 'קרן הפנסיה')
  await user.type(rateBox(1), '0.5')
  await user.click(screen.getByRole('button', { name: OFFER_ADD_TRACK }))
  await user.selectOptions(kindBox(2), 'fixed')
  await user.type(rateBox(2), '3.5')
  await user.click(screen.getByRole('checkbox', { name: OFFER_LINKED }))
  await user.type(monthsBox(), '84')
  await user.click(proceed())
  expect(onAnswer).toHaveBeenCalledTimes(1)
  expect(onAnswer).toHaveBeenCalledWith({ line: PENSION_FUND_LINE, update: null })
})

test('boxes arrive filled with what the assistant passed', () => {
  form({
    kind: 'offer',
    lender: 'הבנק',
    tracks: [{ rate_kind: 'prime', rate: '-0.25', cpi_linked: false }],
    max_term_months: null,
  })
  expect(lenderBox()).toHaveValue('הבנק')
  expect(kindBox(1)).toHaveValue('prime_minus')
  expect(rateBox(1)).toHaveValue('0.25')
  expect(monthsBox()).toHaveValue('')
})

test('only a fixed-interest row can be linked to the index', async () => {
  const user = userEvent.setup()
  const onAnswer = form({ ...EMPTY, lender: 'הבנק', max_term_months: 60 })
  expect(screen.queryByRole('checkbox')).toBeNull()
  await user.selectOptions(kindBox(1), 'fixed')
  await user.click(screen.getByRole('checkbox', { name: OFFER_LINKED }))
  await user.selectOptions(kindBox(1), 'prime_minus')
  expect(screen.queryByRole('checkbox')).toBeNull()
  await user.type(rateBox(1), '0.25')
  await user.click(proceed())
  expect(onAnswer.mock.calls[0][0].line).toContain('(1) פריים מינוס 0.25%, לא צמוד למדד.')
})

test('a percentage typed with a comma or a percent sign is read as the number', async () => {
  const user = userEvent.setup()
  const onAnswer = form({ ...EMPTY, lender: 'הבנק', max_term_months: 60 })
  await user.selectOptions(kindBox(1), 'fixed')
  await user.type(rateBox(1), ' 3,5% ')
  await user.click(proceed())
  expect(onAnswer.mock.calls[0][0].line).toContain('ריבית קבועה 3.5%,')
})

test('a stray comma or dot around a percentage is ignored', async () => {
  const user = userEvent.setup()
  const onAnswer = form({ ...EMPTY, lender: 'הבנק', max_term_months: 84 })
  await user.type(rateBox(1), '0.5,')
  await user.click(proceed())
  expect(onAnswer.mock.calls[0][0].line).toContain('(1) פריים פלוס 0.5%,')
})

test('a refused form says beside its button that a box above needs fixing', async () => {
  const user = userEvent.setup()
  form({ ...EMPTY, lender: 'הבנק', max_term_months: 84 })
  expect(screen.queryByText(OFFER_FIX_ABOVE)).toBeNull()
  await user.type(rateBox(1), 'abc')
  await user.click(proceed())
  expect(screen.getByText(OFFER_FIX_ABOVE)).toBeInTheDocument()
})

test('a percentage above 30 and a lender of spaces are refused', async () => {
  const user = userEvent.setup()
  const onAnswer = form({ ...EMPTY, max_term_months: 60 })
  await user.type(lenderBox(), '   ')
  await user.type(rateBox(1), '31')
  await user.click(proceed())
  expect(screen.getByText(OFFER_LENDER_MISSING)).toBeInTheDocument()
  expect(screen.getByText(OFFER_RATE_INVALID)).toBeInTheDocument()
  expect(onAnswer).not.toHaveBeenCalled()
})

test('a period that is not a whole number of months in range is refused', async () => {
  const user = userEvent.setup()
  const onAnswer = form({
    kind: 'offer',
    lender: 'הבנק',
    tracks: [{ rate_kind: 'fixed', rate: '4', cpi_linked: false }],
    max_term_months: null,
  })
  for (const months of ['5', '12.5', '361']) {
    await user.clear(monthsBox())
    await user.type(monthsBox(), months)
    await user.click(proceed())
    expect(screen.getByText(OFFER_MONTHS_INVALID)).toBeInTheDocument()
  }
  expect(onAnswer).not.toHaveBeenCalled()
})

test('rows are added up to the limit and a single row has no remove button', async () => {
  const user = userEvent.setup()
  form(EMPTY)
  expect(screen.queryByRole('button', { name: OFFER_REMOVE_TRACK })).toBeNull()
  for (let row = 1; row < OFFER_MAX_TRACKS; row++) {
    await user.click(screen.getByRole('button', { name: OFFER_ADD_TRACK }))
  }
  expect(screen.queryByRole('button', { name: OFFER_ADD_TRACK })).toBeNull()
  const removes = screen.getAllByRole('button', { name: OFFER_REMOVE_TRACK })
  expect(removes).toHaveLength(OFFER_MAX_TRACKS)
  await user.click(removes[0])
  expect(screen.getAllByRole('combobox')).toHaveLength(OFFER_MAX_TRACKS - 1)
})

test('an answered form takes no more input', () => {
  form({ ...EMPTY, lender: 'הבנק' }, false)
  expect(screen.queryByRole('textbox')).toBeNull()
  expect(screen.queryByRole('button', { name: OFFER_CONTINUE })).toBeNull()
})
