/**
 * Formats and parses shekel amounts from the API's decimal strings, never via numbers, and
 * formats its ISO dates and times.
 */

const DECIMAL = /^\d+(\.\d+)?$/

function assertDecimal(text: string): void {
  if (!DECIMAL.test(text)) {
    throw new RangeError(`not a non-negative decimal: ${JSON.stringify(text)}`)
  }
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

/** Whether the first amount is greater than the second, compared digit by digit. */
export function exceeds(amount: string, limit: string): boolean {
  assertDecimal(amount)
  assertDecimal(limit)
  const places = Math.max(amount.split('.')[1]?.length ?? 0, limit.split('.')[1]?.length ?? 0)
  return scaled(amount, places) > scaled(limit, places)
}

/** The digits of a decimal as one integer, scaled to the given number of places. */
function scaled(text: string, places: number): bigint {
  const [whole, fraction = ''] = text.split('.')
  return BigInt(whole + fraction.padEnd(places, '0'))
}

/** An integer scaled by 10^places, as decimal text without trailing zeros. */
function unscaled(value: bigint, places: number): string {
  const padded = value.toString().padStart(places + 1, '0')
  const whole = padded.slice(0, padded.length - places)
  const fraction = padded.slice(padded.length - places).replace(/0+$/, '')
  return fraction === '' ? whole : `${whole}.${fraction}`
}

/** a minus b, for b at most a; throws RangeError otherwise. */
export function subtractAmounts(a: string, b: string): string {
  if (exceeds(b, a)) throw new RangeError(`${b} exceeds ${a}`)
  const places = Math.max(a.split('.')[1]?.length ?? 0, b.split('.')[1]?.length ?? 0)
  return unscaled(scaled(a, places) - scaled(b, places), places)
}

/** A percent rounded half up to the given decimals, trailing zeros dropped: 10.58 -> 10.6. */
export function roundedPercent(value: string, decimals: number): string {
  assertDecimal(value)
  const [whole, fraction = ''] = value.split('.')
  const kept = BigInt(whole + fraction.padEnd(decimals, '0').slice(0, decimals))
  const next = fraction[decimals]
  return unscaled(next !== undefined && next >= '5' ? kept + 1n : kept, decimals)
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

/**
 * An amount as a person is typing it, with its whole part grouped by thousands: "100000" gives
 * "100,000". Text that is not digits with at most one fraction is returned as typed, so the form
 * that holds it can still judge it and say what is wrong.
 */
export function groupTypedAmount(text: string): string {
  const match = /^(\d+)(\.\d*)?$/.exec(text.replace(/,/g, ''))
  if (match === null) return text
  const [, whole, fraction] = match
  const grouped = whole.replace(/\B(?=(\d{3})+$)/g, ',')
  return fraction === undefined ? grouped : grouped + fraction
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
