"""「次に読む本」のAPIのテスト。

候補はその場で計算せず、本ごとにあらかじめ設定しておいたものを出す。
画面が頼りにする約束ごと——設定・根拠での絞り込み・距離・ページング・
興味なし・積読への追加——をここで固める。
"""
from sqlalchemy import text


def _book(client, title, **fields):
    return client.post("/api/books", json={"title": title} | fields).json()


def _finished(client, title, **fields):
    return _book(client, title, status="finished", **fields)


def _candidate(**fields):
    base = {
        "title": "リファクタリング",
        "author": "Martin Fowler",
        "basis": "tag",
        "distance": "near",
        "reason": "よく読む「技術書」の本です",
    }
    return base | fields


def _set(client, book_id, items):
    response = client.put(f"/api/books/{book_id}/suggestions", json=items)
    assert response.status_code == 200, response.text
    return response.json()


def _get(client, book_id, **params):
    return client.get(f"/api/books/{book_id}/suggestions", params=params).json()


# --- まだ設定していないとき ---

def test_候補を設定していなければ設定済みでないと返る(client):
    # 画面はこれを見て「まだ検索していません」を出す
    book = _finished(client, "A")
    body = _get(client, book["id"])
    assert body["configured"] is False
    assert body["suggestions"] == []


def test_候補を設定すれば設定済みになる(client):
    book = _finished(client, "A")
    _set(client, book["id"], [_candidate()])
    assert _get(client, book["id"])["configured"] is True


def test_存在しない本では404になる(client):
    assert client.get("/api/books/9999/suggestions").status_code == 404
    assert client.put("/api/books/9999/suggestions", json=[]).status_code == 404


# --- 設定する ---

def test_設定した候補がそのまま返る(client):
    book = _finished(client, "A")
    _set(client, book["id"], [_candidate(title="リファクタリング", reason="設計の話に繋がります")])
    got = _get(client, book["id"])["suggestions"][0]
    assert got["title"] == "リファクタリング"
    assert got["reason"] == "設計の話に繋がります"
    assert got["added_book_id"] is None


def test_設定した順番で返る(client):
    book = _finished(client, "A")
    _set(client, book["id"], [_candidate(title="1冊目"), _candidate(title="2冊目")])
    titles = [s["title"] for s in _get(client, book["id"])["suggestions"]]
    assert titles == ["1冊目", "2冊目"]


def test_設定し直すと前のものは消える(client):
    # PUT は「追加」ではなく「入れ替え」
    book = _finished(client, "A")
    _set(client, book["id"], [_candidate(title="古い候補")])
    _set(client, book["id"], [_candidate(title="新しい候補")])
    titles = [s["title"] for s in _get(client, book["id"])["suggestions"]]
    assert titles == ["新しい候補"]


def test_空の配列を送ると全部消える(client):
    book = _finished(client, "A")
    _set(client, book["id"], [_candidate()])
    _set(client, book["id"], [])
    assert _get(client, book["id"])["configured"] is False


def test_ISBNは13桁に正規化して保存される(client):
    book = _finished(client, "A")
    _set(client, book["id"], [_candidate(isbn="978-4-274-22629-8")])
    assert _get(client, book["id"])["suggestions"][0]["isbn"] == "9784274226298"


def test_知らない根拠は422になる(client):
    book = _finished(client, "A")
    response = client.put(
        f"/api/books/{book['id']}/suggestions", json=[_candidate(basis="mood")]
    )
    assert response.status_code == 422


def test_知らない距離は422になる(client):
    book = _finished(client, "A")
    response = client.put(
        f"/api/books/{book['id']}/suggestions", json=[_candidate(distance="とおい")]
    )
    assert response.status_code == 422


def test_理由が空だと422になる(client):
    book = _finished(client, "A")
    response = client.put(
        f"/api/books/{book['id']}/suggestions", json=[_candidate(reason="")]
    )
    assert response.status_code == 422


def test_知らない項目を送ると422になる(client):
    book = _finished(client, "A")
    response = client.put(
        f"/api/books/{book['id']}/suggestions", json=[_candidate(score=5)]
    )
    assert response.status_code == 422


# --- 根拠と距離での絞り込み ---

def test_根拠で絞り込める(client):
    book = _finished(client, "A")
    _set(client, book["id"], [
        _candidate(title="メモ由来", basis="note"),
        _candidate(title="分野由来", basis="tag"),
    ])
    titles = [s["title"] for s in _get(client, book["id"], basis="note")["suggestions"]]
    assert titles == ["メモ由来"]


def test_根拠を複数指定できる(client):
    book = _finished(client, "A")
    _set(client, book["id"], [
        _candidate(title="メモ由来", basis="note"),
        _candidate(title="評価由来", basis="rating"),
        _candidate(title="分野由来", basis="tag"),
    ])
    titles = [
        s["title"] for s in _get(client, book["id"], basis="note,rating")["suggestions"]
    ]
    assert titles == ["メモ由来", "評価由来"]


def test_根拠を1つも選ばないと422になる(client):
    # デザイン上、根拠トグルは最低1つONでなければならない
    book = _finished(client, "A")
    assert client.get(
        f"/api/books/{book['id']}/suggestions", params={"basis": ""}
    ).status_code == 422


def test_知らない根拠を指定すると422になる(client):
    book = _finished(client, "A")
    assert client.get(
        f"/api/books/{book['id']}/suggestions", params={"basis": "mood"}
    ).status_code == 422


def test_近い本だけに絞れる(client):
    book = _finished(client, "A")
    _set(client, book["id"], [
        _candidate(title="近い", distance="near"),
        _candidate(title="遠い", distance="far"),
    ])
    titles = [
        s["title"] for s in _get(client, book["id"], distance="near")["suggestions"]
    ]
    assert titles == ["近い"]


def test_距離の指定が不正だと422になる(client):
    book = _finished(client, "A")
    assert client.get(
        f"/api/books/{book['id']}/suggestions", params={"distance": "とおい"}
    ).status_code == 422


# --- 出し直す（ページング） ---

def test_一度に出すのは3冊まで(client):
    book = _finished(client, "A")
    _set(client, book["id"], [_candidate(title=f"候補{i}") for i in range(5)])
    body = _get(client, book["id"])
    assert len(body["suggestions"]) == 3
    assert body["has_more"] is True


def test_出し直すと次の候補が出る(client):
    book = _finished(client, "A")
    _set(client, book["id"], [_candidate(title=f"候補{i}") for i in range(5)])
    first = [s["title"] for s in _get(client, book["id"], page=0)["suggestions"]]
    second = [s["title"] for s in _get(client, book["id"], page=1)["suggestions"]]
    assert first == ["候補0", "候補1", "候補2"]
    assert second == ["候補3", "候補4"]


def test_候補を出し切ったらhas_moreがfalseになる(client):
    book = _finished(client, "A")
    _set(client, book["id"], [_candidate()])
    assert _get(client, book["id"])["has_more"] is False


# --- 1ページの冊数を変える（本の詳細画面は候補を全部出す） ---

def test_1ページの冊数を指定すればまとめて出せる(client):
    book = _finished(client, "A")
    _set(client, book["id"], [_candidate(title=f"候補{i}") for i in range(4)])
    body = _get(client, book["id"], per_page=20)
    assert [s["title"] for s in body["suggestions"]] == ["候補0", "候補1", "候補2", "候補3"]
    assert body["has_more"] is False


def test_1ページの冊数を大きくしても候補がなければhas_moreはfalse(client):
    book = _finished(client, "A")
    _set(client, book["id"], [_candidate()])
    assert _get(client, book["id"], per_page=20)["has_more"] is False


def test_1ページの冊数が0以下だと422になる(client):
    book = _finished(client, "A")
    assert client.get(
        f"/api/books/{book['id']}/suggestions", params={"per_page": 0}
    ).status_code == 422


# --- 興味なし ---

def test_興味なしにした本は以後出さない(client):
    book = _finished(client, "A")
    _set(client, book["id"], [_candidate(isbn="9784274226298")])
    assert len(_get(client, book["id"])["suggestions"]) == 1

    assert client.post(
        "/api/suggestions/dismiss", params={"isbn": "9784274226298"}
    ).status_code == 204
    assert _get(client, book["id"])["suggestions"] == []


def test_興味なしは他の本のおすすめにも効く(client):
    first = _finished(client, "A")
    second = _finished(client, "B")
    for book in (first, second):
        _set(client, book["id"], [_candidate(isbn="9784274226298")])
    client.post("/api/suggestions/dismiss", params={"isbn": "9784274226298"})
    assert _get(client, second["id"])["suggestions"] == []


def test_同じ本を二度興味なしにしても壊れない(client):
    for _ in range(2):
        assert client.post(
            "/api/suggestions/dismiss", params={"isbn": "9784274226298"}
        ).status_code == 204


# --- 積読に追加する ---

def test_候補を積読として追加できる(client):
    book = _finished(client, "A")
    suggestion = _set(client, book["id"], [_candidate(title="リファクタリング")])[0]
    created = client.post(f"/api/suggestions/{suggestion['id']}/add").json()
    assert created["title"] == "リファクタリング"
    assert created["status"] == "unread"


def test_追加したら候補に追加済みの印が付く(client):
    # ダイアログを開き直しても「追加済み」と分かるようにする
    book = _finished(client, "A")
    suggestion = _set(client, book["id"], [_candidate()])[0]
    created = client.post(f"/api/suggestions/{suggestion['id']}/add").json()
    assert _get(client, book["id"])["suggestions"][0]["added_book_id"] == created["id"]


def test_すでに本棚にある本なら二重に登録しない(client):
    existing = _book(client, "すでにある本", isbn="9784274226298")
    book = _finished(client, "A")
    suggestion = _set(client, book["id"], [_candidate(isbn="9784274226298")])[0]
    added = client.post(f"/api/suggestions/{suggestion['id']}/add").json()
    assert added["id"] == existing["id"]


def test_存在しない候補を追加すると404になる(client):
    assert client.post("/api/suggestions/9999/add").status_code == 404


# --- 見出しの情報と後片付け ---

def test_読み終えるまでの日数を返す(client):
    book = _finished(client, "A", started_on="2026-09-01", finished_on="2026-09-10")
    assert _get(client, book["id"])["days"] == 10


def test_同じ日に読み切ったら1日と数える(client):
    book = _finished(client, "A", started_on="2026-09-10", finished_on="2026-09-10")
    assert _get(client, book["id"])["days"] == 1


def test_引用メモの件数を返す(client):
    book = _finished(client, "A")
    client.post(f"/api/books/{book['id']}/notes", json={"kind": "memo", "text": "メモ"})
    assert _get(client, book["id"])["note_count"] == 1


def test_本を削除すると候補も消える(client, db_engine):
    book = _finished(client, "A")
    _set(client, book["id"], [_candidate()])
    client.delete(f"/api/books/{book['id']}")
    with db_engine.connect() as conn:
        assert conn.execute(text("select count(*) from suggestions")).scalar() == 0

