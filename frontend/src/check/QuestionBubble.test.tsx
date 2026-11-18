import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { ApiException } from '../api/client.ts'
import type { Finances, Question, TermBasis } from '../api/types.ts'
import { PAYMENT_PLANNING, termBasisLine } from './copy.ts'
import { finances } from '../test/fixtures.ts'
import { wholeText } from '../test/wholeText.ts'
import type { QuestionEntry } from './events.ts'
import { QuestionBubble } from './QuestionBubble.tsx'

function entryFor(question: Question, leadIn: string | null = null): QuestionEntry {
  return { id: 'q-1', role: 'question', question, leadIn, answered: false }
}

const amountQuestion: Question = { field: 'amount', text: null, choices: null }

it('a money answer is saved and sent as a labelled line', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor({ field: 'net_fixed_income', text: null, choices: null })}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  await user.type(screen.getByRole('textbox', { name: 'הכנסה קבועה' }), '8,000')
  await user.click(screen.getByRole('button', { name: 'אישור' }))
  expect(onAnswer).toHaveBeenCalledWith({
    line: 'הכנסה קבועה: 8,000 ₪',
    update: { net_fixed_income: '8000' },
  })
})

it('a money box starts from the stored amount', () => {
  render(
    <QuestionBubble
      entry={entryFor({ field: 'net_fixed_income', text: null, choices: null })}
      live
      finances={finances}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={vi.fn()}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  expect(screen.getByRole('textbox', { name: 'הכנסה קבועה' })).toHaveValue('9,300')
})

it('normalises the typed amount; empty does not answer', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor(amountQuestion)}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  await user.click(screen.getByRole('button', { name: 'אישור' }))
  expect(onAnswer).not.toHaveBeenCalled()
  expect(screen.getByRole('textbox', { name: 'כמה צריך ללוות?' })).toBeInTheDocument()

  await user.type(screen.getByRole('textbox', { name: 'כמה צריך ללוות?' }), ' 12,500 ₪')
  await user.click(screen.getByRole('button', { name: 'אישור' }))
  expect(onAnswer).toHaveBeenCalledWith({
    line: 'כמה צריך ללוות? 12,500 ₪',
    update: null,
  })
})

it('a fixed expenses answer is saved before its line is sent', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor({ field: 'fixed_expenses', text: null, choices: null })}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  await user.type(screen.getByRole('textbox', { name: 'הוצאות קבועות' }), '4500')
  await user.click(screen.getByRole('button', { name: 'אישור' }))
  expect(onAnswer).toHaveBeenCalledWith({
    line: 'הוצאות קבועות: 4,500 ₪',
    update: { fixed_expenses: '4500' },
  })
})

it('a purpose choice sends no finances save', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor({ field: 'purpose', text: null, choices: null })}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  await user.click(screen.getByRole('button', { name: 'רכב' }))
  expect(onAnswer).toHaveBeenCalledWith({ line: 'מה רוצים לקנות? רכב', update: null })
})

it('a loan with no particular purpose is a choice, with no text box', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor({ field: 'purpose', text: null, choices: null })}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'אישור' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'דילוג' })).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'כללי' }))
  expect(onAnswer).toHaveBeenCalledWith({ line: 'מה רוצים לקנות? כללי', update: null })
})

it('a loan amount answer is a shekel line without a finances save', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor({ field: 'amount', text: null, choices: null })}
      live
      finances={finances}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  await user.type(screen.getByRole('textbox', { name: 'כמה צריך ללוות?' }), '55000')
  await user.click(screen.getByRole('button', { name: 'אישור' }))
  expect(onAnswer).toHaveBeenCalledWith({ line: 'כמה צריך ללוות? 55,000 ₪', update: null })
})

it('a free question with choices renders them as buttons', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor({ field: null, text: 'חדש או משומש?', choices: ['חדש', 'משומש'] })}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  expect(screen.getByText('חדש או משומש?')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'משומש' })).toBeInTheDocument()
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'חדש' }))
  expect(onAnswer).toHaveBeenCalledWith({ line: 'חדש או משומש? חדש', update: null })
})

it('a free question without choices takes typed text', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor({ field: null, text: 'מאיזו שנה הרכב?', choices: null })}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  await user.type(screen.getByRole('textbox', { name: 'מאיזו שנה הרכב?' }), '2019{Enter}')
  expect(onAnswer).toHaveBeenCalledWith({ line: 'מאיזו שנה הרכב? 2019', update: null })
})

it('a free question with choices has no skip', () => {
  render(
    <QuestionBubble
      entry={entryFor({
        field: null,
        text: 'איזו הלוואה לקחת?',
        choices: ['110,000 ₪', '100,000 ₪'],
      })}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={vi.fn()}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  expect(screen.getByRole('button', { name: '110,000 ₪' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'דילוג' })).not.toBeInTheDocument()
})

it('skip sends the skip line', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn()
  const onSkip = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor({ field: 'fixed_expenses', text: null, choices: null })}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={onAnswer}
      onSkip={onSkip}
      onClone={vi.fn()}
    />,
  )
  await user.click(screen.getByRole('button', { name: 'דילוג' }))
  expect(onSkip).toHaveBeenCalledWith('דילוג על: הוצאות קבועות')
  expect(onAnswer).not.toHaveBeenCalled()
})

it('a refused save stays on the question with its reason', async () => {
  const user = userEvent.setup()
  const onAnswer = vi
    .fn()
    .mockRejectedValue(new ApiException(422, 'amount cannot be negative'))
  render(
    <QuestionBubble
      entry={entryFor(amountQuestion)}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  await user.type(screen.getByRole('textbox', { name: 'כמה צריך ללוות?' }), '100')
  await user.click(screen.getByRole('button', { name: 'אישור' }))
  expect(
    await screen.findByText('הערך לא התקבל: amount cannot be negative'),
  ).toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: 'כמה צריך ללוות?' })).toBeInTheDocument()
})

it('text that is not a number is refused before anything is sent', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn()
  const logged = vi.spyOn(console, 'error').mockImplementation(() => {})
  render(
    <QuestionBubble
      entry={entryFor(amountQuestion)}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  await user.type(screen.getByRole('textbox', { name: 'כמה צריך ללוות?' }), 'הרבה')
  await user.click(screen.getByRole('button', { name: 'אישור' }))
  expect(screen.getByText('הערך לא התקבל: אפשר להקליד רק מספר, למשל 12,500')).toBeInTheDocument()
  expect(onAnswer).not.toHaveBeenCalled()
  logged.mockRestore()
})

it('an unsaved answer keeps the question open without a message', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(false)
  render(
    <QuestionBubble
      entry={entryFor(amountQuestion)}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  await user.type(screen.getByRole('textbox', { name: 'כמה צריך ללוות?' }), '100')
  await user.click(screen.getByRole('button', { name: 'אישור' }))
  expect(onAnswer).toHaveBeenCalledOnce()
  expect(screen.getByRole('textbox', { name: 'כמה צריך ללוות?' })).toHaveValue('100')
  expect(screen.getByRole('button', { name: 'אישור' })).toBeEnabled()
  expect(document.querySelector('.field-error')).toBeNull()
})

it('a closed bubble shows the question without controls', () => {
  const { container } = render(
    <QuestionBubble
      entry={entryFor(amountQuestion, 'כמעט סיימנו.')}
      live={false}
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={vi.fn()}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  expect(container.firstElementChild).toHaveClass('bubble', 'bubble-assistant', 'bubble-question')
  expect(screen.getByText('כמעט סיימנו.')).toBeInTheDocument()
  expect(screen.getByText('כמה צריך ללוות?')).toBeInTheDocument()
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

it('a live bubble shows the lead-in, the label and its hint', () => {
  render(
    <QuestionBubble
      entry={entryFor(amountQuestion, 'עוד דבר אחד.')}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={vi.fn()}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  expect(screen.getByText('עוד דבר אחד.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'הסבר' })).toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: 'כמה צריך ללוות?' })).toHaveAccessibleDescription(
    /סכום ההלוואה/,
  )
})

it('a term question shows its proposed term and first payment', () => {
  render(
    <QuestionBubble
      entry={entryFor({ kind: 'term', term_months: 60, first_payment: '812.4' })}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={vi.fn()}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  expect(screen.getByText(wholeText(TERM_LINE))).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'דילוג' })).not.toBeInTheDocument()
})

it('the term card is a first calculation that states its assumption', () => {
  renderTerm()
  expect(screen.getByText(wholeText(TERM_TITLE))).toBeInTheDocument()
  expect(screen.getByText(wholeText(termBasisLine(termBasis, '812.4')))).toBeInTheDocument()
})

it('the term card colours its values as a reply does', () => {
  renderTerm()
  const values = [...document.querySelectorAll('.bubble-question .reply-value')]
  expect(values.map((value) => value.textContent)).toEqual(['60', '812 ₪', '1,000 ₪'])
})

it('only the card of the assumed payment is titled a first calculation', () => {
  const { rerender } = render(termCard({ kind: 'typed' }))
  expect(screen.getByText(wholeText(TERM_LINE))).toBeInTheDocument()
  rerender(termCard({ kind: 'ceiling', amount: '2000', fits: true }))
  expect(screen.getByText(wholeText(TERM_LINE))).toBeInTheDocument()
})

it('a term card stored without its basis shows the title alone', () => {
  render(
    <QuestionBubble
      entry={entryFor({ kind: 'term', term_months: 60, first_payment: '812.4' })}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={vi.fn()}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  expect(document.querySelector('.card-note')).toBeNull()
})

it('the ceiling box has no placeholder and may stay empty', async () => {
  const user = userEvent.setup()
  const onAnswer = renderTerm()
  expect(ceilingBox()).not.toHaveAttribute('placeholder')
  await confirm(user)
  expect(onAnswer).toHaveBeenCalledWith({ line: 'אישור: 60 חודשים', term: 60, ceiling: null })
})

it('the payment planning chip sends its sentence and saves nothing', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  const onSkip = vi.fn().mockResolvedValue(true)
  renderTerm(null, onAnswer, onSkip)
  await user.click(screen.getByRole('button', { name: PAYMENT_PLANNING }))
  expect(onSkip).toHaveBeenCalledWith('תכנון החזר חודשי')
  expect(onAnswer).not.toHaveBeenCalled()
})

it('the term card offers no payment planning once both finances figures are recorded', () => {
  renderTerm(null, undefined, undefined, finances)
  expect(screen.queryByRole('button', { name: PAYMENT_PLANNING })).toBeNull()
})

it('the term card shows how a derived ceiling was reached beside its box', async () => {
  const user = userEvent.setup()
  const formula = '(50% מההפרש בין הכנסה של 10,000 ₪ להוצאות של 6,500 ₪)'
  renderTerm('1750', undefined, undefined, finances, formula)
  expect(screen.getByText(formula)).toBeInTheDocument()

  await user.clear(ceilingBox())
  await user.type(ceilingBox(), '2000')
  expect(screen.queryByText(formula)).toBeNull()
})

it('the term card offers payment planning while a finances figure is missing', () => {
  renderTerm(null, undefined, undefined, { ...finances, fixed_expenses: null })
  expect(screen.getByRole('button', { name: PAYMENT_PLANNING })).toBeEnabled()
})

const termBasis = { kind: 'first_payment_target', amount: '1000', fits: true } as const
const TERM_LINE = '60 חודשים · החזר ראשון כ-812 ₪'
const TERM_TITLE = `חישוב ראשוני: ${TERM_LINE}`
const termQuestion: Question = {
  kind: 'term',
  term_months: 60,
  first_payment: '812.4',
  basis: termBasis,
}

function termCard(basis: TermBasis) {
  return (
    <QuestionBubble
      entry={entryFor({ kind: 'term', term_months: 60, first_payment: '812.4', basis })}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={vi.fn()}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />
  )
}

function renderTerm(
  ceiling: string | null = null,
  onAnswer = vi.fn().mockResolvedValue(true),
  onSkip = vi.fn().mockResolvedValue(true),
  checkFinances: Finances | null = null,
  formula: string | null = null,
) {
  render(
    <QuestionBubble
      entry={entryFor(termQuestion)}
      live
      finances={checkFinances}
      ceiling={ceiling}
      ceilingFormula={formula}
      onAnswer={onAnswer}
      onSkip={onSkip}
      onClone={vi.fn()}
    />,
  )
  return onAnswer
}

const termBox = () => screen.getByRole('textbox', { name: 'מספר חודשים' })
const ceilingBox = () => screen.getByRole('textbox', { name: 'החזר חודשי מרבי' })
const confirm = (user: ReturnType<typeof userEvent.setup>) =>
  user.click(screen.getByRole('button', { name: 'אישור' }))

it('the term card starts with the proposed term and the check\'s ceiling', () => {
  renderTerm('1000.00')
  expect(termBox()).toHaveValue('60')
  expect(ceilingBox()).toHaveValue('1,000')
  expect(screen.getAllByRole('button')).toHaveLength(2)
})

it('confirm as proposed sends the term', async () => {
  const user = userEvent.setup()
  const onAnswer = renderTerm()
  await confirm(user)
  expect(onAnswer).toHaveBeenCalledWith({ line: 'אישור: 60 חודשים', term: 60, ceiling: null })
})

it('the check\'s own ceiling, left as it is, is not sent again', async () => {
  const user = userEvent.setup()
  const onAnswer = renderTerm('1000.00')
  await confirm(user)
  expect(onAnswer).toHaveBeenCalledWith({ line: 'אישור: 60 חודשים', term: 60, ceiling: null })
})

it('another term confirms that term', async () => {
  const user = userEvent.setup()
  const onAnswer = renderTerm()
  await user.clear(termBox())
  await user.type(termBox(), '48')
  await confirm(user)
  expect(onAnswer).toHaveBeenCalledWith({ line: 'אישור: 48 חודשים', term: 48, ceiling: null })
})

it('a new ceiling with the proposed term asks for a card worked out from it', async () => {
  const user = userEvent.setup()
  const onAnswer = renderTerm()
  await user.type(ceilingBox(), '1000')
  await confirm(user)
  expect(onAnswer).toHaveBeenCalledWith({ line: 'החזר חודשי מרבי: 1,000 ₪', ceiling: '1000' })
})

it('a new ceiling with another term confirms both', async () => {
  const user = userEvent.setup()
  const onAnswer = renderTerm('1000.00')
  await user.clear(termBox())
  await user.type(termBox(), '48')
  await user.clear(ceilingBox())
  await user.type(ceilingBox(), '1,200')
  await confirm(user)
  expect(onAnswer).toHaveBeenCalledWith({
    line: 'אישור: 48 חודשים, החזר חודשי מרבי: 1,200 ₪',
    term: 48,
    ceiling: '1200',
  })
})

it('a term outside 6–84 is refused', async () => {
  const user = userEvent.setup()
  const onAnswer = renderTerm()
  for (const bad of ['5', '85', '12.5', 'abc', '']) {
    await user.clear(termBox())
    if (bad !== '') await user.type(termBox(), bad)
    await confirm(user)
    expect(screen.getByText('אפשר להקליד מספר חודשים שלם בין 6 ל-84')).toBeInTheDocument()
  }
  expect(onAnswer).not.toHaveBeenCalled()
  for (const edge of ['6', '84']) {
    await user.clear(termBox())
    await user.type(termBox(), edge)
    await confirm(user)
  }
  expect(onAnswer).toHaveBeenCalledTimes(2)
})

it('a ceiling that is not a number, or a held ceiling cleared, is refused', async () => {
  const user = userEvent.setup()
  const onAnswer = renderTerm('1000.00')
  await user.clear(ceilingBox())
  await confirm(user)
  expect(screen.getByText('אפשר להקליד החזר מרבי אחר, אך לא למחוק אותו')).toBeInTheDocument()
  await user.type(ceilingBox(), 'abc')
  await confirm(user)
  expect(screen.getByText('אפשר להקליד רק מספר, למשל 12,500')).toBeInTheDocument()
  expect(onAnswer).not.toHaveBeenCalled()
})

it('the term card offers no skip', () => {
  renderTerm()
  expect(screen.queryByRole('button', { name: 'דילוג' })).not.toBeInTheDocument()
})

it('the ceiling question offers לא יודע/ת', async () => {
  const user = userEvent.setup()
  const onSkip = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor({ field: 'payment_ceiling', text: null, choices: null })}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={vi.fn()}
      onSkip={onSkip}
      onClone={vi.fn()}
    />,
  )
  expect(screen.getByRole('button', { name: 'דילוג' })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'לא יודע/ת' }))
  expect(onSkip).toHaveBeenCalledWith('לא יודע/ת')
})

it('an income answer hands its update with its line', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor({ field: 'net_fixed_income', text: null, choices: null })}
      live
      finances={null}
      ceiling={null}
      ceilingFormula={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  await user.type(screen.getByRole('textbox', { name: 'הכנסה קבועה' }), '9000')
  await user.click(screen.getByRole('button', { name: 'אישור' }))
  expect(onAnswer).toHaveBeenCalledWith({
    line: 'הכנסה קבועה: 9,000 ₪',
    update: { net_fixed_income: '9000' },
  })
})
