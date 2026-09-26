import type { NoteWithBook } from '../api'
import { KIND_LABELS } from '../api'
import { Cover } from '../components/Cover'
import { Segmented } from '../components/Segmented'
import type { NoteFilter } from '../types'

type Props = {
  notes: NoteWithBook[]
  filter: NoteFilter
  onFilter: (next: NoteFilter) => void
  onSelect: (id: number) => void
}

type Group = { book: NoteWithBook['book']; latest: string; items: NoteWithBook[] }

/** 本ごとにまとめる（デザイン #7d）。新しい本が上に来る */
function groupByBook(notes: NoteWithBook[]): Group[] {
  const groups = new Map<number, Group>()
  for (const note of notes) {
    const found = groups.get(note.book.id)
    if (found) {
      found.items.push(note)
    } else {
      groups.set(note.book.id, {
        book: note.book,
        latest: note.created_at,
        items: [note],
      })
    }
  }
  return [...groups.values()]
}

/** 7d メモ・引用 */
export function NotesScreen({ notes, filter, onFilter, onSelect }: Props) {
  const visible = filter ? notes.filter((note) => note.kind === filter) : notes
  const groups = groupByBook(visible)

  return (
    <div className="m-screen">
      <div className="m-head">
        <div>
          <span className="m-kicker">{visible.length}件</span>
          <h1 className="m-title">メモ・引用</h1>
        </div>
      </div>

      <div className="m-seg">
        <Segmented
          name="m-note-filter"
          value={filter ?? 'all'}
          options={[
            { value: 'all', label: 'すべて' },
            { value: 'quote', label: '引用' },
            { value: 'memo', label: 'メモ' },
          ]}
          onChange={(next) => onFilter(next === 'all' ? null : next)}
        />
      </div>

      {groups.length === 0 ? (
        <p className="m-empty">まだ記録がありません。本の詳細から残せます。</p>
      ) : (
        groups.map((group) => (
          <section key={group.book.id} className="m-note-group">
            <div className="m-note-group-head">
              <Cover
                title={group.book.title}
                author={group.book.author}
                src={group.book.cover_url}
              />
              <span className="m-note-group-title">{group.book.title}</span>
              <span className="m-note-group-date">{group.latest.slice(0, 10)}</span>
            </div>
            <div className="m-note-items">
              {group.items.map((note) => (
                <button
                  key={note.id}
                  type="button"
                  className="m-note-item"
                  onClick={() => onSelect(note.id)}
                >
                  <span
                    className={`m-note-kind ${note.kind === 'quote' ? 'kind-quote' : 'kind-memo'}`}
                  >
                    {KIND_LABELS[note.kind]}
                    {note.page ? ` · p.${note.page}` : ''}
                  </span>
                  <span
                    className={`m-note-text ${note.kind === 'quote' ? 'quote-styled' : ''}`}
                  >
                    {note.kind === 'quote' ? `「${note.text}」` : note.text}
                  </span>
                </button>
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  )
}
