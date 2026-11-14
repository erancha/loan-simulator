import { useState } from 'react'
import type { ReactNode } from 'react'
import { withBold } from './check/emphasis.tsx'
import {
  APP_TITLE,
  DEMO_HINT,
  DEMO_LINK,
  INVITE_LINK,
  LANDING_DETAILS,
  LANDING_LEAD,
  LANDING_STEPS,
  LESS,
  MORE,
  SOURCE_LINK,
  versionLine,
} from './copy.ts'
import { whatsAppInviteUrl } from './invite.ts'

// The recorded check replayed in the real page, built beside it from demo.html.
const DEMO_PATH = '/demo.html'
const SOURCE_URL = 'https://github.com/erancha/loan-simulator'

/**
 * The screens before sign-in: one card in the middle of the page, under the tab's icon, the
 * product name and the line naming the running build. Signed out, the card pitches the product
 * over the sign-in button, with a toggle that adds the details, and links under the card open the
 * demo, invite a friend or open the source; the other states show only their own line.
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
        {/* A sibling of the heading, so the heading's accessible name stays the bare title. */}
        <p className="app-version">{versionLine(__APP_VERSION__, __APP_COMMIT_DATE__)}</p>
        {pitch && (
          <>
            <p className="landing-pitch">{withBold(LANDING_LEAD)}</p>
            <ol className="landing-steps">
              {LANDING_STEPS.map((step) => (
                <li key={step.title}>
                  <span>
                    <strong>{step.title}</strong> {withBold(step.text)}
                  </span>
                </li>
              ))}
            </ol>
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
      {pitch && (
        <footer className="landing-links">
          <a href={DEMO_PATH} target="_blank" rel="noreferrer" title={DEMO_HINT}>
            {DEMO_LINK}
          </a>
          <a href={whatsAppInviteUrl()} target="_blank" rel="noreferrer">
            {INVITE_LINK}
          </a>
          <a href={SOURCE_URL} target="_blank" rel="noreferrer">
            {SOURCE_LINK}
          </a>
        </footer>
      )}
    </main>
  )
}
