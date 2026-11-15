import type { CheckArchived } from '../api/types.ts'
import { ARCHIVED_TITLE, manualArchiveLine } from './copy.ts'

interface Props {
  archive: CheckArchived
}

/** The note that closes an archived check's conversation: that it was archived and when. */
export function ArchiveNote({ archive }: Props) {
  return (
    <div className="bubble bubble-assistant check-note" role="note">
      <p className="question-label">{ARCHIVED_TITLE}</p>
      <p>{manualArchiveLine(new Date(archive.archived_at))}</p>
    </div>
  )
}
