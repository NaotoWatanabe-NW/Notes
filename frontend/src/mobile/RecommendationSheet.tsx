import type { Recommendation } from '../api'
import { GENRE_LABELS } from '../api'
import { Cover } from '../components/Cover'
import { metaLine, sourceLabel } from '../recommendations'
import { Sheet } from './Sheet'

type Props = {
  item: Recommendation
  addedBookId: number | undefined
  onAdd: () => void
  onDismiss: () => void
  onOpenBook: (id: number) => void
  onClose: () => void
}

/** 7i おすすめの詳細。行を押すと下から出る（高さ 64%） */
export function RecommendationSheet({
  item,
  addedBookId,
  onAdd,
  onDismiss,
  onOpenBook,
  onClose,
}: Props) {
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
              <span className="rec-reason-source">{sourceLabel(source)}</span>
              <p className="m-rec-sheet-reason">{source.reason}</p>
            </div>
          ))}
        </div>

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
