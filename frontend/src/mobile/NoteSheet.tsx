import { useState } from 'react'
import type { NoteCreate, NoteKind } from '../api'
import { Segmented } from '../components/Segmented'
import { Sheet } from './Sheet'

type Props = {
  onSave: (payload: NoteCreate) => Promise<void>
  onClose: () => void
}

/**
 * メモを書くモーダルシート（デザイン 1d）。
 * 旧案にあった「感想」タブは廃止。感想はレポートに書く。
 *
 * 「メモを書く」から開くので **メモで始める**（PC版の記録パネルと同じ理由）。
 */
export function NoteSheet({ onSave, onClose }: Props) {
  const [kind, setKind] = useState<NoteKind>('memo')
  // ページは空で開く。電子書籍だと表示設定でページが変わるので、
  // 進捗のページを既定で入れると当てにならない数字が残る
  const [pageText, setPageText] = useState('')
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
          placeholder="ページ（任意）"
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

      {/* 「自分のメモ」だけ書いて保存できないときに、理由が分かるようにする */}
      {!text.trim() && memo.trim() ? (
        <p className="muted" style={{ fontSize: 12, margin: '0 16px' }}>
          引用の本文を入れると保存できます。メモだけ残すなら「メモ」に切り替えてください
        </p>
      ) : null}

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
