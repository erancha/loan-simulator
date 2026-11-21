import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { SignInButton } from './SignInButton.tsx'

const WHY = 'למה להתחבר עם Google?'
const GOOGLE_HELP = 'https://support.google.com/accounts/answer/12921417'

test('the reasons for signing in with Google stay closed until asked for', () => {
  render(<SignInButton />)

  expect(screen.getByRole('button', { name: WHY })).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('list')).not.toBeInTheDocument()
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
})

test('the toggle opens the reasons, ending with the link to Google, and closes them', async () => {
  render(<SignInButton />)
  const toggle = screen.getByRole('button', { name: WHY })

  await userEvent.click(toggle)

  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByText('בטוחה ונוחה יותר').tagName).toBe('STRONG')
  const points = screen.getAllByRole('listitem')
  expect(points).toHaveLength(4)
  expect(points[0]).toHaveTextContent(
    'ההתחברות מאושרת על ידי Google, לא על ידי הסימולטור. Google מוסרת לסימולטור רק אימות לגבי' +
      ' הזהות שלכם, ללא גישה לנתונים שלכם (מיילים, אנשי קשר ועוד).',
  )
  const link = screen.getByRole('link', { name: 'ההסבר המלא של Google' })
  expect(link).toHaveAttribute('href', GOOGLE_HELP)
  expect(link).toHaveAttribute('target', '_blank')
  expect(link).toHaveAttribute('rel', 'noreferrer')

  await userEvent.click(toggle)

  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('list')).not.toBeInTheDocument()
})

test('a refused sign-in shows right under the button, above the reasons toggle', () => {
  render(<SignInButton refusal="הכניסה עם Google לא הושלמה. אפשר לנסות שוב." />)

  const alert = screen.getByRole('alert')
  const toggle = screen.getByRole('button', { name: WHY })
  expect(alert.compareDocumentPosition(toggle)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
})
