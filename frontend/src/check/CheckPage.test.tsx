import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { CheckEvent, ProfileView } from '../api/types.ts'
import { FakeEventSource } from '../test/fakeEventSource.ts'
import {
  assistantMessage,
  checkArchived,
  checkContinued,
  delta,
  goalSet,
  optionFixed36,
  optionPrime36,
  profileUpdated,
  profileView,
  questionAsked,
  recommendationPrime,
  REFERENCE_DECISION,
  turnStatus,
  userMessage,
  withSeq,
} from '../test/fixtures.ts'
import { CheckPage } from './CheckPage.tsx'

const MESSAGES = '/api/checks/c1/messages'
const RECOMPUTE = 'הפרופיל שלי השתנה. אפשר לחשב מחדש את ההמלצה לפי המספרים המעודכנים?'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status })
}

/** Stubs fetch: a profile GET or PUT answers the reference profile; a message POST `onMessage`. */
function stubApi(
  onMessage: () => Response | Promise<Response> = () => new Response(null, { status: 202 }),
) {
  const fetchStub = vi.fn((path: string, init?: RequestInit) => {
    if (path === '/api/profile') return Promise.resolve(jsonResponse(200, profileView))
    if (path === MESSAGES && init?.method === 'POST') return Promise.resolve(onMessage())
    return Promise.reject(new Error(`unexpected request ${init?.method ?? 'GET'} ${path}`))
  })
  vi.stubGlobal('fetch', fetchStub)
  return fetchStub
}

function sentTexts(fetchStub: ReturnType<typeof stubApi>): string[] {
  return fetchStub.mock.calls
    .filter(([path]) => path === MESSAGES)
    .map(([, init]) => (JSON.parse(String(init?.body)) as { text: string }).text)
}

/** The bodies of the profile PUTs, in order. */
function profilePuts(fetchStub: ReturnType<typeof stubApi>): unknown[] {
  return fetchStub.mock.calls
    .filter(([path, init]) => path === '/api/profile' && init?.method === 'PUT')
    .map(([, init]) => JSON.parse(String(init?.body)))
}

function emit(...events: CheckEvent[]) {
  const source = FakeEventSource.last()
  act(() => {
    for (const event of events) {
      const id = event.seq === null ? '' : String(event.seq)
      source.emit(event.type, JSON.stringify(event.data), id)
    }
  })
}

function renderPage(
  stale = false,
  onChecksChanged = vi.fn(),
  onClone = vi.fn(() => Promise.resolve()),
  onOpenCheck = vi.fn(),
) {
  render(
    <CheckPage
      checkId="c1"
      stale={stale}
      sidebar={<nav>הבדיקות שלי</nav>}
      activePane="chat"
      onChecksChanged={onChecksChanged}
      onClone={onClone}
      onOpenCheck={onOpenCheck}
    />,
  )
  return { onChecksChanged, onClone, onOpenCheck }
}

beforeEach(() => {
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
})
afterEach(() => vi.unstubAllGlobals())

test('replaying the reference events fills the three panes', async () => {
  stubApi()
  renderPage()
  expect(FakeEventSource.last().url).toBe('/api/checks/c1/events')
  emit(
    userMessage(1, 'רוצה לקנות רכב'),
    profileUpdated,
    goalSet,
    optionPrime36,
    optionFixed36,
    recommendationPrime,
    assistantMessage(7, 'a1', 'הנה ההמלצה'),
    turnStatus(8, 'idle'),
  )

  const page = document.querySelector('.check-page')!
  expect(page).toHaveAttribute('data-active-pane', 'chat')
  expect(page.querySelector('.pane-side')).toHaveTextContent('הבדיקות שלי')
  expect(await screen.findByLabelText('כסף זמין')).toHaveValue('15,000')
  expect(page.querySelector('.pane-chat')).toHaveTextContent('הנה ההמלצה')
  expect(screen.getByText(REFERENCE_DECISION)).toBeInTheDocument()
  expect(screen.getByText('מומלצת')).toBeInTheDocument()
})

test('sending posts the text to the check and clears the input', async () => {
  const fetchStub = stubApi()
  renderPage()
  const input = screen.getByRole('textbox')
  await userEvent.type(input, 'שלום{Enter}')

  await waitFor(() => expect(input).toHaveValue(''))
  expect(sentTexts(fetchStub)).toEqual(['שלום'])
})

test('a 429 shows when sending resumes and keeps the text', async () => {
  const today = new Date()
  const nextAllowed = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate() + 1,
    7,
    5,
  ).toISOString()
  stubApi(() =>
    jsonResponse(429, { detail: 'daily message cap reached', next_allowed: nextAllowed }),
  )
  renderPage()
  const input = screen.getByRole('textbox')
  await userEvent.type(input, 'שלום{Enter}')

  expect(
    await screen.findByText('הגעתם למכסת ההודעות. אפשר להמשיך מחר ב-07:05'),
  ).toBeInTheDocument()
  expect(input).toHaveValue('שלום')
})

test('another failure names it and keeps the text', async () => {
  stubApi(() => jsonResponse(500, { detail: 'boom' }))
  renderPage()
  const input = screen.getByRole('textbox')
  await userEvent.type(input, 'שלום{Enter}')

  expect(await screen.findByText('ההודעה לא נשלחה: boom')).toBeInTheDocument()
  expect(input).toHaveValue('שלום')
})

test('a 409 shows nothing', async () => {
  stubApi(() => jsonResponse(409, { detail: 'a turn is running', check_id: 'c1' }))
  renderPage()
  const input = screen.getByRole('textbox')
  await userEvent.type(input, 'שלום{Enter}')

  await waitFor(() => expect(input).toBeEnabled())
  expect(input).toHaveValue('שלום')
  expect(screen.queryByText(/ההודעה לא נשלחה/)).not.toBeInTheDocument()
})

test('the stale banner recomputes with the fixed message', async () => {
  const fetchStub = stubApi()
  renderPage(true)
  expect(screen.getByText('ההמלצה חושבה לפי פרופיל קודם.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'לחשב מחדש' }))

  await waitFor(() => expect(sentTexts(fetchStub)).toEqual([RECOMPUTE]))
})

test('the recompute button waits for its send and shows why it was refused', async () => {
  let refuse: (response: Response) => void = () => undefined
  stubApi(() => new Promise<Response>((resolve) => (refuse = resolve)))
  renderPage(true)
  const button = screen.getByRole('button', { name: 'לחשב מחדש' })
  await userEvent.click(button)
  expect(button).toBeDisabled()

  await act(async () => refuse(jsonResponse(500, { detail: 'boom' })))
  expect(button).toBeEnabled()
  const banner = screen.getByText('ההמלצה חושבה לפי פרופיל קודם.').closest('.stale-banner')!
  expect(banner).toHaveTextContent('ההודעה לא נשלחה: boom')
})

test('no stale banner on a current check', () => {
  stubApi()
  renderPage(false)
  expect(screen.queryByText('ההמלצה חושבה לפי פרופיל קודם.')).not.toBeInTheDocument()
})

test('replayed turns do not change the checks', async () => {
  stubApi()
  const { onChecksChanged } = renderPage()
  await screen.findByLabelText('כסף זמין')
  emit(
    turnStatus(1, 'running'),
    turnStatus(2, 'idle'),
    turnStatus(3, 'running'),
    turnStatus(4, 'idle'),
  )
  expect(onChecksChanged).not.toHaveBeenCalled()
})

async function sendHello() {
  const input = screen.getByRole('textbox', { name: 'הודעה לעוזר' })
  await userEvent.type(input, 'שלום{Enter}')
  await waitFor(() => expect(input).toHaveValue(''))
}

test('the checks change once when the turn a send started ends', async () => {
  stubApi()
  const { onChecksChanged } = renderPage()
  await screen.findByLabelText('כסף זמין')
  await sendHello()
  emit(userMessage(1, 'שלום'), turnStatus(2, 'running'))
  expect(onChecksChanged).not.toHaveBeenCalled()
  emit(turnStatus(3, 'idle'))
  expect(onChecksChanged).toHaveBeenCalledTimes(1)
  emit(turnStatus(4, 'running'), turnStatus(5, 'idle'))
  expect(onChecksChanged).toHaveBeenCalledTimes(1)
})

test('a turn that runs and ends in one batch after a send still counts', async () => {
  stubApi()
  const { onChecksChanged } = renderPage()
  await screen.findByLabelText('כסף זמין')
  await sendHello()
  emit(userMessage(1, 'שלום'), turnStatus(2, 'running'), turnStatus(3, 'idle'))
  expect(onChecksChanged).toHaveBeenCalledTimes(1)
})

test('a profile save changes the checks', async () => {
  stubApi()
  const { onChecksChanged } = renderPage()
  const savings = await screen.findByLabelText('כסף זמין')
  await userEvent.clear(savings)
  await userEvent.type(savings, '20000')
  await userEvent.tab()
  await waitFor(() => expect(onChecksChanged).toHaveBeenCalledTimes(1))
})

function withSavings(savings: string): ProfileView {
  return { ...profileView, profile: { ...profileView.profile, savings } }
}

/** Stubs fetch: each profile GET answers the next of `answers`, the last one repeating. */
function stubProfileGets(...answers: ProfileView[]) {
  const fetchStub = vi.fn((path: string) => {
    if (path !== '/api/profile') return Promise.reject(new Error(`unexpected request ${path}`))
    const gets = fetchStub.mock.calls.filter(([called]) => called === '/api/profile').length
    return Promise.resolve(jsonResponse(200, answers[Math.min(gets, answers.length) - 1]))
  })
  vi.stubGlobal('fetch', fetchStub)
  return fetchStub
}

function profileGets(fetchStub: ReturnType<typeof stubProfileGets>): number {
  return fetchStub.mock.calls.filter(([path]) => path === '/api/profile').length
}

test('a replayed older profile never replaces the current one the panel fetched', async () => {
  stubProfileGets(withSavings('20000'))
  renderPage()
  const savings = await screen.findByLabelText('כסף זמין')
  emit({ ...profileUpdated, data: withSavings('1') })
  await new Promise((resolve) => setTimeout(resolve, 20))
  expect(savings).toHaveValue('20,000')
})

test('replaying several profile updates on open fetches the profile once', async () => {
  const fetchStub = stubProfileGets(profileView)
  renderPage()
  emit(
    withSeq(profileUpdated, 1),
    withSeq(profileUpdated, 2),
    withSeq(profileUpdated, 3),
  )
  await screen.findByLabelText('כסף זמין')
  await new Promise((resolve) => setTimeout(resolve, 20))
  expect(profileGets(fetchStub)).toBe(1)
})

test('a live profile update after the panel loaded fetches the profile again', async () => {
  const fetchStub = stubProfileGets(profileView, withSavings('20000'))
  renderPage()
  const savings = await screen.findByLabelText('כסף זמין')
  expect(savings).toHaveValue('15,000')
  emit({ ...profileUpdated, data: withSavings('1') })
  await waitFor(() => expect(savings).toHaveValue('20,000'))
  expect(profileGets(fetchStub)).toBe(2)
})

test('a card that cannot be built shows a notice; the chat and profile keep working', async () => {
  const logged = vi.spyOn(console, 'error').mockImplementation(() => {})
  const fetchStub = stubApi()
  renderPage()
  const [track] = optionFixed36.data.loan.tracks
  const broken = {
    ...optionFixed36,
    data: { ...optionFixed36.data, loan: { tracks: [{ ...track, annual_rate: null }] } },
  }
  emit(broken)

  expect(screen.getByText('לא הצלחנו להציג את ההמלצה.')).toBeInTheDocument()
  expect(logged).toHaveBeenCalledWith(
    'the recommendation card failed',
    expect.any(Error),
    expect.anything(),
  )
  expect(await screen.findByLabelText('כסף זמין')).toHaveValue('15,000')
  await userEvent.type(screen.getByLabelText('הודעה לעוזר'), 'שלום{Enter}')
  await waitFor(() => expect(sentTexts(fetchStub)).toEqual(['שלום']))
  logged.mockRestore()
})

const SAVINGS_QUESTION = questionAsked(3, { field: 'savings', text: null, choices: null })

/** Renders the page with a live question for savings, once the profile has loaded. */
async function askSavings(onChecksChanged = vi.fn()) {
  renderPage(false, onChecksChanged)
  await screen.findByLabelText('כסף זמין')
  emit(userMessage(1, 'רוצה לקנות רכב'), turnStatus(2, 'running'), SAVINGS_QUESTION)
  emit(turnStatus(4, 'idle'))
  return document.querySelector<HTMLElement>('.bubble-question')!
}

async function answerSavings(bubble: HTMLElement, amount: string) {
  const box = within(bubble).getByRole('textbox', { name: 'כסף זמין' })
  await userEvent.clear(box)
  await userEvent.type(box, amount)
  await userEvent.click(within(bubble).getByRole('button', { name: 'אישור' }))
}

async function commitInPanel(label: string, amount: string) {
  await userEvent.click(screen.getByRole('button', { name: 'פתיחת הפרופיל לעריכה' }))
  const field = within(document.querySelector<HTMLElement>('.profile-panel')!).getByLabelText(label)
  await userEvent.clear(field)
  await userEvent.type(field, amount)
  await userEvent.tab()
}

test('a tapped profile answer is saved, then sent as a line', async () => {
  const fetchStub = stubApi()
  const bubble = await askSavings()
  await answerSavings(bubble, '12000')

  await waitFor(() => expect(sentTexts(fetchStub)).toEqual(['כסף זמין: 12,000 ₪']))
  expect(profilePuts(fetchStub)).toEqual([{ savings: '12000' }])
  const paths = fetchStub.mock.calls.map(([path, init]) => `${init?.method ?? 'GET'} ${path}`)
  expect(paths.indexOf('PUT /api/profile')).toBeLessThan(paths.indexOf(`POST ${MESSAGES}`))
})

test('a capped send after a saved answer keeps the bubble', async () => {
  const today = new Date()
  const nextAllowed = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate() + 1,
    7,
    5,
  ).toISOString()
  const fetchStub = stubApi(() =>
    jsonResponse(429, { detail: 'daily message cap reached', next_allowed: nextAllowed }),
  )
  const onChecksChanged = vi.fn()
  const bubble = await askSavings(onChecksChanged)
  await answerSavings(bubble, '12000')

  expect(
    await screen.findByText('הגעתם למכסת ההודעות. אפשר להמשיך מחר ב-07:05'),
  ).toBeInTheDocument()
  expect(profilePuts(fetchStub)).toEqual([{ savings: '12000' }])
  expect(onChecksChanged).toHaveBeenCalledTimes(1)
  expect(within(bubble).getByRole('textbox', { name: 'כסף זמין' })).toBeInTheDocument()
  expect(within(bubble).getByRole('button', { name: 'אישור' })).toBeEnabled()
})

test('a skipped savings question saves 0 before sending its line', async () => {
  const fetchStub = stubApi()
  const bubble = await askSavings()
  await userEvent.click(within(bubble).getByRole('button', { name: 'דילוג' }))

  await waitFor(() => expect(sentTexts(fetchStub)).toEqual(['דילוג על: כסף זמין (נשמר כ-0)']))
  expect(profilePuts(fetchStub)).toEqual([{ savings: '0' }])
})

test('a failed skip shows the failure and keeps the bubble', async () => {
  stubApi(() => jsonResponse(500, { detail: 'boom' }))
  const bubble = await askSavings()
  await userEvent.click(within(bubble).getByRole('button', { name: 'דילוג' }))

  expect(await screen.findByText('ההודעה לא נשלחה: boom')).toBeInTheDocument()
  expect(within(bubble).getByRole('button', { name: 'דילוג' })).toBeEnabled()
})

test('a panel edit shows as a note in the conversation', async () => {
  const fetchStub = stubApi()
  const { onChecksChanged } = renderPage()
  await screen.findByLabelText('כסף זמין')
  emit(userMessage(1, 'רוצה לקנות רכב'), assistantMessage(2, 'a1', 'בשמחה'))
  await commitInPanel('הוצאות קבועות', '3000')

  const note = await screen.findByText('עודכן בפרופיל: הוצאות קבועות 3,000 ₪')
  expect(note).toHaveClass('panel-note-line')
  expect(note.closest('li')).toHaveTextContent('בשמחה')
  expect(profilePuts(fetchStub)).toEqual([{ fixed_expenses: '3000' }])
  expect(sentTexts(fetchStub)).toEqual([])
  expect(onChecksChanged).toHaveBeenCalledTimes(1)
})

test('a panel edit of the field the live question asks for answers it', async () => {
  const fetchStub = stubApi()
  await askSavings()
  await commitInPanel('כסף זמין', '9000')

  await waitFor(() => expect(sentTexts(fetchStub)).toEqual(['כסף זמין: 9,000 ₪']))
  expect(profilePuts(fetchStub)).toEqual([{ savings: '9000' }])
  expect(screen.queryByText(/עודכן בפרופיל/)).not.toBeInTheDocument()
})

test('a refused answer from the panel is noted instead', async () => {
  stubApi(() => jsonResponse(500, { detail: 'boom' }))
  await askSavings()
  await commitInPanel('כסף זמין', '9000')

  expect(await screen.findByText('ההודעה לא נשלחה: boom')).toBeInTheDocument()
  expect(await screen.findByText('עודכן בפרופיל: כסף זמין 9,000 ₪')).toHaveClass(
    'panel-note-line',
  )
})

test('a panel note made while a reply streams outlives the reply being dropped', async () => {
  stubApi()
  renderPage()
  await screen.findByLabelText('כסף זמין')
  emit(userMessage(1, 'רוצה לקנות רכב'), turnStatus(2, 'running'), delta('a1', 'חצי'))
  await commitInPanel('הוצאות קבועות', '3000')
  const text = 'עודכן בפרופיל: הוצאות קבועות 3,000 ₪'
  await screen.findByText(text)
  emit(turnStatus(3, 'idle'))

  expect(screen.queryByText('חצי')).not.toBeInTheDocument()
  expect(screen.getByText(text).closest('li')).toHaveTextContent('רוצה לקנות רכב')
})

test('a typed message closes the live question', async () => {
  stubApi()
  const bubble = await askSavings()
  expect(within(bubble).getByRole('button', { name: 'דילוג' })).toBeInTheDocument()
  await userEvent.type(screen.getByRole('textbox', { name: 'הודעה לעוזר' }), 'יש לי 5000{Enter}')
  emit(userMessage(5, 'יש לי 5000'), turnStatus(6, 'running'))

  expect(within(bubble).queryByRole('button')).not.toBeInTheDocument()
  expect(bubble).toHaveTextContent('כסף זמין')
})

const CLONE_OFFER = { field: null, text: null, choices: null, offer_clone: true } as const

test('a clone offer clones with its choice and answers this check with the other', async () => {
  const fetchStub = stubApi()
  const { onClone } = renderPage()
  emit(userMessage(1, 'ומה עם 1,000 בחודש?'), questionAsked(2, CLONE_OFFER))

  expect(screen.getByText(/לשכפל את הבדיקה/, { selector: '.question-label' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'דילוג' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'לשכפל ולבדוק בנפרד' }))
  expect(onClone).toHaveBeenCalledWith('לשכפל ולבדוק בנפרד')
  expect(sentTexts(fetchStub)).toEqual([])

  await userEvent.click(screen.getByRole('button', { name: 'לעדכן את הבדיקה הזאת' }))
  expect(sentTexts(fetchStub)).toEqual(['לעדכן את הבדיקה הזאת'])
})

test('a continuation opens the new check only after this page sent', async () => {
  stubApi()
  const { onOpenCheck } = renderPage()
  emit(userMessage(1, 'א'), checkArchived(2), checkContinued(3, 'c0'))
  expect(onOpenCheck).not.toHaveBeenCalled()

  await userEvent.click(screen.getByRole('button', { name: 'מעבר לבדיקה המעודכנת' }))
  expect(onOpenCheck).toHaveBeenCalledWith('c0')
})

test('a live continuation after a send opens the new check', async () => {
  stubApi()
  const { onOpenCheck } = renderPage()
  await userEvent.type(screen.getByRole('textbox'), 'טעיתי{Enter}')
  emit(
    userMessage(1, 'טעיתי'),
    turnStatus(2, 'running'),
    checkArchived(3),
    checkContinued(4, 'c2'),
  )

  await waitFor(() => expect(onOpenCheck).toHaveBeenCalledWith('c2'))
})
