import { expect, test } from 'vitest'
import {
  answerLine,
  capNotice,
  amountText,
  checkTitle,
  questionLabel,
  skipLine,
} from './copy.ts'

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
    'תקופה מוצעת: 60 חודשים · החזר ראשון כ-812 ₪',
  )
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
