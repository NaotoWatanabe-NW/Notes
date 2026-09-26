/**
 * 本・記録・タグ・設定の読み書きをまとめたフック。
 *
 * PC版（3ペイン）とモバイル版（タブバー＋単一画面）で画面の組み立ては
 * まったく違うが、扱うデータと操作は同じなので、ここに1つだけ置いて
 * 両方から使う。
 */
import { useCallback, useEffect, useState } from 'react'
import type {
  Book,
  BookDetail,
  Note,
  NoteCreate,
  NoteWithBook,
  Settings,
  SettingsUpdate,
  TagCount,
} from './api'
import * as api from './api'
import { ApiError } from './api'

export function useAppData() {
  const [books, setBooks] = useState<Book[]>([])
  const [notes, setNotes] = useState<NoteWithBook[]>([])
  const [tags, setTags] = useState<TagCount[]>([])
  const [settings, setSettings] = useState<Settings | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  const [selectedBookId, setSelectedBookId] = useState<number | null>(null)
  const [bookDetail, setBookDetail] = useState<BookDetail | null>(null)
  const [bookNotes, setBookNotes] = useState<Note[]>([])

  // 読み終えた瞬間に「次に読む本」を出すための目印
  const [justFinished, setJustFinished] = useState<number | null>(null)

  const notify = useCallback((message: string) => setToast(message), [])
  const fail = useCallback((error: unknown, fallback: string) => {
    setToast(error instanceof ApiError ? error.message : fallback)
  }, [])

  /** 一覧をまとめて取り直す。更新のあとに呼ぶ */
  const reload = useCallback(async () => {
    try {
      const [loadedBooks, loadedNotes, loadedTags] = await Promise.all([
        api.listBooks(),
        api.listNotes(),
        api.listTags(),
      ])
      setBooks(loadedBooks)
      setNotes(loadedNotes)
      setTags(loadedTags)
    } catch (error) {
      fail(error, '読み込みに失敗しました')
    }
  }, [fail])

  useEffect(() => {
    void reload()
    api.getSettings().then(setSettings).catch(() => undefined)
  }, [reload])

  // 並び順の設定を変えたら本棚を取り直す（並びはサーバーが決める）
  useEffect(() => {
    if (settings) void api.listBooks().then(setBooks).catch(() => undefined)
  }, [settings?.sort])

  // 引用をイタリックにするかどうかは、ルート要素の属性でまとめて切り替える
  useEffect(() => {
    document.documentElement.dataset.quote = settings?.quote_style ?? 'italic'
  }, [settings?.quote_style])

  // 選んだ本の詳細とノートを取る
  useEffect(() => {
    if (selectedBookId === null) {
      setBookDetail(null)
      setBookNotes([])
      return
    }
    let cancelled = false
    Promise.all([api.getBook(selectedBookId), api.listBookNotes(selectedBookId)])
      .then(([detail, loaded]) => {
        if (cancelled) return
        setBookDetail(detail)
        setBookNotes(loaded)
      })
      .catch((error) => {
        if (!cancelled) fail(error, '本を読み込めませんでした')
      })
    return () => {
      cancelled = true
    }
  }, [selectedBookId, books, fail])

  // ---------------------------------------------------------------- 操作

  async function updateBook(id: number, payload: api.BookUpdate) {
    const before = books.find((book) => book.id === id)?.status
    try {
      const updated = await api.updateBook(id, payload)
      setBookDetail(updated)
      await reload()
      // 読み終えた瞬間だけ「次に読む本」を出す（デザイン #5a / #7g）
      if (before !== 'finished' && updated.status === 'finished') {
        setJustFinished(updated.id)
      }
    } catch (error) {
      fail(error, '更新できませんでした')
    }
  }

  /** 本を1冊足す */
  async function addBook(payload: api.BookCreate) {
    const created = await api.createBook(payload)
    await reload()
    return created
  }

  async function addNote(bookId: number, payload: NoteCreate) {
    try {
      await api.createNote(bookId, payload)
      setBookNotes(await api.listBookNotes(bookId))
      await reload()
      notify('記録しました')
    } catch (error) {
      fail(error, '保存できませんでした')
    }
  }

  async function changeNote(noteId: number, payload: Partial<NoteCreate>) {
    try {
      await api.updateNote(noteId, payload)
      if (selectedBookId) setBookNotes(await api.listBookNotes(selectedBookId))
      await reload()
    } catch (error) {
      fail(error, '更新できませんでした')
    }
  }

  async function removeNote(note: Note) {
    if (!window.confirm('この記録を削除します。よろしいですか？')) return
    try {
      await api.deleteNote(note.id)
      if (selectedBookId) setBookNotes(await api.listBookNotes(selectedBookId))
      await reload()
    } catch (error) {
      fail(error, '削除できませんでした')
    }
  }

  async function removeBook(book: Book) {
    if (!window.confirm(`「${book.title}」を削除します。よろしいですか？`)) return
    try {
      await api.deleteBook(book.id)
      setSelectedBookId(null)
      await reload()
      notify('削除しました')
    } catch (error) {
      fail(error, '削除できませんでした')
    }
  }

  async function changeSettings(payload: SettingsUpdate) {
    try {
      setSettings(await api.updateSettings(payload))
    } catch (error) {
      fail(error, '設定を保存できませんでした')
    }
  }

  return {
    books,
    notes,
    tags,
    settings,
    toast,
    setToast,
    selectedBookId,
    setSelectedBookId,
    bookDetail,
    bookNotes,
    justFinished,
    clearJustFinished: () => setJustFinished(null),
    reload,
    notify,
    fail,
    updateBook,
    addBook,
    addNote,
    changeNote,
    removeNote,
    removeBook,
    changeSettings,
  }
}

export type AppData = ReturnType<typeof useAppData>
