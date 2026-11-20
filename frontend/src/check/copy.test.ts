import { expect, test } from 'vitest'
import {
  ceilingFormula,
  questionText,
  scenarioLine,
  scenarioTitle,
  answerLine,
  capNotice,
  amountText,
  checkTitle,
  confirmedReadingLine,
  equivalentRateText,
  identifiedText,
  lenderQuestion,
  openingLine,
  readingText,
  settledReadingText,
  wordsSuggestText,
  questionLabel,
  skipLine,
  termBasisLine,
  withLastMonth,
} from './copy.ts'
import type { Reading } from '../api/types.ts'
import { awaitingAvis, identifiedMax } from '../test/fixtures.ts'

const now = new Date(2026, 9, 29, 22, 40)

test('the cap notice gives the time alone when sending resumes today', () => {
  expect(capNotice(new Date(2026, 9, 29, 23, 5), now)).toBe(
    'הגעתם למכסת ההודעות. אפשר להמשיך ב-23:05',
  )
})

test('the cap notice says tomorrow when sending resumes on the next day', () => {
  expect(capNotice(new Date(2026, 9, 30, 7, 5), now)).toBe(
    'הגעתם למכסת ההודעות. אפשר להמשיך מחר ב-07:05',
  )
})

test('the cap notice gives the date when sending resumes later than tomorrow', () => {
  expect(capNotice(new Date(2026, 10, 1, 9, 0), now)).toBe(
    'הגעתם למכסת ההודעות. אפשר להמשיך ב-01.11 ב-09:00',
  )
})

test('a question is labelled from the field copy, the term card or the model', () => {
  expect(questionLabel({ field: 'net_fixed_income', text: null, choices: null })).toBe(
    'הכנסה קבועה',
  )
  expect(questionLabel({ field: 'amount', text: null, choices: null })).toBe('כמה צריך ללוות?')
  expect(questionLabel({ field: null, text: 'חדש או משומש?', choices: null })).toBe(
    'חדש או משומש?',
  )
  expect(questionLabel({ kind: 'term', term_months: 60, first_payment: '812.4' })).toBe(
    '60 חודשים · החזר מ-812 ₪',
  )
  expect(
    questionLabel({
      kind: 'term',
      term_months: 60,
      first_payment: '812.4',
      basis: { kind: 'first_payment_target', amount: '1000', fits: true },
    }),
  ).toBe('חישוב ראשוני: 60 חודשים · החזר מ-812 ₪')
})

test('the term card states the assumption its term was worked out from', () => {
  expect(termBasisLine({ kind: 'first_payment_target', amount: '1000', fits: true }, '992.9')).toBe(
    'בהנחה ראשונית שההחזר החודשי יהיה עד כ-1,000 ₪, זה מספר החודשים המתאים. אפשר לשנות כאן' +
      ' את מספר החודשים, או לכתוב החזר חודשי מרבי אחר.',
  )
  expect(termBasisLine({ kind: 'ceiling', amount: '1750.00', fits: true }, '1096.4')).toBe(
    'לפי ההחזר החודשי המרבי שלך, 1,750 ₪, זה מספר החודשים המתאים, גם אם הריבית תעלה כמו בעבר.' +
      ' אפשר לשנות כאן את הפרמטרים.',
  )
})

test('a term that fits nothing is not called a fit', () => {
  const stated = termBasisLine({ kind: 'ceiling', amount: '700', fits: false }, '1553.64')
  expect(stated).toContain('גם ב-84 חודשים')
  expect(stated).not.toContain('המתאים')
  expect(stated).toContain('אפשר לשנות כאן')
  expect(stated).toContain('700 ₪')
})

test('with no payment from the person, the longest term states the lowest payment the loan allows', () => {
  // The first payment the simulator aims at is its own starting point, never the person's, so
  // the card that cannot meet it says what the longest term gives and names no assumed amount.
  expect(termBasisLine({ kind: 'first_payment_target', amount: '1000', fits: false }, '1553.64')).toBe(
    '84 חודשים היא התקופה הארוכה ביותר שהסימולטור מחשב. בתקופה כזו ההחזר החודשי הנמוך ביותר הוא' +
      ' כ-1,554 ₪ בהתחלה. אפשר לקצר כאן את מספר החודשים, או לכתוב החזר' +
      ' חודשי מרבי.',
  )
})

test('a suggested shorter term is titled as one and states what it saves', () => {
  const basis = {
    kind: 'shorter',
    amount: '2000',
    from_term_months: 72,
    worst_payment: '1936',
    saving: '1595',
  } as const
  expect(
    questionLabel({ kind: 'term', term_months: 66, first_payment: '1872.99', basis }),
  ).toBe('אפשר לקצר: 66 חודשים · החזר מ-1,873 ₪')
  expect(termBasisLine(basis, '1872.99')).toBe(
    'זה מספר החודשים המיטבי לפי ההחזר החודשי המרבי שלך, 2,000 ₪: במקום 72 חודשים, ההחזר נשאר' +
      ' עד כ-1,936 ₪ גם אם הריבית תעלה כמו בעבר, והסכום הכולל להחזר קטן ב-1,595 ₪.' +
      ' אפשר לשנות כאן את הפרמטרים.',
  )
})

test('a term the person typed is said to be theirs', () => {
  expect(termBasisLine({ kind: 'typed' }, '812.4')).toContain('שבחרת')
})

test('a skipped question names its label', () => {
  expect(skipLine('כסף זמין')).toBe('דילוג על: כסף זמין')
})

test('an answer follows its label after a colon, or after a space when the label asks', () => {
  expect(answerLine('הכנסה קבועה', '8,000 ₪')).toBe('הכנסה קבועה: 8,000 ₪')
  expect(answerLine('כמה מההכנסה המשתנה מגיע?', '2,000 ₪')).toBe(
    'כמה מההכנסה המשתנה מגיע? 2,000 ₪',
  )
})

test('an amount reads as a shekel amount', () => {
  expect(amountText('3000')).toBe('3,000 ₪')
})

test('checkTitle names the purpose and the amount', () => {
  expect(checkTitle({ purpose: 'רכב', amount: '29000' })).toBe('רכב - הלוואה בסך 29,000₪')
})

test('a loan without a purpose is titled כללי', () => {
  expect(checkTitle({ purpose: null, amount: '100000' })).toBe('כללי - הלוואה בסך 100,000₪')
})

test("a reply's line of months gains the loan's last month, once", () => {
  const today = new Date(2026, 10, 16)
  expect(withLastMonth('סכום ההלוואה: 60,000 ₪\nמספר החודשים: 24\nבדקתי', today)).toBe(
    'סכום ההלוואה: 60,000 ₪\nמספר החודשים: 24 (עד 11/2028)\nבדקתי',
  )
  expect(withLastMonth('מספר החודשים: 24 (עד 11/2028)', today)).toBe(
    'מספר החודשים: 24 (עד 11/2028)',
  )
  expect(withLastMonth('ל-24 חודשים', today)).toBe('ל-24 חודשים')
})

const IDENTIFIED =
  'זיהיתי שזו הלוואה בריבית פריים + 6.45%. ריבית הפריים נכון ל-15.11.2026 היא 4.75%, כך שהריבית' +
  ' הכוללת היום היא 11.2% (4.75 + 6.45). ההחזר שמסרת, 934 ₪, תואם לחישוב הזה.'

test('the identified reply names the loan, the prime, its date, the total and the payment', () => {
  expect(identifiedText({ ...identifiedMax, quoted_amount: '45000' })).toBe(IDENTIFIED)
})

test('an offer quoted on another amount says which amount the check prices', () => {
  expect(identifiedText(identifiedMax)).toBe(
    `${IDENTIFIED} ההצעה ניתנה על 20,000 ₪; בבדיקה היא מחושבת על סכום ההלוואה, 45,000 ₪.`,
  )
})

test('each reading is worded by its kind, a rate fixed by the payment as approximate', () => {
  const [unlinked, margin, linked] = awaitingAvis.readings
  expect(readingText(unlinked)).toBe('ריבית קבועה 10.58%, לא צמודה למדד')
  expect(readingText(margin)).toBe('ריבית פריים + 5.83%')
  expect(readingText(linked)).toBe('ריבית קבועה כ-10.58%, צמודה למדד')
  const total: Reading = {
    ...margin,
    kind: 'prime_total',
    total_rate: '6.45',
    track: { ...margin.track, prime_spread: '1.7' },
  }
  expect(readingText(total)).toBe('ריבית כוללת 6.45% היום (פריים + 1.7%)')
  const negative: Reading = { ...margin, track: { ...margin.track, prime_spread: '-0.25' } }
  expect(readingText(negative)).toBe('ריבית פריים − 0.25%')
  expect(settledReadingText(unlinked)).toBe('אושר: ריבית קבועה 10.58%, לא צמודה למדד.')
  expect(confirmedReadingLine(unlinked)).toBe('אישור: ריבית קבועה 10.58%, לא צמודה למדד')
})

test('the lender question names the payment when one was given', () => {
  expect(lenderQuestion('969')).toBe(
    'האם ההחזר החודשי של 969 ₪ נשאר זהה עד סוף ההלוואה? האם הריבית קבועה או תלויה בריבית' +
      ' הפריים, והאם ההלוואה צמודה למדד?',
  )
  expect(lenderQuestion(null)).toBe(
    'האם הריבית קבועה או תלויה בריבית הפריים, והאם ההלוואה צמודה למדד?',
  )
})

test('"קבוע" and "צמוד" each explain what they suggest; no word suggests nothing', () => {
  expect(wordsSuggestText('fixed_unlinked', ['fixed'], 'אוויס')).toBe(
    'בגלל המילה "קבוע", סביר שההלוואה אינה צמודה למדד ושההחזר לא ישתנה. מלווים משתמשים במילה' +
      ' הזו גם כשרק הריבית קבועה וההחזר עדיין עולה עם המדד, ולכן כדאי לוודא זאת מול אוויס.',
  )
  expect(wordsSuggestText('fixed_linked', ['linked'], 'אוויס')).toBe(
    'בגלל המילה "צמוד", סביר שהריבית קבועה וההלוואה צמודה למדד, כך שההחזר יעלה עם המדד.' +
      ' כדאי לוודא זאת מול אוויס.',
  )
  expect(wordsSuggestText(null, [], 'אוויס')).toBeNull()
  expect(wordsSuggestText(null, ['prime'], 'אוויס')).toBeNull()
})

test('the equivalent rate is rounded to one decimal', () => {
  expect(equivalentRateText('10.58')).toBe('ההחזר הזה שקול לריבית של כ-10.6% לשנה היום.')
})

test('the opening line names the purpose and the amount', () => {
  expect(openingLine('רכב', '45000')).toBe('רכב: הלוואה בסך 45,000 ₪')
})

const twoFigures = { net_fixed_income: '10000', fixed_expenses: '6500' }

test('a derived ceiling names the lower of its two caps', () => {
  const caps = {
    income_percent: '30.00',
    ceiling_by_income_share: '3000.00',
    disposable_percent: '50.00',
    ceiling_by_disposable_income: '1750.00',
  }
  expect(ceilingFormula(caps, twoFigures)).toBe(
    '(50% מההפרש בין הכנסה של 10,000 ₪ להוצאות של 6,500 ₪)',
  )
  expect(ceilingFormula({ ...caps, ceiling_by_income_share: '1500.00' }, twoFigures)).toBe(
    '(30% מהכנסה של 10,000 ₪)',
  )
})

function on(cpi: string, prime: string, cpiYears: number | null = null) {
  return {
    cpi_per_year: cpi,
    prime_per_year: prime,
    cpi_like_last_years: cpiYears,
    prime_like_last_years: null,
  }
}

test('a scenario title names both movements, a fall and no change included', () => {
  expect(scenarioTitle(on('5', '0'))).toBe('אם המדד יעלה 5% בשנה והפריים לא ישתנה')
  expect(scenarioTitle(on('2.0', '1'))).toBe('אם המדד יעלה 2% בשנה והפריים יעלה ב-1% בשנה')
  expect(scenarioTitle(on('0', '-0.5'))).toBe('אם המדד לא ישתנה והפריים ירד ב-0.5% בשנה')
  expect(scenarioTitle(on('-1', '0'))).toBe('אם המדד ירד 1% בשנה והפריים לא ישתנה')
})

test('a scenario title says a movement taken from the last years, with its yearly figure', () => {
  expect(scenarioTitle(on('3.14', '0', 3))).toBe(
    'אם המדד יעלה כמו ב-3 השנים האחרונות (3.14% בשנה) והפריים לא ישתנה',
  )
})

test('a scenario form names its movement, and its line states the yearly rise', () => {
  expect(questionText({ kind: 'scenario', movement: 'prime' })).toBe('סימולציה למקרה שהפריים יעלה')
  expect(scenarioLine('cpi', '3')).toBe('סימולציה: המדד יעלה 3% בשנה')
})

