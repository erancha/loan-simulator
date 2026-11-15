import { CLONED_TITLE, OPEN_CLONE } from './copy.ts'

interface Props {
  cloneId: string
  onOpenCheck: (id: string) => void
}

/** The note that hands a check over to its copy, with the way to the copy. */
export function CloneNote({ cloneId, onOpenCheck }: Props) {
  return (
    <div className="bubble bubble-assistant check-note" role="note">
      <p className="question-label">{CLONED_TITLE}</p>
      <button type="button" onClick={() => onOpenCheck(cloneId)}>
        {OPEN_CLONE}
      </button>
    </div>
  )
}
