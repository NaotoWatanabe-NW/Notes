"""おすすめ一覧のAPI（デザイン J）。

「次に読む本」（本ごと）とキーワードのおすすめを、**本棚に無い本の1列の一覧**に
まとめて返す。同じ本が何冊もの本の候補に出ていれば1つにまとめ、どこから選ばれたかと
理由を全部添える。本棚にある本（ISBN か書名が一致）と「興味なし」にした本は出さない。
候補はその場で計算しない。設定してあるものを並べ直すだけ。
"""
import unicodedata

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Book, DismissedBook, Genre, Suggestion, Topic, TopicSuggestion
from ..schemas import BookDetail, Recommendation, RecommendationAdd, RecommendationSource
from .suggestions import shelve

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


def _same_title_key(title: str) -> str:
    """書名の一致を見るための形（全角/半角と空白の違いを無視する）"""
    return "".join(unicodedata.normalize("NFKC", title).split())


@router.get("", response_model=list[Recommendation])
def list_recommendations(db: Session = Depends(get_db)):
    """おすすめ一覧。いくつもの本やキーワードから選ばれた本を先に並べる"""
    shelf = db.execute(select(Book.isbn, Book.title)).all()
    shelf_isbns = {isbn for isbn, _ in shelf if isbn}
    shelf_titles = {_same_title_key(title) for _, title in shelf}
    dismissed = set(db.scalars(select(DismissedBook.isbn)).all())

    # 本ごとの候補（本の id 順・設定した順）→ キーワードの候補（新しいキーワード順）
    rows = [
        (row, RecommendationSource(kind="book", label=book.title, book_id=book.id, reason=row.reason))
        for row, book in db.execute(
            select(Suggestion, Book)
            .join(Book, Suggestion.book_id == Book.id)
            .order_by(Book.id, Suggestion.position, Suggestion.id)
        ).all()
    ] + [
        (row, RecommendationSource(kind="topic", label=topic.keyword, reason=row.reason))
        for row, topic in db.execute(
            select(TopicSuggestion, Topic)
            .join(Topic, TopicSuggestion.topic_id == Topic.id)
            .order_by(Topic.updated_at.desc(), TopicSuggestion.position, TopicSuggestion.id)
        ).all()
    ]

    merged: dict[str, Recommendation] = {}
    for row, source in rows:
        if not row.isbn or row.isbn in dismissed or row.isbn in shelf_isbns:
            continue
        if _same_title_key(row.title) in shelf_titles:
            continue
        item = merged.get(row.isbn)
        if item is None:
            merged[row.isbn] = Recommendation(
                isbn=row.isbn,
                title=row.title,
                author=row.author,
                cover_url=row.cover_url,
                genre=row.genre or Genre.OTHER,
                publisher=row.publisher,
                total=row.total,
                sources=[source],
            )
            continue
        item.sources.append(source)
        # 先に出た候補に無い情報は、あとの候補から埋める
        if row.genre and item.genre == Genre.OTHER:
            item.genre = row.genre
        item.publisher = item.publisher or row.publisher
        item.total = item.total or row.total
        item.cover_url = item.cover_url or row.cover_url

    # sorted は安定なので、同じ数どうしは上の順のまま
    return sorted(merged.values(), key=lambda item: -len(item.sources))


@router.post("/add", response_model=BookDetail, status_code=201)
def add_to_shelf(payload: RecommendationAdd, db: Session = Depends(get_db)):
    """おすすめを積読として本棚に追加する。

    同じ本の候補（本ごと・キーワード）すべてに追加済みの印を付けるので、
    本の詳細や読了ダイアログで開き直しても「追加済み」と分かる。
    """
    rows: list[Suggestion | TopicSuggestion] = [
        *db.scalars(select(Suggestion).where(Suggestion.isbn == payload.isbn).order_by(Suggestion.id)),
        *db.scalars(select(TopicSuggestion).where(TopicSuggestion.isbn == payload.isbn).order_by(TopicSuggestion.id)),
    ]
    if not rows:
        raise HTTPException(status_code=404, detail="おすすめに無い本です")
    # カテゴリなどが入っている候補から本を作る
    first = next((row for row in rows if row.genre), rows[0])
    book = shelve(db, first)
    for row in rows:
        row.added_book_id = book.id
    db.commit()
    db.refresh(book)
    book.note_count = 0
    book.has_report = bool(book.report_md)
    return book
