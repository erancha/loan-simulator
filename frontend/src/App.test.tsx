import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { SIGNED_OUT_EVENT } from './api/client.ts'
import type { User } from './api/types.ts'
import { App } from './App.tsx'

const dana: User = { id: '1001', email: 'dana@example.com', name: 'Dana' }

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status })
}

/** Stubs fetch with one handler per `METHOD path`; an unlisted call fails the test. */
function stubApi(routes: Record<string, () => Response>) {
  const fetchStub = vi.fn((path: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${path}`
    const route = routes[key]
    if (route === undefined) return Promise.reject(new Error(`unexpected request ${key}`))
    return Promise.resolve(route())
  })
  vi.stubGlobal('fetch', fetchStub)
  return fetchStub
}

const noChecks = { 'GET /api/checks': () => jsonResponse(200, []) }

const signedOut = {
  'GET /api/auth/me': () => jsonResponse(401, { detail: 'sign in to continue' }),
  'GET /api/auth/config': () => jsonResponse(200, { clientId: 'loan-test-client' }),
}

const SIGN_IN = 'התחברות עם Google'

/** An unsigned token whose payload carries the nonce, in the base64url form Google uses. */
function tokenWithNonce(nonce: string): string {
  const payload = btoa(JSON.stringify({ nonce })).replace(/\+/g, '-').replace(/\//g, '_')
  return `header.${payload.replace(/=+$/, '')}.signature`
}

/** Loads the page as Google's redirect leaves it, after this tab stored its nonce. */
function returnFromGoogle(fragment: string, storedNonce = 'tab-nonce') {
  sessionStorage.setItem('google-sign-in-nonce', storedNonce)
  history.replaceState(null, '', `/#${fragment}`)
}

afterEach(() => {
  vi.unstubAllGlobals()
  sessionStorage.clear()
  history.replaceState(null, '', '/')
})

test('the page is Hebrew and right to left', () => {
  stubApi(signedOut)
  render(<App />)
  expect(document.documentElement.lang).toBe('he')
  expect(document.documentElement.dir).toBe('rtl')
})

test('signed out shows our own Google button and the product name', async () => {
  stubApi(signedOut)
  render(<App />)

  expect(screen.getByText('בודקים מי מחובר…')).toBeInTheDocument()
  expect(await screen.findByRole('button', { name: SIGN_IN })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'סימולטור הלוואות' })).toBeInTheDocument()
  const steps = screen.getAllByRole('listitem')
  expect(steps).toHaveLength(3)
  for (const step of steps) expect(step.querySelectorAll('strong')).toHaveLength(1)
  expect(steps.map((step) => step.querySelector('strong')?.textContent)).toEqual([
    'מתארים את ההלוואה המבוקשת',
    'מזינים את ההצעות שקיבלתם',
    'רואים את המחיר האמיתי של כל הצעה',
  ])
  expect(steps[0]).toHaveTextContent(/^\d*מתארים את ההלוואה המבוקשת: מטרה, סכום והחזר חודשי מרבי\.$/)
  expect(steps.map((step) => step.textContent).join(' ')).not.toMatch(/הכנסה|הוצאות/)
  expect(screen.queryByText('כניסה רק עם חשבון Google')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'תפריט חשבון' })).not.toBeInTheDocument()
})

test('a person the server knows goes straight into the app', async () => {
  stubApi({ ...noChecks, 'GET /api/auth/me': () => jsonResponse(200, dana) })
  render(<App />)
  expect(await screen.findByRole('button', { name: 'תפריט חשבון' })).toBeInTheDocument()
})

test('clicking the button leaves for Google with a nonce this tab keeps', async () => {
  stubApi(signedOut)
  const assign = vi.fn()
  vi.stubGlobal('location', { origin: 'http://localhost:8101', hash: '', assign })
  render(<App />)

  await userEvent.click(await screen.findByRole('button', { name: SIGN_IN }))

  await waitFor(() => expect(assign).toHaveBeenCalledOnce())
  const url = new URL(assign.mock.calls[0][0] as string)
  expect(`${url.origin}${url.pathname}`).toBe('https://accounts.google.com/o/oauth2/v2/auth')
  expect(url.searchParams.get('client_id')).toBe('loan-test-client')
  expect(url.searchParams.get('redirect_uri')).toBe('http://localhost:8101/')
  expect(url.searchParams.get('response_type')).toBe('id_token')
  expect(url.searchParams.get('scope')).toBe('openid email profile')
  expect(url.searchParams.get('nonce')).toBe(sessionStorage.getItem('google-sign-in-nonce'))
  expect(url.searchParams.get('nonce')).not.toBeNull()
})

test('a client id that cannot be fetched is shown on the landing', async () => {
  stubApi({
    'GET /api/auth/me': () => jsonResponse(401, { detail: 'sign in to continue' }),
    'GET /api/auth/config': () => jsonResponse(500, { detail: 'no client id' }),
  })
  render(<App />)

  await userEvent.click(await screen.findByRole('button', { name: SIGN_IN }))

  expect(await screen.findByRole('alert')).toHaveTextContent('no client id')
})

test('a token that answers this tab is posted and enters the app', async () => {
  const token = tokenWithNonce('tab-nonce')
  returnFromGoogle(`id_token=${token}&authuser=0`)
  const fetchStub = stubApi({ ...noChecks, 'POST /api/auth/session': () => jsonResponse(200, dana) })
  render(<App />)

  expect(await screen.findByRole('button', { name: 'תפריט חשבון' })).toBeInTheDocument()
  const post = fetchStub.mock.calls.find(([path]) => path === '/api/auth/session')
  expect(JSON.parse(post?.[1]?.body as string)).toEqual({ credential: token })
  expect(window.location.hash).toBe('')
  expect(sessionStorage.getItem('google-sign-in-nonce')).toBeNull()
})

test('a token the server refuses shows the refusal line on the sign-in screen', async () => {
  returnFromGoogle(`id_token=${tokenWithNonce('tab-nonce')}`)
  stubApi({
    ...signedOut,
    'POST /api/auth/session': () => jsonResponse(401, { detail: 'the token is not valid' }),
  })
  render(<App />)

  expect(await screen.findByRole('alert')).toHaveTextContent('הכניסה עם Google לא הושלמה')
  expect(screen.getByRole('button', { name: SIGN_IN })).toBeInTheDocument()
})

test('a token with another nonce is refused and nothing is posted', async () => {
  returnFromGoogle(`id_token=${tokenWithNonce('injected-nonce')}`)
  const fetchStub = stubApi(signedOut)
  render(<App />)

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'הכניסה עם Google לא הושלמה. אפשר לנסות שוב.',
  )
  expect(screen.getByRole('button', { name: SIGN_IN })).toBeInTheDocument()
  expect(fetchStub.mock.calls.map(([path]) => path)).not.toContain('/api/auth/session')
  expect(window.location.hash).toBe('')
})

test('a person who cancels at Google lands on the sign-in screen without an error', async () => {
  returnFromGoogle('error=access_denied')
  stubApi(signedOut)
  render(<App />)

  expect(await screen.findByRole('button', { name: SIGN_IN })).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(window.location.hash).toBe('')
})

test('an error other than a cancellation shows the refusal line', async () => {
  returnFromGoogle('error=server_error')
  stubApi(signedOut)
  render(<App />)

  expect(await screen.findByRole('alert')).toHaveTextContent('הכניסה עם Google לא הושלמה')
})

test('a 401 from any call drops back to the sign-in screen', async () => {
  stubApi({ ...signedOut, ...noChecks, 'GET /api/auth/me': () => jsonResponse(200, dana) })
  render(<App />)
  await screen.findByRole('button', { name: 'תפריט חשבון' })

  act(() => window.dispatchEvent(new Event(SIGNED_OUT_EVENT)))

  await waitFor(() =>
    expect(screen.getByRole('button', { name: SIGN_IN })).toBeInTheDocument(),
  )
  expect(screen.queryByRole('button', { name: 'תפריט חשבון' })).not.toBeInTheDocument()
})

test('a server that cannot be reached shows a failure, not sign-in', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('connection refused')))
  render(<App />)

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'לא הצלחנו להגיע לשרת: connection refused',
  )
  expect(screen.queryByRole('button', { name: SIGN_IN })).not.toBeInTheDocument()
})

test('a failed sign-out says so and keeps the person in the app', async () => {
  stubApi({
    ...noChecks,
    'GET /api/auth/me': () => jsonResponse(200, dana),
    'DELETE /api/auth/session': () => jsonResponse(500, { detail: 'boom' }),
  })
  render(<App />)
  await userEvent.click(await screen.findByRole('button', { name: 'תפריט חשבון' }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'התנתקות' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('היציאה לא הצליחה: boom')
  expect(screen.getByRole('button', { name: 'תפריט חשבון' })).toBeInTheDocument()
})

test('signed out names the tagline and the build under the title', async () => {
  stubApi(signedOut)
  render(<App />)
  await screen.findByRole('button', { name: SIGN_IN })

  expect(screen.getByText(/^גירסה \d+\.\d+\.\d+, \d{2}\/\d{2}\/\d{4}$/)).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'סימולטור הלוואות' })).toBeInTheDocument()
  expect(screen.getByText('מבוסס בינה מלאכותית')).toBeInTheDocument()
})

test('signed out leads with the question and the chat, then says it lends nothing', async () => {
  stubApi(signedOut)
  render(<App />)
  await screen.findByRole('button', { name: SIGN_IN })

  const question = screen.getByText('קיבלתם הצעות להלוואה ולא ברור איזו משתלמת?')
  expect(question.tagName).toBe('STRONG')
  expect(question.parentElement).toHaveTextContent(
    'קיבלתם הצעות להלוואה ולא ברור איזו משתלמת? הסימולטור משווה ביניהן ומול הריבית הממוצעת' +
      ' בבנקים, וממליץ.',
  )
  const chat = screen.getByText('הכול בשיחה, במילים שלכם, בלי ידע מוקדם:')
  expect(chat.tagName).toBe('STRONG')
  expect(chat.parentElement).toHaveTextContent(
    'הכול בשיחה, במילים שלכם, בלי ידע מוקדם: הסימולטור שואל מה שצריך, ואפשר לשאול אותו כל דבר' +
      ' בדרך.',
  )
  expect(question.compareDocumentPosition(chat)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  const offersStep = screen.getAllByRole('listitem')[1]
  expect(offersStep).toHaveTextContent(/הסימולטור לא נותן הלוואות ולא פונה לאף גוף מלווה\.$/)
})

test('signed out links to the demo, the WhatsApp invite and the source', async () => {
  stubApi(signedOut)
  render(<App />)
  await screen.findByRole('button', { name: SIGN_IN })

  const demo = screen.getByRole('link', { name: 'הדגמה (40* שניות)' })
  expect(within(demo).getByText('*').tagName).toBe('SUP')
  expect(demo).toHaveAttribute('href', '/demo.html')
  // The demo's tab keeps its tie to this one, so its link into the simulator can return here.
  expect(demo).toHaveAttribute('rel', 'opener')
  expect(demo).toHaveAttribute(
    'title',
    'שיחה מוקלטת, מהשאלה הראשונה ועד ההמלצה; מומלץ לראות במסך מחשב\n' +
      '* ההדגמה מתחילה במהירות כפולה. במהירות רגילה היא נמשכת כדקה וחצי, והשעון בהדגמה סופר' +
      ' לפיה.',
  )
  const invite = new URL(
    screen.getByRole('link', { name: 'הזמנת חברים ב-WhatsApp' }).getAttribute('href') as string,
  )
  expect(`${invite.origin}${invite.pathname}`).toBe('https://wa.me/')
  const message = invite.searchParams.get('text') as string
  // An empty line between paragraphs; the address sits right under the line that leads into it.
  const paragraphs = message.split('\n\n')
  expect(paragraphs).toHaveLength(4)
  expect(paragraphs[0]).toBe(
    'היי! 👋 קיבלתי המלצה על סימולטור הלוואות מבוסס בינה מלאכותית, למי שמתלבט בין הצעות' +
      ' להלוואה.',
  )
  expect(paragraphs[3]).toBe(
    `🎁 זה בחינם, ויש שם גם ▶️ הדגמה של 40 שניות, בלי להירשם:\n${window.location.origin}`,
  )
  expect(screen.getByRole('link', { name: 'קוד המקור ב-GitHub' })).toHaveAttribute(
    'href',
    'https://github.com/erancha/loan-simulator',
  )
})

test('the more toggle adds the details under the pitch', async () => {
  stubApi(signedOut)
  render(<App />)
  const more = await screen.findByRole('button', { name: 'יותר' })
  expect(screen.queryByText(/זה לא חובה/)).not.toBeInTheDocument()

  await userEvent.click(more)
  expect(screen.getByText(/זה לא חובה/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'פחות' })).toHaveAttribute('aria-expanded', 'true')
})

test('opening the sign-in explanation folds the details back', async () => {
  stubApi(signedOut)
  render(<App />)
  const more = await screen.findByRole('button', { name: 'יותר' })
  fireEvent.click(more)
  fireEvent.click(document.querySelector('.sign-in-why') as HTMLElement)
  expect(document.querySelector('.landing-card > .landing-details')).toBeNull()
  expect(more).toHaveAttribute('aria-expanded', 'false')
})
