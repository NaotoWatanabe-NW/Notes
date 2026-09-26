import type { NoteWithBook } from '../api'
import { KIND_LABELS } from '../api'
import { Cover } from './Cover'

type Props = {
  note: NoteWithBook
  siblings: NoteWithBook[]
  onSelectNote: (id: number) => void
  onOpenBook: (id: number) => void
}

export function NoteDetailView({
  note,
  siblings,
  onSelectNote,
  onOpenBook,
}: Props) {
  const others = siblings.filter(
    (item) => item.book.id === note.book.id && item.id !== note.id,
  )

  return (
    <div className="detail">
      <header style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Cover
          title={note.book.title}
          author={note.book.author}
          src={note.book.cover_url}
        />
        <div className="row-main" style={{ flex: 1 }}>
          <span style={{ fontSize: 15, fontWeight: 600 }}>{note.book.title}</span>
          <span className="row-meta">{note.book.author ?? '著者不明'}</span>
        </div>
        <button
          type="button"
          className="btn btn-ghost"
          style={{ color: 'var(--color-accent-700)', fontSize: 13 }}
          onClick={() => onOpenBook(note.book.id)}
        >
          本を開く →
        </button>
      </header>

      <section className="stack" style={{ gap: 12 }}>
        <span
          className={note.kind === 'quote' ? 'kind-quote' : 'kind-memo'}
          style={{ fontSize: 13 }}
        >
          {KIND_LABELS[note.kind]}
          {note.page ? ` · p.${note.page}` : ''} · {note.created_at.slice(0, 10)}
        </span>
        {note.kind === 'quote' ? (
          <>
            <p
              className="quote-styled"
              style={{ fontSize: 28, lineHeight: 1.6, margin: 0 }}
            >
              「{note.text}」
            </p>
            {note.memo ? (
              <p style={{ fontSize: 16, margin: 0 }} className="muted">
                {note.memo}
              </p>
            ) : null}
          </>
        ) : (
          <p style={{ fontSize: 22, lineHeight: 1.7, margin: 0 }}>{note.text}</p>
        )}
      </section>

      {others.length > 0 ? (
        <section className="stack" style={{ gap: 12 }}>
          <h2 className="section-title">同じ本の記録</h2>
          <div className="rows">
            {others.map((item) => (
              <button
                key={item.id}
                type="button"
                className="row row-note"
                onClick={() => onSelectNote(item.id)}
                style={{ maxWidth: 620 }}
              >
                <span
                  className={`row-meta ${item.kind === 'quote' ? 'kind-quote' : 'kind-memo'}`}
                >
                  {KIND_LABELS[item.kind]}
                  {item.page ? ` · p.${item.page}` : ''}
                </span>
                <span style={{ fontSize: 15, lineHeight: 1.65 }}>
                  {item.kind === 'quote' ? `「${item.text}」` : item.text}
                </span>
              </button>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  )
}
