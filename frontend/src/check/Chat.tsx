import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import type { ProfileFields } from '../api/types.ts'
import {
  CHAT_WELCOME,
  INPUT_LABEL, INPUT_PLACEHOLDER,
  questionText,
  MARKET_SAMPLE,
  SAMPLE_MESSAGES,
  SEND_BUTTON,
  THINKING,
} from './copy.ts'
import { isMessage } from './events.ts'
import type { ChatEntry, CheckState } from './events.ts'
import { marketSampleTappedToday, rememberMarketSampleTapped } from './dailySample.ts'
import { withBold } from './emphasis.tsx'
import { MarketChart } from './MarketChart.tsx'
import { QuestionBubble } from './QuestionBubble.tsx'
import type { Answer } from './QuestionBubble.tsx'

/** A panel edit, shown in this tab's conversation after the entry it follows. */
export interface PanelNote {
  id: number
  /** The last stored entry when the edit was saved; null when the conversation was empty. */
  afterEntryId: string | null
  text: string
}

/** How far from the end of the log (px) a reader still counts as following the conversation. */
const FOLLOW_DISTANCE = 80

interface Props {
  messages: ChatEntry[]
  /** The question entry that still takes an answer; every other question shows as text. */
  liveQuestionId: string | null
  profile: ProfileFields | null
  panelNotes: PanelNote[]
  turn: CheckState['turn']
  failure: string | null
  /** Why the last send did not go through. */
  notice: string | null
  /** Resolves true when the server accepted the text; the input then clears. */
  onSend: (text: string) => Promise<boolean>
  onAnswer: (answer: Answer) => Promise<boolean>
  onSkip: (line: string) => Promise<boolean>
}

function PanelNoteLines({ notes, after }: { notes: PanelNote[]; after: string | null }) {
  return notes
    .filter((note) => note.afterEntryId === after)
    .map((note) => (
      <p key={note.id} className="panel-note-line">
        {note.text}
      </p>
    ))
}

/**
 * The conversation of a check: its bubbles and question bubbles, what each turn saved, the
 * profile edits made beside it, and the message input.
 */
export function Chat({
  messages: entries,
  liveQuestionId,
  profile,
  panelNotes,
  turn,
  failure,
  notice,
  onSend,
  onAnswer,
  onSkip,
}: Props) {
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const running = turn === 'running'
  const messages = entries.filter(isMessage)
  const last = messages.at(-1)
  const streaming = last?.role === 'assistant' && !last.complete
  const lastEntry = entries.at(-1)
  const lastReply = messages.findLast((m) => m.role === 'assistant' && m.complete)
  // Announced instead of the log, so a screen reader reads each reply once, when it is complete,
  // and a question that ends the conversation by its lead-in and label.
  let announcement = lastReply === undefined ? '' : lastReply.text
  if (lastEntry?.role === 'question') {
    const text = questionText(lastEntry.question)
    announcement = lastEntry.leadIn === null ? text : `${lastEntry.leadIn} ${text}`
  }
  const locked = running || sending
  const [marketTapped, setMarketTapped] = useState(marketSampleTappedToday)
  // The opening samples help start a conversation, so they go once the model asks its first
  // question; market data is worth asking at any point, so that sample stays until tapped.
  const opening = !entries.some((entry) => entry.role === 'question')
  const samples = [...(opening ? SAMPLE_MESSAGES : []), ...(marketTapped ? [] : [MARKET_SAMPLE])]
  const input = useRef<HTMLTextAreaElement>(null)
  const log = useRef<HTMLDivElement>(null)
  const following = useRef(true)
  // The log's scrollTop as last set by the code or seen in a scroll event. A scroll event arrives
  // after later renders have grown the log, so only a lower scrollTop means the person scrolled up.
  const lastTop = useRef(0)
  const lastLength = last?.text.length

  function pinToEnd() {
    const element = log.current
    if (element === null || !following.current) return
    element.scrollTop = element.scrollHeight
    lastTop.current = element.scrollTop
  }

  useEffect(pinToEnd, [
    entries.length,
    lastLength,
    panelNotes.length,
    liveQuestionId,
    failure,
    notice,
  ])

  // Content that grows without a new message (a web font swapping in, a resized window or
  // textarea) re-pins the log; the inner list holds all the content, so one node covers it.
  useEffect(() => {
    const element = log.current
    if (element === null) return
    const observer = new ResizeObserver(pinToEnd)
    observer.observe(element)
    if (element.firstElementChild !== null) observer.observe(element.firstElementChild)
    return () => observer.disconnect()
  }, [])

  function trackFollowing() {
    const element = log.current
    if (element === null) return
    const atEnd = element.scrollHeight - element.scrollTop - element.clientHeight <= FOLLOW_DISTANCE
    if (atEnd) following.current = true
    else if (element.scrollTop < lastTop.current) following.current = false
    lastTop.current = element.scrollTop
  }

  async function submit() {
    const text = draft.trim()
    if (text === '' || locked) return
    setSending(true)
    try {
      if (await onSend(text)) setDraft('')
    } finally {
      setSending(false)
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    void submit()
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter' || event.shiftKey) return
    event.preventDefault()
    void submit()
  }

  return (
    <div className="chat">
      <div className="chat-log" ref={log} onScroll={trackFollowing}>
        <ol className="chat-messages">
          <li className="chat-turn">
            <p className="bubble bubble-assistant chat-welcome">{CHAT_WELCOME}</p>
            <PanelNoteLines notes={panelNotes} after={null} />
          </li>
          {entries.map((entry) => (
            <li key={entry.id} className="chat-turn">
              {entry.role === 'question' ? (
                <QuestionBubble
                  entry={entry}
                  live={entry.id === liveQuestionId}
                  profile={profile}
                  onAnswer={onAnswer}
                  onSkip={onSkip}
                />
              ) : entry.role === 'chart' ? (
                <MarketChart chart={entry.chart} />
              ) : (
                <p className={`bubble bubble-${entry.role}`}>
                  {entry.role === 'assistant' ? withBold(entry.text) : entry.text}
                  {!entry.complete && <span className="caret" aria-hidden="true" />}
                </p>
              )}
              <PanelNoteLines notes={panelNotes} after={entry.id} />
            </li>
          ))}
          {running && !streaming && (
            <li className="chat-turn">
              <p className="bubble bubble-thinking">{THINKING}</p>
            </li>
          )}
        </ol>
      </div>
      <p className="visually-hidden" aria-live="polite">
        {announcement}
      </p>
      {failure !== null && (
        <p className="chat-failure" role="alert">
          {failure}
        </p>
      )}
      {samples.length > 0 && (
        <div className="chat-samples">
          {samples.map((sample) => (
            <button
              key={sample.label}
              type="button"
              disabled={locked}
              onClick={() => {
                // The trailing space invites the person to type on after the sample.
                setDraft(`${sample.text} `)
                if (input.current === null) throw new Error('the input renders with the samples')
                input.current.focus()
                if (sample === MARKET_SAMPLE) {
                  rememberMarketSampleTapped()
                  setMarketTapped(true)
                }
              }}
            >
              {sample.label}
            </button>
          ))}
        </div>
      )}
      <form className="chat-input" onSubmit={onSubmit}>
        <textarea
          ref={input}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          aria-label={INPUT_LABEL}
          placeholder={running ? INPUT_PLACEHOLDER.running : INPUT_PLACEHOLDER.idle}
          disabled={locked}
          rows={2}
        />
        <button type="submit" disabled={locked || draft.trim() === ''}>
          {SEND_BUTTON}
        </button>
      </form>
      {notice !== null && <p className="chat-notice" role="status">{notice}</p>}
    </div>
  )
}
