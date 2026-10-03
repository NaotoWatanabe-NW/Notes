import type { View } from '../types'

type Props = {
  view: View
  onChange: (next: View) => void
  onOpenPalette: () => void
  /** 一覧ペインを隠しているか */
  sidebarHidden: boolean
  onToggleSidebar: () => void
}

const ITEMS: { view: View; label: string; icon: string }[] = [
  { view: 'library', label: '本棚', icon: 'ph-books' },
  { view: 'notes', label: 'メモ', icon: 'ph-quotes' },
  { view: 'review', label: '振り返り', icon: 'ph-chart-line-up' },
  // デザインのレールには無い項目（仮置き）。デザインが届いたら位置と見た目を合わせる
  { view: 'suggestions', label: 'おすすめ', icon: 'ph-lightbulb' },
]

export function Rail({
  view,
  onChange,
  onOpenPalette,
  sidebarHidden,
  onToggleSidebar,
}: Props) {
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
      {/* 一覧ペインの開閉。詳細を広く使いたいときに畳む（⌘B / Ctrl+B） */}
      <button
        type="button"
        className="rail-item"
        aria-pressed={sidebarHidden}
        title={`一覧を${sidebarHidden ? '出す' : '隠す'} ⌘B`}
        onClick={onToggleSidebar}
      >
        <i className="ph-duotone ph-sidebar-simple" />
        {sidebarHidden ? '出す' : '隠す'}
      </button>
    </nav>
  )
}
