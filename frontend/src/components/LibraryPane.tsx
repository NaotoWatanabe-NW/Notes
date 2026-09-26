import type { Book, TagCount } from '../api'
import { STATUS_LABELS } from '../api'
import type { LibraryFilter } from '../types'
import { Cover } from './Cover'
import { Segmented } from './Segmented'

type Props = {
  books: Book[]
  filter: LibraryFilter
  tagFilter: string | null
  tags: TagCount[]
  selectedId: number | null
  onFilter: (next: LibraryFilter) => void
  onTagFilter: (next: string | null) => void
  onSelect: (id: number) => void
  onOpenPalette: () => void
  onAdd: () => void
}

/** 一覧の2行目。状態によって出す情報を変える（デザインの指定） */
function meta(book: Book): string {
  if (book.status === 'reading') {
    const parts: string[] = []
    if (book.progress !== null) parts.push(`${book.progress}%`)
    if (book.note_count > 0) parts.push(`メモ ${book.note_count}`)
    return parts.join(' · ') || '読書中'
  }
  if (book.status === 'finished') {
    const parts: string[] = []
    if (book.author) parts.push(book.author)
    if (book.rating) parts.push('★'.repeat(book.rating))
    if (book.read_count > 1) parts.push(`${book.read_count}回`)
    return parts.join(' · ')
  }
  return book.author ?? ''
}

export function LibraryPane({
  books,
  filter,
  tagFilter,
  tags,
  selectedId,
  onFilter,
  onTagFilter,
  onSelect,
  onOpenPalette,
  onAdd,
}: Props) {
  const count = (status: Book['status']) =>
    books.filter((book) => book.status === status).length

  const options = [
    { value: 'reading' as const, label: `読書中 ${count('reading')}` },
    { value: 'finished' as const, label: `読了 ${count('finished')}` },
    { value: 'unread' as const, label: `積読 ${count('unread')}` },
    { value: 'all' as const, label: 'すべて' },
  ]

  const visible = books.filter(
    (book) =>
      (filter === null || book.status === filter) &&
      (tagFilter === null || book.tags.includes(tagFilter)),
  )

  return (
    <>
      <div className="list-head">
        <span className="list-title">本棚</span>
        <span style={{ display: 'flex', gap: 6 }}>
          <button type="button" className="list-action" onClick={onOpenPalette}>
            ⌘K 検索
          </button>
          <button type="button" className="list-action" onClick={onAdd}>
            ＋ 追加
          </button>
        </span>
      </div>

      <Segmented
        name="library-filter"
        value={filter ?? 'all'}
        options={options}
        onChange={(next) => onFilter(next === 'all' ? null : next)}
      />

      {tags.length > 0 ? (
        <div className="tags">
          {tags.map((tag) => (
            <button
              key={tag.name}
              type="button"
              className="tag-chip"
              aria-pressed={tagFilter === tag.name}
              onClick={() => onTagFilter(tagFilter === tag.name ? null : tag.name)}
            >
              {tag.name} {tag.count}
            </button>
          ))}
        </div>
      ) : null}

      {visible.length === 0 ? (
        <p className="list-aside" style={{ padding: '0 8px' }}>
          {books.length === 0
            ? 'まだ本がありません。「＋ 追加」から登録できます。'
            : tagFilter
              ? `「${tagFilter}」の本はありません。`
              : `${filter ? STATUS_LABELS[filter] : ''}の本はありません。`}
        </p>
      ) : (
        <div className="rows">
          {visible.map((book) => (
            <button
              key={book.id}
              type="button"
              className="row"
              aria-current={book.id === selectedId}
              onClick={() => onSelect(book.id)}
            >
              <Cover title={book.title} author={book.author} src={book.cover_url} />
              <span className="row-main">
                <span className="row-title">{book.title}</span>
                <span className="row-meta">{meta(book)}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </>
  )
}
