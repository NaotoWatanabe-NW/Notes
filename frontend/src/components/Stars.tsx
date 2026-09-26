type Props = {
  value: number | null
  size?: number
  onChange?: (next: number | null) => void
}

/** ★1〜5。すでに選ばれている星をもう一度押すと未評価に戻る */
export function Stars({ value, size = 20, onChange }: Props) {
  return (
    <span className="stars" role="group" aria-label="評価">
      {[1, 2, 3, 4, 5].map((star) => {
        const on = value !== null && star <= value
        return (
          <button
            key={star}
            type="button"
            className="star"
            data-on={on}
            aria-label={`${star}つ星`}
            aria-pressed={on}
            disabled={!onChange}
            onClick={() => onChange?.(value === star ? null : star)}
            style={{ cursor: onChange ? 'pointer' : 'default' }}
          >
            <i className="ph-duotone ph-star" style={{ fontSize: size }} />
          </button>
        )
      })}
    </span>
  )
}
