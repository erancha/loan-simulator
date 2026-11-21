import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { App } from '../App.tsx'
import {
  assistantMessage,
  awaitingAvis,
  loanSet,
  offerAwaiting,
  avisReading,
  offerSettled,
  questionAsked,
  optionFixed36,
  optionOfferFixed,
  optionPrime36,
  recommendationPrime,
  REFERENCE_DECISION,
  termSet,
  turnStatus,
  userMessage,
  withSeq,
} from '../test/fixtures.ts'
import { createDemoBackend, DEMO_UNAVAILABLE_EVENT } from './backend.ts'
import type { Entry, Recording } from './backend.ts'
import { wholeText } from '../test/wholeText.ts'

const REPLY = 'הנה ההמלצה: מסלול הפריים.'
const PACE = { pauseMs: 0, quietMs: 0, typingMs: 0, typedChars: 8, entryMs: 0 }
const noEntry = () => () => {}

const recording: Recording = {
  events: [
    userMessage(1, 'אני רוצה לקנות רכב ב-55,000 ₪'),
    turnStatus(2, 'running'),
    withSeq(loanSet, 3),
    withSeq(termSet, 4),
    withSeq(optionPrime36, 5),
    withSeq(optionFixed36, 6),
    withSeq(recommendationPrime, 7),
    assistantMessage(8, 'm1', REPLY),
    turnStatus(9, 'idle'),
  ],
  source: null,
}

/** Installs the demo backend with no pauses, the way demo/main.tsx installs it with its pace. */
function installDemo() {
  const backend = createDemoBackend(recording, PACE, noEntry)
  vi.stubGlobal('fetch', backend.fetch)
  vi.stubGlobal('EventSource', backend.EventSource)
}

afterEach(() => {
  vi.unstubAllGlobals()
  history.replaceState(null, '', '/')
})

test('the demo signs in and replays the recorded check into the page, which asks for no action', async () => {
  installDemo()
  const unavailable = vi.fn()
  window.addEventListener(DEMO_UNAVAILABLE_EVENT, unavailable)
  render(<App />)

  // The chat also announces the reply in a hidden live region; the bubble is the one shown. The
  // replay draws the card on the way, which takes jsdom over a second.
  const shown = { ignore: '.visually-hidden, script, style' }
  expect(await screen.findByText(REPLY, shown, { timeout: 3000 })).toBeInTheDocument()
  expect(screen.getByText('אני רוצה לקנות רכב ב-55,000 ₪', shown)).toBeInTheDocument()
  expect(screen.getByText(wholeText(REFERENCE_DECISION))).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'תפריט חשבון' })).toBeInTheDocument()
  window.removeEventListener(DEMO_UNAVAILABLE_EVENT, unavailable)
  expect(unavailable).not.toHaveBeenCalled()
})

test('the demo lists the check with the loan and term the replay has set so far', async () => {
  const backend = createDemoBackend({ events: recording.events.slice(0, 1), source: null }, PACE, noEntry)
  const [empty] = await (await backend.fetch('/api/checks')).json()
  expect(empty).toMatchObject({
    id: 'demo',
    loan: null,
    term_months: null,
    recommendation: null,
    compares_options: false,
    archived: false,
  })

  const played = createDemoBackend(recording, PACE, noEntry)
  await vi.waitFor(async () => {
    const [summary] = await (await played.fetch('/api/checks')).json()
    expect(summary).toMatchObject({
      loan: { purpose: 'רכב', amount: '29000' },
      term_months: 36,
      recommendation: {
        preferred_option_id: 'prime-36',
        loan_amount: '29000.00',
        payment_ceiling: '1900.00',
        checked: true,
      },
      compares_options: true,
    })
  })
})

test('the demo lists a recommendation of one offer alone as not comparing options', async () => {
  const only = withSeq(
    {
      ...recommendationPrime,
      data: { ...recommendationPrime.data, preferred: optionOfferFixed.data, alternative: null },
    },
    8,
  )
  const events = [...recording.events.slice(0, 4), withSeq(optionOfferFixed, 7), only]
  const backend = createDemoBackend({ events, source: null }, PACE, noEntry)
  await vi.waitFor(async () => {
    const [summary] = await (await backend.fetch('/api/checks')).json()
    expect(summary.recommendation).not.toBeNull()
    expect(summary.compares_options).toBe(false)
  })
})

test('the demo accepts the offer chip, which a visitor may tap', async () => {
  const backend = createDemoBackend(recording, PACE, noEntry)
  const response = await backend.fetch('/api/checks/demo/offer-sample', { method: 'POST' })
  expect(response.status).toBe(202)
})

test('the demo answers the opening, term confirmation, skip and reading routes', async () => {
  const backend = createDemoBackend(recording, PACE, noEntry)
  for (const route of ['opening', 'term-confirmation', 'offer-skip']) {
    const response = await backend.fetch(`/api/checks/demo/${route}`, { method: 'POST' })
    expect(response.status).toBe(202)
  }
  const reading = await backend.fetch('/api/checks/demo/awaiting-offers/a-1', { method: 'PUT' })
  expect(reading.status).toBe(204)
})

test('the demo lists the offers still awaiting their lender, each in its first place', async () => {
  const unpaid = { ...awaitingAvis, monthly_payment: null }
  const direct = { ...unpaid, awaiting_id: 'a-2', lender: 'מימון ישיר' }
  const bank = { ...unpaid, awaiting_id: 'a-3', lender: 'בנק' }
  const events = [
    userMessage(1, '969 שח קבוע'),
    offerAwaiting(2, awaitingAvis),
    offerAwaiting(3, direct),
    offerAwaiting(4, awaitingAvis),
    offerAwaiting(5, bank),
    offerSettled(6, 'a-2', avisReading('fixed_unlinked')),
  ]
  const backend = createDemoBackend({ events, source: null }, PACE, noEntry)
  await vi.waitFor(async () => {
    const [summary] = await (await backend.fetch('/api/checks')).json()
    expect(summary.awaiting_offers).toEqual([
      { id: 'a-1', lender: 'סוכנות אוויס רכבים', monthly_payment: '969' },
      { id: 'a-3', lender: 'בנק', monthly_payment: null },
    ])
  })
})

test('the demo reports the end of its replay once every recorded event was played', async () => {
  const backend = createDemoBackend(recording, PACE, noEntry)
  await backend.finished
  const [summary] = await (await backend.fetch('/api/checks')).json()
  expect(summary.recommendation).toMatchObject({ preferred_option_id: 'prime-36' })
})

/** Counts the times the demo says an action is unavailable while the given calls run. */
async function unavailableCount(run: () => Promise<void>): Promise<number> {
  const heard = vi.fn()
  window.addEventListener(DEMO_UNAVAILABLE_EVENT, heard)
  try {
    await run()
  } finally {
    window.removeEventListener(DEMO_UNAVAILABLE_EVENT, heard)
  }
  return heard.mock.calls.length
}

test('an action the demo has no answer for says so and never settles, so the page shows no failure', async () => {
  const backend = createDemoBackend(recording, PACE, noEntry)
  const settled = vi.fn()
  const count = await unavailableCount(async () => {
    void backend.fetch('/api/checks', { method: 'POST' }).then(settled, settled)
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
  expect(count).toBe(1)
  expect(settled).not.toHaveBeenCalled()
})

test('an action the demo accepts says it is unavailable too; reading the page says nothing', async () => {
  const backend = createDemoBackend(recording, PACE, noEntry)
  const sent = await unavailableCount(async () => {
    await backend.fetch('/api/checks/demo/messages', { method: 'POST' })
    await backend.fetch('/api/checks/demo/awaiting-offers/a-1', { method: 'PUT' })
  })
  expect(sent).toBe(2)
  const read = await unavailableCount(async () => {
    await backend.fetch('/api/checks')
    await backend.fetch('/api/auth/me')
  })
  expect(read).toBe(0)
})

test('the demo refuses a profile request, which the page never makes', async () => {
  const backend = createDemoBackend(recording, PACE, noEntry)
  await expect(backend.fetch('/api/profile')).rejects.toThrow('GET /api/profile')
})

test('the demo refuses a request the page is not known to make', async () => {
  const backend = createDemoBackend(recording, PACE, noEntry)
  await expect(backend.fetch('/api/unknown')).rejects.toThrow('GET /api/unknown')
})

test('the demo shows what the person typed before each message, nothing for a tap', async () => {
  const shown: Array<Entry | 'cleared'> = []
  const events = [
    userMessage(1, 'אני רוצה לקנות רכב'),
    questionAsked(2, { field: 'net_fixed_income', text: null, choices: null }),
    userMessage(3, 'הכנסה קבועה: 8,300 ₪'),
    questionAsked(4, { field: 'payment_ceiling', text: null, choices: null }),
    userMessage(5, 'דילוג על: מה ההחזר החודשי הגבוה ביותר שנוח לך?'),
    questionAsked(6, { field: null, text: 'לאיזו תקופה?', choices: ['36 חודשים', 'אחר'] }),
    userMessage(7, 'לאיזו תקופה? 36 חודשים'),
    questionAsked(8, { field: null, text: 'מה עוד חשוב?', choices: null }),
    userMessage(9, 'מה עוד חשוב? החזר נמוך'),
  ]
  createDemoBackend({ events, source: null }, PACE, (entry) => {
    shown.push(entry)
    return () => shown.push('cleared')
  })

  await vi.waitFor(() => expect(shown).toHaveLength(6))
  expect(shown).toEqual([
    { box: 'הודעה לעוזר', value: 'אני רוצה לקנות רכב' },
    'cleared',
    { box: 'הכנסה קבועה', value: '8,300' },
    'cleared',
    { box: 'מה עוד חשוב?', value: 'החזר נמוך' },
    'cleared',
  ])
})

test('a recorded clone lists its source once the replay passes the clone, with its whole history', async () => {
  const clone: Recording = {
    events: [
      ...recording.events,
      userMessage(10, 'לשכפל ולבדוק בנפרד: ננסה עם 48 חודשים'),
      withSeq({ ...termSet, data: { term_months: 48 } }, 11),
    ],
    source: { sharedThroughSeq: 9 },
  }
  const sharedOnly = createDemoBackend({ ...clone, events: recording.events }, PACE, noEntry)
  await vi.waitFor(async () => {
    const listed = await (await sharedOnly.fetch('/api/checks')).json()
    expect(listed.map((check: { id: string }) => check.id)).toEqual(['demo'])
    expect(listed[0].recommendation).not.toBeNull()
  })

  const backend = createDemoBackend(clone, PACE, noEntry)
  await vi.waitFor(async () => {
    const listed = await (await backend.fetch('/api/checks')).json()
    expect(listed.map((check: { id: string; term_months: number }) => [check.id, check.term_months]))
      .toEqual([
        ['demo', 48],
        ['demo-source', 36],
      ])
  })
  const stream = new backend.EventSource('/api/checks/demo-source/events')
  const types: string[] = []
  for (const type of ['message.user', 'check.cloned']) {
    stream.addEventListener(type, (frame) => types.push(`${frame.type}:${frame.lastEventId}`))
  }
  await vi.waitFor(() => expect(types).toEqual(['message.user:1', 'check.cloned:10']))
})

test('a recorded clone whose source ends at an event it lacks is refused', () => {
  expect(() =>
    createDemoBackend({ events: recording.events, source: { sharedThroughSeq: 12 } }, PACE, noEntry),
  ).toThrow('no event 12')
})

test("the replay's total is its length at 1×, and at 2× it plays in half that", async () => {
  vi.useFakeTimers()
  try {
    const paced = { pauseMs: 1000, quietMs: 1000, typingMs: 100, typedChars: 8, entryMs: 500 }
    const atOne = createDemoBackend(recording, paced, noEntry)
    let started = Date.now()
    await vi.runAllTimersAsync()
    await atOne.finished
    expect(Date.now() - started).toBe(atOne.totalMs)

    const atTwo = createDemoBackend(recording, paced, noEntry)
    atTwo.clock.setRate(2)
    started = Date.now()
    await vi.runAllTimersAsync()
    await atTwo.finished
    expect(Date.now() - started).toBe(atTwo.totalMs / 2)
    expect(atTwo.clock.elapsed()).toBe(atTwo.totalMs)
  } finally {
    vi.useRealTimers()
  }
})

test('an event the conversation does not show waits only the short pause', () => {
  const events = [
    userMessage(1, 'אני רוצה לקנות רכב ב-55,000 ₪'),
    turnStatus(2, 'running'),
    withSeq(optionPrime36, 3),
    assistantMessage(4, 'm1', 'קצר'),
    turnStatus(5, 'idle'),
  ]
  const paced = { pauseMs: 1000, quietMs: 100, typingMs: 0, typedChars: 100, entryMs: 0 }
  const backend = createDemoBackend({ events, source: null }, paced, noEntry)

  // The two messages wait the full pause; the turn's two statuses and the saved option, which
  // only the thinking bubble and the card show, wait the short one.
  expect(backend.totalMs).toBe(2 * 1000 + 3 * 100)
})
