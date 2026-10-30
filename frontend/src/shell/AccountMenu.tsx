import { useEffect, useRef, useState } from 'react'
import type { User } from '../api/types.ts'
import { ACCOUNT_HINT, MENU_LABEL, SIGN_OUT, SIGN_OUT_HINT } from './copy.ts'
import { Icon } from './Icon.tsx'

interface Props {
  user: User
  onSignOut: () => void
}

/**
 * The header's account menu: a button that drops a floating card naming the signed-in account,
 * with sign-out as its item. A press outside the menu or Escape closes it.
 */
export function AccountMenu({ user, onSignOut }: Props) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const dismiss = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false)
    }
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', dismiss)
    document.addEventListener('keydown', onEscape)
    return () => {
      document.removeEventListener('mousedown', dismiss)
      document.removeEventListener('keydown', onEscape)
    }
  }, [open])

  return (
    <span className="account" ref={box}>
      <button
        type="button"
        className="account-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={MENU_LABEL}
        onClick={() => setOpen((current) => !current)}
      >
        <Icon name={open ? 'close' : 'menu'} />
      </button>
      {open && (
        <span className="account-menu">
          <span className="account-name" title={ACCOUNT_HINT}>
            {user.name ?? user.email ?? user.id}
            {user.name !== null && user.email !== null && (
              <span className="account-email">{user.email}</span>
            )}
          </span>
          <span role="menu">
            <button
              type="button"
              role="menuitem"
              className="menu-item"
              title={SIGN_OUT_HINT}
              onClick={() => {
                setOpen(false)
                onSignOut()
              }}
            >
              <Icon name="signOut" />
              {SIGN_OUT}
            </button>
          </span>
        </span>
      )}
    </span>
  )
}
