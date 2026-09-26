import type { View } from '../types'

type Props = {
  view: View
  onChange: (next: View) => void
  onOpenPalette: () => void
}

const ITEMS: { view: View; label: string; icon: string }[] = [
  { view: 'library', label: '本棚', icon: 'ph-books' },
  { view: 'notes', label: 'メモ', icon: 'ph-quotes' },
  { view: 'review', label: '振り返り', icon: 'ph-chart-line-up' },
]

export function Rail({ view, onChange, onOpenPalette }: Props) {
  return (
    <nav className="rail" aria-label="メインナビゲーション">
      <div className="rail-logo">N</div>
      {ITEMS.map((item) => (
        <button
          key={item.view}
          type="button"
          className="rail-item"
          aria-current={view === item.view ? 'page' : undefined}
          onClick={() => onChange(item.view)}
        >
          <i className={`ph-duotone ${item.icon}`} />
          {item.label}
        </button>
      ))}
      <div className="rail-spacer" />
      {/* 「探す」はビューを切り替えず ⌘K を開く */}
      <button
        type="button"
        className="rail-item"
        title="検索・追加 ⌘K"
        onClick={onOpenPalette}
      >
        <i className="ph-duotone ph-magnifying-glass" />
        探す
      </button>
      <button
        type="button"
        className="rail-item"
        aria-current={view === 'settings' ? 'page' : undefined}
        onClick={() => onChange('settings')}
      >
        <i className="ph-duotone ph-gear" />
        設定
      </button>
    </nav>
  )
}
