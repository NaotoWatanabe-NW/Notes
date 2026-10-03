import type { Recommendation } from '../api'
import { GENRE_LABELS } from '../api'
import { metaLine, sourceLabel } from '../recommendations'
import { Cover } from './Cover'

type Props = {
  item: Recommendation | null
  /** 積読に足したなら、その本の id */
  addedBookId: number | undefined
  onAdd: () => void
  onDismiss: () => void
  onOpenBook: (id: number) => void
}

/** おすすめの詳細ペイン（デザイン J） */
export function RecommendationView({ item, addedBookId, onAdd, onDismiss, onOpenBook }: Props) {
  if (!item) return <p className="detail-empty">表示できるおすすめはありません。</p>

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

      {/* 何冊もの本から選ばれた本は、理由も選ばれた元ごとに並べる */}
      <section className="rec-reasons">
        <span className="rec-reason-label">おすすめの理由</span>
        {item.sources.map((source, index) => (
          <div key={index} className="rec-reason">
            <span className="rec-reason-source">{sourceLabel(source)}</span>
            <p className="rec-reason-text">{source.reason}</p>
          </div>
        ))}
      </section>

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
