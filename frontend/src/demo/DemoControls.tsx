import { useEffect, useState, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import { DEMO_PAUSE, DEMO_RESUME, DEMO_SPEED } from '../copy.ts'
import type { DemoClock, Rate } from './clock.ts'

const RATES: Rate[] = [1, 2]
// How often the shown time catches up with the clock while it runs.
const TICK_MS = 250
// How long the sign of a tap's pause or resume stays over the conversation.
const SIGN_MS = 600
// What already does something when tapped, so a tap on it is not a pause.
const CONTROLS = 'a, button, input, textarea, select, label, summary, [role="button"]'
// Where a space types or presses, so it is not a pause.
const TYPING = 'input, textarea, select, button, [contenteditable]'

function minutesAndSeconds(ms: number): string {
  const seconds = Math.floor(ms / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/** The demo time played over its total, as a video player shows them: "0:42 / 2:05". */
export function playbackTime(elapsedMs: number, totalMs: number): string {
  return `${minutesAndSeconds(Math.min(elapsedMs, totalMs))} / ${minutesAndSeconds(totalMs)}`
}

/**
 * The bar right under the app's header, the one place the page leaves for it: the shell lays out
 * its header and main as a column, so a bar placed between them takes its own row and covers
 * nothing. The app draws its header after it signs in, so the bar waits for it.
 */
function useBarUnderHeader(): HTMLElement {
  const [bar] = useState(() => {
    const element = document.createElement('div')
    element.className = 'demo-controls'
    return element
  })
  useEffect(() => {
    const place = () => {
      const header = document.querySelector('.shell-header')
      if (header !== null && header.nextElementSibling !== bar) header.after(bar)
    }
    place()
    const observer = new MutationObserver(place)
    observer.observe(document.body, { childList: true, subtree: true })
    return () => {
      observer.disconnect()
      bar.remove()
    }
  }, [bar])
  return bar
}

/** The sign a tap or the space bar leaves for a moment: the state it put the replay in, and the
 * point it shows at, the conversation's middle. */
interface Sign {
  paused: boolean
  x: number
  y: number
}

/**
 * Pause and resume without reaching for the bar, the way a video player takes them: a tap on the
 * conversation's surface, which on a phone is under the visitor's thumb, and on a computer the
 * space bar. A tap on anything that already does something (a button, a link, a box) keeps doing
 * that, and a scroll fires no tap. Each toggle shows a sign for a moment, since the conversation
 * itself does not change when it pauses.
 */
function useTapToPause(clock: DemoClock, ended: boolean): Sign | null {
  const [sign, setSign] = useState<Sign | null>(null)
  useEffect(() => {
    if (ended) return
    let hide: ReturnType<typeof setTimeout> | undefined
    const toggle = () => {
      if (clock.paused()) clock.resume()
      else clock.pause()
      const log = document.querySelector('.chat-log')
      const area =
        log === null
          ? { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight }
          : log.getBoundingClientRect()
      setSign({
        paused: clock.paused(),
        x: area.left + area.width / 2,
        y: area.top + area.height / 2,
      })
      clearTimeout(hide)
      hide = setTimeout(() => setSign(null), SIGN_MS)
    }
    const onClick = (event: MouseEvent) => {
      const target = event.target
      if (!(target instanceof Element) || target.closest('.chat-log') === null) return
      if (target.closest(CONTROLS) !== null) return
      const selection = window.getSelection()
      if (selection !== null && !selection.isCollapsed) return
      toggle()
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== ' ' || event.repeat) return
      if (event.target instanceof Element && event.target.closest(TYPING) !== null) return
      event.preventDefault()
      toggle()
    }
    document.addEventListener('click', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('click', onClick)
      document.removeEventListener('keydown', onKey)
      clearTimeout(hide)
    }
  }, [clock, ended])
  return sign
}

/**
 * The demo's playback bar: pause and resume, the speed (1× or 2×), and the time played of the
 * whole replay; a tap on the conversation and the space bar pause and resume too. Once the replay
 * ends, there is nothing left to hold, so pause is disabled and taps change nothing.
 */
export function DemoControls({
  clock,
  totalMs,
  replay,
}: {
  clock: DemoClock
  totalMs: number
  replay: Promise<void>
}) {
  const bar = useBarUnderHeader()
  const paused = useSyncExternalStore(clock.subscribe, clock.paused)
  const rate = useSyncExternalStore(clock.subscribe, clock.rate)
  const [elapsed, setElapsed] = useState(clock.elapsed())
  const [ended, setEnded] = useState(false)
  useEffect(() => {
    void replay.then(() => setEnded(true))
  }, [replay])
  useEffect(() => {
    const tick = setInterval(() => setElapsed(clock.elapsed()), TICK_MS)
    return () => clearInterval(tick)
  }, [clock])
  const sign = useTapToPause(clock, ended)
  return createPortal(
    <>
      {sign !== null &&
        createPortal(
          <div className="demo-flash" aria-hidden="true" style={{ left: sign.x, top: sign.y }}>
            {sign.paused ? '⏸' : '▶'}
          </div>,
          document.body,
        )}
      <button
        type="button"
        disabled={ended}
        onClick={() => (paused ? clock.resume() : clock.pause())}
      >
        <span aria-hidden="true">{paused ? '▶' : '⏸'}</span> {paused ? DEMO_RESUME : DEMO_PAUSE}
      </button>
      <span role="group" aria-label={DEMO_SPEED} className="demo-speed">
        {RATES.map((option) => (
          <button
            key={option}
            type="button"
            dir="ltr"
            aria-pressed={rate === option}
            onClick={() => clock.setRate(option)}
          >
            {option}×
          </button>
        ))}
      </span>
      {/* Digits and signs read left to right even on a right-to-left page, here and in the
          speeds. */}
      <span className="demo-time" dir="ltr">
        {playbackTime(ended ? totalMs : elapsed, totalMs)}
      </span>
    </>,
    bar,
  )
}
