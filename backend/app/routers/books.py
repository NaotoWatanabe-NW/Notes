"""本に関するAPI（登録・一覧・詳細・更新・削除）"""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from .. import covers, report_store
from ..models import Book, BookCover, BookSort, BookStatus, Note, Reading, Tag
from ..schemas import BookCreate, BookDetail, BookRead, BookUpdate
from ..settings_store import get_settings
from ..timeutil import now_jst, today_jst

router = APIRouter(prefix="/api/books", tags=["books"])
logger = logging.getLogger(__name__)

# 並び順。設定画面の「本棚の並び順」と同じ3種類（デザインの settings.sort）。
# 同じ値の本が並んだときは id の新しい順で決める。
_SORT_ORDERS = {
    BookSort.RECENT: (Book.created_at.desc(),),
    BookSort.TITLE: (Book.title.asc(),),
    # 進捗順。総ページが未設定の本は割合を出せないので後ろに回す
    BookSort.PROGRESS: (
        (Book.page * 1.0 / func.nullif(Book.total, 0)).desc().nulls_last(),
    ),
}


def _get_book_or_404(db: Session, book_id: int) -> Book:
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="本が見つかりません")
    return book


def _is_isbn_conflict(error: IntegrityError) -> bool:
    """ISBN の重複（UNIQUE 制約違反）かどうかを判定する。

    SQLite の例外は理由を構造化して持っていないのでメッセージで判定する。
    ここは SQLite に依存している箇所。
    """
    message = str(error.orig).lower()
    return "unique" in message and "isbn" in message


def _commit(db: Session) -> None:
    """保存する。DBに弾かれたら、理由に応じたエラーを返す"""
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if _is_isbn_conflict(error):
            raise HTTPException(
                status_code=409, detail="同じISBNの本がすでに登録されています"
            ) from error
        # ISBN重複以外の制約違反。全部 409 にすると原因が分からなくなるので分ける
        raise HTTPException(
            status_code=400, detail="保存できない値が含まれています"
        ) from error


def _apply_progress_rules(book: Book, sent: set[str]) -> None:
    """進捗と状態のつじつまを合わせる。

    - 読み始めたら開始日を入れる
    - 最後のページまで読んだら自動で「読了」にする（デザインの仕様）
    - 読了になったら読了日を入れる

    日付は、フォームから明示的に送られてきたときはその値を尊重して
    自動補完しない。読了を取り消しても読了日は消さない（記録として残す）。
    """
    if book.total and book.page >= book.total:
        book.status = BookStatus.FINISHED

    if book.status in (BookStatus.READING, BookStatus.FINISHED):
        if book.started_on is None and "started_on" not in sent:
            book.started_on = today_jst()

    if book.status == BookStatus.FINISHED:
        if book.finished_on is None and "finished_on" not in sent:
            book.finished_on = today_jst()


def _record_reading(db: Session, book: Book) -> None:
    """「読み終えた」記録を1行足す。

    再読のたびに増えるので、何回読んだかと、それぞれいつ読み終えたかが残る。
    同じ日に二重で記録されないよう、同じ日付の行があれば足さない。
    """
    if book.finished_on is None:
        return
    already = db.scalar(
        select(Reading.id).where(
            Reading.book_id == book.id, Reading.finished_on == book.finished_on
        )
    )
    if already is None:
        db.add(Reading(book_id=book.id, finished_on=book.finished_on))


def _resolve_tags(db: Session, names: list[str]) -> list[Tag]:
    """タグ名の一覧を Tag の行に直す。無い名前はその場で作る。

    前後の空白を落とし、同じ名前が二重に付かないようにする。
    """
    cleaned: list[str] = []
    for raw in names:
        name = raw.strip()
        if name and name not in cleaned:
            cleaned.append(name)
    if not cleaned:
        return []

    existing = {
        tag.name: tag for tag in db.scalars(select(Tag).where(Tag.name.in_(cleaned)))
    }
    tags: list[Tag] = []
    for name in cleaned:
        tag = existing.get(name)
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            existing[name] = tag
        tags.append(tag)
    return tags


def _with_counts(db: Session, books: list[Book]) -> list[Book]:
    """一覧で使う集計値（ノート件数・レポートの有無）を各本に付ける。

    本ごとに問い合わせると冊数ぶん往復してしまうので、1回のクエリでまとめて
    数えてから割り当てる。レポートの有無もファイルを1冊ずつ stat せず、
    report_store の索引から一度に引く。
    """
    if not books:
        return books
    ids = [book.id for book in books]
    counts = dict(
        db.execute(
            select(Note.book_id, func.count(Note.id))
            .where(Note.book_id.in_(ids))
            .group_by(Note.book_id)
        ).all()
    )
    with_report = report_store.book_ids_with_report()
    for book in books:
        book.note_count = counts.get(book.id, 0)
        book.has_report = book.id in with_report
    return books


# レポートの frontmatter に複製している書誌項目。この値が変わったときだけ
# ファイルを書き直す（report_store.build_markdown と対応させる）。
_REPORT_META_FIELDS = (
    "title", "author", "isbn", "genre", "status", "rating",
    "started_on", "finished_on",
)


def _report_meta_snapshot(book: Book) -> tuple:
    """frontmatter に複製している値の現在の組。更新の前後で比べる。"""
    return (
        *(getattr(book, name) for name in _REPORT_META_FIELDS),
        [tag.name for tag in book.tags],
    )


def _attach_report(book: Book) -> Book:
    """詳細（BookDetail）で返すレポート本文をファイルから読んで付ける。

    `report_md` はモデルの列ではなくなったので、ここで付けた値がそのまま
    レスポンスになる（DB には書き戻らない）。一覧では本文が要らないので呼ばない。
    """
    book.report_md = report_store.read(book.id)
    return book


@router.get("", response_model=list[BookRead])
def list_books(
    book_status: BookStatus | None = Query(default=None, alias="status"),
    sort: BookSort | None = Query(default=None),
    tag: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """本の一覧。

    - `?status=finished` で状態を絞り込む
    - `?tag=技術書` でタグで絞り込む
    - `?sort=title` で並び替える。省略したときは設定画面の並び順に従う
    """
    if sort is None:
        sort = get_settings(db).sort
    stmt = (
        select(Book)
        # tags / readings を1件ずつ取りに行かせない
        .options(selectinload(Book.tags), selectinload(Book.readings))
        .order_by(*_SORT_ORDERS[sort], Book.id.desc())
    )
    if book_status is not None:
        stmt = stmt.where(Book.status == book_status)
    if tag is not None:
        stmt = stmt.where(Book.tags.any(Tag.name == tag))
    return _with_counts(db, list(db.scalars(stmt).unique().all()))


@router.get("/{book_id}", response_model=BookDetail)
def get_book(book_id: int, db: Session = Depends(get_db)):
    book = _get_book_or_404(db, book_id)
    _with_counts(db, [book])
    return _attach_report(book)


@router.post("", response_model=BookDetail, status_code=201)
def create_book(payload: BookCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    tag_names = data.pop("tags", [])
    book = Book(**data)
    book.tags = _resolve_tags(db, tag_names)
    _apply_progress_rules(book, payload.model_fields_set)
    db.add(book)
    _commit(db)
    db.refresh(book)

    # 読了として登録された本も、1回読んだことにする
    if book.status == BookStatus.FINISHED:
        _record_reading(db, book)
        _commit(db)
        db.refresh(book)

    _with_counts(db, [book])
    return _attach_report(book)


@router.patch("/{book_id}", response_model=BookDetail)
def update_book(book_id: int, payload: BookUpdate, db: Session = Depends(get_db)):
    book = _get_book_or_404(db, book_id)
    was_finished = book.status == BookStatus.FINISHED
    meta_before = _report_meta_snapshot(book)

    # exclude_unset=True で「送られてきた項目だけ」を取り出す
    changes = payload.model_dump(exclude_unset=True)
    # レポート本文は DB の列ではなくファイル。ここで取り除いておかないと
    # setattr で ORM に乗ってしまい、どこにも保存されないまま消える。
    report_sent = "report_md" in changes
    report_body = changes.pop("report_md", None)
    if "tags" in changes:
        book.tags = _resolve_tags(db, changes.pop("tags") or [])
    for key, value in changes.items():
        setattr(book, key, value)
    _apply_progress_rules(book, set(changes))

    # 読了になった瞬間だけ「読み終えた」記録を足す。
    # 読書中に戻して読み直し、また読了にすると2行目が増える（再読）
    if not was_finished and book.status == BookStatus.FINISHED:
        _commit(db)
        db.refresh(book)
        _record_reading(db, book)

    _commit(db)
    db.refresh(book)

    # 本文の保存は DB のコミット後。frontmatter に載せる書誌が確定してから書く。
    if report_sent:
        report_store.save(book, report_body)
    elif _report_meta_snapshot(book) != meta_before:
        # frontmatter の複製を追従させる。送られたキーではなく値の変化で見るのは、
        # ページ進捗から自動で読了・読了日が入る場合も拾うため。ページ進捗だけで
        # 何も変わらない更新では書き直さない（mtime が動くと週次コミットの差分がノイズになる）。
        report_store.refresh_meta(book)

    _with_counts(db, [book])
    return _attach_report(book)


@router.delete("/{book_id}", status_code=204)
def delete_book(book_id: int, db: Session = Depends(get_db)):
    book = _get_book_or_404(db, book_id)
    db.delete(book)
    db.commit()
    # 本を消したらレポートのファイルも消す（孤児を残さない）。
    # 消したファイルは reports/.trash/ に残る。DB はもう確定しているので、
    # ファイル側の失敗で 500 にはしない。
    try:
        report_store.delete(book_id)
    except OSError:
        logger.exception("本 %s のレポートファイルを片付けられなかった", book_id)


# ---------------------------------------------------------------- 表紙

@router.put("/{book_id}/cover", response_model=BookDetail)
async def set_cover(
    book_id: int,
    file: UploadFile = File(),
    db: Session = Depends(get_db),
):
    """表紙の画像を入れ替える。

    国会図書館に書影が無い本のための手入力。撮った写真をそのまま入れると
    DBが膨らむので、保存する前に縮めて JPEG に揃える。
    """
    book = _get_book_or_404(db, book_id)

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="ファイルが空です")
    if len(raw) > covers.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"画像が大きすぎます（{covers.MAX_UPLOAD_BYTES // 1024 // 1024}MBまで）",
        )
    try:
        data, content_type = covers.normalize(raw)
    except covers.InvalidImageError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    existing = db.get(BookCover, book_id)
    if existing is None:
        db.add(BookCover(book_id=book_id, data=data, content_type=content_type))
    else:
        existing.data = data
        existing.content_type = content_type

    # 画面はこのURLを見る。中身を入れ替えても URL は変わらないので、
    # ブラウザに古い画像を出されないよう更新時刻を付ける
    book.cover_url = f"/api/books/{book_id}/cover?v={int(now_jst().timestamp())}"
    _commit(db)
    db.refresh(book)
    _with_counts(db, [book])
    return book


@router.get("/{book_id}/cover")
def get_cover(book_id: int, db: Session = Depends(get_db)):
    """自分で入れた表紙を返す"""
    cover = db.get(BookCover, book_id)
    if cover is None:
        raise HTTPException(status_code=404, detail="表紙が登録されていません")
    return Response(
        content=cover.data,
        media_type=cover.content_type,
        # URL に更新時刻を付けているので、長めにキャッシュさせてよい
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.delete("/{book_id}/cover", response_model=BookDetail)
def delete_cover(book_id: int, db: Session = Depends(get_db)):
    """自分で入れた表紙を外す"""
    book = _get_book_or_404(db, book_id)
    cover = db.get(BookCover, book_id)
    if cover is not None:
        db.delete(cover)
    book.cover_url = None
    _commit(db)
    db.refresh(book)
    _with_counts(db, [book])
    return book
