import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { ProfileView } from '../api/types.ts'
import { profileView } from '../test/fixtures.ts'
import { ProfilePanel } from './ProfilePanel.tsx'
import { useProfileStore } from './profileStore.ts'

/** The panel over its own store, as the check page wires them. */
function Harness({ profileVersion, onSaved }: { profileVersion: number; onSaved: () => void }) {
  return <ProfilePanel store={useProfileStore(profileVersion)} onSaved={onSaved} />
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status })
}

/** Stubs fetch: GET answers `initial`; each PUT is answered by `onPut`. */
function stubProfile(
  initial: ProfileView,
  onPut: (body: unknown) => Response = () => jsonResponse(200, initial),
) {
  const fetchStub = vi.fn((path: string, init?: RequestInit) => {
    if (path !== '/api/profile') return Promise.reject(new Error(`unexpected request ${path}`))
    if (init?.method === 'PUT') return Promise.resolve(onPut(JSON.parse(String(init.body))))
    return Promise.resolve(jsonResponse(200, initial))
  })
  vi.stubGlobal('fetch', fetchStub)
  return fetchStub
}

function puts(fetchStub: ReturnType<typeof stubProfile>): string[] {
  return fetchStub.mock.calls
    .filter(([, init]) => init?.method === 'PUT')
    .map(([, init]) => String(init?.body))
}

function renderPanel(onSaved = vi.fn()) {
  return {
    onSaved,
    ...render(<Harness profileVersion={0} onSaved={onSaved} />),
  }
}

/** A complete profile starts closed; the tests that edit it open it first. */
async function openPanel() {
  await userEvent.click(await screen.findByRole('button', { name: 'פתיחת הפרופיל לעריכה' }))
}

function withSavings(savings: string): ProfileView {
  return { ...profileView, profile: { ...profileView.profile, savings } }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

test('renders the six fields and marks missing ones', async () => {
  stubProfile({
    profile: {
      ...profileView.profile,
      savings: null,
      variable_income_minimum: null,
    },
    missing: ['savings', 'variable_income_minimum'],
  })
  renderPanel()
  await openPanel()

  expect(await screen.findByLabelText('הכנסה קבועה')).toHaveValue('8,300')
  expect(screen.getByLabelText('הכנסה משתנה')).toHaveValue('5,000')
  expect(screen.getByLabelText('הוצאות קבועות')).toHaveValue('4,500')
  expect(screen.getByLabelText('החזרי הלוואות')).toHaveValue('0')
  const savings = screen.getByLabelText('כסף זמין')
  expect(savings).toHaveValue('')
  expect(savings).toHaveAttribute('placeholder', 'עוד לא הוזן')
  expect(savings.closest('.field')).toHaveClass('missing')
  expect(screen.getByLabelText('הכנסה קבועה').closest('.field')).not.toHaveClass('missing')
  const minimum = screen.getByLabelText('מינימלית')
  expect(minimum).toHaveValue('')
  expect(minimum.closest('.field')).toHaveClass('missing')
})

test('a complete profile starts closed, showing a summary', async () => {
  stubProfile(profileView)
  renderPanel()

  const toggle = await screen.findByRole('button', {
    name: 'פתיחת הפרופיל לעריכה',
  })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByText('8,300 ₪')).toBeInTheDocument()
  expect(screen.queryByRole('textbox', { name: 'הכנסה קבועה' })).not.toBeInTheDocument()

  await userEvent.click(toggle)
  expect(screen.getByRole('textbox', { name: 'הכנסה קבועה' })).toHaveValue('8,300')
  await userEvent.click(screen.getByRole('button', { name: 'סגירת הפרופיל' }))
  expect(screen.queryByRole('textbox', { name: 'הכנסה קבועה' })).not.toBeInTheDocument()
})

test('a folded row shows its hint on hover, after the full name of a shortened label', async () => {
  stubProfile(profileView)
  renderPanel()

  const income = await screen.findByText('הכנסה קבועה', { selector: 'dt' })
  expect(income).toHaveAttribute('title', expect.stringMatching(/^המשכורת שנכנסת לחשבון/))
  const loans = screen.getByText('החזרי הלוואות', { selector: 'dt' })
  expect(loans).toHaveAttribute('title', expect.stringMatching(/^החזרי הלוואות קיימות: סך/))
  expect(loans.nextElementSibling).toHaveAttribute('title', loans.getAttribute('title'))
  await openPanel()
  const field = screen.getByLabelText('החזרי הלוואות').closest('.field')
  expect(field).toHaveAttribute('title', 'החזרי הלוואות קיימות')
})

test('the fields start folded even while some are missing', async () => {
  stubProfile({
    ...profileView,
    profile: { ...profileView.profile, savings: null },
    missing: ['savings'],
  })
  renderPanel()

  expect(await screen.findByRole('button', { name: 'פתיחת הפרופיל לעריכה' })).toHaveAttribute(
    'aria-expanded',
    'false',
  )
  expect(screen.getByText('עוד לא הוזן')).toBeInTheDocument()
})

test('a chat save leaves the panel folded and flashes the changed field', async () => {
  let getCount = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(() => {
      getCount += 1
      return Promise.resolve(jsonResponse(200, getCount === 1 ? profileView : withSavings('20000')))
    }),
  )
  const onSaved = vi.fn()
  const { rerender } = render(<Harness profileVersion={0} onSaved={onSaved} />)
  expect(await screen.findByRole('button', { name: 'פתיחת הפרופיל לעריכה' })).toBeInTheDocument()

  rerender(<Harness profileVersion={1} onSaved={onSaved} />)
  await screen.findByText('20,000 ₪')
  expect(screen.getByRole('button', { name: 'פתיחת הפרופיל לעריכה' })).toHaveAttribute(
    'aria-expanded',
    'false',
  )
  await openPanel()
  const savings = await screen.findByRole('textbox', { name: 'כסף זמין' })
  expect(savings).toHaveValue('20,000')
  expect(savings.closest('.field')).toHaveClass('changed')
  expect(screen.getByRole('textbox', { name: 'הכנסה קבועה' }).closest('.field')).not.toHaveClass(
    'changed',
  )
})

test('available money comes first, before the income fields', async () => {
  stubProfile(profileView)
  renderPanel()
  await openPanel()

  const savings = await screen.findByLabelText('כסף זמין')
  const income = screen.getByLabelText('הכנסה קבועה')
  expect(savings.compareDocumentPosition(income) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

test('the minimum field follows variable income', async () => {
  stubProfile(profileView)
  renderPanel()
  await openPanel()

  const variable = await screen.findByLabelText('הכנסה משתנה')
  const minimum = screen.getByLabelText('מינימלית')
  const expenses = screen.getByLabelText('הוצאות קבועות')
  expect(minimum).toHaveValue('1,000')
  const follows = Node.DOCUMENT_POSITION_FOLLOWING
  expect(variable.compareDocumentPosition(minimum) & follows).toBeTruthy()
  expect(minimum.compareDocumentPosition(expenses) & follows).toBeTruthy()
})

test('each field carries a hint that a tap opens', async () => {
  stubProfile(profileView)
  renderPanel()
  await openPanel()

  const expenses = await screen.findByLabelText('הוצאות קבועות')
  expect(expenses).toHaveAccessibleDescription(/רק החלק שלך/)
  expect(screen.getByLabelText('מינימלית')).toHaveAccessibleDescription(/גם בחודש חלש/)
  const field = expenses.closest('.field') as HTMLElement
  const button = within(field).getByRole('button', { name: 'הסבר' })
  expect(button).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(button)
  expect(button).toHaveAttribute('aria-expanded', 'true')
  expect(document.getElementById(expenses.getAttribute('aria-describedby') ?? '')).toHaveClass(
    'open',
  )
})

test('blur sends only the edited field as a string', async () => {
  const fetchStub = stubProfile(profileView, () =>
    jsonResponse(200, {
      ...profileView,
      profile: { ...profileView.profile, savings: '20000' },
    }),
  )
  const { onSaved } = renderPanel()
  const savings = await screen.findByLabelText('כסף זמין')

  await userEvent.clear(savings)
  await userEvent.type(savings, '20000')
  await userEvent.tab()

  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1))
  expect(puts(fetchStub)).toEqual(['{"savings":"20000"}'])
  expect(savings).toHaveValue('20,000')
  expect(screen.getByRole('status')).toHaveTextContent('נשמר ✓')
})

test('normalises typed money; empty does not save', async () => {
  const fetchStub = stubProfile(profileView)
  renderPanel()
  const income = await screen.findByLabelText('הכנסה קבועה')

  await userEvent.clear(income)
  await userEvent.type(income, ' 9,300 ')
  await userEvent.tab()
  await waitFor(() => expect(puts(fetchStub)).toEqual(['{"net_fixed_income":"9300"}']))

  await userEvent.clear(income)
  await userEvent.tab()
  expect(puts(fetchStub)).toHaveLength(1)
  expect(income).toHaveValue('8,300')
})

test('a value equal to the stored one sends nothing', async () => {
  const fetchStub = stubProfile(profileView)
  renderPanel()
  const income = await screen.findByLabelText('הכנסה קבועה')
  await userEvent.clear(income)
  await userEvent.type(income, ' 8,300 ')
  await userEvent.tab()
  expect(puts(fetchStub)).toEqual([])
})

test('a 422 keeps the text and shows the message', async () => {
  stubProfile(profileView, () => jsonResponse(422, { detail: 'savings is too large' }))
  const { onSaved } = renderPanel()
  const savings = await screen.findByLabelText('כסף זמין')

  await userEvent.clear(savings)
  await userEvent.type(savings, '99')
  await userEvent.tab()

  expect(await screen.findByText('הערך לא התקבל: savings is too large')).toBeInTheDocument()
  expect(savings).toHaveValue('99')
  expect(onSaved).not.toHaveBeenCalled()
})

test('text that is not an amount shows a hint, logs the reason and keeps the text', async () => {
  const logged = vi.spyOn(console, 'error').mockImplementation(() => {})
  const fetchStub = stubProfile(profileView)
  renderPanel()
  const savings = await screen.findByLabelText('כסף זמין')

  await userEvent.clear(savings)
  await userEvent.type(savings, 'abc')
  await userEvent.tab()

  expect(screen.getByText('הערך לא התקבל: אפשר להקליד רק מספר, למשל 12,500')).toBeInTheDocument()
  expect(logged).toHaveBeenCalledWith(expect.any(RangeError))
  expect(savings).toHaveValue('abc')
  expect(puts(fetchStub)).toEqual([])
  logged.mockRestore()
})

test('a failed load is shown', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(jsonResponse(500, { detail: 'boom' }))),
  )
  renderPanel()
  expect(await screen.findByRole('alert')).toHaveTextContent('לא הצלחנו לטעון את הפרופיל: boom')
})

test('a profile GET answered after a later save is dropped', async () => {
  let getCount = 0
  let answerRefetch: (response: Response) => void = () => {}
  vi.stubGlobal(
    'fetch',
    vi.fn((_path: string, init?: RequestInit) => {
      if (init?.method === 'PUT') return Promise.resolve(jsonResponse(200, withSavings('20000')))
      getCount += 1
      if (getCount === 1) return Promise.resolve(jsonResponse(200, profileView))
      return new Promise<Response>((resolve) => (answerRefetch = resolve))
    }),
  )
  const onSaved = vi.fn()
  const { rerender } = render(<Harness profileVersion={0} onSaved={onSaved} />)
  const savings = await screen.findByLabelText('כסף זמין')
  rerender(<Harness profileVersion={1} onSaved={onSaved} />)
  await waitFor(() => expect(getCount).toBe(2))

  await userEvent.clear(savings)
  await userEvent.type(savings, '20000')
  await userEvent.tab()
  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1))
  answerRefetch(jsonResponse(200, withSavings('1')))

  await new Promise((resolve) => setTimeout(resolve, 20))
  expect(savings).toHaveValue('20,000')
})

test('save responses arriving out of order end on the later save', async () => {
  const answers: Record<string, (response: Response) => void> = {}
  vi.stubGlobal(
    'fetch',
    vi.fn((_path: string, init?: RequestInit) => {
      if (init?.method !== 'PUT') return Promise.resolve(jsonResponse(200, profileView))
      const key = Object.keys(JSON.parse(String(init.body)) as object)[0]
      return new Promise<Response>((resolve) => (answers[key] = resolve))
    }),
  )
  renderPanel()
  const income = await screen.findByLabelText('הכנסה קבועה')
  const savings = screen.getByLabelText('כסף זמין')

  await userEvent.clear(income)
  await userEvent.type(income, '9000')
  await userEvent.clear(savings)
  await userEvent.type(savings, '20000')
  await userEvent.tab()
  await waitFor(() => expect(Object.keys(answers)).toHaveLength(2))

  const first = {
    ...profileView,
    profile: { ...profileView.profile, net_fixed_income: '9000' },
  }
  const second = withSavings('20000')
  answers.savings(jsonResponse(200, second))
  answers.net_fixed_income(jsonResponse(200, first))

  await waitFor(() => expect(savings).toHaveValue('20,000'))
  await new Promise((resolve) => setTimeout(resolve, 20))
  expect(savings).toHaveValue('20,000')
})

test('a failure other than a refused value reads as a failed save', async () => {
  stubProfile(profileView, () => jsonResponse(500, { detail: 'boom' }))
  renderPanel()
  const savings = await screen.findByLabelText('כסף זמין')
  await userEvent.clear(savings)
  await userEvent.type(savings, '5')
  await userEvent.tab()
  expect(await screen.findByText('השמירה לא הצליחה: boom')).toBeInTheDocument()
  expect(savings).toHaveValue('5')
})

test('the folded summary marks given values set and needed ones missing', async () => {
  stubProfile({
    profile: { ...profileView.profile, existing_loan_payments: null },
    missing: ['existing_loan_payments'],
  })
  renderPanel()
  expect(await screen.findByText('עוד לא הוזן')).toHaveClass('value-missing')
  expect(screen.getByText('15,000 ₪')).toHaveClass('value-set')
})
