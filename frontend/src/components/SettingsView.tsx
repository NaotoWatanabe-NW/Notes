import { useEffect, useState } from 'react'
import type { Book, NoteWithBook, Review, Settings, SettingsUpdate } from '../api'
import { SORT_LABELS } from '../api'
import { exportCsv, exportMarkdown } from '../export'
import type { SettingsSection } from './SettingsPane'
import { Segmented } from './Segmented'

type Props = {
  section: SettingsSection
  settings: Settings
  yearReview: Review | null
  books: Book[]
  notes: NoteWithBook[]
  onChange: (payload: SettingsUpdate) => void
}

/** 「今年はここまで42冊読了。目標まであと8冊、月に3冊のペースです。」 */
function goalSentence(review: Review | null, goal: number): string {
  if (review === null) return `目標は年に${goal}冊です。`
  const remaining = Math.max(0, goal - review.finished_count)
  if (remaining === 0) {
    return `今年はここまで${review.finished_count}冊読了。目標を達成しています。`
  }
  const monthsLeft = Math.max(1, 12 - new Date().getMonth())
  const pace = Math.ceil(remaining / monthsLeft)
  return `今年はここまで${review.finished_count}冊読了。目標まであと${remaining}冊、月に${pace}冊のペースです。`
}

export function SettingsView({
  section,
  settings,
  yearReview,
  books,
  notes,
  onChange,
}: Props) {
  const [goal, setGoal] = useState(String(settings.yearly_goal))

  useEffect(() => {
    setGoal(String(settings.yearly_goal))
  }, [settings.yearly_goal])

  if (section === 'goal') {
    return (
      <div className="detail">
        <h1 className="section-title">読書目標</h1>
        <div className="stack">
          <input
            className="input"
            style={{ maxWidth: 200, fontSize: 18 }}
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
          <p className="muted" style={{ margin: 0, fontSize: 14 }}>
            {goalSentence(yearReview, settings.yearly_goal)}
          </p>
        </div>
      </div>
    )
  }

  if (section === 'display') {
    return (
      <div className="detail">
        <h1 className="section-title">表示</h1>
        <div className="stack" style={{ gap: 8 }}>
          <span className="section-aside">本棚の並び順</span>
          <Segmented
            name="sort"
            value={settings.sort}
            options={(Object.keys(SORT_LABELS) as (keyof typeof SORT_LABELS)[]).map(
              (key) => ({ value: key, label: SORT_LABELS[key] }),
            )}
            onChange={(sort) => onChange({ sort })}
          />
        </div>
        <div className="stack" style={{ gap: 8 }}>
          <span className="section-aside">引用の書体</span>
          <Segmented
            name="quote-style"
            value={settings.quote_style}
            options={[
              { value: 'italic', label: 'イタリック' },
              { value: 'plain', label: '標準' },
            ]}
            onChange={(quote_style) => onChange({ quote_style })}
          />
          <p className="quote-styled muted" style={{ fontSize: 16, margin: 0 }}>
            「これは引用の見え方の例です」
          </p>
        </div>
      </div>
    )
  }

  if (section === 'data') {
    return (
      <div className="detail">
        <h1 className="section-title">データ</h1>
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>
          本 {books.length}冊 / 記録 {notes.length}件 を書き出します。
        </p>
        <div className="actions">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => exportMarkdown(books, notes)}
          >
            <i className="ph-duotone ph-file-text" />
            Markdown で書き出す
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => exportCsv(books)}
          >
            <i className="ph-duotone ph-file-csv" />
            CSV で書き出す
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="detail">
      <h1 className="section-title">アカウント</h1>
      <p className="muted" style={{ margin: 0, fontSize: 15, lineHeight: 1.8 }}>
        このアプリはログインを持ちません。自分のPCで動かし、Tailscale の中からだけ
        開ける前提なので、アカウントの区別が要らないためです。
        <br />
        データは <code>backend/reading.db</code> の1ファイルにまとまっています。
        バックアップはこのファイルをコピーするだけで済みます。
      </p>
    </div>
  )
}
