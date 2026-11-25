import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent, ReactNode } from 'react'
import type { AwaitingOffer, Finances, MessageStatus, Question, Reading } from '../api/types.ts'
import {
  FEW_MESSAGES_LEFT, INPUT_LABEL, INPUT_PLACEHOLDER,
  questionText,
  CEILING_CHIP,
  LONGER_TERMS_CHIP,
  MARKET_SAMPLE,
  NO_OFFER_YET,
  OFFER_SAMPLE,
  SAMPLES_CHIP,
  SCENARIO_SAMPLE,
  SEND_BUTTON,
  SHORTER_TERMS_CHIP,
  TO_CARD,
  capNotice,
  cloneLine,
  messagesLeft,
  withLastMonth,
} from './copy.ts'
import { ArchiveNote } from './ArchiveNote.tsx'
import { CloneNote } from './CloneNote.tsx'
import { isArchived, isMessage } from './events.ts'
import type {
  ChatEntry,
  ChatMessage,
  CheckState,
  IdentifiedEntry,
  QuestionEntry,
  ReadingsEntry,
  UnrecognizedEntry,
} from './events.ts'
import { formatTimestamp } from '../money.ts'
import { withValues } from './emphasis.tsx'
import { MarketChart } from './MarketChart.tsx'
import { drawAttention, highlight } from './highlight.ts'
import { ScenarioTable } from './ScenarioTable.tsx'
import { IdentifiedBubble, UnrecognizedBubble } from './OfferReplies.tsx'
import { QuestionBubble } from './QuestionBubble.tsx'
import type { Answer } from './QuestionBubble.tsx'
import { ReadingsCard } from './ReadingsCard.tsx'
import { spokenLine } from './spokenLine.ts'
import { ThinkingBubble } from './ThinkingBubble.tsx'

/** How far from the end of the log (px) a reader still counts as following the conversation. */
const FOLLOW_DISTANCE = 80

/** A request of the checks list to bring an awaiting offer's card into view. `request` counts the
 * list's taps, so a second tap on the same link is a new request. */
export interface AwaitingFocus {
  id: string
  request: number
}

interface Props {
  messages: ChatEntry[]
  /** The question entry that still takes an answer; every other question shows as text. */
  liveQuestionId: string | null
  finances: Finances | null
  /** The payment ceiling the check holds; null while it has none. */
  ceiling: string | null
  /** How the ceiling was derived from the finances; null for a stated ceiling or none. */
  ceilingFormula: string | null
  turn: CheckState['turn']
  /** The running turn's steps so far, for the thinking bubble. */
  steps: CheckState['steps']
  /** When the running turn started, for the thinking bubble's seconds. */
  turnStartedAt: CheckState['turnStartedAt']
  failure: string | null
  /** Why the last send did not go through. */
  notice: string | null
  /** The person's standing against the message cap; null on a page with no cap. */
  messageStatus: MessageStatus | null
  /** Resolves true when the server accepted the text; the input then clears. */
  onSend: (text: string) => Promise<boolean>
  onAnswer: (answer: Answer) => Promise<boolean>
  onSkip: (line: string) => Promise<boolean>
  /** Clones the check and sends the line to the copy. */
  onClone: (line: string) => Promise<void>
  /** Opens another of the person's checks: the copy a handoff note names. */
  onOpenCheck: (id: string) => void
  /** Saves an awaiting offer by the reading the person confirmed on its card. */
  onConfirmReading: (awaitingId: string, reading: Reading) => Promise<void>
  /** The lender's answer to an offer quoted for less than the check's loan, given on its card. */
  onAnswerAmount: (offer: AwaitingOffer, covers: boolean, reading: Reading | null) => Promise<void>
  /** The check's loan amount, which an offer's card measures its quoted amount against. */
  loanAmount: string | null
  /** Asks for the offer form, to describe another offer while one waits on its lender. */
  onContinueOffers: () => Promise<boolean>
  /** The reply that presented the check's recommendation, which leads to the card's table of
   * figures; null when there is none. */
  cardReplyId: string | null
  /** Brings the card's table of figures into view, first showing the card's pane on a screen
   * that shows one pane at a time. */
  onShowCard: () => void
  /** Shows the recommendation card with the card of the option a lender's chip names. */
  onShowOption: (optionId: string) => void
  /** The card a new check opens with; while it is given, the chat shows it alone, with no input
   * and no chips. */
  opening: ReactNode | null
  /** The check has a loan and a term, so real offers can be brought. */
  offersOpen: boolean
  /** The check has a loan, a term, no option and no awaiting offer, so its examples can be
   * asked for. */
  samplesOffered: boolean
  /** The check holds an option, example or offer, so a scenario has something to price. */
  scenarioOffered: boolean
  /** The check has no ceiling yet, so the person may state one. */
  ceilingOffered: boolean
  /** The terms cards the chips offer, shorter and longer than the recommendation's term. */
  termChips: { shorter: boolean; longer: boolean }
  /** The awaiting offer whose card the checks list asked to bring into view. */
  focusAwaiting: AwaitingFocus | null
}

/** The person's last message before the entry at index: the request a question answers. */
function requestBefore(entries: ChatEntry[], index: number): string {
  const request = entries
    .slice(0, index)
    .findLast((entry): entry is ChatMessage => entry.role === 'user')
  if (request === undefined) throw new Error('a question is asked after a message of the person')
  return request.text
}

/** The latest question above the entry at index, which a person's answer line names. */
function askedBefore(entries: ChatEntry[], index: number): Question | null {
  const asked = entries
    .slice(0, index)
    .findLast((entry): entry is QuestionEntry => entry.role === 'question')
  return asked === undefined ? null : asked.question
}

type OfferReply = ReadingsEntry | IdentifiedEntry | UnrecognizedEntry

function isOfferReply(entry: ChatEntry): entry is OfferReply {
  return entry.role === 'readings' || entry.role === 'identified' || entry.role === 'unrecognized'
}

/** The chips a phone's width holds on one line; the row never wraps to a second. */
const CHIPS_PER_LINE = 5

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
 * The person's standing against the message cap. While a message is left: the count, emphasized
 * when few are left, with the time a used message frees. Once none is left: the time the next
 * one frees.
 */
function MessageStatusLine({ status }: { status: MessageStatus }) {
  // The moment the line's wording (today, tomorrow or a date) is measured from; the line is keyed
  // by the time it names, so each new time is worded from when it arrived.
  const [shownAt] = useState(() => new Date())
  const next = status.next_free === null ? null : new Date(status.next_free)
  if (status.left === 0) {
    if (next === null) throw new Error('no message left, with no time the next one frees')
    return (
      <p className="chat-message-status out" role="status">
        {capNotice(next, shownAt)}
      </p>
    )
  }
  const few = status.left <= FEW_MESSAGES_LEFT
  return (
    <p className={few ? 'chat-message-status low' : 'chat-message-status'}>
      {messagesLeft(status.left, status.limit, next, shownAt)}
    </p>
  )
}

/**
 * The conversation of a check: its bubbles, question bubbles and the cards and replies of the
 * offers the person described, each with the time it was said, and the chips, the message input
 * and the person's message status under it, which an archived check does not have. Under the reply that presented the check's
 * recommendation a link leads to the recommendation's pane. A new check shows its opening card
 * alone until the card is sent. A request of the checks list scrolls an awaiting offer's card
 * into view and holds it there until the person scrolls or sends.
 */
export function Chat({
  messages: entries,
  liveQuestionId,
  finances,
  ceiling,
  ceilingFormula,
  turn,
  steps,
  turnStartedAt,
  failure,
  notice,
  messageStatus,
  onSend,
  onAnswer,
  onSkip,
  onClone,
  onOpenCheck,
  onConfirmReading,
  onAnswerAmount,
  loanAmount,
  onContinueOffers,
  opening,
  offersOpen,
  samplesOffered,
  scenarioOffered,
  ceilingOffered,
  termChips,
  focusAwaiting,
  cardReplyId,
  onShowCard,
  onShowOption,
}: Props) {
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  // The date the replies' term lines count the loan's last month from, taken as the chat opens.
  const [today] = useState(() => new Date())
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
  // Typed text always reaches the model, so the box locks once no message is left; the chips and
  // cards code answers cost none and stay usable.
  const noMessageLeft = messageStatus !== null && messageStatus.left === 0
  const boxLocked = locked || noMessageLeft
  const archived = isArchived({ messages: entries })
  const liveEntry = entries.find((entry) => entry.id === liveQuestionId)
  // A waiting offer form is the one step on screen: a chip that starts another step would leave
  // the person between the form and a different request in the chat box. Market data is worth
  // asking at any point and costs no model call, so that chip stays.
  const offerFormWaits = liveEntry?.role === 'question' && liveEntry.question.kind === 'offer'
  const stepsOffered = !offerFormWaits
  const stepChips = [
    ...(stepsOffered && samplesOffered ? [SAMPLES_CHIP] : []),
    ...(stepsOffered && termChips.shorter ? [SHORTER_TERMS_CHIP] : []),
    ...(stepsOffered && termChips.longer ? [LONGER_TERMS_CHIP] : []),
    ...(stepsOffered && offersOpen ? [OFFER_SAMPLE] : []),
    ...(stepsOffered && scenarioOffered ? [SCENARIO_SAMPLE] : []),
    ...(stepsOffered && ceilingOffered ? [CEILING_CHIP] : []),
  ]
  // The market chip is the one to give way on a full line: the person can still ask for market
  // data in the chat.
  const samples = stepChips.length < CHIPS_PER_LINE ? [...stepChips, MARKET_SAMPLE] : stepChips
  const input = useRef<HTMLTextAreaElement>(null)
  const samplesChip = useRef<HTMLButtonElement>(null)
  const offerChip = useRef<HTMLButtonElement>(null)
  // The chat box grows with its text, from its two rows up to the stylesheet's cap of five. Its
  // height resets first, so a shorter text shrinks it back; the borders are its offset height
  // beyond its client height. Before paint, so the box never shows at the wrong size.
  useLayoutEffect(() => {
    const box = input.current
    if (box === null) return
    box.style.height = 'auto'
    box.style.height = `${box.scrollHeight + box.offsetHeight - box.clientHeight}px`
  }, [draft])
  const log = useRef<HTMLDivElement>(null)
  const following = useRef(true)
  // The log's scrollTop as last set by the code or seen in a scroll event. A scroll event arrives
  // after later renders have grown the log, so only a lower scrollTop means the person scrolled up.
  const lastTop = useRef(0)
  // True while a card the checks list focused is held in view: a new entry then leaves the log
  // where it is. The person's own scroll or send releases it.
  const held = useRef(false)
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
    if (held.current) return
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

  // Each request of the checks list focuses its card once, as soon as the replay has drawn it,
  // and holds it in view while the rest of the replay arrives.
  const focused = useRef<AwaitingFocus | null>(null)
  useEffect(() => {
    if (focusAwaiting === null || focused.current === focusAwaiting) return
    const card = document.getElementById(`awaiting-${focusAwaiting.id}`)
    if (card === null) return
    focused.current = focusAwaiting
    held.current = true
    following.current = false
    card.scrollIntoView({ block: 'center' })
    highlight(card)
    if (log.current !== null) lastTop.current = log.current.scrollTop
  }, [focusAwaiting, entries.length])

  /** Puts a sample in the input for the person to send or extend; the trailing space invites
   * them to type on after it. */
  function fillInput(text: string) {
    setDraft(`${text} `)
    if (input.current === null) throw new Error('the input renders with the samples')
    input.current.focus()
  }

  const fillMarketSample = () => fillInput(MARKET_SAMPLE.text)

  // True from the offer form's no-offer choice until the chips it points to show; a send that
  // does not go through leaves the form waiting and clears it.
  const pointing = useRef(false)

  /** The offer form's no-offer button: the choice shows as the person's line, which nothing
   * answers and which closes the form. */
  function declineOfferForm() {
    pointing.current = true
    void onSkip(NO_OFFER_YET).then((sent) => {
      if (!sent) pointing.current = false
    })
  }

  // Once the declined form has closed and the chips are back, an arc sweeps the edges of the two
  // ways forward, the examples chip and the offer chip, so the person decides which to take. The
  // form offers the no-offer button only while the examples are offered, and the offer chip
  // shows whenever they are.
  useEffect(() => {
    if (!pointing.current || offerFormWaits) return
    pointing.current = false
    for (const chip of [samplesChip.current, offerChip.current]) {
      if (chip === null) throw new Error('the examples and offer chips are not both shown')
      drawAttention(chip)
    }
  }, [offerFormWaits])
  // A card or a reply takes no answer while a turn runs or once the check is archived.
  const answerable = !running && !archived

  function trackFollowing() {
    const element = log.current
    if (element === null) return
    // A scroll event that leaves scrollTop where the code put it is the code's own scroll.
    if (held.current && element.scrollTop === lastTop.current) return
    held.current = false
    const atEnd = element.scrollHeight - element.scrollTop - element.clientHeight <= FOLLOW_DISTANCE
    if (atEnd) following.current = true
    else if (element.scrollTop < lastTop.current) following.current = false
    lastTop.current = element.scrollTop
  }

  /** Resolves true when the text was sent. */
  async function deliver(text: string): Promise<boolean> {
    held.current = false
    setSending(true)
    try {
      return await onSend(text)
    } finally {
      setSending(false)
    }
  }

  /** A chip that sends at once starts a step of its own, so a sentence another chip left in the
   * chat box no longer applies and clears once the chip's sentence is accepted. */
  async function sendChip(text: string) {
    if (await deliver(text)) setDraft('')
  }

  async function submit() {
    const text = draft.trim()
    if (text === '' || boxLocked) return
    if (await deliver(text)) setDraft('')
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
          {opening !== null && <li className="chat-turn">{opening}</li>}
          {entries.map((entry, index) => (
            <li key={entry.id} className="chat-turn">
              {entry.role === 'question' ? (
                <QuestionBubble
                  entry={entry}
                  live={entry.id === liveQuestionId}
                  finances={finances}
                  ceiling={ceiling}
                  ceilingFormula={ceilingFormula}
                  onAnswer={onAnswer}
                  onSkip={onSkip}
                  onNoOffer={samplesOffered ? declineOfferForm : null}
                  onClone={() => onClone(cloneLine(requestBefore(entries, index)))}
                />
              ) : entry.role === 'chart' ? (
                <MarketChart chart={entry.chart} />
              ) : entry.role === 'scenario' ? (
                <ScenarioTable scenario={entry.scenario} onShowOption={onShowOption} />
              ) : entry.role === 'archived' ? (
                <ArchiveNote archive={entry.archive} />
              ) : entry.role === 'cloned' ? (
                <CloneNote cloneId={entry.cloneId} onOpenCheck={onOpenCheck} />
              ) : entry.role === 'readings' ? (
                <ReadingsCard
                  entry={entry}
                  loanAmount={loanAmount}
                  live={answerable}
                  onConfirm={(reading) => onConfirmReading(entry.offer.awaiting_id, reading)}
                  onAnswerAmount={(covers, reading) => onAnswerAmount(entry.offer, covers, reading)}
                  onContinue={onContinueOffers}
                  onMarketChip={fillMarketSample}
                />
              ) : entry.role === 'identified' ? (
                <IdentifiedBubble
                  offer={entry.offer}
                  live={answerable}
                  onMarketChip={fillMarketSample}
                />
              ) : entry.role === 'unrecognized' ? (
                <UnrecognizedBubble />
              ) : (
                <p className={`bubble bubble-${entry.role}`}>
                  {entry.role === 'assistant'
                    ? withValues(withLastMonth(entry.text, today))
                    : spokenLine(entry.text, askedBefore(entries, index))}
                  {!entry.complete && <span className="caret" aria-hidden="true" />}
                </p>
              )}
              {entry.id === cardReplyId && (
                <button type="button" className="underline-link to-card" onClick={onShowCard}>
                  {TO_CARD}
                </button>
              )}
              {(entry.role === 'question' || isOfferReply(entry)) && (
                <EntryTime at={entry.at} side="assistant" />
              )}
              {isMessage(entry) && <EntryTime at={entry.at} side={entry.role} />}
            </li>
          ))}
          {running && !streaming && (
            <li className="chat-turn">
              <ThinkingBubble steps={steps} startedAt={turnStartedAt} />
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
      {!archived && opening === null && (
        <div className="chat-samples">
          {samples.map((sample) => (
            <button
              key={sample.label}
              ref={
                sample === SAMPLES_CHIP ? samplesChip : sample === OFFER_SAMPLE ? offerChip : undefined
              }
              type="button"
              className="sample-chip"
              disabled={locked}
              onClick={() => {
                if ('sendsAtOnce' in sample) void sendChip(sample.text)
                else fillInput(sample.text)
              }}
            >
              {sample.label}
            </button>
          ))}
        </div>
      )}
      {!archived && opening === null && (
        <form className="chat-input" onSubmit={onSubmit}>
          <div className="chat-input-box">
            <textarea
            ref={input}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onKeyDown}
            aria-label={INPUT_LABEL}
            placeholder={running ? INPUT_PLACEHOLDER.running : INPUT_PLACEHOLDER.idle}
            disabled={boxLocked}
            rows={2}
            />
          </div>
          <button type="submit" disabled={boxLocked || draft.trim() === ''}>
            {SEND_BUTTON}
          </button>
        </form>
      )}
      {notice !== null && <p className="chat-notice" role="status">{notice}</p>}
      {!archived && opening === null && messageStatus !== null && (
        <MessageStatusLine key={messageStatus.next_free} status={messageStatus} />
      )}
    </div>
  )
}
