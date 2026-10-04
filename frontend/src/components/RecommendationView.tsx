import type { Book, Recommendation } from '../api'
import { GENRE_LABELS } from '../api'
import { fromBooks, metaLine, sourceLabel } from '../recommendations'
import { Cover } from './Cover'

type Props = {
  item: Recommendation | null
  /** 積読に足したなら、その本の id */
  addedBookId: number | undefined
  onAdd: () => void
  onDismiss: () => void
  onOpenBook: (id: number) => void
  /** 本棚の本（「本棚のこの本から」を出すため） */
  books: Book[]
  /** 元の本を開く（絞り込みは解除する） */
  onOpenSource: (id: number) => void
}

/** おすすめの詳細ペイン（デザイン J） */
export function RecommendationView({
  item,
  addedBookId,
  onAdd,
  onDismiss,
  onOpenBook,
  books,
  onOpenSource,
}: Props) {
  if (!item) return <p className="detail-empty">表示できるおすすめはありません。</p>
  const from = fromBooks(item, books)
  // 理由が1つならデザインどおり理由だけ。何冊もの本から選ばれたときは、どの理由がどこからかを添える
  const labelled = item.sources.length > 1

  return (
    <div className="detail rec-detail">
      <header className="rec-detail-head">
        <Cover title={item.title} author={item.author} src={item.cover_url} size="lg" />
        <div className="rec-detail-main">
          <span className="tag tag-neutral">{GENRE_LABELS[item.genre]}</span>
          <h1 className="rec-detail-title">{item.title}</h1>
          <p className="rec-detail-meta">{metaLine(item)}</p>
        </div>
      </header>

      <section className="rec-reasons">
        <span className="rec-reason-label">おすすめの理由</span>
        {item.sources.map((source, index) => (
          <div key={index} className="rec-reason">
            {labelled ? <span className="rec-reason-source">{sourceLabel(source)}</span> : null}
            <p className="rec-reason-text">{source.reason}</p>
          </div>
        ))}
      </section>

      {/* 元になった本棚の本へのリンク。派生でないおすすめには出さない */}
      {from.length > 0 ? (
        <section className="rec-from">
          <span className="rec-from-label">本棚のこの本から</span>
          {from.map(({ book, via }) => (
            <button
              key={book.id}
              type="button"
              className="rec-from-row"
              onClick={() => onOpenSource(book.id)}
            >
              <Cover title={book.title} author={book.author} src={book.cover_url} size="xs" />
              <span className="rec-from-main">
                <span className="rec-from-title">{book.title}</span>
                <span className="rec-from-via">{via}</span>
              </span>
              <span className="rec-from-go">
                本を開く
                <i className="ph-duotone ph-arrow-right" />
              </span>
            </button>
          ))}
        </section>
      ) : null}

      {addedBookId === undefined ? (
        <div className="rec-actions">
          <button type="button" className="btn btn-primary" onClick={onAdd}>
            <i className="ph-duotone ph-plus" style={{ fontSize: 17 }} />
            積読に追加
          </button>
          <button type="button" className="btn btn-ghost rec-dismiss" onClick={onDismiss}>
            興味なし
          </button>
        </div>
      ) : (
        <div className="rec-actions">
          <span className="tag tag-accent rec-added-tag">
            <i className="ph-duotone ph-check" />
            積読に追加しました
          </span>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => onOpenBook(addedBookId)}
          >
            本棚で開く
          </button>
        </div>
      )}
      <p className="rec-note">「興味なし」にした本は、このリストに表示しません。</p>
    </div>
  )
}
