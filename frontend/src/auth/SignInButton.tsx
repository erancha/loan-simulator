import { useState } from 'react'
import { getAuthConfig } from '../api/auth.ts'
import { errorText } from '../api/client.ts'
import { SIGN_IN } from '../copy.ts'
import { startGoogleSignIn } from './googleRedirect.ts'
import { SignInReasons } from './SignInReasons.tsx'

/**
 * The landing's sign-in button: asks the server for the Google client id and leaves for Google.
 * Under the button it shows why a sign-in failed, whether Google refused it or the client id
 * could not be fetched, and then the toggle that explains signing in with Google.
 */
export function SignInButton({ refusal }: { refusal?: string }) {
  const [error, setError] = useState<string | null>(null)
  const start = () =>
    getAuthConfig().then(
      ({ clientId }) => startGoogleSignIn(clientId),
      (e: unknown) => setError(errorText(e)),
    )
  const message = error ?? refusal
  return (
    <div className="sign-in">
      <button type="button" className="sign-in-button" onClick={start}>
        <span className="sign-in-mark" aria-hidden="true">G</span>
        {SIGN_IN}
      </button>
      {message !== undefined && <p role="alert" className="error">{message}</p>}
      <SignInReasons />
    </div>
  )
}
