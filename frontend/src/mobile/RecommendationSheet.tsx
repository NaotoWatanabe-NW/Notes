import type { Book, Recommendation } from '../api'
import { GENRE_LABELS } from '../api'
import { Cover } from '../components/Cover'
import { fromBooks, metaLine, sourceLabel } from '../recommendations'
import { Sheet } from './Sheet'

type Props = {
  item: Recommendation
  addedBookId: number | undefined
  onAdd: () => void
  onDismiss: () => void
  /** 積読に足した本・元の本を開く（7b へ） */
  onOpenBook: (id: number) => void
  onClose: () => void
  /** 本棚の本（「本棚のこの本から」を出すため） */
  books: Book[]
}

/** 7i おすすめの詳細。行を押すと下から出る（高さ 76%） */
export function RecommendationSheet({
  item,
  addedBookId,
  onAdd,
  onDismiss,
  onOpenBook,
  onClose,
  books,
}: Props) {
  const from = fromBooks(item, books)
  const labelled = item.sources.length > 1
  return (
    <Sheet size="mid" dim="strong" onClose={onClose}>
      <div className="m-sheet-body m-rec-sheet">
        <div className="m-rec-sheet-head">
          <Cover title={item.title} author={item.author} src={item.cover_url} size="sheet" />
          <div className="m-rec-sheet-main">
            <span className="tag tag-neutral">{GENRE_LABELS[item.genre]}</span>
            <span className="m-rec-sheet-title">{item.title}</span>
            <span className="m-rec-sheet-meta">{metaLine(item)}</span>
          </div>
        </div>

        <div className="rec-reasons">
          <span className="rec-reason-label">おすすめの理由</span>
          {item.sources.map((source, index) => (
            <div key={index} className="rec-reason">
              {labelled ? <span className="rec-reason-source">{sourceLabel(source)}</span> : null}
              <p className="m-rec-sheet-reason">{source.reason}</p>
            </div>
          ))}
        </div>

        {from.length > 0 ? (
          <div className="m-rec-from">
            <span className="rec-from-label">本棚のこの本から</span>
            {from.map(({ book, via }) => (
              <button
                key={book.id}
                type="button"
                className="m-rec-from-row"
                onClick={() => onOpenBook(book.id)}
              >
                <Cover title={book.title} author={book.author} src={book.cover_url} size="xs" />
                <span className="rec-from-main">
                  <span className="m-rec-from-title">{book.title}</span>
                  <span className="rec-from-via">{via}</span>
                </span>
                <i className="ph-duotone ph-caret-right m-rec-from-go" />
              </button>
            ))}
          </div>
        ) : null}

        {addedBookId === undefined ? (
          <div className="m-rec-sheet-actions">
            <button type="button" className="btn btn-primary" onClick={onAdd}>
              <i className="ph-duotone ph-plus" style={{ fontSize: 17 }} />
              積読に追加
            </button>
            <button type="button" className="btn btn-ghost rec-dismiss" onClick={onDismiss}>
              興味なし
            </button>
          </div>
        ) : (
          <div className="m-rec-sheet-actions">
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
        <span className="m-rec-note">「興味なし」にした本は、このリストに表示しません。</span>
      </div>
    </Sheet>
  )
}
