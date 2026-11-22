import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { stepsHint, thinkingLine } from './copy.ts'
import { ThinkingBubble } from './ThinkingBubble.tsx'

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

afterEach(() => {
  vi.useRealTimers()
})

const bubble = () => document.querySelector('.bubble-thinking')!

test('without a start time the bubble counts from its appearance and names the step', () => {
  render(<ThinkingBubble steps={[{ step: 1, tools: [] }]} startedAt={null} />)
  expect(bubble()).toHaveTextContent(/^העוזר חושב \(שלב 1\)/)

  act(() => vi.advanceTimersByTime(99_000))
  expect(bubble()).toHaveTextContent(/^העוזר חושב, 99 שניות \(שלב 1\)/)
})

test("the seconds count from the turn's start, so a bubble shown again keeps its time", () => {
  const startedAt = new Date(Date.now() - 95_000).toISOString()
  render(<ThinkingBubble steps={[{ step: 1, tools: [] }]} startedAt={startedAt} />)
  expect(bubble()).toHaveTextContent(/^העוזר חושב, 95 שניות \(שלב 1\)/)

  act(() => vi.advanceTimersByTime(4_000))
  expect(bubble()).toHaveTextContent(/^העוזר חושב, 99 שניות/)
})

test('a step that chose tools says what they do', () => {
  const steps = [
    { step: 1, tools: [] },
    { step: 2, tools: ['set_loan', 'save_offer'] },
  ]
  render(<ThinkingBubble steps={steps} startedAt={null} />)
  expect(bubble()).toHaveTextContent(/^העוזר שומר את סכום ההלוואה, מחשב את ההצעה \(שלב 2\)/)
})

test('the hint says what a step is and lists the turn\'s steps', async () => {
  const steps = [
    { step: 1, tools: ['set_loan'] },
    { step: 2, tools: [] },
  ]
  render(<ThinkingBubble steps={steps} startedAt={null} />)
  await userEvent.click(screen.getByRole('button'))
  const hint = screen.getByRole('tooltip')
  expect(hint).toHaveClass('open')
  expect(hint).toHaveTextContent('כל שלב הוא סבב אחד של העוזר')
  expect(hint).toHaveTextContent('בתור הזה: שלב 1: שומר את סכום ההלוואה; שלב 2: חושב.')
})

test('a tool with no activity text shows as thinking and is logged', () => {
  const logged = vi.spyOn(console, 'error').mockImplementation(() => {})
  render(<ThinkingBubble steps={[{ step: 3, tools: ['new_tool'] }]} startedAt={null} />)
  expect(bubble()).toHaveTextContent(/^העוזר חושב \(שלב 3\)/)
  expect(logged).toHaveBeenCalled()
  logged.mockRestore()
})

test('the line reads one second, then seconds; before any step it has no step', () => {
  expect(thinkingLine([], null, 0)).toBe('העוזר חושב')
  expect(thinkingLine([], 1, 1)).toBe('העוזר חושב, שנייה אחת (שלב 1)')
  expect(thinkingLine(['מכין את ההמלצה'], 4, 135)).toBe('העוזר מכין את ההמלצה, 135 שניות (שלב 4)')
  expect(stepsHint([])).not.toContain('בתור הזה')
})
