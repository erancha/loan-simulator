import type { CheckArchived } from '../api/types.ts'
import { MONEY_FIELDS } from '../profile/copy.ts'
import {
  ARCHIVED_PROFILE_TITLE,
  ARCHIVED_TITLE,
  CONTINUED_LINK,
  archivedFigure,
  archivedReason,
  manualArchiveLine,
  profileFieldName,
} from './copy.ts'

interface Props {
  archive: CheckArchived
  /** The check that replaced this one; null when the archive came from a profile edit. */
  continuedIn: string | null
  onOpenCheck: (id: string) => void
}

/**
 * The note that closes an archived check. After a profile change it says when and why the check
 * closed and lists every figure of the profile its recommendation was computed from, in the
 * panel's order, so the conversation above it reads in context. A check the person archived
 * themselves says only when.
 */
export function ArchiveNote({ archive, continuedIn, onOpenCheck }: Props) {
  const at = new Date(archive.archived_at)
  const profile = archive.previous_profile
  return (
    <div className="bubble bubble-assistant check-note" role="note">
      <p className="question-label">{ARCHIVED_TITLE}</p>
      {profile === null ? (
        <p>{manualArchiveLine(at)}</p>
      ) : (
        <>
          <p>{archivedReason(at, archive.changes)}</p>
          <p>{ARCHIVED_PROFILE_TITLE}:</p>
          <ul>
            {MONEY_FIELDS.map(({ key: field }) => (
              <li key={field}>{`${profileFieldName(field)}: ${archivedFigure(profile[field])}`}</li>
            ))}
          </ul>
        </>
      )}
      {continuedIn !== null && (
        <button type="button" className="primary" onClick={() => onOpenCheck(continuedIn)}>
          {CONTINUED_LINK}
        </button>
      )}
    </div>
  )
}
