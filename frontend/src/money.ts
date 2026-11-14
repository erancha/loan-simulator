/**
 * Formats and parses shekel amounts from the API's decimal strings, never via numbers, and
 * formats its ISO dates and times.
 */

const DECIMAL = /^\d+(\.\d+)?$/

function assertDecimal(text: string): void {
  if (!DECIMAL.test(text)) throw new RangeError(`not a non-negative decimal: ${JSON.stringify(text)}`)
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

function assertIsoDate(text: string): void {
  if (!ISO_DATE.test(text)) throw new RangeError(`not an ISO date: ${JSON.stringify(text)}`)
}

const ZERO = /^0+(\.0+)?$/

export function isZero(amount: string): boolean {
  assertDecimal(amount)
  return ZERO.test(amount)
}

/** Decimal text of an amount or rate the agent sent as a string or a number, without arithmetic. */
export function decimalText(value: string | number): string {
  const text = String(value)
  assertDecimal(text)
  return text
}

/** Adds one to a string of digits, carrying across 9s. */
function incrementDigits(digits: string): string {
  const chars = digits.split('')
  for (let i = chars.length - 1; i >= 0; i--) {
    if (chars[i] !== '9') {
      chars[i] = String(Number(chars[i]) + 1)
      return chars.join('')
    }
    chars[i] = '0'
  }
  return `1${chars.join('')}`
}

/**
 * Whole shekels without the sign, with thousands separators, rounded half up on the first
 * fractional digit.
 */
export function formatAmount(amount: string): string {
  assertDecimal(amount)
  const [whole, fraction = ''] = amount.split('.')
  const rounded = fraction !== '' && fraction[0] >= '5' ? incrementDigits(whole) : whole
  return rounded.replace(/\B(?=(\d{3})+$)/g, ',')
}

/** Whole shekels with the shekel sign, e.g. "32546.86" gives "32,547 ₪". */
export function formatShekels(amount: string, opts: { approx?: boolean } = {}): string {
  return `${opts.approx === true ? '~' : ''}${formatAmount(amount)} ₪`
}

/** Two amounts as one range with a single shekel sign, e.g. "32,432–34,026 ₪". */
export function formatShekelRange(low: string, high: string): string {
  return `${formatAmount(low)}–${formatAmount(high)} ₪`
}

/** The digits of an amount typed by a person; null when the field is empty. */
export function normaliseMoneyInput(text: string): string | null {
  const stripped = text.replace(/[\s,₪]/g, '')
  if (stripped === '') return null
  assertDecimal(stripped)
  return stripped
}

/** "2026-09-01" gives "09/2026". */
export function formatMonth(iso: string): string {
  assertIsoDate(iso)
  const [year, month] = iso.split('-')
  return `${month}/${year}`
}

/** The calendar years two dates fall in, as one year when they match. */
export function formatYearRange(start: string, end: string): string {
  assertIsoDate(start)
  assertIsoDate(end)
  const first = start.slice(0, 4)
  const last = end.slice(0, 4)
  return first === last ? first : `${first}–${last}`
}

/** "2026-11-02" gives "02.11.2026". */
export function formatDate(iso: string): string {
  assertIsoDate(iso)
  const [year, month, day] = iso.split('-')
  return `${day}.${month}.${year}`
}

const twoDigits = (part: number) => String(part).padStart(2, '0')

/** A moment's day in the browser's time zone, as "02.11.2026". */
export function formatDay(at: Date): string {
  return formatDate(
    [String(at.getFullYear()), twoDigits(at.getMonth() + 1), twoDigits(at.getDate())].join('-'),
  )
}

/** An ISO time as the browser's local day and time, "02.11.2026 09:05:07". */
export function formatTimestamp(iso: string): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) throw new RangeError(`not a time: ${JSON.stringify(iso)}`)
  const time = [at.getHours(), at.getMinutes(), at.getSeconds()].map(twoDigits).join(':')
  return `${formatDay(at)} ${time}`
}
