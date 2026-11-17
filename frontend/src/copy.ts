/** The Hebrew of the page outside a check: sign-in, session states and failed API calls. */

export const APP_TITLE = 'סימולטור הלוואות'
export const CHECKING_SESSION = 'בודקים מי מחובר…'
/** Where real offers can come from; the one place the page and its card name them. The system
 * prompt carries the same list, and a backend test holds the two equal. */
export const OFFER_SOURCES = 'בנקים, קרן השתלמות, קרן פנסיה, חברות אשראי, או גופים אחרים'
/** The signed-out pitch's opening line; **marked** words show in bold. */
export const LANDING_LEAD =
  '**הסימולטור לא נותן הלוואות** ולא פונה לאף גוף מלווה.'
/** The signed-out pitch as numbered steps, since visitors skim prose but follow steps. It leads
 * with the loan, then the offers the person already holds, and ends on what each offer really
 * is; the person's finances come up only if they choose to bring them. */
export const LANDING_STEPS = [
  { title: 'מתארים את ההלוואה המבוקשת', text: 'מטרה, סכום והחזר חודשי מרבי.' },
  { title: 'מזינים את ההצעות שקיבלתם', text: 'בטופס, או במילים שלכם, כמו שהגוף המלווה מסר.' },
  {
    title: 'רואים מה כל הצעה עולה באמת',
    text: 'כמה ריבית תשלמו, איך היא ביחס לממוצע בבנקים, ואיזו הצעה זולה יותר.',
  },
]

/** What the "more" toggle adds under the pitch; **marked** words show in bold. */
export const LANDING_DETAILS = [
  'החישוב נשען על **נתונים אמיתיים** שמתעדכנים כל יום: **הריבית הממוצעת על הלוואות שמפרסם' +
    ' בנק ישראל**, **ריבית הפריים** הנגזרת מריבית בנק ישראל, והמדד.',
  'הסימולטור מיועד להלוואה **לקנייה**, כמו רכב.',
  `הצעות אמיתיות אפשר לבקש מ${OFFER_SOURCES}.`,
  'כל מסלול מתומחר גם לפי **התקופה הקשה ביותר** בעשר השנים האחרונות: כמה ההחזר היה עולה אם' +
    ' הריבית או המדד היו זזים כמו אז.',
  'אפשר גם לכתוב **את ההחזר החודשי הגבוה ביותר שנוח לך**, או לבקש עזרה לחשב אותו לפי הכנסה' +
    ' והוצאות. זה לא חובה.',
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
  'היי! קיבלתי המלצה על סימולטור הלוואות חינמי: מספרים כמה צריך ללוות, והוא מציע' +
    ' לכמה זמן, ומראה את ההחזרים בחודש לפי נתוני בנק ישראל.',
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
