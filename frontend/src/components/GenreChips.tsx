/**
 * カテゴリ（小説 / ビジネス・実用 / …）の部品。PC版・モバイル版で共有する。
 * デザイン 8b「形で分ける」: カテゴリは**塗り**、タグは「#」の文字（`HashTags`）。
 * カテゴリごとの色は作らない（シアンは操作、マゼンタは引用だけ）。
 */
import type { Genre } from '../api'
import { GENRE_LABELS } from '../api'

const GENRES = Object.keys(GENRE_LABELS) as Genre[]

type FilterProps = {
  value: Genre | null
  onChange: (next: Genre | null) => void
  /** モバイル版は1行で横にスクロールさせる */
  scroll?: boolean
}

/** 本棚の絞り込み。「すべて」＋6つ。選んでいるものは塗り（`--color-accent`） */
export function GenreFilterChips({ value, onChange, scroll = false }: FilterProps) {
  return (
    <div
      className={scroll ? 'cat-chips cat-chips-scroll' : 'cat-chips'}
      role="group"
      aria-label="カテゴリで絞り込む"
    >
      <button
        type="button"
        className="cat-chip"
        aria-pressed={value === null}
        onClick={() => onChange(null)}
      >
        すべて
      </button>
      {GENRES.map((genre) => (
        <button
          key={genre}
          type="button"
          className="cat-chip"
          aria-pressed={value === genre}
          onClick={() => onChange(genre)}
        >
          {GENRE_LABELS[genre]}
        </button>
      ))}
    </div>
  )
}

type PickerProps = {
  value: Genre
  onChange: (next: Genre) => void
  /** 見出しが別にあるとき（モバイルのシート）は false */
  label?: boolean
}

/** 本のカテゴリを6つから選ぶ（本の詳細の ▾ を押したとき・追加画面） */
export function GenrePicker({ value, onChange, label = true }: PickerProps) {
  return (
    <div className="cat-pick" role="group" aria-label="カテゴリ">
      {label ? <span className="cat-pick-label">カテゴリ</span> : null}
      {GENRES.map((genre) => (
        <button
          key={genre}
          type="button"
          className="cat-chip"
          aria-pressed={value === genre}
          onClick={() => onChange(genre)}
        >
          {GENRE_LABELS[genre]}
        </button>
      ))}
    </div>
  )
}

/** 一覧の行に出す小さなカテゴリ（`.tag-neutral` 10px） */
export function GenreTag({ genre }: { genre: Genre }) {
  return <span className="tag tag-neutral tag-mini">{GENRE_LABELS[genre]}</span>
}
