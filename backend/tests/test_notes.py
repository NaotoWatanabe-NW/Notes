"""引用・メモのAPIのテスト"""
from sqlalchemy import text


def _create_book(client, title="達人プログラマー"):
    return client.post("/api/books", json={"title": title}).json()


def _create_note(client, book_id, **fields):
    payload = {"kind": "memo", "text": "DRY原則の話が刺さった"} | fields
    response = client.post(f"/api/books/{book_id}/notes", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# --- 作成 ---

def test_引用を記録すると201と内容が返る(client):
    book = _create_book(client)
    response = client.post(
        f"/api/books/{book['id']}/notes",
        json={
            "kind": "quote",
            "page": 182,
            "text": "早すぎる最適化は諸悪の根源である",
            "memo": "自分のコードにも心当たりがある",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "quote"
    assert body["page"] == 182
    assert body["memo"] == "自分のコードにも心当たりがある"
    assert body["book_id"] == book["id"]


def test_ページを書かないメモも作成できる(client):
    # 読んだ場所が思い出せないメモも残せるようにする
    assert _create_note(client, _create_book(client)["id"])["page"] is None


def test_種別を送らないと422になる(client):
    book = _create_book(client)
    assert client.post(f"/api/books/{book['id']}/notes", json={"text": "x"}).status_code == 422


def test_知らない種別は422になる(client):
    book = _create_book(client)
    response = client.post(
        f"/api/books/{book['id']}/notes", json={"kind": "感想", "text": "x"}
    )
    assert response.status_code == 422


def test_本文が空だと422になる(client):
    book = _create_book(client)
    response = client.post(f"/api/books/{book['id']}/notes", json={"kind": "memo", "text": ""})
    assert response.status_code == 422


def test_ページに0を送ると422になる(client):
    book = _create_book(client)
    response = client.post(
        f"/api/books/{book['id']}/notes", json={"kind": "quote", "text": "x", "page": 0}
    )
    assert response.status_code == 422


def test_存在しない本にノートを作ると404になる(client):
    assert client.post("/api/books/9999/notes", json={"kind": "memo", "text": "x"}).status_code == 404


def test_知らない項目を送ると422になる(client):
    book = _create_book(client)
    response = client.post(
        f"/api/books/{book['id']}/notes", json={"kind": "memo", "text": "x", "tag": "設計"}
    )
    assert response.status_code == 422


# --- 本ごとの一覧 ---

def test_本ごとの一覧はページの大きい順に返る(client):
    # 本の詳細では、読み進めた順ではなく後ろのページから見たい
    book = _create_book(client)
    _create_note(client, book["id"], text="12ページ", page=12)
    _create_note(client, book["id"], text="180ページ", page=180)
    _create_note(client, book["id"], text="96ページ", page=96)
    texts = [n["text"] for n in client.get(f"/api/books/{book['id']}/notes").json()]
    assert texts == ["180ページ", "96ページ", "12ページ"]


def test_ページの無いノートは後ろに回る(client):
    book = _create_book(client)
    _create_note(client, book["id"], text="ページなし")
    _create_note(client, book["id"], text="12ページ", page=12)
    texts = [n["text"] for n in client.get(f"/api/books/{book['id']}/notes").json()]
    assert texts == ["12ページ", "ページなし"]


def test_本ごとの一覧に他の本のノートは混ざらない(client):
    book_a = _create_book(client, "本A")
    book_b = _create_book(client, "本B")
    _create_note(client, book_a["id"], text="Aのノート")
    _create_note(client, book_b["id"], text="Bのノート")
    texts = [n["text"] for n in client.get(f"/api/books/{book_a['id']}/notes").json()]
    assert texts == ["Aのノート"]


def test_存在しない本のノート一覧は404になる(client):
    assert client.get("/api/books/9999/notes").status_code == 404


# --- 横断一覧（メモ・引用ビュー） ---

def test_横断一覧は新しい順に全部の本のノートを返す(client):
    book_a = _create_book(client, "本A")
    book_b = _create_book(client, "本B")
    _create_note(client, book_a["id"], text="先に書いた")
    _create_note(client, book_b["id"], text="後に書いた")
    texts = [n["text"] for n in client.get("/api/notes").json()]
    assert texts == ["後に書いた", "先に書いた"]


def test_横断一覧には出典の本が付いてくる(client):
    book = _create_book(client, "達人プログラマー")
    _create_note(client, book["id"])
    note = client.get("/api/notes").json()[0]
    assert note["book"]["id"] == book["id"]
    assert note["book"]["title"] == "達人プログラマー"


def test_横断一覧を種別で絞り込める(client):
    book = _create_book(client)
    _create_note(client, book["id"], kind="memo", text="メモです")
    _create_note(client, book["id"], kind="quote", text="引用です", page=1)
    texts = [n["text"] for n in client.get("/api/notes", params={"kind": "quote"}).json()]
    assert texts == ["引用です"]


def test_ノート単体を取得すると本の情報も付いてくる(client):
    book = _create_book(client, "本A")
    note = _create_note(client, book["id"])
    body = client.get(f"/api/notes/{note['id']}").json()
    assert body["book"]["title"] == "本A"


def test_存在しないノートを取得すると404になる(client):
    assert client.get("/api/notes/9999").status_code == 404


# --- 更新 ---

def test_送った項目だけが更新される(client):
    book = _create_book(client)
    note = _create_note(client, book["id"], kind="quote", text="元の引用", page=10)
    updated = client.patch(f"/api/notes/{note['id']}", json={"text": "直した引用"}).json()
    assert updated["text"] == "直した引用"
    assert updated["page"] == 10
    assert updated["kind"] == "quote"


def test_引用からメモに種別を変えられる(client):
    book = _create_book(client)
    note = _create_note(client, book["id"], kind="quote", text="引用", page=1)
    assert client.patch(f"/api/notes/{note['id']}", json={"kind": "memo"}).json()["kind"] == "memo"


def test_ページを後から足せる(client):
    # 電子書籍で読んだあと、紙の版のページが分かったときなど
    book = _create_book(client)
    note = _create_note(client, book["id"], text="ページ無しで書いたメモ")
    assert client.patch(f"/api/notes/{note['id']}", json={"page": 96}).json()["page"] == 96


def test_ページをnullにして消せる(client):
    # 電子書籍はページが可変なので、入れた数字を取り消せる必要がある
    book = _create_book(client)
    note = _create_note(client, book["id"], page=96)
    assert client.patch(f"/api/notes/{note['id']}", json={"page": None}).json()["page"] is None


def test_更新でページに0を送ると422になる(client):
    book = _create_book(client)
    note = _create_note(client, book["id"], page=96)
    assert client.patch(f"/api/notes/{note['id']}", json={"page": 0}).status_code == 422


def test_補足メモをnullにして消せる(client):
    book = _create_book(client)
    note = _create_note(client, book["id"], kind="quote", text="引用", memo="補足")
    assert client.patch(f"/api/notes/{note['id']}", json={"memo": None}).json()["memo"] is None


def test_本文にnullを送ると422になる(client):
    book = _create_book(client)
    note = _create_note(client, book["id"])
    assert client.patch(f"/api/notes/{note['id']}", json={"text": None}).status_code == 422


def test_種別にnullを送ると422になる(client):
    book = _create_book(client)
    note = _create_note(client, book["id"])
    assert client.patch(f"/api/notes/{note['id']}", json={"kind": None}).status_code == 422


def test_存在しないノートを更新すると404になる(client):
    assert client.patch("/api/notes/9999", json={"text": "x"}).status_code == 404


# --- 削除と連鎖削除 ---

def test_ノートを削除すると204になり一覧から消える(client):
    book = _create_book(client)
    note = _create_note(client, book["id"])
    assert client.delete(f"/api/notes/{note['id']}").status_code == 204
    assert client.get(f"/api/books/{book['id']}/notes").json() == []


def test_存在しないノートを削除すると404になる(client):
    assert client.delete("/api/notes/9999").status_code == 404


def test_本を削除するとその本のノートも消える(client, db_engine):
    book = _create_book(client)
    _create_note(client, book["id"], text="消えるはずのノート")
    assert client.delete(f"/api/books/{book['id']}").status_code == 204
    with db_engine.connect() as conn:
        assert conn.execute(text("select count(*) from notes")).scalar() == 0


def test_本を削除しても他の本のノートは残る(client):
    book_a = _create_book(client, "本A")
    book_b = _create_book(client, "本B")
    _create_note(client, book_a["id"], text="Aのノート")
    _create_note(client, book_b["id"], text="Bのノート")
    client.delete(f"/api/books/{book_a['id']}")
    texts = [n["text"] for n in client.get(f"/api/books/{book_b['id']}/notes").json()]
    assert texts == ["Bのノート"]


def test_存在しない本のidでノートを直接作れない(client, db_engine):
    # 外部キー制約が効いていれば、DBが直接の挿入を拒否する
    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            conn.execute(
                text(
                    "insert into notes (book_id, kind, text, created_at, updated_at)"
                    " values (9999, 'memo', 'x', '2026-01-01', '2026-01-01')"
                )
            )
