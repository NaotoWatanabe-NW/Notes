import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { BookDetail, Note, Recommend } from '../api'
import { RECOMMEND_LABELS } from '../api'
import { countCharacters, insertBlock, wrapInline } from '../markdownInsert'
import { Markdown } from './Markdown'
import type { SyntaxRow } from './MemoWindow'
import { MemoWindow } from './MemoWindow'
import { Segmented } from './Segmented'
import { Stars } from './Stars'

type Props = {
  book: BookDetail
  notes: Note[]
  /** 自動保存。書き続けている間、静かに保存するだけ */
  onSave: (markdown: string) => void
  /** 保存して執筆モードを閉じる */
  onClose: (markdown: string) => void
  onUpdateBook: (payload: { rating?: number | null; recommend?: Recommend }) => void
  /** ⌘K パレットが開いているときは、Esc をそちらに譲る */
  escActive: boolean
}

type View = 'split' | 'write' | 'read'

const VIEWS: { value: View; label: string }[] = [
  { value: 'split', label: '並べる' },
  { value: 'write', label: '書く' },
  { value: 'read', label: '読む' },
]

// 打つのをやめてからこれだけ経ったら保存する
const AUTOSAVE_MS = 1200

export function ReportEditor({
  book,
  notes,
  onSave,
  onClose,
  onUpdateBook,
  escActive,
}: Props) {
  const [text, setText] = useState(book.report_md ?? '')
  const [view, setView] = useState<View>('split')
  const [memoOpen, setMemoOpen] = useState(true)
  const [saved, setSaved] = useState(true)
  const sourceRef = useRef<HTMLTextAreaElement>(null)
  const previewRef = useRef<HTMLDivElement>(null)
  // 差し込み先。ボタンを押した瞬間に選択が外れるので覚えておく
  const range = useRef({ start: 0, end: 0 })

  // 本を切り替えたときだけ本文を入れ直す。打っている最中に上書きしない
  useEffect(() => {
    setText(book.report_md ?? '')
    setSaved(true)
  }, [book.id])

  // 自動保存。打つたびに投げると重いので、手が止まってから保存する
  useEffect(() => {
    if (saved) return
    const timer = window.setTimeout(() => {
      onSave(text)
      setSaved(true)
    }, AUTOSAVE_MS)
    return () => window.clearTimeout(timer)
  }, [text, saved, onSave])

  const characters = useMemo(() => countCharacters(text), [text])

  const rememberRange = useCallback(() => {
    const input = sourceRef.current
    if (input) range.current = { start: input.selectionStart, end: input.selectionEnd }
  }, [])

  /** 計算しておいた「次の本文と選択範囲」を textarea に反映する */
  const apply = useCallback(
    (result: { text: string; selectionStart: number; selectionEnd: number }) => {
      setText(result.text)
      setSaved(false)
      range.current = { start: result.selectionStart, end: result.selectionEnd }
      // setState の反映後にカーソルを置く
      requestAnimationFrame(() => {
        const input = sourceRef.current
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

  // 上部バーのツール（デザイン #6a の5つ）
  const tools = [
    { icon: 'ph-text-h-two', label: '見出し', title: '見出し', run: () => putBlock('## ') },
    {
      icon: 'ph-text-h-three',
      label: '章',
      title: '章の見出し',
      run: () => putBlock(`### 第◯章 · p.${page}`),
    },
    { icon: 'ph-quotes', label: '', title: '引用', run: () => putBlock(`> 「」 p.${page}`) },
    { icon: 'ph-list-bullets', label: '', title: '箇条書き', run: () => putBlock('- ') },
    {
      icon: 'ph-text-b',
      label: '',
      title: '太字',
      run: () => putInline('**', '**', '太字'),
    },
  ]

  // 記法タブの中身。見本は実際の書体・太さ・色で出す
  const syntax: SyntaxRow[] = [
    { code: '## 見出し', label: '見出し', style: { fontSize: 17, fontWeight: 600 }, onInsert: () => putBlock('## ') },
    {
      code: '### 章 · p.21',
      label: '章の見出し',
      style: { fontSize: 15, fontWeight: 600, color: 'var(--color-accent-700)' },
      onInsert: () => putBlock(`### 第◯章 · p.${page}`),
    },
    { code: '**太字**', label: '太字', style: { fontSize: 14, fontWeight: 600 }, onInsert: () => putInline('**', '**', '太字') },
    { code: '*斜体*', label: '斜体', style: { fontSize: 14, fontStyle: 'italic' }, onInsert: () => putInline('*', '*', '斜体') },
    { code: '~~取り消し~~', label: '取り消し線', style: { fontSize: 14, textDecoration: 'line-through' }, onInsert: () => putInline('~~', '~~', '取り消し') },
    {
      code: '> 引用 p.96',
      label: '「引用」',
      style: { fontSize: 14, fontStyle: 'italic', color: 'var(--color-accent-2-800)' },
      onInsert: () => putBlock(`> 「」 p.${page}`),
    },
    { code: '- 項目', label: '・ 箇条書き', style: { fontSize: 14 }, onInsert: () => putBlock('- ') },
    { code: '1. 項目', label: '1. 番号付き', style: { fontSize: 14 }, onInsert: () => putBlock('1. ') },
    { code: '- [ ] やること', label: '☐ チェックリスト', style: { fontSize: 14 }, onInsert: () => putBlock('- [ ] ') },
    {
      code: '[文字](URL)',
      label: 'リンク',
      style: { fontSize: 14, color: 'var(--color-accent-700)' },
      onInsert: () => putInline('[', '](https://)', 'リンク'),
    },
    { code: '`語句`', label: '語句を強調', style: { fontSize: 14 }, onInsert: () => putInline('`', '`', '語句') },
    { code: '---', label: '区切り（余白）', style: { fontSize: 14, color: 'var(--color-neutral-700)' }, onInsert: () => putBlock('---') },
  ]

  function insertNote(note: Note) {
    const where = note.page ? ` p.${note.page}` : ''
    putBlock(
      note.kind === 'quote'
        ? `> 「${note.text}」${where}`
        : `${note.text}${note.page ? `（p.${note.page}）` : ''}`,
    )
  }

  /** 左のスクロール位置に合わせて右も動かす（「並べる」のときだけ） */
  function syncScroll(event: React.UIEvent<HTMLTextAreaElement>) {
    if (view !== 'split') return
    const source = event.currentTarget
    const preview = previewRef.current
    if (!preview) return
    const ratio =
      source.scrollTop / Math.max(source.scrollHeight - source.clientHeight, 1)
    preview.scrollTop = ratio * (preview.scrollHeight - preview.clientHeight)
  }

  const close = useCallback(() => onClose(text), [onClose, text])

  // Esc で保存して閉じる（パレットが開いているときはそちらが優先）
  useEffect(() => {
    if (!escActive) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        close()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [close, escActive])

  return (
    <div className="report">
      {/* ── 上部バー ── */}
      <div className="report-bar">
        <button type="button" className="btn btn-ghost" onClick={close}>
          <i className="ph-duotone ph-arrow-left" />
          本に戻る
        </button>
        <span className="report-bar-title">{book.title}</span>

        <span className="report-tools">
          {tools.map((tool) => (
            <button
              key={tool.title}
              type="button"
              className="btn btn-ghost"
              title={tool.title}
              // カーソルを保ったまま差し込む
              onMouseDown={(event) => {
                event.preventDefault()
                tool.run()
              }}
            >
              <i className={`ph-duotone ${tool.icon}`} style={{ fontSize: 18 }} />
              {tool.label}
            </button>
          ))}
        </span>

        <span className="report-spacer" />
        <span className="report-status">
          {characters}字 · {saved ? '自動保存済み' : '保存中…'}
        </span>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => setMemoOpen((prev) => !prev)}
        >
          <i className="ph-duotone ph-cards" style={{ fontSize: 17 }} />
          メモ窓
        </button>
        <Segmented name="report-view" value={view} options={VIEWS} onChange={setView} />
      </div>

      {/* ── 本体 ── */}
      <div className="report-body" data-view={view}>
        {view !== 'read' ? (
          <div className="report-source">
            <textarea
              ref={sourceRef}
              value={text}
              spellCheck={false}
              placeholder={'## 要約\n\n読んで考えたことを書く。\n\n> 引用はメモ窓から差し込めます'}
              onChange={(e) => {
                setText(e.target.value)
                setSaved(false)
                range.current = {
                  start: e.target.selectionStart,
                  end: e.target.selectionEnd,
                }
              }}
              onScroll={syncScroll}
              onKeyUp={rememberRange}
              onClick={rememberRange}
              onSelect={rememberRange}
              onBlur={rememberRange}
            />
          </div>
        ) : null}

        {view !== 'write' ? (
          <div className="report-preview" ref={previewRef}>
            <div className="report-sheet">
              <span className="report-kicker">読書レポート</span>
              <h1 className="report-title">{book.title}</h1>

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
                  name="recommend"
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
                <p className="muted" style={{ fontSize: 14 }}>
                  左に書くと、ここに仕上がりが出ます。
                </p>
              )}
            </div>
          </div>
        ) : null}
      </div>

      {memoOpen ? (
        <MemoWindow
          notes={notes}
          syntax={syntax}
          onInsertNote={insertNote}
          onClose={() => setMemoOpen(false)}
        />
      ) : null}
    </div>
  )
}
