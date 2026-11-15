import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ApiException } from '../api/client.ts'
import { FinancesPanel, hasFinances } from './FinancesPanel.tsx'

const FINANCES = { net_fixed_income: '9300', fixed_expenses: null }

function renderPanel(
  props: Partial<Parameters<typeof FinancesPanel>[0]> = {},
  onAnswer = vi.fn().mockResolvedValue(true),
) {
  render(
    <FinancesPanel
      finances={FINANCES}
      ceiling={null}
      readOnly={false}
      onAnswer={onAnswer}
      {...props}
    />,
  )
  return onAnswer
}

async function typeExpenses(text: string) {
  await userEvent.click(screen.getByRole('button', { name: 'עריכה' }))
  const input = screen.getByRole('textbox', { name: 'הוצאות קבועות' })
  await userEvent.type(input, `${text}{Tab}`)
}

test('a check has finances once either figure is set', () => {
  expect(hasFinances({ net_fixed_income: null, fixed_expenses: null })).toBe(false)
  expect(hasFinances(FINANCES)).toBe(true)
})

test('the panel sums the figures up in one line, with no fields until edit is clicked', () => {
  renderPanel()
  expect(screen.getByText('9,300 ₪')).toBeInTheDocument()
  expect(screen.getByText('עוד לא הוזן')).toBeInTheDocument()
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
})

test('a save puts the figure then sends the update line', async () => {
  const onAnswer = renderPanel()
  await typeExpenses('4500')
  expect(onAnswer).toHaveBeenCalledWith({
    line: 'עודכן: הוצאות קבועות 4,500 ₪',
    update: { fixed_expenses: '4500' },
  })
})

test('a refused save shows the rejection and sends nothing', async () => {
  const onAnswer = renderPanel(
    {},
    vi.fn().mockRejectedValue(new ApiException(422, 'negative expenses')),
  )
  await typeExpenses('4500')
  expect(await screen.findByText('הערך לא התקבל: negative expenses')).toBeInTheDocument()
  expect(onAnswer).toHaveBeenCalledTimes(1)
})

test('the panel shows the ceiling the figures give', () => {
  renderPanel({ ceiling: { amount: '1900', source: 'finances' } })
  expect(screen.getByText('1,900 ₪').parentElement).toHaveTextContent('החזר חודשי מרבי')
})

test('a stated ceiling stays on the card, not in the panel', () => {
  renderPanel({ ceiling: { amount: '1900', source: 'stated' } })
  expect(screen.queryByText('1,900 ₪')).not.toBeInTheDocument()
})

test('a read-only panel offers no edit', () => {
  renderPanel({ readOnly: true })
  expect(screen.getByText('9,300 ₪')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'עריכה' })).not.toBeInTheDocument()
})
