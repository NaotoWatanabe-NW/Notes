"""引用・メモのAPI"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Book, Note, NoteKind
from ..schemas import NoteCreate, NoteRead, NoteUpdate, NoteWithBook

# 本に紐づくノート（一覧・作成）
book_notes_router = APIRouter(prefix="/api/books/{book_id}/notes", tags=["notes"])
# ノート単体と横断一覧
notes_router = APIRouter(prefix="/api/notes", tags=["notes"])


def _get_book_or_404(db: Session, book_id: int) -> Book:
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="本が見つかりません")
    return book


def _get_note_or_404(db: Session, note_id: int) -> Note:
    note = db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="ノートが見つかりません")
    return note


@book_notes_router.get("", response_model=list[NoteRead])
def list_book_notes(book_id: int, db: Session = Depends(get_db)):
    """ある本の引用・メモ。本の詳細ではページの大きい順に並べる"""
    _get_book_or_404(db, book_id)
    stmt = (
        select(Note)
        .where(Note.book_id == book_id)
        # ページが入っていないメモは後ろに回す
        .order_by(Note.page.desc().nulls_last(), Note.created_at.desc(), Note.id.desc())
    )
    return db.scalars(stmt).all()


@book_notes_router.post("", response_model=NoteRead, status_code=201)
def create_note(book_id: int, payload: NoteCreate, db: Session = Depends(get_db)):
    _get_book_or_404(db, book_id)
    note = Note(book_id=book_id, **payload.model_dump())
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@notes_router.get("", response_model=list[NoteWithBook])
def list_all_notes(
    kind: NoteKind | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """全部の本を横断した引用・メモ。「メモ・引用」ビュー用。

    出典を出すので本の情報も一緒に返す。joinedload を付けないと、
    1件ごとに本を取りに行って件数ぶん往復してしまう（N+1問題）。
    """
    stmt = (
        select(Note)
        .options(joinedload(Note.book))
        .order_by(Note.created_at.desc(), Note.id.desc())
    )
    if kind is not None:
        stmt = stmt.where(Note.kind == kind)
    return db.scalars(stmt).all()


@notes_router.get("/{note_id}", response_model=NoteWithBook)
def get_note(note_id: int, db: Session = Depends(get_db)):
    return _get_note_or_404(db, note_id)


@notes_router.patch("/{note_id}", response_model=NoteRead)
def update_note(note_id: int, payload: NoteUpdate, db: Session = Depends(get_db)):
    note = _get_note_or_404(db, note_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(note, key, value)
    db.commit()
    db.refresh(note)
    return note


@notes_router.delete("/{note_id}", status_code=204)
def delete_note(note_id: int, db: Session = Depends(get_db)):
    db.delete(_get_note_or_404(db, note_id))
    db.commit()
