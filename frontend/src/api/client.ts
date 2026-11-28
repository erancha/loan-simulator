/**
 * The page's HTTP client for the agent API: JSON requests by method, a failed answer thrown as an
 * ApiException with the server's detail, and a window event on any 401.
 */
import { REQUEST_DATA_REFUSED, requestFailed } from '../copy.ts'

/** The message of a failed call, whatever was thrown. */
export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/** Fired on window when the server answers 401: the sign-in ended, whatever the page was doing. */
export const SIGNED_OUT_EVENT = 'ls:signed-out'

/**
 * A non-2xx answer. When the body carries fields beside `detail` (a 409's `check_id`, a 429's
 * `next_allowed`), `detail` is a record holding them plus the text under `message`.
 */
export class ApiException extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, detail: unknown) {
    super(detailText(status, detail))
    this.status = status
    this.detail = detail
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * The page shows a server-given detail text as it is. FastAPI's request validation 422 lists
 * English errors, which are logged; the page shows a Hebrew sentence instead.
 */
function detailText(status: number, detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    console.error('request rejected', detail)
    return REQUEST_DATA_REFUSED
  }
  if (isRecord(detail) && typeof detail.message === 'string') return detail.message
  return requestFailed(status)
}

/** Null when the body carries no detail. */
function errorDetail(body: unknown): unknown {
  if (!isRecord(body) || !('detail' in body)) return null
  const { detail, ...extras } = body
  return typeof detail === 'string' && Object.keys(extras).length > 0
    ? { message: detail, ...extras }
    : detail
}

async function send<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    if (response.status === 401) window.dispatchEvent(new Event(SIGNED_OUT_EVENT))
    throw new ApiException(response.status, errorDetail(body))
  }
  const text = await response.text()
  return (text === '' ? undefined : JSON.parse(text)) as T
}

function sendJson<T>(method: string, path: string, body: unknown): Promise<T> {
  return send<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function apiGet<T>(path: string): Promise<T> {
  return send<T>(path)
}

export function apiDelete(path: string): Promise<void> {
  return send<void>(path, { method: 'DELETE' })
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return sendJson<T>('POST', path, body)
}

export function apiPut<T>(path: string, body: unknown): Promise<T> {
  return sendJson<T>('PUT', path, body)
}
