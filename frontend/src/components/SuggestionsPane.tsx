import type { SourceGroup } from '../suggestionSearch'

type Props = {
  /** キーワードで絞り込んだあとの、本ごとのまとまり */
  groups: SourceGroup[]
  /** 絞り込んだあとの候補の数 */
  total: number
  query: string
  onQuery: (next: string) => void
  /** 選んでいる本。null は「すべての本から」 */
  selectedId: number | null
  onSelect: (id: number | null) => void
  loading: boolean
}

/**
 * おすすめの一覧ペイン（PC版）。キーワード欄と、おすすめを持つ本の一覧。
 * デザインには無い画面なので、見た目は本棚・振り返りの一覧に合わせた仮のもの。
 */
export function SuggestionsPane({
  groups,
  total,
  query,
  onQuery,
  selectedId,
  onSelect,
  loading,
}: Props) {
  return (
    <>
      <div className="list-head">
        <span className="list-title">おすすめ</span>
        <span className="list-aside">{total}件</span>
      </div>

      <input
        type="search"
        className="input"
        placeholder="書名・紹介文で絞り込む"
        aria-label="書名・紹介文で絞り込む"
        value={query}
        onChange={(event) => onQuery(event.target.value)}
      />

      {groups.length === 0 ? (
        loading ? null : (
          <p className="list-aside" style={{ padding: '0 8px' }}>
            {query.trim()
              ? `「${query.trim()}」を含むおすすめはありません。`
              : 'まだおすすめがありません。'}
          </p>
        )
      ) : (
        <div className="rows">
          <button
            type="button"
            className="row row-source"
            aria-current={selectedId === null}
            onClick={() => onSelect(null)}
          >
            <span className="row-main">
              <span className="row-title">すべての本から</span>
            </span>
            <span className="row-count">{total}件</span>
          </button>
          {groups.map((group) => (
            <button
              key={group.book.id}
              type="button"
              className="row row-source"
              aria-current={group.book.id === selectedId}
              onClick={() => onSelect(group.book.id)}
            >
              <span className="row-main">
                <span className="row-title">{group.book.title}</span>
                {group.book.author ? (
                  <span className="row-meta">{group.book.author}</span>
                ) : null}
              </span>
              <span className="row-count">{group.items.length}件</span>
            </button>
          ))}
        </div>
      )}
    </>
  )
}
