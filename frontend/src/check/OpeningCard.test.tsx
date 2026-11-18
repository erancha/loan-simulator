import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ApiException } from '../api/client.ts'
import {
  CONTINUE,
  OPENING_AMOUNT_INVALID,
  OPENING_CAPITAL_COVERS,
  OPENING_CAPITAL_LABEL,
  OPENING_MODE,
  OPENING_MODE_LABEL,
  OPENING_PRICE_LABEL,
  OPENING_PURPOSE_LABEL,
  OPENING_PURPOSE_MISSING,
  OPENING_TITLE,
  openingLoanLine,
  PURPOSE_CHOICES,
} from './copy.ts'
import { OpeningCard } from './OpeningCard.tsx'

function card(onSubmit = vi.fn().mockResolvedValue(true)) {
  render(<OpeningCard onSubmit={onSubmit} />)
  return onSubmit
}

const goal = (name: string) => screen.getByRole('radio', { name })
const loanBox = () => screen.getByRole('textbox', { name: OPENING_MODE.loan })
const proceed = () => screen.getByRole('button', { name: CONTINUE })

test('the card shows its title, the three goals, the amount switch and one amount box', () => {
  card()
  expect(screen.getByText(OPENING_TITLE)).toBeTruthy()
  expect(screen.getByRole('group', { name: OPENING_PURPOSE_LABEL })).toBeTruthy()
  for (const purpose of PURPOSE_CHOICES) expect(goal(purpose)).toBeTruthy()
  expect(screen.getByRole('group', { name: OPENING_MODE_LABEL })).toBeTruthy()
  expect((goal(OPENING_MODE.loan) as HTMLInputElement).checked).toBe(true)
  expect((goal(OPENING_MODE.price) as HTMLInputElement).checked).toBe(false)
  expect(screen.getAllByRole('textbox')).toHaveLength(1)
  expect(loanBox()).toBeTruthy()
})

test('a goal and an amount send both once, the amount as a decimal string', async () => {
  const onSubmit = card()
  await userEvent.click(goal('רכב'))
  await userEvent.type(loanBox(), '45,000 ₪')
  await userEvent.click(proceed())
  expect(onSubmit).toHaveBeenCalledOnce()
  expect(onSubmit).toHaveBeenCalledWith('רכב', '45000')
})

test('price and own capital show the loan they come to and send it', async () => {
  const onSubmit = card()
  await userEvent.click(goal('רכב'))
  await userEvent.click(goal(OPENING_MODE.price))
  await userEvent.type(screen.getByRole('textbox', { name: OPENING_PRICE_LABEL }), '55,000')
  await userEvent.type(screen.getByRole('textbox', { name: OPENING_CAPITAL_LABEL }), '10,000')
  expect(screen.getByText(openingLoanLine('45000'))).toBeTruthy()
  expect(screen.getByText('סכום ההלוואה: 45,000 ₪')).toBeTruthy()
  await userEvent.click(proceed())
  expect(onSubmit).toHaveBeenCalledWith('רכב', '45000')
})

test('no goal, no amount or an amount outside 10,000 to 10,000,000 is marked and sends nothing', async () => {
  const onSubmit = card()
  await userEvent.click(proceed())
  expect(screen.getByText(OPENING_PURPOSE_MISSING)).toBeTruthy()
  expect(screen.getByText(OPENING_AMOUNT_INVALID)).toBeTruthy()

  await userEvent.click(goal('רכב'))
  expect(screen.queryByText(OPENING_PURPOSE_MISSING)).toBeNull()
  for (const amount of ['9,999', '10,000,001', 'abc']) {
    await userEvent.clear(loanBox())
    await userEvent.type(loanBox(), amount)
    await userEvent.click(proceed())
    expect(screen.getByText(OPENING_AMOUNT_INVALID)).toBeTruthy()
  }
  expect(onSubmit).not.toHaveBeenCalled()

  await userEvent.clear(loanBox())
  await userEvent.type(loanBox(), '10,000')
  await userEvent.click(proceed())
  expect(onSubmit).toHaveBeenCalledWith('רכב', '10000')
})

test('own capital at or above the price is marked and sends nothing', async () => {
  const onSubmit = card()
  await userEvent.click(goal('רכב'))
  await userEvent.click(goal(OPENING_MODE.price))
  await userEvent.type(screen.getByRole('textbox', { name: OPENING_PRICE_LABEL }), '55,000')
  const capital = screen.getByRole('textbox', { name: OPENING_CAPITAL_LABEL })
  for (const amount of ['55,000', '60,000']) {
    await userEvent.clear(capital)
    await userEvent.type(capital, amount)
    await userEvent.click(proceed())
    expect(screen.getByText(OPENING_CAPITAL_COVERS)).toBeTruthy()
  }
  expect(onSubmit).not.toHaveBeenCalled()
})

test('a refused loan shows the card\'s own line, logs the reason and keeps the card', async () => {
  const reason = 'The engine refused the amount: too high; tell the person the range'
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
  const onSubmit = vi.fn().mockRejectedValue(new ApiException(422, reason))
  card(onSubmit)
  await userEvent.click(goal('רכב'))
  await userEvent.type(loanBox(), '45000')
  await userEvent.click(proceed())
  expect(await screen.findByText(OPENING_AMOUNT_INVALID)).toBeTruthy()
  expect(document.body.textContent).not.toContain('engine')
  expect(warn).toHaveBeenCalledWith(expect.stringContaining(reason))
  warn.mockRestore()
  expect((proceed() as HTMLButtonElement).disabled).toBe(false)
  expect(loanBox()).toBeTruthy()
})

test('the button is disabled while the card is sent, enabled again if it was not', async () => {
  let finish: (sent: boolean) => void = () => undefined
  const onSubmit = vi.fn(() => new Promise<boolean>((resolve) => (finish = resolve)))
  card(onSubmit)
  await userEvent.click(goal('רכב'))
  await userEvent.type(loanBox(), '45000')
  await userEvent.click(proceed())
  expect((proceed() as HTMLButtonElement).disabled).toBe(true)
  finish(false)
  await vi.waitFor(() => expect((proceed() as HTMLButtonElement).disabled).toBe(false))
})

test('a sent card stays disabled, so a second press sends nothing', async () => {
  const onSubmit = card()
  await userEvent.click(goal('רכב'))
  await userEvent.type(loanBox(), '45000')
  await userEvent.click(proceed())
  await vi.waitFor(() => expect(onSubmit).toHaveBeenCalledOnce())
  expect((proceed() as HTMLButtonElement).disabled).toBe(true)
  await userEvent.click(proceed())
  expect(onSubmit).toHaveBeenCalledOnce()
})

test('an amount is grouped by thousands as it is typed, and sent as plain digits', async () => {
  const onSubmit = card()
  await userEvent.click(goal('רכב'))
  await userEvent.type(loanBox(), '100000')
  expect(loanBox()).toHaveValue('100,000')

  await userEvent.click(proceed())
  expect(onSubmit).toHaveBeenCalledExactlyOnceWith('רכב', '100000')
})

test('a digit typed in the middle of an amount keeps the caret after it', async () => {
  card()
  await userEvent.type(loanBox(), '1000')
  expect(loanBox()).toHaveValue('1,000')

  await userEvent.type(loanBox(), '5', { initialSelectionStart: 1, initialSelectionEnd: 1 })
  expect(loanBox()).toHaveValue('15,000')
  expect((loanBox() as HTMLInputElement).selectionStart).toBe(2)
})
