"""ビルド済みフロントエンドの配信のテスト"""


def test_存在しないAPIパスはindexではなく404を返す(client):
    # index.html を返してしまうと、APIのパスを間違えたときに気づけない
    response = client.get("/api/unknown")
    assert response.status_code == 404
    assert "text/html" not in response.headers.get("content-type", "")


def test_APIのルートは静的配信に飲み込まれない(client):
    # キャッチオールを先に登録すると、ここが index.html になってしまう
    response = client.get("/api/books")
    assert response.status_code == 200
    assert response.json() == []


def test_画面のパスはindexを返す(client):
    response = client.get("/")
    # dist がある場合は HTML、まだビルドしていない場合は案内付きの404
    if response.status_code == 200:
        assert "text/html" in response.headers["content-type"]
    else:
        assert response.status_code == 404
        assert "npm run build" in response.json()["detail"]


def test_distの外のファイルは取得できない(client):
    """`../` を並べて dist の外のファイルを読み出せないこと。

    404 ではなく index.html が返ってもよい（SPA のフォールバック）。
    大事なのは中身が返らないことなので、ファイルの中身で判定する。
    ステータスコードで判定すると、クライアント側の URL 正規化で
    素通りしていても気づけない。
    """
    targets = [
        "/../../backend/requirements.txt",
        "/%2e%2e/%2e%2e/backend/requirements.txt",
        "/..%2f..%2fbackend%2frequirements.txt",
        "/assets/../../backend/requirements.txt",
    ]
    for path in targets:
        body = client.get(path).text
        assert "uvicorn" not in body, f"{path} で requirements.txt の中身が返った"
