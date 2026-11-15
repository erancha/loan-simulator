import { expect, test } from 'vitest'
import {
  assistantMessage,
  checkArchived,
  chartShown,
  cpiChart,
  delta,
  ceilingSet,
  finances,
  financesUpdated,
  loan,
  loanSet,
  optionFixed36,
  optionOfferFixed,
  optionPrime36,
  questionAsked,
  recommendationPrime,
  turnFailed,
  termSet,
  turnStatus,
  userMessage,
  withSeq,
} from '../test/fixtures.ts'
import type { CheckEvent } from '../api/types.ts'
import { initialState, isArchived, liveQuestion, reduce } from './events.ts'

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
  expect(state.ceiling).toEqual({ amount: '1900', source: 'stated' })
})

test('a finances save sets the figures and the ceiling that follows from them', () => {
  const state = play([withSeq(financesUpdated, 1)])
  expect(state.finances).toBe(finances)
  expect(state.ceiling).toEqual({ amount: '1900', source: 'finances' })
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
