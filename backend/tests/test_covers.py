"""自分で入れる表紙画像のテスト"""
import io
import time

import pytest
from PIL import Image
from sqlalchemy import text

from app import covers


def _image_bytes(size=(400, 600), mode="RGB", fmt="PNG") -> bytes:
    """テスト用の画像を作る"""
    image = Image.new(mode, size, (200, 40, 40) if mode == "RGB" else (200, 40, 40, 128))
    out = io.BytesIO()
    image.save(out, format=fmt)
    return out.getvalue()


def _book(client, title="達人プログラマー"):
    return client.post("/api/books", json={"title": title}).json()


def _upload(client, book_id, data=None, name="cover.png", content_type="image/png"):
    return client.put(
        f"/api/books/{book_id}/cover",
        files={"file": (name, data if data is not None else _image_bytes(), content_type)},
    )


# --- 入れる ---

def test_表紙を入れると本にURLが入る(client):
    book = _book(client)
    body = _upload(client, book["id"]).json()
    assert body["cover_url"].startswith(f"/api/books/{book['id']}/cover")


def test_入れた表紙を取り出せる(client):
    book = _book(client)
    _upload(client, book["id"])
    response = client.get(f"/api/books/{book['id']}/cover")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    # 画像として読み戻せる
    assert Image.open(io.BytesIO(response.content)).size == (400, 600)


def test_大きな画像は縮めて保存される(client):
    # 撮った写真をそのまま入れるとDBが膨らむので、保存前に縮める
    book = _book(client)
    _upload(client, book["id"], data=_image_bytes(size=(2000, 3000)))
    stored = Image.open(io.BytesIO(client.get(f"/api/books/{book['id']}/cover").content))
    assert stored.width <= covers.MAX_SIZE[0]
    assert stored.height <= covers.MAX_SIZE[1]
    # 縦横比は保つ
    assert abs(stored.width / stored.height - 2000 / 3000) < 0.01


def test_小さい画像は引き伸ばさない(client):
    book = _book(client)
    _upload(client, book["id"], data=_image_bytes(size=(100, 150)))
    stored = Image.open(io.BytesIO(client.get(f"/api/books/{book['id']}/cover").content))
    assert stored.size == (100, 150)


def test_透過画像も入れられる(client):
    # JPEG は透過を持てないので、白で埋めてから保存する
    book = _book(client)
    response = _upload(client, book["id"], data=_image_bytes(mode="RGBA"))
    assert response.status_code == 200
    stored = Image.open(io.BytesIO(client.get(f"/api/books/{book['id']}/cover").content))
    assert stored.mode == "RGB"


def test_JPEGも入れられる(client):
    book = _book(client)
    response = _upload(
        client, book["id"], data=_image_bytes(fmt="JPEG"), name="c.jpg",
        content_type="image/jpeg",
    )
    assert response.status_code == 200


def test_入れ直すと差し替わる(client):
    book = _book(client)
    _upload(client, book["id"], data=_image_bytes(size=(400, 600)))
    _upload(client, book["id"], data=_image_bytes(size=(300, 450)))
    stored = Image.open(io.BytesIO(client.get(f"/api/books/{book['id']}/cover").content))
    assert stored.size == (300, 450)


def test_入れ直すとURLが変わる(client):
    # URL が同じだと、ブラウザが古い画像を出し続けてしまう
    book = _book(client)
    first = _upload(client, book["id"]).json()["cover_url"]
    time.sleep(1.1)
    second = _upload(client, book["id"]).json()["cover_url"]
    assert first != second


# --- 受け付けないもの ---

def test_画像でないファイルは422になる(client):
    book = _book(client)
    response = _upload(client, book["id"], data="これは画像ではありません".encode())
    assert response.status_code == 422


def test_空のファイルは422になる(client):
    book = _book(client)
    response = _upload(client, book["id"], data=b"")
    assert response.status_code == 422


def test_大きすぎるファイルは413になる(client):
    book = _book(client)
    response = _upload(client, book["id"], data=b"x" * (covers.MAX_UPLOAD_BYTES + 1))
    assert response.status_code == 413


def test_存在しない本には入れられない(client):
    assert _upload(client, 9999).status_code == 404


# --- 取り出す・外す ---

def test_表紙が無い本の取得は404になる(client):
    book = _book(client)
    assert client.get(f"/api/books/{book['id']}/cover").status_code == 404


def test_表紙を外すとURLも消える(client):
    book = _book(client)
    _upload(client, book["id"])
    body = client.delete(f"/api/books/{book['id']}/cover").json()
    assert body["cover_url"] is None
    assert client.get(f"/api/books/{book['id']}/cover").status_code == 404


def test_表紙が無くても外す操作は通る(client):
    book = _book(client)
    assert client.delete(f"/api/books/{book['id']}/cover").status_code == 200


def test_本を削除すると表紙も消える(client, db_engine):
    book = _book(client)
    _upload(client, book["id"])
    client.delete(f"/api/books/{book['id']}")
    with db_engine.connect() as conn:
        assert conn.execute(text("select count(*) from book_covers")).scalar() == 0


# --- 画像の変換そのもの ---

def test_読めない中身はInvalidImageErrorになる():
    with pytest.raises(covers.InvalidImageError):
        covers.normalize(b"not an image")


def test_変換後は常にJPEGになる():
    _, content_type = covers.normalize(_image_bytes(fmt="PNG"))
    assert content_type == "image/jpeg"
