/** The Hebrew of the page outside a check: sign-in, session states and failed API calls. */

export const APP_TITLE = 'סימולטור הלוואות'
/** The line under the title: what sets the simulator apart from a loan calculator. */
export const APP_TAGLINE = 'מבוסס בינה מלאכותית'
export const CHECKING_SESSION = 'בודקים מי מחובר…'
/** Where real offers can come from; the one place the page and its card name them. The system
 * prompt carries the same list, and a backend test holds the two equal. */
export const OFFER_SOURCES = 'בנקים, קרן השתלמות, קרן פנסיה, חברות אשראי, או גופים אחרים'
/** The signed-out pitch's opening lines; **marked** words show in bold. The first names the
 * question the simulator answers, which a loan calculator's payment table does not; the second
 * says it is a conversation that needs no financial knowledge. */
export const LANDING_LEAD = [
  '**קיבלתם הצעות להלוואה ולא ברור איזו משתלמת?** הסימולטור משווה ביניהן ומול הריבית הממוצעת' +
    ' בבנקים, וממליץ.',
  '**הכול בשיחה, במילים שלכם, בלי ידע מוקדם:** הסימולטור שואל מה שצריך, ואפשר לשאול אותו כל דבר' +
    ' בדרך.',
]
/** The signed-out pitch as numbered steps, since visitors skim prose but follow steps. It leads
 * with the loan, then the offers the person already holds, and ends on what each offer really
 * is; the person's finances come up only if they choose to bring them. The step that names
 * lenders also says the simulator is not one, so no visitor expects a loan from it. */
export const LANDING_STEPS = [
  { title: 'מתארים את ההלוואה המבוקשת', text: 'מטרה, סכום והחזר חודשי מרבי.' },
  {
    title: 'מזינים את ההצעות שקיבלתם',
    text: 'בטופס או במילים שלכם. הסימולטור לא נותן הלוואות ולא פונה לאף גוף מלווה.',
  },
  {
    title: 'רואים את המחיר האמיתי של כל הצעה',
    text: 'כמה ריבית תשלמו בסה"כ, איך היא ביחס לממוצע בבנקים, ואיזו הצעה זולה יותר.',
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

/** How long the recorded check on demo.html replays at its starting speed, to the nearest ten
 * seconds; a test holds it to the recording. */
export const DEMO_SECONDS = 60
/** The landing page's link to the demo, with its length, so a visitor knows what a click costs.
 * The page draws the mark in superscript after the number, which holds only at the demo's
 * starting speed. */
export const DEMO_LINK = { before: `הדגמה (${DEMO_SECONDS}`, mark: '*', after: ' שניות)' }
/** The marks before the demo and invite links, the same as the invite message's own. */
export const DEMO_MARK = '▶️'
export const INVITE_MARK = '💬'
/** The demo link's tooltip, which only a computer shows. Its first line recommends a computer,
 * where the chat and the card show side by side; its second says what the mark on the link's
 * length stands for: the demo's starting speed, and the speed its clock counts by. */
export const DEMO_HINT =
  'שיחה מוקלטת, מהשאלה הראשונה ועד ההמלצה; מומלץ לראות במסך מחשב\n' +
  `${DEMO_LINK.mark} ההדגמה מתחילה במהירות כפולה. במהירות רגילה היא נמשכת כשתי דקות, והשעון` +
  ' בהדגמה סופר לפיה.'
/** The banner over the replayed check on demo.html. */
export const DEMO_BANNER = 'הדגמה מוקלטת'
export const DEMO_RESTART = 'מההתחלה'
/** The demo's playback bar: pause and resume, and the speed group's name; the speeds name
 * themselves (1×, 2×). */
export const DEMO_PAUSE = 'השהיה'
export const DEMO_RESUME = 'המשך'
export const DEMO_SPEED = 'מהירות'
/** The notice on demo.html when the visitor's action needs a server: the sentence, then its link
 * into the simulator, which ends it. */
export const DEMO_UNAVAILABLE = 'הפעולה הזאת לא זמינה בהדגמה. כדי לנסות בעצמך,'
export const DEMO_ENTER = 'נכנסים לסימולטור'
export const DEMO_NOTICE_CLOSE = 'סגירת ההודעה'
export const INVITE_LINK = 'הזמנת חברים ב-WhatsApp'
/** The invite message's paragraphs, in the voice of the friend who sends it: who it is for, how
 * it works, what it does not ask of the reader, and the demo, which needs no sign-in. The page's
 * own address follows the last one. */
export const INVITE_MESSAGE = [
  'היי! 👋 קיבלתי המלצה על סימולטור הלוואות מבוסס בינה מלאכותית, למי שמתלבט בין הצעות' +
    ' להלוואה.',
  '💬 כותבים לו בצ\'אט, במילים פשוטות, מה הציעו לכם. הוא משווה בין ההצעות, בודק אותן מול הריבית' +
    ' הממוצעת בבנקים לפי נתוני בנק ישראל, וממליץ.',
  'לא צריך להבין בריביות, והוא לא מוכר כלום ולא פונה לאף בנק.',
  `🎁 זה בחינם, ויש שם גם ▶️ הדגמה של ${DEMO_SECONDS} שניות, בלי להירשם:`,
]
export const SOURCE_LINK = 'קוד המקור ב-GitHub'

export const SIGN_IN = 'התחברות עם Google'
export const SIGN_IN_REFUSED = 'הכניסה עם Google לא הושלמה. אפשר לנסות שוב.'
/** The toggle under the sign-in button, for a visitor wary of signing in to an unfamiliar site
 * with a Google account. */
export const SIGN_IN_WHY = 'למה להתחבר עם Google?'
/** The opening line of what the toggle shows; **marked** words show in bold. */
export const SIGN_IN_WHY_LEAD = 'כניסה עם Google **בטוחה ונוחה יותר** מפתיחת חשבון עם סיסמה חדשה.'
/** The points under that line. The first two answer the fear of handing the simulator access to a
 * Google account, since a worried reader discounts advantages until then; the last two argue the
 * advantages. */
export const SIGN_IN_WHY_POINTS = [
  '**ההתחברות מאושרת על ידי Google, לא על ידי הסימולטור.** Google מוסרת לסימולטור רק אימות' +
    ' לגבי הזהות שלכם, ללא גישה לנתונים שלכם (מיילים, אנשי קשר ועוד).',
  '**השליטה אצלכם:** אפשר לנתק את הסימולטור בכל רגע מהגדרות חשבון Google.',
  '**אין עוד סיסמה לזכור,** ואין סיסמה שיכולה לדלוף מכאן: הסימולטור לא שומר סיסמאות בכלל.',
  '**ההגנות של Google עובדות בשבילכם:** אימות דו-שלבי והתראה על כניסה חשודה שומרים גם על' +
    ' הכניסה לכאן.',
]
export const SIGN_IN_WHY_LINK = 'ההסבר המלא של Google'

export const MORE = 'יותר'
export const LESS = 'פחות'
export const serverUnreachable = (message: string) => `לא הצלחנו להגיע לשרת: ${message}`

export function requestFailed(status: number): string {
  return `הבקשה נכשלה (קוד ${status})`
}

export const REQUEST_DATA_REFUSED = 'הנתונים לא התקבלו'
