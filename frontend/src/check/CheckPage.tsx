import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  answerAmount,
  confirmReading,
  saveFinances,
  saveTerm,
  sendMarketSample,
  sendMessage,
  sendUnanswered,
  sendOfferSample,
  sendOpening,
  sendTermCeiling,
  sendTermConfirmation,
} from '../api/checks.ts'
import { ApiException } from '../api/client.ts'
import { buildCard } from './card.ts'
import { CardBoundary } from './CardBoundary.tsx'
import { CardResizer, useCardWidth } from './CardResizer.tsx'
import { Chat } from './Chat.tsx'
import type { AwaitingFocus } from './Chat.tsx'
import {
  amountCoveredLine,
  amountDeclinedLine,
  ceilingFormula,
  CONTINUE_TO_ANOTHER_OFFER,
  confirmedReadingLine,
  NO_OFFER_YET,
  openingLine,
  questionLabel,
  sendFailed,
  skipLine,
} from './copy.ts'
import { FinancesPanel, hasFinancialDetails } from './FinancesPanel.tsx'
import { OpeningCard } from './OpeningCard.tsx'
import { termConfirmation, typedTerm } from './QuestionBubble.tsx'
import { isRefusal } from './rejection.ts'
import type { Answer } from './QuestionBubble.tsx'
import { RecommendationCard, revealFigures, revealOption } from './RecommendationCard.tsx'
import {
  holdsOption,
  isArchived,
  liveQuestion,
  recommendationReplyId,
  termComparisons,
} from './events.ts'
import type { CheckState } from './events.ts'
import type { AwaitingOffer, CheckSummary, MessageStatus, Reading } from '../api/types.ts'
import { isMarketSample, isOfferSample } from './serverSamples.ts'
import { useCheckEvents } from './useCheckEvents.ts'

/** The notice for a refused send; anything that is not an Error propagates. */
function sendFailureText(error: unknown): string {
  if (error instanceof Error) return sendFailed(error.message)
  throw error
}

function isStatus(error: unknown, status: number): boolean {
  return error instanceof ApiException && error.status === status
}

/** Builds the card while rendering, inside the boundary, so a throw from buildCard is contained. */
function BuiltCard({ state }: { state: CheckState }) {
  return <RecommendationCard model={buildCard(state)} />
}

function ceilingAmountOf(state: CheckState): string | null {
  return state.ceiling === null ? null : state.ceiling.amount
}

/**
 * Whether the checks list shows the check as its own events do: its loan, its term, whether it
 * has a recommendation or financial details, and how many offers await their lender. They differ
 * after a turn this page did not start, such as the first turn of a clone, which the page that
 * cloned it sends.
 */
function listedAsShown(listed: CheckSummary, state: CheckState): boolean {
  return (
    listed.loan?.amount === state.loan?.amount &&
    listed.term_months === state.termMonths &&
    (listed.recommendation === null) === (state.recommendation === null) &&
    listed.has_finances === hasFinancialDetails(state.finances, ceilingAmountOf(state)) &&
    listed.awaiting_offers.length === state.awaiting.size
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
  /** The awaiting offer whose card to bring into view: the checks list's link that opened it. */
  focusAwaiting: AwaitingFocus | null
  /** The person asked for the finances line with the checks list's finances link. */
  showFinances: boolean
  /** Told whenever the term card starts or stops taking an answer. */
  onTermCardLive: (live: boolean) => void
  /** Told whether the check holds an option or an offer awaiting its lender: until it does, the
   * recommendation pane has nothing to show. */
  onCardReady: (ready: boolean) => void
  /** Shows the recommendation's pane, on a screen that shows one pane at a time; the reply that
   * presents a recommendation links to its table of figures. */
  onShowCard: () => void
  /** The person's standing against the message cap; null on a page with no cap. */
  messages: MessageStatus | null
  /** A send was accepted or refused over the cap, so the message status may have changed. */
  onMessagesChanged: () => void
}

/**
 * One check: the checks list, the conversation, and the recommendation card, all fed by the
 * check's single event stream. A check nobody has written to opens on its opening card alone. The
 * finances line above the conversation shows the check's figures only while the person asks for
 * it with the checks list's finances link, and never while the term card takes an answer: the
 * card holds the ceiling then, and the line's edit would change it from a second place.
 */
export function CheckPage({
  checkId,
  listed,
  sidebar,
  activePane,
  onChecksChanged,
  onClone,
  onOpenCheck,
  focusAwaiting,
  showFinances,
  onTermCardLive,
  onCardReady,
  onShowCard,
  messages,
  onMessagesChanged,
}: Props) {
  const { state } = useCheckEvents(checkId)
  const [notice, setNotice] = useState<string | null>(null)
  // The turn count when this page's last accepted send started; null once that turn has ended.
  // Turns that end in a replay or that another tab started do not pass it.
  const awaitedAfter = useRef<number | null>(null)
  // Bumped on each accepted send, so the check below also runs for a turn that ended mid-POST.
  const [accepted, setAccepted] = useState(0)
  const live = liveQuestion(state)
  const ceilingAmount = ceilingAmountOf(state)
  const termCardLive = live !== null && live.question.kind === 'term'

  useEffect(() => onTermCardLive(termCardLive), [termCardLive, onTermCardLive])
  const cardReady = holdsOption(state)
  useEffect(() => onCardReady(cardReady), [cardReady, onCardReady])

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

  /** A line nothing answers: the skip of a live ceiling question, or the live offer form's
   * no-offer choice. The server stores it with no reply, and the person goes on as they choose. */
  function isUnanswered(text: string): boolean {
    if (live === null) return false
    const { question } = live
    if (question.kind === 'offer') return text === NO_OFFER_YET
    if (question.kind !== undefined) return false
    return question.field === 'payment_ceiling' && text === skipLine(questionLabel(question))
  }

  /** Resolves true when the server accepted the text; a 409 means a turn is already running. */
  function send(text: string): Promise<boolean> {
    // The offer form needs the check's loan, so before one the sentence goes to the model, which
    // asks for the loan.
    const request = isMarketSample(text)
      ? sendMarketSample
      : isOfferSample(text) && state.loan !== null
        ? sendOfferSample
        : isUnanswered(text)
          ? sendUnanswered
          : sendMessage
    return deliver(() => request(checkId, text))
  }

  /**
   * Runs a request that starts a turn, with a send's notices and its wait for the turn's end. An
   * error `propagates` accepts is rethrown to the control that asked, with no notice. A send the
   * cap refused (429) shows no notice either: the message status, asked for again, says it.
   */
  async function deliver(
    request: () => Promise<void>,
    propagates: (error: unknown) => boolean = () => false,
  ): Promise<boolean> {
    const turnsEndedBefore = state.turnsEnded
    try {
      await request()
    } catch (error) {
      if (propagates(error)) throw error
      if (isStatus(error, 429)) onMessagesChanged()
      else if (!isStatus(error, 409)) setNotice(sendFailureText(error))
      return false
    }
    onMessagesChanged()
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
      return deliver(() => sendTermConfirmation(checkId, given.line))
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

  /** A reading confirmed on an offer's card is saved, then sent as its line; a refused save
   * propagates to the card. */
  async function confirmOfferReading(awaitingId: string, reading: Reading): Promise<void> {
    await confirmReading(checkId, awaitingId, reading.kind)
    await deliver(() => sendMessage(checkId, confirmedReadingLine(reading)))
  }

  /** The lender's answer on the loan amount of an offer quoted for less: the offer is saved at
   * the loan amount or dropped, then sent as its line; a refused answer propagates to the card. */
  async function answerOfferAmount(
    offer: AwaitingOffer,
    covers: boolean,
    reading: Reading | null,
  ): Promise<void> {
    if (state.loan === null) throw new Error('an offer awaits its lender on a check with no loan')
    const loan = state.loan.amount
    await answerAmount(checkId, offer.awaiting_id, covers, reading === null ? null : reading.kind)
    const line =
      reading === null
        ? amountDeclinedLine(offer.lender, loan)
        : amountCoveredLine(offer.lender, loan, reading)
    await deliver(() => sendMessage(checkId, line))
  }

  /** The opening card's loan; resolves true when it was sent, and a refused one rejects to the
   * card. */
  function submitOpening(purpose: string, amount: string): Promise<boolean> {
    const text = openingLine(purpose, amount)
    return deliver(() => sendOpening(checkId, text, purpose, amount), isRefusal)
  }

  /** The server answers this line with the offer form, for another offer. */
  function continueOffers(): Promise<boolean> {
    return deliver(() => sendOfferSample(checkId, CONTINUE_TO_ANOTHER_OFFER))
  }

  const cardWidth = useCardWidth()
  const fresh = !listed.started && state.messages.length === 0
  const offersOpen = state.loan !== null && state.termMonths !== null

  return (
    <div className="check-page" data-active-pane={activePane} style={cardWidth.style}>
      <aside className="pane-side">
        {sidebar}
      </aside>
      <section className="pane-chat">
        {showFinances && !termCardLive && hasFinancialDetails(state.finances, ceilingAmount) && (
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
            ceiling={ceilingAmount}
            ceilingFormula={
              state.ceiling === null || state.ceiling.basis === null
                ? null
                : ceilingFormula(state.ceiling.basis, state.finances)
            }
            turn={state.turn}
            steps={state.steps}
            turnStartedAt={state.turnStartedAt}
            failure={state.failure}
            notice={notice}
            messageStatus={messages}
            onSend={sendTyped}
            onAnswer={answer}
            onSkip={send}
            onClone={onClone}
            onOpenCheck={onOpenCheck}
            onConfirmReading={confirmOfferReading}
            onAnswerAmount={answerOfferAmount}
            loanAmount={state.loan === null ? null : state.loan.amount}
            onContinueOffers={continueOffers}
            cardReplyId={recommendationReplyId(state)}
            onShowCard={() => {
              onShowCard()
              revealFigures()
            }}
            onShowOption={(optionId) => {
              onShowCard()
              revealOption(optionId)
            }}
            opening={fresh ? <OpeningCard onSubmit={submitOpening} /> : null}
            offersOpen={offersOpen}
            samplesOffered={offersOpen && !holdsOption(state)}
            scenarioOffered={state.options.size > 0}
            ceilingOffered={state.ceiling === null}
            termChips={termComparisons(state)}
            focusAwaiting={focusAwaiting}
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
