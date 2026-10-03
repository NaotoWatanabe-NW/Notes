"""おすすめ一覧のAPI（デザイン J）のテスト。

「次に読む本」とキーワードのおすすめを、本棚に無い本の1列にまとめる。
画面が頼りにする約束ごと——まとめ方・並び・出さない本・積読への追加——をここで固める。
"""

ISBN_A = "9784274224546"
ISBN_B = "9784274226298"
ISBN_C = "9784062884426"


def _book(client, title, **fields):
    return client.post("/api/books", json={"title": title} | fields).json()


def _candidate(**fields):
    base = {"title": "候補", "author": "著者", "basis": "tag", "distance": "near",
            "reason": "理由です", "isbn": ISBN_A}
    return base | fields


def _set_book(client, book_id, items):
    response = client.put(f"/api/books/{book_id}/suggestions", json=items)
    assert response.status_code == 200, response.text


def _set_topic(client, keyword, items):
    items = [{k: v for k, v in item.items() if k != "basis"} for item in items]
    response = client.put("/api/topics", json={"keyword": keyword, "suggestions": items})
    assert response.status_code == 200, response.text


def _list(client):
    response = client.get("/api/recommendations")
    assert response.status_code == 200, response.text
    return response.json()


def test_候補が無ければ空(client):
    assert _list(client) == []


def test_本の候補とキーワードの候補を1つの一覧にまとめる(client):
    source = _book(client, "ピダハン")
    _set_book(client, source["id"], [_candidate(title="数の発明", isbn=ISBN_A, reason="数の話へ")])
    _set_topic(client, "ゲーム理論", [_candidate(title="ゲーム理論入門の入門", isbn=ISBN_B, reason="入門")])

    body = _list(client)

    assert [item["title"] for item in body] == ["数の発明", "ゲーム理論入門の入門"]
    assert body[0]["sources"] == [
        {"kind": "book", "label": "ピダハン", "book_id": source["id"], "reason": "数の話へ"}
    ]
    assert body[1]["sources"] == [
        {"kind": "topic", "label": "ゲーム理論", "book_id": None, "reason": "入門"}
    ]


def test_同じ本は1つにまとめ選ばれた元と理由を全部添える(client):
    first = _book(client, "A")
    second = _book(client, "B")
    _set_book(client, first["id"], [_candidate(reason="Aから")])
    _set_book(client, second["id"], [_candidate(reason="Bから")])
    _set_topic(client, "統計", [_candidate(reason="統計から")])

    body = _list(client)

    assert len(body) == 1
    assert [(s["label"], s["reason"]) for s in body[0]["sources"]] == [
        ("A", "Aから"), ("B", "Bから"), ("統計", "統計から"),
    ]


def test_いくつもの元から選ばれた本を先に並べる(client):
    first = _book(client, "A")
    second = _book(client, "B")
    _set_book(client, first["id"], [_candidate(title="1か所", isbn=ISBN_A),
                                    _candidate(title="2か所", isbn=ISBN_B)])
    _set_book(client, second["id"], [_candidate(title="2か所", isbn=ISBN_B)])

    assert [item["title"] for item in _list(client)] == ["2か所", "1か所"]


def test_本棚にある本は出さない(client):
    source = _book(client, "A")
    _book(client, "持っている本", isbn=ISBN_B)
    _set_book(client, source["id"], [_candidate(title="持っていない本", isbn=ISBN_A),
                                     _candidate(title="持っている本", isbn=ISBN_B)])

    assert [item["title"] for item in _list(client)] == ["持っていない本"]


def test_ISBNが違っても書名が同じ本は本棚にあるとみなす(client):
    # 文庫と単行本のように版が違うだけのことがある（デザイン: 書名で一致）
    source = _book(client, "A")
    _book(client, "思考の整理学")
    _set_book(client, source["id"], [_candidate(title="思考の整理学 ", isbn=ISBN_A)])

    assert _list(client) == []


def test_興味なしにした本は出さない(client):
    source = _book(client, "A")
    _set_book(client, source["id"], [_candidate(title="残る", isbn=ISBN_A),
                                     _candidate(title="外す", isbn=ISBN_B)])
    client.post("/api/suggestions/dismiss", params={"isbn": ISBN_B})

    assert [item["title"] for item in _list(client)] == ["残る"]


def test_カテゴリ出版社ページ数を返しカテゴリが分からなければその他(client):
    source = _book(client, "A")
    _set_book(client, source["id"], [
        _candidate(title="分かる", isbn=ISBN_A, genre="novel", publisher="新潮文庫", total=291),
        _candidate(title="分からない", isbn=ISBN_B),
    ])

    body = {item["title"]: item for item in _list(client)}

    assert (body["分かる"]["genre"], body["分かる"]["publisher"], body["分かる"]["total"]) == (
        "novel", "新潮文庫", 291)
    assert body["分からない"]["genre"] == "other"


def test_積読に追加すると本棚にカテゴリ付きで入り一覧から消える(client):
    source = _book(client, "A")
    _set_book(client, source["id"], [
        _candidate(title="博士の愛した数式", isbn=ISBN_C, genre="novel", publisher="新潮文庫", total=291),
    ])

    response = client.post("/api/recommendations/add", json={"isbn": ISBN_C})

    assert response.status_code == 201
    added = response.json()
    assert (added["title"], added["genre"], added["publisher"], added["total"], added["status"]) == (
        "博士の愛した数式", "novel", "新潮文庫", 291, "unread")
    assert _list(client) == []


def test_積読に追加すると同じ本の候補すべてに追加済みの印が付く(client):
    first = _book(client, "A")
    second = _book(client, "B")
    _set_book(client, first["id"], [_candidate()])
    _set_book(client, second["id"], [_candidate()])
    _set_topic(client, "統計", [_candidate()])

    added = client.post("/api/recommendations/add", json={"isbn": ISBN_A}).json()

    for book in (first, second):
        got = client.get(f"/api/books/{book['id']}/suggestions").json()["suggestions"]
        assert got[0]["added_book_id"] == added["id"]
    topic_id = client.get("/api/topics").json()[0]["id"]
    assert client.get(f"/api/topics/{topic_id}").json()["suggestions"][0]["added_book_id"] == added["id"]


def test_おすすめに無い本を追加すると404(client):
    assert client.post("/api/recommendations/add", json={"isbn": ISBN_A}).status_code == 404
