import { useState } from 'react'
import type { CheckSummary } from '../api/types.ts'
import { CHIP_EXAMPLE } from '../check/copy.ts'
import { formatShekels } from '../money.ts'
import {
  ARCHIVED,
  ARCHIVED_GROUP,
  CHECKS_HEADING,
  CONFIRM_DELETE,
  DELETE_CANCELLED,
  DELETE_CONFIRMED,
  NEW_CHECK,
  RECOMMENDATION_READY,
  STALE_PROFILE,
  UNTITLED_CHECK,
  archiveLabel,
  cloneLabel,
  deleteLabel,
  restoreLabel,
} from './copy.ts'
import { Icon } from './Icon.tsx'
import type { IconName } from './Icon.tsx'

interface Props {
  checks: CheckSummary[]
  selectedId: string | null
  onSelect: (id: string) => void
  onCreate: () => void
  /** Whether the archived group is unfolded; its owner keeps it across a switch of checks. */
  archivedOpen: boolean
  onArchivedToggle: (open: boolean) => void
  onClone: (id: string) => void
  onArchive: (id: string) => void
  onRestore: (id: string) => void
  onDelete: (id: string) => void
}

/**
 * The person's checks, newest first, with the one open marked and the button for a new one. The
 * archived checks follow the live ones in their own group, folded until the person opens it or
 * jumps to one of them, so they neither mix with the live checks nor fill the sidebar. Every
 * check has a duplicate icon. A live check also has an archive icon; an archived one has a
 * restore icon while its figures still match the profile, and a delete icon. Only an archived
 * check can be deleted, so a delete is always a second step. It cannot be undone, so its icon
 * first asks beside the check, with focus on the cancel button.
 */
export function ChecksList({
  checks,
  selectedId,
  onSelect,
  onCreate,
  archivedOpen,
  onArchivedToggle,
  onClone,
  onArchive,
  onRestore,
  onDelete,
}: Props) {
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const live = checks.filter((check) => !check.archived)
  const archived = checks.filter((check) => check.archived)

  /** One icon of a check's column, named for a screen reader and on hover by what it does. */
  const action = (
    icon: IconName,
    kind: 'check-clone' | 'check-delete',
    label: (title: string) => string,
    run: () => void,
    check: CheckSummary,
  ) => {
    const name = label(check.goal?.purpose ?? UNTITLED_CHECK)
    return (
      <button
        type="button"
        className={`check-action ${kind}`}
        aria-label={name}
        title={name}
        onClick={run}
      >
        <Icon name={icon} />
      </button>
    )
  }

  const item = (check: CheckSummary) => (
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
          {check.recommendation !== null && !check.archived && (
            <span className="check-chips">
              <span className="chip chip-green">{RECOMMENDATION_READY}</span>
              {check.recommends_examples_only && (
                <span className="chip chip-example">{CHIP_EXAMPLE}</span>
              )}
            </span>
          )}
          {check.archived ? (
            <span className="chip chip-gray">{ARCHIVED}</span>
          ) : (
            check.profile_stale && <span className="chip chip-amber">{STALE_PROFILE}</span>
          )}
        </button>
        <div className="check-actions">
          {action('copy', 'check-clone', cloneLabel, () => onClone(check.id), check)}
          {check.archived
            ? check.restorable &&
              action('restore', 'check-clone', restoreLabel, () => onRestore(check.id), check)
            : action('archive', 'check-clone', archiveLabel, () => onArchive(check.id), check)}
          {check.archived &&
            action('trash', 'check-delete', deleteLabel, () => setConfirmingId(check.id), check)}
        </div>
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
  )

  return (
    <nav className="checks-list" aria-label={CHECKS_HEADING}>
      <h2 className="panel-title">{CHECKS_HEADING}</h2>
      <button type="button" className="primary" onClick={onCreate}>
        {NEW_CHECK}
      </button>
      <ul>{live.map(item)}</ul>
      {archived.length > 0 && (
        <details
          className="checks-archived"
          open={archivedOpen}
          onToggle={(event) => onArchivedToggle(event.currentTarget.open)}
        >
          <summary>{ARCHIVED_GROUP(archived.length)}</summary>
          <ul>{archived.map(item)}</ul>
        </details>
      )}
    </nav>
  )
}
