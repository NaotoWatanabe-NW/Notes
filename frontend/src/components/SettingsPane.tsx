export type SettingsSection = 'goal' | 'display' | 'data' | 'account'

const SECTIONS: { key: SettingsSection; label: string; icon: string }[] = [
  { key: 'goal', label: '読書目標', icon: 'ph-target' },
  { key: 'display', label: '表示', icon: 'ph-eye' },
  { key: 'data', label: 'データ', icon: 'ph-export' },
  { key: 'account', label: 'アカウント', icon: 'ph-user-circle' },
]

type Props = {
  selected: SettingsSection
  onSelect: (next: SettingsSection) => void
}

export function SettingsPane({ selected, onSelect }: Props) {
  return (
    <>
      <div className="list-head">
        <span className="list-title">設定</span>
      </div>
      <div className="rows">
        {SECTIONS.map((section) => (
          <button
            key={section.key}
            type="button"
            className="row row-settings"
            aria-current={section.key === selected}
            onClick={() => onSelect(section.key)}
          >
            <i className={`ph-duotone ${section.icon}`} />
            {section.label}
          </button>
        ))}
      </div>
    </>
  )
}
