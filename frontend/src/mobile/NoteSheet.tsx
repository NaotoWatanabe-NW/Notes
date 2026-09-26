import { useState } from 'react'
import type { NoteCreate, NoteKind } from '../api'
import { Segmented } from '../components/Segmented'
import { Sheet } from './Sheet'

type Props = {
  /** 記録するときの既定のページ（いま読んでいるところ） */
  page: number
  onSave: (payload: NoteCreate) => Promise<void>
  onClose: () => void
}

/**
 * メモを書くモーダルシート（デザイン 1d）。
 * 旧案にあった「感想」タブは廃止。感想はレポートに書く。
 */
export function NoteSheet({ page, onSave, onClose }: Props) {
  const [kind, setKind] = useState<NoteKind>('quote')
  const [pageText, setPageText] = useState(page ? String(page) : '')
  const [text, setText] = useState('')
  const [memo, setMemo] = useState('')
  const [saving, setSaving] = useState(false)

  async function save() {
    if (!text.trim() || saving) return
    setSaving(true)
    try {
      await onSave({
        kind,
        text: text.trim(),
        page: pageText ? Number(pageText) : null,
        memo: kind === 'quote' && memo.trim() ? memo.trim() : null,
      })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet size="tall" onClose={onClose}>
      <div className="m-sheet-head">
        <Segmented
          name="m-note-kind"
          value={kind}
          options={[
            { value: 'quote', label: '引用' },
            { value: 'memo', label: 'メモ' },
          ]}
          onChange={setKind}
        />
        <input
          className="input input-page"
          type="number"
          min={1}
          placeholder="ページ"
          value={pageText}
          onChange={(e) => setPageText(e.target.value)}
        />
        <button type="button" className="m-icon-btn" aria-label="閉じる" onClick={onClose}>
          <i className="ph-duotone ph-x" />
        </button>
      </div>

      <div className="m-sheet-body">
        <textarea
          className={`input ${kind === 'quote' ? 'quote-styled' : ''}`}
          style={{ fontSize: 16, lineHeight: 1.7, minHeight: 140 }}
          placeholder={kind === 'quote' ? '本文から書き写す' : 'そのとき考えたこと'}
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoFocus
        />
        {kind === 'quote' ? (
          <input
            className="input"
            style={{ marginTop: 10 }}
            placeholder="自分のメモ（任意）"
            value={memo}
            onChange={(e) => setMemo(e.target.value)}
          />
        ) : null}
      </div>

      <div className="m-sheet-actions">
        <button
          type="button"
          className="btn btn-secondary"
          style={{ flex: 1 }}
          onClick={onClose}
        >
          やめる
        </button>
        <button
          type="button"
          className="btn btn-primary"
          style={{ flex: 2 }}
          disabled={!text.trim() || saving}
          onClick={save}
        >
          {saving ? '保存中…' : '保存'}
        </button>
      </div>
    </Sheet>
  )
}
