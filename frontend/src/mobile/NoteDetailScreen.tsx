import type { NoteWithBook } from '../api'
import { KIND_LABELS } from '../api'
import { Cover } from '../components/Cover'

type Props = {
  note: NoteWithBook
  siblings: NoteWithBook[]
  onSelectNote: (id: number) => void
  onOpenBook: (id: number) => void
  onBack: () => void
}

/** メモ・引用の詳細（Web の C-2 をフル画面に畳んだもの） */
export function NoteDetailScreen({
  note,
  siblings,
  onSelectNote,
  onOpenBook,
  onBack,
}: Props) {
  const others = siblings.filter(
    (item) => item.book.id === note.book.id && item.id !== note.id,
  )

  return (
    <div className="m-screen">
      <div className="m-nav">
        <button type="button" className="m-back" onClick={onBack}>
          <i className="ph-duotone ph-caret-left" />
          メモ
        </button>
      </div>

      <button
        type="button"
        className="m-result"
        style={{ marginBottom: 20 }}
        onClick={() => onOpenBook(note.book.id)}
      >
        <Cover
          title={note.book.title}
          author={note.book.author}
          src={note.book.cover_url}
        />
        <span className="m-result-main">
          <span className="m-result-title" style={{ fontWeight: 600 }}>
            {note.book.title}
          </span>
          <span className="m-result-sub">{note.book.author ?? '著者不明'}</span>
        </span>
        <span className="m-result-go">本を開く ›</span>
      </button>

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
            style={{ fontSize: 22, lineHeight: 1.7, margin: '10px 0' }}
          >
            「{note.text}」
          </p>
          {note.memo ? (
            <p className="muted" style={{ fontSize: 15, margin: 0 }}>
              {note.memo}
            </p>
          ) : null}
        </>
      ) : (
        <p style={{ fontSize: 18, lineHeight: 1.8, margin: '10px 0' }}>{note.text}</p>
      )}

      {others.length > 0 ? (
        <section style={{ marginTop: 28 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600, margin: '0 0 10px' }}>
            同じ本の記録
          </h2>
          <div className="m-note-items" style={{ paddingLeft: 0 }}>
            {others.map((item) => (
              <button
                key={item.id}
                type="button"
                className="m-note-item"
                onClick={() => onSelectNote(item.id)}
              >
                <span
                  className={`m-note-kind ${item.kind === 'quote' ? 'kind-quote' : 'kind-memo'}`}
                >
                  {KIND_LABELS[item.kind]}
                  {item.page ? ` · p.${item.page}` : ''}
                </span>
                <span className="m-note-text">
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
