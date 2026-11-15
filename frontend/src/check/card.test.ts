import { describe, expect, test } from 'vitest'
import type { CheckEvent } from '../api/types.ts'
import {
  ceilingSet,
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
  termNote: null,
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
  termNote: null,
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
    check: 'unchecked',
    checkNote: null,
    ceiling: { label: 'החזר חודשי מרבי', amount: 'לא נקבע', source: null },
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
    'הלוואה של 29,000 ₪ ל-36 חודשים, כ-904 ₪ בחודש.',
  )
  expect(card.recommended).toEqual([PRIME_CARD, FIXED_CARD])
  expect(card.others).toBeNull()
  expect(card.reasoning).toBe(recommendationPrime.data.reasoning)
  expect(card.fold).toEqual({
    assumptions: [
      'ריבית בנק ישראל נכון ל-28.10.2026, מדד המחירים נכון ל-09/2026',
      'ריבית ממוצעת על הלוואות צרכניות חדשות שמפרסם בנק ישראל, עד שיוזנו הצעות אמיתיות',
      'התרחישים חוזרים על שינויי הריבית והמדד של כל תקופה בעשר השנים האחרונות',
    ],
  })
})

test('an offer after the recommendation goes under "הצעות חדשות, עוד לא נכללו בהמלצה"', () => {
  const card = buildCard(
    stateOf(optionPrime36, optionFixed36, recommendationPrime, optionOfferFixed),
  )
  expect(card.recommended.map((o) => o.id)).toEqual(['prime-36', 'fixed-36'])
  expect(card.others?.title).toBe('הצעות חדשות, עוד לא נכללו בהמלצה')
  expect(card.others?.options).toEqual([
    {
      id: 'offer-hapoalim',
      label: null,
      track: 'ריבית קבועה 6.9%, שפיצר (תשלום חודשי קבוע), 36 חודשים',
      source: 'הצעה מבנק הפועלים · 02.11.2026',
      termNote: null,
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
  const card = buildCard(
    stateOf(optionPrime36, optionFixed36, recommendationPrime, optionOfferFixed, second),
  )
  expect(card.recommended.map((o) => [o.id, o.label])).toEqual([['offer-hapoalim', 'מומלצת']])
  expect(card.others?.title).toBe('אפשרויות נוספות')
  expect(card.others?.options.map((o) => o.id)).toEqual(['prime-36', 'fixed-36'])
  expect(card.fold?.assumptions[0]).toBe(
    'ריבית בנק ישראל נכון ל-28.10.2026, מדד המחירים נכון ל-09/2026',
  )
})

test('samples made for another term drop out once the term changes; offers stay', () => {
  const card = buildCard(
    stateOf(optionPrime36, optionFixed36, optionOfferFixed, {
      type: 'term.set',
      data: { term_months: 72 },
      seq: 10,
    }),
  )
  expect(card.others?.options.map((o) => o.id)).toEqual(['offer-hapoalim'])
})

test('an open offer priced at a maximum shorter than the term says so', () => {
  const capped: CheckEvent = {
    ...optionOfferFixed,
    data: { ...optionOfferFixed.data, max_term_months: 36 },
  }
  const card = buildCard(
    stateOf(capped, { type: 'term.set', data: { term_months: 72 }, seq: 10 }),
  )
  expect(card.others?.options.map((o) => o.termNote)).toEqual(['הגוף המלווה מאפשר עד 36 חודשים'])
})

test('samples for the confirmed term stay among the other options', () => {
  const card = buildCard(
    stateOf(optionPrime36, optionFixed36, { type: 'term.set', data: { term_months: 36 }, seq: 10 }),
  )
  expect(card.others?.options.map((o) => o.id)).toEqual(['prime-36', 'fixed-36'])
})

test('real offers come before samples among the other options, each in saved order', () => {
  const card = buildCard(stateOf(optionPrime36, optionFixed36, optionOfferFixed))
  expect(card.others?.options.map((o) => o.id)).toEqual(['offer-hapoalim', 'prime-36', 'fixed-36'])
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
      loan: {
        tracks: [{ ...optionFixed36.data.loan.tracks[0], annual_rate: 3.1, cpi_linked: true }],
      },
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
  expect(buildCard(stateOf(lender('Max'))).others!.options[0].source).toBe(
    'הצעה מ-Max · 02.11.2026',
  )
  expect(buildCard(stateOf(lender('בנק לאומי'))).others!.options[0].source).toBe(
    'הצעה מבנק לאומי · 02.11.2026',
  )
})

test('a recommended id missing from the options throws, naming it', () => {
  expect(() => buildCard(stateOf(optionPrime36, recommendationPrime))).toThrow('fixed-36')
})

const WITHOUT_CEILING: CheckEvent = {
  ...recommendationPrime,
  data: {
    ...recommendationPrime.data,
    payment_ceiling: null,
    ceiling_source: null,
    checked: false,
  },
}

test('an unchecked recommendation is labelled', () => {
  const card = buildCard(stateOf(optionPrime36, optionFixed36, WITHOUT_CEILING))
  expect(card.check).toBe('unchecked')
  expect(card.checkNote).toBe('ההמלצה לפי ההלוואות עצמן; עוד לא נבדקה מול ההחזר שנוח לך')
  expect(card.ceiling).toEqual({ label: 'החזר חודשי מרבי', amount: 'לא נקבע', source: null })
})

test('a recommendation made with a ceiling fits and shows the ceiling with its source', () => {
  const card = buildCard(
    stateOf(ceilingSet, optionPrime36, optionFixed36, recommendationPrime),
  )
  expect(card.check).toBe('fits')
  expect(card.checkNote).toBeNull()
  expect(card.ceiling).toEqual({
    label: 'החזר חודשי מרבי',
    amount: '1,900 ₪',
    source: 'לפי מה שאמרת',
  })
})

test('a recommendation above the ceiling shows both payments', () => {
  const lower: CheckEvent = {
    ...ceilingSet,
    seq: 7,
    data: { ...ceilingSet.data, payment_ceiling: '900' },
  }
  const card = buildCard(stateOf(optionPrime36, optionFixed36, recommendationPrime, lower))
  expect(card.check).toBe('above')
  expect(card.checkNote).toBe('מעל התקרה שלך: 955 ₪ מול 900 ₪')
})
