/** demo.html's entry: installs the demo backend over fetch and EventSource, then renders the real
 * app under a banner that says the page is a recording. */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from '../App.tsx'
import { DEMO_BANNER, DEMO_RESTART } from '../copy.ts'
import '../styles/global.css'
import { createDemoBackend } from './backend.ts'
import { fillBox } from './fillBox.ts'
import type { Recording } from './backend.ts'
import recording from './recording.json'

// Slow enough to read each bubble as it lands, quick enough that the whole check plays in about
// two minutes; a reply types at a pace a person reads at, and a typed answer stays in its box long
// enough to read before it is sent.
const PACE = { pauseMs: 1400, typingMs: 60, typedChars: 6, entryMs: 1000 }

const backend = createDemoBackend(recording as Recording, PACE, fillBox)
window.fetch = backend.fetch as typeof window.fetch
window.EventSource = backend.EventSource as unknown as typeof window.EventSource

const root = document.getElementById('root')
if (root === null) throw new Error('missing #root element')
createRoot(root).render(
  <StrictMode>
    <p className="demo-banner">
      {DEMO_BANNER}{' '}
      <a href="/demo.html">{DEMO_RESTART}</a>
    </p>
    <App />
  </StrictMode>,
)
