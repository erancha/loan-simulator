import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { CheckEvent, CheckSummary } from '../api/types.ts'
import { FakeEventSource } from '../test/fakeEventSource.ts'
import {
  assistantMessage,
  checkArchived,
  financesUpdated,
  loanSet,
  optionFixed36,
  optionPrime36,
  questionAsked,
  recommendationPrime,
  REFERENCE_DECISION,
  termSet,
  turnStatus,
  userMessage,
  withSeq,
} from '../test/fixtures.ts'
import { CheckPage } from './CheckPage.tsx'

const MESSAGES = '/api/checks/c1/messages'
const FINANCES = '/api/checks/c1/finances'
const MARKET = '/api/checks/c1/market-sample'
const OFFER = '/api/checks/c1/offer-sample'
const TERM = '/api/checks/c1/term'
const TERM_CEILING = '/api/checks/c1/term-ceiling'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status })
}

/** Stubs fetch: a finances PUT answers `onFinances`; a message POST answers `onMessage`. */
function stubApi(
  onMessage: () => Response | Promise<Response> = () => new Response(null, { status: 202 }),
  onFinances: () => Response | Promise<Response> = () => jsonResponse(200, {}),
) {
  const fetchStub = vi.fn((path: string, init?: RequestInit) => {
    if (path === FINANCES && init?.method === 'PUT') return Promise.resolve(onFinances())
    if (path === MESSAGES && init?.method === 'POST') return Promise.resolve(onMessage())
    if (path === MARKET && init?.method === 'POST') return Promise.resolve(onMessage())
    if (path === OFFER && init?.method === 'POST') return Promise.resolve(onMessage())
    if (path === TERM_CEILING && init?.method === 'POST') return Promise.resolve(onMessage())
    if (path === TERM && init?.method === 'PUT') return Promise.resolve(new Response(null, { status: 204 }))
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

/** The bodies of the finances PUTs, in order. */
function financesPuts(fetchStub: ReturnType<typeof stubApi>): unknown[] {
  return fetchStub.mock.calls
    .filter(([path, init]) => path === FINANCES && init?.method === 'PUT')
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

/** A new check as the checks list shows it: no loan, no term, no recommendation. */
const NEW_CHECK: CheckSummary = {
  id: 'c1',
  created_at: '2026-11-15T10:00:00Z',
  loan: null,
  recommendation: null,
  recommends_examples_only: false,
  term_months: null,
  archived: false,
  started: true,
}

function renderPage(
  onChecksChanged = vi.fn(),
  onClone = vi.fn(() => Promise.resolve()),
  listed: CheckSummary = NEW_CHECK,
) {
  render(
    <CheckPage
      checkId="c1"
      listed={listed}
      sidebar={<nav>הבדיקות שלי</nav>}
      activePane="chat"
      onChecksChanged={onChecksChanged}
      onClone={onClone}
      onOpenCheck={vi.fn()}
    />,
  )
  return { onChecksChanged, onClone }
}

beforeEach(() => {
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
})
afterEach(() => vi.unstubAllGlobals())

test('replaying the reference events fills the panes', () => {
  stubApi()
  renderPage()
  expect(FakeEventSource.last().url).toBe('/api/checks/c1/events')
  emit(
    userMessage(1, 'רוצה לקנות רכב'),
    loanSet,
    optionPrime36,
    optionFixed36,
    recommendationPrime,
    assistantMessage(7, 'a1', 'הנה ההמלצה'),
    turnStatus(8, 'idle'),
  )

  const page = document.querySelector('.check-page')!
  expect(page).toHaveAttribute('data-active-pane', 'chat')
  expect(page.querySelector('.pane-side')).toHaveTextContent('הבדיקות שלי')
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

test('the market sample goes to its own route, any other text to the model', async () => {
  const fetchStub = stubApi()
  renderPage()
  await userEvent.click(screen.getByRole('button', { name: 'פריים ומדדים' }))
  await userEvent.click(screen.getByRole('button', { name: 'שליחה' }))

  await waitFor(() => expect(screen.getByRole('textbox')).toHaveValue(''))
  expect(fetchStub.mock.calls.map(([path]) => path)).toEqual([MARKET])
  expect(sentTexts(fetchStub)).toEqual([])
})

test('the offer chip sentence goes to its own route, typed with more words to the model', async () => {
  const fetchStub = stubApi()
  renderPage()
  emit(loanSet)
  const input = screen.getByRole('textbox')
  await userEvent.type(input, 'קיבלתי הצעה להלוואה מגוף מלווה{Enter}')
  await waitFor(() => expect(input).toHaveValue(''))
  await userEvent.type(input, 'קיבלתי הצעה להלוואה מגוף מלווה, מהבנק{Enter}')
  await waitFor(() => expect(input).toHaveValue(''))

  expect(fetchStub.mock.calls.map(([path]) => path)).toEqual([OFFER, MESSAGES])
})

test('the offer chip sentence on a check with no loan goes to the model, which asks for it', async () => {
  const fetchStub = stubApi()
  renderPage()
  const input = screen.getByRole('textbox')
  await userEvent.type(input, 'קיבלתי הצעה להלוואה מגוף מלווה{Enter}')
  await waitFor(() => expect(input).toHaveValue(''))

  expect(fetchStub.mock.calls.map(([path]) => path)).toEqual([MESSAGES])
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

test('replayed turns do not change the checks', async () => {
  stubApi()
  const { onChecksChanged } = renderPage()
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
  await sendHello()
  emit(userMessage(1, 'שלום'), turnStatus(2, 'running'), turnStatus(3, 'idle'))
  expect(onChecksChanged).toHaveBeenCalledTimes(1)
})

test('a card that cannot be built shows a notice; the chat keeps working', async () => {
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
  await userEvent.type(screen.getByLabelText('הודעה לעוזר'), 'שלום{Enter}')
  await waitFor(() => expect(sentTexts(fetchStub)).toEqual(['שלום']))
  logged.mockRestore()
})

const EXPENSES_QUESTION = questionAsked(3, {
  field: 'fixed_expenses',
  text: null,
  choices: null,
})

/** Renders the page with a live term card proposing 78 months. */
function askTerm() {
  renderPage()
  emit(
    userMessage(1, 'אני רוצה הלוואה בסך 60,000₪'),
    turnStatus(2, 'running'),
    questionAsked(3, { kind: 'term', term_months: 78, first_payment: '986.03' }),
  )
  emit(turnStatus(4, 'idle'))
}

/** The calls the page made, as "METHOD path", with each body that has one. */
function requests(fetchStub: ReturnType<typeof stubApi>): string[] {
  return fetchStub.mock.calls.map(
    ([path, init]) => `${init?.method ?? 'GET'} ${path} ${String(init?.body ?? '')}`.trim(),
  )
}

const CONFIRMED = [
  `PUT ${TERM} {"term_months":78,"payment_ceiling":null}`,
  `POST ${MESSAGES} {"text":"אישור: 78 חודשים"}`,
]

test('the card\'s confirm saves the term, then sends the confirmation', async () => {
  const fetchStub = stubApi()
  askTerm()
  await userEvent.click(screen.getByRole('button', { name: 'אישור' }))
  await waitFor(() => expect(requests(fetchStub)).toEqual(CONFIRMED))
})

test('the card\'s term typed in the chat confirms it too', async () => {
  for (const typed of ['78', '78 חודשים']) {
    const fetchStub = stubApi()
    askTerm()
    await userEvent.type(screen.getByPlaceholderText(/אפשר לכתוב כאן/), `${typed}{Enter}`)
    await waitFor(() => expect(requests(fetchStub)).toEqual(CONFIRMED))
    cleanup()
  }
})

test('a new ceiling alone on the term card is one request with its line', async () => {
  const fetchStub = stubApi()
  askTerm()
  await userEvent.type(screen.getByRole('textbox', { name: 'החזר חודשי מרבי' }), '1000')
  await userEvent.click(screen.getByRole('button', { name: 'אישור' }))
  await waitFor(() =>
    expect(requests(fetchStub)).toEqual([
      `POST ${TERM_CEILING} {"text":"החזר חודשי מרבי: 1,000 ₪","payment_ceiling":"1000"}`,
    ]),
  )
})

test('another term with a new ceiling saves both, then sends the confirmation', async () => {
  const fetchStub = stubApi()
  askTerm()
  const term = screen.getByRole('textbox', { name: 'מספר חודשים' })
  await userEvent.clear(term)
  await userEvent.type(term, '48')
  await userEvent.type(screen.getByRole('textbox', { name: 'החזר חודשי מרבי' }), '1000')
  await userEvent.click(screen.getByRole('button', { name: 'אישור' }))
  await waitFor(() =>
    expect(requests(fetchStub)).toEqual([
      `PUT ${TERM} {"term_months":48,"payment_ceiling":"1000"}`,
      `POST ${MESSAGES} {"text":"אישור: 48 חודשים, החזר חודשי מרבי: 1,000 ₪"}`,
    ]),
  )
})

test('another term typed in the chat goes to the model as text', async () => {
  const fetchStub = stubApi()
  askTerm()
  await userEvent.type(screen.getByPlaceholderText(/אפשר לכתוב כאן/), '48{Enter}')
  await waitFor(() => expect(requests(fetchStub)).toEqual([`POST ${MESSAGES} {"text":"48"}`]))
})

/** Renders the page with a live question for the fixed expenses. */
function askExpenses(onChecksChanged = vi.fn()) {
  renderPage(onChecksChanged)
  emit(userMessage(1, 'רוצה לקנות רכב'), turnStatus(2, 'running'), EXPENSES_QUESTION)
  emit(turnStatus(4, 'idle'))
  return document.querySelector<HTMLElement>('.bubble-question')!
}

async function answerExpenses(bubble: HTMLElement, amount: string) {
  const box = within(bubble).getByRole('textbox', { name: 'הוצאות קבועות' })
  await userEvent.clear(box)
  await userEvent.type(box, amount)
  await userEvent.click(within(bubble).getByRole('button', { name: 'אישור' }))
}

test('a finances answer is saved to the check, then sent as a line', async () => {
  const fetchStub = stubApi()
  const onChecksChanged = vi.fn()
  const bubble = askExpenses(onChecksChanged)
  await answerExpenses(bubble, '4500')

  await waitFor(() => expect(sentTexts(fetchStub)).toEqual(['הוצאות קבועות: 4,500 ₪']))
  expect(financesPuts(fetchStub)).toEqual([{ fixed_expenses: '4500' }])
  const paths = fetchStub.mock.calls.map(([path, init]) => `${init?.method ?? 'GET'} ${path}`)
  expect(paths.indexOf(`PUT ${FINANCES}`)).toBeLessThan(paths.indexOf(`POST ${MESSAGES}`))
  expect(onChecksChanged).toHaveBeenCalledTimes(1)
})

test('a refused finances save stays on the question and sends nothing', async () => {
  const fetchStub = stubApi(undefined, () => jsonResponse(422, { detail: 'negative expenses' }))
  const bubble = askExpenses()
  await answerExpenses(bubble, '4500')

  expect(await screen.findByText('הערך לא התקבל: negative expenses')).toBeInTheDocument()
  expect(sentTexts(fetchStub)).toEqual([])
  expect(within(bubble).getByRole('button', { name: 'אישור' })).toBeEnabled()
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
  const bubble = askExpenses()
  await answerExpenses(bubble, '4500')

  expect(
    await screen.findByText('הגעתם למכסת ההודעות. אפשר להמשיך מחר ב-07:05'),
  ).toBeInTheDocument()
  expect(financesPuts(fetchStub)).toEqual([{ fixed_expenses: '4500' }])
  expect(within(bubble).getByRole('textbox', { name: 'הוצאות קבועות' })).toBeInTheDocument()
  expect(within(bubble).getByRole('button', { name: 'אישור' })).toBeEnabled()
})

test('a skip sends its line without saving anything', async () => {
  const fetchStub = stubApi()
  const bubble = askExpenses()
  await userEvent.click(within(bubble).getByRole('button', { name: 'דילוג' }))

  await waitFor(() => expect(sentTexts(fetchStub)).toEqual(['דילוג על: הוצאות קבועות']))
  expect(financesPuts(fetchStub)).toEqual([])
})

test('a failed skip shows the failure and keeps the bubble', async () => {
  stubApi(() => jsonResponse(500, { detail: 'boom' }))
  const bubble = askExpenses()
  await userEvent.click(within(bubble).getByRole('button', { name: 'דילוג' }))

  expect(await screen.findByText('ההודעה לא נשלחה: boom')).toBeInTheDocument()
  expect(within(bubble).getByRole('button', { name: 'דילוג' })).toBeEnabled()
})

test('a typed message closes the live question', async () => {
  stubApi()
  const bubble = askExpenses()
  expect(within(bubble).getByRole('button', { name: 'דילוג' })).toBeInTheDocument()
  await userEvent.type(screen.getByRole('textbox', { name: 'הודעה לעוזר' }), 'יש לי 5000{Enter}')
  emit(userMessage(5, 'יש לי 5000'), turnStatus(6, 'running'))

  expect(within(bubble).queryByRole('button')).not.toBeInTheDocument()
  expect(bubble).toHaveTextContent('כמה יוצא כל חודש על הוצאות קבועות?')
})

const CLONE_OFFER = { field: null, text: null, choices: null, offer_clone: true } as const

test('a clone offer clones with its choice and the request, and answers this check with the other', async () => {
  const fetchStub = stubApi()
  const { onClone } = renderPage()
  emit(userMessage(1, 'ומה עם 1,000 בחודש?'), questionAsked(2, CLONE_OFFER))

  expect(screen.getByText(/לשכפל את הבדיקה/, { selector: '.question-label' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'דילוג' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'לשכפל ולבדוק בנפרד' }))
  expect(onClone).toHaveBeenCalledWith('לשכפל ולבדוק בנפרד: ומה עם 1,000 בחודש?')
  expect(sentTexts(fetchStub)).toEqual([])

  await userEvent.click(screen.getByRole('button', { name: 'לעדכן את הבדיקה הזאת' }))
  expect(sentTexts(fetchStub)).toEqual(['לעדכן את הבדיקה הזאת'])
})

test('an archived check shows the manual archive line only, with no stale banner', () => {
  stubApi()
  renderPage()
  emit(userMessage(1, 'א'), checkArchived(2))

  expect(screen.getByRole('note')).toHaveTextContent('הבדיקה הועברה לארכיון ידנית.')
  expect(screen.queryByRole('button', { name: 'מעבר לבדיקה המעודכנת' })).not.toBeInTheDocument()
  expect(screen.queryByText('ההמלצה חושבה לפי פרופיל קודם.')).not.toBeInTheDocument()
})

test('no stale banner exists', () => {
  stubApi()
  renderPage()
  expect(document.querySelector('.stale-banner')).toBeNull()
  expect(screen.queryByRole('button', { name: 'לחשב מחדש' })).not.toBeInTheDocument()
})

test('the figures panel stays hidden until the check has figures', () => {
  stubApi()
  renderPage()
  expect(document.querySelector('.finances-panel')).toBeNull()
  emit(financesUpdated, turnStatus(9, 'idle'))
  expect(document.querySelector('.finances-panel')).not.toBeNull()
})

test('an edited figure is saved, then followed by its update line', async () => {
  const fetchStub = stubApi()
  renderPage()
  emit(financesUpdated, turnStatus(9, 'idle'))
  await userEvent.click(screen.getByRole('button', { name: 'עריכה' }))
  const input = screen.getByRole('textbox', { name: 'הוצאות קבועות' })
  expect(input).toHaveValue('4,500')
  await userEvent.clear(input)
  await userEvent.type(input, '5000{Tab}')

  await waitFor(() => expect(sentTexts(fetchStub)).toEqual(['עודכן: הוצאות קבועות 5,000 ₪']))
  expect(financesPuts(fetchStub)).toEqual([{ fixed_expenses: '5000' }])
})

test('a running turn offers no edit of the figures', () => {
  stubApi()
  renderPage()
  emit(financesUpdated, turnStatus(9, 'running'))
  expect(document.querySelector('.finances-panel')).not.toBeNull()
  expect(screen.queryByRole('button', { name: 'עריכה' })).not.toBeInTheDocument()
})

test('an archived check shows the figures read-only', () => {
  const fetchStub = stubApi()
  renderPage()
  emit(financesUpdated, turnStatus(9, 'idle'), checkArchived(10))
  expect(document.querySelector('.finances-panel')).not.toBeNull()
  expect(screen.queryByRole('button', { name: 'עריכה' })).not.toBeInTheDocument()
  expect(financesPuts(fetchStub)).toEqual([])
})

test('an idle check whose term the list shows otherwise refreshes the list once', async () => {
  const onChecksChanged = vi.fn()
  renderPage(onChecksChanged, undefined, { ...NEW_CHECK, loan: loanSet.data, term_months: 24 })
  emit(userMessage(1, 'לשכפל ולבדוק בנפרד'), turnStatus(2, 'running'), loanSet)
  expect(onChecksChanged).not.toHaveBeenCalled()
  emit(withSeq(termSet, 4), turnStatus(5, 'idle'))
  await waitFor(() => expect(onChecksChanged).toHaveBeenCalledTimes(1))
})
