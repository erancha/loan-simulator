import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { CheckSummary, User } from '../api/types.ts'
import { FakeEventSource } from '../test/fakeEventSource.ts'
import { goal, profileView } from '../test/fixtures.ts'
import { Shell } from './Shell.tsx'

const dana: User = { id: '1001', email: 'dana@example.com', name: 'Dana' }

function summary(id: string, created_at: string, over: Partial<CheckSummary> = {}): CheckSummary {
  return {
    id,
    created_at,
    goal: null,
    recommendation: null,
    recommends_examples_only: false,
    profile_stale: false,
    ...over,
  }
}

const RECOMMENDATION = {} as CheckSummary['recommendation']

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status })
}

/** Stubs fetch: the checks list answers from `lists` in turn (the last repeats). */
function stubApi(
  lists: Array<CheckSummary[] | Response>,
  create: () => Response = () => jsonResponse(201, { id: 'new' }),
  remove: () => Response = () => new Response(null, { status: 204 }),
) {
  let served = 0
  const fetchStub = vi.fn((path: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    if (path === '/api/profile') return Promise.resolve(jsonResponse(200, profileView))
    if (path === '/api/checks' && method === 'GET') {
      const next = lists[Math.min(served++, lists.length - 1)]
      return Promise.resolve(next instanceof Response ? next : jsonResponse(200, next))
    }
    if (path === '/api/checks' && method === 'POST') return Promise.resolve(create())
    if (method === 'DELETE') return Promise.resolve(remove())
    return Promise.reject(new Error(`unexpected request ${method} ${path}`))
  })
  vi.stubGlobal('fetch', fetchStub)
  return fetchStub
}

function openedStreams(): string[] {
  return FakeEventSource.instances.map((source) => source.url)
}

beforeEach(() => {
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  window.history.replaceState(null, '', '/')
})
afterEach(() => vi.unstubAllGlobals())

test('the account menu names the person and signs out', async () => {
  stubApi([[summary('a', '2026-01-01T00:00:00Z')]])
  const onSignOut = vi.fn()
  const user = userEvent.setup()
  render(<Shell user={dana} onSignOut={onSignOut} />)

  expect(screen.getByRole('heading', { level: 1, name: 'סימולטור הלוואות' })).toBeInTheDocument()
  expect(screen.queryByText('Dana')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'תפריט חשבון' }))
  expect(screen.getByText('Dana')).toBeInTheDocument()
  expect(screen.getByText('dana@example.com')).toBeInTheDocument()
  await user.click(screen.getByRole('menuitem', { name: 'התנתקות' }))
  expect(onSignOut).toHaveBeenCalledOnce()
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  await screen.findByRole('navigation', { name: 'הבדיקות שלי' })
  await waitFor(() => expect(window.location.hash).toBe(''))
})

test('the account menu closes on Escape and on a press outside it', async () => {
  stubApi([[]])
  const user = userEvent.setup()
  render(<Shell user={dana} onSignOut={vi.fn()} />)

  await user.click(screen.getByRole('button', { name: 'תפריט חשבון' }))
  await user.keyboard('{Escape}')
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'תפריט חשבון' }))
  await user.click(screen.getByRole('heading', { level: 1 }))
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  await screen.findByText('עוד אין בדיקות. מתחילים?')
})

test('the account menu falls back to the email, then the id', async () => {
  stubApi([[]])
  const user = userEvent.setup()
  const { rerender } = render(<Shell user={{ ...dana, name: null }} onSignOut={vi.fn()} />)
  await user.click(screen.getByRole('button', { name: 'תפריט חשבון' }))
  expect(screen.getByText('dana@example.com')).toBeInTheDocument()
  rerender(<Shell user={{ id: '7', email: null, name: null }} onSignOut={vi.fn()} />)
  expect(screen.getByText('7')).toBeInTheDocument()
  await screen.findByText('עוד אין בדיקות. מתחילים?')
})

test('no checks: the empty state; the button creates and opens a check', async () => {
  const fetchStub = stubApi([[], [summary('new', '2026-02-01T00:00:00Z')]])
  const user = userEvent.setup()
  render(<Shell user={dana} onSignOut={vi.fn()} />)

  expect(await screen.findByText('עוד אין בדיקות. מתחילים?')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '+ בדיקה חדשה' }))

  await waitFor(() => expect(openedStreams()).toEqual(['/api/checks/new/events']))
  expect(window.location.hash).toBe('#check=new')
  expect(screen.queryByText('עוד אין בדיקות. מתחילים?')).not.toBeInTheDocument()
  const posts = fetchStub.mock.calls.filter(([p, i]) => p === '/api/checks' && i?.method === 'POST')
  expect(posts).toHaveLength(1)
})

test('lists checks with price, recommendation and stale markers; the newest opens', async () => {
  stubApi([
    [
      summary('old', '2026-01-01T00:00:00Z', { goal, recommendation: RECOMMENDATION }),
      summary('new', '2026-03-01T00:00:00Z', { profile_stale: true }),
    ],
  ])
  render(<Shell user={dana} onSignOut={vi.fn()} />)

  const list = await screen.findByRole('navigation', { name: 'הבדיקות שלי' })
  const items = within(list).getAllByRole('listitem')
  expect(items).toHaveLength(2)
  const old = items.find((item) => within(item).queryByText('המלצה מוכנה'))!
  expect(old).toHaveTextContent(goal.purpose)
  expect(old).toHaveTextContent('₪')
  const fresh = items.find((item) => within(item).queryByText('חושב לפי פרופיל קודם'))!
  expect(fresh).toHaveTextContent('בדיקה חדשה')
  expect(fresh.querySelector('[aria-current="true"]')).not.toBeNull()
  await waitFor(() => expect(openedStreams()).toEqual(['/api/checks/new/events']))
  expect(window.location.hash).toBe('#check=new')
})

test('picking a check opens its recommendation if it has one, else its chat', async () => {
  stubApi([
    [
      summary('ready', '2026-03-01T00:00:00Z', { goal, recommendation: RECOMMENDATION }),
      summary('open', '2026-01-01T00:00:00Z', { goal }),
    ],
  ])
  const user = userEvent.setup()
  render(<Shell user={dana} onSignOut={vi.fn()} />)
  const list = await screen.findByRole('navigation', { name: 'הבדיקות שלי' })
  const [ready, open] = within(list).getAllByRole('listitem')
  await user.click(screen.getByRole('tab', { name: 'פרופיל' }))

  await user.click(within(ready).getAllByRole('button')[0])
  expect(document.querySelector('.check-page')).toHaveAttribute('data-active-pane', 'card')
  await user.click(within(open).getAllByRole('button')[0])
  expect(document.querySelector('.check-page')).toHaveAttribute('data-active-pane', 'chat')
})

test('a check recommending only examples says so beside its ready chip', async () => {
  stubApi([
    [
      summary('examples', '2026-03-01T00:00:00Z', {
        goal,
        recommendation: RECOMMENDATION,
        recommends_examples_only: true,
      }),
      summary('offer', '2026-01-01T00:00:00Z', { goal, recommendation: RECOMMENDATION }),
    ],
  ])
  render(<Shell user={dana} onSignOut={vi.fn()} />)

  const list = await screen.findByRole('navigation', { name: 'הבדיקות שלי' })
  const [examples, offer] = within(list).getAllByRole('listitem')
  expect(within(examples).getByText('המלצה מוכנה')).toBeInTheDocument()
  expect(within(examples).getByText('דוגמא')).toBeInTheDocument()
  expect(within(offer).getByText('המלצה מוכנה')).toBeInTheDocument()
  expect(within(offer).queryByText('דוגמא')).not.toBeInTheDocument()
})

test('the hash selects a check; clicking another switches stream and hash', async () => {
  stubApi([[summary('a', '2026-01-01T00:00:00Z'), summary('b', '2026-03-01T00:00:00Z')]])
  window.history.replaceState(null, '', '#check=a')
  const user = userEvent.setup()
  render(<Shell user={dana} onSignOut={vi.fn()} />)

  await waitFor(() => expect(openedStreams()).toEqual(['/api/checks/a/events']))
  const [newest] = screen.getAllByRole('listitem')
  await user.click(within(newest).getByRole('button', { name: 'בדיקה חדשה' }))

  await waitFor(() => expect(window.location.hash).toBe('#check=b'))
  expect(openedStreams()).toEqual(['/api/checks/a/events', '/api/checks/b/events'])
})

test('a hash naming an unknown check falls back to the newest and rewrites the hash', async () => {
  stubApi([[summary('a', '2026-01-01T00:00:00Z'), summary('b', '2026-03-01T00:00:00Z')]])
  window.history.replaceState(null, '', '#check=gone')
  render(<Shell user={dana} onSignOut={vi.fn()} />)

  await waitFor(() => expect(openedStreams()).toEqual(['/api/checks/b/events']))
  expect(window.location.hash).toBe('#check=b')
})

test('the tab bar switches the active pane', async () => {
  stubApi([[summary('a', '2026-01-01T00:00:00Z')]])
  const user = userEvent.setup()
  render(<Shell user={dana} onSignOut={vi.fn()} />)
  await screen.findByRole('navigation', { name: 'הבדיקות שלי' })
  const page = document.querySelector('.check-page')!

  expect(page).toHaveAttribute('data-active-pane', 'chat')
  expect(screen.getByRole('tab', { name: 'שיחה' })).toHaveAttribute('aria-selected', 'true')
  await user.click(screen.getByRole('tab', { name: 'המלצה' }))
  expect(page).toHaveAttribute('data-active-pane', 'card')
  expect(screen.getByRole('tab', { name: 'המלצה' })).toHaveAttribute('aria-selected', 'true')
  await user.click(screen.getByRole('tab', { name: 'פרופיל' }))
  expect(page).toHaveAttribute('data-active-pane', 'side')
})

test('a failing list shows an alert', async () => {
  stubApi([jsonResponse(500, { detail: 'db down' })])
  render(<Shell user={dana} onSignOut={vi.fn()} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('לא הצלחנו לטעון את הבדיקות: db down')
})

test('a failing create is reported and opens nothing', async () => {
  stubApi([[]], () => jsonResponse(500, { detail: 'no room' }))
  const user = userEvent.setup()
  render(<Shell user={dana} onSignOut={vi.fn()} />)
  await user.click(await screen.findByRole('button', { name: '+ בדיקה חדשה' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('לא הצלחנו לפתוח בדיקה חדשה: no room')
  expect(openedStreams()).toEqual([])
})

test('a refresh answered late does not overwrite a newer list', async () => {
  const listAnswers: Array<(response: Response) => void> = []
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string, init?: RequestInit) => {
      if (path === '/api/profile') return Promise.resolve(jsonResponse(200, profileView))
      if (init?.method === 'POST') return Promise.resolve(jsonResponse(201, { id: 'n' }))
      return new Promise<Response>((resolve) => listAnswers.push(resolve))
    }),
  )
  const user = userEvent.setup()
  render(<Shell user={dana} onSignOut={vi.fn()} />)
  await waitFor(() => expect(listAnswers).toHaveLength(1))
  listAnswers[0](jsonResponse(200, []))
  const create = await screen.findByRole('button', { name: '+ בדיקה חדשה' })
  await user.click(create)
  await waitFor(() => expect(listAnswers).toHaveLength(2))
  await user.click(create)
  await waitFor(() => expect(listAnswers).toHaveLength(3))

  listAnswers[2](jsonResponse(200, [summary('n', '2026-02-01T00:00:00Z')]))
  await waitFor(() => expect(openedStreams()).toEqual(['/api/checks/n/events']))
  listAnswers[1](jsonResponse(200, []))
  await waitFor(() => expect(screen.getByRole('navigation')).toBeInTheDocument())
  expect(screen.queryByText('עוד אין בדיקות. מתחילים?')).not.toBeInTheDocument()
})

test('deleting asks first; a cancel keeps the check and sends nothing', async () => {
  const fetchStub = stubApi([[summary('a', '2026-01-01T00:00:00Z')]])
  const user = userEvent.setup()
  render(<Shell user={dana} onSignOut={vi.fn()} />)

  await user.click(await screen.findByRole('button', { name: 'מחיקת הבדיקה: בדיקה חדשה' }))
  expect(screen.getByText('למחוק את הבדיקה ואת כל מה שנשמר בה?')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'ביטול' })).toHaveFocus()
  await user.click(screen.getByRole('button', { name: 'ביטול' }))

  expect(screen.queryByText('למחוק את הבדיקה ואת כל מה שנשמר בה?')).not.toBeInTheDocument()
  expect(fetchStub).not.toHaveBeenCalledWith(
    expect.anything(),
    expect.objectContaining({ method: 'DELETE' }),
  )
})

test('a deleted open check gives way to the newest one left', async () => {
  const older = summary('older', '2026-01-01T00:00:00Z')
  const newer = summary('newer', '2026-02-01T00:00:00Z', { goal })
  const fetchStub = stubApi([[newer, older], [older]])
  const user = userEvent.setup()
  render(<Shell user={dana} onSignOut={vi.fn()} />)

  await user.click(await screen.findByRole('button', { name: `מחיקת הבדיקה: ${goal.purpose}` }))
  await user.click(screen.getByRole('button', { name: 'מחיקה' }))

  await waitFor(() => expect(window.location.hash).toBe('#check=older'))
  expect(fetchStub).toHaveBeenCalledWith(
    '/api/checks/newer',
    expect.objectContaining({ method: 'DELETE' }),
  )
  expect(openedStreams().at(-1)).toContain('/api/checks/older/events')
})

test('deleting the last check leaves the empty state and a clean URL', async () => {
  stubApi([[summary('a', '2026-01-01T00:00:00Z')], []])
  const user = userEvent.setup()
  render(<Shell user={dana} onSignOut={vi.fn()} />)

  await user.click(await screen.findByRole('button', { name: 'מחיקת הבדיקה: בדיקה חדשה' }))
  await user.click(screen.getByRole('button', { name: 'מחיקה' }))

  expect(await screen.findByText('עוד אין בדיקות. מתחילים?')).toBeInTheDocument()
  expect(window.location.hash).toBe('')
})

test('a delete during a reply is refused with its reason and keeps the check', async () => {
  const refused = () =>
    jsonResponse(409, { detail: "check 'a' is still answering", check_id: 'a' })
  stubApi([[summary('a', '2026-01-01T00:00:00Z')]], undefined, refused)
  const user = userEvent.setup()
  render(<Shell user={dana} onSignOut={vi.fn()} />)

  await user.click(await screen.findByRole('button', { name: 'מחיקת הבדיקה: בדיקה חדשה' }))
  await user.click(screen.getByRole('button', { name: 'מחיקה' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'אי אפשר למחוק בדיקה בזמן שהעוזר עונה. נסו שוב בעוד רגע.',
  )
  expect(screen.getByRole('button', { name: 'מחיקת הבדיקה: בדיקה חדשה' })).toBeInTheDocument()
})

test('a failed delete is shown with its reason', async () => {
  const failed = () => jsonResponse(500, { detail: 'database down' })
  stubApi([[summary('a', '2026-01-01T00:00:00Z')]], undefined, failed)
  const user = userEvent.setup()
  render(<Shell user={dana} onSignOut={vi.fn()} />)

  await user.click(await screen.findByRole('button', { name: 'מחיקת הבדיקה: בדיקה חדשה' }))
  await user.click(screen.getByRole('button', { name: 'מחיקה' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'לא הצלחנו למחוק את הבדיקה: database down',
  )
})
