import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import type { CheckEvent, OptionPrice, Track } from '../api/types.ts'
import {
  ceilingSet,
  loanSet,
  optionBalloon,
  optionFixed36,
  optionOfferFixed,
  optionPrime36,
  offerAwaiting,
  awaitingAvis,
  awaitingMaxShort,
  recommendationPrime,
} from '../test/fixtures.ts'
import { buildCard, comparesOptions } from './card.ts'
import { initialState, reduce } from './events.ts'

// The loan starts the month after the card is shown: shown in 11/2026, 36 months run to 11/2029.
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 10, 16))
})
afterEach(() => {
  vi.useRealTimers()
})

function stateOf(...events: CheckEvent[]) {
  return events.reduce(reduce, initialState)
}

const SPITZER_BY_RATE = 'שפיצר (תשלום חודשי שווה כל עוד הריבית לא זזה)'
const SPITZER_BY_INDEX = 'שפיצר (תשלום חודשי שווה כל עוד המדד לא זז)'

const PRIME_CARD = {
  id: 'prime-36',
  label: 'מועדפת',
  track: `מסלול פריים − 0.5%, ${SPITZER_BY_RATE}, 36 חודשים`,
  lender: 'לפי ריבית ממוצעת בבנקים',
  termNote: null,
  isExample: true,
  paymentToday: '904 ₪',
  chip: { tone: 'amber', text: 'עד ~955 ₪ אם הריבית תעלה כמו ב-2022–2025' },
  balloon: null,
  totalToday: '32,547 ₪',
  totalRange: { range: '32,432–34,026 ₪', basis: 'לפי 85 תקופות מהעבר' },
  price: null,
}

const FIXED_CARD = {
  id: 'fixed-36',
  label: 'חלופה',
  track: 'ריבית קבועה 6.9%, שפיצר (תשלום חודשי קבוע), 36 חודשים',
  lender: 'לפי ריבית ממוצעת בבנקים',
  termNote: null,
  isExample: true,
  paymentToday: '907 ₪',
  chip: { tone: 'green', text: 'התשלום לא ישתנה' },
  balloon: null,
  totalToday: '32,667 ₪',
  totalRange: null,
  price: null,
}

test('no options: empty card', () => {
  expect(buildCard(initialState)).toEqual({
    decision: null,
    check: 'unchecked',
    checkNote: null,
    ceiling: { label: 'החזר חודשי מרבי', amount: 'לא נקבע', source: null },
    recommended: [],
    others: null,
    awaiting: [],
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
    'הלוואה של 29,000 ₪ ל-36 חודשים (עד 11/2029), כ-904 ₪ בחודש.',
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
      lender: 'הצעה מבנק הפועלים · 02.11.2026',
      termNote: null,
      isExample: false,
      paymentToday: '890 ₪',
      chip: { tone: 'green', text: 'התשלום לא ישתנה' },
      balloon: null,
      totalToday: '32,040 ₪',
      totalRange: null,
      price: {
        interest: 'ריבית: כ-3,040 ₪ על 29,000 ₪',
        rate: '6.9% היום — מתחת לריבית הממוצעת בבנקים להלוואה צרכנית, כ-7.9% (נכון ל-08/2026)',
      },
    },
  ])
})

describe("a real offer's price", () => {
  const offerAt = (price: Partial<OptionPrice>, track: Partial<Track> = {}) => ({
    ...optionOfferFixed,
    data: {
      ...optionOfferFixed.data,
      loan: { tracks: [{ ...optionOfferFixed.data.loan.tracks[0], ...track }] },
      figures: {
        ...optionOfferFixed.data.figures,
        price: { ...optionOfferFixed.data.figures.price!, ...price },
      },
    },
  })
  const priceOf = (event: CheckEvent) => buildCard(stateOf(event)).others!.options[0].price

  test('a rate above the market average says so with both rates and the month', () => {
    expect(priceOf(offerAt({ rate_today: '10.75', against_market: 'above' }))).toEqual({
      interest: 'ריבית: כ-3,040 ₪ על 29,000 ₪',
      rate: '10.75% היום — מעל הריבית הממוצעת בבנקים להלוואה צרכנית, כ-7.9% (נכון ל-08/2026)',
    })
  })

  test('a rate within the band reads as similar to the average', () => {
    expect(priceOf(offerAt({ rate_today: '8', against_market: 'similar' }))?.rate).toBe(
      '8% היום — דומה לריבית הממוצעת בבנקים להלוואה צרכנית, כ-7.9% (נכון ל-08/2026)',
    )
  })

  test('a CPI-linked rate is on top of the index, with no comparison', () => {
    const linked = offerAt(
      { rate_today: '4', against_market: null },
      { annual_rate: '4', cpi_linked: true },
    )
    expect(priceOf(linked)).toEqual({
      interest: 'ריבית והצמדה: כ-3,040 ₪ על 29,000 ₪',
      rate: '4% מעל המדד',
    })
  })

  test('an offer stored before the engine priced rates shows its interest cost only', () => {
    const { price: _, ...figures } = optionOfferFixed.data.figures
    const old = { ...optionOfferFixed, data: { ...optionOfferFixed.data, figures } }
    expect(priceOf(old)).toEqual({ interest: 'ריבית: כ-3,040 ₪ על 29,000 ₪', rate: null })
  })
})

test('a recommendation of the only option on the card carries no label', () => {
  const only: CheckEvent = {
    ...recommendationPrime,
    seq: 9,
    data: { ...recommendationPrime.data, preferred: optionOfferFixed.data, alternative: null },
  }
  const state = stateOf(optionOfferFixed, only)
  expect(buildCard(state).recommended.map((o) => [o.id, o.label])).toEqual([
    ['offer-hapoalim', null],
  ])
  expect(comparesOptions(state)).toBe(false)
  expect(comparesOptions(stateOf(optionPrime36, optionFixed36, recommendationPrime))).toBe(true)
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
  expect(card.recommended.map((o) => [o.id, o.label])).toEqual([['offer-hapoalim', 'מועדפת']])
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

test('the other options are listed cheapest first', () => {
  const cheaper = { ...optionOfferFixed.data, option_id: 'offer-cheaper', lender: 'הארי פוטר' }
  cheaper.figures = { ...cheaper.figures, total_paid: '31000.00' }
  const card = buildCard(stateOf(optionOfferFixed, { ...optionOfferFixed, data: cheaper, seq: 8 }))
  expect(card.others?.options.map((o) => o.id)).toEqual(['offer-cheaper', 'offer-hapoalim'])
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

test('a CPI-linked example names the pension fund terms it follows', () => {
  const pension = {
    ...optionFixed36,
    data: {
      ...optionFixed36.data,
      loan: {
        tracks: [{ ...optionFixed36.data.loan.tracks[0], annual_rate: 4, cpi_linked: true }],
      },
    },
  }
  const [option] = buildCard(stateOf(pension)).others!.options
  expect(option.lender).toBe('לפי תנאים שקרן פנסיה מפרסמת לעמיתיה')
  expect(option.isExample).toBe(true)
  expect(buildCard(stateOf(optionFixed36)).others!.options[0].lender).toBe(
    'לפי ריבית ממוצעת בבנקים',
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

test('an offer names its lender, with a hyphen before a non-Hebrew name', () => {
  const lender = (name: string) => ({
    ...optionOfferFixed,
    data: { ...optionOfferFixed.data, lender: name },
  })
  expect(buildCard(stateOf(lender('Max'))).others!.options[0].lender).toBe(
    'הצעה מ-Max · 02.11.2026',
  )
  expect(buildCard(stateOf(lender('בנק לאומי'))).others!.options[0].lender).toBe(
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

test('a recommendation above the ceiling only in the worst period says it fits today', () => {
  const between: CheckEvent = {
    ...ceilingSet,
    seq: 7,
    data: { ...ceilingSet.data, payment_ceiling: '930' },
  }
  const card = buildCard(stateOf(optionPrime36, optionFixed36, recommendationPrime, between))
  expect(card.check).toBe('history')
  expect(card.checkNote).toBe(
    'בתוך התקרה שלך היום; בתקופה הגרועה בעבר ההחזר היה מגיע ל-955 ₪ מול 930 ₪',
  )
})

test('awaiting offers are listed by lender and are not among the options', () => {
  const card = buildCard(stateOf(optionPrime36, offerAwaiting(20, awaitingAvis)))
  expect(card.awaiting).toEqual(['סוכנות אוויס רכבים: ממתינה לבירור סוג ההלוואה, לא נכללת בהשוואה'])
  expect(card.others?.options.map((o) => o.id)).toEqual(['prime-36'])
})

test('an offer quoted for less than the loan is listed as awaiting the loan amount', () => {
  const card = buildCard(stateOf(loanSet, offerAwaiting(20, awaitingMaxShort)))
  expect(card.awaiting).toEqual(['מקס: ממתינה לתשובה על סכום ההלוואה, לא נכללת בהשוואה'])
})
