"""アプリ設定のAPIのテスト"""


def test_初回アクセスでも既定値の設定が返る(client):
    # 設定の行がまだ無くても、既定値で作ってから返す
    body = client.get("/api/settings").json()
    assert body == {"yearly_goal": 50, "sort": "recent", "quote_style": "italic"}


def test_読書目標を変更できる(client):
    assert client.patch("/api/settings", json={"yearly_goal": 36}).json()["yearly_goal"] == 36
    assert client.get("/api/settings").json()["yearly_goal"] == 36


def test_送った項目だけが更新される(client):
    client.patch("/api/settings", json={"yearly_goal": 36})
    body = client.patch("/api/settings", json={"quote_style": "plain"}).json()
    assert body["quote_style"] == "plain"
    assert body["yearly_goal"] == 36


def test_読書目標に0を送ると422になる(client):
    assert client.patch("/api/settings", json={"yearly_goal": 0}).status_code == 422


def test_知らない並び順は422になる(client):
    assert client.patch("/api/settings", json={"sort": "rating"}).status_code == 422


def test_知らない引用書体は422になる(client):
    assert client.patch("/api/settings", json={"quote_style": "bold"}).status_code == 422


def test_知らない項目を送ると422になる(client):
    assert client.patch("/api/settings", json={"theme": "dark"}).status_code == 422
