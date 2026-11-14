/** Every Hebrew label and sentence on a check's page: the conversation and the card. */
import type { ChartShown, ProfileChange, Question, QuestionField, Track } from '../api/types.ts'
import { OFFER_SOURCES } from '../copy.ts'
import { formatDate, formatDay, formatMonth, formatShekels } from '../money.ts'
import { MONEY_FIELDS } from '../profile/copy.ts'
import type { MoneyKey } from '../profile/copy.ts'

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

// The shares (מחצית, 30%) are the engine's, in mcp-server/src/loan_engine/domain/assumptions.py.
export const REASON_SENTENCES: Record<string, string> = {
  variable_income_minimum_counted: 'מההכנסה המשתנה נספר רק הסכום המינימלי שמגיע גם בחודש חלש',
  ceiling_by_disposable_income:
    'התקרה היא מחצית ממה שנשאר מההכנסה שהוזנה אחרי ההוצאות הקבועות; החצי השני נשאר להוצאות לא צפויות',
  ceiling_by_income_share: 'התקרה היא 30% מההכנסה שהוזנה',
  existing_loans_deducted: 'ההחזרים על הלוואות קיימות נוכו מהתקרה',
  no_room_for_payment: 'לפי המספרים האלה לא נשאר מקום להחזר חודשי',
}

export const LABEL_PREFERRED = 'מומלצת'
export const LABEL_ALTERNATIVE = 'חלופה'

export const SOURCE_PUBLISHED_AVERAGE = 'לפי ריבית ממוצעת בבנקים'
/** Marks an option nobody can take, so it never reads as a real offer. */
export const CHIP_EXAMPLE = 'דוגמא'
export const EXAMPLES_NOTE = 'מחושב לפי ממוצעים. אי אפשר לקחת הלוואה כזו, היא רק נקודת השוואה.'

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

/** `spareSavings` is null when no savings are left beyond the cushion. */
export function decisionText(
  loanAmount: string,
  termMonths: number,
  monthlyPayment: string,
  cushionKept: string,
  spareSavings: string | null,
): string {
  const spare = spareSavings === null ? '' : ` ועוד ${spareSavings} פנויים`
  return `הלוואה של ${loanAmount} ל-${termText(termMonths)}, כ-${monthlyPayment} בחודש, ו-${cushionKept} נשארים בצד לביטחון${spare}.`
}

export const OTHERS_TITLE = {
  checked: 'האפשרויות שנבדקו',
  newSinceRecommendation: 'הצעות חדשות, עוד לא נכללו בהמלצה',
  further: 'אפשרויות נוספות',
} as const satisfies Record<string, string>

// The engine's CUSHION_MONTHS, in mcp-server/src/loan_engine/domain/assumptions.py.
export const CUSHION_TEXT = 'הסכום שכדאי לא לגעת בו: הוצאות של חודשיים'

export function dataDatesLine(rateDate: string, cpiMonth: string): string {
  return `ריבית בנק ישראל נכון ל-${rateDate}, מדד המחירים נכון ל-${cpiMonth}`
}

export const PUBLISHED_RATE_LINE =
  'ריבית ממוצעת על הלוואות צרכניות חדשות שמפרסם בנק ישראל, עד שיוזנו הצעות אמיתיות'

// The engine's HISTORY_MONTHS, in mcp-server/src/loan_engine/domain/assumptions.py.
export const HISTORY_LINE = 'התרחישים חוזרים על שינויי הריבית והמדד של כל תקופה בעשר השנים האחרונות'

export const FOLD_TITLE = 'למה המספרים האלה'

export function ceilingLine(amount: string): string {
  return `תקרת ההחזר החודשי: ${amount}`
}

export function cushionLine(amount: string): string {
  return `כרית הביטחון: ${amount}`
}

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
  'כדי להמליץ על הלוואה שמתאימה לך, צריך לדעת מה רוצים לקנות ובכמה, כמה כסף זמין יש, הכנסה' +
  ' קבועה ומשתנה (נטו), הוצאות קבועות והחזרי הלוואות קיימות.\n\n' +
  "**כתבו בתיבה למטה** את כל או חלק מהנתונים הנדרשים במלל חופשי, או ענו על השאלות בצ'אט אחת אחת."

/** Sample opening messages above the input; a tap only fills the input, the person sends. */
export const SAMPLE_MESSAGES: { label: string; text: string }[] = [
  { label: 'מכונית', text: 'אני רוצה לקנות מכונית.' },
  {
    label: 'מכונית + נתונים נוספים',
    text:
      'אני רוצה לקנות מכונית ב-55,000 ₪, כסף זמין 35,000 ₪, משכורת קבועה 8,000 ₪, משכורת' +
      ' נוספת ממלצרות 5,000 ₪ (מינימום 2,000 ₪ בחודש), הוצאות קבועות 6,000 ₪ בחודש.',
  },
]

/** The market-data sample, offered at any point of a conversation until tapped that day. */
export const MARKET_SAMPLE = {
  label: 'פריים ומדדים',
  text:
    'מהי ריבית הפריים הנוכחית, ומה היו השינויים ב-5 השנים האחרונות\n' +
    'מה היו המדדים לצרכן ב-12 החודשים האחרונים\n' +
    'הצג את הנתונים בשני גרפים.',
}

/** The real-offer sample, offered once a check has a recommendation; ?? marks each figure the
 * person fills in from their own offer. */
export const OFFER_SAMPLE = {
  label: 'הצעה מגוף מלווה',
  text:
    'קיבלתי הצעה מ-?? (בנק, קרן השתלמות, חברת אשראי או גוף אחר). שני מסלולים אפשריים:' +
    ' (1) פריים + ??%  (2) ריבית קבועה ??% צמודה למדד.\n' +
    'לתקופה של עד ?? חודשים, בתשלומים חודשיים שווים.',
}

/** Marks a figure in a sample that the person fills in. */
export const PLACEHOLDER = '??'
export const PLACEHOLDER_QUESTION = 'האם לשלוח בקשה עם סימני שאלה?'
export const PLACEHOLDER_CONFIRM = 'לשלוח בכל זאת'
export const PLACEHOLDER_CANCEL = 'ביטול'

export const NEXT_STEP_TITLE = 'מה הלאה'
export const NEXT_STEP = `להביא הצעות אמיתיות מ${OFFER_SOURCES}, ולכתוב אותן כאן בשיחה להשוואה.`
export const OFFER_DETAILS =
  'בכל הצעה כדאי לבקש: ריבית (או פריים ומרווח), הצמדה, מספר חודשים, שיטת החזר, עמלות, בלון, שם' +
  ' הגוף ותאריך.'

export const EMPTY_CARD = 'ההמלצה תופיע כאן אחרי שנכיר את המטרה ואת המצב.'

export const STALE_BANNER = 'ההמלצה חושבה לפי פרופיל קודם.'
export const RECOMPUTE_BUTTON = 'לחשב מחדש'
export const RECOMPUTE_MESSAGE =
  'הפרופיל שלי השתנה. אפשר לחשב מחדש את ההמלצה לפי המספרים המעודכנים?'

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

type GoalField = 'purpose' | 'price'

/** The goal fields the model can ask about; `hint` says what goes in the answer. */
export const GOAL_QUESTIONS: Record<GoalField, { label: string; hint: string }> = {
  purpose: {
    label: 'מה רוצים לקנות?',
    hint: 'למשל רכב או שיפוץ. אפשר גם משהו אחר.',
  },
  price: {
    label: 'מה המחיר, בערך?',
    hint: 'המחיר המלא של הקנייה, לפני שמורידים ממנו כסף זמין.',
  },
}

export function isGoalField(field: QuestionField): field is GoalField {
  return field in GOAL_QUESTIONS
}

export const PURPOSE_CHOICES = ['רכב', 'שיפוץ']
export const OTHER_PURPOSE = 'משהו אחר'
export const SKIP = 'דילוג'
export const ANSWER = 'אישור'

/**
 * The person's message for an answered question; the agent's prompt quotes this form. A label
 * that is itself a question takes its value after a space.
 */
export function answerLine(label: string, value: string): string {
  return label.endsWith('?') ? `${label} ${value}` : `${label}: ${value}`
}

/** A profile amount as an answer or a panel note shows it. */
export function profileValueText(value: string): string {
  return formatShekels(value)
}

/** The person's message for a skipped question; the agent's prompt quotes this form. */
export function skipLine(label: string): string {
  return `דילוג על: ${label}`
}

/** The person's message for a skipped amount that the page saved as 0. */
export function skipAsZeroLine(label: string): string {
  return `${skipLine(label)} (נשמר כ-0)`
}

function fieldCopy(field: QuestionField): { label: string; hint: string } {
  if (isGoalField(field)) return GOAL_QUESTIONS[field]
  const money = MONEY_FIELDS.find(({ key }) => key === field)
  if (money === undefined) throw new Error(`no profile copy for ${field}`)
  return money
}

/** The label a profile or goal field carries in a question and in a panel note. */
export function fieldLabel(field: QuestionField): string {
  return fieldCopy(field).label
}

/** The conversation's line for a field the person saved in the profile panel. */
export function panelNote(label: string, value: string): string {
  return `עודכן בפרופיל: ${label} ${value}`
}

/** How the question bubble asks for each profile amount; the panel and the lines use the label. */
const PROFILE_QUESTIONS: Record<MoneyKey, string> = {
  savings: 'כמה כסף זמין יש לקנייה?',
  net_fixed_income: 'מה ההכנסה הקבועה שלך בחודש, נטו?',
  variable_income: 'מה ההכנסה המשתנה שלך בחודש, בממוצע ונטו?',
  variable_income_minimum: 'ובחודש חלש, כמה מההכנסה המשתנה בכל זאת נכנס?',
  fixed_expenses: 'כמה יוצא כל חודש על הוצאות קבועות?',
  existing_loan_payments:
    'האם יש הלוואות קיימות עם יותר מ-3 חודשים לסיום, ואם כן - מה ההחזר החודשי?',
}

/** The offer to clone a check before changing its recommendation; the prompt quotes the choices. */
export const CLONE_QUESTION =
  'לשכפל את הבדיקה ולבצע סימולציה נפרדת? כך אפשר יהיה להשוות בין הבדיקות.'
export const CLONE_CHOICE = 'לשכפל ולבדוק בנפרד'
export const STAY_CHOICE = 'לעדכן את הבדיקה הזאת'

/** The question a bubble shows: a profile amount's question, a goal label, the clone offer, or
 * the model's own sentence. */
export function questionText(question: Question): string {
  if (question.offer_clone === true) return CLONE_QUESTION
  const { field } = question
  if (field === null) return question.text
  if (isGoalField(field)) return fieldLabel(field)
  return PROFILE_QUESTIONS[field]
}

/** A field's label from the profile or goal copy, the clone offer, or the model's own sentence. */
export function questionLabel(question: Question): string {
  if (question.offer_clone === true) return CLONE_QUESTION
  return question.field === null ? question.text : fieldLabel(question.field)
}

/** A field's hint; a free question has none. */
export function questionHint(question: Question): string | null {
  return question.field === null ? null : fieldCopy(question.field).hint
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
export const ARCHIVED_PROFILE_TITLE = 'הפרופיל שעליו התבססה הבדיקה'
export const NOT_TOLD = 'לא נמסר'
/** Opens the check that replaced an archived one, computed from the changed profile. */
export const CONTINUED_LINK = 'מעבר לבדיקה המעודכנת'

/** A profile amount in the closing note; an amount never told shows as such. */
export function archivedFigure(value: string | null): string {
  return value === null ? NOT_TOLD : formatShekels(value)
}

/** A profile field's full name, as the closing note lists it. */
export function profileFieldName(field: MoneyKey): string {
  const copy = MONEY_FIELDS.find(({ key }) => key === field)
  if (copy === undefined) throw new Error(`no profile copy for ${field}`)
  return copy.title ?? copy.label
}

/** Each changed figure, from its old value to its new one. */
function changesText(changes: ProfileChange[]): string {
  return changes
    .map(
      ({ field, from, to }) =>
        `${profileFieldName(field)}: מ-${archivedFigure(from)} ל-${archivedFigure(to)}`,
    )
    .join('; ')
}

/** Why a profile change closed the check: the day and each changed figure. */
export function archivedReason(at: Date, changes: ProfileChange[]): string {
  const list = changesText(changes)
  return `ב-${formatDay(at)} השתנה הפרופיל (${list}), ולכן ההמלצה כאן כבר לא מתאימה.`
}

/** The closing line of a check the person archived themselves. */
export function manualArchiveLine(at: Date): string {
  return `ב-${formatDay(at)} הבדיקה הועברה לארכיון ידנית.`
}

export const FOLLOWS_TITLE = 'בדיקת המשך'
/** Opens the archived check a follow-up check replaces. */
export const ORIGIN_LINK = 'מעבר לבדיקה הקודמת שבארכיון'

/** Why a follow-up check exists: the changed figures that archived the check it replaces. */
export function followsReason(changes: ProfileChange[]): string {
  return (
    `הבדיקה הזאת מחליפה בדיקה קודמת שנסגרה כי הפרופיל השתנה (${changesText(changes)}).` +
    ' כל החישובים כאן לפי הפרופיל המעודכן.'
  )
}
