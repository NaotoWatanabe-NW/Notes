"""タグ一覧のAPIのテスト"""


def _book(client, title, tags):
    return client.post("/api/books", json={"title": title, "tags": tags}).json()


def test_使われているタグと冊数を返す(client):
    _book(client, "A", ["技術書", "設計"])
    _book(client, "B", ["技術書"])
    rows = {row["name"]: row["count"] for row in client.get("/api/tags").json()}
    assert rows == {"技術書": 2, "設計": 1}


def test_冊数の多い順に並ぶ(client):
    _book(client, "A", ["設計"])
    _book(client, "B", ["技術書"])
    _book(client, "C", ["技術書"])
    assert [row["name"] for row in client.get("/api/tags").json()][0] == "技術書"


def test_どの本にも付いていないタグは出さない(client):
    # 本から外したあとの「残りかす」を候補に出さない
    book = _book(client, "A", ["まちがえたタグ"])
    client.patch(f"/api/books/{book['id']}", json={"tags": []})
    assert client.get("/api/tags").json() == []


def test_タグが1つも無ければ空で返る(client):
    assert client.get("/api/tags").json() == []
