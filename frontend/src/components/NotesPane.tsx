import type { NoteWithBook } from '../api'
import { KIND_LABELS } from '../api'
import type { NoteFilter } from '../types'
import { Segmented } from './Segmented'

type Props = {
  notes: NoteWithBook[]
  filter: NoteFilter
  selectedId: number | null
  onFilter: (next: NoteFilter) => void
  onSelect: (id: number) => void
}

/** 一覧では長い引用を途中で切る（デザインの指定は42字） */
const LIMIT = 42

export function summarize(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length > LIMIT ? `${flat.slice(0, LIMIT)}…` : flat
}

export function NotesPane({
  notes,
  filter,
  selectedId,
  onFilter,
  onSelect,
}: Props) {
  const options = [
    { value: 'all' as const, label: 'すべて' },
    { value: 'quote' as const, label: '引用' },
    { value: 'memo' as const, label: 'メモ' },
  ]
  const visible = filter ? notes.filter((note) => note.kind === filter) : notes

  return (
    <>
      <div className="list-head">
        <span className="list-title">メモ・引用</span>
        <span className="list-aside">{visible.length}件</span>
      </div>

      <Segmented
        name="note-filter"
        value={filter ?? 'all'}
        options={options}
        onChange={(next) => onFilter(next === 'all' ? null : next)}
      />

      {visible.length === 0 ? (
        <p className="list-aside" style={{ padding: '0 8px' }}>
          まだ記録がありません。本の詳細から残せます。
        </p>
      ) : (
        <div className="rows">
          {visible.map((note) => (
            <button
              key={note.id}
              type="button"
              className="row row-note"
              aria-current={note.id === selectedId}
              onClick={() => onSelect(note.id)}
            >
              <span
                className={`row-meta ${note.kind === 'quote' ? 'kind-quote' : 'kind-memo'}`}
              >
                {KIND_LABELS[note.kind]}
              </span>
              <span
                style={{ fontSize: 14, lineHeight: 1.65 }}
                className={note.kind === 'quote' ? 'quote-styled' : undefined}
              >
                {note.kind === 'quote'
                  ? `「${summarize(note.text)}」`
                  : summarize(note.text)}
              </span>
              <span className="row-meta">
                {note.book.title}
                {note.page ? ` · p.${note.page}` : ''}
              </span>
            </button>
          ))}
        </div>
      )}
    </>
  )
}
