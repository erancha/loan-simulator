import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { SignInButton } from './SignInButton.tsx'

const WHY = 'למה להתחבר עם Google?'
const GOOGLE_HELP = 'https://support.google.com/accounts/answer/12921417'

test('the reasons for signing in with Google stay closed until asked for', () => {
  render(<SignInButton />)

  expect(screen.getByRole('button', { name: WHY })).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('list')).not.toBeInTheDocument()
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'סגירת ההסבר' })).not.toBeInTheDocument()
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
    'ההתחברות מאושרת על ידי Google.\u200F Google מוסרת לאפליקציה רק אימות לגבי' +
      ' הזהות שלכם, ללא גישה לנתונים שלכם (מיילים, אנשי קשר ועוד).',
  )
  expect(points[1]).toHaveTextContent('אפשר לנתק את האפליקציה בכל רגע מהגדרות חשבון Google.')
  expect(points[2]).toHaveTextContent('האפליקציה לא שומרת סיסמאות בכלל.')
  // The link says it opens a new tab, so nobody takes it for the way to close the explanation.
  const link = screen.getByRole('link', { name: 'ההסבר המלא של Google (נפתח בכרטיסייה חדשה)' })
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

test('the open explanation frames the sign-in area, and its close button closes it', async () => {
  const { container } = render(<SignInButton />)
  const scroll = vi.spyOn(Element.prototype, 'scrollIntoView')
  const area = container.querySelector('.sign-in')
  const toggle = screen.getByRole('button', { name: WHY })
  expect(area).not.toHaveClass('sign-in-open')

  await userEvent.click(toggle)
  // Opening scrolls down to the explanation's last line.
  expect(scroll).toHaveBeenLastCalledWith({ behavior: 'smooth', block: 'end' })
  expect(scroll.mock.instances).toContain(container.querySelector('.sign-in-why-text'))
  expect(area).toHaveClass('sign-in-open')

  await userEvent.click(screen.getByRole('button', { name: 'סגירת ההסבר' }))
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('list')).not.toBeInTheDocument()
  expect(area).not.toHaveClass('sign-in-open')
  // The close button is gone, so focus moves to the toggle rather than to the page's start.
  expect(toggle).toHaveFocus()
})
