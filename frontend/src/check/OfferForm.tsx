import { type FormEvent, useState } from 'react'
import type { OfferTrackDraft, Question } from '../api/types.ts'
import {
  CONTINUE,
  OFFER_ADD_TRACK,
  OFFER_FIX_ABOVE,
  OFFER_FORM_INTRO,
  OFFER_KIND_LABEL,
  OFFER_LENDER_LABEL,
  OFFER_LENDER_MISSING,
  OFFER_LINKED,
  OFFER_MAX_MONTHS,
  OFFER_MAX_RATE,
  OFFER_MAX_TRACKS,
  OFFER_MONTHS_INVALID,
  OFFER_MONTHS_LABEL,
  OFFER_MONTHS_UNIT,
  OFFER_NOTE,
  OFFER_REMOVE_TRACK,
  OFFER_TRACK_REPEATED,
  OFFER_TRACKS_LABEL,
  type OfferKind,
  type OfferTrack,
  offerKindBox,
  offerLine,
  offerRateBox,
  offerRateInvalid,
  questionText,
  SKIP,
  TERM_MIN_MONTHS,
} from './copy.ts'
import type { QuestionEntry } from './events.ts'
import type { Answer } from './QuestionBubble.tsx'
import { rejectionText } from './rejection.ts'

/** A track row as typed: the percentage is free text until the form is sent. */
interface Row {
  /** Stable across added and removed rows, so each row keeps its boxes. */
  key: number
  kind: OfferKind
  rate: string
  /** Only a fixed-interest track can be linked to the index; false on a prime row. */
  linked: boolean
}

const EMPTY_ROW = { kind: 'prime_plus', rate: '', linked: false } as const

/**
 * A track the person already described, as a row: a margin under prime shows unsigned, and a
 * prime track is never linked to the index, whatever was passed.
 */
function rowOf(track: OfferTrackDraft): Omit<Row, 'key'> {
  const rate = track.rate ?? ''
  if (track.rate_kind === 'fixed') return { kind: 'fixed', rate, linked: track.cpi_linked }
  return rate.startsWith('-')
    ? { kind: 'prime_minus', rate: rate.slice(1), linked: false }
    : { kind: 'prime_plus', rate, linked: false }
}

/**
 * The percentage in a box, "3,5 %" read as "3.5" and a stray separator at either end dropped, as a
 * phone's keyboard leaves one; null when it is no percent the engine prices for the row's kind.
 */
function typedRate(kind: OfferKind, text: string): string | null {
  const rate = text
    .replace(/[\s%]/g, '')
    .replace(',', '.')
    .replace(/^[.,]+|[.,]+$/g, '')
  return /^\d+(\.\d+)?$/.test(rate) && Number(rate) <= OFFER_MAX_RATE[kind] ? rate : null
}

/**
 * A prime row's box as typed: "-0.5", as offers write a margin under prime, sets the row to prime
 * minus and keeps the box unsigned. A fixed rate keeps its sign, which typedRate refuses.
 */
function typedRow(kind: OfferKind, text: string): Partial<Row> {
  const unsigned = text.replace(/^\s*[-−]/, '')
  return kind === 'fixed' || unsigned === text
    ? { rate: text }
    : { kind: 'prime_minus', rate: unsigned }
}

/**
 * Whether a row offers the same track as an earlier one: the same kind, percentage and linkage,
 * "1.2" and "1.20" being one percentage. A lender's tracks are alternatives, so a repeat adds none.
 */
function repeatsAnEarlierRow(rows: Row[], rates: (string | null)[], index: number): boolean {
  const rate = rates[index]
  if (rate === null) return false
  return rows
    .slice(0, index)
    .some(
      (earlier, at) =>
        earlier.kind === rows[index].kind &&
        earlier.linked === rows[index].linked &&
        rates[at] !== null &&
        Number(rates[at]) === Number(rate),
    )
}

/** The whole number of months in a box; null when it is none an offer can allow. */
function typedMonths(text: string): number | null {
  const months = text.trim()
  if (!/^\d+$/.test(months)) return null
  const count = Number(months)
  return count >= TERM_MIN_MONTHS && count <= OFFER_MAX_MONTHS ? count : null
}

interface Props {
  entry: QuestionEntry
  question: Extract<Question, { kind: 'offer' }>
  /** Only a live form shows its boxes; an answered one keeps its title as text. */
  live: boolean
  /** Resolves false when nothing was sent; rejects with an ApiException on a refused send. */
  onAnswer: (answer: Answer) => Promise<boolean>
  /** Sends a line alone, saving nothing; the skip button's way to leave the form unfilled. */
  onSkip: (line: string) => Promise<boolean>
}

/**
 * A lender's offer as a form: who the lender is, one row per track offered (its kind, its
 * percentage and, for fixed interest, whether it is linked to the index), and the longest period.
 * The boxes start with what the person already said. Sending marks every box that is empty or out
 * of range and sends nothing; a valid form goes as one worded message, which the model saves the
 * offer from. A skip button leaves the form unfilled, sending its own line and saving nothing.
 */
export function OfferForm({ entry, question, live, onAnswer, onSkip }: Props) {
  const [lender, setLender] = useState(question.lender ?? '')
  const [rows, setRows] = useState<Row[]>(() =>
    (question.tracks.length > 0 ? question.tracks.map(rowOf) : [EMPTY_ROW]).map((row, key) => ({
      ...row,
      key,
    })),
  )
  const [nextKey, setNextKey] = useState(rows.length)
  const [months, setMonths] = useState(
    question.max_term_months === null ? '' : String(question.max_term_months),
  )
  // The boxes are judged once the person tries to send, not while they are still typing.
  const [tried, setTried] = useState(false)
  const [rejection, setRejection] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const named = lender.trim()
  const rates = rows.map((row) => typedRate(row.kind, row.rate))
  const repeated = rows.map((_row, index) => repeatsAnEarlierRow(rows, rates, index))
  const period = typedMonths(months)
  const refused =
    named === '' || rates.includes(null) || repeated.includes(true) || period === null

  function change(key: number, update: Partial<Row>) {
    setRows(rows.map((row) => (row.key === key ? { ...row, ...update } : row)))
  }

  function addRow() {
    setRows([...rows, { ...EMPTY_ROW, key: nextKey }])
    setNextKey(nextKey + 1)
  }

  async function skip() {
    setBusy(true)
    try {
      await onSkip(SKIP)
    } finally {
      setBusy(false)
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setTried(true)
    const tracks: OfferTrack[] = []
    rows.forEach((row, index) => {
      const rate = rates[index]
      if (rate !== null) tracks.push({ kind: row.kind, rate, linked: row.linked })
    })
    if (refused) return
    setRejection(null)
    setBusy(true)
    try {
      await onAnswer({ line: offerLine(named, tracks, period), update: null })
    } catch (caught) {
      setRejection(rejectionText(caught))
    } finally {
      setBusy(false)
    }
  }

  const lenderId = `${entry.id}-lender`
  const monthsId = `${entry.id}-months`
  return (
    <div className="bubble bubble-assistant bubble-question">
      <p className="question-label">{questionText(question)}</p>
      {live && <p className="card-note">{OFFER_FORM_INTRO}</p>}
      {live && (
        <form className="offer-form" noValidate onSubmit={(event) => void submit(event)}>
          <label htmlFor={lenderId}>{OFFER_LENDER_LABEL}</label>
          <input
            id={lenderId}
            type="text"
            value={lender}
            onChange={(event) => setLender(event.target.value)}
          />
          {tried && named === '' && <p className="field-error">{OFFER_LENDER_MISSING}</p>}

          <span className="offer-group question-label">{OFFER_TRACKS_LABEL}</span>
          {rows.map((row, index) => (
            <div key={row.key}>
              <div className="offer-track">
                <select
                  aria-label={offerKindBox(index + 1)}
                  value={row.kind}
                  onChange={(event) => {
                    const kind = event.target.value as OfferKind
                    change(row.key, { kind, linked: kind === 'fixed' && row.linked })
                  }}
                >
                  {Object.entries(OFFER_KIND_LABEL).map(([kind, label]) => (
                    <option key={kind} value={kind}>
                      {label}
                    </option>
                  ))}
                </select>
                <span className="field-input offer-rate">
                  <input
                    type="text"
                    inputMode="decimal"
                    dir="ltr"
                    aria-label={offerRateBox(index + 1)}
                    value={row.rate}
                    onChange={(event) => change(row.key, typedRow(row.kind, event.target.value))}
                  />
                  <span className="unit">%</span>
                </span>
                {row.kind === 'fixed' && (
                  <label className="offer-linked">
                    <input
                      type="checkbox"
                      checked={row.linked}
                      onChange={(event) => change(row.key, { linked: event.target.checked })}
                    />
                    {OFFER_LINKED}
                  </label>
                )}
                {rows.length > 1 && (
                  <button
                    type="button"
                    className="link-button"
                    aria-label={OFFER_REMOVE_TRACK}
                    onClick={() => setRows(rows.filter((other) => other.key !== row.key))}
                  >
                    ✕
                  </button>
                )}
              </div>
              {tried && rates[index] === null && (
                <p className="field-error">{offerRateInvalid(row.kind)}</p>
              )}
              {tried && repeated[index] && <p className="field-error">{OFFER_TRACK_REPEATED}</p>}
            </div>
          ))}
          {rows.length < OFFER_MAX_TRACKS && (
            <button type="button" className="link-button" onClick={addRow}>
              {OFFER_ADD_TRACK}
            </button>
          )}

          <label className="offer-group" htmlFor={monthsId}>
            {OFFER_MONTHS_LABEL}
          </label>
          <span className="field-input offer-months">
            <input
              id={monthsId}
              type="text"
              inputMode="numeric"
              dir="ltr"
              value={months}
              onChange={(event) => setMonths(event.target.value)}
            />
            <span className="unit">{OFFER_MONTHS_UNIT}</span>
          </span>
          {tried && period === null && <p className="field-error">{OFFER_MONTHS_INVALID}</p>}

          {tried && refused && <p className="field-error">{OFFER_FIX_ABOVE}</p>}
          {rejection !== null && <p className="field-error">{rejection}</p>}
          <div className="question-actions">
            <button type="submit" className="primary" disabled={busy}>
              {CONTINUE}
            </button>
            <button type="button" disabled={busy} onClick={() => void skip()}>
              {SKIP}
            </button>
          </div>
          <p className="offer-note">{OFFER_NOTE}</p>
        </form>
      )}
    </div>
  )
}
