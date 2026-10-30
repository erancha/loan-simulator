import { TABS, TABS_LABEL } from './copy.ts'

export type Pane = (typeof TABS)[number]['pane']

interface Props {
  active: Pane
  onChange: (pane: Pane) => void
}

/** The phone-width switch between the check page's panes; hidden by CSS on wide screens. */
export function TabBar({ active, onChange }: Props) {
  return (
    <div className="tab-bar" role="tablist" aria-label={TABS_LABEL}>
      {TABS.map(({ pane, label }) => (
        <button
          key={pane}
          type="button"
          role="tab"
          aria-selected={pane === active}
          onClick={() => onChange(pane)}
        >
          {label}
        </button>
      ))}
    </div>
  )
}
