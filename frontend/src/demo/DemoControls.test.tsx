import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { createDemoClock } from './clock.ts'
import { DemoControls, playbackTime } from './DemoControls.tsx'

afterEach(() => {
  vi.useRealTimers()
  // React unmounts what it placed in the page before the page's own nodes go.
  cleanup()
  document.body.innerHTML = ''
})

const TOTAL_MS = 125_000
const PLAYING = new Promise<void>(() => {})

/** The app's header, which the bar sits under. */
function renderHeader() {
  const shell = document.createElement('div')
  shell.className = 'shell'
  shell.innerHTML = '<header class="shell-header"></header><main></main>'
  document.body.append(shell)
  return shell
}

test('the time reads as a video player shows it', () => {
  expect(playbackTime(0, TOTAL_MS)).toBe('0:00 / 2:05')
  expect(playbackTime(42_600, TOTAL_MS)).toBe('0:42 / 2:05')
  expect(playbackTime(130_000, TOTAL_MS)).toBe('2:05 / 2:05')
})

test('the bar sits right under the app header', async () => {
  const shell = renderHeader()
  render(<DemoControls clock={createDemoClock()} totalMs={TOTAL_MS} replay={PLAYING} />)

  const pause = await screen.findByRole('button', { name: 'השהיה' })
  expect(shell.children[1]).toContainElement(pause)
  expect(shell.children[2].tagName).toBe('MAIN')
})

test('pause holds the clock and turns into resume, which runs it again', async () => {
  const user = userEvent.setup()
  renderHeader()
  const clock = createDemoClock()
  render(<DemoControls clock={clock} totalMs={TOTAL_MS} replay={PLAYING} />)

  await user.click(await screen.findByRole('button', { name: 'השהיה' }))
  expect(clock.paused()).toBe(true)
  await user.click(screen.getByRole('button', { name: 'המשך' }))
  expect(clock.paused()).toBe(false)
  expect(screen.getByRole('button', { name: 'השהיה' })).toBeInTheDocument()
})

test('the speed buttons set the rate and show which one is on', async () => {
  const user = userEvent.setup()
  renderHeader()
  const clock = createDemoClock()
  render(<DemoControls clock={clock} totalMs={TOTAL_MS} replay={PLAYING} />)

  const double = await screen.findByRole('button', { name: '2×' })
  expect(screen.getByRole('button', { name: '1×' })).toHaveAttribute('aria-pressed', 'true')
  // A right-to-left page would otherwise draw the sign before the digit.
  expect(double).toHaveAttribute('dir', 'ltr')
  await user.click(double)
  expect(clock.rate()).toBe(2)
  expect(double).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('button', { name: '1×' })).toHaveAttribute('aria-pressed', 'false')
})

test('the time follows the clock, and the end disables pause and shows the total', async () => {
  vi.useFakeTimers()
  renderHeader()
  const clock = createDemoClock()
  let end = () => {}
  const replay = new Promise<void>((resolve) => {
    end = resolve
  })
  render(<DemoControls clock={clock} totalMs={TOTAL_MS} replay={replay} />)
  await act(async () => {
    void clock.wait(TOTAL_MS)
    await vi.advanceTimersByTimeAsync(42_000)
  })
  expect(screen.getByText('0:42 / 2:05')).toBeInTheDocument()

  await act(async () => {
    end()
    await replay
  })
  expect(screen.getByRole('button', { name: 'השהיה' })).toBeDisabled()
  expect(screen.getByText('2:05 / 2:05')).toBeInTheDocument()
})

/** The app's header and a conversation with a bubble and a button on a card. */
function renderChat() {
  const shell = renderHeader()
  shell.querySelector('main')!.innerHTML =
    '<div class="chat-log"><p>בועה</p><button type="button">כרטיס</button></div>' +
    '<textarea aria-label="הודעה"></textarea>'
}

test('a tap on the conversation pauses and resumes, with a short sign of which', async () => {
  const user = userEvent.setup()
  renderChat()
  const clock = createDemoClock()
  render(<DemoControls clock={clock} totalMs={TOTAL_MS} replay={PLAYING} />)

  await user.click(screen.getByText('בועה'))
  expect(clock.paused()).toBe(true)
  expect(document.querySelector('.demo-flash')).toHaveTextContent('⏸')
  await user.click(screen.getByText('בועה'))
  expect(clock.paused()).toBe(false)
  expect(document.querySelector('.demo-flash')).toHaveTextContent('▶')
})

test('a tap on a control, or outside the conversation, leaves the replay playing', async () => {
  const user = userEvent.setup()
  renderChat()
  const clock = createDemoClock()
  render(<DemoControls clock={clock} totalMs={TOTAL_MS} replay={PLAYING} />)

  await user.click(screen.getByRole('button', { name: 'כרטיס' }))
  await user.click(screen.getByRole('textbox', { name: 'הודעה' }))
  expect(clock.paused()).toBe(false)
  expect(document.querySelector('.demo-flash')).toBeNull()
})

test('the space bar pauses and resumes, except while typing in a box', async () => {
  const user = userEvent.setup()
  renderChat()
  const clock = createDemoClock()
  render(<DemoControls clock={clock} totalMs={TOTAL_MS} replay={PLAYING} />)

  await user.keyboard(' ')
  expect(clock.paused()).toBe(true)
  await user.keyboard(' ')
  expect(clock.paused()).toBe(false)
  await user.type(screen.getByRole('textbox', { name: 'הודעה' }), ' ')
  expect(clock.paused()).toBe(false)
})

test('once the replay ends, a tap on the conversation changes nothing', async () => {
  const user = userEvent.setup()
  renderChat()
  const clock = createDemoClock()
  render(<DemoControls clock={clock} totalMs={TOTAL_MS} replay={Promise.resolve()} />)
  await screen.findByText(/2:05 \/ 2:05/)

  await user.click(screen.getByText('בועה'))
  expect(clock.paused()).toBe(false)
})
