/**
 * Sign-in with Google by redirect: the page sends the browser to Google, which sends it back to
 * this page with a signed ID token in the URL fragment.
 *
 * Core responsibilities:
 * - startGoogleSignIn leaves for Google carrying a fresh nonce kept in sessionStorage
 * - takeRedirectResult reads and clears what Google put in the fragment on the way back
 */
const AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
const NONCE_KEY = 'google-sign-in-nonce'

export type RedirectResult = { credential: string } | { error: string }

export function startGoogleSignIn(clientId: string): void {
  const nonce = crypto.randomUUID()
  sessionStorage.setItem(NONCE_KEY, nonce)
  const query = new URLSearchParams({
    client_id: clientId,
    redirect_uri: `${window.location.origin}/`,
    response_type: 'id_token',
    scope: 'openid email profile',
    nonce,
    prompt: 'select_account',
  })
  window.location.assign(`${AUTH_URL}?${query}`)
}

/** The nonce claim of an ID token, read without verifying: the server verifies the signature. */
function nonceOf(token: string): unknown {
  const payload = token.split('.')[1]
  if (payload === undefined) throw new Error('the Google ID token has no payload')
  const base64 = payload.replace(/-/g, '+').replace(/_/g, '/')
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0))
  return (JSON.parse(new TextDecoder().decode(bytes)) as { nonce?: unknown }).nonce
}

/**
 * Null when the page was not opened by Google's redirect. Otherwise the fragment is cleared and
 * the token is returned only when its nonce is the one this tab stored before leaving: the nonce
 * proves the token answers this tab's own request, not one injected into the URL by someone else.
 */
export function takeRedirectResult(): RedirectResult | null {
  const params = new URLSearchParams(window.location.hash.slice(1))
  const token = params.get('id_token')
  const error = params.get('error')
  if (token === null && error === null) return null

  history.replaceState(null, '', window.location.pathname + window.location.search)
  const stored = sessionStorage.getItem(NONCE_KEY)
  sessionStorage.removeItem(NONCE_KEY)
  if (error !== null) return { error }
  if (token === null || stored === null || nonceOf(token) !== stored) {
    return { error: 'nonce_mismatch' }
  }
  return { credential: token }
}
