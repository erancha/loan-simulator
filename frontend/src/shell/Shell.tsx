import { useCallback, useEffect, useState } from 'react'
import { createCheck, deleteCheck, listChecks } from '../api/checks.ts'
import { ApiException, errorText } from '../api/client.ts'
import type { CheckSummary, User } from '../api/types.ts'
import { CheckPage } from '../check/CheckPage.tsx'
import { AccountMenu } from './AccountMenu.tsx'
import { ChecksList } from './ChecksList.tsx'
import { APP_TITLE } from '../copy.ts'
import { useLatest } from '../latest.ts'
import {
  DELETE_WHILE_ANSWERING,
  NEW_CHECK,
  NO_CHECKS,
  createFailed,
  deleteFailed,
  loadFailed,
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

  const latest = useLatest()
  const refresh = useCallback(() => {
    const request = latest.begin()
    return listChecks().then(
      (fetched) => {
        if (!latest.accept(request)) return
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

  function select(id: string) {
    setWantedId(id)
    setCreateError(null)
    setPane('chat')
  }

  async function create() {
    try {
      const { id } = await createCheck()
      await refresh()
      select(id)
    } catch (error) {
      setCreateError(createFailed(errorText(error)))
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
        onSelect={select}
        onCreate={() => void create()}
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
