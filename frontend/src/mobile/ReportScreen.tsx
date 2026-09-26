import { useCallback, useEffect, useRef, useState } from 'react'
import type { BookDetail, Note, Recommend } from '../api'
import { RECOMMEND_LABELS } from '../api'
import { Markdown } from '../components/Markdown'
import { Segmented } from '../components/Segmented'
import { Stars } from '../components/Stars'
import { countCharacters, insertBlock, wrapInline } from '../markdownInsert'
import { Sheet } from './Sheet'

type Props = {
  book: BookDetail
  notes: Note[]
  onSave: (markdown: string) => void
  onClose: (markdown: string) => void
  onUpdateBook: (payload: { rating?: number | null; recommend?: Recommend }) => void
}

type View = 'write' | 'read'

// 打つのをやめてからこれだけ経ったら保存する
const AUTOSAVE_MS = 1200

/** 7f レポート（Markdown）。PC版の 6a を1列に畳んだもの */
export function ReportScreen({ book, notes, onSave, onClose, onUpdateBook }: Props) {
  const [text, setText] = useState(book.report_md ?? '')
  const [view, setView] = useState<View>('write')
  const [sheet, setSheet] = useState<'none' | 'half' | 'tall'>('none')
  const [tab, setTab] = useState<'notes' | 'syntax'>('notes')
  const [saved, setSaved] = useState(true)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const range = useRef({ start: 0, end: 0 })

  useEffect(() => {
    setText(book.report_md ?? '')
    setSaved(true)
  }, [book.id])

  // 自動保存。手が止まってから書き込む
  useEffect(() => {
    if (saved) return
    const timer = window.setTimeout(() => {
      onSave(text)
      setSaved(true)
    }, AUTOSAVE_MS)
    return () => window.clearTimeout(timer)
  }, [text, saved, onSave])

  const rememberRange = useCallback(() => {
    const input = inputRef.current
    if (input) range.current = { start: input.selectionStart, end: input.selectionEnd }
  }, [])

  const apply = useCallback(
    (result: { text: string; selectionStart: number; selectionEnd: number }) => {
      setText(result.text)
      setSaved(false)
      range.current = { start: result.selectionStart, end: result.selectionEnd }
      requestAnimationFrame(() => {
        const input = inputRef.current
        input?.focus()
        input?.setSelectionRange(result.selectionStart, result.selectionEnd)
      })
    },
    [],
  )

  const putBlock = useCallback(
    (block: string) =>
      apply(insertBlock(text, range.current.start, range.current.end, block)),
    [apply, text],
  )
  const putInline = useCallback(
    (open: string, close: string, placeholder: string) =>
      apply(
        wrapInline(text, range.current.start, range.current.end, open, close, placeholder),
      ),
    [apply, text],
  )

  const page = book.page || 1

  /** シートから差し込んだら、そのままシートを閉じて本文に戻る（デザインの指定） */
  function insertAndClose(run: () => void) {
    run()
    setSheet('none')
  }

  const syntax: { code: string; label: string; style?: React.CSSProperties; run: () => void }[] = [
    { code: '## 見出し', label: '見出し', style: { fontSize: 17, fontWeight: 600 }, run: () => putBlock('## ') },
    { code: '### 章 · p.21', label: '章の見出し', style: { fontSize: 15, fontWeight: 600, color: 'var(--color-accent-700)' }, run: () => putBlock(`### 第◯章 · p.${page}`) },
    { code: '**太字**', label: '太字', style: { fontSize: 14, fontWeight: 600 }, run: () => putInline('**', '**', '太字') },
    { code: '> 引用 p.96', label: '「引用」', style: { fontSize: 14, fontStyle: 'italic', color: 'var(--color-accent-2-800)' }, run: () => putBlock(`> 「」 p.${page}`) },
    { code: '- 項目', label: '・ 箇条書き', style: { fontSize: 14 }, run: () => putBlock('- ') },
    { code: '- [ ] やること', label: '☐ チェックリスト', style: { fontSize: 14 }, run: () => putBlock('- [ ] ') },
    { code: '*斜体*', label: '斜体', style: { fontSize: 14, fontStyle: 'italic' }, run: () => putInline('*', '*', '斜体') },
    { code: '~~取り消し~~', label: '取り消し線', style: { fontSize: 14, textDecoration: 'line-through' }, run: () => putInline('~~', '~~', '取り消し') },
    { code: '1. 項目', label: '1. 番号付き', style: { fontSize: 14 }, run: () => putBlock('1. ') },
    { code: '`語句`', label: '語句を強調', style: { fontSize: 14 }, run: () => putInline('`', '`', '語句') },
    { code: '[文字](URL)', label: 'リンク', style: { fontSize: 14, color: 'var(--color-accent-700)' }, run: () => putInline('[', '](https://)', 'リンク') },
    { code: '---', label: '区切り（余白）', style: { fontSize: 14, color: 'var(--color-neutral-700)' }, run: () => putBlock('---') },
  ]

  return (
    <div className="m-report">
      <div className="m-report-bar">
        <button
          type="button"
          className="m-icon-btn"
          aria-label="戻る"
          onClick={() => onClose(text)}
        >
          <i className="ph-duotone ph-caret-left" />
        </button>
        <span className="m-report-bar-title">
          {book.title} · {countCharacters(text)}字
        </span>
        <Segmented
          name="m-report-view"
          value={view}
          options={[
            { value: 'write', label: '書く' },
            { value: 'read', label: '読む' },
          ]}
          onChange={setView}
        />
        <button type="button" className="btn btn-ghost" onClick={() => onClose(text)}>
          完了
        </button>
      </div>

      <div className="m-report-body">
        {view === 'write' ? (
          <textarea
            ref={inputRef}
            value={text}
            spellCheck={false}
            placeholder={'## 要約\n\n読んで考えたことを書く。'}
            onChange={(e) => {
              setText(e.target.value)
              setSaved(false)
              range.current = {
                start: e.target.selectionStart,
                end: e.target.selectionEnd,
              }
            }}
            onKeyUp={rememberRange}
            onClick={rememberRange}
            onSelect={rememberRange}
            onBlur={rememberRange}
          />
        ) : (
          <div className="m-report-read">
            <span className="report-kicker">読書レポート</span>
            <h1 className="report-title" style={{ fontSize: 28 }}>
              {book.title}
            </h1>
            <div className="report-rule">
              <span>{book.author ?? '著者不明'}</span>
              {book.total ? (
                <span>
                  p.{book.page} / {book.total}
                </span>
              ) : null}
              <Stars
                value={book.rating}
                size={16}
                onChange={(rating) => onUpdateBook({ rating })}
              />
              <Segmented
                name="m-recommend"
                value={book.recommend ?? 'self'}
                options={(Object.keys(RECOMMEND_LABELS) as Recommend[]).map((key) => ({
                  value: key,
                  label: RECOMMEND_LABELS[key],
                }))}
                onChange={(recommend) => onUpdateBook({ recommend })}
              />
            </div>
            {text.trim() ? (
              <Markdown>{text}</Markdown>
            ) : (
              <p className="m-empty">「書く」に入力すると、ここに仕上がりが出ます。</p>
            )}
          </div>
        )}
      </div>

      {view === 'write' ? (
        <div className="m-accessory">
          <button
            type="button"
            className="btn btn-primary"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => setSheet('half')}
          >
            <i className="ph-duotone ph-cards" />
            メモ・記法
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            aria-label="見出し"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => putBlock('## ')}
          >
            <i className="ph-duotone ph-text-h" style={{ fontSize: 20 }} />
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => putBlock(`### 第◯章 · p.${page}`)}
          >
            <i className="ph-duotone ph-bookmark-simple" style={{ fontSize: 18 }} />
            p.{page}
          </button>
        </div>
      ) : null}

      {sheet !== 'none' ? (
        <Sheet
          size={sheet}
          onClose={() => setSheet('none')}
          onGrab={() => setSheet(sheet === 'half' ? 'tall' : 'half')}
        >
          <div className="m-sheet-head">
            <Segmented
              name="m-sheet-tab"
              value={tab}
              options={[
                { value: 'notes', label: `メモ・引用 ${notes.length}` },
                { value: 'syntax', label: '記法' },
              ]}
              onChange={setTab}
            />
            <button
              type="button"
              className="m-icon-btn"
              aria-label="閉じる"
              onClick={() => setSheet('none')}
            >
              <i className="ph-duotone ph-x" />
            </button>
          </div>

          <div className="m-sheet-body">
            {tab === 'notes' ? (
              notes.length === 0 ? (
                <p className="m-empty">この本にはまだ記録がありません。</p>
              ) : (
                <div className="m-rows">
                  {notes.map((note) => (
                    <button
                      key={note.id}
                      type="button"
                      className="m-note-item"
                      style={{ padding: '10px 0' }}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() =>
                        insertAndClose(() =>
                          putBlock(
                            note.kind === 'quote'
                              ? `> 「${note.text}」${note.page ? ` p.${note.page}` : ''}`
                              : `${note.text}${note.page ? `（p.${note.page}）` : ''}`,
                          ),
                        )
                      }
                    >
                      <span
                        className={`m-note-kind ${note.kind === 'quote' ? 'kind-quote' : 'kind-memo'}`}
                      >
                        {note.kind === 'quote' ? '引用' : 'メモ'}
                        {note.page ? ` · p.${note.page}` : ''}
                      </span>
                      <span
                        className={`m-note-text ${note.kind === 'quote' ? 'quote-styled' : ''}`}
                      >
                        {note.text}
                      </span>
                    </button>
                  ))}
                </div>
              )
            ) : (
              <div className="syntax-list" style={{ maxHeight: 'none' }}>
                {syntax.map((row) => (
                  <button
                    key={row.code}
                    type="button"
                    className="syntax-row"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => insertAndClose(row.run)}
                  >
                    <span className="syntax-code">{row.code}</span>
                    <span style={row.style}>{row.label}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="m-sheet-foot">
            タップでカーソル位置に挿入し、シートを閉じます
          </div>
        </Sheet>
      ) : null}
    </div>
  )
}
