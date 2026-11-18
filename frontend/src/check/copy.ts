/** Every Hebrew label and sentence on a check's page: the conversation and the card. */
import type {
  CeilingBasis,
  CeilingSource,
  ChartShown,
  Finances,
  LoanRequest,
  OfferDropped,
  OfferIdentified,
  OptionPrice,
  Question,
  QuestionField,
  Reading,
  ReadingKind,
  TermBasis,
  Track,
  TypeWord,
} from '../api/types.ts'
import { OFFER_SOURCES } from '../copy.ts'
import {
  exceeds,
  formatAmount,
  formatDate,
  formatDay,
  formatMonth,
  formatShekels,
  roundedPercent,
} from '../money.ts'

export const RATE_KIND = {
  fixed: 'ריבית קבועה',
  prime: 'מסלול פריים',
} as const satisfies Record<Track['rate_kind'], string>

export const CPI_LINKED = 'צמוד למדד'

export const METHOD = {
  spitzer: 'שפיצר (תשלום חודשי קבוע)',
  equal_principal: 'קרן שווה (התשלום יורד עם הזמן)',
  balloon: 'בלון (חלק מהקרן נדחה לסוף)',
} as const satisfies Record<Track['method'], string>

/** A spitzer payment that moves, named by what moves it: the prime rate, the index, or both. */
export const SPITZER_MOVING = {
  rate: 'שפיצר (תשלום חודשי שווה כל עוד הריבית לא זזה)',
  index: 'שפיצר (תשלום חודשי שווה כל עוד המדד לא זז)',
  both: 'שפיצר (תשלום חודשי שווה כל עוד הריבית והמדד לא זזים)',
} as const satisfies Record<string, string>

export const LABEL_PREFERRED = 'מועדפת'
export const LABEL_ALTERNATIVE = 'חלופה'

/** Where an example's rate comes from: the unlinked ones from the bank average, the
 * CPI-linked one from the terms a pension fund publishes for loans to its members. */
export const SOURCE_EXAMPLE = {
  bankAverage: 'לפי ריבית ממוצעת בבנקים',
  pensionFund: 'לפי תנאים שקרן פנסיה מפרסמת לעמיתיה',
} as const satisfies Record<string, string>
/** Marks an option nobody can take, so it never reads as a real offer. */
export const CHIP_EXAMPLE = 'דוגמא'
export const EXAMPLES_NOTE =
  'מחושב לפי ממוצעים ותנאים מפורסמים. אי אפשר לקחת הלוואה כזו: היא מוצגת רק עד שתוזן הצעה' +
  ' אמיתית.'

const HEBREW_LETTER = /^[\u05D0-\u05EA]/

/** A lender's name after "from": `מ` before a Hebrew letter, `מ-` otherwise. */
export function fromLender(lender: string): string {
  return `${HEBREW_LETTER.test(lender) ? 'מ' : 'מ-'}${lender}`
}

export function offerSource(lender: string | null, date: string | null): string {
  const from = lender === null ? 'הצעה' : `הצעה ${fromLender(lender)}`
  return date === null ? from : `${from} · ${date}`
}

export const CHIP_UNCHANGING = 'התשלום לא ישתנה'

/** What would have to happen again for the payment to reach its worst level. */
export function chipText(
  amount: string,
  years: string,
  change: { prime: boolean; cpiLinked: boolean },
): string {
  const what = change.prime
    ? change.cpiLinked
      ? 'הריבית והמחירים יעלו'
      : 'הריבית תעלה'
    : 'המחירים יעלו'
  return `עד ${amount} אם ${what} כמו ב-${years}`
}

/** What a real offer costs over its principal; a linked loan's cost holds the CPI's rise too. */
export function interestLine(cost: string, principal: string, cpiLinked: boolean): string {
  return `${cpiLinked ? 'ריבית והצמדה' : 'ריבית'}: כ-${cost} על ${principal}`
}

const AGAINST_MARKET = {
  above: 'מעל הריבית הממוצעת',
  similar: 'דומה לריבית הממוצעת',
  below: 'מתחת לריבית הממוצעת',
} as const satisfies Record<NonNullable<OptionPrice['against_market']>, string>

/** An unlinked offer's rate today against the bank average on consumer loans, with its month. */
export function rateAgainstMarketLine(
  rate: string,
  against: keyof typeof AGAINST_MARKET,
  marketRate: string,
  month: string,
): string {
  return (
    `${rate}% היום — ${AGAINST_MARKET[against]} בבנקים להלוואה צרכנית, ` +
    `כ-${marketRate}% (נכון ל-${month})`
  )
}

/** A linked offer's rate, which is on top of the CPI. */
export function rateOverIndexLine(rate: string): string {
  return `${rate}% מעל המדד`
}

export function balloonLine(amount: string): string {
  return `ובסוף התקופה תשלום אחד של ${amount}`
}

export function totalRangeText(range: string, windows: number): string {
  return `${range} (לפי ${windows} תקופות מהעבר)`
}

export function termText(months: number): string {
  return `${months} חודשים`
}

/** The title over the decision line: it sums up the loan being looked for. */
export const DECISION_TITLE = 'מה מחפשים'

/** The loan's last month as MM/YYYY, for a loan that starts the month after `today`. */
export function lastMonthText(termMonths: number, today: Date): string {
  const last = new Date(today.getFullYear(), today.getMonth() + termMonths, 1)
  return `${String(last.getMonth() + 1).padStart(2, '0')}/${last.getFullYear()}`
}

/** The term line of a reply's data block, "מספר החודשים: 60", unless it names its last month. */
const REPLY_TERM_LINE = /מספר החודשים: (\d+)(?!\d| \(עד)/g

/** A reply with its term line followed by the loan's last month, as the card's decision shows. */
export function withLastMonth(text: string, today: Date): string {
  return text.replace(
    REPLY_TERM_LINE,
    (line: string, months: string) => `${line} (עד ${lastMonthText(Number(months), today)})`,
  )
}

export function decisionText(
  loanAmount: string,
  termMonths: number,
  monthlyPayment: string,
  today: Date,
): string {
  const term = `${termText(termMonths)} (עד ${lastMonthText(termMonths, today)})`
  return `הלוואה של ${loanAmount} ל-${term}, כ-${monthlyPayment} בחודש.`
}

/** Under the decision of a recommendation made without a payment ceiling. */
export const UNCHECKED_NOTE = 'ההמלצה לפי ההלוואות עצמן; עוד לא נבדקה מול ההחזר שנוח לך'

/** Under the decision of a recommendation whose worst-case payment passes the ceiling. */
export function aboveCeilingText(worst: string, ceiling: string): string {
  return `מעל התקרה שלך: ${formatShekels(worst)} מול ${formatShekels(ceiling)}`
}

/** Under the decision of a recommendation within the ceiling today, above it only in the worst
 * period history holds. */
export function historyAboveCeilingText(worst: string, ceiling: string): string {
  return `בתוך התקרה שלך היום; בתקופה הגרועה בעבר ההחזר היה מגיע ל-${formatShekels(worst)}` +
    ` מול ${formatShekels(ceiling)}`
}

/** A check's title in the checks list: its purpose, or the general label, and its amount. */
export function checkTitle(loan: LoanRequest): string {
  return `${loan.purpose ?? GENERAL_PURPOSE} - הלוואה בסך ${formatAmount(loan.amount)}₪`
}

export const OTHERS_TITLE = {
  checked: 'האפשרויות שנבדקו',
  newSinceRecommendation: 'הצעות חדשות, עוד לא נכללו בהמלצה',
  further: 'אפשרויות נוספות',
} as const satisfies Record<string, string>

export function dataDatesLine(rateDate: string, cpiMonth: string): string {
  return `ריבית בנק ישראל נכון ל-${rateDate}, מדד המחירים נכון ל-${cpiMonth}`
}

export const PUBLISHED_RATE_LINE =
  'ריבית ממוצעת על הלוואות צרכניות חדשות שמפרסם בנק ישראל, עד שיוזנו הצעות אמיתיות'

// The engine's HISTORY_MONTHS, in mcp-server/src/loan_engine/domain/assumptions.py.
export const HISTORY_LINE = 'התרחישים חוזרים על שינויי הריבית והמדד של כל תקופה בעשר השנים האחרונות'

export const FOLD_TITLE = 'למה המספרים האלה'

export const TOTALS_HEADINGS = {
  option: 'אפשרות',
  today: 'סך התשלומים בתנאי היום',
  range: 'טווח בתרחישים',
} as const

/** In the range column, for an option whose total cannot change. */
export const NO_RANGE = '—'

export function monthlyPayment(amount: string): string {
  return `${amount} בחודש`
}

export const CARD_FAILED = 'לא הצלחנו להציג את ההמלצה.'

/** The market-data sample, offered at any point of a conversation; the server answers it from
 * the market data with no model call. A tap fills the input, for the person to send. */
export const MARKET_SAMPLE = {
  label: 'פריים ומדדים',
  text:
    'מהי ריבית הפריים הנוכחית, ומה היו השינויים ב-5 השנים האחרונות?\n' +
    'מה היו המדדים לצרכן ב-12 החודשים האחרונים?',
}

/** The real-offer sample, offered once a check has a loan and a term: the way to open the empty
 * offer form at any time. A tap sends it at once, and the server answers it with the form and no
 * model call; an offer in the person's own words goes through the chat box instead. */
export const OFFER_SAMPLE = {
  label: 'הצעה מגוף מלווה',
  text: 'קיבלתי הצעה להלוואה מגוף מלווה',
  sendsAtOnce: true,
}

export const NEXT_STEP_TITLE = 'מה הלאה'
export const NEXT_STEP =
  `להביא הצעות אמיתיות מ${OFFER_SOURCES}, ולהזין אותן כאן בשיחה עם "${OFFER_SAMPLE.label}".`
export const OFFER_DETAILS =
  'בכל הצעה כדאי לבקש: ריבית (או פריים ומרווח), הצמדה, מספר חודשים, שיטת החזר, עמלות, בלון, שם' +
  ' הגוף ותאריך.'

export const EMPTY_CARD = 'ההמלצה תופיע כאן אחרי שנכיר את ההלוואה.'

export const THINKING = 'העוזר חושב…'
export const INPUT_PLACEHOLDER = {
  idle: 'אפשר לכתוב כאן…',
  running: THINKING,
} as const
export const INPUT_LABEL = 'הודעה לעוזר'
export const SEND_BUTTON = 'שליחה'

const twoDigits = (value: number) => String(value).padStart(2, '0')

function sameDay(a: Date, b: Date): boolean {
  return a.toDateString() === b.toDateString()
}

/**
 * The message cap counts a rolling window, so sending may resume today, tomorrow or later; `next`
 * is shown in local time.
 */
export function capNotice(next: Date, now: Date): string {
  const time = `${twoDigits(next.getHours())}:${twoDigits(next.getMinutes())}`
  const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)
  const when = sameDay(next, now)
    ? `ב-${time}`
    : sameDay(next, tomorrow)
      ? `מחר ב-${time}`
      : `ב-${twoDigits(next.getDate())}.${twoDigits(next.getMonth() + 1)} ב-${time}`
  return `הגעתם למכסת ההודעות. אפשר להמשיך ${when}`
}

export function sendFailed(message: string): string {
  return `ההודעה לא נשלחה: ${message}`
}

/** The purpose a loan without one is titled by; also the last purpose choice. */
export const GENERAL_PURPOSE = 'כללי'
export const PURPOSE_CHOICES = ['רכב', 'שיפוץ', GENERAL_PURPOSE]
export const SKIP = 'דילוג'
export const ANSWER = 'אישור'
export const CONTINUE = 'המשך'
/** Sent as the person's message, as it is, when they cannot name a comfortable payment. */
export const DONT_KNOW = 'לא יודע/ת'

export const TERM_MIN_MONTHS = 6
export const TERM_MAX_MONTHS = 84
export const TERM_BOX_LABEL = 'מספר חודשים'
export const TERM_BOX_PLACEHOLDER = `${TERM_MIN_MONTHS}–${TERM_MAX_MONTHS}`
/** A ceiling the check holds cannot be removed from the term card, only replaced. */
export const CEILING_CLEARED = 'אפשר להקליד החזר מרבי אחר, אך לא למחוק אותו'
/** An offer priced at its lender's maximum, shorter than the check's term. */
export const offerMaxNote = (months: number) => `הגוף המלווה מאפשר עד ${termText(months)}`
/**
 * The line a confirmed term sends, naming a ceiling typed beside it; the prompt reads its
 * "אישור:" as a term and ceiling already saved.
 */
export function confirmedTermLine(months: number, ceiling: string | null): string {
  const term = `אישור: ${termText(months)}`
  return ceiling === null ? term : `${term}, ${CEILING_LABEL}: ${amountText(ceiling)}`
}
export const TERM_OUT_OF_RANGE =
  `אפשר להקליד מספר חודשים שלם בין ${TERM_MIN_MONTHS} ל-${TERM_MAX_MONTHS}`

/**
 * The person's message for an answered question; the agent's prompt quotes this form. A label
 * that is itself a question takes its value after a space.
 */
export function answerLine(label: string, value: string): string {
  return label.endsWith('?') ? `${label} ${value}` : `${label}: ${value}`
}

/** An amount as an answer line shows it. */
export function amountText(value: string): string {
  return formatShekels(value)
}

/** The person's message for a skipped question; the agent's prompt quotes this form. */
export function skipLine(label: string): string {
  return `דילוג על: ${label}`
}

/** The income and expenses labels and hints, shared by the question bubble and the data panel. */
export const INCOME_LABEL = 'הכנסה קבועה'
export const INCOME_HINT =
  'המשכורת שנכנסת לחשבון כל חודש, אחרי מסים וניכויים, ועוד ההכנסה המשתנה שנכנסת גם בחודש חלש.'
export const EXPENSES_LABEL = 'הוצאות קבועות'
export const EXPENSES_HINT =
  'מה שיוצא ממך כל חודש: שכר דירה, מזון וקניות, חשבונות, ביטוחים, תחבורה, בילויים, וגם' +
  ' החזרים על הלוואות קיימות. גרים עם עוד אנשים? רק החלק שלך.'

/**
 * What each asked field shows: `label` names it in the person's answer line, `text` is the
 * question the bubble asks, and `hint` says what goes in the box.
 */
const FIELD_COPY: Record<QuestionField, { label: string; text: string; hint: string }> = {
  purpose: {
    label: 'מה רוצים לקנות?',
    text: 'מה רוצים לקנות?',
    hint: 'להלוואה בלי מטרה מסוימת בוחרים "כללי". מטרה אחרת אפשר לכתוב בתיבה למטה.',
  },
  amount: {
    label: 'כמה צריך ללוות?',
    text: 'כמה צריך ללוות?',
    hint: 'סכום ההלוואה, בשקלים.',
  },
  own_capital: {
    label: 'כמה מהמחיר משולם מכסף שכבר יש?',
    text: 'כמה מהמחיר משולם מכסף שכבר יש?',
    hint: 'הסכום שמשלמים מהכסף שלכם. אם הכול נלקח בהלוואה, כתבו 0.',
  },
  net_fixed_income: {
    label: INCOME_LABEL,
    text: 'מה ההכנסה הקבועה שלך בחודש, נטו?',
    hint: INCOME_HINT,
  },
  fixed_expenses: {
    label: EXPENSES_LABEL,
    text: 'כמה יוצא כל חודש על הוצאות קבועות?',
    hint: EXPENSES_HINT,
  },
  payment_ceiling: {
    label: 'מה ההחזר החודשי הגבוה ביותר שנוח לך?',
    text: 'מה ההחזר החודשי הגבוה ביותר שנוח לך?',
    hint: 'הסכום החודשי שאפשר לעמוד בו גם בחודש קשה.',
  },
}

/** The label a field carries in a question and in the answer line. */
export function fieldLabel(field: QuestionField): string {
  return FIELD_COPY[field].label
}

/** The offer to clone a check before changing its recommendation; the prompt quotes the choices. */
export const CLONE_QUESTION =
  'לשכפל את הבדיקה ולבצע סימולציה נפרדת? כך אפשר יהיה להשוות בין הבדיקות.'
export const CLONE_CHOICE = 'לשכפל ולבדוק בנפרד'
/** The clone's first line: the choice and the request that brought the offer, which the clone
 * carries out; the prompt reads the request after the colon. */
export const cloneLine = (request: string) => `${CLONE_CHOICE}: ${request}`
export const STAY_CHOICE = 'לעדכן את הבדיקה הזאת'

const INITIAL_CALCULATION = 'חישוב ראשוני: '
const SHORTER_TERM = 'אפשר לקצר: '

/**
 * The term question's card line: the term and the first payment it gives. The card worked out
 * from the simulator's own assumed payment is titled an initial calculation, and the card of a
 * shorter term the recommendation suggests is titled a possible shortening, so a card the person
 * did not ask for says what it is; a term that follows the person's ceiling or that they typed
 * has no title.
 */
export function termLine(termMonths: number, firstPayment: string, basis?: TermBasis): string {
  const line = `${termText(termMonths)} · החזר ראשון כ-${formatShekels(firstPayment)}`
  if (basis?.kind === 'first_payment_target') return `${INITIAL_CALCULATION}${line}`
  return basis?.kind === 'shorter' ? `${SHORTER_TERM}${line}` : line
}

const LONGEST_TERM = `גם ב-${termText(TERM_MAX_MONTHS)}, התקופה הארוכה ביותר שהסימולטור מחשב,`
const CHANGE_TERM_OR_CEILING = 'אפשר לשנות כאן את מספר החודשים, או לכתוב החזר חודשי מרבי אחר.'
const SHORTEN_TERM_OR_NAME_CEILING = 'אפשר לקצר כאן את מספר החודשים, או לכתוב החזר חודשי מרבי.'
const CHANGE_PARAMETERS = 'אפשר לשנות כאן את הפרמטרים.'

/**
 * The term card's line under its title: what the term was worked out from. The first payment the
 * simulator aims at before the person named one is its own starting point, so a loan that cannot
 * meet it even at the longest term is told what that term gives, the lowest payment the loan
 * allows, with no word of an amount nobody chose.
 */
export function termBasisLine(basis: TermBasis, firstPayment: string): string {
  if (basis.kind === 'typed') return `זה החישוב למספר החודשים שבחרת. ${CHANGE_PARAMETERS}`
  const amount = formatShekels(basis.amount)
  if (basis.kind === 'shorter') {
    return (
      `זה מספר החודשים המיטבי לפי ההחזר החודשי המרבי שלך, ${amount}: במקום` +
      ` ${termText(basis.from_term_months)}, ההחזר נשאר עד` +
      ` כ-${formatShekels(basis.worst_payment)} גם אם הריבית תעלה כמו בעבר, והסכום הכולל להחזר` +
      ` קטן ב-${formatShekels(basis.saving)}.` +
      ` ${CHANGE_PARAMETERS}`
    )
  }
  if (basis.kind === 'first_payment_target') {
    return basis.fits
      ? `בהנחה ראשונית שההחזר החודשי יהיה עד כ-${amount}, זה מספר החודשים המתאים, לפי` +
          ` הריבית הממוצעת בבנקים. ${CHANGE_TERM_OR_CEILING}`
      : `${termText(TERM_MAX_MONTHS)} היא התקופה הארוכה ביותר שהסימולטור מחשב. בתקופה כזו` +
          ` ההחזר החודשי הנמוך ביותר הוא כ-${formatShekels(firstPayment)} בהתחלה, לפי הריבית` +
          ` הממוצעת בבנקים. ${SHORTEN_TERM_OR_NAME_CEILING}`
  }
  return basis.fits
    ? `לפי ההחזר החודשי המרבי שלך, ${amount}, זה מספר החודשים המתאים, גם אם הריבית תעלה כמו` +
        ` בעבר. ${CHANGE_PARAMETERS}`
    : `${LONGEST_TERM} ההחזר עלול לעלות על ההחזר החודשי המרבי שלך, ${amount}, אם הריבית תעלה` +
        ` כמו בעבר. ${CHANGE_PARAMETERS}`
}

/** The chips that ask for the terms card, shorter or longer than the recommended option's term.
 * A tap sends the sentence at once; the agent answers it with the card. */
export const SHORTER_TERMS_CHIP = {
  label: 'קיצור תקופה',
  text: 'אפשר לראות סימולציה בתקופה קצרה יותר, עם פחות תשלומים?',
  sendsAtOnce: true,
}
export const LONGER_TERMS_CHIP = {
  label: 'הארכת תקופה',
  text: 'אפשר לראות סימולציה בתקופה ארוכה יותר, עם החזר חודשי נמוך יותר?',
  sendsAtOnce: true,
}

/** Terms as a Hebrew list: "72, 66 ו-60 חודשים". */
function termsListText(terms: number[]): string {
  const last = terms.at(-1)
  if (last === undefined) throw new Error('a terms card lists at least one term')
  const head = terms.slice(0, -1).join(', ')
  return head === '' ? termText(last) : `${head} ו-${termText(last)}`
}

/** The terms card's title: the terms it priced, the option's own first. */
export function termsTitle(terms: number[]): string {
  return `חישבתי את ההמלצה ל-${termsListText(terms)}`
}

export const TERMS_HEADINGS = {
  term: 'חודשים',
  today: 'החזר היום',
  worst: 'בתקופה הגרועה בעבר',
} as const

/** The worst-period cell of a payment that never changes. */
export const STEADY_PAYMENT = 'קבוע'
/** In place of a choice button on the row of the term the check already has. */
export const CURRENT_TERM = 'התקופה הנוכחית'
export const CHOOSE_TERM = 'לבחור'

/** Under the terms card's table: what a marked worst-period payment means. */
export function termsCeilingNote(ceiling: string): string {
  return `מסומן: ההחזר היה עובר את התקרה שלך, ${formatShekels(ceiling)}, בתקופה הגרועה בעבר.` +
    ' אפשר לבחור גם מספר חודשים כזה.'
}

/** The question a bubble shows: a field's question, the term card, the terms card, the clone
 * offer, or the model's own sentence. */
export function questionText(question: Question): string {
  if (question.kind === 'term') {
    return termLine(question.term_months, question.first_payment, question.basis)
  }
  if (question.kind === 'terms') return termsTitle(question.rows.map((row) => row.term_months))
  if (question.kind === 'offer') return OFFER_FORM_TITLE
  if (question.offer_clone === true) return CLONE_QUESTION
  const { field } = question
  return field === null ? question.text : FIELD_COPY[field].text
}

/** A field's label, a card's title, the clone offer, or the model's own sentence. */
export function questionLabel(question: Question): string {
  if (question.kind !== undefined) return questionText(question)
  if (question.offer_clone === true) return CLONE_QUESTION
  return question.field === null ? question.text : fieldLabel(question.field)
}

/** A field's hint; a free question and the cards have none. */
export function questionHint(question: Question): string | null {
  if (question.kind !== undefined || question.field === null) return null
  return FIELD_COPY[question.field].hint
}

/** Under the reply that presents a recommendation, on a screen that shows one pane at a time: the
 * way to the pane with the tracks' details, named by its tab. */
export const TO_CARD = 'לפירוט המסלולים: מעבר ללשונית "המלצה"'

export const OFFER_FORM_TITLE = 'פרטי ההצעה'
export const OFFER_FORM_INTRO =
  'קיבלת הצעות להלוואה מגופים מלווים? אפשר לתאר אותן כאן, או בצ\'אט למטה, והסימולטור ישווה אותן.'
export const OFFER_LENDER_LABEL = 'מי הגוף המלווה?'
export const OFFER_TRACKS_LABEL = 'המסלולים שהוצעו'
export const OFFER_MONTHS_LABEL = 'לכמה חודשים לכל היותר?'
export const OFFER_MONTHS_UNIT = 'חודשים'
export const OFFER_LINKED = 'צמוד למדד'
export const OFFER_ADD_TRACK = '+ מסלול נוסף'
export const OFFER_REMOVE_TRACK = 'הסרת המסלול'
export const OFFER_NOTE = 'ההחזר מחושב בתשלומים חודשיים שווים, על סכום ההלוואה שבבדיקה.'

/** How a track of an offer prices its interest: a margin over or under prime, or a fixed rate. */
export type OfferKind = 'prime_plus' | 'prime_minus' | 'fixed'
export const OFFER_KIND_LABEL: Record<OfferKind, string> = {
  prime_plus: 'פריים פלוס',
  prime_minus: 'פריים מינוס',
  fixed: 'ריבית קבועה',
}

/** The names a screen reader gives the boxes of the form's track row, numbered from 1. */
export const offerKindBox = (row: number) => `סוג המסלול ${row}`
export const offerRateBox = (row: number) => `אחוז של מסלול ${row}`

export const OFFER_MAX_TRACKS = 4
/**
 * The highest percent a row of each kind takes. The engine prices fixed interest up to 30%, and a
 * margin over prime is held to it too. Prime is the Bank of Israel rate plus 1.5 (the engine's
 * PRIME_MARGIN), so a margin under prime goes no lower than the Bank of Israel rate itself.
 */
export const OFFER_MAX_RATE: Record<OfferKind, number> = {
  prime_plus: 30,
  prime_minus: 1.5,
  fixed: 30,
}
/** An offer's longest period is a limit, not the loan's term, so it may pass the term's range. */
export const OFFER_MAX_MONTHS = 360

export const OFFER_LENDER_MISSING = 'חסר שם הגוף המלווה'
export const offerRateInvalid = (kind: OfferKind) => `צריך אחוז בין 0 ל-${OFFER_MAX_RATE[kind]}`
export const OFFER_FIX_ABOVE = 'צריך לתקן את המסומן למעלה'
export const OFFER_TRACK_REPEATED = 'המסלול הזה כבר מופיע למעלה'
export const OFFER_MONTHS_INVALID = `צריך מספר חודשים שלם, ${TERM_MIN_MONTHS} לפחות`

/** A track of the offer form once valid: `rate` is an unsigned decimal string. */
export interface OfferTrack {
  kind: OfferKind
  rate: string
  linked: boolean
}

/**
 * The message the offer form sends: a complete offer in the words the model reads typed offers
 * in. The lender's name follows its own label, so the model never takes "גוף מלווה" for it.
 * Every track says whether it is linked, so the model has nothing left to ask, and names its
 * kind by the form's own label: a margin under prime written with a minus sign would read as a
 * dash.
 */
export function offerLine(lender: string, tracks: OfferTrack[], months: number): string {
  const listed = tracks.map(
    (track, index) =>
      `(${index + 1}) ${OFFER_KIND_LABEL[track.kind]} ${track.rate}%, ` +
      (track.linked ? OFFER_LINKED : `לא ${OFFER_LINKED}`),
  )
  return (
    `קיבלתי הצעה. הגוף המלווה: ${lender}. ${listed.join(' ')}.` +
    ` לתקופה של עד ${months} ${OFFER_MONTHS_UNIT}, בתשלומים חודשיים שווים.`
  )
}

/** A market chart's title, by series. */
export const CHART_TITLE: Record<ChartShown['series'], string> = {
  prime: 'ריבית הפריים, לפי חודש',
  cpi: 'השינוי החודשי במדד המחירים לצרכן',
}

/** Where a chart's figures come from and how recent they are. */
export function chartSource(series: ChartShown['series'], asOf: string): string {
  return series === 'prime'
    ? `לפי נתוני בנק ישראל, נכון ל-${formatDate(asOf)}`
    : `לפי נתוני הלשכה המרכזית לסטטיסטיקה, עד ${formatMonth(asOf)}`
}

/** The column headings of a chart's table for screen readers. */
export const CHART_MONTH = 'חודש'
export const CHART_VALUE: Record<ChartShown['series'], string> = { prime: 'פריים', cpi: 'שינוי' }

/** The accessible name of the border that widens the card pane. */
export const RESIZE_CARD = 'שינוי רוחב חלונית ההמלצה'

export const ARCHIVED_TITLE = 'הבדיקה נסגרה והועברה לארכיון.'
export const CLONED_TITLE = 'הבדיקה שוכפלה לבדיקה נפרדת.'
export const OPEN_CLONE = 'מעבר לבדיקה החדשה'

/** The closing line of a check the person archived. */
export function manualArchiveLine(at: Date): string {
  return `ב-${formatDay(at)} הבדיקה הועברה לארכיון ידנית.`
}

/** Shown in an empty money field. */
export const NOT_COUNTED_YET = 'עוד לא הוזן'
/** The accessible name of the button that opens a field's hint. */
export const HINT_LABEL = 'הסבר'
export const NOT_A_NUMBER = 'אפשר להקליד רק מספר, למשל 12,500'
export const refused = (reason: string) => `הערך לא התקבל: ${reason}`
export const saveFailed = (message: string) => `השמירה לא הצליחה: ${message}`

/** Opens the check's two finances figures for editing. */
export const EDIT_FINANCES = 'עריכה'
export const CEILING_LABEL = 'החזר חודשי מרבי'
export const CEILING_NOT_SET = 'לא נקבע'

/** How a ceiling derived from the finances was reached: the lower of its two caps, in words. */
export function ceilingFormula(basis: CeilingBasis, finances: Finances): string {
  const { net_fixed_income: income, fixed_expenses: expenses } = finances
  if (income === null || expenses === null) {
    throw new Error('a derived ceiling needs both finances figures')
  }
  if (exceeds(basis.ceiling_by_disposable_income, basis.ceiling_by_income_share)) {
    return `(${roundedPercent(basis.income_percent, 1)}% מהכנסה של ${formatShekels(income)})`
  }
  return (
    `(${roundedPercent(basis.disposable_percent, 1)}% מההפרש בין הכנסה של ` +
    `${formatShekels(income)} להוצאות של ${formatShekels(expenses)})`
  )
}
export const CEILING_SOURCE = {
  stated: 'לפי מה שאמרת',
  finances: 'לפי ההכנסה וההוצאות',
} as const satisfies Record<CeilingSource, string>

/** The person's message for a figure edited in the data panel; the agent's prompt quotes it. */
export function updateLine(label: string, amount: string): string {
  return `עודכן: ${label} ${amountText(amount)}`
}

export const OPENING_TITLE = 'פרטי ההלוואה'
export const OPENING_PURPOSE_LABEL = 'מטרה'
export const OPENING_MODE_LABEL = 'איך נחשב את הסכום?'
export const OPENING_MODE = { loan: 'סכום ההלוואה', price: 'מחיר והון עצמי' } as const
export const OPENING_PRICE_LABEL = 'מחיר הקנייה'
export const OPENING_CAPITAL_LABEL = 'הון עצמי'

// The engine's MIN_PRINCIPAL and MAX_PRINCIPAL, in
// mcp-server/src/loan_engine/domain/limits.py.
export const LOAN_MIN_AMOUNT = '10000'
export const LOAN_MAX_AMOUNT = '10000000'

export const OPENING_PURPOSE_MISSING = 'צריך לבחור מטרה'
export const OPENING_AMOUNT_INVALID =
  `צריך סכום הלוואה בין ${formatAmount(LOAN_MIN_AMOUNT)} ל-${formatShekels(LOAN_MAX_AMOUNT)}`
export const OPENING_CAPITAL_COVERS = 'ההון העצמי מכסה את כל המחיר, אז אין צורך בהלוואה'

/** Under the opening card's price and capital boxes: the loan they leave. */
export function openingLoanLine(amount: string): string {
  return `${OPENING_MODE.loan}: ${formatShekels(amount)}`
}

/** The person's message for the opening card; the agent's prompt quotes this form. */
export function openingLine(purpose: string, amount: string): string {
  return `${purpose}: הלוואה בסך ${formatShekels(amount)}`
}

export const PAYMENT_PLANNING = 'תכנון החזר חודשי'
/** The chip that asks the model for example loans of the check's amount and term. */
export const SAMPLES_CHIP = {
  label: 'דוגמאות',
  text:
    'אפשר לראות דוגמאות להלוואה כזו? פריים, ריבית קבועה לא צמודה, וריבית קבועה צמודה למדד כמו' +
    ' בהלוואה מקרן פנסיה או השתלמות',
}

/** The margin of a prime reading; a prime reading always carries one. */
function primeSpread(reading: Reading): string {
  const { prime_spread: spread } = reading.track
  if (spread === null) throw new Error(`a ${reading.kind} reading has no prime spread`)
  return String(spread)
}

/** A margin over prime as a signed percent, "+ 5.83%"; a margin below prime reads "− 0.25%". */
function marginText(spread: string): string {
  const below = spread.startsWith('-')
  return `${below ? '−' : '+'} ${roundedPercent(below ? spread.slice(1) : spread, 2)}%`
}

/** How a reading prices the loan, by its kind; a rate fixed by the payment alone is approximate. */
export function readingText(reading: Reading): string {
  const rate = roundedPercent(reading.total_rate, 2)
  const about = reading.approximate ? 'כ-' : ''
  switch (reading.kind) {
    case 'prime_margin':
      return `ריבית פריים ${marginText(primeSpread(reading))}`
    case 'prime_total':
      return `ריבית כוללת ${rate}% היום (פריים ${marginText(primeSpread(reading))})`
    case 'fixed_unlinked':
      return `ריבית קבועה ${about}${rate}%, לא צמודה למדד`
    case 'fixed_linked':
      return `ריבית קבועה ${about}${rate}%, צמודה למדד`
  }
}

export const READING_BEHAVIOUR = {
  prime_margin: 'ההחזר משתנה עם ריבית הפריים',
  prime_total: 'ההחזר משתנה עם ריבית הפריים',
  fixed_unlinked: 'ההחזר לא משתנה',
  fixed_linked: 'ההחזר עולה עם המדד',
} as const satisfies Record<ReadingKind, string>

/** How the quoted payment identified a reading: the loan, how a prime reading's rate adds up to
 * the total, and that the payment given matches. */
export function identificationText(
  reading: Reading,
  prime: string,
  rateAsOf: string,
  monthlyPayment: string,
): string {
  const sentences = [`זיהיתי שזו הלוואה ב${readingText(reading)}.`]
  if (reading.kind === 'prime_margin' || reading.kind === 'prime_total') {
    const sum = marginText(primeSpread(reading)).replace('%', '')
    sentences.push(
      `ריבית הפריים נכון ל-${formatDate(rateAsOf)} היא ${prime}%, כך שהריבית` +
        ` הכוללת היום היא ${roundedPercent(reading.total_rate, 2)}% (${prime} ${sum}).`,
    )
  }
  sentences.push(`ההחזר שמסרת, ${formatShekels(monthlyPayment)}, תואם לחישוב הזה.`)
  return sentences.join(' ')
}

/** The reply to an offer whose reading the agent identified and saved; an offer quoted on more
 * than the check's loan says which amount the check prices. */
export function identifiedText(offer: OfferIdentified): string {
  const sentences = [
    identificationText(offer.reading, offer.prime, offer.rate_as_of, offer.monthly_payment),
  ]
  const { quoted_amount: quoted, loan_amount: loan } = offer
  if (exceeds(quoted, loan) || exceeds(loan, quoted)) {
    sentences.push(
      `ההצעה ניתנה על ${formatShekels(quoted)}; בבדיקה היא מחושבת על סכום ההלוואה,` +
        ` ${formatShekels(loan)}.`,
    )
  }
  return sentences.join(' ')
}

export const OFFER_UNRECOGNIZED =
  'לא זיהיתי את סוג ההלוואה. בקשו יותר פרטים - האם ההלוואה מבוססת פריים? ריבית קבועה צמודה' +
  ' למדד?'

/** What a payment with no stated rate is worth as a fixed annual rate today. */
export function equivalentRateText(rate: string): string {
  return `ההחזר הזה שקול לריבית של כ-${roundedPercent(rate, 1)}% לשנה היום.`
}

/** What the lender's own words suggest about the loan; null when no word of theirs does. */
export function wordsSuggestText(
  likely: ReadingKind | null,
  typeWords: TypeWord[],
  lender: string,
): string | null {
  if (typeWords.includes('linked') && likely !== 'fixed_unlinked') {
    return (
      'בגלל המילה "צמוד", סביר שהריבית קבועה וההלוואה צמודה למדד, כך שההחזר יעלה עם המדד.' +
      ` כדאי לוודא זאת מול ${lender}.`
    )
  }
  if (typeWords.includes('fixed')) {
    return (
      'בגלל המילה "קבוע", סביר שההלוואה אינה צמודה למדד ושההחזר לא ישתנה. מלווים משתמשים' +
      ' במילה הזו גם כשרק הריבית קבועה וההחזר עדיין עולה עם המדד, ולכן כדאי לוודא זאת מול' +
      ` ${lender}.`
    )
  }
  return null
}

export const lenderQuestionTitle = (lender: string) => `השאלה לשאול את ${lender}`

const LENDER_TYPE_QUESTION = 'האם הריבית קבועה או תלויה בריבית הפריים, והאם ההלוואה צמודה למדד?'

/** The question to put to the lender; it names the monthly payment when the person gave one. */
export function lenderQuestion(payment: string | null): string {
  if (payment === null) return LENDER_TYPE_QUESTION
  const same = `האם ההחזר החודשי של ${formatShekels(payment)} נשאר זהה עד סוף ההלוואה?`
  return `${same} ${LENDER_TYPE_QUESTION}`
}

export const COPY_QUESTION = 'העתקה'
export const READINGS_TITLE = 'לפי התשובה, זו אחת מהאפשרויות:'
export const MOST_LIKELY = 'הסביר ביותר'
export const READING_MISSING = 'צריך לבחור אחת מהאפשרויות'
/** The two lines of a readings card's button for describing another offer, broken where the
 * meaning breaks; its message is the whole sentence. */
export const CONTINUE_TO_ANOTHER_OFFER_LINES = ['המשך להצעה נוספת', 'עד לבירור השאלה'] as const
export const CONTINUE_TO_ANOTHER_OFFER = CONTINUE_TO_ANOTHER_OFFER_LINES.join(' ')

export const readingsClosing = (lender: string) =>
  'אפשר להמשיך ולהזין הצעות נוספות. לאחר קבלת התשובה ' +
  `${fromLender(lender)} אפשר לחזור לנקודה הזו מהעיגול הצהוב שליד הבדיקה.`

/** The person's message for a confirmed reading; the agent's prompt reads its "אישור:". */
export const confirmedReadingLine = (reading: Reading) => `אישור: ${readingText(reading)}`

/** A readings card's line once its awaiting offer became a saved offer by this reading. */
export const settledReadingText = (reading: Reading) => `אושר: ${readingText(reading)}.`

/** Why an offer quoted for less than the check's loan waits on its lender. */
export const amountGapText = (lender: string, quoted: string, loan: string) =>
  `ההצעה של ${lender} היא על ${formatShekels(quoted)}, והבדיקה היא על ${formatShekels(loan)}.`

/** The question to put to a lender who quoted less than the check's loan. */
export const amountQuestion = (loan: string) =>
  `האם תוכלו להציע ${formatShekels(loan)} באותם תנאים?`

export const COVERS_SAME_TERMS = 'כן, באותם תנאים'
export const NOT_COVERED = 'לא'

/** The person's message once the lender lends the check's loan on the same terms; the agent's
 * prompt reads its "אישור:" and "באותם תנאים". */
export const amountCoveredLine = (lender: string, loan: string, reading: Reading) =>
  `אישור: ${formatShekels(loan)} באותם תנאים אצל ${lender}, ${readingText(reading)}`

/** The person's message once the lender does not lend the check's loan; the agent's prompt
 * reads its "לא: אין הצעה של". */
export const amountDeclinedLine = (lender: string, loan: string) =>
  `לא: אין הצעה של ${lender} על ${formatShekels(loan)}`

/** A readings card's line once its lender does not lend the check's loan. */
export const droppedText = (dropped: OfferDropped) =>
  `ההצעה של ${dropped.lender} לא מכסה את ההלוואה של ${formatShekels(dropped.loan_amount)},` +
  ' ולכן היא לא נכנסת להשוואה.'

export const AWAITING_ONLY = 'ההמלצה תופיע אחרי קבלת התשובה מהגוף המלווה.'
export const awaitingNote = (lender: string) =>
  `${lender}: ממתינה לבירור סוג ההלוואה, לא נכללת בהשוואה`
export const shortAwaitingNote = (lender: string) =>
  `${lender}: ממתינה לתשובה על סכום ההלוואה, לא נכללת בהשוואה`
