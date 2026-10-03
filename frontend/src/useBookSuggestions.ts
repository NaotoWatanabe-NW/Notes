/**
 * その本に設定してある「次に読む本」を読み、積読への追加と「興味なし」を扱うフック。
 *
 * 見せ方は PC版（カードを並べる）とモバイル版（1列）で別物なので、
 * `useAppData` と同じように、データの出し入れだけをここで共有する。
 *
 * 読了ダイアログ（#5a / #7g）とは狙いが違う。あちらは根拠と距離で絞り込み、
 * 3冊ずつ出し直す。こちらは詳細画面に置く控えめな一覧なので、
 * 絞り込みは持たず、設定してある候補をそのまま全部出す。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { Basis, Suggestion } from './api'
import { addSuggestionToShelf, ApiError, dismissSuggestion, getSuggestions } from './api'

const ALL_BASIS: Basis[] = ['note', 'rating', 'tag']
/** 1冊につき近い本2・少し離れた本2で設定している。PUT の上限と同じ 20 で足りる */
const PER_PAGE = 20

type Handlers = {
  /** 積読に追加したあと、本棚の一覧を取り直してもらう */
  onAdded: () => void
  onError: (message: string) => void
}

export function useBookSuggestions(bookId: number, handlers: Handlers) {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [configured, setConfigured] = useState(false)
  const [loading, setLoading] = useState(true)
  // 興味なしにした候補を覚えて、その場で消す（サーバーにも記録は残る）
  const [dismissed, setDismissed] = useState<number[]>([])

  // 呼び出し側が毎回新しい関数を渡してきても読み込みが走り直さないよう、
  // 最新の関数は参照でだけ持つ（描画のたびに書き換えず、描画のあとに差し替える）
  const latest = useRef(handlers)
  useEffect(() => {
    latest.current = handlers
  })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const set = await getSuggestions(bookId, {
        basis: ALL_BASIS,
        distance: 'both',
        page: 0,
        perPage: PER_PAGE,
      })
      setSuggestions(set.suggestions)
      setConfigured(set.configured)
    } catch (error) {
      latest.current.onError(
        error instanceof ApiError ? error.message : 'おすすめを取得できませんでした',
      )
    } finally {
      setLoading(false)
    }
  }, [bookId])

  // 別の本に切り替えたら、興味なしの覚えも捨てて取り直す
  useEffect(() => {
    setDismissed([])
    void load()
  }, [load])

  async function add(suggestion: Suggestion) {
    try {
      await addSuggestionToShelf(suggestion.id)
      latest.current.onAdded()
      // 「追加済み」の印はサーバーが持つので、取り直して反映する
      await load()
    } catch (error) {
      latest.current.onError(
        error instanceof ApiError ? error.message : '積読に追加できませんでした',
      )
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
  }

  return {
    suggestions: suggestions.filter((item) => !dismissed.includes(item.id)),
    configured,
    loading,
    add,
    dismiss,
  }
}
