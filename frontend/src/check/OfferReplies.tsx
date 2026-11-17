/**
 * The replies to an offer that needs no card: one whose reading the agent identified, with the
 * market chip for checking today's prime, and one whose loan type it could not tell.
 */
import type { OfferIdentified } from '../api/types.ts'
import { identifiedText, MARKET_SAMPLE, OFFER_UNRECOGNIZED } from './copy.ts'
import { withValues } from './emphasis.tsx'

interface IdentifiedProps {
  offer: OfferIdentified
  /** False while a turn runs or the check is archived, which has no input for the chip to fill. */
  live: boolean
  onMarketChip: () => void
}

export function IdentifiedBubble({ offer, live, onMarketChip }: IdentifiedProps) {
  return (
    <div className="bubble bubble-assistant offer-identified">
      <p>{withValues(identifiedText(offer))}</p>
      <div className="chat-samples">
        <button type="button" disabled={!live} onClick={onMarketChip}>
          {MARKET_SAMPLE.label}
        </button>
      </div>
    </div>
  )
}

export function UnrecognizedBubble() {
  return <p className="bubble bubble-assistant">{OFFER_UNRECOGNIZED}</p>
}
