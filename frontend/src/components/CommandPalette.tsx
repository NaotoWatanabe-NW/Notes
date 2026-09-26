import { useEffect, useMemo, useRef, useState } from 'react'
import type { Book, BookInfo, NoteWithBook } from '../api'
import { ApiError, KIND_LABELS, searchCatalog } from '../api'
import { looksLikeIsbn } from '../isbnLike'

export type PaletteAction =
  | { type: 'openBook'; bookId: number }
  | { type: 'openNote'; noteId: number }
  | { type: 'addBook'; info: BookInfo }
  | { type: 'writeNote'; bookId: number }

type Item = {
  key: string
  label: string
  sub?: string
  icon: string
  action: PaletteAction
}

type Group = { label: string; items: Item[] }

type Props = {
  books: Book[]
  notes: NoteWithBook[]
  selectedBook: Book | null
  onRun: (action: PaletteAction) => void
  onClose: () => void
}

function matches(haystack: string | null, needle: string): boolean {
  return (haystack ?? '').toLowerCase().includes(needle)
}

export function CommandPalette({
  books,
  notes,
  selectedBook,
  onRun,
  onClose,
}: Props) {
  const [query, setQuery] = useState('')
  const [catalog, setCatalog] = useState<BookInfo[]>([])
  const [searching, setSearching] = useState(false)
  // 外部検索が引けなかったときの断り書き。「見つからない」とは別物
  const [searchError, setSearchError] = useState<string | null>(null)
  const [cursor, setCursor] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const trimmed = query.trim()
  const needle = trimmed.toLowerCase()
  const ownedIsbns = useMemo(
    () => new Set(books.map((book) => book.isbn).filter(Boolean)),
    [books],
  )

  // 外部カタログの検索。打つたびに呼ぶと叩きすぎるので少し待ってからにする
  useEffect(() => {
    if (trimmed.length < 2 || looksLikeIsbn(trimmed)) {
      setCatalog([])
      setSearchError(null)
      return
    }
    let cancelled = false
    setSearching(true)
    setSearchError(null)
    const timer = window.setTimeout(() => {
      searchCatalog(trimmed)
        .then((found) => {
          if (!cancelled) setCatalog(found)
        })
        .catch((error) => {
          // 外部検索が失敗しても、本棚の検索だけは使えるようにしておく。
          // ただし「見つからなかった」と混同させない
          if (cancelled) return
          setCatalog([])
          setSearchError(
            error instanceof ApiError
              ? error.message
              : 'いま本を探せませんでした',
          )
        })
        .finally(() => {
          if (!cancelled) setSearching(false)
        })
    }, 300)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
      setSearching(false)
    }
  }, [trimmed])

  const groups: Group[] = useMemo(() => {
    if (!trimmed) {
      const reading = books.filter((book) => book.status === 'reading').slice(0, 5)
      const result: Group[] = []
      if (reading.length > 0) {
        result.push({
          label: 'いま読んでいる',
          items: reading.map((book) => ({
            key: `book-${book.id}`,
            label: book.title,
            sub: book.progress !== null ? `${book.progress}%` : undefined,
            icon: 'ph-book-open',
            action: { type: 'openBook', bookId: book.id },
          })),
        })
      }
      return result
    }

    const result: Group[] = []

    const shelf = books
      .filter((book) => matches(book.title, needle) || matches(book.author, needle))
      .slice(0, 4)
    if (shelf.length > 0) {
      result.push({
        label: '本棚',
        items: shelf.map((book) => ({
          key: `book-${book.id}`,
          label: book.title,
          sub: book.author ?? undefined,
          icon: 'ph-books',
          action: { type: 'openBook', bookId: book.id },
        })),
      })
    }

    const hits = notes
      .filter((note) => matches(note.text, needle) || matches(note.memo, needle))
      .slice(0, 3)
    if (hits.length > 0) {
      result.push({
        label: 'メモ・引用',
        items: hits.map((note) => ({
          key: `note-${note.id}`,
          label: note.text.slice(0, 40),
          sub: `${KIND_LABELS[note.kind]} · ${note.book.title}`,
          icon: 'ph-quotes',
          action: { type: 'openNote', noteId: note.id },
        })),
      })
    }

    // すでに本棚にある本は「追加」に出さない
    const fresh = catalog.filter((info) => !ownedIsbns.has(info.isbn)).slice(0, 4)
    if (fresh.length > 0) {
      result.push({
        label: '本を追加',
        items: fresh.map((info) => ({
          key: `catalog-${info.isbn}`,
          label: info.title,
          sub: info.author ?? undefined,
          icon: 'ph-plus',
          action: { type: 'addBook', info },
        })),
      })
    }

    const actions: Item[] = []
    if (looksLikeIsbn(trimmed)) {
      actions.push({
        key: 'isbn',
        label: `ISBN ${trimmed} で追加`,
        icon: 'ph-barcode',
        action: { type: 'addBook', info: { isbn: trimmed } as BookInfo },
      })
    }
    if (selectedBook) {
      actions.push({
        key: 'write-note',
        label: `「${selectedBook.title}」にメモを書く`,
        icon: 'ph-pencil-simple-line',
        action: { type: 'writeNote', bookId: selectedBook.id },
      })
    }
    if (actions.length > 0) result.push({ label: '操作', items: actions })

    return result
  }, [trimmed, needle, books, notes, catalog, ownedIsbns, selectedBook])

  const flat = useMemo(() => groups.flatMap((group) => group.items), [groups])

  // 候補が変わったら選択位置を先頭に戻す
  useEffect(() => {
    setCursor(0)
  }, [flat.length, trimmed])

  function handleKeyDown(event: React.KeyboardEvent) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setCursor((prev) => (flat.length === 0 ? 0 : (prev + 1) % flat.length))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setCursor((prev) => (flat.length === 0 ? 0 : (prev - 1 + flat.length) % flat.length))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const item = flat[cursor]
      if (item) onRun(item.action)
    }
  }

  let index = -1

  return (
    <div
      className="palette-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="palette" role="dialog" aria-label="検索・追加">
        <div className="palette-input-row">
          <i className="ph-duotone ph-magnifying-glass" />
          <input
            ref={inputRef}
            className="palette-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="本棚・メモを検索、または本を追加"
          />
          <span className="palette-esc">esc</span>
        </div>

        <div className="palette-results">
          {groups.map((group) => (
            <div key={group.label}>
              <div className="palette-group-label">{group.label}</div>
              {group.items.map((item) => {
                index += 1
                const current = index
                return (
                  <button
                    key={item.key}
                    type="button"
                    className="palette-item"
                    aria-selected={current === cursor}
                    onMouseEnter={() => setCursor(current)}
                    onClick={() => onRun(item.action)}
                  >
                    <i className={`ph-duotone ${item.icon}`} />
                    <span>{item.label}</span>
                    {item.sub ? (
                      <span className="palette-item-sub">{item.sub}</span>
                    ) : null}
                  </button>
                )
              })}
            </div>
          ))}

          {/* 外部カタログは応答が遅いことがあるので、待っていることを伝える */}
          {searching && !groups.some((group) => group.label === '本を追加') ? (
            <p className="palette-empty">本を探しています…</p>
          ) : null}

          {/* 外部が引けなかったときは、そう言う */}
          {searchError ? <p className="palette-empty">{searchError}</p> : null}

          {groups.length === 0 && !searching && !searchError ? (
            <p className="palette-empty">
              {trimmed
                ? `「${trimmed}」に一致するものはありません。`
                : '本棚・メモを検索するか、書名を入れて本を追加できます。'}
            </p>
          ) : null}
        </div>

        <div className="palette-foot">
          <span>↵ 先頭を選択</span>
          <span>esc 閉じる</span>
          <span>⌘K 開閉</span>
        </div>
      </div>
    </div>
  )
}
