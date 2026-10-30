import { render } from '@testing-library/react'
import { expect, test } from 'vitest'
import { withBold } from './emphasis.tsx'

test('marked spans turn bold and the marks disappear', () => {
  const { container } = render(<p>{withBold('**כמה צריך ללוות**\nמחיר פחות כסף זמין')}</p>)
  expect(container.querySelector('strong')).toHaveTextContent('כמה צריך ללוות')
  expect(container.textContent).toBe('כמה צריך ללוותמחיר פחות כסף זמין')
})

test('an unclosed mark stays as typed', () => {
  const { container } = render(<p>{withBold('**כמה צריך')}</p>)
  expect(container.querySelector('strong')).toBeNull()
  expect(container.textContent).toBe('**כמה צריך')
})

test('a marked line is a heading that takes the place of the blank line after it', () => {
  const { container } = render(
    <p>{withBold('פתיח\n\n**כמה צריך ללוות**\n\nמחיר פחות **כסף זמין** וזהו')}</p>,
  )
  const [heading, inline] = container.querySelectorAll('strong')
  expect(heading).toHaveClass('reply-heading')
  expect(inline).not.toHaveClass('reply-heading')
  expect(container.textContent).toBe('פתיח\n\nכמה צריך ללוותמחיר פחות כסף זמין וזהו')
})
