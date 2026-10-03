/**
 * おすすめ一覧（デザイン J）を読み、積読への追加と「興味なし」を扱うフック。
 * 見せ方は PC版（一覧ペイン＋詳細）とモバイル版（本棚の帯・7h・7i）で別物なので、
 * データの出し入れだけをここで共有する。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { Recommendation } from './api'
import { addRecommendation, ApiError, dismissSuggestion, listRecommendations } from './api'

type Handlers = {
  /** 積読に追加したあと、本棚の一覧を取り直してもらう */
  onAdded: () => void
  onNotify: (message: string) => void
  onError: (message: string) => void
}

/**
 * @param active おすすめを出している画面か。出すたびに取り直す
 *   （ほかの画面で積読に足した・興味なしにした、を拾うため）
 */
export function useRecommendations(active: boolean, handlers: Handlers) {
  const [items, setItems] = useState<Recommendation[]>([])
  const [loading, setLoading] = useState(true)
  // この画面で積読に足した本（ISBN → 本の id）。デザインどおり、一覧には残して印を出す
  const [added, setAdded] = useState<Map<string, number>>(new Map())

  // 呼び出し側が毎回新しい関数を渡してきても読み込みが走り直さないよう、参照でだけ持つ
  const latest = useRef(handlers)
  useEffect(() => {
    latest.current = handlers
  })

  const fail = useCallback((error: unknown, fallback: string) => {
    latest.current.onError(error instanceof ApiError ? error.message : fallback)
  }, [])

  useEffect(() => {
    if (!active) return
    let cancelled = false
    // 足した本は、開き直すと一覧から消える（本棚に入ったので）。開いている間は残して印を出す
    listRecommendations()
      .then((next) => {
        if (!cancelled) setItems(next)
      })
      .catch((error: unknown) => fail(error, 'おすすめを取得できませんでした'))
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [active, fail])

  async function add(item: Recommendation) {
    try {
      const book = await addRecommendation(item.isbn)
      setAdded((prev) => new Map(prev).set(item.isbn, book.id))
      latest.current.onAdded()
      latest.current.onNotify(`「${item.title}」を積読に追加しました`)
    } catch (error) {
      fail(error, '積読に追加できませんでした')
    }
  }

  async function dismiss(item: Recommendation) {
    try {
      await dismissSuggestion(item.isbn)
      setItems((prev) => prev.filter((other) => other.isbn !== item.isbn))
      latest.current.onNotify(`「${item.title}」をおすすめから外しました`)
    } catch (error) {
      fail(error, '興味なしにできませんでした')
    }
  }

  return { items, loading, added, add, dismiss }
}
