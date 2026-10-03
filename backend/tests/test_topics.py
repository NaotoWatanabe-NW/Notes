"""キーワードのおすすめのAPIのテスト。

「次に読む本」と違い、本棚の1冊ではなくキーワードに紐づく。
スキルが頼りにする約束ごと——キーワードのそろえ方・入れ替え・手がかりの本・
興味なし・積読への追加——をここで固める。
"""


def _book(client, title, **fields):
    return client.post("/api/books", json={"title": title} | fields).json()


def _candidate(**fields):
    base = {
        "title": "ゲーム理論入門の入門",
        "author": "鎌田雄一郎",
        "distance": "near",
        "reason": "数式を使わずに、まず全体の見取り図をつかめます",
    }
    return base | fields


def _put(client, keyword, items):
    return client.put("/api/topics", json={"keyword": keyword, "suggestions": items})


def _set(client, keyword, items):
    response = _put(client, keyword, items)
    assert response.status_code == 200, response.text
    return response.json()


def _topics(client):
    return client.get("/api/topics").json()


# --- 設定する ---

def test_設定した候補がキーワードと一緒に返る(client):
    topic = _set(client, "ゲーム理論", [_candidate()])

    got = client.get(f"/api/topics/{topic['id']}").json()
    assert got["keyword"] == "ゲーム理論"
    assert got["suggestions"][0]["title"] == "ゲーム理論入門の入門"
    assert got["suggestions"][0]["reason"] == "数式を使わずに、まず全体の見取り図をつかめます"
    assert got["suggestions"][0]["added_book_id"] is None


def test_設定した順番で返る(client):
    topic = _set(client, "統計", [_candidate(title="1冊目"), _candidate(title="2冊目", distance="far")])
    assert [s["title"] for s in topic["suggestions"]] == ["1冊目", "2冊目"]


def test_同じキーワードで設定し直すと前の候補は消える(client):
    first = _set(client, "統計", [_candidate(title="古い候補")])
    second = _set(client, "統計", [_candidate(title="新しい候補")])

    assert second["id"] == first["id"]
    assert [s["title"] for s in second["suggestions"]] == ["新しい候補"]


def test_全角半角と空白の違いは同じキーワードとして扱う(client):
    first = _set(client, "ＡＩ　倫理", [_candidate(title="1冊目")])
    second = _set(client, "  AI 倫理 ", [_candidate(title="2冊目")])

    assert second["id"] == first["id"]
    assert second["keyword"] == "AI 倫理"
    assert len(_topics(client)) == 1


def test_スラッシュを含むキーワードも設定できる(client):
    topic = _set(client, "CI/CD", [_candidate()])
    assert client.get(f"/api/topics/{topic['id']}").json()["keyword"] == "CI/CD"


def test_ISBNは13桁に正規化して保存される(client):
    topic = _set(client, "統計", [_candidate(isbn="978-4-274-22629-8")])
    assert topic["suggestions"][0]["isbn"] == "9784274226298"


# --- 入力の検査 ---

def test_候補が空だと422になる(client):
    # 消すときは DELETE を使う。空のキーワードを残さない
    assert _put(client, "統計", []).status_code == 422


def test_候補が21件以上だと422になる(client):
    assert _put(client, "統計", [_candidate(title=f"本{i}") for i in range(21)]).status_code == 422


def test_キーワードが空白だけだと422になる(client):
    assert _put(client, "　 ", [_candidate()]).status_code == 422


def test_知らない距離は422になる(client):
    assert _put(client, "統計", [_candidate(distance="same")]).status_code == 422


def test_知らない項目を送ると422になる(client):
    # 「次に読む本」の basis はこちらには無い
    assert _put(client, "統計", [_candidate(basis="tag")]).status_code == 422


def test_本棚にない本を手がかりにすると422になる(client):
    response = _put(client, "統計", [_candidate(from_book_id=9999)])
    assert response.status_code == 422
    assert "9999" in response.json()["detail"]
    assert _topics(client) == []


# --- 手がかりの本 ---

def test_手がかりにした本を覚えている(client):
    owned = _book(client, "ゲーム理論の思考法")
    topic = _set(client, "ゲーム理論", [_candidate(from_book_id=owned["id"])])
    assert topic["suggestions"][0]["from_book_id"] == owned["id"]


def test_手がかりにした本を消しても候補は残る(client):
    owned = _book(client, "ゲーム理論の思考法")
    topic = _set(client, "ゲーム理論", [_candidate(from_book_id=owned["id"])])

    client.delete(f"/api/books/{owned['id']}")

    got = client.get(f"/api/topics/{topic['id']}").json()
    assert got["suggestions"][0]["from_book_id"] is None


# --- 一覧 ---

def test_キーワードの一覧は件数を添えて設定し直した順に並ぶ(client):
    _set(client, "統計", [_candidate(title="A"), _candidate(title="B")])
    _set(client, "ゲーム理論", [_candidate(title="C")])
    _set(client, "統計", [_candidate(title="A"), _candidate(title="B"), _candidate(title="D")])

    assert [(t["keyword"], t["count"]) for t in _topics(client)] == [("統計", 3), ("ゲーム理論", 1)]


def test_キーワードを1つも設定していなければ一覧は空(client):
    assert _topics(client) == []


# --- 興味なし ---

def test_興味なしにした本はキーワードのおすすめにも出ない(client):
    topic = _set(client, "統計", [
        _candidate(title="残す", isbn="9784062884426"),
        _candidate(title="外す", isbn="9784274224546"),
    ])
    client.post("/api/suggestions/dismiss", params={"isbn": "9784274224546"})

    got = client.get(f"/api/topics/{topic['id']}").json()
    assert [s["title"] for s in got["suggestions"]] == ["残す"]
    assert _topics(client)[0]["count"] == 1


# --- 消す ---

def test_キーワードを消すと候補ごと消える(client):
    topic = _set(client, "統計", [_candidate()])

    assert client.delete(f"/api/topics/{topic['id']}").status_code == 204
    assert client.get(f"/api/topics/{topic['id']}").status_code == 404
    assert _topics(client) == []


def test_存在しないキーワードは404になる(client):
    assert client.get("/api/topics/9999").status_code == 404
    assert client.delete("/api/topics/9999").status_code == 404


# --- 積読に追加 ---

def test_候補を積読として追加すると追加済みの印が付く(client):
    topic = _set(client, "統計", [_candidate(isbn="9784062884426")])
    suggestion_id = topic["suggestions"][0]["id"]

    response = client.post(f"/api/topic-suggestions/{suggestion_id}/add")

    assert response.status_code == 201
    added = response.json()
    assert added["title"] == "ゲーム理論入門の入門"
    assert added["status"] == "unread"
    got = client.get(f"/api/topics/{topic['id']}").json()
    assert got["suggestions"][0]["added_book_id"] == added["id"]


def test_すでに本棚にある本を追加しても二重に登録しない(client):
    owned = _book(client, "ゲーム理論入門の入門", isbn="9784062884426")
    topic = _set(client, "統計", [_candidate(isbn="9784062884426")])

    added = client.post(f"/api/topic-suggestions/{topic['suggestions'][0]['id']}/add").json()

    assert added["id"] == owned["id"]
    assert len(client.get("/api/books").json()) == 1


def test_存在しない候補を追加すると404になる(client):
    assert client.post("/api/topic-suggestions/9999/add").status_code == 404
