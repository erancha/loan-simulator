import { useState } from 'react'
import type { CSSProperties, KeyboardEvent, PointerEvent } from 'react'
import { RESIZE_CARD } from './copy.ts'

/** The card pane's width at rest, its narrowest; the page grid reads it from --card-width. */
export const MIN_CARD_WIDTH = 380
/** What the card may never take from the page: the sidebar and a readable chat. */
const RESERVED_WIDTH = 250 + 360
const STEP = 20
const STORAGE_KEY = 'card-width'

function stored(): number {
  const value = Number(localStorage.getItem(STORAGE_KEY))
  return Number.isFinite(value) && value > MIN_CARD_WIDTH ? value : MIN_CARD_WIDTH
}

/** The card pane's width, which the person widens by dragging its border toward the chat. */
export function useCardWidth() {
  const [width, setWidth] = useState(stored)
  const resize = (next: number, pageWidth: number) => {
    const clamped = Math.round(
      Math.min(
        Math.max(next, MIN_CARD_WIDTH),
        Math.max(pageWidth - RESERVED_WIDTH, MIN_CARD_WIDTH),
      ),
    )
    setWidth(clamped)
    localStorage.setItem(STORAGE_KEY, String(clamped))
  }
  const style = { '--card-width': `${width}px` } as CSSProperties
  return { width, resize, style }
}

interface Props {
  width: number
  resize: (next: number, pageWidth: number) => void
}

/**
 * The draggable border between the card pane, on the page's left, and the chat. Dragging right
 * widens the card; the arrow keys move it in steps for keyboard users.
 */
export function CardResizer({ width, resize }: Props) {
  const page = (element: Element) => (element.parentElement as HTMLElement).getBoundingClientRect()

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
    const bounds = page(event.currentTarget)
    resize(event.clientX - bounds.left, bounds.width)
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const delta = { ArrowRight: STEP, ArrowLeft: -STEP }[event.key]
    if (delta === undefined) return
    event.preventDefault()
    resize(width + delta, page(event.currentTarget).width)
  }

  return (
    <div
      className="card-resizer"
      role="separator"
      aria-orientation="vertical"
      aria-label={RESIZE_CARD}
      aria-valuenow={width}
      aria-valuemin={MIN_CARD_WIDTH}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onKeyDown={onKeyDown}
    />
  )
}
