import { useEffect, useState } from 'react'
import type { Review, ReviewPeriod } from '../api'
import * as api from '../api'
import { CmykNumber } from '../components/CmykNumber'
import { Cover } from '../components/Cover'

type Props = {
  /** 本が変わったら取り直すための目印 */
  version: number
  onOpenBook: (id: number) => void
}

/** 7e 振り返り */
export function ReviewScreen({ version, onOpenBook }: Props) {
  const [periods, setPeriods] = useState<ReviewPeriod[]>([])
  const [period, setPeriod] = useState<string | null>(null)
  const [review, setReview] = useState<Review | null>(null)

  useEffect(() => {
    api
      .listPeriods()
      .then((loaded) => {
        setPeriods(loaded)
        setPeriod((prev) => prev ?? loaded[0]?.period ?? null)
      })
      .catch(() => undefined)
  }, [version])

  useEffect(() => {
    if (period === null) return
    api.getReview(period).then(setReview).catch(() => undefined)
  }, [period, version])

  const peak = Math.max(1, ...(review?.bars ?? []).map((bar) => bar.value))
  const sub = periods.find((p) => p.period === period)?.sub ?? ''

  return (
    <div className="m-screen m-screen-flush">
      <div className="m-head">
        <h1 className="m-title">振り返り</h1>
      </div>

      <div className="m-bleed m-chips">
        {periods.map((item) => (
          <button
            key={item.period}
            type="button"
            className={`m-chip tag ${item.period === period ? 'tag-accent' : 'tag-neutral'}`}
            onClick={() => setPeriod(item.period)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {review === null ? (
        <p className="m-empty">読み込んでいます…</p>
      ) : (
        <>
          {sub ? <p className="m-kicker">{sub}</p> : null}

          <section className="review-count" style={{ margin: '8px 0 20px' }}>
            <CmykNumber value={review.finished_count} fontSize={112} />
            <span style={{ fontSize: 20, fontWeight: 600 }}>冊 読了</span>
          </section>
          {review.yearly_goal !== null ? (
            <p className="m-kicker" style={{ marginBottom: 18 }}>
              {review.remaining_to_goal === 0
                ? `目標 ${review.yearly_goal}冊 を達成`
                : `目標 ${review.yearly_goal}冊まで あと${review.remaining_to_goal}冊`}
            </p>
          ) : null}

          <div className="m-chart">
            {review.bars.map((bar) => (
              <div key={bar.label} className="chart-col" data-current={bar.current}>
                <span
                  className="chart-bar"
                  style={{ height: `${(bar.value / peak) * 100}%` }}
                  title={`${bar.label} ${bar.value}冊`}
                />
                <span className="chart-label">{bar.label}</span>
              </div>
            ))}
          </div>

          <section className="m-stats-3">
            <div>
              <div className="m-stat-value">{review.pages.toLocaleString()}</div>
              <div className="stat-label">ページ</div>
            </div>
            <div>
              <div className="m-stat-value">{review.note_count}</div>
              <div className="stat-label">メモ・引用</div>
            </div>
            <div>
              <div
                className="m-stat-value"
                style={{ fontSize: review.top_category ? 15 : 22 }}
              >
                {review.top_category ?? '—'}
              </div>
              <div className="stat-label">よく読む分野</div>
            </div>
          </section>

          {review.top_quote ? (
            <section className="stack" style={{ gap: 8, marginBottom: 24 }}>
              <span className="record-kind kind-quote">いちばん残した言葉</span>
              <p
                className="quote-styled"
                style={{ fontSize: 18, lineHeight: 1.65, margin: 0 }}
              >
                「{review.top_quote.text}」
              </p>
              <span className="section-aside">
                {review.top_quote.book_title}
                {review.top_quote.page ? ` · p.${review.top_quote.page}` : ''}
              </span>
            </section>
          ) : null}

          {review.books.length > 0 ? (
            <section className="stack" style={{ gap: 12 }}>
              <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>
                この期間に読み終えた本
              </h2>
              <div className="shelf">
                {review.books.map((book) => (
                  <button
                    key={book.id}
                    type="button"
                    onClick={() => onOpenBook(book.id)}
                    title={book.title}
                    style={{ border: 0, background: 'transparent', padding: 0 }}
                  >
                    <Cover
                      title={book.title}
                      author={book.author}
                      src={book.cover_url}
                      size="md"
                    />
                  </button>
                ))}
              </div>
            </section>
          ) : null}
        </>
      )}
    </div>
  )
}
