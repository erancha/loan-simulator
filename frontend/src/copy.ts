/** The Hebrew of the page outside a check: sign-in, session states and failed API calls. */

export const APP_TITLE = 'סימולטור הלוואות'
export const CHECKING_SESSION = 'בודקים מי מחובר…'
/** Where real offers can come from; the one place the page and its card name them. The system
 * prompt carries the same list, and a backend test holds the two equal. */
export const OFFER_SOURCES = 'בנקים, קרן השתלמות, קרן פנסיה, חברות אשראי, או גופים אחרים'
/** The signed-out pitch; **marked** words show in bold. */
export const LANDING_PITCH = [
  'עוזר להבין **כמה ללוות ולכמה זמן** לפני שמבקשים הלוואה, ואחר כך להשוות בין הצעות.' +
    ' **הסימולטור לא נותן הלוואות** ולא פונה לאף גוף מלווה: הוא רק מחשב ומשווה.',
  'מספרים בשיחה **מה רוצים לקנות** ומה המצב הכספי, והסימולטור מחשב **כמה כסף להשאיר בצד למקרה' +
    ' חירום**, **כמה צריך ללוות**, **לכמה חודשים** ו**כמה אפשר להחזיר בחודש**.',
  'החישוב נשען על **נתונים אמיתיים** שמתעדכנים כל יום: **הריבית הממוצעת על הלוואות שמפרסם' +
    ' בנק ישראל**, **ריבית הפריים** הנגזרת מריבית בנק ישראל, והמדד.',
  'אחר כך מבקשים לבד **הצעות אמיתיות** מבנקים ומגופים אחרים, כותבים אותן בשיחה, והסימולטור' +
    ' משווה ביניהן וממליץ.',
]

/** What the "more" toggle adds under the pitch; **marked** words show in bold. */
export const LANDING_DETAILS = [
  'הסימולטור מיועד להלוואה **לקנייה**, כמו מכונית.',
  `הצעות אמיתיות אפשר לבקש מ${OFFER_SOURCES}.`,
  'כל מסלול מתומחר גם לפי **התקופה הקשה ביותר** בעשר השנים האחרונות: כמה ההחזר היה עולה אם' +
    ' הריבית או המדד היו זזים כמו אז.',
  'המצב הכספי (הכנסות, כסף זמין, הוצאות קבועות והלוואות קיימות) נשמר פעם אחת ומשמש את כל הבדיקות.',
  'ההחזר החודשי המומלץ הוא לכל היותר מחצית ממה שנשאר אחרי ההוצאות הקבועות; החצי השני נשאר' +
    ' להוצאות לא צפויות.',
  'מההכנסה המשתנה נספר רק הסכום שמגיע גם בחודש חלש.',
  'כל המספרים מחושבים לפי נוסחאות קבועות, לא מנוחשים.',
]

/** The line under the title that names the running build, so a report can name it too. */
export const versionLine = (version: string, commitDate: string) =>
  `גירסה ${version}, ${commitDate}`

export const DEMO_LINK = 'הדגמה'
/** The demo link's tooltip: the desktop shows the chat and the card side by side. */
export const DEMO_HINT = 'שיחה מוקלטת, מהשאלה הראשונה ועד ההמלצה; מומלץ לראות במסך מחשב'
/** The banner over the replayed check on demo.html. */
export const DEMO_BANNER = 'הדגמה מוקלטת'
export const DEMO_RESTART = 'מההתחלה'
export const INVITE_LINK = 'הזמנת חברים ב-WhatsApp'
/** The invite message, before the page's own address, which closes it on a line of its own. */
export const INVITE_MESSAGE = [
  'היי! קיבלתי המלצה על סימולטור הלוואות חינמי: מספרים מה רוצים לקנות ומה המצב הכספי, והוא מחשב' +
    ' כמה ללוות, לכמה זמן וכמה אפשר להחזיר בחודש, לפי נתוני בנק ישראל.',
  'אחר כך הוא משווה בין הצעות אמיתיות וממליץ. נכנסים בחינם עם חשבון Google:',
]
export const SOURCE_LINK = 'קוד המקור ב-GitHub'

export const SIGN_IN = 'התחברות עם Google'
export const SIGN_IN_REFUSED = 'הכניסה עם Google לא הושלמה. אפשר לנסות שוב.'

export const MORE = 'יותר'
export const LESS = 'פחות'
export const serverUnreachable = (message: string) => `לא הצלחנו להגיע לשרת: ${message}`

export function requestFailed(status: number): string {
  return `הבקשה נכשלה (קוד ${status})`
}

export const REQUEST_DATA_REFUSED = 'הנתונים לא התקבלו'
