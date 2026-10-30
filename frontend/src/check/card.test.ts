import { describe, expect, test } from 'vitest'
import type { CheckEvent } from '../api/types.ts'
import {
  optionBalloon,
  optionFixed36,
  optionOfferFixed,
  optionPrime36,
  recommendationPrime,
} from '../test/fixtures.ts'
import { buildCard } from './card.ts'
import { initialState, reduce } from './events.ts'

function stateOf(...events: CheckEvent[]) {
  return events.reduce(reduce, initialState)
}

const SPITZER_BY_RATE = 'שפיצר (תשלום חודשי שווה כל עוד הריבית לא זזה)'
const SPITZER_BY_INDEX = 'שפיצר (תשלום חודשי שווה כל עוד המדד לא זז)'

const PRIME_CARD = {
  id: 'prime-36',
  label: 'מומלצת',
  track: `מסלול פריים − 0.5%, ${SPITZER_BY_RATE}, 36 חודשים`,
  source: 'לפי ריבית ממוצעת בבנקים',
  isExample: true,
  paymentToday: '904 ₪',
  chip: { tone: 'amber', text: 'עד ~955 ₪ אם הריבית תעלה כמו ב-2022–2025' },
  balloon: null,
  totalToday: '32,547 ₪',
  totalRange: '32,432–34,026 ₪ (לפי 85 תקופות מהעבר)',
}

const FIXED_CARD = {
  id: 'fixed-36',
  label: 'חלופה',
  track: 'ריבית קבועה 6.9%, שפיצר (תשלום חודשי קבוע), 36 חודשים',
  source: 'לפי ריבית ממוצעת בבנקים',
  isExample: true,
  paymentToday: '907 ₪',
  chip: { tone: 'green', text: 'התשלום לא ישתנה' },
  balloon: null,
  totalToday: '32,667 ₪',
  totalRange: null,
}

test('no options: empty card', () => {
  expect(buildCard(initialState)).toEqual({
    decision: null,
    recommended: [],
    others: null,
    reasoning: null,
    fold: null,
  })
})

test('options before a recommendation: listed under others with no decision', () => {
  const card = buildCard(stateOf(optionPrime36, optionFixed36))
  expect(card.decision).toBeNull()
  expect(card.recommended).toEqual([])
  expect(card.fold).toBeNull()
  expect(card.others?.title).toBe('האפשרויות שנבדקו')
  expect(card.others?.options).toEqual([
    { ...PRIME_CARD, label: null },
    { ...FIXED_CARD, label: null },
  ])
})

test('the reference recommendation', () => {
  const card = buildCard(stateOf(optionPrime36, optionFixed36, recommendationPrime))
  expect(card.decision).toBe(
    'הלוואה של 29,000 ₪ ל-36 חודשים, כ-904 ₪ בחודש, ו-9,000 ₪ נשארים בצד לביטחון.',
  )
  expect(card.recommended).toEqual([PRIME_CARD, FIXED_CARD])
  expect(card.others).toBeNull()
  expect(card.reasoning).toBe(recommendationPrime.data.reasoning)
  expect(card.fold).toEqual({
    ceiling: {
      amount: '1,900 ₪',
      reasons: [
        'מההכנסה המשתנה נספר רק הסכום המינימלי שמגיע גם בחודש חלש',
        'התקרה היא מחצית ממה שנשאר מההכנסה שהוזנה אחרי ההוצאות הקבועות; החצי השני נשאר להוצאות לא צפויות',
      ],
    },
    cushion: { amount: '9,000 ₪', text: 'הסכום שכדאי לא לגעת בו: הוצאות של חודשיים' },
    assumptions: [
      'ריבית בנק ישראל נכון ל-28.10.2026, מדד המחירים נכון ל-09/2026',
      'ריבית ממוצעת על הלוואות צרכניות חדשות שמפרסם בנק ישראל, עד שיוזנו הצעות אמיתיות',
      'התרחישים חוזרים על שינויי הריבית והמדד של כל תקופה בעשר השנים האחרונות',
    ],
  })
})

test('an offer after the recommendation goes under "הצעות חדשות, עוד לא נכללו בהמלצה"', () => {
  const card = buildCard(stateOf(optionPrime36, optionFixed36, recommendationPrime, optionOfferFixed))
  expect(card.recommended.map((o) => o.id)).toEqual(['prime-36', 'fixed-36'])
  expect(card.others?.title).toBe('הצעות חדשות, עוד לא נכללו בהמלצה')
  expect(card.others?.options).toEqual([
    {
      id: 'offer-hapoalim',
      label: null,
      track: 'ריבית קבועה 6.9%, שפיצר (תשלום חודשי קבוע), 36 חודשים',
      source: 'הצעה מבנק הפועלים · 02.11.2026',
      isExample: false,
      paymentToday: '890 ₪',
      chip: { tone: 'green', text: 'התשלום לא ישתנה' },
      balloon: null,
      totalToday: '32,040 ₪',
      totalRange: null,
    },
  ])
})

test('after a new recommendation, unnamed options go under "אפשרויות נוספות"', () => {
  const second: CheckEvent = {
    ...recommendationPrime,
    seq: 9,
    data: { ...recommendationPrime.data, preferred: optionOfferFixed.data, alternative: null },
  }
  const card = buildCard(stateOf(optionPrime36, optionFixed36, recommendationPrime, optionOfferFixed, second))
  expect(card.recommended.map((o) => [o.id, o.label])).toEqual([['offer-hapoalim', 'מומלצת']])
  expect(card.others?.title).toBe('אפשרויות נוספות')
  expect(card.others?.options.map((o) => o.id)).toEqual(['prime-36', 'fixed-36'])
  expect(card.fold?.assumptions[0]).toBe(
    'ריבית בנק ישראל נכון ל-28.10.2026, מדד המחירים נכון ל-09/2026',
  )
})

test('balloon option shows the balloon line with the amber chip', () => {
  const [option] = buildCard(stateOf(optionBalloon)).others!.options
  expect(option.track).toBe('מסלול פריים − 0.5%, בלון (חלק מהקרן נדחה לסוף), 36 חודשים')
  expect(option.balloon).toBe('ובסוף התקופה תשלום אחד של 10,000 ₪')
  expect(option.chip).toEqual({
    tone: 'amber',
    text: 'עד ~688 ₪ אם הריבית תעלה כמו ב-2022–2025',
  })
})

describe('a CPI-linked fixed track', () => {
  const linked = {
    ...optionFixed36,
    data: {
      ...optionFixed36.data,
      loan: { tracks: [{ ...optionFixed36.data.loan.tracks[0], annual_rate: 3.1, cpi_linked: true }] },
      figures: {
        ...optionFixed36.data.figures,
        worst_peak_payment: '980.00',
        worst_start: '2022-04-01',
        worst_end: '2025-03-01',
      },
    },
  }

  test('says prices, not the rate', () => {
    const [option] = buildCard(stateOf(linked)).others!.options
    expect(option.track).toBe(
      `ריבית קבועה 3.1%, ${SPITZER_BY_INDEX}, 36 חודשים, צמוד למדד`,
    )
    expect(option.chip).toEqual({
      tone: 'amber',
      text: 'עד ~980 ₪ אם המחירים יעלו כמו ב-2022–2025',
    })
  })
})

test('spare savings beyond the cushion are named separately', () => {
  const spare: CheckEvent = {
    ...recommendationPrime,
    data: {
      ...recommendationPrime.data,
      sizing: { ...recommendationPrime.data.sizing, spare_savings: '2500.00' },
    },
  }
  expect(buildCard(stateOf(optionPrime36, optionFixed36, spare)).decision).toBe(
    'הלוואה של 29,000 ₪ ל-36 חודשים, כ-904 ₪ בחודש, ו-9,000 ₪ נשארים בצד לביטחון ועוד 2,500 ₪ פנויים.',
  )
})

test('a prime track linked to the index says both the rate and prices', () => {
  const linked = {
    ...optionPrime36,
    data: {
      ...optionPrime36.data,
      loan: { tracks: [{ ...optionPrime36.data.loan.tracks[0], cpi_linked: true }] },
    },
  }
  const [option] = buildCard(stateOf(linked)).others!.options
  expect(option.track.endsWith(', צמוד למדד')).toBe(true)
  expect(option.chip).toEqual({
    tone: 'amber',
    text: 'עד ~955 ₪ אם הריבית והמחירים יעלו כמו ב-2022–2025',
  })
})

test('an offer source names the lender, with a hyphen before a non-Hebrew name', () => {
  const lender = (name: string) => ({
    ...optionOfferFixed,
    data: { ...optionOfferFixed.data, lender: name },
  })
  expect(buildCard(stateOf(lender('Max'))).others!.options[0].source).toBe('הצעה מ-Max · 02.11.2026')
  expect(buildCard(stateOf(lender('בנק לאומי'))).others!.options[0].source).toBe(
    'הצעה מבנק לאומי · 02.11.2026',
  )
})

test('an unknown reason code throws, naming it', () => {
  const bad: CheckEvent = {
    ...recommendationPrime,
    data: {
      ...recommendationPrime.data,
      bounds: { ...recommendationPrime.data.bounds, reasons: ['no_such_code'] },
    },
  }
  expect(() => buildCard(stateOf(optionPrime36, optionFixed36, bad))).toThrow('no_such_code')
})

test('a recommended id missing from the options throws, naming it', () => {
  expect(() => buildCard(stateOf(optionPrime36, recommendationPrime))).toThrow('fixed-36')
})
