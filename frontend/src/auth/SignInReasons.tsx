import { useState } from 'react'
import { withBold } from '../check/emphasis.tsx'
import {
  SIGN_IN_WHY,
  SIGN_IN_WHY_LEAD,
  SIGN_IN_WHY_LINK,
  SIGN_IN_WHY_POINTS,
} from '../copy.ts'

// Google's help page "How Sign in with Google helps you share data safely". It carries no
// language parameter, so Google answers in the visitor's own language.
const GOOGLE_HELP_URL = 'https://support.google.com/accounts/answer/12921417'

/**
 * The toggle under the sign-in button and the text it opens in place: why signing in with Google
 * is safe for a visitor who does not know this site, ending with a link to Google's own account
 * of it.
 */
export function SignInReasons() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        className="sign-in-why"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {SIGN_IN_WHY}
      </button>
      {open && (
        <div className="sign-in-why-text">
          <p>{withBold(SIGN_IN_WHY_LEAD)}</p>
          <ul className="landing-details">
            {SIGN_IN_WHY_POINTS.map((point) => (
              <li key={point}>{withBold(point)}</li>
            ))}
          </ul>
          <a href={GOOGLE_HELP_URL} target="_blank" rel="noreferrer">
            {SIGN_IN_WHY_LINK}
          </a>
        </div>
      )}
    </>
  )
}
