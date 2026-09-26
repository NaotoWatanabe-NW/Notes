import type { Review } from '../api'
import { CmykNumber } from './CmykNumber'
import { Cover } from './Cover'

type Props = {
  review: Review
  sub: string
  onOpenBook: (id: number) => void
}

export function ReviewView({ review, sub, onOpenBook }: Props) {
  // 棒の高さは、その期間でいちばん多い月（週）を基準に決める
  const peak = Math.max(1, ...review.bars.map((bar) => bar.value))

  return (
    <div className="detail">
      <header className="stack" style={{ gap: 4 }}>
        {sub ? <span className="section-aside">{sub}</span> : null}
        <h1 style={{ fontSize: 32, fontWeight: 600, margin: 0 }}>{review.label}</h1>
      </header>

      <section className="review-count">
        <CmykNumber value={review.finished_count} fontSize={150} />
        <span style={{ fontSize: 22, fontWeight: 600 }}>冊 読了</span>
        {review.yearly_goal !== null ? (
          <span className="review-goal">
            {review.remaining_to_goal === 0
              ? `目標 ${review.yearly_goal}冊 を達成`
              : `目標 ${review.yearly_goal}冊まで あと${review.remaining_to_goal}冊`}
          </span>
        ) : null}
      </section>

      <section className="stack" style={{ gap: 10 }}>
        <div className="chart">
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
      </section>

      <section className="stats">
        <div>
          <div className="stat-value">{review.pages.toLocaleString()}</div>
          <div className="stat-label">ページ</div>
        </div>
        <div>
          <div className="stat-value">{review.note_count}</div>
          <div className="stat-label">メモ・引用</div>
        </div>
        <div>
          <div className="stat-value" style={{ fontSize: review.top_category ? 20 : 28 }}>
            {review.top_category ?? '—'}
          </div>
          <div className="stat-label">よく読む分野</div>
        </div>
      </section>

      {review.top_quote ? (
        <section className="stack" style={{ gap: 8 }}>
          <span className="record-kind kind-quote">いちばん残した言葉</span>
          <p
            className="quote-styled"
            style={{ fontSize: 22, lineHeight: 1.65, margin: 0 }}
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
        <section className="stack" style={{ gap: 16 }}>
          <h2 className="section-title">この期間に読み終えた本</h2>
          <div className="shelf">
            {review.books.map((book) => (
              <button
                key={book.id}
                type="button"
                onClick={() => onOpenBook(book.id)}
                title={book.title}
                style={{
                  border: 0,
                  background: 'transparent',
                  padding: 0,
                  cursor: 'pointer',
                }}
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
    </div>
  )
}
