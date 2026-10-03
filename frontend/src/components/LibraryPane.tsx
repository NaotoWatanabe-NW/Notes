import type { Book, Genre } from '../api'
import { STATUS_LABELS } from '../api'
import type { LibraryFilter } from '../types'
import { isVisible, topTags } from '../visibility'
import { Cover } from './Cover'
import { GenreFilterChips, GenreTag } from './GenreChips'
import { HashText, TagFilterRow } from './HashTags'
import { Segmented } from './Segmented'

type Props = {
  books: Book[]
  filter: LibraryFilter
  tagFilter: string | null
  genreFilter: Genre | null
  selectedId: number | null
  onFilter: (next: LibraryFilter) => void
  onTagFilter: (next: string | null) => void
  onGenreFilter: (next: Genre | null) => void
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
  genreFilter,
  selectedId,
  onFilter,
  onTagFilter,
  onGenreFilter,
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

  const visible = books.filter((book) =>
    isVisible(book, { status: filter, tag: tagFilter, genre: genreFilter }),
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

      {/* 状態 → カテゴリ → タグ の順（デザイン 8b）。条件はすべて同時に効く */}
      <GenreFilterChips value={genreFilter} onChange={onGenreFilter} />
      <TagFilterRow tags={topTags(books, tagFilter)} value={tagFilter} onChange={onTagFilter} />

      {visible.length === 0 ? (
        <p className="list-aside" style={{ padding: '0 8px' }}>
          {books.length === 0
            ? 'まだ本がありません。「＋ 追加」から登録できます。'
            : genreFilter
              ? 'このカテゴリの本はありません。'
              : tagFilter
                ? `#${tagFilter} の本はありません。`
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
                <span className="row-cats">
                  <GenreTag genre={book.genre} />
                  <HashText tags={book.tags} />
                </span>
              </span>
            </button>
          ))}
        </div>
      )}
    </>
  )
}
