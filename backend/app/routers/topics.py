"""キーワードのおすすめのAPI。

「次に読む本」（suggestions.py）は本棚の1冊に紐づくが、こちらは
**キーワード**（「ゲーム理論」「統計」など）に紐づく。
候補はその場で計算しない。スキル `keyword-suggestions` で選んだものを
`PUT /api/topics` でまとめて流し込み、ここでは読むだけ。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Book, DismissedBook, Topic, TopicSuggestion
from ..schemas import BookDetail, TopicDetail, TopicSummary, TopicWrite
from ..schemas import TopicSuggestion as TopicSuggestionRead
from ..timeutil import now_jst
from .suggestions import shelve

router = APIRouter(prefix="/api", tags=["topics"])


def _dismissed(db: Session) -> set[str]:
    return set(db.scalars(select(DismissedBook.isbn)).all())


def _visible(topic: Topic, dismissed: set[str]) -> list[TopicSuggestion]:
    """「興味なし」にした本を外した候補"""
    return [row for row in topic.suggestions if not (row.isbn and row.isbn in dismissed)]


def _detail(topic: Topic, dismissed: set[str]) -> TopicDetail:
    return TopicDetail(
        id=topic.id,
        keyword=topic.keyword,
        updated_at=topic.updated_at,
        suggestions=[TopicSuggestionRead.model_validate(row) for row in _visible(topic, dismissed)],
    )


def _get_topic_or_404(db: Session, topic_id: int) -> Topic:
    topic = db.scalar(
        select(Topic).options(selectinload(Topic.suggestions)).where(Topic.id == topic_id)
    )
    if topic is None:
        raise HTTPException(status_code=404, detail="キーワードが見つかりません")
    return topic


@router.get("/topics", response_model=list[TopicSummary])
def list_topics(db: Session = Depends(get_db)):
    """キーワードの一覧。新しく設定し直したものから並べる"""
    dismissed = _dismissed(db)
    topics = db.scalars(
        select(Topic)
        .options(selectinload(Topic.suggestions))
        .order_by(Topic.updated_at.desc(), Topic.id.desc())
    ).all()
    return [
        TopicSummary(
            id=topic.id,
            keyword=topic.keyword,
            count=len(_visible(topic, dismissed)),
            updated_at=topic.updated_at,
        )
        for topic in topics
    ]


@router.get("/topics/{topic_id}", response_model=TopicDetail)
def get_topic(topic_id: int, db: Session = Depends(get_db)):
    """キーワード1つぶんのおすすめを、設定した順に返す（興味なしは外す）"""
    return _detail(_get_topic_or_404(db, topic_id), _dismissed(db))


@router.put("/topics", response_model=TopicDetail)
def set_topic(payload: TopicWrite, db: Session = Depends(get_db)):
    """キーワードのおすすめをまとめて入れ替える。キーワードが無ければ作る。

    キーワードは本文（`keyword`）で受け取る。パスに入れると「CI/CD」のような
    スラッシュ入りのキーワードが扱えないため。
    """
    book_ids = {s.from_book_id for s in payload.suggestions if s.from_book_id is not None}
    if book_ids:
        missing = sorted(book_ids - set(db.scalars(select(Book.id).where(Book.id.in_(book_ids)))))
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"手がかりの本（from_book_id）が本棚にありません: {missing}",
            )

    topic = db.scalar(
        select(Topic).options(selectinload(Topic.suggestions)).where(Topic.keyword == payload.keyword)
    )
    if topic is None:
        topic = Topic(keyword=payload.keyword)
        db.add(topic)

    # 古い候補は delete-orphan で消える
    topic.suggestions = [
        TopicSuggestion(position=index, **item.model_dump())
        for index, item in enumerate(payload.suggestions)
    ]
    # 候補だけを入れ替えても topics の行は変わらず onupdate が走らないので、自分で入れる
    topic.updated_at = now_jst()
    db.commit()
    return _detail(_get_topic_or_404(db, topic.id), _dismissed(db))


@router.delete("/topics/{topic_id}", status_code=204)
def delete_topic(topic_id: int, db: Session = Depends(get_db)):
    """キーワードごと、そのおすすめを消す"""
    db.delete(_get_topic_or_404(db, topic_id))
    db.commit()


@router.post("/topic-suggestions/{suggestion_id}/add", response_model=BookDetail, status_code=201)
def add_to_shelf(suggestion_id: int, db: Session = Depends(get_db)):
    """キーワードのおすすめを積読として本棚に追加する"""
    suggestion = db.get(TopicSuggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="候補が見つかりません")
    return shelve(db, suggestion)
