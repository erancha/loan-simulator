/**
 * Switches the phone-width pane with a sideways swipe, in the tab bar's order and around it:
 * the checks list, the conversation, the recommendation, then the checks list again.
 *
 * A swipe counts only while the tab bar shows, so a wide screen with all three columns ignores
 * it. Scrolling wins over switching: a mostly vertical move, and any move that starts inside
 * something that scrolls sideways (a scenario's table) or inside a text field, is left to the
 * browser, as is a move that starts at a screen edge, where the phone has its own back gesture. A
 * swipe passes over a pane whose tab is disabled.
 */
import { useRef, type TouchEvent } from 'react'
import { TABS } from './copy.ts'
import type { Pane } from './TabBar.tsx'

/** How far a finger travels sideways before the move is a swipe, in CSS pixels. */
const MIN_DISTANCE = 60
/** The strip at each side of the screen left to the phone's back gesture, in CSS pixels. */
const EDGE = 24
/** A swipe travels at least this many times further sideways than up or down. */
const SIDEWAYS_RATIO = 2

function nextPane(pane: Pane, step: 1 | -1, disabled: readonly Pane[]): Pane {
  let index = TABS.findIndex((tab) => tab.pane === pane)
  do {
    index = (index + step + TABS.length) % TABS.length
  } while (disabled.includes(TABS[index].pane))
  return TABS[index].pane
}

function tabBarShown(root: Element): boolean {
  const bar = root.querySelector('.tab-bar')
  if (bar === null) throw new Error('the swipe area holds no tab bar')
  return getComputedStyle(bar).display !== 'none'
}

function scrollsSideways(target: Element, root: Element): boolean {
  let node: Element | null = target
  for (; node !== null && node !== root; node = node.parentElement) {
    const { overflowX } = getComputedStyle(node)
    if ((overflowX === 'auto' || overflowX === 'scroll') && node.scrollWidth > node.clientWidth) {
      return true
    }
  }
  return false
}

export function useTabSwipe(
  pane: Pane,
  onChange: (pane: Pane) => void,
  disabled: readonly Pane[],
) {
  const start = useRef<{ x: number; y: number } | null>(null)

  function onTouchStart(event: TouchEvent<HTMLElement>) {
    start.current = null
    if (event.touches.length !== 1) return
    const { clientX: x, clientY: y } = event.touches[0]
    const root = event.currentTarget
    const target = event.target as Element
    if (!tabBarShown(root) || x < EDGE || x > window.innerWidth - EDGE) return
    if (target.closest('input, textarea, select') !== null || scrollsSideways(target, root)) return
    start.current = { x, y }
  }

  function onTouchEnd(event: TouchEvent<HTMLElement>) {
    const from = start.current
    start.current = null
    if (from === null) return
    const { clientX, clientY } = event.changedTouches[0]
    const dx = clientX - from.x
    const dy = clientY - from.y
    if (Math.abs(dx) < MIN_DISTANCE || Math.abs(dx) < SIDEWAYS_RATIO * Math.abs(dy)) return
    // The page reads right to left, so a finger moving right brings in the next tab, from the left.
    onChange(nextPane(pane, dx > 0 ? 1 : -1, disabled))
  }

  return {
    onTouchStart,
    onTouchEnd,
    onTouchCancel: () => {
      start.current = null
    },
  }
}
