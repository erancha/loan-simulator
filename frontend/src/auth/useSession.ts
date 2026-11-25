import { useCallback, useEffect, useRef, useState } from 'react'
import { me, signIn, signOut as signOutRequest } from '../api/auth.ts'
import { ApiException, SIGNED_OUT_EVENT, errorText } from '../api/client.ts'
import type { User } from '../api/types.ts'
import { SIGN_IN_REFUSED } from '../copy.ts'
import { useLatest } from '../latest.ts'
import { takeRedirectResult, type RedirectResult } from './googleRedirect.ts'

/** Google's error code for a person who closed the sign-in page. */
const CANCELLED = 'access_denied'

export type Session =
  | { state: 'loading' }
  | { state: 'signed-out'; refusal?: string }
  | { state: 'signed-in'; user: User }
  | { state: 'failed'; message: string }

/**
 * Who is signed in, settled once on mount and kept current afterwards. A page opened by Google's
 * redirect posts the token it carries; any other page asks the server who is signed in. A
 * sign-out or any 401 from the API drops back to signed-out. A server that cannot be asked at all
 * is a failure, shown as such rather than as a sign-in screen. A sign-in Google or the server
 * refused is signed-out with a refusal to show, except when the person cancelled. `refresh` asks
 * the server again for the signed-in person, whose message status changes as they send.
 */
export function useSession() {
  const [session, setSession] = useState<Session>({ state: 'loading' })

  // Taken once per page: it clears the URL fragment, and Strict Mode runs the effect twice.
  const redirectResult = useRef<RedirectResult | null | undefined>(undefined)

  useEffect(() => {
    let current = true
    const failure = (error: unknown) => {
      if (!current) return
      if (error instanceof ApiException && error.status === 401) {
        setSession({ state: 'signed-out' })
      } else {
        setSession({ state: 'failed', message: errorText(error) })
      }
    }
    redirectResult.current ??= takeRedirectResult()
    const redirect = redirectResult.current
    if (redirect === null) {
      me().then((user) => current && setSession({ state: 'signed-in', user }), failure)
    } else if ('credential' in redirect) {
      signIn(redirect.credential).then(
        (user) => current && setSession({ state: 'signed-in', user }),
        (error: unknown) => {
          if (!current) return
          if (error instanceof ApiException && error.status === 401) {
            setSession({ state: 'signed-out', refusal: SIGN_IN_REFUSED })
          } else {
            failure(error)
          }
        },
      )
    } else {
      const refused: Session =
        redirect.error === CANCELLED
          ? { state: 'signed-out' }
          : { state: 'signed-out', refusal: SIGN_IN_REFUSED }
      Promise.resolve().then(() => current && setSession(refused))
    }
    return () => {
      current = false
    }
  }, [])

  useEffect(() => {
    const onSignedOut = () => setSession({ state: 'signed-out' })
    window.addEventListener(SIGNED_OUT_EVENT, onSignedOut)
    return () => window.removeEventListener(SIGNED_OUT_EVENT, onSignedOut)
  }, [])

  const signedIn = useCallback((user: User) => setSession({ state: 'signed-in', user }), [])
  const latest = useLatest()
  const refresh = useCallback(() => {
    const request = latest.begin()
    // A 401 signs the person out through SIGNED_OUT_EVENT; any other failure keeps the status
    // the page already shows, and the next refresh asks again.
    me().then(
      (user) => {
        if (!latest.accept(request)) return
        setSession((current) => (current.state === 'signed-in' ? { ...current, user } : current))
      },
      (error: unknown) => console.error('the message status was not refreshed', error),
    )
  }, [latest])
  const signOut = useCallback(async () => {
    await signOutRequest()
    setSession({ state: 'signed-out' })
  }, [])
  return { session, signedIn, signOut, refresh }
}
