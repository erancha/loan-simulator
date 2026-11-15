import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import type { Finances } from '../api/types.ts'
import {
  CHAT_WELCOME,
  INPUT_LABEL, INPUT_PLACEHOLDER,
  questionText,
  MARKET_SAMPLE,
  OFFER_SAMPLE,
  PLACEHOLDER,
  PLACEHOLDER_CANCEL,
  PLACEHOLDER_CONFIRM,
  PLACEHOLDER_QUESTION,
  SAMPLE_MESSAGES,
  SEND_BUTTON,
  THINKING,
  cloneLine,
} from './copy.ts'
import { ArchiveNote } from './ArchiveNote.tsx'
import { CloneNote } from './CloneNote.tsx'
import { isArchived, isMessage } from './events.ts'
import type { ChatEntry, ChatMessage, CheckState } from './events.ts'
import { formatTimestamp } from '../money.ts'
import { withBold } from './emphasis.tsx'
import { MarketChart } from './MarketChart.tsx'
import { QuestionBubble } from './QuestionBubble.tsx'
import type { Answer } from './QuestionBubble.tsx'

/** How far from the end of the log (px) a reader still counts as following the conversation. */
const FOLLOW_DISTANCE = 80

interface Props {
  messages: ChatEntry[]
  /** The question entry that still takes an answer; every other question shows as text. */
  liveQuestionId: string | null
  finances: Finances | null
  /** The payment ceiling the check holds; null while it has none. */
  ceiling: string | null
  turn: CheckState['turn']
  failure: string | null
  /** Why the last send did not go through. */
  notice: string | null
  /** Resolves true when the server accepted the text; the input then clears. */
  onSend: (text: string) => Promise<boolean>
  onAnswer: (answer: Answer) => Promise<boolean>
  onSkip: (line: string) => Promise<boolean>
  /** Clones the check and sends the line to the copy. */
  onClone: (line: string) => Promise<void>
  /** Opens another of the person's checks: the copy a handoff note names. */
  onOpenCheck: (id: string) => void
  /** The check has a recommendation, so the next step is bringing real offers. */
  recommended: boolean
}

/** The person's last message before the entry at index: the request a question answers. */
function requestBefore(entries: ChatEntry[], index: number): string {
  const request = entries
    .slice(0, index)
    .findLast((entry): entry is ChatMessage => entry.role === 'user')
  if (request === undefined) throw new Error('a question is asked after a message of the person')
  return request.text
}

/** When an entry was said, under its bubble on the bubble's side. */
function EntryTime({ at, side }: { at: string | undefined; side: 'user' | 'assistant' }) {
  if (at === undefined) return null
  return (
    <time className={`bubble-time bubble-time-${side}`} dateTime={at}>
      {formatTimestamp(at)}
    </time>
  )
}

/**
 * The conversation of a check: its bubbles and question bubbles, each with the time it was
 * said, and the message input, which an archived check does not have.
 */
export function Chat({
  messages: entries,
  liveQuestionId,
  finances,
  ceiling,
  turn,
  failure,
  notice,
  onSend,
  onAnswer,
  onSkip,
  onClone,
  onOpenCheck,
  recommended,
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
  const archived = isArchived({ messages: entries })
  // The opening samples help start a conversation, so they go once the model asks its first
  // question; once there is a recommendation, the offer sample shows how to bring a real offer.
  // Market data is worth asking at any point and costs no model call, so that sample stays.
  const opening = !recommended && !entries.some((entry) => entry.role === 'question')
  const samples = [
    ...(opening ? SAMPLE_MESSAGES : []),
    ...(recommended ? [OFFER_SAMPLE] : []),
    MARKET_SAMPLE,
  ]
  // A check with no message yet leads the eye to where to start: the input's edge, then the
  // samples' (the border-sweep classes in global.css).
  const fresh = entries.length === 0
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

  // A new entry is what the reader is waiting for, so it brings the end back into view even
  // after they scrolled up; text streaming into an entry leaves a reader who scrolled up in place.
  useEffect(() => {
    following.current = true
    pinToEnd()
  }, [entries.length])

  useEffect(pinToEnd, [
    lastLength,
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

  // A sample's ?? marks a figure the person was to fill in, so a message still holding one asks
  // before it goes.
  const [confirmingPlaceholder, setConfirmingPlaceholder] = useState(false)

  async function submit(confirmed = false) {
    const text = draft.trim()
    if (text === '' || locked) return
    if (!confirmed && text.includes(PLACEHOLDER)) {
      setConfirmingPlaceholder(true)
      return
    }
    setConfirmingPlaceholder(false)
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
            <p className="bubble bubble-assistant chat-welcome">{withBold(CHAT_WELCOME)}</p>
          </li>
          {entries.map((entry, index) => (
            <li key={entry.id} className="chat-turn">
              {entry.role === 'question' ? (
                <QuestionBubble
                  entry={entry}
                  live={entry.id === liveQuestionId}
                  finances={finances}
                  ceiling={ceiling}
                  onAnswer={onAnswer}
                  onSkip={onSkip}
                  onClone={() => onClone(cloneLine(requestBefore(entries, index)))}
                />
              ) : entry.role === 'chart' ? (
                <MarketChart chart={entry.chart} />
              ) : entry.role === 'archived' ? (
                <ArchiveNote archive={entry.archive} />
              ) : entry.role === 'cloned' ? (
                <CloneNote cloneId={entry.cloneId} onOpenCheck={onOpenCheck} />
              ) : (
                <p className={`bubble bubble-${entry.role}`}>
                  {entry.role === 'assistant' ? withBold(entry.text) : entry.text}
                  {!entry.complete && <span className="caret" aria-hidden="true" />}
                </p>
              )}
              {entry.role === 'question' && <EntryTime at={entry.at} side="assistant" />}
              {isMessage(entry) && <EntryTime at={entry.at} side={entry.role} />}
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
      {!archived && samples.length > 0 && (
        <div className="chat-samples">
          {samples.map((sample) => (
            <button
              key={sample.label}
              type="button"
              className={fresh ? 'border-sweep sweep-after-input' : undefined}
              disabled={locked}
              onClick={() => {
                // The trailing space invites the person to type on after the sample.
                setDraft(`${sample.text} `)
                if (input.current === null) throw new Error('the input renders with the samples')
                input.current.focus()
              }}
            >
              {sample.label}
            </button>
          ))}
        </div>
      )}
      {!archived && (
        <form className="chat-input" onSubmit={onSubmit}>
          {/* A textarea draws no ::before, so the sweep runs on this wrapper of the same shape. */}
          <div className={fresh ? 'chat-input-box border-sweep' : 'chat-input-box'}>
            <textarea
            ref={input}
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value)
              setConfirmingPlaceholder(false)
            }}
            onKeyDown={onKeyDown}
            aria-label={INPUT_LABEL}
            placeholder={running ? INPUT_PLACEHOLDER.running : INPUT_PLACEHOLDER.idle}
            disabled={locked}
            rows={2}
            />
          </div>
          <button type="submit" disabled={locked || draft.trim() === ''}>
            {SEND_BUTTON}
          </button>
        </form>
      )}
      {confirmingPlaceholder && (
        <div className="check-confirm">
          <p>{PLACEHOLDER_QUESTION}</p>
          <button type="button" className="primary" onClick={() => void submit(true)}>
            {PLACEHOLDER_CONFIRM}
          </button>
          <button
            type="button"
            onClick={() => {
              setConfirmingPlaceholder(false)
              if (input.current === null) throw new Error('the input renders with the prompt')
              input.current.focus()
            }}
          >
            {PLACEHOLDER_CANCEL}
          </button>
        </div>
      )}
      {notice !== null && <p className="chat-notice" role="status">{notice}</p>}
    </div>
  )
}
