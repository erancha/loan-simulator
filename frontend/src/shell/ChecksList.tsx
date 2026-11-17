import { useId, useState } from 'react'
import type { CheckSummary } from '../api/types.ts'
import { CHIP_EXAMPLE, checkTitle, termText } from '../check/copy.ts'
import { withValues } from '../check/emphasis.tsx'
import {
  ARCHIVED,
  ARCHIVED_GROUP,
  CHECKS_HEADING,
  AWAITING_LIST_TITLE,
  CONFIRM_DELETE,
  DELETE_CANCELLED,
  DELETE_CONFIRMED,
  FINANCES_LINK,
  NEW_CHECK,
  OFFER_EVALUATED,
  RECOMMENDATION_READY,
  UNTITLED_CHECK,
  archiveLabel,
  awaitingLabel,
  awaitingLink,
  cloneLabel,
  deleteLabel,
  restoreLabel,
} from './copy.ts'
import { Icon } from './Icon.tsx'
import type { IconName } from './Icon.tsx'

/** A check's title: built from its loan, or the new-check title until it has one. */
function titleOf(check: CheckSummary): string {
  return check.loan === null ? UNTITLED_CHECK : checkTitle(check.loan)
}

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
  onOpenAwaiting: (checkId: string, awaitingId: string) => void
  /** Whether the open check shows its finances line. */
  financesShown: boolean
  /** The open check's term card takes the ceiling, so its finances link is not offered. */
  financesLocked: boolean
  onFinancesToggle: (id: string) => void
}

/**
 * The person's checks, newest first, with the one open marked and the button for a new one. A
 * check with a recommendation has a ready chip when it compares more than one option, an
 * evaluated chip when its card holds one real offer alone, or only an example chip while it rests
 * on examples, which nobody can take, so there is nothing to recommend yet. The archived checks
 * follow the live ones in their own group, folded until the person opens it or jumps to one of
 * them, or unfolded on load when every check is archived, so they neither mix with the live
 * checks nor fill the sidebar. A check the person has written to has a duplicate icon,
 * and when live an archive icon; one showing only the opening card has neither, since it has
 * nothing to copy or keep. An archived check has a restore icon and a delete icon. Only an
 * archived check can be deleted, so a delete is always a second step. It cannot be undone, so its
 * icon first asks beside the check, with focus on the cancel button. A live check with offers
 * awaiting the lender's answer has a yellow bubble counting them, which unfolds under the check a
 * list of links, one per offer, each opening the check on its conversation. A check whose
 * finances hold a figure has a finances link on its months row, which opens the check on its
 * conversation with the finances line shown, and hides the line again on a second tap; the open
 * check has no such link while its term card takes an answer. A check's item in the list is a
 * container rather than one button so the finances link can sit inside it: the select button
 * holds the title, its click area stretches over the item, and it takes the item's text as its
 * name.
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
  onOpenAwaiting,
  financesShown,
  financesLocked,
  onFinancesToggle,
}: Props) {
  const idPrefix = useId()
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [awaitingOpenId, setAwaitingOpenId] = useState<string | null>(null)
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
    const name = label(titleOf(check))
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

  const item = (check: CheckSummary) => {
    const id = (part: string) => `${idPrefix}${check.id}-${part}`
    const hasTerm = check.term_months !== null
    const financesLink = check.has_finances && !(financesLocked && check.id === selectedId)
    const ready = check.recommendation !== null && !check.archived
    const nameParts = [
      'title',
      ...(hasTerm ? ['term'] : []),
      ...(ready ? ['chips'] : []),
      ...(check.archived ? ['archived'] : []),
    ]
    return (
      <li key={check.id}>
        <div className="check-row">
          <div className="check-item">
            <button
              type="button"
              className="check-select"
              aria-current={check.id === selectedId ? 'true' : undefined}
              aria-labelledby={nameParts.map(id).join(' ')}
              onClick={() => onSelect(check.id)}
            >
              <span id={id('title')} className="check-title">
                {withValues(titleOf(check))}
              </span>
            </button>
            {(hasTerm || financesLink) && (
              <span className="check-term-row">
                {check.term_months !== null && (
                  <span id={id('term')} className="check-term">
                    {withValues(termText(check.term_months))}
                  </span>
                )}
                {hasTerm && financesLink && <span aria-hidden="true"> · </span>}
                {financesLink && (
                  <button
                    type="button"
                    className="underline-link check-finances"
                    aria-expanded={financesShown && check.id === selectedId}
                    onClick={() => onFinancesToggle(check.id)}
                  >
                    {FINANCES_LINK}
                  </button>
                )}
              </span>
            )}
            {ready && (
              <span id={id('chips')} className="check-chips">
                {check.recommends_examples_only ? (
                  <span className="chip chip-example">{CHIP_EXAMPLE}</span>
                ) : (
                  <span className="chip chip-green">
                    {check.compares_options ? RECOMMENDATION_READY : OFFER_EVALUATED}
                  </span>
                )}
              </span>
            )}
            {check.archived && (
              <span id={id('archived')} className="chip chip-gray">
                {ARCHIVED}
              </span>
            )}
          </div>
          <div className="check-actions">
            {!check.archived && check.awaiting_offers.length > 0 && (
              <button
                type="button"
                className="check-awaiting"
                aria-label={awaitingLabel(check.awaiting_offers.length)}
                title={awaitingLabel(check.awaiting_offers.length)}
                aria-expanded={awaitingOpenId === check.id}
                onClick={() => setAwaitingOpenId(awaitingOpenId === check.id ? null : check.id)}
              >
                {check.awaiting_offers.length}
              </button>
            )}
            {check.started &&
              action('copy', 'check-clone', cloneLabel, () => onClone(check.id), check)}
            {check.archived &&
              action('restore', 'check-clone', restoreLabel, () => onRestore(check.id), check)}
            {!check.archived &&
              check.started &&
              action('archive', 'check-clone', archiveLabel, () => onArchive(check.id), check)}
            {check.archived &&
              action('trash', 'check-delete', deleteLabel, () => setConfirmingId(check.id), check)}
          </div>
        </div>
        {awaitingOpenId === check.id && !check.archived && (
          <div className="check-awaiting-list">
            <p>{AWAITING_LIST_TITLE}</p>
            <ul>
              {check.awaiting_offers.map((offer) => (
                <li key={offer.id}>
                  <button type="button" onClick={() => onOpenAwaiting(check.id, offer.id)}>
                    {awaitingLink(offer.lender, offer.monthly_payment)}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
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
  }

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
