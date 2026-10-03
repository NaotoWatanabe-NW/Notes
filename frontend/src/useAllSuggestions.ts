/**
 * おすすめ一覧（全部の本の「次に読む本」）を読み、積読への追加と「興味なし」を扱うフック。
 *
 * 見せ方は PC版（一覧ペイン＋詳細）とモバイル版（1画面）で別物なので、
 * `useBookSuggestions` と同じように、データの出し入れだけをここで共有する。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { SuggestionWithBook } from './api'
import { addSuggestionToShelf, ApiError, dismissSuggestion, listAllSuggestions } from './api'

type Handlers = {
  /** 積読に追加したあと、本棚の一覧を取り直してもらう */
  onAdded: () => void
  onError: (message: string) => void
}

/**
 * @param active おすすめの画面を開いているか。開くたびに取り直す
 *   （本の詳細で「興味なし」にした、などの変化を拾うため）。
 *   閉じている間は読まない（アプリを開くたびに数百件を取りに行かない）
 */
export function useAllSuggestions(active: boolean, handlers: Handlers) {
  const [items, setItems] = useState<SuggestionWithBook[]>([])
  const [loading, setLoading] = useState(true)

  // 呼び出し側が毎回新しい関数を渡してきても読み込みが走り直さないよう、参照でだけ持つ
  const latest = useRef(handlers)
  useEffect(() => {
    latest.current = handlers
  })

  // 「読み込み中」は最初の1回だけ。取り直しの間は前の一覧を出したままにする
  const load = useCallback(
    () =>
      listAllSuggestions()
        .then(setItems)
        .catch((error: unknown) => {
          latest.current.onError(
            error instanceof ApiError ? error.message : 'おすすめを取得できませんでした',
          )
        })
        .finally(() => setLoading(false)),
    [],
  )

  useEffect(() => {
    if (active) void load()
  }, [active, load])

  async function add(item: SuggestionWithBook) {
    try {
      await addSuggestionToShelf(item.id)
      latest.current.onAdded()
      // 「追加済み」の印はサーバーが持つので、取り直して反映する
      await load()
    } catch (error) {
      latest.current.onError(
        error instanceof ApiError ? error.message : '積読に追加できませんでした',
      )
    }
  }

  async function dismiss(item: SuggestionWithBook) {
    // 興味なしは ISBN で覚えるので、同じ本はほかの本の候補からも消える
    setItems((prev) =>
      prev.filter((other) => (item.isbn ? other.isbn !== item.isbn : other.id !== item.id)),
    )
    if (item.isbn) {
      try {
        await dismissSuggestion(item.isbn)
      } catch {
        // 記録に失敗しても、この場で消えていれば用は足りる
      }
    }
  }

  return { items, loading, add, dismiss }
}
