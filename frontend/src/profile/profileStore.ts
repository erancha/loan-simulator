import { useCallback, useEffect, useRef, useState } from 'react'
import { errorText } from '../api/client.ts'
import { getProfile, updateProfile } from '../api/profile.ts'
import type { ProfileUpdate, ProfileView } from '../api/types.ts'
import { useLatest } from '../latest.ts'

const SAVED_SHOWN_MS = 2000
const CHANGED_SHOWN_MS = 2500

export type ProfileKey = keyof ProfileView['profile']

/** Who asked for a save: the chat's saves flash their fields. */
export type SaveSource = 'panel' | 'chat'

export interface ProfileStore {
  view: ProfileView | null
  loadError: string | null
  /** Fields the chat just filled, flashed for CHANGED_SHOWN_MS. */
  changed: ReadonlySet<ProfileKey>
  open: boolean
  setOpen(open: boolean): void
  /** True for SAVED_SHOWN_MS after each successful save. */
  savedRecently: boolean
  /** Rejects with the ApiException when the server refuses the update. */
  save(update: ProfileUpdate, from: SaveSource): Promise<ProfileView>
}

/** The fields whose stored value differs between two profile views. */
function changedKeys(previous: ProfileView | null, next: ProfileView): ReadonlySet<ProfileKey> {
  const keys = Object.keys(next.profile) as ProfileKey[]
  return new Set(
    keys.filter((key) => previous === null || previous.profile[key] !== next.profile[key]),
  )
}

/**
 * The profile's page state, shared by the profile panel and the chat's question bubble.
 *
 * The profile is shared by all checks, so the store holds only what GET /api/profile and PUT
 * answer, never a profile carried by an event: a check's stream replays the older profiles of its
 * history. It loads on mount, refetches when profileVersion grows past what the shown profile
 * covers, and saves updates; a refetch or save from the chat flashes the fields it filled.
 */
export function useProfileStore(profileVersion: number): ProfileStore {
  const [view, setView] = useState<ProfileView | null>(null)
  // The view as rendered, for diffing a refetch against it outside React's render.
  const shown = useRef<ProfileView | null>(null)
  useEffect(() => {
    shown.current = view
  }, [view])
  const [loadError, setLoadError] = useState<string | null>(null)
  // The fields start folded and only the person unfolds them, so the chat keeps the focus.
  const [open, setOpen] = useState(false)
  // GETs and PUTs share one numbering, so an older answer never replaces a newer one.
  const latest = useLatest()
  // The profileVersion the shown profile reflects; null until the mount GET answers.
  const [covered, setCovered] = useState<number | null>(null)
  const versionNow = useRef(profileVersion)
  const fetching = useRef(false)

  useEffect(() => {
    versionNow.current = profileVersion
  }, [profileVersion])

  const [changed, setChanged] = useState<ReadonlySet<ProfileKey>>(new Set())
  useEffect(() => {
    if (changed.size === 0) return
    const timer = setTimeout(() => setChanged(new Set()), CHANGED_SHOWN_MS)
    return () => clearTimeout(timer)
  }, [changed])

  const markFromChat = useCallback((keys: ReadonlySet<ProfileKey>) => {
    setChanged(keys)
  }, [])

  const load = useCallback(
    (covers: () => number, fromChat: boolean) => {
      const request = latest.begin()
      fetching.current = true
      const settle = () => {
        fetching.current = false
        setCovered(covers())
      }
      getProfile().then(
        (fetched) => {
          if (latest.accept(request)) {
            if (fromChat) markFromChat(changedKeys(shown.current, fetched))
            setView(fetched)
            setLoadError(null)
          }
          settle()
        },
        (error: unknown) => {
          setLoadError(errorText(error))
          settle()
        },
      )
    },
    [latest, markFromChat],
  )

  // The mount GET answers with the current profile, which already reflects every profile.updated
  // the replay delivered while it was in flight; those do not refetch.
  useEffect(() => load(() => versionNow.current, false), [load])

  useEffect(() => {
    if (covered === null || fetching.current || profileVersion <= covered) return
    load(() => profileVersion, true)
  }, [covered, profileVersion, load])

  // A fresh mark per successful save, so each save restarts the saved status's timer.
  const [savedMark, setSavedMark] = useState<symbol | null>(null)
  useEffect(() => {
    if (savedMark === null) return
    const timer = setTimeout(() => setSavedMark(null), SAVED_SHOWN_MS)
    return () => clearTimeout(timer)
  }, [savedMark])

  const save = useCallback(
    async (update: ProfileUpdate, from: SaveSource) => {
      const request = latest.begin()
      const saved = await updateProfile(update)
      if (latest.accept(request)) setView(saved)
      if (from === 'chat') markFromChat(new Set(Object.keys(update) as ProfileKey[]))
      setSavedMark(Symbol())
      return saved
    },
    [latest, markFromChat],
  )

  return {
    view,
    loadError,
    changed,
    open,
    setOpen,
    savedRecently: savedMark !== null,
    save,
  }
}
