import { useCallback, useEffect, useRef, useState } from 'react'
import {
  archiveCheck,
  cloneCheck,
  createCheck,
  deleteCheck,
  listChecks,
  restoreCheck,
  sendMessage,
} from '../api/checks.ts'
import { ApiException, errorText } from '../api/client.ts'
import type { CheckSummary, User } from '../api/types.ts'
import { CheckPage } from '../check/CheckPage.tsx'
import { AccountMenu } from './AccountMenu.tsx'
import { ChecksList } from './ChecksList.tsx'
import { APP_TITLE } from '../copy.ts'
import { useLatest } from '../latest.ts'
import {
  ARCHIVE_WHILE_ANSWERING,
  DELETE_WHILE_ANSWERING,
  NEW_CHECK,
  NO_CHECKS,
  archiveFailed,
  cloneFailed,
  createFailed,
  deleteFailed,
  loadFailed,
  restoreFailed,
  signOutFailed,
} from './copy.ts'
import { TabBar } from './TabBar.tsx'
import type { Pane } from './TabBar.tsx'

const HASH_PREFIX = '#check='

function hashedId(): string | null {
  return location.hash.startsWith(HASH_PREFIX) ? location.hash.slice(HASH_PREFIX.length) : null
}

function newestFirst(checks: CheckSummary[]): CheckSummary[] {
  return [...checks].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
}

interface Props {
  user: User
  /** Rejects when the server did not end the session. */
  onSignOut: () => Promise<void>
}

/**
 * The signed-in page: header, the person's checks, and the open check laid out by CSS as three
 * columns or, on a phone, as the pane the tab bar picks. The open check is kept in the URL hash.
 */
export function Shell({ user, onSignOut }: Props) {
  const [checks, setChecks] = useState<CheckSummary[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [createError, setCreateError] = useState<string | null>(null)
  const [signOutError, setSignOutError] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [wantedId, setWantedId] = useState(hashedId)
  const [pane, setPane] = useState<Pane>('chat')
  // Kept here because the checks list is rebuilt with the check page on every switch of checks.
  const [archivedOpen, setArchivedOpen] = useState(false)
  const listedOnce = useRef(false)

  const latest = useLatest()
  const refresh = useCallback(() => {
    const request = latest.begin()
    return listChecks().then(
      (fetched) => {
        if (!latest.accept(request)) return
        // On the page's load the archived group starts folded, unless it holds every check: a
        // folded group would then show the person an empty list.
        if (!listedOnce.current) {
          listedOnce.current = true
          if (fetched.length > 0 && fetched.every((check) => check.archived)) setArchivedOpen(true)
        }
        setChecks(newestFirst(fetched))
        setLoadError(null)
      },
      (error: unknown) => {
        if (latest.accept(request)) setLoadError(errorText(error))
      },
    )
  }, [latest])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const selected =
    checks === null ? null : (checks.find((check) => check.id === wantedId) ?? checks[0] ?? null)
  const selectedId = selected?.id ?? null

  useEffect(() => {
    if (selectedId !== null && hashedId() !== selectedId) {
      history.replaceState(null, '', `${HASH_PREFIX}${selectedId}`)
    }
  }, [selectedId])

  // Going to an archived check unfolds the archived group, so the check shows marked in the list;
  // a check opened by the page's load leaves the group folded.
  function select(id: string, opening: Pane) {
    if (checks?.find((listed) => listed.id === id)?.archived === true) setArchivedOpen(true)
    setWantedId(id)
    setCreateError(null)
    setPane(opening)
  }

  // A check with a recommendation opens on its card, the answer the person comes back for; any
  // other check opens on its conversation.
  function open(id: string) {
    const check = checks?.find((listed) => listed.id === id)
    if (check === undefined) throw new Error(`check ${id} is not in the list it was picked from`)
    select(id, check.recommendation === null ? 'chat' : 'card')
  }

  // Folding the archived group would hide the open check when it is archived, so the newest
  // live check opens in its place; with no live check, the archived one stays open.
  function toggleArchived(unfolded: boolean) {
    if (checks === null || selected === null) {
      throw new Error('the archived group renders only with checks, one of them open')
    }
    setArchivedOpen(unfolded)
    if (unfolded || !selected.archived) return
    const newestLive = checks.find((check) => !check.archived)
    if (newestLive !== undefined) open(newestLive.id)
  }

  async function create() {
    try {
      const { id } = await createCheck()
      await refresh()
      select(id, 'chat')
    } catch (error) {
      setCreateError(createFailed(errorText(error)))
    }
  }

  async function openCheck(id: string) {
    await refresh()
    select(id, 'chat')
  }

  /** Clones a check and opens the copy, first sending it the line when one is given. */
  async function duplicate(id: string, line: string | null) {
    setCreateError(null)
    try {
      const { id: cloneId } = await cloneCheck(id)
      if (line !== null) await sendMessage(cloneId, line)
      await openCheck(cloneId)
    } catch (error) {
      setCreateError(cloneFailed(errorText(error)))
    }
  }

  async function archive(id: string) {
    setCreateError(null)
    try {
      await archiveCheck(id)
      await refresh()
    } catch (error) {
      setCreateError(
        error instanceof ApiException && error.status === 409
          ? ARCHIVE_WHILE_ANSWERING
          : archiveFailed(errorText(error)),
      )
    }
  }

  async function restore(id: string) {
    setCreateError(null)
    try {
      await restoreCheck(id)
      await refresh()
    } catch (error) {
      setCreateError(restoreFailed(errorText(error)))
    }
  }

  async function remove(id: string) {
    setDeleteError(null)
    try {
      await deleteCheck(id)
      if (hashedId() === id) history.replaceState(null, '', location.pathname + location.search)
      await refresh()
    } catch (error) {
      setDeleteError(
        error instanceof ApiException && error.status === 409
          ? DELETE_WHILE_ANSWERING
          : deleteFailed(errorText(error)),
      )
    }
  }

  async function signOut() {
    try {
      await onSignOut()
      history.replaceState(null, '', location.pathname + location.search)
    } catch (error) {
      setSignOutError(signOutFailed(errorText(error)))
    }
  }

  const list =
    checks === null ? null : (
      <ChecksList
        checks={checks}
        selectedId={selectedId}
        onSelect={open}
        onCreate={() => void create()}
        archivedOpen={archivedOpen}
        onArchivedToggle={toggleArchived}
        onClone={(id) => void duplicate(id, null)}
        onArchive={(id) => void archive(id)}
        onRestore={(id) => void restore(id)}
        onDelete={(id) => void remove(id)}
      />
    )

  return (
    <div className="shell">
      <header className="shell-header">
        <h1>{APP_TITLE}</h1>
        <AccountMenu user={user} onSignOut={() => void signOut()} />
      </header>
      {loadError !== null && (
        <p role="alert" className="error">
          {loadFailed(loadError)}
        </p>
      )}
      {[createError, deleteError, signOutError].map(
        (error) =>
          error !== null && (
            <p key={error} role="alert" className="error">
              {error}
            </p>
          ),
      )}
      {selected !== null && (
        <main className="shell-main">
          <TabBar active={pane} onChange={setPane} />
          <CheckPage
            key={selected.id}
            checkId={selected.id}
            stale={selected.profile_stale}
            sidebar={list}
            activePane={pane}
            onChecksChanged={refresh}
            onClone={(line) => duplicate(selected.id, line)}
            onOpenCheck={(id) => void openCheck(id)}
          />
        </main>
      )}
      {checks !== null && selected === null && (
        <main className="landing empty-checks">
          <div className="landing-card">
            <p className="landing-pitch">{NO_CHECKS}</p>
            <button type="button" className="primary" onClick={() => void create()}>
              {NEW_CHECK}
            </button>
          </div>
        </main>
      )}
    </div>
  )
}
