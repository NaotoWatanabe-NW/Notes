import type { SuggestionWithBook } from '../api'
import type { SourceGroup } from '../suggestionSearch'
import { SuggestionCard } from './SuggestionCard'

type Props = {
  /** 出すまとまり。「すべての本から」なら全部、本を選んでいればその1冊ぶん */
  groups: SourceGroup[]
  query: string
  loading: boolean
  onOpenBook: (id: number) => void
  onAdd: (item: SuggestionWithBook) => void
  onDismiss: (item: SuggestionWithBook) => void
}

/**
 * おすすめの詳細（PC版）。持っている本ごとに、その本を読み終えたときの候補を並べる。
 * カードは読了ダイアログ・本の詳細と同じ `SuggestionCard`。
 */
export function SuggestionsView({
  groups,
  query,
  loading,
  onOpenBook,
  onAdd,
  onDismiss,
}: Props) {
  if (groups.length === 0) {
    if (loading) return <p className="detail-empty">読み込み中…</p>
    return (
      <p className="detail-empty">
        {query.trim()
          ? `「${query.trim()}」を含むおすすめはありません。書名と紹介文から探しています。`
          : 'まだおすすめがありません。'}
      </p>
    )
  }

  return (
    <div className="detail">
      {groups.map((group) => (
        <section key={group.book.id} className="stack suggestion-group">
          <div className="section-head">
            <h2 className="section-title">『{group.book.title}』を読み終えたら</h2>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => onOpenBook(group.book.id)}
            >
              この本を開く
            </button>
          </div>
          <div className="next-cards book-next-cards">
            {group.items.map((item) => (
              <SuggestionCard
                key={item.id}
                suggestion={item}
                onAdd={() => onAdd(item)}
                onDismiss={() => onDismiss(item)}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
