import { useEffect, useState } from 'react'
import {
  DEMO_BANNER,
  DEMO_ENTER,
  DEMO_NOTICE_CLOSE,
  DEMO_RESTART,
  DEMO_UNAVAILABLE,
} from '../copy.ts'
import { NEW_CHECK } from '../shell/copy.ts'
import { DEMO_UNAVAILABLE_EVENT } from './backend.ts'
import { holdButtons } from './holdButtons.ts'

/**
 * Whether the tab the demo was opened from is still open on this site. The landing page's demo
 * link keeps the tie between the two tabs; a tab that moved to another site refuses the read of
 * its address with a SecurityError.
 */
function openedFromSimulatorTab(): boolean {
  const opener = window.opener as Window | null
  if (opener === null || opener.closed) return false
  try {
    return opener.location.origin === location.origin
  } catch (caught) {
    if (caught instanceof DOMException && caught.name === 'SecurityError') return false
    throw caught
  }
}

/**
 * What demo.html shows over the replayed check: the banner that says the page is a recording, and,
 * once the visitor tries an action only a server could carry out, a notice that it is unavailable
 * here, with a link into the simulator. The notice stays until closed and returns with the next
 * such action. The link closes the demo's tab when the tab it was opened from still shows the
 * simulator, so the visitor returns there; otherwise, or when the browser refuses the close, it
 * loads the simulator in the demo's tab.
 *
 * Until the replay ends, the button that opens a new check is disabled, so a visitor is not led
 * out of the recording midway.
 */
export function DemoBanner({ replay }: { replay: Promise<void> }) {
  const [unavailable, setUnavailable] = useState(false)
  useEffect(() => {
    const release = holdButtons(NEW_CHECK)
    void replay.then(release)
    return release
  }, [replay])
  useEffect(() => {
    const show = () => setUnavailable(true)
    window.addEventListener(DEMO_UNAVAILABLE_EVENT, show)
    return () => window.removeEventListener(DEMO_UNAVAILABLE_EVENT, show)
  }, [])
  return (
    <>
      <p className="demo-banner">
        {DEMO_BANNER} <a href="/demo.html">{DEMO_RESTART}</a>
      </p>
      {unavailable && (
        <p className="demo-notice" role="status">
          {DEMO_UNAVAILABLE}{' '}
          <a
            href="/"
            onClick={() => {
              if (openedFromSimulatorTab()) window.close()
            }}
          >
            {DEMO_ENTER}
          </a>
          .
          <button
            type="button"
            className="link-button"
            aria-label={DEMO_NOTICE_CLOSE}
            onClick={() => setUnavailable(false)}
          >
            ✕
          </button>
        </p>
      )}
    </>
  )
}
