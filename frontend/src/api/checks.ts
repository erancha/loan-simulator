import { apiDelete, apiGet, apiPost, apiPut } from './client.ts'
import type { CheckSummary, CheckView, Finances, ReadingKind } from './types.ts'

export function listChecks(): Promise<CheckSummary[]> {
  return apiGet('/api/checks')
}

export function createCheck(): Promise<{ id: string }> {
  return apiPost('/api/checks', {})
}

/** A copy of the check, its conversation and all it produced, under a new id. */
export function cloneCheck(id: string): Promise<{ id: string }> {
  return apiPost(`/api/checks/${id}/clone`, {})
}

/** Closes the check; it stays readable and can be restored. */
export function archiveCheck(id: string): Promise<void> {
  return apiPost(`/api/checks/${id}/archive`, {})
}

export function restoreCheck(id: string): Promise<void> {
  return apiPost(`/api/checks/${id}/restore`, {})
}

export function deleteCheck(id: string): Promise<void> {
  return apiDelete(`/api/checks/${id}`)
}

export function getCheck(id: string): Promise<CheckView> {
  return apiGet(`/api/checks/${id}`)
}

/** The server accepts the message with an empty 202; the answer arrives on the event stream. */
export function sendMessage(id: string, text: string): Promise<void> {
  return apiPost(`/api/checks/${id}/messages`, { text })
}

/** A ceiling typed on the term card: the server saves it and shows a term card for it. */
export function sendTermCeiling(id: string, text: string, paymentCeiling: string): Promise<void> {
  return apiPost(`/api/checks/${id}/term-ceiling`, { text, payment_ceiling: paymentCeiling })
}

/**
 * Saves the term the person confirms on the term card, and the payment ceiling typed beside it
 * when one is given; refused outside 6 to 84 months.
 */
export function saveTerm(
  checkId: string,
  termMonths: number,
  paymentCeiling: string | null,
): Promise<void> {
  return apiPut(`/api/checks/${checkId}/term`, {
    term_months: termMonths,
    payment_ceiling: paymentCeiling,
  })
}

/** Sends the offer chip's sentence, which the server answers with the offer form and no model. */
export function sendOfferSample(id: string, text: string): Promise<void> {
  return apiPost(`/api/checks/${id}/offer-sample`, { text })
}

/** Sends the market-data sample, which the server answers from the market data with no model. */
export function sendMarketSample(id: string, text: string): Promise<void> {
  return apiPost(`/api/checks/${id}/market-sample`, { text })
}

/**
 * Replaces the figures named; one left out keeps its value. The server derives the check's
 * payment ceiling from the two figures once both are known, and answers with the saved check.
 */
export function saveFinances(checkId: string, update: Partial<Finances>): Promise<CheckView> {
  return apiPut(`/api/checks/${checkId}/finances`, update)
}

/** The opening card's loan: the purpose and amount are saved and the line is the person's message;
 * refused with 422 when the loan is. */
export function sendOpening(
  id: string,
  text: string,
  purpose: string,
  amount: string,
): Promise<void> {
  return apiPost(`/api/checks/${id}/opening`, { text, purpose, amount })
}

/** The term confirmed on the term card, as the person's message. */
export function sendTermConfirmation(id: string, text: string): Promise<void> {
  return apiPost(`/api/checks/${id}/term-confirmation`, { text })
}

/** The person's message for leaving the offer form, which the server answers with no model. */
export function sendOfferSkip(id: string, text: string): Promise<void> {
  return apiPost(`/api/checks/${id}/offer-skip`, { text })
}

/** Turns an awaiting offer into a saved offer by the reading the person confirms. */
export function confirmReading(id: string, awaitingId: string, kind: ReadingKind): Promise<void> {
  return apiPut(`/api/checks/${id}/awaiting-offers/${awaitingId}`, { reading: kind })
}

/** The lender's answer to an offer quoted for less than the check's loan: whether it lends the
 * loan amount on the same terms, with the reading the person chose; the offer is saved at the
 * loan amount, or dropped. */
export function answerAmount(
  id: string,
  awaitingId: string,
  covers: boolean,
  kind: ReadingKind | null,
): Promise<void> {
  return apiPut(`/api/checks/${id}/awaiting-offers/${awaitingId}/amount`, {
    covers,
    reading: kind,
  })
}
