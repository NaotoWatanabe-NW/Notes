"""振り返り（ある期間の読書のまとめ）のAPI。

冊数は個人の蔵書ぶんしかないので、DBで凝った集計をせず、期間内のデータを
取ってきて Python で数える。そのほうが読んで分かりやすい。
"""
import calendar
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..database import get_db
from ..models import Book, BookStatus, Note, NoteKind
from ..schemas import Review, ReviewBar, ReviewBook, ReviewPeriod, ReviewQuote
from ..settings_store import get_settings
from ..timeutil import today_jst

router = APIRouter(prefix="/api/reviews", tags=["reviews"])

_MONTH_LABELS = [f"{m}月" for m in range(1, 13)]


def _parse_period(period: str) -> tuple[date, date, str, bool]:
    """"2026" や "2026-09" を (開始日, 終了日, 表示名, 年かどうか) に直す"""
    parts = period.split("-")
    try:
        if len(parts) == 1:
            year = int(parts[0])
            return date(year, 1, 1), date(year, 12, 31), f"{year}年", True
        if len(parts) == 2:
            year, month = int(parts[0]), int(parts[1])
            last_day = calendar.monthrange(year, month)[1]
            return (
                date(year, month, 1),
                date(year, month, last_day),
                f"{year}年{month}月",
                False,
            )
    except (ValueError, calendar.IllegalMonthError):
        pass
    raise HTTPException(
        status_code=422, detail="期間は 2026 または 2026-09 の形式で指定してください"
    )


def _week_index(day: date) -> int:
    """月の中の第何週か（0始まり）。1〜7日を第1週として7日ごとに区切る"""
    return min((day.day - 1) // 7, 4)


@router.get("", response_model=list[ReviewPeriod])
def list_periods(db: Session = Depends(get_db)):
    """振り返りを出せる期間の一覧。

    今年・今月・先月を先に出し、そのあとに読了した本がある年を新しい順に並べる。
    """
    finished = list(
        db.scalars(
            select(Book.finished_on).where(
                Book.status == BookStatus.FINISHED, Book.finished_on.is_not(None)
            )
        ).all()
    )
    today = today_jst()
    last_month_end = date(today.year, today.month, 1) - timedelta(days=1)

    def count_in(period: str) -> int:
        start, end, _, _ = _parse_period(period)
        return sum(1 for d in finished if start <= d <= end)

    rows: list[tuple[str, str, str]] = [
        (f"{today.year}", f"{today.year}年", f"1月〜{today.month}月"),
        (f"{today.year}-{today.month:02d}", f"{today.year}年{today.month}月", "今月"),
        (
            f"{last_month_end.year}-{last_month_end.month:02d}",
            f"{last_month_end.year}年{last_month_end.month}月",
            "先月",
        ),
    ]
    seen = {row[0] for row in rows}
    for year in sorted({d.year for d in finished}, reverse=True):
        if str(year) not in seen:
            rows.append((str(year), f"{year}年", ""))
            seen.add(str(year))

    return [
        ReviewPeriod(period=period, label=label, sub=sub, count=count_in(period))
        for period, label, sub in rows
    ]


@router.get("/{period}", response_model=Review)
def get_review(period: str, db: Session = Depends(get_db)):
    start, end, label, is_year = _parse_period(period)
    today = today_jst()

    finished = list(
        db.scalars(
            select(Book)
            .options(selectinload(Book.tags))
            .where(
                Book.status == BookStatus.FINISHED,
                Book.finished_on.is_not(None),
                Book.finished_on >= start,
                Book.finished_on <= end,
            )
            .order_by(Book.finished_on.desc(), Book.id.desc())
        ).all()
    )
    notes = list(
        db.scalars(
            select(Note)
            .options(joinedload(Note.book))
            .where(Note.created_at >= start, Note.created_at <= end)
        ).all()
    )

    # 読んだページ数。総ページが分かっている本はそれを、分からない本は
    # 読んだところまでを足す
    pages = sum((book.total or book.page or 0) for book in finished)

    # よく読む分野。自分で付けたタグを優先し、無ければ国会図書館の件名を使う
    labels: list[str] = []
    for book in finished:
        if book.tags:
            labels.extend(tag.name for tag in book.tags)
        elif book.category:
            labels.append(book.category)
    top_category = max(set(labels), key=labels.count) if labels else None

    # 棒グラフ。年は月別、月は週別
    if is_year:
        counts = [0] * 12
        for book in finished:
            counts[book.finished_on.month - 1] += 1
        bars = [
            ReviewBar(
                label=_MONTH_LABELS[i],
                value=counts[i],
                current=(start.year == today.year and i == today.month - 1),
            )
            for i in range(12)
        ]
    else:
        counts = [0] * 5
        for book in finished:
            counts[_week_index(book.finished_on)] += 1
        in_this_month = start.year == today.year and start.month == today.month
        bars = [
            ReviewBar(
                label=f"第{i + 1}週",
                value=counts[i],
                current=(in_this_month and i == _week_index(today)),
            )
            for i in range(5)
        ]

    # いちばん残した言葉。評価の高い本の引用から、いちばん長いものを選ぶ
    quotes = [n for n in notes if n.kind == NoteKind.QUOTE]
    top_quote = None
    if quotes:
        best = max(quotes, key=lambda n: ((n.book.rating or 0), len(n.text)))
        top_quote = ReviewQuote(
            text=best.text, book_title=best.book.title, page=best.page
        )

    settings = get_settings(db)
    # 目標は年間のものなので、年の振り返りのときだけ出す
    goal = settings.yearly_goal if is_year else None
    return Review(
        label=label,
        finished_count=len(finished),
        yearly_goal=goal,
        remaining_to_goal=max(0, goal - len(finished)) if goal is not None else None,
        pages=pages,
        note_count=len(notes),
        top_category=top_category,
        bars=bars,
        books=[ReviewBook.model_validate(book) for book in finished],
        top_quote=top_quote,
    )
