import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  saveFinances,
  saveTerm,
  sendMarketSample,
  sendOfferSample,
  sendMessage,
  sendTermCeiling,
} from '../api/checks.ts'
import { ApiException, isRecord } from '../api/client.ts'
import { buildCard } from './card.ts'
import { CardBoundary } from './CardBoundary.tsx'
import { CardResizer, useCardWidth } from './CardResizer.tsx'
import { Chat } from './Chat.tsx'
import { capNotice, sendFailed } from './copy.ts'
import { FinancesPanel, hasFinances } from './FinancesPanel.tsx'
import { termConfirmation, typedTerm } from './QuestionBubble.tsx'
import type { Answer } from './QuestionBubble.tsx'
import { RecommendationCard } from './RecommendationCard.tsx'
import { isArchived, liveQuestion } from './events.ts'
import type { CheckState } from './events.ts'
import type { CheckSummary } from '../api/types.ts'
import { isMarketSample, isOfferSample } from './serverSamples.ts'
import { useCheckEvents } from './useCheckEvents.ts'

/** A 429's detail carries the ISO time the next message is allowed. */
function nextAllowed(detail: unknown): Date {
  if (!isRecord(detail) || typeof detail.next_allowed !== 'string') {
    throw new Error(`a 429 without next_allowed: ${JSON.stringify(detail)}`)
  }
  return new Date(detail.next_allowed)
}

/** The notice for a refused send; anything that is not an Error propagates. */
function sendFailureText(error: unknown): string {
  if (error instanceof ApiException && error.status === 429) {
    return capNotice(nextAllowed(error.detail), new Date())
  }
  if (error instanceof Error) return sendFailed(error.message)
  throw error
}

/** Builds the card while rendering, inside the boundary, so a throw from buildCard is contained. */
function BuiltCard({ state }: { state: CheckState }) {
  return <RecommendationCard model={buildCard(state)} />
}

/**
 * Whether the checks list shows the check as its own events do: its loan, its term and whether it
 * has a recommendation. They differ after a turn this page did not start, such as the first turn
 * of a clone, which the page that cloned it sends.
 */
function listedAsShown(listed: CheckSummary, state: CheckState): boolean {
  return (
    listed.loan?.amount === state.loan?.amount &&
    listed.term_months === state.termMonths &&
    (listed.recommendation === null) === (state.recommendation === null)
  )
}

interface Props {
  checkId: string
  /** The check as the checks list shows it. */
  listed: CheckSummary
  sidebar: ReactNode
  /** Which pane a narrow screen shows; wide screens show all three. */
  activePane: 'chat' | 'card' | 'side'
  /** The checks list may have changed: a turn this page started ended, or figures were saved. */
  onChecksChanged: () => void
  /** Clones this check, sends the line to the copy and opens it. */
  onClone: (line: string) => Promise<void>
  /** Opens another of the person's checks. */
  onOpenCheck: (id: string) => void
}

/**
 * One check: the checks list, the conversation, and the recommendation card, all fed by the
 * check's single event stream.
 */
export function CheckPage({
  checkId,
  listed,
  sidebar,
  activePane,
  onChecksChanged,
  onClone,
  onOpenCheck,
}: Props) {
  const { state } = useCheckEvents(checkId)
  const [notice, setNotice] = useState<string | null>(null)
  // The turn count when this page's last accepted send started; null once that turn has ended.
  // Turns that end in a replay or that another tab started do not pass it.
  const awaitedAfter = useRef<number | null>(null)
  // Bumped on each accepted send, so the check below also runs for a turn that ended mid-POST.
  const [accepted, setAccepted] = useState(0)
  const live = liveQuestion(state)

  useEffect(() => {
    const after = awaitedAfter.current
    if (after === null || state.turnsEnded <= after) return
    awaitedAfter.current = null
    onChecksChanged()
  }, [accepted, state.turnsEnded, onChecksChanged])

  // Once the stream has events and no turn runs, a list that shows the check otherwise is stale.
  const stale = state.lastSeq > 0 && state.turn === 'idle' && !listedAsShown(listed, state)
  useEffect(() => {
    if (stale) onChecksChanged()
  }, [stale, onChecksChanged])

  /** Resolves true when the server accepted the text; a 409 means a turn is already running. */
  function send(text: string): Promise<boolean> {
    // The offer form needs the check's loan, so before one the sentence goes to the model, which
    // asks for the loan.
    const request = isMarketSample(text)
      ? sendMarketSample
      : isOfferSample(text) && state.loan !== null
        ? sendOfferSample
        : sendMessage
    return deliver(() => request(checkId, text))
  }

  /** Runs a request that starts a turn, with a send's notices and its wait for the turn's end. */
  async function deliver(request: () => Promise<void>): Promise<boolean> {
    const turnsEndedBefore = state.turnsEnded
    try {
      await request()
    } catch (error) {
      if (!(error instanceof ApiException && error.status === 409)) {
        setNotice(sendFailureText(error))
      }
      return false
    }
    setNotice(null)
    awaitedAfter.current = turnsEndedBefore
    setAccepted((count) => count + 1)
    return true
  }

  /**
   * A finances answer, from a bubble or the data panel, or a confirmed term with any ceiling
   * typed beside it is saved before its line is sent; a refused save propagates to the control
   * that asked. A new ceiling alone from the term card goes with its line in one request, which
   * the server answers with a new card.
   */
  async function answer(given: Answer): Promise<boolean> {
    if ('term' in given) {
      await saveTerm(checkId, given.term, given.ceiling)
    } else if ('ceiling' in given) {
      return deliver(() => sendTermCeiling(checkId, given.line, given.ceiling))
    } else if (given.update !== null) {
      await saveFinances(checkId, given.update)
      onChecksChanged()
    }
    return send(given.line)
  }

  /** Typed text that names the open term card's own term confirms it, as its button does. */
  async function sendTyped(text: string): Promise<boolean> {
    const card = live?.question.kind === 'term' ? live.question : null
    if (card === null || typedTerm(text) !== card.term_months) return send(text)
    try {
      return await answer(termConfirmation(card.term_months, null))
    } catch (error) {
      setNotice(sendFailureText(error))
      return false
    }
  }

  const cardWidth = useCardWidth()

  return (
    <div className="check-page" data-active-pane={activePane} style={cardWidth.style}>
      <aside className="pane-side">
        {sidebar}
      </aside>
      <section className="pane-chat">
        {hasFinances(state.finances) && (
          <FinancesPanel
            finances={state.finances}
            ceiling={state.ceiling}
            readOnly={state.turn === 'running' || isArchived(state)}
            onAnswer={answer}
          />
        )}
        <div className="pane-chat-body">
          <Chat
            messages={state.messages}
            liveQuestionId={live === null ? null : live.id}
            finances={state.finances}
            ceiling={state.ceiling === null ? null : state.ceiling.amount}
            turn={state.turn}
            failure={state.failure}
            notice={notice}
            onSend={sendTyped}
            onAnswer={answer}
            onSkip={send}
            onClone={onClone}
            onOpenCheck={onOpenCheck}
            recommended={state.recommendation !== null}
          />
        </div>
      </section>
      <section className="pane-card">
        <CardBoundary>
          <BuiltCard state={state} />
        </CardBoundary>
      </section>
      <CardResizer width={cardWidth.width} resize={cardWidth.resize} />
    </div>
  )
}
