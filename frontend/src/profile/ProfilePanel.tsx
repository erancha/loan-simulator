import { Fragment } from 'react'
import type { ProfileUpdate } from '../api/types.ts'
import { formatShekels } from '../money.ts'
import { MoneyField } from './MoneyField.tsx'
import {
  LOADING_PROFILE,
  MONEY_FIELDS,
  NOT_COUNTED_YET,
  CLOSE_PROFILE,
  OPEN_PROFILE,
  PROFILE_NOTE,
  PROFILE_TITLE,
  SAVED,
  loadFailed,
  rowTooltip,
} from './copy.ts'
import type { ProfileStore } from './profileStore.ts'

/** The field's classes: a dashed outline while missing, a flash while the chat just filled it. */
export function fieldClass(missing: boolean, changed: boolean): string {
  return ['field', missing && 'missing', changed && 'changed'].filter(Boolean).join(' ')
}

/** The summary value's color: dark red while the agent still needs it, dark green once given. */
function summaryClass(amount: string | null, missing: boolean): string | undefined {
  if (missing) return 'value-missing'
  return amount === null ? undefined : 'value-set'
}

/** A field's amount for the closed panel's summary; an unset field says so. */
function amountText(amount: string | null): string {
  return amount === null ? NOT_COUNTED_YET : formatShekels(amount)
}

interface Props {
  store: ProfileStore
  onSaved: (update: ProfileUpdate) => void
}

/** What the agent understood about the person's finances, with inline correction of each figure. */
export function ProfilePanel({ store, onSaved }: Props) {
  const { view, loadError, changed, open } = store

  async function save(update: ProfileUpdate) {
    await store.save(update, 'panel')
    onSaved(update)
  }

  if (loadError !== null) {
    return <p role="alert">{loadFailed(loadError)}</p>
  }
  if (view === null) return <p>{LOADING_PROFILE}</p>

  return (
    <section className="profile-panel">
      <h2 className="panel-title">
        <button
          type="button"
          className="panel-toggle"
          aria-expanded={open}
          aria-controls="profile-fields"
          aria-label={open ? CLOSE_PROFILE : OPEN_PROFILE}
          onClick={() => store.setOpen(!open)}
        >
          {PROFILE_TITLE}
          <span className="toggle-mark" aria-hidden="true">
            {open ? '▴' : '▾'}
          </span>
        </button>
      </h2>
      <p className="saved-status" role="status">
        {store.savedRecently && SAVED}
      </p>
      {!open && (
        <dl className="profile-summary">
          {MONEY_FIELDS.map((field) => (
            <Fragment key={field.key}>
              <dt title={rowTooltip(field)}>{field.label}</dt>
              <dd
                title={rowTooltip(field)}
                className={summaryClass(view.profile[field.key], view.missing.includes(field.key))}
              >
                {amountText(view.profile[field.key])}
              </dd>
            </Fragment>
          ))}
        </dl>
      )}
      <div id="profile-fields" hidden={!open}>
        <p className="panel-note">{PROFILE_NOTE}</p>
        {MONEY_FIELDS.map(({ key, label, title, hint }) => (
          <Fragment key={key}>
            <MoneyField
              id={`profile-${key}`}
              label={label}
              title={title}
              hint={hint}
              value={view.profile[key]}
              missing={view.missing.includes(key)}
              changed={changed.has(key)}
              onCommit={(amount) => save({ [key]: amount })}
            />
          </Fragment>
        ))}
      </div>
    </section>
  )
}
