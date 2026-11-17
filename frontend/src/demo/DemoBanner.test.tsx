import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { DEMO_BANNER, DEMO_ENTER, DEMO_NOTICE_CLOSE, DEMO_UNAVAILABLE } from '../copy.ts'
import { NEW_CHECK } from '../shell/copy.ts'
import { DEMO_UNAVAILABLE_EVENT } from './backend.ts'
import { DemoBanner } from './DemoBanner.tsx'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const ENDED = Promise.resolve()

function refuseAnAction() {
  act(() => {
    window.dispatchEvent(new Event(DEMO_UNAVAILABLE_EVENT))
  })
}

test('the banner alone shows until an action is unavailable', () => {
  render(<DemoBanner replay={ENDED} />)
  expect(screen.getByText(DEMO_BANNER)).toBeInTheDocument()
  expect(screen.queryByRole('status')).toBeNull()
})

test('an unavailable action shows the notice, with a link into the simulator in the same tab', () => {
  render(<DemoBanner replay={ENDED} />)
  refuseAnAction()
  expect(screen.getByRole('status')).toHaveTextContent(DEMO_UNAVAILABLE)
  const link = screen.getByRole('link', { name: DEMO_ENTER })
  expect(link).toHaveAttribute('href', '/')
  expect(link).not.toHaveAttribute('target')
})

test('the notice closes, and the next unavailable action shows it again', async () => {
  const user = userEvent.setup()
  render(<DemoBanner replay={ENDED} />)
  refuseAnAction()
  await user.click(screen.getByRole('button', { name: DEMO_NOTICE_CLOSE }))
  expect(screen.queryByRole('status')).toBeNull()
  refuseAnAction()
  expect(screen.getByRole('status')).toBeInTheDocument()
})

/**
 * Clicks the notice's link with the given tab as the one the demo was opened from, and returns
 * the spy on closing the demo's tab. jsdom loads no page, so the link's own navigation is held.
 */
async function enterWithOpener(opener: unknown) {
  vi.stubGlobal('opener', opener)
  const close = vi.spyOn(window, 'close').mockImplementation(() => {})
  render(<DemoBanner replay={ENDED} />)
  refuseAnAction()
  const link = screen.getByRole('link', { name: DEMO_ENTER })
  link.addEventListener('click', (event) => event.preventDefault())
  await userEvent.setup().click(link)
  return close
}

test('the link closes the demo tab when the tab it was opened from still shows the simulator', async () => {
  const close = await enterWithOpener({ closed: false, location: { origin: location.origin } })
  expect(close).toHaveBeenCalledTimes(1)
})

test('the link loads the simulator in the demo tab when no tab opened it, or that tab is closed', async () => {
  expect(await enterWithOpener(null)).not.toHaveBeenCalled()
  cleanup()
  expect(await enterWithOpener({ closed: true })).not.toHaveBeenCalled()
})

test('the link loads the simulator in the demo tab when the opening tab moved to another site', async () => {
  const moved = {
    closed: false,
    get location(): Location {
      throw new DOMException('cross-origin', 'SecurityError')
    },
  }
  expect(await enterWithOpener(moved)).not.toHaveBeenCalled()
})

test('the new-check button is held while the recording replays, and released at its end', async () => {
  let end = () => {}
  const replay = new Promise<void>((resolve) => {
    end = resolve
  })
  render(
    <>
      <button type="button">{NEW_CHECK}</button>
      <DemoBanner replay={replay} />
    </>,
  )
  const button = screen.getByRole('button', { name: NEW_CHECK })
  expect(button).toBeDisabled()
  await act(async () => {
    end()
    await replay
  })
  expect(button).toBeEnabled()
})
