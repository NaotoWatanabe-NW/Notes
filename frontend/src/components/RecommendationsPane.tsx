import type { Genre, Recommendation } from '../api'
import { GENRE_LABELS } from '../api'
import { Cover } from './Cover'
import { GenreFilterChips } from './GenreChips'

type Props = {
  items: Recommendation[]
  /** この画面で積読に足した本（ISBN → 本の id） */
  added: Map<string, number>
  genre: Genre | null
  onGenre: (next: Genre | null) => void
  selectedIsbn: string | null
  onSelect: (isbn: string) => void
  loading: boolean
}

/** おすすめの一覧ペイン（デザイン J）。本棚に無い本を1列に並べ、カテゴリで絞る */
export function RecommendationsPane({
  items,
  added,
  genre,
  onGenre,
  selectedIsbn,
  onSelect,
  loading,
}: Props) {
  const visible = items.filter((item) => genre === null || item.genre === genre)
  const count = visible.filter((item) => !added.has(item.isbn)).length

  return (
    <>
      <div className="list-head">
        <span className="list-title">おすすめ</span>
        <span className="list-aside">{count}冊</span>
      </div>
      <p className="rec-pane-desc">Notes が選んだ本のリストです。本棚にある本は表示しません。</p>

      <GenreFilterChips value={genre} onChange={onGenre} />

      {visible.length === 0 ? (
        <p className="rec-empty">
          {loading ? '読み込み中…' : 'このカテゴリのおすすめはありません。'}
        </p>
      ) : (
        <div className="rows">
          {visible.map((item) => {
            const isAdded = added.has(item.isbn)
            return (
              <button
                key={item.isbn}
                type="button"
                className="row"
                aria-current={item.isbn === selectedIsbn}
                onClick={() => onSelect(item.isbn)}
              >
                <Cover title={item.title} author={item.author} src={item.cover_url} />
                <span className="row-main">
                  <span className="row-title">{item.title}</span>
                  <span className={isAdded ? 'row-meta rec-added' : 'row-meta'}>
                    {isAdded
                      ? '積読に追加済み'
                      : [item.author, GENRE_LABELS[item.genre]].filter(Boolean).join(' · ')}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      )}
    </>
  )
}
