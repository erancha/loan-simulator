import { useState } from 'react'
import type { CheckSummary } from '../api/types.ts'
import { formatShekels } from '../money.ts'
import {
  CHECKS_HEADING,
  CONFIRM_DELETE,
  DELETE_CANCELLED,
  DELETE_CONFIRMED,
  NEW_CHECK,
  RECOMMENDATION_READY,
  STALE_PROFILE,
  UNTITLED_CHECK,
  deleteLabel,
} from './copy.ts'
import { Icon } from './Icon.tsx'

interface Props {
  checks: CheckSummary[]
  selectedId: string | null
  onSelect: (id: string) => void
  onCreate: () => void
  onDelete: (id: string) => void
}

/**
 * The person's checks, newest first, with the one open marked and the button for a new one. A
 * delete cannot be undone, so each check's delete icon first asks beside the check, with focus on
 * the cancel button.
 */
export function ChecksList({ checks, selectedId, onSelect, onCreate, onDelete }: Props) {
  const [confirmingId, setConfirmingId] = useState<string | null>(null)

  return (
    <nav className="checks-list" aria-label={CHECKS_HEADING}>
      <h2 className="panel-title">{CHECKS_HEADING}</h2>
      <button type="button" className="primary" onClick={onCreate}>
        {NEW_CHECK}
      </button>
      <ul>
        {checks.map((check) => (
          <li key={check.id}>
            <div className="check-row">
              <button
                type="button"
                className="check-item"
                aria-current={check.id === selectedId ? 'true' : undefined}
                onClick={() => onSelect(check.id)}
              >
                <span className="check-title">{check.goal?.purpose ?? UNTITLED_CHECK}</span>
                {check.goal !== null && <span>{formatShekels(check.goal.price)}</span>}
                {check.recommendation !== null && (
                  <span className="chip chip-green">{RECOMMENDATION_READY}</span>
                )}
                {check.profile_stale && <span className="chip chip-amber">{STALE_PROFILE}</span>}
              </button>
              <button
                type="button"
                className="check-delete"
                aria-label={deleteLabel(check.goal?.purpose ?? UNTITLED_CHECK)}
                title={deleteLabel(check.goal?.purpose ?? UNTITLED_CHECK)}
                onClick={() => setConfirmingId(check.id)}
              >
                <Icon name="trash" />
              </button>
            </div>
            {confirmingId === check.id && (
              <div className="check-confirm">
                <p>{CONFIRM_DELETE}</p>
                <button
                  type="button"
                  className="check-confirm-delete"
                  onClick={() => {
                    setConfirmingId(null)
                    onDelete(check.id)
                  }}
                >
                  {DELETE_CONFIRMED}
                </button>
                <button
                  type="button"
                  ref={(cancel) => cancel?.focus()}
                  onClick={() => setConfirmingId(null)}
                >
                  {DELETE_CANCELLED}
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </nav>
  )
}
