import { render } from '@testing-library/react'
import { expect, test } from 'vitest'
import { withBold, withValues } from './emphasis.tsx'

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

test('amounts, percentages and months of a reply are marked as values beside bold spans', () => {
  const { container } = render(
    <p>{withValues('התקרה: 1,750 ₪\n- 30% מההכנסה\n**סיכום קצר:** 60,000 ₪ בפריים +0.5% ל-60 חודשים')}</p>,
  )
  const values = [...container.querySelectorAll('.reply-value')].map((value) => value.textContent)
  expect(values).toEqual(['1,750 ₪', '30%', '60,000 ₪', '0.5%', '60'])
  expect(container.querySelector('strong')).toHaveTextContent('סיכום קצר:')
  expect(container.textContent).toBe(
    'התקרה: 1,750 ₪\n- 30% מההכנסה\nסיכום קצר: 60,000 ₪ בפריים +0.5% ל-60 חודשים',
  )
})

test('bold alone marks no values', () => {
  const { container } = render(<p>{withBold('עד 1,750 ₪')}</p>)
  expect(container.querySelector('.reply-value')).toBeNull()
})

test('a number of months is marked as a value, a date and a count of tracks are not', () => {
  const { container } = render(
    <p>{withValues('מספר החודשים: 60\nבדקתי 2 מסלולים ל-60 חודשים, בין 04/2022 ל-09/2024')}</p>,
  )
  const values = [...container.querySelectorAll('.reply-value')].map((value) => value.textContent)
  expect(values).toEqual(['60', '60'])
})
