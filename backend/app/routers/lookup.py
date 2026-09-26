"""ISBN から本の情報・書影を取ってくる API（保存はしない）"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from .. import booklookup
from ..isbn import InvalidIsbnError
from ..isbn import normalize as normalize_isbn

router = APIRouter(prefix="/api", tags=["lookup"])


def _normalized_or_422(raw: str) -> str:
    try:
        isbn = normalize_isbn(raw)
    except InvalidIsbnError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if isbn is None:
        raise HTTPException(status_code=422, detail="ISBNを入力してください")
    return isbn


@router.get("/isbn/{raw_isbn}", response_model=booklookup.BookInfo)
def lookup_isbn(
    raw_isbn: str,
    client: httpx.Client = Depends(booklookup.get_http_client),
):
    """ISBN から本の情報を調べて返す（DBには保存しない）。

    フォームの自動入力用。見つからなければ 404 を返すので、画面側は
    「見つかりませんでした。手で入力してください」と出して先に進める。
    """
    isbn = _normalized_or_422(raw_isbn)
    info = booklookup.lookup(client, isbn)
    if info is None:
        raise HTTPException(
            status_code=404, detail="この ISBN の本が見つかりませんでした"
        )
    return info


@router.get("/search", response_model=list[booklookup.BookInfo])
def search_books(
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=4, ge=1, le=10),
    client: httpx.Client = Depends(booklookup.get_http_client),
):
    """書名・著者で本を探す。⌘K と本の追加画面で使う（DBには保存しない）"""
    try:
        return booklookup.search(client, q.strip(), limit=limit)
    except booklookup.SearchUnavailable as error:
        # 「見つからなかった」ではなく「今は引けなかった」。
        # 画面が「その本はありません」と嘘をつかないよう 503 で伝える
        raise HTTPException(
            status_code=503,
            detail="いま本を探せませんでした。少し待ってからもう一度お試しください",
        ) from error


@router.get("/covers/{raw_isbn}")
def get_cover(
    raw_isbn: str,
    client: httpx.Client = Depends(booklookup.get_http_client),
):
    """書影を中継して返す。

    国会図書館サーチの画像は Referer がないと 403 になる。ブラウザが
    <img src> で直接読むとその Referer が付かないので、ここで付け直す。
    """
    isbn = _normalized_or_422(raw_isbn)
    response = booklookup.fetch_ndl_cover(client, isbn)
    if response is None:
        raise HTTPException(status_code=404, detail="書影が見つかりませんでした")

    return Response(
        content=response.content,
        media_type=response.headers.get("content-type", "image/jpeg"),
        # 表紙は変わらないので、ブラウザに1日キャッシュさせて毎回取りに行かない
        headers={"Cache-Control": "public, max-age=86400"},
    )
