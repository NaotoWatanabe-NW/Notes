import { useEffect, useState } from 'react'
import type { Book, BookInfo, NoteWithBook } from '../api'
import { ApiError, KIND_LABELS, searchCatalog } from '../api'
import { looksLikeIsbn } from '../isbnLike'
import { Cover } from '../components/Cover'

type Props = {
  books: Book[]
  notes: NoteWithBook[]
  onOpenBook: (id: number) => void
  onOpenNote: (id: number) => void
  onAdd: (info: BookInfo) => Promise<void>
  onClose: () => void
}

function matches(haystack: string | null, needle: string): boolean {
  return (haystack ?? '').toLowerCase().includes(needle)
}

/** 7c 探す（PC版の ⌘K にあたる全画面の検索） */
export function SearchScreen({
  books,
  notes,
  onOpenBook,
  onOpenNote,
  onAdd,
  onClose,
}: Props) {
  const [query, setQuery] = useState('')
  const [catalog, setCatalog] = useState<BookInfo[]>([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [added, setAdded] = useState<string[]>([])

  const trimmed = query.trim()
  const needle = trimmed.toLowerCase()

  // 外部カタログの検索。打つたびに呼ぶと叩きすぎるので少し待ってからにする
  useEffect(() => {
    // ISBN を打っているときは書名で引かない（下の「この番号で追加」を使う）
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
          if (cancelled) return
          setCatalog([])
          // 「見つからなかった」と混同させない
          setSearchError(
            error instanceof ApiError ? error.message : 'いま本を探せませんでした',
          )
        })
        .finally(() => {
          if (!cancelled) setSearching(false)
        })
    }, 300)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [trimmed])

  const shelf = trimmed
    ? books
        .filter((b) => matches(b.title, needle) || matches(b.author, needle))
        .slice(0, 5)
    : books.filter((b) => b.status === 'reading')

  const hits = trimmed
    ? notes.filter((n) => matches(n.text, needle) || matches(n.memo, needle)).slice(0, 4)
    : []

  const owned = new Set(books.map((b) => b.isbn).filter(Boolean))
  const fresh = catalog.filter((info) => !owned.has(info.isbn)).slice(0, 4)

  return (
    <div className="m-screen">
      <div className="m-search-head">
        <input
          className="m-search-input"
          value={query}
          placeholder="本棚・メモを検索、本を追加"
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
        />
        <button type="button" className="btn btn-ghost" onClick={onClose}>
          キャンセル
        </button>
      </div>

      {shelf.length > 0 ? (
        <>
          <p className="m-section-label">{trimmed ? '本棚' : 'いま読んでいる'}</p>
          <div className="m-rows" style={{ marginBottom: 18 }}>
            {shelf.map((book) => (
              <button
                key={book.id}
                type="button"
                className="m-result"
                onClick={() => onOpenBook(book.id)}
              >
                <Cover title={book.title} author={book.author} src={book.cover_url} />
                <span className="m-result-main">
                  <span className="m-result-title">{book.title}</span>
                  <span className="m-result-sub">{book.author ?? '著者不明'}</span>
                </span>
                <span className="m-result-go">開く</span>
              </button>
            ))}
          </div>
        </>
      ) : null}

      {hits.length > 0 ? (
        <>
          <p className="m-section-label">メモ・引用</p>
          <div className="m-rows" style={{ marginBottom: 18 }}>
            {hits.map((note) => (
              <button
                key={note.id}
                type="button"
                className="m-result"
                onClick={() => onOpenNote(note.id)}
              >
                <i
                  className="ph-duotone ph-quotes"
                  style={{ fontSize: 20, color: 'var(--color-accent-2-700)' }}
                />
                <span className="m-result-main">
                  <span className="m-result-title">{note.text.slice(0, 44)}</span>
                  <span className="m-result-sub">
                    {KIND_LABELS[note.kind]} · {note.book.title}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </>
      ) : null}

      {fresh.length > 0 ? (
        <>
          <p className="m-section-label">本を追加</p>
          <div className="m-rows" style={{ marginBottom: 18 }}>
            {fresh.map((info) => {
              const done = added.includes(info.isbn)
              return (
                <div key={info.isbn} className="m-result">
                  <Cover title={info.title} author={info.author} src={info.cover_url} />
                  <span className="m-result-main">
                    <span className="m-result-title">{info.title}</span>
                    <span className="m-result-sub">{info.author ?? '著者不明'}</span>
                  </span>
                  {done ? (
                    <span className="tag tag-accent">✓ 追加</span>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-secondary btn-icon"
                      aria-label={`${info.title} を積読に追加`}
                      onClick={async () => {
                        await onAdd(info)
                        setAdded((prev) => [...prev, info.isbn])
                      }}
                    >
                      <i className="ph-duotone ph-plus" />
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        </>
      ) : null}

      {looksLikeIsbn(trimmed) ? (
        <>
          <p className="m-section-label">操作</p>
          <button
            type="button"
            className="m-result"
            style={{ marginBottom: 18 }}
            onClick={async () => {
              // 書名が分からないので、サーバーに ISBN を引いてもらってから足す
              await onAdd({ isbn: trimmed } as BookInfo)
              setQuery('')
            }}
          >
            <i className="ph-duotone ph-barcode" style={{ fontSize: 20 }} />
            <span className="m-result-main">
              <span className="m-result-title">ISBN {trimmed} で追加</span>
              <span className="m-result-sub">
                書名・著者・ページ数・表紙を自動で取ります
              </span>
            </span>
          </button>
        </>
      ) : null}

      {searching ? <p className="m-empty">本を探しています…</p> : null}
      {searchError ? <p className="m-empty">{searchError}</p> : null}

      {trimmed &&
      !searching &&
      !searchError &&
      !looksLikeIsbn(trimmed) &&
      shelf.length === 0 &&
      hits.length === 0 &&
      fresh.length === 0 ? (
        <p className="m-empty">「{trimmed}」に一致するものはありません。</p>
      ) : null}
    </div>
  )
}
