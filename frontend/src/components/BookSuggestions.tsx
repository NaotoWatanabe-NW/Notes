import { useBookSuggestions } from '../useBookSuggestions'
import { SuggestionCard } from './SuggestionCard'

type Props = {
  bookId: number
  /** 積読に追加したあと、本棚の一覧を取り直してもらう */
  onAdded: () => void
  onError: (message: string) => void
}

/**
 * 本の詳細に出す「次に読む本」（PC版）。
 *
 * 読了ダイアログと同じ候補を、条件の絞り込みなしで全部並べる。
 * これまで候補は読み終えた瞬間に一度しか見られなかったので、
 * 積読の本でも「読んだら次はこれ」を確かめられるようにする。
 */
export function BookSuggestions({ bookId, onAdded, onError }: Props) {
  const { suggestions, configured, loading, add, dismiss } = useBookSuggestions(
    bookId,
    { onAdded, onError },
  )

  // 最初の読み込み中は何も出さない。「まだ決めていません」が一瞬見えると紛らわしい
  if (loading && !configured) return null

  return (
    <section className="stack" style={{ gap: 16 }}>
      <div className="section-head">
        <h2 className="section-title">
          次に読む本{configured ? ` ${suggestions.length}件` : ''}
        </h2>
        {suggestions.length > 0 ? (
          <span className="section-aside">読み終えたあとの候補</span>
        ) : null}
      </div>

      {!configured ? (
        <p className="muted" style={{ fontSize: 15, margin: 0 }}>
          この本の「次に読む本」はまだ決めていません。
        </p>
      ) : suggestions.length === 0 ? (
        <p className="muted" style={{ fontSize: 15, margin: 0 }}>
          候補は「興味なし」で全部外しました。
        </p>
      ) : (
        <div className="next-cards book-next-cards">
          {suggestions.map((suggestion) => (
            <SuggestionCard
              key={suggestion.id}
              suggestion={suggestion}
              onAdd={() => void add(suggestion)}
              onDismiss={() => void dismiss(suggestion)}
            />
          ))}
        </div>
      )}
    </section>
  )
}
