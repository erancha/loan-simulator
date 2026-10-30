import { apiDelete, apiGet, apiPost } from './client.ts'
import type { CheckSummary, CheckView } from './types.ts'

export function listChecks(): Promise<CheckSummary[]> {
  return apiGet('/api/checks')
}

export function createCheck(): Promise<{ id: string }> {
  return apiPost('/api/checks', {})
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
