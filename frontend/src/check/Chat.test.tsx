import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { Chat } from './Chat.tsx'
import { MARKET_SAMPLE, SHORTER_TERMS_CHIP, TO_CARD } from './copy.ts'
import {
  awaitingAvis,
  checkArchived,
  cpiChart,
  identifiedMax,
  scenarioCpi5,
} from '../test/fixtures.ts'
import { restoreScrollIntoView, stubScrollIntoView } from '../test/scrollIntoView.ts'
import type { ChatEntry, ChatMessage, CheckState, QuestionEntry } from './events.ts'

const exchange: ChatMessage[] = [
  { id: 'u-1', role: 'user', text: 'רוצה לקנות רכב', complete: true },
  { id: 'a1', role: 'assistant', text: 'בשמחה, כמה הוא עולה?', complete: true },
]

/** The question props, for a chat whose entries hold no question. */
const noQuestion = {
  liveQuestionId: null,
  finances: null,
  ceiling: null,
  ceilingFormula: null,
  onAnswer: vi.fn(),
  onSkip: vi.fn(),
  onClone: vi.fn(),
  onOpenCheck: vi.fn(),
  onConfirmReading: vi.fn(() => Promise.resolve()),
  onAnswerAmount: vi.fn(() => Promise.resolve()),
  loanAmount: '45000',
  onContinueOffers: vi.fn(() => Promise.resolve(true)),
  opening: null,
  offersOpen: false,
  samplesOffered: false,
  termChips: { shorter: false, longer: false },
  focusAwaiting: null,
  cardReplyId: null,
  onShowCard: vi.fn(),
}

interface Options {
  messages?: ChatEntry[]
  liveQuestionId?: string | null
  turn?: CheckState['turn']
  failure?: string | null
  notice?: string | null
  onSend?: (text: string) => Promise<boolean>
  offersOpen?: boolean
  samplesOffered?: boolean
  termChips?: { shorter: boolean; longer: boolean }
}

function renderChat({
  messages = exchange,
  liveQuestionId = null,
  turn = 'idle',
  failure = null,
  notice = null,
  onSend = vi.fn(() => Promise.resolve(true)),
  offersOpen = false,
  samplesOffered = false,
  termChips = { shorter: false, longer: false },
}: Options = {}) {
  const { unmount } = render(
    <Chat
      {...noQuestion}
      messages={messages}
      liveQuestionId={liveQuestionId}
      turn={turn}
      failure={failure}
      notice={notice}
      onSend={onSend}
      offersOpen={offersOpen}
      samplesOffered={samplesOffered}
      termChips={termChips}
    />,
  )
  return { onSend, unmount }
}

test('user and assistant bubbles sit on opposite sides', () => {
  renderChat()
  expect(screen.getByText('רוצה לקנות רכב')).toHaveClass('bubble', 'bubble-user')
  expect(screen.getByText('בשמחה, כמה הוא עולה?', { selector: '.bubble' })).toHaveClass(
    'bubble-assistant',
  )
})

test('the reply that presents the recommendation links to the recommendation pane', async () => {
  const onShowCard = vi.fn()
  const props = { ...noQuestion, turn: 'idle' as const, failure: null, notice: null, onSend: vi.fn() }
  const { rerender } = render(<Chat {...props} messages={exchange} onShowCard={onShowCard} />)
  expect(screen.queryByRole('button', { name: TO_CARD })).toBeNull()

  rerender(<Chat {...props} messages={exchange} cardReplyId="a1" onShowCard={onShowCard} />)
  await userEvent.setup().click(screen.getByRole('button', { name: TO_CARD }))
  expect(onShowCard).toHaveBeenCalledTimes(1)
})

test('a running turn shows the thinking bubble until the reply streams', () => {
  const { rerender } = render(
    <Chat
      {...noQuestion}
      messages={exchange.slice(0, 1)}
      turn="running"
      failure={null}
      notice={null}
      onSend={vi.fn()}
    />,
  )
  expect(screen.getByText('העוזר חושב…')).toHaveClass('bubble', 'bubble-thinking')

  rerender(
    <Chat
      {...noQuestion}
      messages={[exchange[0], { id: 'a1', role: 'assistant', text: 'בשמ', complete: false }]}
      turn="running"
      failure={null}
      notice={null}
      onSend={vi.fn()}
    />,
  )
  expect(screen.queryByText('העוזר חושב…')).not.toBeInTheDocument()
  const streaming = screen.getByText('בשמ')
  expect(streaming.querySelector('.caret')).toBeInTheDocument()
})

test('the input is disabled while a turn runs', () => {
  renderChat({ turn: 'running' })
  const input = screen.getByRole('textbox')
  expect(input).toBeDisabled()
  expect(input).toHaveAttribute('placeholder', 'העוזר חושב…')
  expect(screen.getByRole('button', { name: 'שליחה' })).toBeDisabled()
})

test('Enter sends and clears; Shift+Enter breaks a line', async () => {
  const { onSend } = renderChat()
  const input = screen.getByPlaceholderText('אפשר לכתוב כאן…')

  await userEvent.type(input, 'שורה אחת{Shift>}{Enter}{/Shift}שורה שתיים')
  expect(onSend).not.toHaveBeenCalled()
  await userEvent.keyboard('{Enter}')

  expect(onSend).toHaveBeenCalledExactlyOnceWith('שורה אחת\nשורה שתיים')
  await waitFor(() => expect(input).toHaveValue(''))
})

test('the text stays when the send is refused', async () => {
  const onSend = vi.fn(() => Promise.resolve(false))
  renderChat({ onSend, notice: 'ההודעה לא נשלחה: boom' })
  const input = screen.getByRole('textbox')

  await userEvent.type(input, 'שלום')
  await userEvent.click(screen.getByRole('button', { name: 'שליחה' }))

  expect(onSend).toHaveBeenCalledExactlyOnceWith('שלום')
  await waitFor(() => expect(input).toBeEnabled())
  expect(input).toHaveValue('שלום')
  expect(screen.getByText('ההודעה לא נשלחה: boom')).toBeInTheDocument()
})

test('a failed turn shows its message as an alert', () => {
  renderChat({ failure: 'the engine did not answer' })
  expect(screen.getByRole('alert')).toHaveTextContent('the engine did not answer')
})

test('the input is labelled; only completed replies are announced', () => {
  const streaming: ChatMessage = { id: 'a2', role: 'assistant', text: 'חצי', complete: false }
  render(
    <Chat
      {...noQuestion}
      messages={[...exchange, streaming]}
      turn="running"
      failure={null}
      notice={null}
      onSend={vi.fn()}
    />,
  )
  expect(screen.getByRole('textbox', { name: 'הודעה לעוזר' })).toBeInTheDocument()
  expect(screen.getByRole('list')).not.toHaveAttribute('aria-live')
  const announced = document.querySelectorAll('[aria-live]')
  expect(announced).toHaveLength(1)
  expect(announced[0]).toHaveClass('visually-hidden')
  expect(announced[0]).toHaveAttribute('aria-live', 'polite')
  expect(announced[0]).toHaveTextContent('בשמחה, כמה הוא עולה?')
})

test('each new message scrolls to the end; streamed text follows until the reader scrolls up', () => {
  const props = {
    ...noQuestion,
    turn: 'idle' as const,
    failure: null,
    notice: null,
    onSend: vi.fn(),
  }
  const { rerender } = render(<Chat {...props} messages={exchange} />)
  const log = document.querySelector<HTMLElement>('.chat-log')!
  const size = (scrollHeight: number) => {
    Object.defineProperty(log, 'scrollHeight', { configurable: true, value: scrollHeight })
    Object.defineProperty(log, 'clientHeight', { configurable: true, value: 300 })
  }
  const message = (id: string) => ({ id, role: 'user' as const, text: id, complete: true })
  size(1000)

  const more = [...exchange, message('u-2')]
  rerender(<Chat {...props} messages={more} />)
  expect(log.scrollTop).toBe(1000)

  // The scroll event of the code's own scroll arrives after the log has grown further.
  size(1400)
  fireEvent.scroll(log)
  const evenMore = [...more, message('u-3')]
  rerender(<Chat {...props} messages={evenMore} />)
  expect(log.scrollTop).toBe(1400)

  // Scrolled up, the reader keeps their place while a reply's text streams in.
  log.scrollTop = 100
  fireEvent.scroll(log)
  size(1600)
  const reply = (text: string) => ({ id: 'a2', role: 'assistant' as const, text, complete: false })
  const streaming = [...evenMore, reply('א')]
  rerender(<Chat {...props} messages={streaming} />)
  log.scrollTop = 100
  fireEvent.scroll(log)
  size(1800)
  rerender(<Chat {...props} messages={[...evenMore, reply('אבג')]} />)
  expect(log.scrollTop).toBe(100)

  // A new message brings the end of the log back into view.
  size(2000)
  rerender(<Chat {...props} messages={[...evenMore, reply('אבג'), message('u-4')]} />)
  expect(log.scrollTop).toBe(2000)
})

test('a note, a failure or a notice under the last message is brought into view', () => {
  const props = { ...noQuestion, messages: exchange, turn: 'idle' as const, onSend: vi.fn() }
  const { rerender } = render(<Chat {...props} failure={null} notice={null} />)
  const log = document.querySelector<HTMLElement>('.chat-log')!
  Object.defineProperty(log, 'scrollHeight', { configurable: true, value: 900 })
  rerender(<Chat {...props} failure={null} notice="לא נשלח" />)
  expect(log.scrollTop).toBe(900)
})

test('growth without a new message re-pins the log unless the reader scrolled up', () => {
  const callbacks: Array<() => void> = []
  const observed: Element[] = []
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(callback: () => void) {
        callbacks.push(callback)
      }
      observe(element: Element) {
        observed.push(element)
      }
      disconnect() {}
    },
  )
  const { unmount } = render(
    <Chat
      {...noQuestion}
      messages={exchange}
      turn="idle"
      failure={null}
      notice={null}
      onSend={vi.fn()}
    />,
  )
  const log = document.querySelector<HTMLElement>('.chat-log')!
  expect(observed).toEqual([log, log.firstElementChild])
  const grow = (scrollHeight: number) =>
    Object.defineProperty(log, 'scrollHeight', { configurable: true, value: scrollHeight })

  grow(1744)
  callbacks[0]()
  expect(log.scrollTop).toBe(1744)

  log.scrollTop = 100
  fireEvent.scroll(log)
  grow(2000)
  callbacks[0]()
  expect(log.scrollTop).toBe(100)
  unmount()
  vi.unstubAllGlobals()
})

const question: QuestionEntry = {
  id: 'q-3',
  role: 'question',
  question: { field: 'amount', text: null, choices: null },
  leadIn: null,
  answered: false,
}

test('a question shows as its own turn, with a control only while it is live', () => {
  const props = {
    ...noQuestion,
    messages: [...exchange, question],
    turn: 'idle' as const,
    failure: null,
    notice: null,
    onSend: vi.fn(),
  }
  const { rerender } = render(
    <Chat
      {...props}
      liveQuestionId="q-3"
    />,
  )
  const turn = screen.getAllByRole('listitem')[2]
  expect(turn).toHaveClass('chat-turn')
  expect(turn.querySelector('.bubble-question')).toHaveTextContent('כמה צריך ללוות?')
  expect(screen.getByRole('button', { name: 'דילוג' })).toBeInTheDocument()

  rerender(<Chat {...props} liveQuestionId={null} />)
  expect(screen.queryByRole('button', { name: 'דילוג' })).not.toBeInTheDocument()
  expect(document.querySelector('.bubble-question')).toHaveTextContent('כמה צריך ללוות?')
})

test('a question that ends the conversation is announced with its lead-in and question', () => {
  renderChat({
    messages: [...exchange, { ...question, leadIn: 'כדי להמשיך' }],
    liveQuestionId: 'q-3',
  })
  const announced = document.querySelector('[aria-live="polite"]')
  expect(announced).toHaveTextContent(/^כדי להמשיך כמה צריך ללוות\?$/)
})

test('a scenario pairs each figure today with the scenario, marking how it moved', () => {
  renderChat({ messages: [{ id: 's-2', role: 'scenario', scenario: scenarioCpi5 }] })

  const table = screen.getByRole('table', { name: 'אם המדד יעלה 5% בשנה והפריים לא ישתנה' })
  const [groups, columns, linked, prime] = within(table).getAllByRole('row')
  expect(groups).toHaveTextContent('החזר מרביסך התשלומים')
  expect(columns).toHaveTextContent('היוםבתרחישהיוםבתרחיש')
  const cells = (row: HTMLElement) => within(row).getAllByRole('cell')
  expect(cells(linked).map((cell) => cell.textContent)).toEqual([
    '1,985 ₪',
    '2,210 ₪',
    '113,424 ₪',
    '121,005 ₪',
  ])
  expect(cells(linked)[3]).toHaveClass('scenario-higher')
  expect(cells(prime).map((cell) => cell.textContent)).toEqual(['1,899 ₪', '↔️', '113,916 ₪', '↔️'])
  expect(cells(prime)[1]).toHaveAccessibleName('ללא שינוי')
})

test('a scenario names each option by its lender, with the full track on its title', () => {
  renderChat({ messages: [{ id: 's-2', role: 'scenario', scenario: scenarioCpi5 }] })

  const name = within(screen.getByRole('table')).getAllByRole('rowheader')[0]
  expect(name.querySelector('.scenario-lender .chip-lender')).toHaveTextContent('הצעה מבנק הפועלים')
  expect(name.querySelector('.scenario-track')).not.toBeNull()
  expect(name.getAttribute('title')).toMatch(/^ריבית קבועה 6.9%.*\nהצעה מבנק הפועלים/s)
})

test('a chart shows its title, its source and a table of every month', () => {
  renderChat({ messages: [{ id: 'c-3', role: 'chart', chart: cpiChart }] })

  const figure = screen.getByRole('figure', { name: /השינוי החודשי במדד המחירים לצרכן/ })
  expect(figure).toHaveTextContent('לפי נתוני הלשכה המרכזית לסטטיסטיקה, עד 09/2026')
  const rows = within(figure).getAllByRole('row')
  expect(rows).toHaveLength(4)
  expect(rows[3]).toHaveTextContent('09/2026-0.5%')
})

test('a multi-line sample keeps its line breaks in the input', async () => {
  renderChat({ messages: [] })
  await userEvent.click(screen.getByRole('button', { name: 'פריים ומדדים' }))

  const lines = (screen.getByRole('textbox') as HTMLTextAreaElement).value.split('\n')
  expect(lines).toHaveLength(2)
  expect(lines[1]).toBe('מה היו המדדים לצרכן ב-12 החודשים האחרונים? ')
})

test('the market sample stays after the first question and after a tap', async () => {
  const question: QuestionEntry = {
    id: 'q-2',
    role: 'question',
    question: { field: 'amount', text: null, choices: null },
    leadIn: null,
    answered: false,
  }
  renderChat({ messages: [...exchange, question], liveQuestionId: 'q-2' })
  await userEvent.click(screen.getByRole('button', { name: 'פריים ומדדים' }))
  expect(screen.getByRole('button', { name: 'פריים ומדדים' })).toBeInTheDocument()
})

test('an archived check ends with the manual archive line and no input', () => {
  render(
    <Chat
      {...noQuestion}
      messages={[...exchange, { id: 'x-3', role: 'archived', archive: checkArchived(3).data }]}
      turn="idle"
      failure={null}
      notice={null}
      onSend={vi.fn()}
    />,
  )

  const note = screen.getByRole('note')
  expect(note).toHaveTextContent('הבדיקה נסגרה והועברה לארכיון.')
  expect(note).toHaveTextContent('ב-14.11.2026 הבדיקה הועברה לארכיון ידנית.')
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
})

test('a cloned check ends with the handoff note, whose button opens the copy', async () => {
  const onOpenCheck = vi.fn()
  render(
    <Chat
      {...noQuestion}
      messages={[...exchange, { id: 'c-3', role: 'cloned', cloneId: 'copy' }]}
      turn="idle"
      failure={null}
      notice={null}
      onSend={vi.fn()}
      onOpenCheck={onOpenCheck}
    />,
  )

  expect(screen.getByRole('note')).toHaveTextContent('הבדיקה שוכפלה לבדיקה נפרדת.')
  await userEvent.click(screen.getByRole('button', { name: 'מעבר לבדיקה החדשה' }))
  expect(onOpenCheck).toHaveBeenCalledWith('copy')
})

/** The labels of the chips above the input, in their order. */
function chipLabels(): string[] {
  return [...document.querySelectorAll('.chat-samples button')].map((chip) => chip.textContent)
}

test('the samples chip shows with a loan and a term and no offer, and fills the input', async () => {
  const { onSend } = renderChat({ offersOpen: true, samplesOffered: true })
  expect(chipLabels()).toEqual(['דוגמאות', 'הצעה מגוף מלווה', 'פריים ומדדים'])
  await userEvent.click(screen.getByRole('button', { name: 'דוגמאות' }))

  expect(onSend).not.toHaveBeenCalled()
  expect(screen.getByRole('textbox')).toHaveValue(
    'אפשר לראות דוגמאות להלוואה כזו? פריים, ריבית קבועה לא צמודה, וריבית קבועה צמודה למדד כמו' +
      ' בהלוואה מקרן פנסיה או השתלמות ',
  )
  expect(screen.getByRole('textbox')).toHaveFocus()
})

test('no samples chip once an offer is saved or awaits', () => {
  renderChat({ offersOpen: true, samplesOffered: false })
  expect(chipLabels()).toEqual(['הצעה מגוף מלווה', 'פריים ומדדים'])
})

test('the terms chips show as offered and send their sentence at once', async () => {
  const { onSend } = renderChat({ offersOpen: true, termChips: { shorter: true, longer: true } })
  expect(chipLabels()).toEqual(['קיצור תקופה', 'הארכת תקופה', 'הצעה מגוף מלווה', 'פריים ומדדים'])
  await userEvent.click(screen.getByRole('button', { name: 'קיצור תקופה' }))

  expect(onSend).toHaveBeenCalledExactlyOnceWith(SHORTER_TERMS_CHIP.text)
})

test('only the terms chips the recommendation allows show', () => {
  renderChat({ offersOpen: true, termChips: { shorter: true, longer: false } })
  expect(chipLabels()).toEqual(['קיצור תקופה', 'הצעה מגוף מלווה', 'פריים ומדדים'])
})

test('the offer chip sends its sentence at once, which opens the empty offer form', async () => {
  const { onSend } = renderChat({ offersOpen: true })
  await userEvent.click(screen.getByRole('button', { name: 'הצעה מגוף מלווה' }))

  expect(onSend).toHaveBeenCalledExactlyOnceWith('קיבלתי הצעה להלוואה מגוף מלווה')
  expect(screen.getByRole('textbox')).toHaveValue('')
})

test('the market chip stays at every stage', () => {
  for (const stage of [{}, { offersOpen: true }, { offersOpen: true, samplesOffered: true }]) {
    const { unmount } = renderChat(stage)
    expect(chipLabels().at(-1)).toBe('פריים ומדדים')
    unmount()
  }
  renderChat({ messages: [] })
  expect(chipLabels()).toEqual(['פריים ומדדים'])
})

test('the market sample fills the input and waits for the person to send', async () => {
  const { onSend } = renderChat({ offersOpen: true })
  await userEvent.click(screen.getByRole('button', { name: 'פריים ומדדים' }))

  expect(onSend).not.toHaveBeenCalled()
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toContain('ריבית הפריים')
})

test('a message with ?? in it sends without asking', async () => {
  const { onSend } = renderChat()
  await userEvent.type(screen.getByRole('textbox'), 'פריים + ??%{Enter}')
  expect(onSend).toHaveBeenCalledWith('פריים + ??%')
})

test('a single question mark sends without asking', async () => {
  const { onSend } = renderChat()
  await userEvent.type(screen.getByRole('textbox'), 'כמה זה עולה?{Enter}')
  expect(onSend).toHaveBeenCalledWith('כמה זה עולה?')
})

test('a message and a question show when they were said; one without a time shows none', () => {
  const at = new Date(2026, 10, 14, 9, 30, 5).toISOString()
  const question: QuestionEntry = {
    id: 'q-3',
    role: 'question',
    question: { field: 'amount', text: null, choices: null },
    leadIn: null,
    answered: false,
    at,
  }
  renderChat({ messages: [{ ...exchange[0], at }, exchange[1], question] })

  const times = document.querySelectorAll('time.bubble-time')
  expect(times).toHaveLength(2)
  expect(times[0]).toHaveTextContent('14.11.2026 09:30:05')
  expect(times[0]).toHaveAttribute('datetime', at)
})

test('a readings card stays answerable after later messages', () => {
  renderChat({
    messages: [
      { id: 'r-a-1', role: 'readings', offer: awaitingAvis, settled: null, dropped: null },
      ...exchange,
    ],
  })
  const card = document.getElementById('awaiting-a-1')!
  for (const radio of within(card).getAllByRole('radio')) expect(radio).toBeEnabled()
  expect(within(card).getByRole('button', { name: 'אישור' })).toBeEnabled()
})

const IDENTIFIED =
  'an identified offer shows its short reply with the market chip, which fills the input'

test(IDENTIFIED, async () => {
  renderChat({ messages: [{ id: 'i-1', role: 'identified', offer: identifiedMax }] })
  const reply = screen.getByText(/זיהיתי שזו הלוואה/).closest('.bubble')!
  expect(reply).toHaveTextContent(
    'זיהיתי שזו הלוואה בריבית פריים + 6.45%. ריבית הפריים נכון ל-15.11.2026 היא 4.75%, כך' +
      ' שהריבית הכוללת היום היא 11.2% (4.75 + 6.45). ההחזר שמסרת, 934 ₪, תואם לחישוב הזה.',
  )
  await userEvent.click(within(reply as HTMLElement).getByRole('button', { name: 'פריים ומדדים' }))
  const input = screen.getByRole('textbox')
  expect(input).toHaveValue(`${MARKET_SAMPLE.text} `)
  expect(input).toHaveFocus()
})

test('an unrecognized offer shows what to ask the lender', () => {
  renderChat({ messages: [{ id: 'n-1', role: 'unrecognized', lender: 'מקס' }] })
  expect(
    screen.getByText(
      'לא זיהיתי את סוג ההלוואה. בקשו יותר פרטים - האם ההלוואה מבוססת פריים? ריבית קבועה צמודה' +
        ' למדד?',
    ),
  ).toHaveClass('bubble-assistant')
})

describe('a card the checks list asks to focus', () => {
  afterEach(restoreScrollIntoView)

  const readings: ChatEntry = {
    id: 'r-a-1',
    role: 'readings',
    offer: awaitingAvis,
    settled: null,
    dropped: null,
  }
  const message = (id: string): ChatMessage => ({ id, role: 'user', text: id, complete: true })
  const props = {
    ...noQuestion,
    turn: 'idle' as const,
    failure: null,
    notice: null,
    onSend: vi.fn(() => Promise.resolve(true)),
  }
  const entries = [...exchange, readings]
  const focus = { id: 'a-1', request: 1 }

  /** The log, sized so pinning it to the end sets its scrollTop to 1000. */
  function sizedLog(): HTMLElement {
    const log = document.querySelector<HTMLElement>('.chat-log')!
    Object.defineProperty(log, 'scrollHeight', { configurable: true, value: 1000 })
    Object.defineProperty(log, 'clientHeight', { configurable: true, value: 300 })
    return log
  }

  test('is centred and highlighted once, and stays in view while later entries arrive', () => {
    const scrolled = stubScrollIntoView()
    const { rerender } = render(<Chat {...props} messages={entries} focusAwaiting={focus} />)
    const card = document.getElementById('awaiting-a-1')!
    expect(scrolled).toHaveBeenCalledExactlyOnceWith({ block: 'center' })
    expect(scrolled.mock.contexts[0]).toBe(card)
    expect(card).toHaveClass('card-focus')
    expect(card).not.toHaveClass('attention-flash')

    const log = sizedLog()
    fireEvent.scroll(log)
    const later = [...entries, message('u-2')]
    rerender(<Chat {...props} messages={later} focusAwaiting={focus} />)
    rerender(<Chat {...props} messages={[...later, message('u-3')]} focusAwaiting={focus} />)
    expect(log.scrollTop).toBe(0)
    expect(scrolled).toHaveBeenCalledOnce()
  })

  test('lets the log follow the end again once the person scrolls', () => {
    stubScrollIntoView()
    const { rerender } = render(<Chat {...props} messages={entries} focusAwaiting={focus} />)
    const log = sizedLog()
    log.scrollTop = 50
    fireEvent.scroll(log)
    rerender(<Chat {...props} messages={[...entries, message('u-2')]} focusAwaiting={focus} />)
    expect(log.scrollTop).toBe(1000)
  })

  test('lets the log follow the end again once the person sends', async () => {
    stubScrollIntoView()
    const { rerender } = render(<Chat {...props} messages={entries} focusAwaiting={focus} />)
    const log = sizedLog()
    await userEvent.type(screen.getByRole('textbox'), 'שלום{Enter}')
    rerender(<Chat {...props} messages={[...entries, message('שלום')]} focusAwaiting={focus} />)
    expect(log.scrollTop).toBe(1000)
  })

  test('is focused again by a second request for the same card', () => {
    const scrolled = stubScrollIntoView()
    const { rerender } = render(<Chat {...props} messages={entries} focusAwaiting={focus} />)
    rerender(<Chat {...props} messages={entries} focusAwaiting={{ id: 'a-1', request: 2 }} />)
    expect(scrolled).toHaveBeenCalledTimes(2)
    expect(document.getElementById('awaiting-a-1')).toHaveClass('card-focus')
  })
})
