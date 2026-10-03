import { useBookSuggestions } from '../useBookSuggestions'
import { SuggestionRow } from './SuggestionRow'

type Props = {
  bookId: number
  /** 積読に追加したあと、本棚の一覧を取り直してもらう */
  onAdded: () => void
  onError: (message: string) => void
}

/**
 * 本の詳細（#7b）に出す「次に読む本」。
 * 読了シートと同じ候補を、条件の絞り込みなしで全部並べる。
 */
export function BookSuggestions({ bookId, onAdded, onError }: Props) {
  const { suggestions, configured, loading, add, dismiss } = useBookSuggestions(
    bookId,
    { onAdded, onError },
  )

  // 最初の読み込み中は何も出さない。「まだ決めていません」が一瞬見えると紛らわしい
  if (loading && !configured) return null

  return (
    <section style={{ marginTop: 26 }}>
      <div className="section-head" style={{ marginBottom: 12 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>
          次に読む本{configured ? ` ${suggestions.length}件` : ''}
        </h2>
        {suggestions.length > 0 ? (
          <span className="section-aside">読み終えたあとの候補</span>
        ) : null}
      </div>

      {!configured ? (
        <p className="m-empty">この本の「次に読む本」はまだ決めていません。</p>
      ) : suggestions.length === 0 ? (
        <p className="m-empty">候補は「興味なし」で全部外しました。</p>
      ) : (
        suggestions.map((suggestion) => (
          <SuggestionRow
            key={suggestion.id}
            suggestion={suggestion}
            onAdd={() => void add(suggestion)}
            onDismiss={() => void dismiss(suggestion)}
          />
        ))
      )}
    </section>
  )
}
