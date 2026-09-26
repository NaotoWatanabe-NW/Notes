import { useEffect, useState } from 'react'
import type { Book, NoteWithBook, Settings, SettingsUpdate } from '../api'
import * as api from '../api'
import { SORT_LABELS } from '../api'
import { Segmented } from '../components/Segmented'
import { exportCsv, exportMarkdown } from '../export'

type Props = {
  settings: Settings
  books: Book[]
  notes: NoteWithBook[]
  onChange: (payload: SettingsUpdate) => void
  onBack: () => void
}

/** 設定（Web の C-4 と同じ項目を1画面に縦積み） */
export function SettingsScreen({ settings, books, notes, onChange, onBack }: Props) {
  const [goal, setGoal] = useState(String(settings.yearly_goal))
  const [finished, setFinished] = useState<number | null>(null)

  useEffect(() => {
    setGoal(String(settings.yearly_goal))
  }, [settings.yearly_goal])

  useEffect(() => {
    api
      .getReview(String(new Date().getFullYear()))
      .then((review) => setFinished(review.finished_count))
      .catch(() => undefined)
  }, [books])

  const remaining = finished === null ? null : Math.max(0, settings.yearly_goal - finished)

  return (
    <div className="m-screen">
      <div className="m-nav">
        <button type="button" className="m-back" onClick={onBack}>
          <i className="ph-duotone ph-caret-left" />
          本棚
        </button>
      </div>
      <h1 className="m-title" style={{ marginBottom: 24 }}>
        設定
      </h1>

      <section className="stack" style={{ gap: 8, marginBottom: 28 }}>
        <span className="m-section-label">読書目標</span>
        <input
          className="input"
          style={{ maxWidth: 160, fontSize: 18, height: 44 }}
          type="number"
          min={1}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onBlur={() => {
            const next = Number(goal)
            if (Number.isInteger(next) && next >= 1 && next !== settings.yearly_goal) {
              onChange({ yearly_goal: next })
            } else {
              setGoal(String(settings.yearly_goal))
            }
          }}
        />
        {finished !== null ? (
          <p className="m-kicker" style={{ margin: 0 }}>
            {remaining === 0
              ? `今年はここまで${finished}冊読了。目標を達成しています。`
              : `今年はここまで${finished}冊読了。目標まであと${remaining}冊。`}
          </p>
        ) : null}
      </section>

      <section className="stack" style={{ gap: 8, marginBottom: 20 }}>
        <span className="m-section-label">本棚の並び順</span>
        <div className="m-seg">
          <Segmented
            name="m-sort"
            value={settings.sort}
            options={(Object.keys(SORT_LABELS) as (keyof typeof SORT_LABELS)[]).map(
              (key) => ({ value: key, label: SORT_LABELS[key] }),
            )}
            onChange={(sort) => onChange({ sort })}
          />
        </div>
      </section>

      <section className="stack" style={{ gap: 8, marginBottom: 28 }}>
        <span className="m-section-label">引用の書体</span>
        <div className="m-seg">
          <Segmented
            name="m-quote-style"
            value={settings.quote_style}
            options={[
              { value: 'italic', label: 'イタリック' },
              { value: 'plain', label: '標準' },
            ]}
            onChange={(quote_style) => onChange({ quote_style })}
          />
        </div>
        <p className="quote-styled muted" style={{ fontSize: 15, margin: 0 }}>
          「これは引用の見え方の例です」
        </p>
      </section>

      <section className="stack" style={{ gap: 10, marginBottom: 28 }}>
        <span className="m-section-label">データ</span>
        <p className="m-kicker" style={{ margin: 0 }}>
          本 {books.length}冊 / 記録 {notes.length}件
        </p>
        <button
          type="button"
          className="btn btn-secondary btn-block"
          style={{ height: 44 }}
          onClick={() => exportMarkdown(books, notes)}
        >
          <i className="ph-duotone ph-file-text" />
          Markdown で書き出す
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-block"
          style={{ height: 44 }}
          onClick={() => exportCsv(books)}
        >
          <i className="ph-duotone ph-file-csv" />
          CSV で書き出す
        </button>
      </section>

      <section className="stack" style={{ gap: 8 }}>
        <span className="m-section-label">アカウント</span>
        <p className="muted" style={{ fontSize: 14, lineHeight: 1.8, margin: 0 }}>
          このアプリはログインを持ちません。自分のPCで動かし、Tailscale の中からだけ
          開ける前提だからです。データは <code>reading.db</code> の1ファイルにまとまっています。
        </p>
      </section>
    </div>
  )
}
