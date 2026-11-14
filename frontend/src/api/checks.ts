import { apiDelete, apiGet, apiPost } from './client.ts'
import type { CheckSummary, CheckView } from './types.ts'

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

/** Closes the check; it stays readable and can be restored while its figures match the profile. */
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
