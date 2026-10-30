import { expect, test } from 'vitest'
import {
  answerLine,
  capNotice,
  panelNote,
  profileValueText,
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

test('a question is labelled from the profile copy, the goal copy or the model', () => {
  expect(questionLabel({ field: 'savings', text: null, choices: null })).toBe('כסף זמין')
  expect(questionLabel({ field: 'variable_income_minimum', text: null, choices: null })).toBe(
    'מינימלית',
  )
  expect(questionLabel({ field: 'price', text: null, choices: null })).toBe('מה המחיר, בערך?')
  expect(questionLabel({ field: null, text: 'חדש או משומש?', choices: null })).toBe(
    'חדש או משומש?',
  )
})

test('a skipped question names its label', () => {
  expect(skipLine('כסף זמין')).toBe('דילוג על: כסף זמין')
})

test('a panel edit is noted with its label and value', () => {
  expect(panelNote('הוצאות קבועות', '3,000 ₪')).toBe('עודכן בפרופיל: הוצאות קבועות 3,000 ₪')
})

test('an answer follows its label after a colon, or after a space when the label asks', () => {
  expect(answerLine('הכנסה קבועה', '8,000 ₪')).toBe('הכנסה קבועה: 8,000 ₪')
  expect(answerLine('כמה מההכנסה המשתנה מגיע?', '2,000 ₪')).toBe(
    'כמה מההכנסה המשתנה מגיע? 2,000 ₪',
  )
})

test('a profile value reads as a shekel amount', () => {
  expect(profileValueText('3000')).toBe('3,000 ₪')
})
