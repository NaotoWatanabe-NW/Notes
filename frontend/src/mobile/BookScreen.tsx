import { useState } from 'react'
import type { BookDetail, BookUpdate, Note, NoteCreate } from '../api'
import { KIND_LABELS, STATUS_LABELS } from '../api'
import { CoverPicker } from '../components/CoverPicker'
import { Stars } from '../components/Stars'
import { countCharacters } from '../markdownInsert'
import { NoteSheet } from './NoteSheet'
import { Sheet } from './Sheet'

type Props = {
  book: BookDetail
  notes: Note[]
  onBack: () => void
  onUpdate: (payload: BookUpdate) => void
  onAddNote: (payload: NoteCreate) => Promise<void>
  onDeleteNote: (note: Note) => void
  onWriteReport: () => void
  onDelete: () => void
  onReload: () => void
  onError: (message: string) => void
}

const STATUS_TAG: Record<BookDetail['status'], string> = {
  reading: 'tag-accent',
  finished: 'tag-outline',
  unread: 'tag-neutral',
}

/** 「2026-09-03」→「9月3日」 */
function shortDate(iso: string): string {
  const [, month, day] = iso.split('-')
  return `${Number(month)}月${Number(day)}日`
}

/** 7b 本の詳細 */
export function BookScreen({
  book,
  notes,
  onBack,
  onUpdate,
  onAddNote,
  onDeleteNote,
  onWriteReport,
  onDelete,
  onReload,
  onError,
}: Props) {
  const [sheet, setSheet] = useState<'none' | 'note' | 'more' | 'progress'>('none')
  const [pageDraft, setPageDraft] = useState(String(book.page || ''))

  function saveProgress() {
    const next = Number(pageDraft)
    if (!Number.isFinite(next) || next < 0) return
    onUpdate({ page: next, status: book.status === 'unread' ? 'reading' : undefined })
    setSheet('none')
  }

  const reportChars = book.report_md ? countCharacters(book.report_md) : 0

  return (
    <div className="m-screen">
      <div className="m-nav">
        <button type="button" className="m-back" onClick={onBack}>
          <i className="ph-duotone ph-caret-left" />
          本棚
        </button>
        <button
          type="button"
          className="m-icon-btn"
          aria-label="この本の操作"
          onClick={() => setSheet('more')}
        >
          <i className="ph-duotone ph-dots-three" />
        </button>
      </div>

      <div className="m-book-head">
        <CoverPicker
          bookId={book.id}
          title={book.title}
          author={book.author}
          coverUrl={book.cover_url}
          size="md"
          onChanged={onReload}
          onError={onError}
        />
        <div className="m-book-main">
          <span>
            <span className={`tag ${STATUS_TAG[book.status]}`}>
              {STATUS_LABELS[book.status]}
            </span>
            {book.read_count > 1 ? (
              <span className="tag tag-neutral" style={{ marginLeft: 6 }}>
                {book.read_count}回読了
              </span>
            ) : null}
          </span>
          <h1 className="m-book-title">{book.title}</h1>
          <p className="m-book-byline">
            {[book.author, book.publisher].filter(Boolean).join(' · ') || '著者不明'}
          </p>
          {book.status === 'finished' ? (
            <Stars value={book.rating} onChange={(rating) => onUpdate({ rating })} />
          ) : null}
        </div>
      </div>

      {book.status === 'reading' && book.total ? (
        <section className="stack" style={{ marginBottom: 18 }}>
          <div className="progress-line" style={{ maxWidth: 'none' }}>
            <span>
              p.{book.page} / {book.total}
            </span>
            <span>
              {book.started_on ? `${shortDate(book.started_on)}から · ` : ''}
              {book.progress}%
            </span>
          </div>
          <div className="progress-bar" style={{ maxWidth: 'none' }}>
            <span style={{ width: `${book.progress ?? 0}%` }} />
          </div>
        </section>
      ) : null}

      <div className="m-actions-2">
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => setSheet('note')}
        >
          <i className="ph-duotone ph-pencil-simple-line" />
          メモを書く
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => {
            setPageDraft(String(book.page || ''))
            setSheet('progress')
          }}
        >
          進捗を記録
        </button>
      </div>

      <button type="button" className="m-report-row" onClick={onWriteReport}>
        <i className="ph-duotone ph-article" />
        <span className="m-report-main">
          <span className="m-report-title">
            {book.report_md ? '読書レポート' : 'レポートを書く'}
          </span>
          {book.report_md ? (
            <span className="m-report-meta">
              {reportChars.toLocaleString()}字 · {book.updated_at.slice(0, 10)}に更新
            </span>
          ) : (
            <span className="m-report-meta">読んで考えたことをまとめる</span>
          )}
        </span>
        <span className="m-report-go">
          {book.report_md ? '続きを書く ›' : '書く ›'}
        </span>
      </button>

      <div className="section-head" style={{ marginBottom: 12 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>
          メモ・引用 {notes.length}件
        </h2>
        {notes.length > 0 ? <span className="section-aside">ページ順</span> : null}
      </div>

      {notes.length === 0 ? (
        <p className="m-empty">
          まだ記録がありません。読んだページの引用や、そのとき考えたことを残せます。
        </p>
      ) : (
        <ul className="records" style={{ gap: 22 }}>
          {notes.map((note) => (
            <li key={note.id} className="record" style={{ maxWidth: 'none' }}>
              <div className="section-head">
                <span
                  className={`record-kind ${note.kind === 'quote' ? 'kind-quote' : 'kind-memo'}`}
                >
                  {KIND_LABELS[note.kind]}
                  {note.page ? ` · p.${note.page}` : ''}
                </span>
                <button
                  type="button"
                  className="btn btn-ghost"
                  style={{ fontSize: 12 }}
                  onClick={() => onDeleteNote(note)}
                >
                  削除
                </button>
              </div>
              {note.kind === 'quote' ? (
                <>
                  <p className="record-quote quote-styled" style={{ fontSize: 16 }}>
                    「{note.text}」
                  </p>
                  {note.memo ? <p className="record-sub">{note.memo}</p> : null}
                </>
              ) : (
                <p className="record-memo" style={{ fontSize: 16 }}>
                  {note.text}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}

      {sheet === 'note' ? (
        <NoteSheet
          page={book.page}
          onSave={onAddNote}
          onClose={() => setSheet('none')}
        />
      ) : null}

      {sheet === 'progress' ? (
        <Sheet size="half" onClose={() => setSheet('none')}>
          <div className="m-sheet-head">
            <span style={{ fontWeight: 600 }}>進捗を記録</span>
          </div>
          <div className="m-sheet-body">
            <div className="panel-row">
              <label htmlFor="m-page">読んだページ</label>
              <input
                id="m-page"
                className="input input-narrow"
                type="number"
                min={0}
                value={pageDraft}
                onChange={(e) => setPageDraft(e.target.value)}
                autoFocus
              />
              {book.total ? <span className="muted">/ {book.total}</span> : null}
            </div>
          </div>
          <div className="m-sheet-actions">
            <button
              type="button"
              className="btn btn-secondary"
              style={{ flex: 1 }}
              onClick={() => {
                onUpdate({ status: 'finished', page: book.total ?? book.page })
                setSheet('none')
              }}
            >
              読み終えた
            </button>
            <button
              type="button"
              className="btn btn-primary"
              style={{ flex: 1 }}
              onClick={saveProgress}
            >
              更新
            </button>
          </div>
        </Sheet>
      ) : null}

      {sheet === 'more' ? (
        <Sheet size="half" onClose={() => setSheet('none')}>
          <div className="m-sheet-body">
            <div className="m-rows">
              {book.status === 'unread' ? (
                <button
                  type="button"
                  className="m-row"
                  onClick={() => {
                    onUpdate({ status: 'reading' })
                    setSheet('none')
                  }}
                >
                  <i className="ph-duotone ph-book-open m-row-caret" />
                  <span className="m-row-main">
                    <span className="m-row-title">読み始める</span>
                  </span>
                </button>
              ) : null}
              {book.status === 'finished' ? (
                <button
                  type="button"
                  className="m-row"
                  onClick={() => {
                    onUpdate({ status: 'reading', page: 0, finished_on: null })
                    setSheet('none')
                  }}
                >
                  <i className="ph-duotone ph-arrows-clockwise m-row-caret" />
                  <span className="m-row-main">
                    <span className="m-row-title">もう一度読む</span>
                  </span>
                </button>
              ) : null}
              <button
                type="button"
                className="m-row"
                onClick={() => {
                  setSheet('none')
                  onDelete()
                }}
              >
                <i className="ph-duotone ph-x m-row-caret" />
                <span className="m-row-main">
                  <span className="m-row-title" style={{ color: 'var(--color-accent-2-700)' }}>
                    この本を削除
                  </span>
                </span>
              </button>
            </div>
          </div>
        </Sheet>
      ) : null}
    </div>
  )
}
