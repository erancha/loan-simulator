/**
 * What the person reads while the agent runs a tool, by the tool's name as `turn.step` names it.
 * The backend's tests read this file and require one entry for each of the agent's tools, each
 * on a line of its own as `name: 'text',`.
 */
export const TOOL_ACTIVITY: Readonly<Record<string, string>> = {
  set_loan: 'שומר את סכום ההלוואה',
  set_term: 'שומר את מספר החודשים',
  set_ceiling: 'שומר את התקרה להחזר החודשי',
  update_finances: 'שומר את הנתונים הכספיים',
  save_examples: 'מחשב מסלולי דוגמא',
  save_offer: 'מחשב את ההצעה',
  read_offer: 'מזהה את סוג ההצעה',
  answer_offer_amount: 'שומר את תשובת הגוף המלווה',
  choose_option: 'מעדכן את ההמלצה לבחירה שלך',
  compare_terms: 'משווה בין תקופות',
  ask: 'מנסח שאלה',
  ask_term: 'מחשב את מספר החודשים',
  ask_offer: 'מכין את טופס ההצעה',
  show_chart: 'מכין גרף של נתוני השוק',
  show_scenario: 'מחשב תרחיש',
  simulate_loan: 'מחשב את ההלוואה',
  market_series: 'קורא את נתוני השוק',
}
