/** The Hebrew of the page outside a check: sign-in, session states and failed API calls. */

export const APP_TITLE = 'סימולטור הלוואות'
export const CHECKING_SESSION = 'בודקים מי מחובר…'
/** Where real offers can come from; the one place the page and its card name them. The system
 * prompt carries the same list, and a backend test holds the two equal. */
export const OFFER_SOURCES = 'בנקים, קרן השתלמות, קרן פנסיה, חברות אשראי, או גופים אחרים'
/** The signed-out pitch; **marked** words show in bold. */
export const LANDING_PITCH = [
  'סימולטור הלוואות **לקנייה גדולה**, כמו מכונית: מספרים בשיחה **מה רוצים לקנות** ומה המצב' +
    ' הכספי, והעוזר מחשב **כמה כסף להשאיר בצד למקרה חירום**, **כמה צריך ללוות**' +
    ' ו**כמה אפשר להחזיר בחודש**.',
  'כל מסלול מתומחר לפי **הריבית הממוצעת שמפרסם בנק ישראל**, וגם לפי **התקופה הקשה ביותר** בעשר' +
    ' השנים האחרונות: כמה ההחזר היה עולה אם הריבית או המדד היו זזים כמו אז.',
  `אחר כך מביאים **הצעות אמיתיות** מ${OFFER_SOURCES}, והעוזר משווה ביניהן וממליץ.`,
]

/** What the "more" toggle adds under the pitch. */
export const LANDING_DETAILS = [
  'המצב הכספי (הכנסות, כסף זמין, הוצאות קבועות והלוואות קיימות) נשמר פעם אחת ומשמש את כל הבדיקות.',
  'ההחזר החודשי המומלץ הוא לכל היותר מחצית ממה שנשאר אחרי ההוצאות הקבועות; החצי השני נשאר' +
    ' להוצאות לא צפויות.',
  'מההכנסה המשתנה נספר רק הסכום שמגיע גם בחודש חלש.',
  'כל המספרים מחושבים לפי נוסחאות קבועות, לא מנוחשים.',
]

export const SIGN_IN = 'התחברות עם Google'
export const SIGN_IN_REFUSED = 'הכניסה עם Google לא הושלמה. אפשר לנסות שוב.'

export const MORE = 'יותר'
export const LESS = 'פחות'
export const serverUnreachable = (message: string) => `לא הצלחנו להגיע לשרת: ${message}`

export function requestFailed(status: number): string {
  return `הבקשה נכשלה (קוד ${status})`
}

export const REQUEST_DATA_REFUSED = 'הנתונים לא התקבלו'
