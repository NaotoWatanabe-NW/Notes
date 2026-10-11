"""「次に読む本」のAPI（デザイン #5a の読了時ダイアログ用）

候補はその場で計算しない。**本ごとにあらかじめ設定しておいたもの**を読むだけ。
外部サービスを叩かないので速く、理由も人の言葉で書ける。
設定は `PUT /api/books/{id}/suggestions` でまとめて入れ替える。
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from .. import report_store
from ..models import (
    Basis, Book, BookStatus, DismissedBook, Genre, Note, Suggestion, TopicSuggestion,
)
from ..schemas import BookDetail, Suggestion as SuggestionRead
from ..schemas import SuggestionSet, SuggestionWrite

router = APIRouter(prefix="/api", tags=["suggestions"])

# 1ページに出す冊数（デザインは3列）
PAGE_SIZE = 3

BASIS_LABELS = {
    Basis.NOTE: "引用・メモから",
    Basis.RATING: "評価から",
    Basis.TAG: "分野から",
}
DISTANCE_LABELS = {"near": "近い本", "far": "少し離れた本"}


def _get_book_or_404(db: Session, book_id: int) -> Book:
    book = db.scalar(
        select(Book).options(selectinload(Book.tags)).where(Book.id == book_id)
    )
    if book is None:
        raise HTTPException(status_code=404, detail="本が見つかりません")
    return book


def _days_taken(started: date | None, finished: date | None) -> int | None:
    """読み終えるまでにかかった日数。同じ日に読み切ったら1日と数える"""
    if started is None or finished is None or finished < started:
        return None
    return (finished - started).days + 1


def _summary(
    chosen: set[Basis], distance: str, total: int, dismissed: int, per_page: int
) -> str:
    """画面の下に出す、根拠の要約"""
    if total == 0:
        return "条件に合う候補がありません。根拠や距離を変えてみてください。"

    parts = [BASIS_LABELS[b] for b in (Basis.NOTE, Basis.RATING, Basis.TAG) if b in chosen]
    text = f"{'、'.join(parts)}選んでいます"
    if distance != "both":
        text += f"（{DISTANCE_LABELS[distance]}のみ）"
    if dismissed:
        text += f" — 興味なし {dismissed}件は出していません"
    if total <= per_page:
        text += "。候補はこれで全部です"
    return text


@router.get("/books/{book_id}/suggestions", response_model=SuggestionSet)
def get_suggestions(
    book_id: int,
    basis: str = Query(default="note,rating,tag"),
    distance: str = Query(default="both", pattern="^(near|far|both)$"),
    page: int = Query(default=0, ge=0, le=20),
    per_page: int = Query(default=PAGE_SIZE, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """設定しておいた「次に読む本」を返す。

    - `basis`: `note,rating,tag` のようにカンマ区切り。**最低1つ必要**
    - `distance`: `near`（近い本）/ `far`（少し離れた本）/ `both`
    - `page`: 「出し直す」を押すたびに1つ増やす
    - `per_page`: 1ページの冊数。既定は読了ダイアログの3冊。
      本の詳細画面は設定してある候補を全部出したいので大きくして使う
    """
    try:
        chosen = {Basis(part.strip()) for part in basis.split(",") if part.strip()}
    except ValueError:
        chosen = set()
    if not chosen:
        raise HTTPException(
            status_code=422,
            detail="根拠は note / rating / tag から1つ以上選んでください",
        )

    book = _get_book_or_404(db, book_id)
    all_rows = list(
        db.scalars(
            select(Suggestion)
            .where(Suggestion.book_id == book_id)
            .order_by(Suggestion.position, Suggestion.id)
        ).all()
    )

    dismissed = set(db.scalars(select(DismissedBook.isbn)).all())
    matched = [
        row
        for row in all_rows
        if row.basis in chosen
        and (distance == "both" or row.distance.value == distance)
        and not (row.isbn and row.isbn in dismissed)
    ]

    start = page * per_page
    chunk = matched[start : start + per_page]
    note_count = len(list(db.scalars(select(Note.id).where(Note.book_id == book_id))))

    return SuggestionSet(
        book_id=book.id,
        book_title=book.title,
        days=_days_taken(book.started_on, book.finished_on),
        note_count=note_count,
        # 1件も設定していなければ、画面は「まだ検索していません」を出す
        configured=bool(all_rows),
        suggestions=[SuggestionRead.model_validate(row) for row in chunk],
        summary=_summary(chosen, distance, len(matched), len(dismissed), per_page),
        has_more=len(matched) > start + per_page,
    )


@router.put(
    "/books/{book_id}/suggestions", response_model=list[SuggestionRead], status_code=200
)
def set_suggestions(
    book_id: int,
    payload: list[SuggestionWrite],
    db: Session = Depends(get_db),
):
    """その本の「次に読む本」をまとめて入れ替える。

    設定は Claude との相談で決めて、ここに流し込む想定。
    空の配列を送れば全部消える。
    """
    if len(payload) > 20:
        raise HTTPException(status_code=422, detail="候補は20件までにしてください")
    _get_book_or_404(db, book_id)

    for existing in db.scalars(select(Suggestion).where(Suggestion.book_id == book_id)):
        db.delete(existing)
    db.flush()

    rows = [
        Suggestion(book_id=book_id, position=index, **item.model_dump())
        for index, item in enumerate(payload)
    ]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


@router.post("/suggestions/{suggestion_id}/add", response_model=BookDetail, status_code=201)
def add_to_shelf(suggestion_id: int, db: Session = Depends(get_db)):
    """候補を積読として本棚に追加する。

    追加した本の id を候補に控えるので、ダイアログを開き直しても
    「追加済み」と分かる。
    """
    suggestion = db.get(Suggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="候補が見つかりません")
    return shelve(db, suggestion)


def shelve(db: Session, suggestion: Suggestion | TopicSuggestion) -> Book:
    """候補を積読として本棚に入れ、候補に追加済みの印を付ける。

    「次に読む本」・キーワードのおすすめ・おすすめ一覧で共通。
    候補にカテゴリ・出版社・ページ数があれば、本にも引き継ぐ。
    """
    # すでに同じ ISBN の本があれば、それを使い回す（二重登録を防ぐ）
    existing = None
    if suggestion.isbn:
        existing = db.scalar(select(Book).where(Book.isbn == suggestion.isbn))

    book = existing or Book(
        isbn=suggestion.isbn,
        title=suggestion.title,
        author=suggestion.author,
        publisher=suggestion.publisher,
        total=suggestion.total,
        genre=suggestion.genre or Genre.OTHER,
        cover_url=suggestion.cover_url,
        status=BookStatus.UNREAD,
    )
    if existing is None:
        db.add(book)
        db.flush()

    suggestion.added_book_id = book.id
    db.commit()
    db.refresh(book)
    book.note_count = 0
    book.has_report = report_store.has_report(book.id)
    return book


@router.post("/suggestions/dismiss", status_code=204)
def dismiss(
    isbn: str = Query(min_length=13, max_length=13), db: Session = Depends(get_db)
):
    """「興味なし」にする。以後のおすすめから外す"""
    already = db.scalar(select(DismissedBook.id).where(DismissedBook.isbn == isbn))
    if already is None:
        db.add(DismissedBook(isbn=isbn))
        db.commit()
