import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { App } from '../App.tsx'
import {
  assistantMessage,
  goalSet,
  questionAsked,
  optionFixed36,
  optionPrime36,
  profileUpdated,
  recommendationPrime,
  REFERENCE_DECISION,
  turnStatus,
  userMessage,
  withSeq,
} from '../test/fixtures.ts'
import { createDemoBackend } from './backend.ts'
import type { Entry, Recording } from './backend.ts'

const REPLY = 'הנה ההמלצה: פריים ל-36 חודשים.'
const PACE = { pauseMs: 0, typingMs: 0, typedChars: 8, entryMs: 0 }
const noEntry = () => () => {}

const recording: Recording = {
  events: [
    userMessage(1, 'אני רוצה לקנות רכב ב-55,000 ₪'),
    turnStatus(2, 'running'),
    withSeq(profileUpdated, 3),
    withSeq(goalSet, 4),
    withSeq(optionPrime36, 5),
    withSeq(optionFixed36, 6),
    withSeq(recommendationPrime, 7),
    assistantMessage(8, 'm1', REPLY),
    turnStatus(9, 'idle'),
  ],
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

test('the demo signs in and replays the recorded check into the page', async () => {
  installDemo()
  render(<App />)

  // The chat also announces the reply in a hidden live region; the bubble is the one shown. The
  // replay draws the card on the way, which takes jsdom over a second.
  const shown = { ignore: '.visually-hidden, script, style' }
  expect(await screen.findByText(REPLY, shown, { timeout: 3000 })).toBeInTheDocument()
  expect(screen.getByText('אני רוצה לקנות רכב ב-55,000 ₪', shown)).toBeInTheDocument()
  expect(screen.getByText(REFERENCE_DECISION)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'תפריט חשבון' })).toBeInTheDocument()
})

test('the demo serves the profile as the replay has filled it so far', async () => {
  const backend = createDemoBackend(
    { events: recording.events.slice(0, 1) },
    PACE,
    noEntry,
  )
  const empty = await (await backend.fetch('/api/profile')).json()
  expect(empty.missing).toEqual([
    'savings',
    'net_fixed_income',
    'variable_income',
    'variable_income_minimum',
    'fixed_expenses',
    'existing_loan_payments',
  ])

  const filled = createDemoBackend(recording, PACE, noEntry)
  await vi.waitFor(async () =>
    expect(await (await filled.fetch('/api/profile')).json()).toEqual(profileUpdated.data),
  )
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
    questionAsked(4, { field: 'existing_loan_payments', text: null, choices: null }),
    userMessage(5, 'דילוג על: החזרי הלוואות (נשמר כ-0)'),
    questionAsked(6, { field: null, text: 'לאיזו תקופה?', choices: ['36 חודשים', 'אחר'] }),
    userMessage(7, 'לאיזו תקופה? 36 חודשים'),
    questionAsked(8, { field: null, text: 'מה עוד חשוב?', choices: null }),
    userMessage(9, 'מה עוד חשוב? החזר נמוך'),
  ]
  createDemoBackend({ events }, PACE, (entry) => {
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
