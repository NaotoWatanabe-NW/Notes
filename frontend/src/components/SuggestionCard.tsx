import type { Suggestion } from '../api'
import { BASIS_LABELS, DISTANCE_LABELS } from '../api'
import { Cover } from './Cover'

type Props = {
  suggestion: Suggestion
  onAdd: () => void
  onDismiss: () => void
}

/**
 * 候補1冊のカード（PC版）。読了ダイアログ #5a と本の詳細で同じものを使う。
 * 表紙・書名・著者・**理由は一言**・根拠ラベルの並びはデザインの指定。
 */
export function SuggestionCard({ suggestion, onAdd, onDismiss }: Props) {
  const isAdded = suggestion.added_book_id !== null
  return (
    <article className="next-card">
      <Cover
        title={suggestion.title}
        author={suggestion.author}
        src={suggestion.cover_url}
        size="md"
      />
      <span className="next-card-title">{suggestion.title}</span>
      <span className="next-card-author">{suggestion.author ?? '著者不明'}</span>
      <span className="next-card-reason">{suggestion.reason}</span>
      {/* 引用・メモ由来はマゼンタ、それ以外はシアン（デザインの指定） */}
      <span
        className={`next-card-basis ${
          suggestion.basis === 'note' ? 'kind-quote' : 'writing-kicker'
        }`}
      >
        {BASIS_LABELS[suggestion.basis]} · {DISTANCE_LABELS[suggestion.distance]}
      </span>

      <div className="next-card-actions">
        {isAdded ? (
          <span className="tag tag-accent">✓ 積読に追加しました</span>
        ) : (
          <>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: 12 }}
              onClick={onAdd}
            >
              積読に追加
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              style={{ fontSize: 12, color: 'var(--color-neutral-700)' }}
              onClick={onDismiss}
            >
              興味なし
            </button>
          </>
        )}
      </div>
    </article>
  )
}
