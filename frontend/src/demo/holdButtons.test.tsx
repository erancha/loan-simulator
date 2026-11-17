import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'
import { holdButtons } from './holdButtons.ts'

afterEach(cleanup)

test('buttons of the label are disabled until released; other buttons are left alone', () => {
  render(
    <>
      <button type="button">חדש</button>
      <button type="button">אחר</button>
    </>,
  )
  const release = holdButtons('חדש')
  expect(screen.getByRole('button', { name: 'חדש' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'אחר' })).toBeEnabled()
  release()
  expect(screen.getByRole('button', { name: 'חדש' })).toBeEnabled()
})

test('a button of the label the page adds while held is disabled too, and none after the release', async () => {
  const { rerender } = render(<p>רשימה</p>)
  const release = holdButtons('חדש')
  rerender(<button type="button">חדש</button>)
  await waitFor(() => expect(screen.getByRole('button', { name: 'חדש' })).toBeDisabled())
  release()
  rerender(
    <>
      <button type="button">חדש</button>
      <button type="button">חדש</button>
    </>,
  )
  await new Promise((resolve) => setTimeout(resolve, 0))
  for (const button of screen.getAllByRole('button', { name: 'חדש' })) expect(button).toBeEnabled()
})

test('a button the page itself disabled stays disabled after the release', () => {
  render(
    <button type="button" disabled>
      חדש
    </button>,
  )
  holdButtons('חדש')()
  expect(screen.getByRole('button', { name: 'חדש' })).toBeDisabled()
})
