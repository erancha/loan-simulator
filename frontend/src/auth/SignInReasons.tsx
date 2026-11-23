import { useEffect, useRef } from 'react'
import { withBold } from '../check/emphasis.tsx'
import {
  NEW_TAB,
  SIGN_IN_WHY,
  SIGN_IN_WHY_CLOSE,
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
 * of it. The sign-in button owns whether it is open, since it frames itself while it is. A close
 * button at the end of the toggle's line closes it too, and the link marks that it opens a new tab,
 * so it is not taken for the way out.
 */
export function SignInReasons({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const toggle = useRef<HTMLButtonElement>(null)
  const text = useRef<HTMLDivElement>(null)
  // Opening scrolls down to the explanation's last line, which on a phone opens below the fold.
  useEffect(() => {
    if (open) text.current!.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [open])
  return (
    <>
      <div className="sign-in-why-row">
        <button
          ref={toggle}
          type="button"
          className="sign-in-why"
          aria-expanded={open}
          onClick={() => onOpenChange(!open)}
        >
          {SIGN_IN_WHY}
        </button>
        {open && (
          <button
            type="button"
            className="sign-in-why-close"
            aria-label={SIGN_IN_WHY_CLOSE}
            onClick={() => {
              onOpenChange(false)
              // The close button leaves with the text, so focus returns to what reopens it.
              toggle.current?.focus()
            }}
          >
            ✕
          </button>
        )}
      </div>
      {open && (
        <div ref={text} className="sign-in-why-text">
          <p>{withBold(SIGN_IN_WHY_LEAD)}</p>
          <ul className="landing-details">
            {SIGN_IN_WHY_POINTS.map((point) => (
              <li key={point}>{withBold(point)}</li>
            ))}
          </ul>
          <a
            href={GOOGLE_HELP_URL}
            target="_blank"
            rel="noreferrer"
            aria-label={`${SIGN_IN_WHY_LINK} ${NEW_TAB}`}
          >
            {SIGN_IN_WHY_LINK} <span aria-hidden="true">↗</span>
          </a>
        </div>
      )}
    </>
  )
}
