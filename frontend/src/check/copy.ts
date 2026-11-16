/** Every Hebrew label and sentence on a check's page: the conversation and the card. */
import type {
  CeilingSource,
  ChartShown,
  LoanRequest,
  Question,
  QuestionField,
  Track,
} from '../api/types.ts'
import { OFFER_SOURCES } from '../copy.ts'
import { formatAmount, formatDate, formatDay, formatMonth, formatShekels } from '../money.ts'

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

export const LABEL_PREFERRED = 'מומלצת'
export const LABEL_ALTERNATIVE = 'חלופה'

export const SOURCE_EXAMPLE = 'לפי ריבית ממוצעת בבנקים'
/** Marks an option nobody can take, so it never reads as a real offer. */
export const CHIP_EXAMPLE = 'דוגמא'
export const EXAMPLES_NOTE =
  'מחושב לפי ממוצעים. אי אפשר לקחת הלוואה כזו: היא מוצגת רק עד שתוזן הצעה אמיתית.'

const HEBREW_LETTER = /^[\u05D0-\u05EA]/

export function offerSource(lender: string | null, date: string | null): string {
  const from = lender === null ? 'הצעה' : `הצעה ${HEBREW_LETTER.test(lender) ? 'מ' : 'מ-'}${lender}`
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
  today: 'סך התשלומים בתנאים של היום',
  range: 'טווח בתרחישים',
} as const

/** In the range column, for an option whose total cannot change. */
export const NO_RANGE = '—'

export function monthlyPayment(amount: string): string {
  return `${amount} בחודש`
}

export const CARD_FAILED = 'לא הצלחנו להציג את ההמלצה.'

/** The page's own opening line, the first bubble of every check, so the first reply has a question;
 * **marked** words show in bold. */
export const CHAT_WELCOME =
  'כדי להמליץ על הלוואה שמתאימה לך, **כתבו בתיבה למטה** את ההלוואה: כמה צריך ללוות, או מחיר' +
  ' הקנייה וכמה כסף יש כבר.\n' +
  'אפשר להוסיף גם את ההחזר החודשי הגבוה ביותר שנוח לך, אבל זה לא חובה.'

/** Sample opening messages above the input; a tap only fills the input, the person sends. */
export const SAMPLE_MESSAGES: { label: string; text: string }[] = [
  { label: 'הלוואה', text: 'אני רוצה הלוואה בסך 60,000₪' },
  { label: 'רכב', text: 'אני רוצה לקנות רכב ב-100,000₪ ויש לי 40,000₪' },
  {
    label: 'רכב, החזר מרבי',
    text: 'אני רוצה לקנות רכב ב-50,000₪ ויש לי 26,000₪. אוכל להחזיר עד 1,000₪ בחודש.',
  },
  { label: 'שיפוץ', text: 'אני רוצה הלוואה בסך 80,000₪ לשיפוץ, בהחזר של עד 2,000₪ בחודש' },
]

/** The market-data sample, offered at any point of a conversation; the server answers it from
 * the market data with no model call. */
export const MARKET_SAMPLE = {
  label: 'פריים ומדדים',
  text:
    'מהי ריבית הפריים הנוכחית, ומה היו השינויים ב-5 השנים האחרונות?\n' +
    'מה היו המדדים לצרכן ב-12 החודשים האחרונים?',
}

/** The real-offer sample, offered once a check has a recommendation. It has nothing to fill in,
 * so a tap sends it; the server answers it with the offer form and no model call. */
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
/** Sent as the person's message, as it is, when they cannot name a comfortable payment. */
export const DONT_KNOW = 'לא יודע/ת'

export const TERM_MIN_MONTHS = 6
export const TERM_MAX_MONTHS = 84
export const TERM_BOX_LABEL = 'מספר חודשים'
export const TERM_BOX_PLACEHOLDER = `${TERM_MIN_MONTHS}–${TERM_MAX_MONTHS}`
export const CEILING_BOX_PLACEHOLDER = 'לא חובה'
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

/** The term question's card line: the proposed term and the first payment it gives. */
export function termLine(termMonths: number, firstPayment: string): string {
  return `תקופה מוצעת: ${termText(termMonths)} · החזר ראשון כ-${formatShekels(firstPayment)}`
}

/** The question a bubble shows: a field's question, the term card, the clone offer, or the
 * model's own sentence. */
export function questionText(question: Question): string {
  if (question.kind === 'term') return termLine(question.term_months, question.first_payment)
  if (question.kind === 'offer') return OFFER_FORM_TITLE
  if (question.offer_clone === true) return CLONE_QUESTION
  const { field } = question
  return field === null ? question.text : FIELD_COPY[field].text
}

/** A field's label, the term card's line, the clone offer, or the model's own sentence. */
export function questionLabel(question: Question): string {
  if (question.kind === 'term' || question.kind === 'offer') return questionText(question)
  if (question.offer_clone === true) return CLONE_QUESTION
  return question.field === null ? question.text : fieldLabel(question.field)
}

/** A field's hint; a free question, the term card and the offer form have none. */
export function questionHint(question: Question): string | null {
  if (question.kind === 'term' || question.kind === 'offer' || question.field === null) return null
  return FIELD_COPY[question.field].hint
}

export const OFFER_FORM_TITLE = 'פרטי ההצעה'
export const OFFER_LENDER_LABEL = 'מי הגוף המלווה?'
export const OFFER_TRACKS_LABEL = 'המסלולים שהוצעו'
export const OFFER_MONTHS_LABEL = 'לכמה חודשים לכל היותר?'
export const OFFER_MONTHS_UNIT = 'חודשים'
export const OFFER_LINKED = 'צמוד למדד'
export const OFFER_ADD_TRACK = '+ מסלול נוסף'
export const OFFER_REMOVE_TRACK = 'הסרת המסלול'
export const OFFER_CONTINUE = 'המשך'
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
 * in. Every track says whether it is linked, so the model has nothing left to ask, and names
 * its kind by the form's own label: a margin under prime written with a minus sign would read
 * as a dash.
 */
export function offerLine(lender: string, tracks: OfferTrack[], months: number): string {
  const listed = tracks.map(
    (track, index) =>
      `(${index + 1}) ${OFFER_KIND_LABEL[track.kind]} ${track.rate}%, ` +
      (track.linked ? OFFER_LINKED : `לא ${OFFER_LINKED}`),
  )
  return (
    `קיבלתי הצעה מגוף מלווה, ${lender}: ${listed.join(' ')}.` +
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
export const CEILING_SOURCE = {
  stated: 'לפי מה שאמרת',
  finances: 'לפי ההכנסה וההוצאות',
} as const satisfies Record<CeilingSource, string>

/** The person's message for a figure edited in the data panel; the agent's prompt quotes it. */
export function updateLine(label: string, amount: string): string {
  return `עודכן: ${label} ${amountText(amount)}`
}
