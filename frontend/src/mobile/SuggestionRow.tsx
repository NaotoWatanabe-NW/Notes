import type { Suggestion } from '../api'
import { BASIS_LABELS } from '../api'
import { Cover } from '../components/Cover'

type Props = {
  suggestion: Suggestion
  onAdd: () => void
  onDismiss: () => void
}

/**
 * 候補1冊（モバイル版は横並びの1列）。
 * 読了シート #7g と本の詳細で同じものを使う。
 */
export function SuggestionRow({ suggestion, onAdd, onDismiss }: Props) {
  const isAdded = suggestion.added_book_id !== null
  return (
    <article className="m-next-card">
      <Cover
        title={suggestion.title}
        author={suggestion.author}
        src={suggestion.cover_url}
      />
      <div className="m-next-main">
        <span className="m-next-title">{suggestion.title}</span>
        <span className="m-next-sub">
          {suggestion.author ?? '著者不明'} ·{' '}
          <span
            className={suggestion.basis === 'note' ? 'kind-quote' : 'writing-kicker'}
          >
            {BASIS_LABELS[suggestion.basis]}
          </span>
        </span>
        <span className="m-next-reason">{suggestion.reason}</span>
        <div className="m-next-actions">
          {isAdded ? (
            <span className="tag tag-accent">✓ 積読に追加しました</span>
          ) : (
            <>
              <button type="button" className="btn btn-secondary" onClick={onAdd}>
                積読に追加
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                style={{ color: 'var(--color-neutral-700)' }}
                onClick={onDismiss}
              >
                興味なし
              </button>
            </>
          )}
        </div>
      </div>
    </article>
  )
}
