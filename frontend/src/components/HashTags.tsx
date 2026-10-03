/**
 * タグの部品（デザイン 8b）。タグは枠も塗りも無い「#」の文字で出し、
 * 塗りのカテゴリ（`GenreChips`）と形で見分けられるようにする。PC版・モバイル版で共有する。
 */
import { useId, useState } from 'react'

/** 「#哲学 #生き方」（一覧の行用。押せない）。タグが無ければ何も出さない */
export function HashText({ tags }: { tags: string[] }) {
  if (tags.length === 0) return null
  return <span>{tags.map((tag) => `#${tag}`).join(' ')}</span>
}

type FilterProps = {
  tags: string[]
  value: string | null
  onChange: (next: string | null) => void
}

/** 本棚の「タグ」行。選んでいるタグは下線。もう一度押すと解除 */
export function TagFilterRow({ tags, value, onChange }: FilterProps) {
  if (tags.length === 0) return null
  return (
    <div className="tag-filter" role="group" aria-label="タグで絞り込む">
      <span className="tag-filter-label">タグ</span>
      {tags.map((tag) => (
        <button
          key={tag}
          type="button"
          className="hash-filter"
          aria-pressed={value === tag}
          onClick={() => onChange(value === tag ? null : tag)}
        >
          #{tag}
        </button>
      ))}
    </div>
  )
}

type LineProps = {
  tags: string[]
  /** 入力欄の補完に出す、これまでに使ったタグ */
  suggestions?: string[]
  onChange: (next: string[]) => void
  /** タグを押したとき（本棚をそのタグで絞り込む） */
  onSelect: (tag: string) => void
}

/**
 * 本の詳細のタグ行。`#タグ` を押すと本棚をそのタグで絞り込む。
 * 「＋ タグ」で編集に入り、入力して Enter で足す（Esc か「完了」で終わる）。
 * 編集中は各タグに × が付き、押すと外す。
 */
export function TagLine({ tags, suggestions = [], onChange, onSelect }: LineProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const listId = useId()

  function add() {
    // 「#哲学」と打っても「哲学」として足す
    const clean = draft.trim().replace(/^[#＃]/, '').trim()
    if (clean && !tags.includes(clean)) onChange([...tags, clean])
    setDraft('')
  }

  function finish() {
    setEditing(false)
    setDraft('')
  }

  return (
    <div className="hash-tags">
      {tags.map((tag) => (
        <button
          key={tag}
          type="button"
          className="hash-tag"
          title={editing ? 'タグを外す' : 'このタグで絞り込む'}
          onClick={() =>
            editing ? onChange(tags.filter((item) => item !== tag)) : onSelect(tag)
          }
        >
          #{tag}
          {editing ? <i className="ph-duotone ph-x" aria-label="外す" /> : null}
        </button>
      ))}
      {editing ? (
        <>
          <input
            className="input hash-input"
            value={draft}
            list={listId}
            autoFocus
            placeholder="タグを入力して Enter"
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              // 日本語入力の確定の Enter では足さない
              if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                event.preventDefault()
                add()
              } else if (event.key === 'Escape') {
                event.stopPropagation()
                finish()
              }
            }}
          />
          <datalist id={listId}>
            {suggestions
              .filter((name) => !tags.includes(name))
              .map((name) => (
                <option key={name} value={name} />
              ))}
          </datalist>
          <button type="button" className="hash-add" onClick={finish}>
            完了
          </button>
        </>
      ) : (
        <button type="button" className="hash-add" onClick={() => setEditing(true)}>
          ＋ タグ
        </button>
      )}
    </div>
  )
}
