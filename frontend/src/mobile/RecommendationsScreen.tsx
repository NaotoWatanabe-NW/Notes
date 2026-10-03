import type { Genre, Recommendation } from '../api'
import { Cover } from '../components/Cover'
import { GenreFilterChips, GenreTag } from '../components/GenreChips'

type Props = {
  items: Recommendation[]
  /** この画面で積読に足した本（ISBN → 本の id） */
  added: Map<string, number>
  genre: Genre | null
  onGenre: (next: Genre | null) => void
  loading: boolean
  onBack: () => void
  /** 行を押したとき（7i のシートを開く） */
  onOpen: (isbn: string) => void
  onAdd: (item: Recommendation) => void
}

/** 7h おすすめ一覧。本棚の「すべて見る」から開く。カテゴリで絞り、＋で積読に追加 */
export function RecommendationsScreen({
  items,
  added,
  genre,
  onGenre,
  loading,
  onBack,
  onOpen,
  onAdd,
}: Props) {
  const visible = items.filter((item) => genre === null || item.genre === genre)
  const count = items.filter((item) => !added.has(item.isbn)).length

  return (
    <div className="m-screen m-screen-flush">
      <div className="m-nav">
        <button type="button" className="m-back" onClick={onBack}>
          <i className="ph-duotone ph-caret-left" />
          本棚
        </button>
      </div>
      <div className="m-rec-head">
        <span className="m-kicker">本棚にない本 · {count}冊</span>
        <h1 className="m-title">おすすめ</h1>
      </div>

      <div className="m-bleed" style={{ marginBottom: 18 }}>
        <GenreFilterChips value={genre} onChange={onGenre} scroll />
      </div>

      {visible.length === 0 ? (
        <p className="m-empty">
          {loading ? '読み込み中…' : 'このカテゴリのおすすめはありません。'}
        </p>
      ) : (
        <div className="m-rec-list">
          {visible.map((item) => (
            <div key={item.isbn} className="m-rec-row">
              <button type="button" className="m-rec-open" onClick={() => onOpen(item.isbn)}>
                <Cover title={item.title} author={item.author} src={item.cover_url} size="row" />
                <span className="m-rec-main">
                  <span className="m-rec-title">{item.title}</span>
                  <span className="row-cats">
                    <GenreTag genre={item.genre} />
                    {item.author ? <span>{item.author}</span> : null}
                  </span>
                  <span className="m-rec-reason">{item.sources[0]?.reason}</span>
                </span>
              </button>
              {added.has(item.isbn) ? (
                <span className="m-rec-done" aria-label="積読に追加済み">
                  <i className="ph-duotone ph-check" />
                </span>
              ) : (
                <button
                  type="button"
                  className="btn btn-icon btn-secondary m-rec-add"
                  aria-label={`「${item.title}」を積読に追加`}
                  onClick={() => onAdd(item)}
                >
                  <i className="ph-duotone ph-plus" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
