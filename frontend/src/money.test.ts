import { describe, expect, test } from 'vitest'
import {
  decimalText,
  formatAmount,
  formatDate,
  formatMonth,
  formatShekelRange,
  formatShekels,
  formatTimestamp,
  exceeds,
  formatYearRange,
  isZero,
  roundedPercent,
  subtractAmounts,
  groupTypedAmount,
  normaliseMoneyInput,
} from './money.ts'

describe('formatShekels', () => {
  test.each([
    ['904.08', '904 ₪'],
    ['904.50', '905 ₪'],
    ['904.49', '904 ₪'],
    ['999.5', '1,000 ₪'],
    ['32546.86', '32,547 ₪'],
    ['0', '0 ₪'],
    ['1900.00', '1,900 ₪'],
    ['99.5', '100 ₪'],
    ['9999.5', '10,000 ₪'],
    ['0.5', '1 ₪'],
    ['1000', '1,000 ₪'],
    ['1234567', '1,234,567 ₪'],
  ])('formatShekels(%s)', (input, expected) => expect(formatShekels(input)).toBe(expected))

  test('approx', () => expect(formatShekels('955.37', { approx: true })).toBe('~955 ₪'))

  test.each(['-5', '', '1,000', 'abc', '1.'])('rejects %j', (input) =>
    expect(() => formatShekels(input)).toThrow(RangeError),
  )
})

test('formatAmount groups whole shekels without the sign', () => {
  expect(formatAmount('1234567.5')).toBe('1,234,568')
  expect(formatAmount('8300')).toBe('8,300')
  expect(() => formatAmount('8,300')).toThrow(RangeError)
})

test('normalise', () => {
  expect(normaliseMoneyInput(' 8,300 ₪ ')).toBe('8300')
  expect(normaliseMoneyInput('')).toBeNull()
  expect(() => normaliseMoneyInput('abc')).toThrow(RangeError)
})

test('dates', () => {
  expect(formatMonth('2026-09-01')).toBe('09/2026')
  expect(formatYearRange('2022-04-01', '2025-03-01')).toBe('2022–2025')
  expect(formatYearRange('2022-04-01', '2022-12-01')).toBe('2022')
})

test('formatShekelRange rounds each end and shows one shekel sign', () => {
  expect(formatShekelRange('32432.14', '34025.57')).toBe('32,432–34,026 ₪')
  expect(formatShekelRange('999.5', '1000')).toBe('1,000–1,000 ₪')
})

test('formatDate', () => {
  expect(formatDate('2026-11-02')).toBe('02.11.2026')
  expect(() => formatDate('02.11.2026')).toThrow(RangeError)
})

test('decimalText', () => {
  expect(decimalText(250000)).toBe('250000')
  expect(decimalText(0.045)).toBe('0.045')
  expect(decimalText('3.10')).toBe('3.10')
  expect(() => decimalText('x')).toThrow(RangeError)
})

test('date formatters reject non-ISO input', () => {
  expect(() => formatMonth('09/2026')).toThrow(RangeError)
  expect(() => formatYearRange('2022', '2025-03-01')).toThrow(RangeError)
})

test('isZero recognises every spelling of zero and nothing else', () => {
  for (const zero of ['0', '000', '0.00', '0.0']) expect(isZero(zero)).toBe(true)
  for (const other of ['1', '0.01', '10', '100.00']) expect(isZero(other)).toBe(false)
  expect(() => isZero('-0')).toThrow(RangeError)
})

test('formatTimestamp gives the local day and time', () => {
  const at = new Date(2026, 10, 4, 9, 5, 7)
  expect(formatTimestamp(at.toISOString())).toBe('04.11.2026 09:05:07')
  expect(() => formatTimestamp('not a time')).toThrow(RangeError)
})

test('exceeds compares decimal strings without rounding', () => {
  expect(exceeds('1000.01', '1000')).toBe(true)
  expect(exceeds('1000', '1000.00')).toBe(false)
  expect(exceeds('999.9', '1000')).toBe(false)
  expect(exceeds('10000', '9999.99')).toBe(true)
})

test('subtractAmounts works on decimal strings', () => {
  expect(subtractAmounts('55000', '10000')).toBe('45000')
  expect(subtractAmounts('100.50', '0.25')).toBe('100.25')
  expect(subtractAmounts('10.5', '10.50')).toBe('0')
  expect(() => subtractAmounts('1', '2')).toThrow(RangeError)
})

test('roundedPercent rounds half up and drops trailing zeros', () => {
  expect(roundedPercent('10.58', 1)).toBe('10.6')
  expect(roundedPercent('11.20', 1)).toBe('11.2')
  expect(roundedPercent('6.00', 1)).toBe('6')
  expect(roundedPercent('9.95', 1)).toBe('10')
  expect(roundedPercent('10.54', 1)).toBe('10.5')
  expect(roundedPercent('0.05', 1)).toBe('0.1')
})

test('groupTypedAmount groups the whole part of an amount as it is typed', () => {
  expect(groupTypedAmount('100000')).toBe('100,000')
  expect(groupTypedAmount('1,0000')).toBe('10,000')
  expect(groupTypedAmount('999')).toBe('999')
  expect(groupTypedAmount('1234567.5')).toBe('1,234,567.5')
  expect(groupTypedAmount('1000.')).toBe('1,000.')
  expect(groupTypedAmount('')).toBe('')
})

test('groupTypedAmount leaves text that is not an amount as typed', () => {
  expect(groupTypedAmount('45,000 ₪')).toBe('45,000 ₪')
  expect(groupTypedAmount('abc')).toBe('abc')
})
