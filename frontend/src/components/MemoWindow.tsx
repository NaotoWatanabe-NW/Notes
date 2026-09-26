import { useEffect, useRef, useState } from 'react'
import type { Note } from '../api'
import { KIND_LABELS } from '../api'
import type { NoteFilter } from '../types'
import { Segmented } from './Segmented'

/** 記法タブの1行 */
export type SyntaxRow = {
  code: string
  label: string
  /** 見本の見た目 */
  style?: React.CSSProperties
  onInsert: () => void
}

type Props = {
  notes: Note[]
  syntax: SyntaxRow[]
  onInsertNote: (note: Note) => void
  onClose: () => void
}

const WIDTH = 320

/** 画面の外に出ないように位置を丸める */
function clamp(x: number, y: number, height: number) {
  return {
    x: Math.min(Math.max(8, x), Math.max(8, window.innerWidth - WIDTH - 8)),
    // 上部バー（56px）の下からは出さない
    y: Math.min(Math.max(64, y), Math.max(64, window.innerHeight - height - 8)),
  }
}

/**
 * 執筆中に引用・メモと Markdown の記法を見ながら、本文へ差し込むための小窓。
 * タイトルバーをつかんで動かせる。
 */
export function MemoWindow({ notes, syntax, onInsertNote, onClose }: Props) {
  // 初期位置は左下（デザイン #6a の指定: x40 y420）
  const [pos, setPos] = useState(() => clamp(40, 420, 420))
  const [minimized, setMinimized] = useState(false)
  const [tab, setTab] = useState<'notes' | 'syntax'>('notes')
  const [filter, setFilter] = useState<NoteFilter>(null)
  const dragRef = useRef<{ dx: number; dy: number } | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onMove(event: PointerEvent) {
      if (!dragRef.current) return
      const height = boxRef.current?.offsetHeight ?? 200
      setPos(
        clamp(
          event.clientX - dragRef.current.dx,
          event.clientY - dragRef.current.dy,
          height,
        ),
      )
    }
    function onUp() {
      dragRef.current = null
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [])

  const visible = filter ? notes.filter((note) => note.kind === filter) : notes

  return (
    <div
      ref={boxRef}
      className="memo-window"
      style={{ left: pos.x, top: pos.y, width: WIDTH }}
    >
      <div
        className="memo-bar"
        onPointerDown={(event) => {
          dragRef.current = { dx: event.clientX - pos.x, dy: event.clientY - pos.y }
        }}
      >
        <i className="ph-duotone ph-dots-six-vertical" />
        <span className="memo-bar-title">執筆の道具</span>
        <button
          type="button"
          aria-label={minimized ? '展開する' : '小さくする'}
          onClick={() => setMinimized((prev) => !prev)}
        >
          <i
            className={`ph-duotone ${minimized ? 'ph-arrows-out-simple' : 'ph-minus'}`}
          />
        </button>
        <button type="button" aria-label="閉じる" onClick={onClose}>
          <i className="ph-duotone ph-x" />
        </button>
      </div>

      {minimized ? null : (
        <>
          <div className="memo-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              className="memo-tab"
              aria-selected={tab === 'notes'}
              onClick={() => setTab('notes')}
            >
              メモ・引用 {notes.length}
            </button>
            <button
              type="button"
              role="tab"
              className="memo-tab"
              aria-selected={tab === 'syntax'}
              onClick={() => setTab('syntax')}
            >
              記法
            </button>
          </div>

          {tab === 'notes' ? (
            <>
              <div className="memo-filter">
                <Segmented
                  name="memo-window-filter"
                  value={filter ?? 'all'}
                  options={[
                    { value: 'all', label: 'すべて' },
                    { value: 'quote', label: '引用' },
                    { value: 'memo', label: 'メモ' },
                  ]}
                  onChange={(next) => setFilter(next === 'all' ? null : next)}
                />
              </div>

              <div className="memo-list">
                {visible.length === 0 ? (
                  <p className="palette-empty" style={{ fontSize: 13 }}>
                    この本にはまだ記録がありません。
                  </p>
                ) : (
                  visible.map((note) => (
                    <button
                      key={note.id}
                      type="button"
                      className="memo-item"
                      // mousedown を止めないと、押した瞬間に本文のカーソルが
                      // 外れて挿入先が分からなくなる
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => onInsertNote(note)}
                    >
                      <span
                        className={`memo-item-kind ${note.kind === 'quote' ? 'kind-quote' : 'kind-memo'}`}
                      >
                        {KIND_LABELS[note.kind]}
                        {note.page ? ` · p.${note.page}` : ''}
                      </span>
                      <span
                        className={`memo-item-text ${note.kind === 'quote' ? 'quote-styled' : ''}`}
                      >
                        {note.text}
                      </span>
                    </button>
                  ))
                )}
              </div>
            </>
          ) : (
            <div className="syntax-list">
              {syntax.map((row) => (
                <button
                  key={row.code}
                  type="button"
                  className="syntax-row"
                  onMouseDown={(event) => {
                    event.preventDefault()
                    row.onInsert()
                  }}
                >
                  <span className="syntax-code">{row.code}</span>
                  <span style={row.style}>{row.label}</span>
                </button>
              ))}
            </div>
          )}

          <div className="memo-foot">
            {tab === 'notes'
              ? 'クリックでカーソル位置に挿入 · ドラッグで移動'
              : 'クリックで挿入 · 太字・斜体は選択範囲を囲む'}
          </div>
        </>
      )}
    </div>
  )
}
