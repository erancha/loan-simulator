import type { CheckFollows } from '../api/types.ts'
import { FOLLOWS_TITLE, ORIGIN_LINK, followsReason } from './copy.ts'

interface Props {
  follows: CheckFollows
  onOpenCheck: (id: string) => void
}

/**
 * The note that opens a follow-up check: why it replaced an archived check, and a way back to
 * that check, so the conversation that led here stays one tap away.
 */
export function FollowsNote({ follows, onOpenCheck }: Props) {
  return (
    <div className="bubble bubble-assistant check-note" role="note">
      <p className="question-label">{FOLLOWS_TITLE}</p>
      <p>{followsReason(follows.changes)}</p>
      <button type="button" className="primary" onClick={() => onOpenCheck(follows.check_id)}>
        {ORIGIN_LINK}
      </button>
    </div>
  )
}
