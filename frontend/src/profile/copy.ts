/** Every Hebrew label and sentence of the profile panel. */
import type { ProfileFields } from '../api/types.ts'

export type MoneyKey = keyof ProfileFields

/**
 * In the order the panel shows them; `hint` says what goes in the field, and `title`, when set,
 * is the full name a shortened label stands for, shown on hover over the field's row.
 */
export const MONEY_FIELDS: {
  key: MoneyKey
  label: string
  title?: string
  hint: string
}[] = [
  {
    key: 'savings',
    label: 'כסף זמין',
    hint:
      'כל הכסף הנזיל שיש לך לקנייה: עו"ש, פיקדונות, חסכונות נזילים, וגם מה שיתקבל ' +
      'ממכירה של רכב קודם או של משהו אחר. בלי פנסיה ובלי קרן השתלמות נעולה.',
  },
  {
    key: 'net_fixed_income',
    label: 'הכנסה קבועה',
    hint: 'המשכורת שנכנסת לחשבון כל חודש, אחרי מסים וניכויים.',
  },
  {
    key: 'variable_income',
    label: 'הכנסה משתנה',
    hint: 'ממוצע חודשי של הכנסות שמשתנות: משמרות, טיפים, עבודות צד, בונוסים.',
  },
  {
    key: 'variable_income_minimum',
    label: 'מינימלית',
    hint: 'הסכום מההכנסה המשתנה שמגיע גם בחודש חלש. רק הסכום הזה נספר בחישוב, במלואו.',
  },
  {
    key: 'fixed_expenses',
    label: 'הוצאות קבועות',
    hint:
      'מה שיוצא ממך כל חודש: שכר דירה, מזון וקניות, חשבונות, ביטוחים, תחבורה, בילויים וכיו"ב.' +
      ' גרים עם עוד אנשים? רק החלק שלך. בלי החזרי הלוואות.',
  },
  {
    key: 'existing_loan_payments',
    label: 'החזרי הלוואות',
    title: 'החזרי הלוואות קיימות',
    hint:
      'סך ההחזרים החודשיים על הלוואות שכבר יש, כולל עסקאות בתשלומים. הלוואה שנשארו לה 3 חודשים' +
      ' או פחות לא נספרת: הכסף שלה מתפנה להלוואה החדשה.',
  },
]

/** A folded row's hover text: the field's full name, when its label is shortened, then its hint. */
export function rowTooltip({ title, hint }: { title?: string; hint: string }): string {
  return title === undefined ? hint : `${title}: ${hint}`
}

export const PROFILE_TITLE = 'פרופיל פיננסי'
/** The toggle's accessible name for opening and for closing the profile's fields. */
export const OPEN_PROFILE = 'פתיחת הפרופיל לעריכה'
export const CLOSE_PROFILE = 'סגירת הפרופיל'
export const PROFILE_NOTE =
  'הפרטים נאספים בשיחה. אפשר לתקן כאן כל מספר; התיקון נשמר מיד ומופיע גם בשיחה.'
/** Shown for a moment after a field is saved. */
export const SAVED = 'נשמר ✓'
/** The accessible name of the button that opens a field's hint. */
export const HINT_LABEL = 'הסבר'
export const LOADING_PROFILE = 'טוענים את הפרופיל…'
export const loadFailed = (message: string) => `לא הצלחנו לטעון את הפרופיל: ${message}`
/** Shown in an empty money field. */
export const NOT_COUNTED_YET = 'עוד לא הוזן'

export const NOT_A_NUMBER = 'אפשר להקליד רק מספר, למשל 12,500'

export const refused = (reason: string) => `הערך לא התקבל: ${reason}`
export const saveFailed = (message: string) => `השמירה לא הצליחה: ${message}`
