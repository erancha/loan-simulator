import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { ProfileView } from '../api/types.ts'
import { profileView } from '../test/fixtures.ts'
import { useProfileStore } from './profileStore.ts'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status })
}

/** GET answers the fixture; a PUT answers the fixture with the sent fields applied. */
function stubProfile() {
  vi.stubGlobal(
    'fetch',
    vi.fn((_path: string, init?: RequestInit) => {
      if (init?.method !== 'PUT') return Promise.resolve(jsonResponse(200, profileView))
      const update = JSON.parse(String(init.body)) as Partial<ProfileView['profile']>
      const saved = { ...profileView, profile: { ...profileView.profile, ...update } }
      return Promise.resolve(jsonResponse(200, saved))
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

it('a chat save marks the field and leaves the panel folded; a panel save does not', async () => {
  stubProfile()
  const { result } = renderHook(() => useProfileStore(0))
  await waitFor(() => expect(result.current.view).not.toBeNull())
  await act(() => result.current.save({ savings: '12000' }, 'chat'))
  expect(result.current.open).toBe(false)
  expect(result.current.changed.has('savings')).toBe(true)
  await act(() => result.current.save({ fixed_expenses: '3000' }, 'panel'))
  expect(result.current.changed.has('fixed_expenses')).toBe(false)
})

it('a refused save rejects with the server reason and keeps the view', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn((_path: string, init?: RequestInit) =>
      Promise.resolve(
        init?.method === 'PUT'
          ? jsonResponse(422, { detail: 'savings is too large' })
          : jsonResponse(200, profileView),
      ),
    ),
  )
  const { result } = renderHook(() => useProfileStore(0))
  await waitFor(() => expect(result.current.view).not.toBeNull())
  await expect(
    act(() => result.current.save({ savings: '99' }, 'chat')),
  ).rejects.toMatchObject({ status: 422 })
  expect(result.current.view).toEqual(profileView)
  expect(result.current.savedRecently).toBe(false)
})
