/** Every Hebrew label and sentence of the signed-in shell: header, checks list and tabs. */
import { monthlyPayment as monthlyPaymentText } from '../check/copy.ts'
import { formatShekels } from '../money.ts'

export const SIGN_OUT = 'התנתקות'
export const MENU_LABEL = 'תפריט חשבון'
/** Hover texts of the account menu: what each line reaches. */
export const ACCOUNT_HINT = 'החשבון שאיתו התחברת'
export const SIGN_OUT_HINT = 'יציאה מהחשבון'
export const NEW_CHECK = '+ בדיקה חדשה'
export const NO_CHECKS = 'עוד אין בדיקות. מתחילים?'
export const UNTITLED_CHECK = 'בדיקה חדשה'
export const CONFIRM_DELETE = 'למחוק את הבדיקה ואת כל מה שנשמר בה?'
export const DELETE_CONFIRMED = 'מחיקה'
export const DELETE_CANCELLED = 'ביטול'
export const DELETE_WHILE_ANSWERING = 'אי אפשר למחוק בדיקה בזמן שהעוזר עונה. נסו שוב בעוד רגע.'
export const ARCHIVE_WHILE_ANSWERING =
  'אי אפשר להעביר בדיקה לארכיון בזמן שהעוזר עונה. נסו שוב בעוד רגע.'
export const RECOMMENDATION_READY = 'המלצה מוכנה'
/** The chip of a check whose card holds one real offer alone, evaluated rather than ranked. */
export const OFFER_EVALUATED = 'הצעה נבדקה'
export const ARCHIVED = 'בארכיון'
export const CHECKS_HEADING = 'הבדיקות שלי'
/** The link on a check's months row that shows or hides its finances line above the chat. */
export const FINANCES_LINK = 'פרטים כספיים'
export const TABS_LABEL = 'חלקי העמוד'

export const TABS = [
  { pane: 'side', label: 'בדיקות' },
  { pane: 'chat', label: 'שיחה' },
  { pane: 'card', label: 'המלצה' },
] as const

export const loadFailed = (message: string) => `לא הצלחנו לטעון את הבדיקות: ${message}`
export const createFailed = (message: string) => `לא הצלחנו לפתוח בדיקה חדשה: ${message}`
export const deleteLabel = (title: string) => `מחיקת הבדיקה: ${title}`
export const ARCHIVED_GROUP = (count: number) => `בדיקות בארכיון (${count})`
export const archiveLabel = (title: string) => `העברה לארכיון: ${title}`
export const restoreLabel = (title: string) => `שחזור מהארכיון: ${title}`
export const archiveFailed = (message: string) => `לא הצלחנו להעביר את הבדיקה לארכיון: ${message}`
export const restoreFailed = (message: string) => `לא הצלחנו לשחזר את הבדיקה: ${message}`
export const cloneLabel = (title: string) => `שכפול הבדיקה: ${title}`
/** The tooltip and accessible name of a check's yellow bubble: how many of its offers wait on
 * the lender's answer. */
export const awaitingLabel = (count: number) =>
  count === 1
    ? 'הצעה אחת ממתינה לבירור מול הגוף המלווה'
    : `${count} הצעות ממתינות לבירור מול הגוף המלווה`
export const AWAITING_LIST_TITLE = 'ממתינות לבירור מול הגוף המלווה'
/** One awaiting offer's link: its lender, then the monthly payment when the person gave one. */
export const awaitingLink = (lender: string, monthlyPayment: string | null) =>
  monthlyPayment === null
    ? lender
    : `${lender} · ${monthlyPaymentText(formatShekels(monthlyPayment))}`
export const cloneFailed = (message: string) => `לא הצלחנו לשכפל את הבדיקה: ${message}`
export const deleteFailed = (message: string) => `לא הצלחנו למחוק את הבדיקה: ${message}`
export const signOutFailed = (message: string) => `היציאה לא הצליחה: ${message}`
