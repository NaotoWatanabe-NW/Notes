"""タグのAPI"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Tag, book_tags
from ..schemas import TagCount

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=list[TagCount])
def list_tags(db: Session = Depends(get_db)):
    """使われているタグと、それが付いている冊数。多い順に返す。

    どの本にも付いていないタグは出さない（本から外した残りかすを見せない）。
    """
    stmt = (
        select(Tag.name, func.count(book_tags.c.book_id).label("count"))
        .join(book_tags, Tag.id == book_tags.c.tag_id)
        .group_by(Tag.name)
        .order_by(func.count(book_tags.c.book_id).desc(), Tag.name)
    )
    return [TagCount(name=name, count=count) for name, count in db.execute(stmt)]
