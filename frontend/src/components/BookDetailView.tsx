import { useEffect, useState } from 'react'
import type { BookDetail, BookUpdate, Note, NoteCreate, NoteKind } from '../api'
import { KIND_LABELS, RECOMMEND_LABELS, STATUS_LABELS } from '../api'
import { CoverPicker } from './CoverPicker'
import { Markdown } from './Markdown'
import { Segmented } from './Segmented'
import { Stars } from './Stars'
import { TagEditor } from './TagEditor'

type Props = {
  book: BookDetail
  notes: Note[]
  tagSuggestions: string[]
  onUpdate: (payload: BookUpdate) => void
  onAddNote: (payload: NoteCreate) => Promise<void>
  onUpdateNote: (noteId: number, payload: Partial<NoteCreate>) => void
  onDeleteNote: (note: Note) => void
  onWriteReport: () => void
  onDelete: () => void
  /** 表紙を入れ替えたあと、データを取り直してもらう */
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

const EMPTY_DRAFT = { kind: 'quote' as NoteKind, page: '', text: '', memo: '' }

export function BookDetailView({
  book,
  notes,
  tagSuggestions,
  onUpdate,
  onAddNote,
  onUpdateNote,
  onDeleteNote,
  onWriteReport,
  onDelete,
  onReload,
  onError,
}: Props) {
  const [panel, setPanel] = useState<'none' | 'note' | 'progress'>('none')
  const [draft, setDraft] = useState(EMPTY_DRAFT)
  const [pageDraft, setPageDraft] = useState('')
  const [editingNote, setEditingNote] = useState<number | null>(null)
  const [noteEdit, setNoteEdit] = useState({ text: '', memo: '' })

  // 別の本に切り替えたら編集中の状態は捨てる
  useEffect(() => {
    setPanel('none')
    setDraft(EMPTY_DRAFT)
    setPageDraft(String(book.page || ''))
    setEditingNote(null)
  }, [book.id, book.page])

  function openNotePanel(kind: NoteKind) {
    setDraft({ ...EMPTY_DRAFT, kind, page: book.page ? String(book.page) : '' })
    setPanel('note')
  }

  async function saveNote() {
    if (!draft.text.trim()) return
    await onAddNote({
      kind: draft.kind,
      text: draft.text.trim(),
      page: draft.page ? Number(draft.page) : null,
      memo: draft.kind === 'quote' && draft.memo.trim() ? draft.memo.trim() : null,
    })
    setDraft(EMPTY_DRAFT)
    setPanel('none')
  }

  function saveProgress() {
    const next = Number(pageDraft)
    if (!Number.isFinite(next) || next < 0) return
    // 最後のページまで読んだらサーバー側が状態を「読了」に変える
    onUpdate({ page: next, status: book.status === 'unread' ? 'reading' : undefined })
    setPanel('none')
  }

  function finishNow() {
    onUpdate({ status: 'finished', page: book.total ?? book.page })
    setPanel('none')
  }

  function readAgain() {
    // 進捗を 0 に戻して読書中にする。読了の記録は残るので回数が積み上がる
    onUpdate({ status: 'reading', page: 0, finished_on: null })
    setPanel('none')
  }

  return (
    <div className="detail">
      {/* ── ヘッダー ── */}
      <header className="book-head">
        <CoverPicker
          bookId={book.id}
          title={book.title}
          author={book.author}
          coverUrl={book.cover_url}
          onChanged={onReload}
          onError={onError}
        />
        <div className="book-head-main">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span className={`tag ${STATUS_TAG[book.status]}`}>
              {STATUS_LABELS[book.status]}
            </span>
            {book.read_count > 1 ? (
              <span className="tag tag-neutral">{book.read_count}回読了</span>
            ) : null}
            {book.recommend ? (
              <span className="list-aside">{RECOMMEND_LABELS[book.recommend]}</span>
            ) : null}
            <button
              type="button"
              className="btn btn-ghost"
              style={{ marginLeft: 'auto', fontSize: 12 }}
              onClick={onDelete}
            >
              削除
            </button>
          </div>
          <h1 className="book-title">{book.title}</h1>
          <p className="book-byline" style={{ margin: 0 }}>
            {[book.author, book.publisher].filter(Boolean).join(' · ') || '著者不明'}
          </p>
          {book.status === 'finished' ? (
            <Stars value={book.rating} onChange={(rating) => onUpdate({ rating })} />
          ) : null}
          <TagEditor
            tags={book.tags}
            suggestions={tagSuggestions}
            onChange={(tags) => onUpdate({ tags })}
          />
        </div>
      </header>

      {/* ── 進捗（読書中のみ） ── */}
      {book.status === 'reading' && book.total ? (
        <section className="stack">
          <div className="progress-line">
            <span>
              p.{book.page} / {book.total}
            </span>
            <span>
              {book.started_on ? `${shortDate(book.started_on)}から · ` : ''}
              {book.progress}%
            </span>
          </div>
          <div className="progress-bar">
            <span style={{ width: `${book.progress ?? 0}%` }} />
          </div>
        </section>
      ) : null}

      {/* ── 読了の履歴 ── */}
      {book.readings.length > 0 ? (
        <section className="stack" style={{ gap: 8 }}>
          <span className="section-aside">
            読み終えた記録 {book.readings.length}回
          </span>
          <ul className="readings">
            {book.readings.map((reading, index) => (
              <li key={reading.id} className="reading-chip">
                {book.readings.length - index}回目 · {reading.finished_on}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* ── 操作ボタン（状態で出し分ける） ── */}
      <div className="actions">
        {book.status === 'unread' ? (
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => onUpdate({ status: 'reading' })}
          >
            <i className="ph-duotone ph-book-open" />
            読み始める
          </button>
        ) : null}

        {book.status === 'reading' ? (
          <>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => openNotePanel('quote')}
            >
              <i className="ph-duotone ph-pencil-simple-line" />
              メモを書く
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setPanel('progress')}
            >
              進捗を記録
            </button>
            <button type="button" className="btn btn-secondary" onClick={onWriteReport}>
              <i className="ph-duotone ph-article" />
              レポートを書く
            </button>
          </>
        ) : null}

        {book.status === 'finished' ? (
          <>
            <button type="button" className="btn btn-primary" onClick={onWriteReport}>
              <i className="ph-duotone ph-article" />
              {book.report_md ? 'レポートを直す' : 'レポートを書く'}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => openNotePanel('quote')}
            >
              メモを追加
            </button>
            <button type="button" className="btn btn-secondary" onClick={readAgain}>
              <i className="ph-duotone ph-arrows-clockwise" />
              もう一度読む
            </button>
          </>
        ) : null}
      </div>

      {/* ── インライン編集: 進捗 ── */}
      {panel === 'progress' ? (
        <div className="panel">
          <div className="panel-row">
            <label htmlFor="page-input">読んだページ</label>
            <input
              id="page-input"
              className="input input-narrow"
              type="number"
              min={0}
              value={pageDraft}
              onChange={(e) => setPageDraft(e.target.value)}
            />
            {book.total ? <span className="muted">/ {book.total}</span> : null}
          </div>
          <div className="panel-actions">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setPanel('none')}
            >
              キャンセル
            </button>
            {/* 最後まで読んだときに、わざわざ総ページ数を打たなくて済むように */}
            <button type="button" className="btn btn-secondary" onClick={finishNow}>
              <i className="ph-duotone ph-check-circle" />
              読み終えた
            </button>
            <button type="button" className="btn btn-primary" onClick={saveProgress}>
              更新
            </button>
          </div>
        </div>
      ) : null}

      {/* ── インライン編集: 引用・メモ ── */}
      {panel === 'note' ? (
        <div className="panel">
          <div className="panel-row">
            <Segmented
              name="note-kind"
              value={draft.kind}
              options={[
                { value: 'quote', label: '引用' },
                { value: 'memo', label: 'メモ' },
              ]}
              onChange={(kind) => setDraft({ ...draft, kind })}
            />
            <input
              className="input input-page"
              type="number"
              min={1}
              placeholder="ページ"
              value={draft.page}
              onChange={(e) => setDraft({ ...draft, page: e.target.value })}
            />
          </div>
          <textarea
            className={`input ${draft.kind === 'quote' ? 'quote-styled' : ''}`}
            style={{ fontSize: 16, lineHeight: 1.7, minHeight: 96 }}
            placeholder={
              draft.kind === 'quote' ? '本文から書き写す' : 'そのとき考えたこと'
            }
            value={draft.text}
            onChange={(e) => setDraft({ ...draft, text: e.target.value })}
          />
          {draft.kind === 'quote' ? (
            <input
              className="input"
              placeholder="自分のメモ（任意）"
              value={draft.memo}
              onChange={(e) => setDraft({ ...draft, memo: e.target.value })}
            />
          ) : null}
          <div className="panel-actions">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setPanel('none')}
            >
              キャンセル
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!draft.text.trim()}
              onClick={saveNote}
            >
              保存
            </button>
          </div>
        </div>
      ) : null}

      {/* ── 記録一覧 ── */}
      <section className="stack" style={{ gap: 20 }}>
        <div className="section-head">
          <h2 className="section-title">メモ・引用 {notes.length}件</h2>
          {notes.length > 0 ? <span className="section-aside">ページ順</span> : null}
        </div>

        {notes.length === 0 ? (
          <p className="muted" style={{ fontSize: 15, margin: 0 }}>
            まだ記録がありません。読んだページの引用や、そのとき考えたことを残せます。
          </p>
        ) : (
          <ul className="records">
            {notes.map((note) => (
              <li key={note.id} className="record">
                <div className="section-head">
                  <span
                    className={`record-kind ${note.kind === 'quote' ? 'kind-quote' : 'kind-memo'}`}
                  >
                    {KIND_LABELS[note.kind]}
                    {note.page ? ` · p.${note.page}` : ''}
                  </span>
                  <span className="record-tools">
                    <button
                      type="button"
                      className="btn btn-ghost"
                      style={{ fontSize: 12 }}
                      onClick={() => {
                        setEditingNote(note.id)
                        setNoteEdit({ text: note.text, memo: note.memo ?? '' })
                      }}
                    >
                      編集
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      style={{ fontSize: 12 }}
                      onClick={() => onDeleteNote(note)}
                    >
                      削除
                    </button>
                  </span>
                </div>

                {editingNote === note.id ? (
                  <div className="stack">
                    <textarea
                      className="input"
                      style={{ fontSize: 16, lineHeight: 1.7, minHeight: 96 }}
                      value={noteEdit.text}
                      onChange={(e) => setNoteEdit({ ...noteEdit, text: e.target.value })}
                    />
                    {note.kind === 'quote' ? (
                      <input
                        className="input"
                        placeholder="自分のメモ（任意）"
                        value={noteEdit.memo}
                        onChange={(e) =>
                          setNoteEdit({ ...noteEdit, memo: e.target.value })
                        }
                      />
                    ) : null}
                    <div className="panel-actions">
                      <button
                        type="button"
                        className="btn btn-ghost"
                        onClick={() => setEditingNote(null)}
                      >
                        やめる
                      </button>
                      <button
                        type="button"
                        className="btn btn-primary"
                        disabled={!noteEdit.text.trim()}
                        onClick={() => {
                          onUpdateNote(note.id, {
                            text: noteEdit.text.trim(),
                            memo: noteEdit.memo.trim() || null,
                          })
                          setEditingNote(null)
                        }}
                      >
                        保存
                      </button>
                    </div>
                  </div>
                ) : note.kind === 'quote' ? (
                  <>
                    <p className="record-quote quote-styled">「{note.text}」</p>
                    {note.memo ? <p className="record-sub">{note.memo}</p> : null}
                  </>
                ) : (
                  <p className="record-memo">{note.text}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ── 読書レポート（本の下部に出す） ── */}
      {book.report_md ? (
        <section className="stack" style={{ gap: 16 }}>
          <div className="section-head">
            <h2 className="section-title">読書レポート</h2>
            <button
              type="button"
              className="btn btn-ghost"
              style={{ fontSize: 12 }}
              onClick={onWriteReport}
            >
              編集
            </button>
          </div>
          <Markdown>{book.report_md}</Markdown>
        </section>
      ) : null}
    </div>
  )
}
