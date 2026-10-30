/** Every Hebrew label and sentence of the signed-in shell: header, checks list and tabs. */
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
export const RECOMMENDATION_READY = 'המלצה מוכנה'
export const STALE_PROFILE = 'חושב לפי פרופיל קודם'
export const CHECKS_HEADING = 'הבדיקות שלי'
export const TABS_LABEL = 'חלקי העמוד'

export const TABS = [
  { pane: 'chat', label: 'שיחה' },
  { pane: 'card', label: 'המלצה' },
  { pane: 'side', label: 'פרופיל' },
] as const

export const loadFailed = (message: string) => `לא הצלחנו לטעון את הבדיקות: ${message}`
export const createFailed = (message: string) => `לא הצלחנו לפתוח בדיקה חדשה: ${message}`
export const deleteLabel = (title: string) => `מחיקת הבדיקה: ${title}`
export const deleteFailed = (message: string) => `לא הצלחנו למחוק את הבדיקה: ${message}`
export const signOutFailed = (message: string) => `היציאה לא הצליחה: ${message}`
