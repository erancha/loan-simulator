/** demo.html's entry: installs the demo backend over fetch and EventSource, then renders the real
 * app under the demo's banner and playback bar. */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from '../App.tsx'
import '../styles/global.css'
import { createDemoBackend } from './backend.ts'
import { DemoBanner } from './DemoBanner.tsx'
import { DemoControls } from './DemoControls.tsx'
import { fillBox } from './fillBox.ts'
import { PACE, START_RATE } from './pace.ts'
import type { Recording } from './backend.ts'
import recording from './recording.json'

const backend = createDemoBackend(recording as Recording, PACE, fillBox)
backend.clock.setRate(START_RATE)
window.fetch = backend.fetch as typeof window.fetch
window.EventSource = backend.EventSource as unknown as typeof window.EventSource

const root = document.getElementById('root')
if (root === null) throw new Error('missing #root element')
createRoot(root).render(
  <StrictMode>
    <DemoBanner replay={backend.finished} />
    <DemoControls clock={backend.clock} totalMs={backend.totalMs} replay={backend.finished} />
    <App />
  </StrictMode>,
)
