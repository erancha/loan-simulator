import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { sendMessage } from '../api/checks.ts'
import { ApiException, isRecord } from '../api/client.ts'
import type { ProfileUpdate } from '../api/types.ts'
import { ProfilePanel } from '../profile/ProfilePanel.tsx'
import { useProfileStore } from '../profile/profileStore.ts'
import type { ProfileKey } from '../profile/profileStore.ts'
import { buildCard } from './card.ts'
import { CardBoundary } from './CardBoundary.tsx'
import { CardResizer, useCardWidth } from './CardResizer.tsx'
import { Chat } from './Chat.tsx'
import type { PanelNote } from './Chat.tsx'
import {
  RECOMPUTE_BUTTON,
  RECOMPUTE_MESSAGE,
  STALE_BANNER,
  answerLine,
  capNotice,
  fieldLabel,
  panelNote,
  profileValueText,
  sendFailed,
} from './copy.ts'
import type { Answer } from './QuestionBubble.tsx'
import { RecommendationCard } from './RecommendationCard.tsx'
import { isArchived, isSettled, liveQuestion } from './events.ts'
import type { CheckState } from './events.ts'
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

/** A saved profile value as the conversation shows it; the panel never saves a null. */
function savedValueText(value: ProfileUpdate[ProfileKey]): string {
  if (value === null || value === undefined) {
    throw new Error(`a profile save without a value: ${JSON.stringify(value)}`)
  }
  return profileValueText(value)
}

/** Builds the card while rendering, inside the boundary, so a throw from buildCard is contained. */
function BuiltCard({ state }: { state: CheckState }) {
  return <RecommendationCard model={buildCard(state)} />
}

interface Props {
  checkId: string
  /** The check's recommendation was computed from a profile the person has since changed. */
  stale: boolean
  sidebar: ReactNode
  /** Which pane a narrow screen shows; wide screens show all three. */
  activePane: 'chat' | 'card' | 'side'
  /** The checks list may have changed: a turn this page started ended, or the profile was saved. */
  onChecksChanged: () => void
  /** Clones this check, sends the line to the copy and opens it. */
  onClone: (line: string) => Promise<void>
  onOpenCheck: (id: string) => void
}

/**
 * One check: the checks list and profile, the conversation, and the recommendation card, all fed
 * by the check's single event stream. A turn this page started that archived the check opens the
 * check its conversation went on in; opening an archived check later stays on it.
 */
export function CheckPage({
  checkId,
  stale,
  sidebar,
  activePane,
  onChecksChanged,
  onClone,
  onOpenCheck,
}: Props) {
  const { state } = useCheckEvents(checkId)
  const profileStore = useProfileStore(state.profileVersion)
  const [notice, setNotice] = useState<string | null>(null)
  const [recomputing, setRecomputing] = useState(false)
  // The turn count when this page's last accepted send started; null once that turn has ended.
  // Turns that end in a replay or that another tab started do not pass it.
  const awaitedAfter = useRef<number | null>(null)
  // Bumped on each accepted send, so the check below also runs for a turn that ended mid-POST.
  const [accepted, setAccepted] = useState(0)
  const [panelNotes, setPanelNotes] = useState<PanelNote[]>([])
  const nextNoteId = useRef(0)
  const live = liveQuestion(state)

  useEffect(() => {
    const after = awaitedAfter.current
    if (after === null || state.turnsEnded <= after) return
    awaitedAfter.current = null
    onChecksChanged()
  }, [accepted, state.turnsEnded, onChecksChanged])

  // Opening the new check refreshes the checks list itself, so the turn's end needs no refresh.
  useEffect(() => {
    if (state.continuedIn === null || awaitedAfter.current === null) return
    awaitedAfter.current = null
    onOpenCheck(state.continuedIn)
  }, [accepted, state.continuedIn, onOpenCheck])

  /** Resolves true when the server accepted the text; a 409 means a turn is already running. */
  async function send(text: string): Promise<boolean> {
    const turnsEndedBefore = state.turnsEnded
    try {
      await sendMessage(checkId, text)
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

  /** A profile answer is saved before its line is sent; a refused save propagates to the bubble. */
  async function answer({ line, update }: Answer): Promise<boolean> {
    if (update !== null) {
      await profileStore.save(update, 'chat')
      onChecksChanged()
    }
    return send(line)
  }

  /**
   * A panel save of the field the live question asks for answers that question; any other field,
   * or an answer the server refused, is noted in the conversation.
   */
  function onPanelSaved(update: ProfileUpdate) {
    // A reply still streaming may be dropped when its turn ends, so a note never follows one.
    const anchor = state.messages.findLast(isSettled)
    const afterEntryId = anchor === undefined ? null : anchor.id
    for (const key of Object.keys(update) as ProfileKey[]) {
      const label = fieldLabel(key)
      const value = savedValueText(update[key])
      const addNote = () => {
        nextNoteId.current += 1
        const note = { id: nextNoteId.current, afterEntryId, text: panelNote(label, value) }
        setPanelNotes((shown) => [...shown, note])
      }
      if (live?.question.field === key) {
        void send(answerLine(label, value)).then((sent) => {
          if (!sent) addNote()
        })
      } else {
        addNote()
      }
    }
    onChecksChanged()
  }

  async function recompute() {
    setRecomputing(true)
    try {
      await send(RECOMPUTE_MESSAGE)
    } finally {
      setRecomputing(false)
    }
  }

  const cardWidth = useCardWidth()

  return (
    <div className="check-page" data-active-pane={activePane} style={cardWidth.style}>
      <aside className="pane-side">
        {sidebar}
        <ProfilePanel store={profileStore} onSaved={onPanelSaved} />
      </aside>
      <section className="pane-chat">
        <Chat
          messages={state.messages}
          liveQuestionId={live === null ? null : live.id}
          profile={profileStore.view === null ? null : profileStore.view.profile}
          panelNotes={panelNotes}
          turn={state.turn}
          failure={state.failure}
          notice={notice}
          onSend={send}
          onAnswer={answer}
          onSkip={send}
          onClone={onClone}
          continuedIn={state.continuedIn}
          onOpenCheck={onOpenCheck}
          recommended={state.recommendation !== null}
        />
      </section>
      <section className="pane-card">
        {stale && !isArchived(state) && (
          <div className="stale-banner">
            <span>{STALE_BANNER}</span>
            <button
              type="button"
              disabled={state.turn === 'running' || recomputing}
              onClick={() => void recompute()}
            >
              {RECOMPUTE_BUTTON}
            </button>
            {notice !== null && <p className="chat-notice">{notice}</p>}
          </div>
        )}
        <CardBoundary>
          <BuiltCard state={state} />
        </CardBoundary>
      </section>
      <CardResizer width={cardWidth.width} resize={cardWidth.resize} />
    </div>
  )
}
