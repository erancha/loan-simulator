import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { ApiException } from '../api/client.ts'
import type { Question } from '../api/types.ts'
import { profileView } from '../test/fixtures.ts'
import type { QuestionEntry } from './events.ts'
import { QuestionBubble } from './QuestionBubble.tsx'

function entryFor(question: Question, leadIn: string | null = null): QuestionEntry {
  return { id: 'q-1', role: 'question', question, leadIn, answered: false }
}

const savingsQuestion: Question = { field: 'savings', text: null, choices: null }

it('a money answer is saved and sent as a labelled line', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor({ field: 'net_fixed_income', text: null, choices: null })}
      live
      profile={null}
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
      entry={entryFor(savingsQuestion)}
      live
      profile={profileView.profile}
      onAnswer={vi.fn()}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  expect(screen.getByRole('textbox', { name: 'כסף זמין' })).toHaveValue('15,000')
})

it('normalises the typed amount; empty does not answer', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor(savingsQuestion)}
      live
      profile={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  await user.click(screen.getByRole('button', { name: 'אישור' }))
  expect(onAnswer).not.toHaveBeenCalled()
  expect(screen.getByRole('textbox', { name: 'כסף זמין' })).toBeInTheDocument()

  await user.type(screen.getByRole('textbox', { name: 'כסף זמין' }), ' 12,500 ₪')
  await user.click(screen.getByRole('button', { name: 'אישור' }))
  expect(onAnswer).toHaveBeenCalledWith({
    line: 'כסף זמין: 12,500 ₪',
    update: { savings: '12500' },
  })
})

it('the minimum of the variable income is an ordinary money answer', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor({ field: 'variable_income_minimum', text: null, choices: null })}
      live
      profile={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  expect(screen.getByText('ובחודש חלש, כמה מההכנסה המשתנה בכל זאת נכנס?')).toBeInTheDocument()
  await user.type(screen.getByRole('textbox', { name: 'מינימלית' }), '2000')
  await user.click(screen.getByRole('button', { name: 'אישור' }))
  expect(onAnswer).toHaveBeenCalledWith({
    line: 'מינימלית: 2,000 ₪',
    update: { variable_income_minimum: '2000' },
  })
})

it('a skip saves a minimum of 0', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor({ field: 'variable_income_minimum', text: null, choices: null })}
      live
      profile={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  await user.click(screen.getByRole('button', { name: 'דילוג' }))
  expect(onAnswer).toHaveBeenLastCalledWith({
    line: 'דילוג על: מינימלית (נשמר כ-0)',
    update: { variable_income_minimum: '0' },
  })
})

it('a purpose choice sends no profile update', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor({ field: 'purpose', text: null, choices: null })}
      live
      profile={null}
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
      profile={null}
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

it('a price answer is a shekel line without a profile update', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor({ field: 'price', text: null, choices: null })}
      live
      profile={profileView.profile}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  await user.type(screen.getByRole('textbox', { name: 'מה המחיר, בערך?' }), '55000')
  await user.click(screen.getByRole('button', { name: 'אישור' }))
  expect(onAnswer).toHaveBeenCalledWith({ line: 'מה המחיר, בערך? 55,000 ₪', update: null })
})

it('a free question with choices renders them as buttons', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  render(
    <QuestionBubble
      entry={entryFor({ field: null, text: 'חדש או משומש?', choices: ['חדש', 'משומש'] })}
      live
      profile={null}
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
      profile={null}
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
      profile={null}
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
      profile={null}
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
    .mockRejectedValue(new ApiException(422, 'savings cannot be negative'))
  render(
    <QuestionBubble
      entry={entryFor(savingsQuestion)}
      live
      profile={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  await user.type(screen.getByRole('textbox', { name: 'כסף זמין' }), '100')
  await user.click(screen.getByRole('button', { name: 'אישור' }))
  expect(
    await screen.findByText('הערך לא התקבל: savings cannot be negative'),
  ).toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: 'כסף זמין' })).toBeInTheDocument()
})

it('text that is not a number is refused before anything is sent', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn()
  const logged = vi.spyOn(console, 'error').mockImplementation(() => {})
  render(
    <QuestionBubble
      entry={entryFor(savingsQuestion)}
      live
      profile={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  await user.type(screen.getByRole('textbox', { name: 'כסף זמין' }), 'הרבה')
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
      entry={entryFor(savingsQuestion)}
      live
      profile={null}
      onAnswer={onAnswer}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  await user.type(screen.getByRole('textbox', { name: 'כסף זמין' }), '100')
  await user.click(screen.getByRole('button', { name: 'אישור' }))
  expect(onAnswer).toHaveBeenCalledOnce()
  expect(screen.getByRole('textbox', { name: 'כסף זמין' })).toHaveValue('100')
  expect(screen.getByRole('button', { name: 'אישור' })).toBeEnabled()
  expect(document.querySelector('.field-error')).toBeNull()
})

it('a closed bubble shows the question without controls', () => {
  const { container } = render(
    <QuestionBubble
      entry={entryFor(savingsQuestion, 'כמעט סיימנו.')}
      live={false}
      profile={null}
      onAnswer={vi.fn()}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  expect(container.firstElementChild).toHaveClass('bubble', 'bubble-assistant', 'bubble-question')
  expect(screen.getByText('כמעט סיימנו.')).toBeInTheDocument()
  expect(screen.getByText('כמה כסף זמין יש לקנייה?')).toBeInTheDocument()
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

it('a live bubble shows the lead-in, the label and its hint', () => {
  render(
    <QuestionBubble
      entry={entryFor(savingsQuestion, 'עוד דבר אחד.')}
      live
      profile={null}
      onAnswer={vi.fn()}
      onSkip={vi.fn()}
      onClone={vi.fn()}
    />,
  )
  expect(screen.getByText('עוד דבר אחד.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'הסבר' })).toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: 'כסף זמין' })).toHaveAccessibleDescription(
    /כל הכסף הנזיל שיש לך לקנייה/,
  )
})

it('a skipped loans, savings or variable income question saves 0 and says so', async () => {
  const user = userEvent.setup()
  const onAnswer = vi.fn().mockResolvedValue(true)
  const onSkip = vi.fn()
  render(
    <QuestionBubble
      entry={entryFor(savingsQuestion)}
      live
      profile={null}
      onAnswer={onAnswer}
      onSkip={onSkip}
      onClone={vi.fn()}
    />,
  )
  await user.click(screen.getByRole('button', { name: 'דילוג' }))
  expect(onAnswer).toHaveBeenCalledWith({
    line: 'דילוג על: כסף זמין (נשמר כ-0)',
    update: { savings: '0' },
  })
  expect(onSkip).not.toHaveBeenCalled()
})
