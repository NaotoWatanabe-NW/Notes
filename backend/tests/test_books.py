"""本のAPIのテスト"""
from datetime import datetime, timedelta

from sqlalchemy import text

from app.timeutil import JST, today_jst


def _create(client, **fields):
    """テスト用に1冊登録して、返ってきた本の情報を返す"""
    payload = {"title": "達人プログラマー"} | fields
    response = client.post("/api/books", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _add_note(client, book_id, **fields):
    payload = {"kind": "memo", "text": "メモ"} | fields
    response = client.post(f"/api/books/{book_id}/notes", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# --- 登録 ---

def test_本を登録すると201と登録した内容が返る(client):
    response = client.post(
        "/api/books",
        json={
            "title": "達人プログラマー",
            "author": "David Thomas",
            "publisher": "オーム社",
            "total": 422,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "達人プログラマー"
    assert body["publisher"] == "オーム社"
    assert body["total"] == 422
    assert body["status"] == "unread"
    assert body["page"] == 0


def test_同じISBNの本を登録すると409になる(client):
    _create(client, isbn="9784274226298")
    response = client.post(
        "/api/books", json={"title": "別のタイトル", "isbn": "9784274226298"}
    )
    assert response.status_code == 409


def test_評価に6を送ると422になる(client):
    assert client.post("/api/books", json={"title": "x", "rating": 6}).status_code == 422


def test_総ページに0を送ると422になる(client):
    assert client.post("/api/books", json={"title": "x", "total": 0}).status_code == 422


def test_読んだページに負の数を送ると422になる(client):
    assert client.post("/api/books", json={"title": "x", "page": -1}).status_code == 422


def test_登録時に知らない項目を送ると422になる(client):
    response = client.post("/api/books", json={"title": "x", "publishr": "誤字"})
    assert response.status_code == 422


# --- ISBN の正規化 ---

def test_ハイフン付きISBNで登録でき13桁に正規化される(client):
    assert _create(client, isbn="978-4-274-22629-8")["isbn"] == "9784274226298"


def test_ISBN10で登録するとISBN13に変換して保存される(client):
    assert _create(client, isbn="4274226298")["isbn"] == "9784274226298"


def test_空文字のISBNはNoneとして扱われ複数登録できる(client):
    assert _create(client, title="1冊目", isbn="")["isbn"] is None
    assert _create(client, title="2冊目", isbn="")["isbn"] is None


def test_チェックディジットが合わないISBNは422になる(client):
    response = client.post("/api/books", json={"title": "x", "isbn": "9784274226299"})
    assert response.status_code == 422


# --- 進捗と状態のつじつま ---

def test_進捗を記録すると読んだ割合が計算される(client):
    book = _create(client, total=320)
    updated = client.patch(f"/api/books/{book['id']}", json={"page": 182}).json()
    # 182 / 320 = 56.875% → 57%
    assert updated["progress"] == 57


def test_総ページが分からない本の割合はnullになる(client):
    book = _create(client)
    assert client.patch(f"/api/books/{book['id']}", json={"page": 50}).json()["progress"] is None


def test_最後のページまで読むと自動で読了になる(client):
    # デザインの仕様: 進捗が総ページに達したら状態を読了にする
    book = _create(client, total=320, status="reading")
    updated = client.patch(f"/api/books/{book['id']}", json={"page": 320}).json()
    assert updated["status"] == "finished"
    assert updated["finished_on"] == today_jst().isoformat()
    assert updated["progress"] == 100


def test_総ページを超えて読んでも割合は100を超えない(client):
    book = _create(client, total=100, status="reading")
    assert client.patch(f"/api/books/{book['id']}", json={"page": 150}).json()["progress"] == 100


def test_総ページに届かなければ読書中のまま(client):
    book = _create(client, total=320, status="reading")
    assert client.patch(f"/api/books/{book['id']}", json={"page": 319}).json()["status"] == "reading"


def test_読み始めると開始日が今日で自動的に入る(client):
    book = _create(client)
    updated = client.patch(f"/api/books/{book['id']}", json={"status": "reading"}).json()
    assert updated["started_on"] == today_jst().isoformat()


def test_開始日を指定したら自動補完で上書きされない(client):
    book = _create(client, status="reading", started_on="2026-01-15")
    assert book["started_on"] == "2026-01-15"


def test_積読のままなら開始日は入らない(client):
    assert _create(client)["started_on"] is None


def test_読了にすると読了日が今日で自動的に入る(client):
    book = _create(client)
    updated = client.patch(f"/api/books/{book['id']}", json={"status": "finished"}).json()
    assert updated["finished_on"] == today_jst().isoformat()


def test_読了から読書中に戻しても読了日は残る(client):
    # 一度読み終えた日付は記録として残す（再読のときに前回が分かる）
    book = _create(client, status="finished")
    updated = client.patch(f"/api/books/{book['id']}", json={"status": "reading"}).json()
    assert updated["finished_on"] == today_jst().isoformat()


def test_読了日にnullを明示的に送ると消える(client):
    book = _create(client, status="finished")
    assert client.patch(f"/api/books/{book['id']}", json={"finished_on": None}).json()["finished_on"] is None


# --- 一覧に出す集計値 ---

def test_一覧にノート件数が入る(client):
    book = _create(client)
    _add_note(client, book["id"])
    _add_note(client, book["id"], kind="quote", text="引用", page=10)
    assert client.get("/api/books").json()[0]["note_count"] == 2


def test_ノートが無い本の件数は0になる(client):
    _create(client)
    assert client.get("/api/books").json()[0]["note_count"] == 0


def test_レポートを書いた本には印が付く(client):
    book = _create(client)
    assert client.get("/api/books").json()[0]["has_report"] is False
    client.patch(f"/api/books/{book['id']}", json={"report_md": "## 感想"})
    assert client.get("/api/books").json()[0]["has_report"] is True


def test_一覧にはレポート本文を含めず詳細では返す(client):
    # レポートは長くなるので、一覧では有無だけ返す
    book = _create(client)
    client.patch(f"/api/books/{book['id']}", json={"report_md": "## 長い感想"})
    assert "report_md" not in client.get("/api/books").json()[0]
    assert client.get(f"/api/books/{book['id']}").json()["report_md"] == "## 長い感想"


# --- 並び替え ---

def test_一覧は既定で登録の新しい順に返る(client):
    _create(client, title="先に登録した本")
    _create(client, title="後に登録した本")
    titles = [b["title"] for b in client.get("/api/books").json()]
    assert titles == ["後に登録した本", "先に登録した本"]


def test_評価を変えても一覧の並びは動かない(client):
    first = _create(client, title="先に登録した本")
    _create(client, title="後に登録した本")
    client.patch(f"/api/books/{first['id']}", json={"rating": 5})
    titles = [b["title"] for b in client.get("/api/books").json()]
    assert titles == ["後に登録した本", "先に登録した本"]


def test_書名順に並び替えられる(client):
    _create(client, title="Refactoring")
    _create(client, title="Clean Code")
    response = client.get("/api/books", params={"sort": "title"})
    assert [b["title"] for b in response.json()] == ["Clean Code", "Refactoring"]


def test_進捗順では読み進んでいる本が先頭に来る(client):
    _create(client, title="半分", total=100, page=50)
    _create(client, title="ほぼ読了", total=100, page=90)
    _create(client, title="総ページ不明", page=10)
    response = client.get("/api/books", params={"sort": "progress"})
    # 割合を出せない本は後ろに回す
    assert [b["title"] for b in response.json()] == ["ほぼ読了", "半分", "総ページ不明"]


def test_並び順を指定しなければ設定の並び順に従う(client):
    _create(client, title="Refactoring")
    _create(client, title="Clean Code")
    client.patch("/api/settings", json={"sort": "title"})
    assert [b["title"] for b in client.get("/api/books").json()] == [
        "Clean Code",
        "Refactoring",
    ]


def test_知らない並び替えキーを指定すると422になる(client):
    assert client.get("/api/books", params={"sort": "rating"}).status_code == 422


def test_状態で一覧を絞り込める(client):
    _create(client, title="積んでる本")
    _create(client, title="読んだ本", status="finished")
    response = client.get("/api/books", params={"status": "finished"})
    assert [b["title"] for b in response.json()] == ["読んだ本"]


# --- 更新・削除 ---

def test_送った項目だけが更新され他の項目は変わらない(client):
    book = _create(client, author="David Thomas", rating=3)
    body = client.patch(f"/api/books/{book['id']}", json={"rating": 5}).json()
    assert body["rating"] == 5
    assert body["author"] == "David Thomas"


def test_おすすめ度を記録できる(client):
    book = _create(client, status="finished")
    assert client.patch(f"/api/books/{book['id']}", json={"recommend": "strong"}).json()["recommend"] == "strong"


def test_知らないおすすめ度は422になる(client):
    book = _create(client)
    assert client.patch(f"/api/books/{book['id']}", json={"recommend": "maybe"}).status_code == 422


def test_タイトルにnullを送ると422になる(client):
    # 修正前はここで NOT NULL 違反が起き、ISBN重複を示す 409 が返っていた
    book = _create(client)
    assert client.patch(f"/api/books/{book['id']}", json={"title": None}).status_code == 422


def test_状態にnullを送ると422になる(client):
    book = _create(client)
    assert client.patch(f"/api/books/{book['id']}", json={"status": None}).status_code == 422


def test_読んだページにnullを送ると422になる(client):
    book = _create(client)
    assert client.patch(f"/api/books/{book['id']}", json={"page": None}).status_code == 422


def test_知らない項目を送ると422になる(client):
    book = _create(client)
    assert client.patch(f"/api/books/{book['id']}", json={"ratng": 5}).status_code == 422


def test_他の本と同じISBNに更新すると409になる(client):
    _create(client, title="1冊目", isbn="9784274226298")
    second = _create(client, title="2冊目")
    response = client.patch(f"/api/books/{second['id']}", json={"isbn": "9784274226298"})
    assert response.status_code == 409


def test_存在しない本を更新すると404になる(client):
    assert client.patch("/api/books/9999", json={"rating": 3}).status_code == 404


def test_本を削除すると204になりその後は取得できない(client):
    book = _create(client)
    assert client.delete(f"/api/books/{book['id']}").status_code == 204
    assert client.get(f"/api/books/{book['id']}").status_code == 404


def test_存在しない本を削除すると404になる(client):
    assert client.delete("/api/books/9999").status_code == 404


# --- 保存されている形 ---

def test_作成日時がJSTで記録される(client):
    # SQLite の CURRENT_TIMESTAMP（UTC）だと finished_on と9時間ずれる
    created_at = datetime.fromisoformat(_create(client)["created_at"])
    now = datetime.now(JST).replace(tzinfo=None)
    assert abs(now - created_at) < timedelta(seconds=10)


def test_DBには状態が小文字の値で保存される(client, db_engine):
    # 既定のままだと enum の名前 'READING' が保存され、APIの 'reading' と食い違う
    book = _create(client)
    client.patch(f"/api/books/{book['id']}", json={"status": "reading"})
    with db_engine.connect() as conn:
        stored = conn.execute(
            text("select status from books where id = :id"), {"id": book["id"]}
        ).scalar()
    assert stored == "reading"


def test_外部キー制約が有効になっている(client, db_engine):
    # SQLite は既定で外部キーが無効。ノートの紐づけに必要
    with db_engine.connect() as conn:
        assert conn.execute(text("pragma foreign_keys")).scalar() == 1


# --- タグ ---

def test_タグを付けて登録できる(client):
    book = _create(client, tags=["技術書", "設計"])
    assert book["tags"] == ["技術書", "設計"]


def test_タグを付け替えられる(client):
    book = _create(client, tags=["技術書"])
    updated = client.patch(f"/api/books/{book['id']}", json={"tags": ["小説"]}).json()
    assert updated["tags"] == ["小説"]


def test_タグを空にできる(client):
    book = _create(client, tags=["技術書"])
    assert client.patch(f"/api/books/{book['id']}", json={"tags": []}).json()["tags"] == []


def test_同じタグ名を二重に付けない(client):
    assert _create(client, tags=["技術書", "技術書"])["tags"] == ["技術書"]


def test_タグの前後の空白は落とす(client):
    assert _create(client, tags=["  技術書  "])["tags"] == ["技術書"]


def test_空白だけのタグは無視する(client):
    assert _create(client, tags=["   "])["tags"] == []


def test_同じタグ名は共有される(client, db_engine):
    # 2冊に同じタグを付けても、タグの行は1つだけにする
    _create(client, title="A", tags=["技術書"])
    _create(client, title="B", tags=["技術書"])
    with db_engine.connect() as conn:
        assert conn.execute(text("select count(*) from tags")).scalar() == 1


def test_タグで一覧を絞り込める(client):
    _create(client, title="技術の本", tags=["技術書"])
    _create(client, title="小説", tags=["小説"])
    titles = [b["title"] for b in client.get("/api/books", params={"tag": "技術書"}).json()]
    assert titles == ["技術の本"]


def test_本を削除してもタグ自体は消えない(client, db_engine):
    book = _create(client, title="A", tags=["技術書"])
    _create(client, title="B", tags=["技術書"])
    client.delete(f"/api/books/{book['id']}")
    with db_engine.connect() as conn:
        assert conn.execute(text("select count(*) from tags")).scalar() == 1
        # 結び付きの方は消える
        assert conn.execute(text("select count(*) from book_tags")).scalar() == 1


# --- 読み終えた回数（再読） ---

def test_読了にすると読んだ回数が1になる(client):
    book = _create(client)
    updated = client.patch(f"/api/books/{book['id']}", json={"status": "finished"}).json()
    assert updated["read_count"] == 1
    assert [r["finished_on"] for r in updated["readings"]] == [today_jst().isoformat()]


def test_読了として登録した本も1回読んだことになる(client):
    assert _create(client, status="finished")["read_count"] == 1


def test_読書中のうちは回数が0のまま(client):
    assert _create(client, status="reading")["read_count"] == 0


def test_もう一度読んで読了にすると回数が2になる(client):
    book = _create(client, status="finished", finished_on="2024-05-01")
    # もう一度読む: 読書中に戻して進捗をリセットする
    client.patch(f"/api/books/{book['id']}", json={"status": "reading", "page": 0})
    updated = client.patch(
        f"/api/books/{book['id']}", json={"status": "finished", "finished_on": "2026-09-20"}
    ).json()
    assert updated["read_count"] == 2
    assert [r["finished_on"] for r in updated["readings"]] == ["2026-09-20", "2024-05-01"]


def test_読了のまま更新しても回数は増えない(client):
    book = _create(client, status="finished")
    updated = client.patch(f"/api/books/{book['id']}", json={"rating": 5}).json()
    assert updated["read_count"] == 1


def test_同じ日に二重で読了記録を作らない(client):
    book = _create(client, status="finished")
    client.patch(f"/api/books/{book['id']}", json={"status": "reading"})
    updated = client.patch(f"/api/books/{book['id']}", json={"status": "finished"}).json()
    assert updated["read_count"] == 1


def test_本を削除すると読了の記録も消える(client, db_engine):
    book = _create(client, status="finished")
    client.delete(f"/api/books/{book['id']}")
    with db_engine.connect() as conn:
        assert conn.execute(text("select count(*) from readings")).scalar() == 0


# --- カテゴリ ---

def test_カテゴリを付けて登録できる(client):
    book = _create(client, genre="novel")
    assert book["genre"] == "novel"
    assert client.get(f"/api/books/{book['id']}").json()["genre"] == "novel"


def test_カテゴリを指定しなければその他になる(client):
    assert _create(client)["genre"] == "other"


def test_カテゴリを変えられる(client):
    book = _create(client, genre="novel")
    response = client.patch(f"/api/books/{book['id']}", json={"genre": "academic"})
    assert response.status_code == 200
    assert response.json()["genre"] == "academic"


def test_カテゴリはnullで空にできない(client):
    # 画面は6つのどれかを選ぶだけで、未分類は作らない（デザイン 8b）
    book = _create(client, genre="essay")
    response = client.patch(f"/api/books/{book['id']}", json={"genre": None})
    assert response.status_code == 422
    assert client.get(f"/api/books/{book['id']}").json()["genre"] == "essay"


def test_カテゴリが入っていない古い本はその他として返る(client, db_engine):
    book = _create(client)
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE books SET genre = NULL WHERE id = :id"), {"id": book["id"]})
    assert client.get(f"/api/books/{book['id']}").json()["genre"] == "other"
    assert client.get("/api/books").json()[0]["genre"] == "other"


def test_ほかの項目を更新してもカテゴリは変わらない(client):
    # PATCH は送らなかった項目を変えない
    book = _create(client, genre="business")
    client.patch(f"/api/books/{book['id']}", json={"rating": 4})
    assert client.get(f"/api/books/{book['id']}").json()["genre"] == "business"


def test_知らないカテゴリは422になる(client):
    assert client.post("/api/books", json={"title": "A", "genre": "comic"}).status_code == 422


def test_一覧にもカテゴリが入る(client):
    _create(client, title="A", genre="magazine")
    assert client.get("/api/books").json()[0]["genre"] == "magazine"
