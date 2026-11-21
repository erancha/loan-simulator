import { expect, test } from 'vitest'
import type { Question } from '../api/types.ts'
import { avisReading } from '../test/fixtures.ts'
import {
  amountCoveredLine,
  amountDeclinedLine,
  amountText,
  answerLine,
  CEILING_LABEL,
  cloneLine,
  confirmedReadingLine,
  confirmedTermLine,
  CONTINUE_TO_ANOTHER_OFFER,
  EXPENSES_LABEL,
  fieldLabel,
  GENERAL_PURPOSE,
  INCOME_LABEL,
  offerLine,
  openingLine,
  PAYMENT_PLANNING,
  readingText,
  scenarioLine,
  SKIP,
  skipLine,
  STAY_CHOICE,
  updateLine,
} from './copy.ts'
import { spokenLine } from './spokenLine.ts'

const said = (line: string, asked: Question | null = null) => spokenLine(line, asked)

test('the opening card reads as wanting a loan for its purpose', () => {
  expect(said(openingLine('רכב', '45000'))).toBe('אני רוצה הלוואה לרכב בסך 45,000 ₪.')
  expect(said(openingLine('חתונה', '30000'))).toBe('אני רוצה הלוואה לחתונה בסך 30,000 ₪.')
  expect(said(openingLine(GENERAL_PURPOSE, '20000'))).toBe('אני רוצה הלוואה כללית בסך 20,000 ₪.')
})

test('a ceiling reads the same from the term card and from its question', () => {
  const sentence = 'אוכל להחזיר עד 1,200 ₪ בחודש.'
  expect(said(answerLine(CEILING_LABEL, amountText('1200')))).toBe(sentence)
  expect(said(answerLine(fieldLabel('payment_ceiling'), amountText('1200')))).toBe(sentence)
})

test('a confirmed term reads as agreeing to it, with any ceiling typed beside it', () => {
  expect(said(confirmedTermLine(48, null))).toBe('מתאים לי: 48 חודשים.')
  expect(said(confirmedTermLine(48, '1200'))).toBe(
    'מתאים לי: 48 חודשים, עם החזר חודשי של עד 1,200 ₪.',
  )
})

test('an answered field reads as a sentence about the person', () => {
  expect(said(answerLine(fieldLabel('purpose'), 'רכב'))).toBe('אני רוצה לקנות רכב.')
  expect(said(answerLine(fieldLabel('amount'), amountText('45000')))).toBe(
    'אני רוצה ללוות 45,000 ₪.',
  )
  expect(said(answerLine(fieldLabel('own_capital'), amountText('20000')))).toBe(
    'מהכסף שכבר יש לי אשלם 20,000 ₪.',
  )
  expect(said(answerLine(fieldLabel('net_fixed_income'), amountText('12000')))).toBe(
    'ההכנסה הקבועה שלי היא 12,000 ₪ בחודש, נטו.',
  )
  expect(said(answerLine(fieldLabel('fixed_expenses'), amountText('6000')))).toBe(
    'ההוצאות הקבועות שלי הן 6,000 ₪ בחודש.',
  )
})

test("an answer to the agent's own question reads as the answer alone", () => {
  const asked: Question = { field: null, text: 'האם ההצעה צמודה למדד?', choices: ['כן', 'לא'] }
  expect(said(answerLine('האם ההצעה צמודה למדד?', 'כן'), asked)).toBe('כן')
})

test('a skip reads the same from any form', () => {
  expect(said(skipLine(fieldLabel('net_fixed_income')))).toBe('נדלג על זה בינתיים.')
  expect(said(SKIP)).toBe('נדלג על זה בינתיים.')
})

test('a figure edited in the data panel reads as having updated it', () => {
  expect(said(updateLine(INCOME_LABEL, '10000'))).toBe('עדכנתי את ההכנסה הקבועה ל-10,000 ₪.')
  expect(said(updateLine(EXPENSES_LABEL, '5000'))).toBe('עדכנתי את ההוצאות הקבועות ל-5,000 ₪.')
})

test('an offer from the form reads as one sentence naming its lender and its tracks', () => {
  const tracks = [
    { kind: 'prime_plus' as const, rate: '0.5', linked: false },
    { kind: 'prime_plus' as const, rate: '1.5', linked: false },
    { kind: 'fixed' as const, rate: '3.5', linked: true },
  ]
  expect(said(offerLine('קרן פנסיה', tracks, 48))).toBe(
    'קיבלתי הצעה מקרן פנסיה, לעד 48 חודשים בתשלומים חודשיים שווים, בשלושה מסלולים: ' +
      'פריים פלוס 0.5%, לא צמוד למדד; פריים פלוס 1.5%, לא צמוד למדד; ריבית קבועה 3.5%, צמודה למדד.',
  )
  expect(said(offerLine('Max', [{ kind: 'fixed', rate: '4', linked: false }], 60))).toBe(
    'קיבלתי הצעה מ-Max: ריבית קבועה 4%, לא צמודה למדד, לעד 60 חודשים בתשלומים חודשיים שווים.',
  )
})

test('the buttons that send a fixed line read as a sentence', () => {
  expect(said(PAYMENT_PLANNING)).toBe('אשמח לעזרה בתכנון ההחזר החודשי.')
  expect(said(CONTINUE_TO_ANOTHER_OFFER)).toBe('בינתיים אזין הצעה נוספת, עד שתגיע תשובה.')
  expect(said(STAY_CHOICE)).toBe('נעדכן את הבדיקה הזאת.')
})

test("a reading and the lender's answer on the amount read as what the person learned", () => {
  const reading = avisReading('fixed_unlinked')
  const terms = readingText(reading)
  expect(said(confirmedReadingLine(reading))).toBe(`כן, זו ההצעה: ${terms}.`)
  expect(said(amountCoveredLine('בנק הפועלים', '45000', reading))).toBe(
    `בנק הפועלים מציעים גם 45,000 ₪ באותם תנאים: ${terms}.`,
  )
  expect(said(amountDeclinedLine('בנק הפועלים', '45000'))).toBe('בנק הפועלים לא מציעים 45,000 ₪.')
})

test('a clone and a scenario read as the request they carry', () => {
  expect(said(cloneLine('אפשר לקצר ל-36 חודשים?'))).toBe('נבדוק בנפרד: אפשר לקצר ל-36 חודשים?')
  expect(said(scenarioLine('cpi', '3'))).toBe('מה יקרה אם המדד יעלה 3% בשנה?')
  expect(said(scenarioLine('prime', '1.5'))).toBe('מה יקרה אם הפריים יעלה 1.5% בשנה?')
})

test('anything the person typed shows as typed', () => {
  const typed = 'מהבנק שלי הציעו לי פריים פלוס 6, הלוואה של 45, 5 שנים, 972 שח קבוע'
  expect(said(typed)).toBe(typed)
  expect(said('אישור')).toBe('אישור')
})
