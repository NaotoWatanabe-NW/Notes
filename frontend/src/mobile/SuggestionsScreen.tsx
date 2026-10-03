import { useMemo, useState } from 'react'
import type { Book } from '../api'
import { groupBySource, markShelved, matchesKeyword } from '../suggestionSearch'
import { useAllSuggestions } from '../useAllSuggestions'
import { SuggestionRow } from './SuggestionRow'

type Props = {
  books: Book[]
  onOpenBook: (id: number) => void
  /** 積読に追加したあと、本棚の一覧を取り直してもらう */
  onAdded: () => void
  onError: (message: string) => void
}

/**
 * おすすめ（モバイル版）。デザイン外の仮の画面で、見た目はメモ・探すの画面に合わせている。
 * 持っている本ごとに、その本を読み終えたときの候補を並べ、書名と紹介文で絞り込める。
 */
export function SuggestionsScreen({ books, onOpenBook, onAdded, onError }: Props) {
  const [query, setQuery] = useState('')
  const { items, loading, add, dismiss } = useAllSuggestions(true, { onAdded, onError })

  const groups = useMemo(
    () =>
      groupBySource(
        markShelved(items, books).filter((item) => matchesKeyword(item, query)),
      ),
    [items, books, query],
  )
  const total = groups.reduce((sum, group) => sum + group.items.length, 0)

  return (
    <div className="m-screen">
      <div className="m-head">
        <div>
          <span className="m-kicker">{total}件</span>
          <h1 className="m-title">おすすめ</h1>
        </div>
      </div>

      <div className="m-search-head">
        <input
          className="m-search-input"
          type="search"
          placeholder="書名・紹介文で絞り込む"
          aria-label="書名・紹介文で絞り込む"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      {groups.length === 0 ? (
        loading ? null : (
          <p className="m-empty">
            {query.trim()
              ? `「${query.trim()}」を含むおすすめはありません。`
              : 'まだおすすめがありません。'}
          </p>
        )
      ) : (
        groups.map((group) => (
          <section key={group.book.id} className="m-source-group">
            {/* 見出しを押すと、その本の詳細へ */}
            <button
              type="button"
              className="m-source-head"
              onClick={() => onOpenBook(group.book.id)}
            >
              『{group.book.title}』を読み終えたら
              <i className="ph-duotone ph-caret-right" aria-hidden="true" />
            </button>
            {group.items.map((item) => (
              <SuggestionRow
                key={item.id}
                suggestion={item}
                onAdd={() => void add(item)}
                onDismiss={() => void dismiss(item)}
              />
            ))}
          </section>
        ))
      )}
    </div>
  )
}
