import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ApiException } from '../api/client.ts'
import type { AwaitingOffer, Reading } from '../api/types.ts'
import {
  avisReading,
  awaitingAvis,
  awaitingMaxShort,
  identifiedMax,
  offerDropped,
} from '../test/fixtures.ts'
import type { ReadingsEntry } from './events.ts'
import { ReadingsCard } from './ReadingsCard.tsx'

const LIKELY_FIXED: AwaitingOffer = {
  ...awaitingAvis,
  likely: 'fixed_unlinked',
  type_words: ['fixed'],
}

function entry(
  offer: AwaitingOffer,
  settled: ReadingsEntry['settled'] = null,
  dropped: ReadingsEntry['dropped'] = null,
): ReadingsEntry {
  return { id: `r-${offer.awaiting_id}`, role: 'readings', offer, settled, dropped }
}

interface Options {
  offer?: AwaitingOffer
  settled?: ReadingsEntry['settled']
  dropped?: ReadingsEntry['dropped']
  loanAmount?: string
  live?: boolean
  onConfirm?: (reading: Reading) => Promise<void>
  onAnswerAmount?: (covers: boolean, reading: Reading | null) => Promise<void>
  onContinue?: () => Promise<boolean>
}

function renderCard({
  offer = LIKELY_FIXED,
  settled = null,
  dropped = null,
  loanAmount = '45000',
  live = true,
  onConfirm = vi.fn(() => Promise.resolve()),
  onAnswerAmount = vi.fn(() => Promise.resolve()),
  onContinue = vi.fn(() => Promise.resolve(true)),
}: Options = {}) {
  const onMarketChip = vi.fn()
  render(
    <ReadingsCard
      entry={entry(offer, settled, dropped)}
      loanAmount={loanAmount}
      live={live}
      onConfirm={onConfirm}
      onAnswerAmount={onAnswerAmount}
      onContinue={onContinue}
      onMarketChip={onMarketChip}
    />,
  )
  return { onConfirm, onAnswerAmount, onContinue, onMarketChip }
}

const card = () => document.getElementById('awaiting-a-1')!

const SHOWS_ALL =
  'the card shows the equivalent rate, what the word suggests, the question and the readings'

test(SHOWS_ALL, () => {
  renderCard()
  expect(card()).toHaveTextContent('ההחזר הזה שקול לריבית של כ-10.6% לשנה היום.')
  expect(card()).toHaveTextContent(
    'בגלל המילה "קבוע", סביר שההלוואה אינה צמודה למדד ושההחזר לא ישתנה. מלווים משתמשים במילה' +
      ' הזו גם כשרק הריבית קבועה וההחזר עדיין עולה עם המדד, ולכן כדאי לוודא זאת מול' +
      ' סוכנות אוויס רכבים.',
  )
  expect(card()).toHaveTextContent('השאלה לשאול את סוכנות אוויס רכבים')
  expect(card()).toHaveTextContent(
    'האם ההחזר החודשי של 969 ₪ נשאר זהה עד סוף ההלוואה? האם הריבית קבועה או תלויה בריבית' +
      ' הפריים, והאם ההלוואה צמודה למדד?',
  )
  const group = screen.getByRole('group', { name: 'לפי התשובה, זו אחת מהאפשרויות:' })
  const radios = within(group).getAllByRole('radio')
  expect(radios.map((radio) => radio.closest('label')?.textContent)).toEqual([
    'ריבית קבועה 10.58%, לא צמודה למדד — ההחזר לא משתנההסביר ביותר',
    'ריבית פריים + 5.83% — ההחזר משתנה עם ריבית הפריים',
    'ריבית קבועה כ-10.58%, צמודה למדד — ההחזר עולה עם המדד',
  ])
  expect(radios.map((radio) => (radio as HTMLInputElement).checked)).toEqual([true, false, false])
  expect(card()).toHaveTextContent(
    'אפשר להמשיך ולהזין הצעות נוספות. לאחר קבלת התשובה מסוכנות אוויס רכבים אפשר לחזור לנקודה' +
      ' הזו מהעיגול הצהוב שליד הבדיקה.',
  )
})

test('with no likely reading none is chosen and אישור asks for a choice', async () => {
  const { onConfirm } = renderCard({ offer: awaitingAvis })
  expect(screen.getAllByRole('radio').some((radio) => (radio as HTMLInputElement).checked)).toBe(
    false,
  )
  expect(screen.queryByText('הסביר ביותר')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'אישור' }))
  expect(screen.getByText('צריך לבחור אחת מהאפשרויות')).toBeInTheDocument()
  expect(onConfirm).not.toHaveBeenCalled()
})

test('אישור confirms the chosen reading', async () => {
  const { onConfirm } = renderCard()
  await userEvent.click(screen.getByRole('radio', { name: /ריבית פריים/ }))
  await userEvent.click(screen.getByRole('button', { name: 'אישור' }))
  expect(onConfirm).toHaveBeenCalledWith(awaitingAvis.readings[1])
})

test('the copy button copies the question', async () => {
  const user = userEvent.setup()
  const writeText = vi.spyOn(navigator.clipboard, 'writeText')
  renderCard()
  await user.click(screen.getByRole('button', { name: 'העתקה' }))
  expect(writeText).toHaveBeenCalledWith(
    'האם ההחזר החודשי של 969 ₪ נשאר זהה עד סוף ההלוואה? האם הריבית קבועה או תלויה בריבית' +
      ' הפריים, והאם ההלוואה צמודה למדד?',
  )
})

test('המשך להצעה נוספת עד לבירור השאלה continues and leaves the card open', async () => {
  const { onContinue } = renderCard()
  await userEvent.click(screen.getByRole('button', { name: 'המשך להצעה נוספת עד לבירור השאלה' }))
  expect(onContinue).toHaveBeenCalledOnce()
  expect(screen.getAllByRole('radio')).toHaveLength(3)
  expect(screen.getByRole('button', { name: 'אישור' })).toBeEnabled()
})

test('a market chip on the card hands the market question to the chat', async () => {
  const { onMarketChip } = renderCard()
  await userEvent.click(screen.getByRole('button', { name: 'פריים ומדדים' }))
  expect(onMarketChip).toHaveBeenCalledOnce()
})

test('a settled card shows the confirmed reading and no buttons', () => {
  renderCard({ settled: avisReading('fixed_unlinked') })
  expect(card()).toHaveTextContent('אושר: ריבית קבועה 10.58%, לא צמודה למדד.')
  expect(card()).not.toHaveTextContent('כדאי לוודא')
  expect(screen.queryAllByRole('button')).toEqual([])
  expect(screen.queryAllByRole('radio')).toEqual([])
})

test('a settled card shows the saved reading even when the card never offered it', () => {
  const total: Reading = {
    ...avisReading('prime_margin'),
    kind: 'prime_total',
    track: { ...avisReading('prime_margin').track, prime_spread: '6.20' },
    total_rate: '10.95',
  }
  renderCard({ settled: total })
  expect(card()).toHaveTextContent('אושר:')
  expect(card()).toHaveTextContent('10.95%')
})

test('a card is not answerable while a turn runs, but its question can still be copied', () => {
  renderCard({ live: false })
  for (const radio of screen.getAllByRole('radio')) expect(radio).toBeDisabled()
  const copy = screen.getByRole('button', { name: 'העתקה' })
  expect(copy).toBeEnabled()
  for (const button of screen.getAllByRole('button').filter((b) => b !== copy)) {
    expect(button).toBeDisabled()
  }
})

const checkedKinds = () =>
  screen
    .getAllByRole('radio')
    .filter((radio) => (radio as HTMLInputElement).checked)
    .map((radio) => radio.closest('label')?.textContent)

/** Renders the card, then hands back a re-render of it with the same awaiting id. */
function renderReplaced(first: AwaitingOffer, onConfirm = vi.fn(() => Promise.resolve())) {
  const props = {
    loanAmount: '45000',
    live: true,
    onConfirm,
    onAnswerAmount: vi.fn(),
    onContinue: vi.fn(),
    onMarketChip: vi.fn(),
  }
  const { rerender } = render(<ReadingsCard entry={entry(first)} {...props} />)
  return {
    onConfirm,
    replace: (offer: AwaitingOffer) => rerender(<ReadingsCard entry={entry(offer)} {...props} />),
  }
}

test('an offer emitted again with another likely reading chooses that one', () => {
  const { replace } = renderReplaced(awaitingAvis)
  expect(checkedKinds()).toEqual([])
  replace(LIKELY_FIXED)
  expect(checkedKinds()).toEqual([
    'ריבית קבועה 10.58%, לא צמודה למדד — ההחזר לא משתנההסביר ביותר',
  ])
})

const NARROWED_LIKELY =
  'readings narrowed past the chosen one choose the likely one, and אישור confirms it'

test(NARROWED_LIKELY, async () => {
  const { replace, onConfirm } = renderReplaced(awaitingAvis)
  await userEvent.click(screen.getByRole('radio', { name: /ריבית פריים/ }))
  const fixedOnly = {
    ...LIKELY_FIXED,
    readings: awaitingAvis.readings.filter((r) => r.kind !== 'prime_margin'),
  }
  replace(fixedOnly)
  expect(checkedKinds()).toEqual([
    'ריבית קבועה 10.58%, לא צמודה למדד — ההחזר לא משתנההסביר ביותר',
  ])
  await userEvent.click(screen.getByRole('button', { name: 'אישור' }))
  expect(onConfirm).toHaveBeenCalledWith(awaitingAvis.readings[0])
})

test('readings narrowed past the chosen one with no likely reading choose none', async () => {
  const { replace, onConfirm } = renderReplaced(awaitingAvis)
  await userEvent.click(screen.getByRole('radio', { name: /ריבית פריים/ }))
  replace({ ...awaitingAvis, readings: [awaitingAvis.readings[0]] })
  expect(checkedKinds()).toEqual([])
  await userEvent.click(screen.getByRole('button', { name: 'אישור' }))
  expect(screen.getByText('צריך לבחור אחת מהאפשרויות')).toBeInTheDocument()
  expect(onConfirm).not.toHaveBeenCalled()
})

test('a confirmation that went through keeps the card locked until the offer settles', async () => {
  const { onConfirm } = renderCard()
  await userEvent.click(screen.getByRole('button', { name: 'אישור' }))
  expect(onConfirm).toHaveBeenCalledOnce()
  expect(screen.getByRole('button', { name: 'אישור' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'המשך להצעה נוספת עד לבירור השאלה' })).toBeDisabled()
  for (const radio of screen.getAllByRole('radio')) expect(radio).toBeDisabled()
})

test('a refused confirmation shows its reason and keeps the card', async () => {
  const onConfirm = vi.fn(() => Promise.reject(new ApiException(422, 'the offer is refused')))
  renderCard({ onConfirm })
  await userEvent.click(screen.getByRole('button', { name: 'אישור' }))
  expect(await screen.findByText('הערך לא התקבל: the offer is refused')).toBeInTheDocument()
  expect(screen.getAllByRole('radio')).toHaveLength(3)
  expect(screen.getByRole('button', { name: 'אישור' })).toBeEnabled()
})

const maxCard = () => document.getElementById('awaiting-a-max')!

const IDENTIFIED_SHORT =
  'an identified offer quoted for less shows its reading and asks the lender for the loan amount'

test(IDENTIFIED_SHORT, () => {
  renderCard({ offer: awaitingMaxShort })
  expect(maxCard()).toHaveTextContent('זיהיתי שזו הלוואה בריבית פריים + 6.45%.')
  expect(maxCard()).toHaveTextContent('ההחזר שמסרת, 934 ₪, תואם לחישוב הזה.')
  expect(maxCard()).toHaveTextContent('ההצעה של מקס היא על 20,000 ₪, והבדיקה היא על 45,000 ₪.')
  expect(maxCard()).toHaveTextContent('השאלה לשאול את מקס')
  expect(maxCard()).toHaveTextContent('האם תוכלו להציע 45,000 ₪ באותם תנאים?')
  expect(screen.queryAllByRole('radio')).toEqual([])
  expect(screen.queryByRole('button', { name: 'אישור' })).toBeNull()
  expect(screen.getByRole('button', { name: 'המשך להצעה נוספת עד לבירור השאלה' })).toBeEnabled()
})

test('כן, באותם תנאים on an identified offer answers with its one reading', async () => {
  const { onAnswerAmount, onConfirm } = renderCard({ offer: awaitingMaxShort })
  await userEvent.click(screen.getByRole('button', { name: 'כן, באותם תנאים' }))
  expect(onAnswerAmount).toHaveBeenCalledWith(true, identifiedMax.reading)
  expect(onConfirm).not.toHaveBeenCalled()
})

test('לא answers that the lender does not lend the loan amount', async () => {
  const { onAnswerAmount } = renderCard({ offer: awaitingMaxShort })
  await userEvent.click(screen.getByRole('button', { name: 'לא' }))
  expect(onAnswerAmount).toHaveBeenCalledWith(false, null)
})

test('an offer quoted for the loan amount or more asks no amount question', () => {
  renderCard({ offer: { ...LIKELY_FIXED, amount: '45000' }, loanAmount: '45000' })
  expect(card()).not.toHaveTextContent('באותם תנאים')
  expect(screen.getByRole('button', { name: 'אישור' })).toBeEnabled()
  expect(screen.queryByRole('button', { name: 'לא' })).toBeNull()
})

const READINGS_SHORT =
  'a card of readings quoted for less asks both questions and answers with the chosen reading'

test(READINGS_SHORT, async () => {
  const short = { ...LIKELY_FIXED, amount: '20000' }
  const writeText = vi.spyOn(navigator.clipboard, 'writeText')
  const { onAnswerAmount } = renderCard({ offer: short })
  expect(card()).toHaveTextContent(
    'ההצעה של סוכנות אוויס רכבים היא על 20,000 ₪, והבדיקה היא על 45,000 ₪.',
  )
  expect(screen.getAllByRole('radio')).toHaveLength(3)
  await userEvent.click(screen.getByRole('button', { name: 'העתקה' }))
  expect(writeText).toHaveBeenCalledWith(
    'האם ההחזר החודשי של 969 ₪ נשאר זהה עד סוף ההלוואה? האם הריבית קבועה או תלויה בריבית' +
      ' הפריים, והאם ההלוואה צמודה למדד? האם תוכלו להציע 45,000 ₪ באותם תנאים?',
  )
  expect(screen.queryByRole('button', { name: 'אישור' })).toBeNull()
  expect(screen.getByRole('button', { name: 'המשך להצעה נוספת עד לבירור השאלה' })).toBeEnabled()
  await userEvent.click(screen.getByRole('radio', { name: /ריבית פריים/ }))
  await userEvent.click(screen.getByRole('button', { name: 'כן, באותם תנאים' }))
  expect(onAnswerAmount).toHaveBeenCalledWith(true, awaitingAvis.readings[1])
})

test('כן, באותם תנאים on a card of readings asks for a choice first', async () => {
  const { onAnswerAmount } = renderCard({ offer: { ...awaitingAvis, amount: '20000' } })
  await userEvent.click(screen.getByRole('button', { name: 'כן, באותם תנאים' }))
  expect(screen.getByText('צריך לבחור אחת מהאפשרויות')).toBeInTheDocument()
  expect(onAnswerAmount).not.toHaveBeenCalled()
})

test('a refused amount answer shows the reason and unlocks the card', async () => {
  const refused = vi.fn(() => Promise.reject(new ApiException(422, 'refused')))
  renderCard({ offer: awaitingMaxShort, onAnswerAmount: refused })
  await userEvent.click(screen.getByRole('button', { name: 'לא' }))
  expect(maxCard().querySelector('.field-error')).not.toBeNull()
  expect(screen.getByRole('button', { name: 'לא' })).toBeEnabled()
})

test('a dropped card says the offer does not cover the loan and shows no buttons', () => {
  renderCard({
    offer: awaitingMaxShort,
    dropped: offerDropped(5, awaitingMaxShort, '45000').data,
  })
  expect(maxCard()).toHaveTextContent(
    'ההצעה של מקס לא מכסה את ההלוואה של 45,000 ₪, ולכן היא לא נכנסת להשוואה.',
  )
  expect(maxCard()).not.toHaveTextContent('האם תוכלו')
  expect(screen.queryAllByRole('button')).toEqual([])
})
