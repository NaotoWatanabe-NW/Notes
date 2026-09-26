import type { Book, BookStatus } from '../api'
import { STATUS_LABELS } from '../api'
import { Cover } from '../components/Cover'
import { Segmented } from '../components/Segmented'

type Filter = BookStatus | 'all'

type Props = {
  books: Book[]
  filter: Filter
  onFilter: (next: Filter) => void
  onSelect: (id: number) => void
  onSearch: () => void
  onSettings: () => void
}

/** 「9月26日 · 7冊」 */
function todayLine(count: number): string {
  const now = new Date()
  return `${now.getMonth() + 1}月${now.getDate()}日 · ${count}冊`
}

function meta(book: Book): string {
  const parts = [book.author].filter(Boolean) as string[]
  parts.push(STATUS_LABELS[book.status])
  if (book.rating) parts.push('★'.repeat(book.rating))
  return parts.join(' · ')
}

/** 7a 本棚 */
export function LibraryScreen({
  books,
  filter,
  onFilter,
  onSelect,
  onSearch,
  onSettings,
}: Props) {
  const reading = books.filter((book) => book.status === 'reading')
  const count = (status: BookStatus) =>
    books.filter((book) => book.status === status).length

  // 読書中は上のカードに出すので、セグメントからは外す（デザインの指定）
  const options: { value: Filter; label: string }[] = [
    { value: 'all', label: 'すべて' },
    { value: 'finished', label: `読了 ${count('finished')}` },
    { value: 'unread', label: `積読 ${count('unread')}` },
  ]
  const visible = filter === 'all' ? books : books.filter((b) => b.status === filter)

  return (
    <div className="m-screen m-screen-flush">
      <div className="m-head">
        <div>
          <span className="m-kicker">{todayLine(books.length)}</span>
          <h1 className="m-title">本棚</h1>
        </div>
        <button
          type="button"
          className="m-icon-btn"
          aria-label="設定"
          onClick={onSettings}
        >
          <i className="ph-duotone ph-gear" />
        </button>
      </div>

      <button type="button" className="m-searchbar" onClick={onSearch}>
        <i className="ph-duotone ph-magnifying-glass" />
        <span>本棚・メモを検索、本を追加</span>
        <i className="ph-duotone ph-barcode" />
      </button>

      {reading.length > 0 ? (
        <>
          <p className="m-section-label">いま読んでいる · {reading.length}冊</p>
          <div className="m-bleed m-reading-row">
            {reading.map((book) => (
              <button
                key={book.id}
                type="button"
                className="m-reading-card"
                onClick={() => onSelect(book.id)}
              >
                <Cover
                  title={book.title}
                  author={book.author}
                  src={book.cover_url}
                  size="sm"
                />
                <span className="m-reading-main">
                  <span className="m-reading-title">{book.title}</span>
                  <span className="m-reading-meta">{book.author ?? '著者不明'}</span>
                  <span className="m-reading-progress">
                    {book.total
                      ? `p.${book.page} / ${book.total} · ${book.progress}%`
                      : `p.${book.page}`}
                  </span>
                  {book.total ? (
                    <span className="progress-bar" style={{ maxWidth: 'none' }}>
                      <span style={{ width: `${book.progress ?? 0}%` }} />
                    </span>
                  ) : null}
                </span>
              </button>
            ))}
          </div>
        </>
      ) : null}

      <div className="m-seg">
        <Segmented
          name="m-library-filter"
          value={filter}
          options={options}
          onChange={onFilter}
        />
      </div>

      {visible.length === 0 ? (
        <p className="m-empty">
          {books.length === 0
            ? 'まだ本がありません。上の検索から追加できます。'
            : 'この条件の本はありません。'}
        </p>
      ) : (
        <div className="m-rows">
          {visible.map((book) => (
            <button
              key={book.id}
              type="button"
              className="m-row"
              onClick={() => onSelect(book.id)}
            >
              <Cover title={book.title} author={book.author} src={book.cover_url} />
              <span className="m-row-main">
                <span className="m-row-title">{book.title}</span>
                <span className="m-row-meta">{meta(book)}</span>
              </span>
              <i className="ph-duotone ph-caret-right m-row-caret" />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
