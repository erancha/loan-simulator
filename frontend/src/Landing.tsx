import { useState } from 'react'
import type { ReactNode } from 'react'
import { withBold } from './check/emphasis.tsx'
import { APP_TITLE, LANDING_DETAILS, LANDING_PITCH, LESS, MORE } from './copy.ts'

/**
 * The screens before sign-in: one card in the middle of the page, under the tab's icon and the
 * product name. Signed out, the card pitches the product over the sign-in button, with a toggle
 * that adds the details; the other states show only their own line.
 */
export function Landing({ pitch = false, children }: { pitch?: boolean; children: ReactNode }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <main className="landing">
      <div className="landing-card">
        <h1 className="app-heading">
          {/* The same file as the tab's icon, so the two cannot drift apart; decorative. */}
          <img className="app-icon" src="/favicon.svg" alt="" /> {APP_TITLE}
        </h1>
        {pitch && (
          <>
            {LANDING_PITCH.map((paragraph) => (
              <p key={paragraph} className="landing-pitch">
                {withBold(paragraph)}
              </p>
            ))}
            {expanded && (
              <ul className="landing-details">
                {LANDING_DETAILS.map((detail) => (
                  <li key={detail}>{withBold(detail)}</li>
                ))}
              </ul>
            )}
            <button
              type="button"
              className="landing-more"
              aria-expanded={expanded}
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? LESS : MORE}
            </button>
          </>
        )}
        {children}
      </div>
    </main>
  )
}
