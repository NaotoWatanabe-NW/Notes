import type { ReviewPeriod } from '../api'

type Props = {
  periods: ReviewPeriod[]
  selected: string | null
  onSelect: (period: string) => void
}

export function ReviewPane({ periods, selected, onSelect }: Props) {
  return (
    <>
      <div className="list-head">
        <span className="list-title">振り返り</span>
      </div>
      <div className="rows">
        {periods.map((period) => (
          <button
            key={period.period}
            type="button"
            className="row row-period"
            aria-current={period.period === selected}
            onClick={() => onSelect(period.period)}
          >
            <span className="row-main">
              <span className="row-period-label">{period.label}</span>
              {period.sub ? <span className="row-meta">{period.sub}</span> : null}
            </span>
            <span className="row-period-count">{period.count}冊</span>
          </button>
        ))}
      </div>
    </>
  )
}
