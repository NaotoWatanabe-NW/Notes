import { useState } from 'react'

type Props = {
  tags: string[]
  suggestions?: string[]
  onChange: (next: string[]) => void
}

/** 本に付けるタグの編集。入力して Enter で足し、×で外す */
export function TagEditor({ tags, suggestions = [], onChange }: Props) {
  const [draft, setDraft] = useState('')

  function add(name: string) {
    const clean = name.trim()
    // 同じタグを二重に付けない
    if (!clean || tags.includes(clean)) {
      setDraft('')
      return
    }
    onChange([...tags, clean])
    setDraft('')
  }

  // まだ付いていないタグだけを候補に出す
  const unused = suggestions.filter((name) => !tags.includes(name)).slice(0, 6)

  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="tags">
        {tags.map((tag) => (
          <span key={tag} className="tag-chip">
            {tag}
            <button
              type="button"
              className="tag-chip-remove"
              aria-label={`タグ ${tag} を外す`}
              onClick={() => onChange(tags.filter((t) => t !== tag))}
            >
              <i className="ph-duotone ph-x" style={{ fontSize: 12 }} />
            </button>
          </span>
        ))}
        <input
          className="input tag-input"
          value={draft}
          placeholder="タグを追加"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add(draft)
            }
          }}
          onBlur={() => add(draft)}
        />
      </div>

      {unused.length > 0 ? (
        <div className="tags">
          <span className="row-meta">よく使うタグ:</span>
          {unused.map((tag) => (
            <button
              key={tag}
              type="button"
              className="tag-chip"
              onClick={() => add(tag)}
            >
              ＋ {tag}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}
