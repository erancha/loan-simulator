import { expect, test } from 'vitest'
import {
  assistantMessage,
  awaitingAvis,
  checkArchived,
  chartShown,
  cpiChart,
  scenarioCpi5,
  scenarioShown,
  delta,
  ceilingSet,
  examplesRemoved,
  finances,
  financesUpdated,
  identifiedMax,
  loan,
  loanSet,
  optionFixed36,
  optionOfferFixed,
  optionPrime36,
  offerAwaiting,
  offerIdentified,
  avisReading,
  offerSettled,
  offerDropped,
  awaitingMaxShort,
  offerUnrecognized,
  questionAsked,
  recommendationPrime,
  turnFailed,
  termSet,
  turnStatus,
  userMessage,
  withSeq,
} from '../test/fixtures.ts'
import type { CheckEvent } from '../api/types.ts'
import {
  holdsOption,
  initialState,
  isArchived,
  liveQuestion,
  quotedBelowLoan,
  recommendationReplyId,
  reduce,
  termComparisons,
} from './events.ts'

const play = (events: CheckEvent[]) => events.reduce(reduce, initialState)

test('replay builds the conversation in order', () => {
  const state = play([
    userMessage(1, 'שלום'),
    assistantMessage(2, 'a1', 'היי'),
    userMessage(3, 'עוד שאלה'),
  ])
  expect(state.messages).toEqual([
    { id: 'u-1', role: 'user', text: 'שלום', complete: true },
    { id: 'a1', role: 'assistant', text: 'היי', complete: true },
    { id: 'u-3', role: 'user', text: 'עוד שאלה', complete: true },
  ])
  expect(state.lastSeq).toBe(3)
})

test('delta then complete: one message, text replaced, complete flips', () => {
  const streaming = play([delta('a1', 'ה'), delta('a1', 'היי')])
  expect(streaming.messages).toEqual([
    { id: 'a1', role: 'assistant', text: 'היי', complete: false },
  ])
  const done = reduce(streaming, assistantMessage(5, 'a1', 'היי שם'))
  expect(done.messages).toEqual([{ id: 'a1', role: 'assistant', text: 'היי שם', complete: true }])
})

test('a retracted draft leaves the conversation', () => {
  const retracted: CheckEvent = { type: 'message.retracted', data: { message_id: 'a1' }, seq: null }
  expect(play([delta('a1', 'ההפרש'), retracted]).messages).toEqual([])
})

test('delta after complete is ignored', () => {
  const state = play([assistantMessage(1, 'a1', 'סופי'), delta('a1', 'ס')])
  expect(state.messages).toEqual([{ id: 'a1', role: 'assistant', text: 'סופי', complete: true }])
})

test('a duplicate seq is ignored', () => {
  const once = play([userMessage(1, 'שלום')])
  const twice = reduce(once, userMessage(1, 'שלום'))
  expect(twice).toBe(once)
  expect(play([userMessage(2, 'x'), userMessage(1, 'y')]).messages).toHaveLength(1)
})

test('option.saved twice for one id keeps the latest and its place', () => {
  const resaved = withSeq({ ...optionPrime36, data: { ...optionPrime36.data, lender: 'עדכון' } }, 9)
  const state = play([optionPrime36, optionFixed36, resaved])
  expect([...state.options.keys()]).toEqual(['prime-36', 'fixed-36'])
  expect(state.options.get('prime-36')?.lender).toBe('עדכון')
})

test('options saved after the recommendation are listed separately', () => {
  const state = play([optionPrime36, optionFixed36, recommendationPrime, optionOfferFixed])
  expect(state.recommendation).toBe(recommendationPrime.data)
  expect(state.optionsSinceRecommendation).toEqual(['offer-hapoalim'])
  const resaved = reduce(state, withSeq(optionPrime36, 20))
  expect(resaved.optionsSinceRecommendation).toEqual(['offer-hapoalim'])
})

test('a new recommendation clears optionsSinceRecommendation', () => {
  const state = play([
    optionPrime36,
    recommendationPrime,
    optionOfferFixed,
    withSeq(recommendationPrime, 20),
  ])
  expect(state.optionsSinceRecommendation).toEqual([])
})

test('the reply that presents a recommendation is the first one after it, in its turn', () => {
  const presented: CheckEvent[] = [
    userMessage(1, 'אפשר לראות דוגמאות?'),
    turnStatus(2, 'running'),
    withSeq(optionPrime36, 3),
    withSeq(recommendationPrime, 4),
  ]
  expect(recommendationReplyId(play(presented))).toBeNull()
  const draft: CheckEvent = {
    type: 'message.delta',
    data: { message_id: 'm1', text: 'ההמ' },
    seq: null,
  }
  expect(recommendationReplyId(play([...presented, draft]))).toBeNull()

  const replied = [...presented, assistantMessage(5, 'm1', 'ההמלצה שלי'), turnStatus(6, 'idle')]
  expect(recommendationReplyId(play(replied))).toBe('m1')
  const later = [
    ...replied,
    userMessage(7, 'מהי ריבית הפריים?'),
    turnStatus(8, 'running'),
    assistantMessage(9, 'm2', 'ריבית הפריים היא 4.75%'),
  ]
  expect(recommendationReplyId(play(later))).toBe('m1')
})

test('a recommendation whose turn ended with no reply has no presenting reply', () => {
  const state = play([
    userMessage(1, 'אפשר לראות דוגמאות?'),
    turnStatus(2, 'running'),
    withSeq(optionPrime36, 3),
    withSeq(recommendationPrime, 4),
    turnStatus(5, 'idle'),
    userMessage(6, 'מהי ריבית הפריים?'),
    assistantMessage(7, 'm2', 'ריבית הפריים היא 4.75%'),
  ])
  expect(recommendationReplyId(state)).toBeNull()
})

test('a removed recommendation has no presenting reply', () => {
  const state = play([
    withSeq(optionPrime36, 1),
    withSeq(recommendationPrime, 2),
    assistantMessage(3, 'm1', 'ההמלצה שלי'),
    examplesRemoved(4, ['prime-36'], true),
  ])
  expect(recommendationReplyId(state)).toBeNull()
})

test('a real offer removes the examples and the recommendation that named one', () => {
  const state = play([
    optionPrime36,
    optionFixed36,
    recommendationPrime,
    optionOfferFixed,
    examplesRemoved(20, ['prime-36', 'fixed-36'], true),
  ])
  expect([...state.options.keys()]).toEqual(['offer-hapoalim'])
  expect(state.recommendation).toBeNull()
  expect(state.optionsSinceRecommendation).toEqual(['offer-hapoalim'])
})

test('a new loan amount removes the options and the recommendation of another amount', () => {
  const state = play([
    optionPrime36,
    recommendationPrime,
    { ...examplesRemoved(20, ['prime-36'], true), type: 'options.removed' },
  ])
  expect([...state.options.keys()]).toEqual([])
  expect(state.recommendation).toBeNull()
})

test('a turn keeps its steps, each with the tools it chose, until a turn starts or ends', () => {
  const step = (number: number, tools: string[]): CheckEvent => ({
    type: 'turn.step',
    data: { step: number, tools },
    seq: null,
  })
  const running = play([
    turnStatus(1, 'running'),
    step(1, []),
    step(1, ['set_loan']),
    step(2, []),
  ])
  expect(running.steps).toEqual([
    { step: 1, tools: ['set_loan'] },
    { step: 2, tools: [] },
  ])
  expect(running.lastSeq).toBe(1)
  expect(reduce(running, turnStatus(2, 'idle')).steps).toEqual([])
  const timed = reduce(initialState, { ...turnStatus(1, 'running'), at: '2026-11-22T09:52:31Z' })
  expect(timed.turnStartedAt).toBe('2026-11-22T09:52:31Z')
  expect(reduce(timed, turnStatus(2, 'idle')).turnStartedAt).toBeNull()
  expect(reduce(running, turnStatus(2, 'running')).steps).toEqual([])
})

test('removing examples keeps a recommendation that names none of them', () => {
  const state = play([optionPrime36, recommendationPrime, examplesRemoved(20, ['fixed-36'], false)])
  expect(state.recommendation).toBe(recommendationPrime.data)
})

test('status follows the last turn.status; turn.failed sets failure; message.user clears it', () => {
  const running = play([userMessage(1, 'שלום'), turnStatus(2, 'running')])
  expect(running.turn).toBe('running')
  const failed = reduce(reduce(running, turnFailed(3, 'boom')), turnStatus(4, 'idle'))
  expect(failed.turn).toBe('idle')
  expect(failed.failure).toBe('boom')
  expect(reduce(failed, userMessage(5, 'שוב')).failure).toBeNull()
})

test('a turn end is counted only when a running turn goes idle', () => {
  const state = play([
    turnStatus(1, 'idle'),
    turnStatus(2, 'running'),
    turnStatus(3, 'idle'),
    turnStatus(4, 'idle'),
    turnStatus(5, 'running'),
    turnStatus(6, 'idle'),
  ])
  expect(initialState.turnsEnded).toBe(0)
  expect(state.turnsEnded).toBe(2)
})

test('a turn that goes idle drops its half-written reply, as a reload would', () => {
  const state = play([
    userMessage(1, 'חשב'),
    turnStatus(2, 'running'),
    withSeq(loanSet, 3),
    delta('a1', 'חצי תשו'),
    turnFailed(4, 'boom'),
    turnStatus(5, 'idle'),
  ])
  expect(state.messages).toEqual([{ id: 'u-1', role: 'user', text: 'חשב', complete: true }])
})

test('a question becomes an entry and is live once the turn is idle', () => {
  const state = play([
    userMessage(1, 'מכונית'),
    turnStatus(2, 'running'),
    questionAsked(3, { field: 'net_fixed_income', text: null, choices: null }, 'קודם ההכנסה'),
    turnStatus(4, 'idle'),
  ])
  expect(state.messages.at(-1)).toMatchObject({ id: 'q-3', role: 'question', answered: false })
  expect(liveQuestion(state)?.id).toBe('q-3')
})

test('status and finances events after a question do not close it; a user message does', () => {
  const asked = questionAsked(3, { field: 'amount', text: null, choices: null })
  const open = play([
    userMessage(1, 'x'),
    turnStatus(2, 'running'),
    asked,
    withSeq(financesUpdated, 4),
    turnStatus(5, 'idle'),
  ])
  expect(liveQuestion(open)?.id).toBe('q-3')
  const closed = reduce(open, userMessage(6, 'כמה צריך ללוות? 12,000 ₪'))
  expect(closed.messages.find((m) => m.id === 'q-3')).toMatchObject({ answered: true })
  expect(liveQuestion(closed)).toBeNull()
})

test('a chart becomes an entry where it was shown and survives its turn ending', () => {
  const state = play([
    userMessage(1, 'מה המדד?'),
    turnStatus(2, 'running'),
    chartShown(3),
    delta('a1', 'הנה'),
    turnStatus(4, 'idle'),
  ])
  expect(state.messages).toEqual([
    { id: 'u-1', role: 'user', text: 'מה המדד?', complete: true },
    { id: 'c-3', role: 'chart', chart: cpiChart },
  ])
})

test('a scenario table becomes an entry where it was shown', () => {
  const state = play([userMessage(1, 'ואם המדד יעלה 5%?'), scenarioShown(2)])
  expect(state.messages.at(-1)).toEqual({ id: 's-2', role: 'scenario', scenario: scenarioCpi5 })
})

test('a question is not live while a turn runs', () => {
  const state = play([
    userMessage(1, 'x'),
    turnStatus(2, 'running'),
    questionAsked(3, { field: null, text: 'מה המטרה?', choices: ['רכב', 'דירה'] }),
    turnStatus(4, 'running'),
  ])
  expect(liveQuestion(state)).toBeNull()
})


test('the loan, term and ceiling events set the check\'s figures', () => {
  const state = play([
    userMessage(1, 'רכב ב-29,000'),
    turnStatus(2, 'running'),
    withSeq(loanSet, 3),
    withSeq(termSet, 4),
    withSeq(ceilingSet, 5),
    turnStatus(6, 'idle'),
  ])
  expect(state.loan).toBe(loan)
  expect(state.termMonths).toBe(36)
  expect(state.ceiling).toEqual({ amount: '1900', source: 'stated', basis: null })
})

test('a finances save that derives the ceiling keeps the caps behind it', () => {
  const basis = {
    income_percent: '30.00',
    ceiling_by_income_share: '3000.00',
    disposable_percent: '50.00',
    ceiling_by_disposable_income: '1900.00',
  }
  const derived = { ...financesUpdated, data: { ...financesUpdated.data, ceiling_basis: basis } }
  const state = play([withSeq(derived, 1)])
  expect(state.ceiling).toEqual({ amount: '1900', source: 'finances', basis })
})

test('a finances save sets the figures and the ceiling that follows from them', () => {
  const state = play([withSeq(financesUpdated, 1)])
  expect(state.finances).toBe(finances)
  expect(state.ceiling).toEqual({ amount: '1900', source: 'finances', basis: null })
})

test('an archive closes the conversation with its note', () => {
  const archived = checkArchived(2)
  const state = play([userMessage(1, 'טעיתי'), archived])
  expect(state.messages.at(-1)).toEqual({ id: 'x-2', role: 'archived', archive: archived.data })
  expect(isArchived(state)).toBe(true)
  expect(isArchived(play([userMessage(1, 'שלום')]))).toBe(false)
})

test('a restore reopens the conversation and drops the closing note', () => {
  const state = play([
    userMessage(1, 'שלום'),
    checkArchived(2),
    { type: 'check.restored', data: {}, seq: 3 },
  ])
  expect(isArchived(state)).toBe(false)
  expect(state.messages).toHaveLength(1)
})

test('a clone hands the conversation over with a note naming the copy, which closes a question', () => {
  const state = play([
    questionAsked(1, { field: null, text: null, choices: null, offer_clone: true }),
    { type: 'check.cloned', data: { clone_id: 'copy' }, seq: 2 },
  ])
  expect(state.messages.at(-1)).toEqual({ id: 'c-2', role: 'cloned', cloneId: 'copy' })
  expect(liveQuestion(state)).toBeNull()
})

test('messages and questions keep the time of their stored event; a streaming reply has none', () => {
  const at = '2026-11-14T09:30:05+00:00'
  const state = play([
    { ...userMessage(1, 'שלום'), at },
    { ...assistantMessage(2, 'a1', 'היי'), at },
    { ...questionAsked(3, { field: 'amount', text: null, choices: null }), at },
    delta('a2', 'ע'),
  ])
  expect(state.messages.map((entry) => ('at' in entry ? entry.at : 'none'))).toEqual([
    at,
    at,
    at,
    undefined,
  ])
})

test('an awaiting offer becomes a card entry and is counted as awaiting', () => {
  const at = '2026-11-16T09:30:05+00:00'
  const state = play([userMessage(1, '969 שח קבוע'), { ...offerAwaiting(2, awaitingAvis), at }])
  expect(state.messages.at(-1)).toEqual({
    id: 'r-a-1',
    role: 'readings',
    offer: awaitingAvis,
    settled: null,
    dropped: null,
    at,
  })
  expect([...state.awaiting.values()]).toEqual([awaitingAvis])
})

test('the same offer emitted again replaces its card where it stands', () => {
  const likely = { ...awaitingAvis, likely: 'fixed_unlinked' as const }
  const state = play([
    offerAwaiting(1, awaitingAvis),
    userMessage(2, 'וגם 60 חודשים'),
    offerAwaiting(3, likely),
  ])
  expect(state.messages.map((entry) => entry.id)).toEqual(['r-a-1', 'u-2'])
  expect(state.messages[0]).toMatchObject({ role: 'readings', offer: { likely: 'fixed_unlinked' } })
  expect([...state.awaiting.values()]).toEqual([likely])
})

test('a settled offer marks its card and leaves the awaiting offers', () => {
  const other = { ...awaitingAvis, awaiting_id: 'a-2' }
  const state = play([
    offerAwaiting(1, awaitingAvis),
    offerAwaiting(2, other),
    offerSettled(3, 'a-1', avisReading('prime_margin')),
  ])
  expect(state.messages[0]).toMatchObject({ id: 'r-a-1', settled: avisReading('prime_margin') })
  expect(state.messages[1]).toMatchObject({ id: 'r-a-2', settled: null })
  expect([...state.awaiting.keys()]).toEqual(['a-2'])
})

test('a dropped offer marks its card and leaves the awaiting offers', () => {
  const state = play([
    offerAwaiting(1, awaitingMaxShort),
    offerDropped(2, awaitingMaxShort, '45000'),
  ])
  expect(state.messages[0]).toMatchObject({
    id: 'r-a-max',
    settled: null,
    dropped: { lender: 'מקס', quoted_amount: '20000', loan_amount: '45000' },
  })
  expect(state.awaiting.size).toBe(0)
})

test('an offer dropped with no card is a broken stream', () => {
  expect(() => play([offerDropped(1, awaitingMaxShort, '45000')])).toThrow(
    'offer.dropped for a-max, which no offer.awaiting showed',
  )
})

test('an offer quoted for less than the loan awaits the amount', () => {
  expect(quotedBelowLoan(awaitingMaxShort, '45000')).toBe(true)
  expect(quotedBelowLoan(awaitingMaxShort, '20000')).toBe(false)
  expect(quotedBelowLoan(awaitingMaxShort, '15000')).toBe(false)
})

test('identified and unrecognized offers are entries of their own', () => {
  const state = play([offerIdentified(1, identifiedMax), offerUnrecognized(2, 'מקס')])
  expect(state.messages).toEqual([
    { id: 'i-1', role: 'identified', offer: identifiedMax },
    { id: 'n-2', role: 'unrecognized', lender: 'מקס' },
  ])
  expect(state.awaiting.size).toBe(0)
})

test('a message after a card leaves it unanswered and unsettled', () => {
  const state = play([
    questionAsked(1, { field: 'amount', text: null, choices: null }),
    offerAwaiting(2, awaitingAvis),
    userMessage(3, 'עוד הצעה'),
  ])
  expect(state.messages[1]).toMatchObject({ role: 'readings', settled: null })
  expect(state.awaiting.has('a-1')).toBe(true)
})

test('holdsOption is true for an example, a saved offer or an awaiting one', () => {
  expect(holdsOption(play([]))).toBe(false)
  expect(holdsOption(play([optionPrime36]))).toBe(true)
  expect(holdsOption(play([optionOfferFixed]))).toBe(true)
  expect(holdsOption(play([offerAwaiting(9, awaitingAvis)]))).toBe(true)
})

/** A recommendation of the offer, as presented with its data. */
function recommending(offer: typeof optionOfferFixed): CheckEvent {
  return {
    ...withSeq(recommendationPrime, 20),
    data: { ...recommendationPrime.data, preferred: offer.data },
  }
}

test('the terms chips wait for a recommendation and follow its option', () => {
  expect(termComparisons(play([optionPrime36]))).toEqual({ shorter: false, longer: false })
  expect(termComparisons(play([optionPrime36, recommendationPrime]))).toEqual({
    shorter: true,
    longer: true,
  })
})

test('an offer whose lender fixed its term offers no terms chip', () => {
  const state = play([optionOfferFixed, recommending(optionOfferFixed)])
  expect(termComparisons(state)).toEqual({ shorter: false, longer: false })
})

test('an offer at the longest term its lender allows offers only the shorter chip', () => {
  const open = { ...optionOfferFixed, data: { ...optionOfferFixed.data, max_term_months: 36 } }
  expect(termComparisons(play([open, recommending(open)]))).toEqual({
    shorter: true,
    longer: false,
  })
})
