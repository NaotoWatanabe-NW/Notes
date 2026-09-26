import { useCallback, useEffect, useState } from 'react'
import type { Basis, Distance, Suggestion, SuggestionSet } from '../api'
import {
  addSuggestionToShelf,
  ApiError,
  BASIS_LABELS,
  dismissSuggestion,
  DISTANCE_LABELS,
  getSuggestions,
} from '../api'
import { Cover } from './Cover'
import { Segmented } from './Segmented'
import { Stars } from './Stars'

type Props = {
  bookId: number
  /** 読み終えた本の評価。ここでそのまま付けられる（デザインの指定） */
  rating: number | null
  onRate: (rating: number | null) => void
  /** 積読に追加したあと、一覧を取り直してもらう */
  onAdded: () => void
  onWriteReport: () => void
  onClose: () => void
  onError: (message: string) => void
}

const ALL_BASIS: Basis[] = ['note', 'rating', 'tag']
const BASIS_ICONS: Record<Basis, string> = {
  note: 'ph-quotes',
  rating: 'ph-star',
  tag: 'ph-tag',
}

/**
 * 読み終えた瞬間に一度だけ出る「次に読む本」（デザイン #5a）。
 * 候補をどう選ぶかはサーバー側（suggest.py）の担当で、ここは出し方だけ。
 */
export function NextBookDialog({
  bookId,
  rating,
  onRate,
  onAdded,
  onWriteReport,
  onClose,
  onError,
}: Props) {
  const [basis, setBasis] = useState<Basis[]>(ALL_BASIS)
  const [distance, setDistance] = useState<Distance>('both')
  const [page, setPage] = useState(0)
  const [data, setData] = useState<SuggestionSet | null>(null)
  const [loading, setLoading] = useState(true)
  // 興味なしにした候補を覚えて、その場で消す。
  // 追加済みかどうかはサーバーが覚えている（added_book_id）
  const [dismissed, setDismissed] = useState<number[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await getSuggestions(bookId, { basis, distance, page }))
    } catch (e) {
      onError(e instanceof ApiError ? e.message : 'おすすめを取得できませんでした')
    } finally {
      setLoading(false)
    }
  }, [bookId, basis, distance, page, onError])

  useEffect(() => {
    void load()
  }, [load])

  // 条件を変えたら先頭のページに戻る（デザインの指定）
  function changeBasis(key: Basis) {
    const next = basis.includes(key)
      ? basis.filter((b) => b !== key)
      : [...basis, key]
    // 最低1つは ON のままにする
    if (next.length === 0) return
    setBasis(next)
    setPage(0)
  }

  async function add(suggestion: Suggestion) {
    try {
      await addSuggestionToShelf(suggestion.id)
      onAdded()
      // 追加済みの印はサーバーが持つので、取り直して反映する
      await load()
    } catch (e) {
      onError(e instanceof ApiError ? e.message : '積読に追加できませんでした')
    }
  }

  async function dismiss(suggestion: Suggestion) {
    setDismissed((prev) => [...prev, suggestion.id])
    if (suggestion.isbn) {
      try {
        await dismissSuggestion(suggestion.isbn)
      } catch {
        // 記録に失敗しても、この場で消えていれば用は足りる
      }
    }
    // 消したぶんを埋めるため、次の候補を取りに行く
    setPage((prev) => prev + 1)
  }

  const visible = (data?.suggestions ?? []).filter(
    (s) => !dismissed.includes(s.id),
  )

  return (
    <div
      className="next-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="next" role="dialog" aria-label="次に読む本">
        {/* ── ヘッダー ── */}
        <header className="next-head">
          <div>
            <span className="next-kicker">
              読了
              {data?.days ? ` · ${data.days}日間` : ''}
              {data ? ` · 引用・メモ ${data.note_count}件` : ''}
            </span>
            <h2 className="next-title">
              『{data?.book_title ?? ''}』を読み終えました
            </h2>
          </div>
          <Stars value={rating} size={24} onChange={onRate} />
        </header>

        {/* ── 条件 ── */}
        <div className="next-conditions">
          <h3>次に読む本</h3>
          {ALL_BASIS.map((key) => {
            const on = basis.includes(key)
            return (
              <button
                key={key}
                type="button"
                className="basis-toggle"
                aria-pressed={on}
                // 最後の1つは外せない
                disabled={on && basis.length === 1}
                onClick={() => changeBasis(key)}
              >
                <i className={`ph-duotone ${BASIS_ICONS[key]}`} />
                {BASIS_LABELS[key]}
              </button>
            )
          })}
          <Segmented
            name="next-distance"
            value={distance}
            options={(Object.keys(DISTANCE_LABELS) as Distance[]).map((key) => ({
              value: key,
              label: DISTANCE_LABELS[key],
            }))}
            onChange={(next) => {
              setDistance(next)
              setPage(0)
            }}
          />
          <button
            type="button"
            className="btn btn-ghost"
            style={{ fontSize: 12 }}
            disabled={loading}
            onClick={() => setPage((prev) => prev + 1)}
          >
            <i className="ph-duotone ph-arrows-clockwise" />
            出し直す
          </button>
        </div>

        {/* ── 候補 ── */}
        {loading && data === null ? (
          <p className="next-empty">読み込んでいます…</p>
        ) : !data?.configured ? (
          /* この本にはまだ候補を設定していない */
          <p className="next-empty">
            この本の「次に読む本」はまだ決めていません。
            <br />
            読んだ内容をもとに候補を選んで、設定しておくとここに出ます。
          </p>
        ) : visible.length === 0 ? (
          <p className="next-empty">
            条件に合う候補がありません。根拠や距離を変えてみてください。
          </p>
        ) : (
          <div className="next-cards">
            {visible.map((suggestion) => {
              const isAdded = suggestion.added_book_id !== null
              return (
                <article key={suggestion.id} className="next-card">
                  <Cover
                    title={suggestion.title}
                    author={suggestion.author}
                    src={suggestion.cover_url}
                    size="md"
                  />
                  <span className="next-card-title">{suggestion.title}</span>
                  <span className="next-card-author">
                    {suggestion.author ?? '著者不明'}
                  </span>
                  <span className="next-card-reason">{suggestion.reason}</span>
                  <span
                    className={`next-card-basis ${
                      suggestion.basis === 'note' ? 'kind-quote' : 'writing-kicker'
                    }`}
                  >
                    {BASIS_LABELS[suggestion.basis]} ·{' '}
                    {DISTANCE_LABELS[suggestion.distance]}
                  </span>

                  <div className="next-card-actions">
                    {isAdded ? (
                      <>
                        <span className="tag tag-accent">✓ 積読に追加しました</span>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="btn btn-secondary"
                          style={{ fontSize: 12 }}
                          onClick={() => add(suggestion)}
                        >
                          積読に追加
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost"
                          style={{ fontSize: 12, color: 'var(--color-neutral-700)' }}
                          onClick={() => dismiss(suggestion)}
                        >
                          興味なし
                        </button>
                      </>
                    )}
                  </div>
                </article>
              )
            })}
          </div>
        )}

        {/* ── フッター ── */}
        <footer className="next-foot">
          <span className="next-summary">{data?.configured ? data.summary : ''}</span>
          <span style={{ display: 'flex', gap: 'var(--space-2)' }}>
            <button type="button" className="btn btn-ghost" onClick={onWriteReport}>
              レポートを仕上げる
            </button>
            <button type="button" className="btn btn-primary" onClick={onClose}>
              閉じる
            </button>
          </span>
        </footer>
      </div>
    </div>
  )
}
