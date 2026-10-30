import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, test } from 'vitest'
import { CardResizer, MIN_CARD_WIDTH, useCardWidth } from './CardResizer.tsx'

function Page() {
  const card = useCardWidth()
  return (
    <div data-testid="page" style={card.style}>
      <CardResizer width={card.width} resize={card.resize} />
    </div>
  )
}

function renderPage(pageWidth: number) {
  render(<Page />)
  const page = screen.getByTestId('page')
  page.getBoundingClientRect = () => ({ left: 0, width: pageWidth }) as DOMRect
  return { page, border: screen.getByRole('separator', { name: 'שינוי רוחב חלונית ההמלצה' }) }
}

beforeEach(() => localStorage.clear())

test('the arrow keys widen and narrow the card, never below its resting width', () => {
  const { page, border } = renderPage(1600)

  fireEvent.keyDown(border, { key: 'ArrowRight' })
  expect(page.style.getPropertyValue('--card-width')).toBe(`${MIN_CARD_WIDTH + 20}px`)
  fireEvent.keyDown(border, { key: 'ArrowLeft' })
  fireEvent.keyDown(border, { key: 'ArrowLeft' })
  expect(page.style.getPropertyValue('--card-width')).toBe(`${MIN_CARD_WIDTH}px`)
})

test('the card never takes the room the sidebar and the chat need', () => {
  const { page, border } = renderPage(1200)

  for (let i = 0; i < 40; i++) fireEvent.keyDown(border, { key: 'ArrowRight' })
  expect(page.style.getPropertyValue('--card-width')).toBe(`${1200 - 250 - 360}px`)
})

test('the chosen width is kept for the next visit', () => {
  const { border } = renderPage(1600)
  fireEvent.keyDown(border, { key: 'ArrowRight' })

  expect(localStorage.getItem('card-width')).toBe(String(MIN_CARD_WIDTH + 20))
})
