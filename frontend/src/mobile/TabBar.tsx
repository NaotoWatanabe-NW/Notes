export type MobileTab = 'library' | 'notes' | 'review' | 'suggestions' | 'search'

const TABS: { key: MobileTab; label: string; icon: string }[] = [
  { key: 'library', label: '本棚', icon: 'ph-books' },
  { key: 'notes', label: 'メモ', icon: 'ph-quotes' },
  { key: 'review', label: '振り返り', icon: 'ph-chart-line-up' },
  // デザインのタブバーは4つ。5つ目は仮置きで、デザインが届いたら合わせる
  { key: 'suggestions', label: 'おすすめ', icon: 'ph-lightbulb' },
  { key: 'search', label: '探す', icon: 'ph-magnifying-glass' },
]

/** 下部のタブバー（デザイン #7a〜7e 共通。「おすすめ」だけデザイン外） */
export function TabBar({
  tab,
  onChange,
}: {
  tab: MobileTab
  onChange: (next: MobileTab) => void
}) {
  return (
    <nav className="m-tabs" aria-label="メインナビゲーション">
      {TABS.map((item) => (
        <button
          key={item.key}
          type="button"
          className="m-tab"
          aria-current={tab === item.key ? 'page' : undefined}
          onClick={() => onChange(item.key)}
        >
          <i className={`ph-duotone ${item.icon}`} />
          {item.label}
        </button>
      ))}
    </nav>
  )
}
