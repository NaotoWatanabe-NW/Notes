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
import { Stars } from '../components/Stars'
import { Sheet } from './Sheet'
import { SuggestionRow } from './SuggestionRow'

type Props = {
  bookId: number
  rating: number | null
  onRate: (rating: number | null) => void
  onAdded: () => void
  onWriteReport: () => void
  onClose: () => void
  onError: (message: string) => void
}

const ALL_BASIS: Basis[] = ['note', 'rating', 'tag']
const ALL_DISTANCE: Distance[] = ['near', 'far', 'both']

/** 7g 読了 → 次に読む本（PC版 #5a のモバイル版） */
export function NextBookSheet({
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

  function toggleBasis(key: Basis) {
    const next = basis.includes(key) ? basis.filter((b) => b !== key) : [...basis, key]
    // 最低1つは ON のままにする
    if (next.length === 0) return
    setBasis(next)
    setPage(0)
  }

  async function add(suggestion: Suggestion) {
    try {
      await addSuggestionToShelf(suggestion.id)
      onAdded()
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
    setPage((prev) => prev + 1)
  }

  const visible = (data?.suggestions ?? []).filter((s) => !dismissed.includes(s.id))

  return (
    <Sheet size="full" dim="strong" onClose={onClose}>
      <div className="m-sheet-body">
        <span className="m-section-label">
          読了
          {data?.days ? ` · ${data.days}日間` : ''}
          {data ? ` · 引用・メモ ${data.note_count}件` : ''}
        </span>
        <h2 style={{ fontSize: 22, fontWeight: 600, lineHeight: 1.35, margin: '4px 0 10px' }}>
          『{data?.book_title ?? ''}』を読み終えました
        </h2>
        <Stars value={rating} size={28} onChange={onRate} />

        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            justifyContent: 'space-between',
            margin: '22px 0 10px',
          }}
        >
          <h3 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>次に読む本</h3>
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

        {/* 条件は横スクロールのチップ（デザインの指定） */}
        <div className="m-chips" style={{ paddingLeft: 0, paddingRight: 0 }}>
          {ALL_BASIS.map((key) => {
            const on = basis.includes(key)
            return (
              <button
                key={key}
                type="button"
                className={`m-chip tag ${on ? 'tag-accent' : 'tag-neutral'}`}
                disabled={on && basis.length === 1}
                onClick={() => toggleBasis(key)}
              >
                {BASIS_LABELS[key]}
              </button>
            )
          })}
          {ALL_DISTANCE.map((key) => (
            <button
              key={key}
              type="button"
              className={`m-chip tag ${distance === key ? 'tag-accent' : 'tag-neutral'}`}
              onClick={() => {
                setDistance(key)
                setPage(0)
              }}
            >
              {DISTANCE_LABELS[key]}
            </button>
          ))}
        </div>

        {loading && data === null ? (
          <p className="m-empty">読み込んでいます…</p>
        ) : !data?.configured ? (
          <p className="m-empty">
            この本の「次に読む本」はまだ決めていません。
            <br />
            読んだ内容をもとに候補を選んで、設定しておくとここに出ます。
          </p>
        ) : visible.length === 0 ? (
          <p className="m-empty">
            条件に合う候補がありません。根拠や距離を変えてみてください。
          </p>
        ) : (
          visible.map((suggestion) => (
            <SuggestionRow
              key={suggestion.id}
              suggestion={suggestion}
              onAdd={() => void add(suggestion)}
              onDismiss={() => void dismiss(suggestion)}
            />
          ))
        )}

        {data?.configured ? (
          <p className="m-kicker" style={{ marginTop: 18 }}>
            {data.summary}
          </p>
        ) : null}
      </div>

      <div className="m-sheet-actions">
        <button type="button" className="btn btn-secondary" onClick={onWriteReport}>
          <i className="ph-duotone ph-article" />
          レポートを仕上げる
        </button>
        <button
          type="button"
          className="btn btn-primary"
          style={{ flex: 1 }}
          onClick={onClose}
        >
          閉じる
        </button>
      </div>
    </Sheet>
  )
}
