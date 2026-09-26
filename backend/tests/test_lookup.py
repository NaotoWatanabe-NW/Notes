"""ISBN から本の情報・書影を取る API のテスト。

外部サービスだけを httpx.MockTransport で差し替える。DB は本物を使う。
"""
import httpx
import pytest

from app.booklookup import get_http_client
from app.main import app

from fixtures_lookup import (
    COVER_BYTES,
    GOOGLE_BOOKS_FOUND,
    GOOGLE_BOOKS_NOT_FOUND,
    NDL_FOUND,
    NDL_NOT_FOUND,
    OPENBD_FOUND,
    OPENBD_NOT_FOUND,
)

NDL_HOST = "ndlsearch.ndl.go.jp"
OPENBD_HOST = "api.openbd.jp"
GOOGLE_HOST = "www.googleapis.com"


class FakeInternet:
    """外部サービスの代わり。どのURLに何を返すかをテストごとに決める。

    受け取ったリクエストを records に残すので、「Referer を付けて呼んだか」
    のような呼び出し方の検証もできる。
    """

    def __init__(self, ndl=None, openbd=None, google=None, cover=None):
        self.ndl = ndl
        # 書名検索・著者検索はそれぞれ別に差し替えられる
        self.ndl_by_title = None
        self.ndl_by_creator = None
        self.openbd = openbd
        self.google = google
        self.cover = cover
        self.records: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.records.append(request)
        host, path = request.url.host, request.url.path

        if host == NDL_HOST and path.startswith("/thumbnail/"):
            return self._respond(self.cover)
        if host == NDL_HOST:
            params = request.url.params
            if "title" in params and self.ndl_by_title is not None:
                return self._respond(self.ndl_by_title)
            if "creator" in params and self.ndl_by_creator is not None:
                return self._respond(self.ndl_by_creator)
            return self._respond(self.ndl)
        if host == OPENBD_HOST:
            return self._respond(self.openbd)
        if host == GOOGLE_HOST:
            return self._respond(self.google)
        raise AssertionError(f"テストが想定していない通信先: {request.url}")

    @staticmethod
    def _respond(spec) -> httpx.Response:
        if spec is None:
            return httpx.Response(404)
        # リストを渡すと、呼ばれるたびに次のものを返す（やり直しの検証用）
        if isinstance(spec, list):
            return FakeInternet._respond(spec.pop(0) if len(spec) > 1 else spec[0])
        if isinstance(spec, int):
            return httpx.Response(spec)
        status, payload = spec
        if isinstance(payload, str):
            return httpx.Response(
                status, text=payload, headers={"content-type": "text/xml"}
            )
        if isinstance(payload, bytes):
            return httpx.Response(
                status, content=payload, headers={"content-type": "image/jpeg"}
            )
        return httpx.Response(status, json=payload)

    def requests_to(self, host: str) -> list[httpx.Request]:
        return [r for r in self.records if r.url.host == host]


@pytest.fixture
def google_key(monkeypatch):
    """Google Books はキーがあるときだけ引くので、テストでは立てておく"""
    from app import booklookup

    monkeypatch.setattr(booklookup, "GOOGLE_BOOKS_KEY", "test-key")


@pytest.fixture
def fake_internet(client):
    """外部サービスを差し替える。テスト本体で中身を設定して使う"""
    fake = FakeInternet()

    def override():
        transport = httpx.MockTransport(fake.handle)
        with httpx.Client(transport=transport) as http_client:
            yield http_client

    app.dependency_overrides[get_http_client] = override
    yield fake
    app.dependency_overrides.pop(get_http_client, None)


# --- 検索元の切り替え ---

def test_国会図書館サーチから本の情報を取得できる(client, fake_internet):
    fake_internet.ndl = (200, NDL_FOUND)
    body = client.get("/api/isbn/9784274226298").json()
    assert body["title"] == "達人プログラマー : 熟達に向けたあなたの旅"
    assert body["publisher"] == "オーム社"
    assert body["source"] == "ndl"


def test_国会図書館で見つからないときopenBDを使う(client, fake_internet):
    fake_internet.ndl = (200, NDL_NOT_FOUND)
    fake_internet.openbd = (200, OPENBD_FOUND)
    body = client.get("/api/isbn/9784873115658").json()
    assert body["source"] == "openbd"
    assert body["title"].startswith("リーダブルコード")


def test_国会図書館が429でもopenBDで取得できる(client, fake_internet):
    # 外部サービスが落ちていても次を試すこと
    fake_internet.ndl = 429
    fake_internet.openbd = (200, OPENBD_FOUND)
    assert client.get("/api/isbn/9784873115658").json()["source"] == "openbd"


def test_和書のデータベースに無い洋書はGoogleBooksで取得できる(client, fake_internet, google_key):
    fake_internet.ndl = (200, NDL_NOT_FOUND)
    fake_internet.openbd = (200, OPENBD_NOT_FOUND)
    fake_internet.google = (200, GOOGLE_BOOKS_FOUND)
    body = client.get("/api/isbn/9780201616224").json()
    assert body["source"] == "google_books"
    # subtitle があるときは「タイトル : サブタイトル」に繋ぐ
    assert body["title"] == "The Pragmatic Programmer : From Journeyman to Master"
    assert body["author"] == "Andrew Hunt, David Thomas"


def test_どこにも無いISBNは404になる(client, fake_internet):
    fake_internet.ndl = (200, NDL_NOT_FOUND)
    fake_internet.openbd = (200, OPENBD_NOT_FOUND)
    fake_internet.google = (200, GOOGLE_BOOKS_NOT_FOUND)
    response = client.get("/api/isbn/9784274226298")
    assert response.status_code == 404
    assert "見つかりません" in response.json()["detail"]


def test_全ての検索先が落ちていても404で返る(client, fake_internet):
    # 500 が返ってもアプリ側が落ちないこと
    fake_internet.ndl = 500
    fake_internet.openbd = 500
    fake_internet.google = 500
    assert client.get("/api/isbn/9784274226298").status_code == 404


# --- 著者名の整形 ---

def test_著者名から生没年が取り除かれる(client, fake_internet):
    fake_internet.ndl = (200, NDL_FOUND)
    author = client.get("/api/isbn/9784274226298").json()["author"]
    assert "1956" not in author and "1960" not in author


def test_欧文の著者は名姓の順に直され日本語の著者は姓名が繋がる(client, fake_internet):
    fake_internet.ndl = (200, NDL_FOUND)
    author = client.get("/api/isbn/9784274226298").json()["author"]
    # 「Thomas, David, 1956-」→「David Thomas」、「村上, 雅章, 1960-」→「村上雅章」
    assert author == "David Thomas, Andrew Hunt, 村上雅章"


# --- ISBN の受け付け方 ---

def test_ハイフン付きのISBNでも検索できる(client, fake_internet):
    fake_internet.ndl = (200, NDL_FOUND)
    assert client.get("/api/isbn/978-4-274-22629-8").status_code == 200
    # 外部サービスにはハイフンなし13桁で問い合わせること
    assert fake_internet.requests_to(NDL_HOST)[0].url.params["isbn"] == "9784274226298"


def test_ISBN10で検索するとISBN13に変換して問い合わせる(client, fake_internet):
    fake_internet.ndl = (200, NDL_FOUND)
    client.get("/api/isbn/4274226298")
    assert fake_internet.requests_to(NDL_HOST)[0].url.params["isbn"] == "9784274226298"


def test_不正なISBNは外部に問い合わせずに422を返す(client, fake_internet):
    response = client.get("/api/isbn/1234")
    assert response.status_code == 422
    assert fake_internet.records == []


# --- 書影 ---

def test_書影があるとき自分のAPI経由のパスが返る(client, fake_internet):
    # 書影のURLをそのまま返すとブラウザでは Referer が付かず 403 になる
    fake_internet.ndl = (200, NDL_FOUND)
    fake_internet.cover = (200, COVER_BYTES)
    body = client.get("/api/isbn/9784274226298").json()
    assert body["cover_url"] == "/api/covers/9784274226298"


def test_書影が無いときcover_urlはnullになる(client, fake_internet):
    fake_internet.ndl = (200, NDL_FOUND)
    fake_internet.cover = 403
    assert client.get("/api/isbn/9784274226298").json()["cover_url"] is None


def test_書影APIは画像をそのまま返す(client, fake_internet):
    fake_internet.cover = (200, COVER_BYTES)
    response = client.get("/api/covers/9784274226298")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == COVER_BYTES


def test_書影APIはRefererを付けて取りに行く(client, fake_internet):
    # Referer が無いと国会図書館サーチは 403 を返す（実測で確認済み）
    fake_internet.cover = (200, COVER_BYTES)
    client.get("/api/covers/9784274226298")
    thumbnail_requests = [
        r for r in fake_internet.records if r.url.path.startswith("/thumbnail/")
    ]
    assert thumbnail_requests[0].headers["Referer"] == "https://ndlsearch.ndl.go.jp/"


def test_書影が無いISBNの書影APIは404を返す(client, fake_internet):
    fake_internet.cover = 403
    assert client.get("/api/covers/9784274226298").status_code == 404


def test_画像以外が返ってきたら書影として扱わない(client, fake_internet):
    # 403 のときHTMLが返ってくる。これを画像として配ってしまわないこと
    fake_internet.cover = (200, {"error": "not an image"})
    assert client.get("/api/covers/9784274226298").status_code == 404


# --- ページ数と分野（進捗バーと「よく読む分野」に使う） ---

def test_国会図書館から総ページ数を取得できる(client, fake_internet):
    # <dc:extent>422p</dc:extent> から数字だけ取り出す
    fake_internet.ndl = (200, NDL_FOUND)
    assert client.get("/api/isbn/9784274226298").json()["total"] == 422


def test_国会図書館から分野を取得できる(client, fake_internet):
    fake_internet.ndl = (200, NDL_FOUND)
    assert client.get("/api/isbn/9784274226298").json()["category"] == "プログラミング (コンピュータ)"


def test_分類記号は分野として使わない(client, fake_internet):
    # <dc:subject xsi:type="dcndl:NDC10">007.64</dc:subject> は人が読む件名ではない
    fake_internet.ndl = (200, NDL_FOUND)
    assert client.get("/api/isbn/9784274226298").json()["category"] != "007.64"


def test_ページ数が載っていない本のtotalはnullになる(client, fake_internet):
    fake_internet.ndl = (200, NDL_NOT_FOUND)
    fake_internet.openbd = (200, OPENBD_FOUND)
    assert client.get("/api/isbn/9784873115658").json()["total"] is None


def test_GoogleBooksからもページ数と分野を取得できる(client, fake_internet, google_key):
    fake_internet.ndl = (200, NDL_NOT_FOUND)
    fake_internet.openbd = (200, OPENBD_NOT_FOUND)
    fake_internet.google = (200, GOOGLE_BOOKS_FOUND)
    body = client.get("/api/isbn/9780201616224").json()
    assert body["total"] == 321
    assert body["category"] == "Computers"


# --- 書名・著者での検索（⌘K の「本を追加」） ---

def _search(client, query, **params):
    return client.get("/api/search", params={"q": query, **params}).json()


def test_書名で本を検索できる(client, fake_internet):
    from fixtures_lookup import NDL_SEARCH_BY_TITLE

    fake_internet.ndl = (200, NDL_SEARCH_BY_TITLE)
    titles = [r["title"] for r in _search(client, "達人プログラマー")]
    assert "達人プログラマー : 職人から名匠への道" in titles


def test_クエリと関係のない本は結果から外す(client, fake_internet):
    # 国会図書館サーチは関連度順ではなく五十音順で返し、関係の薄い本も混ぜてくる
    from fixtures_lookup import NDL_SEARCH_BY_TITLE

    fake_internet.ndl = (200, NDL_SEARCH_BY_TITLE)
    titles = [r["title"] for r in _search(client, "達人プログラマー")]
    assert "愛の花束 : 2005年度新鋭随筆家傑作撰" not in titles


def test_書名がクエリで始まる本を先頭に出す(client, fake_internet):
    # 「実践JUnit : 達人プログラマーの…」より「達人プログラマー : …」を上に
    from fixtures_lookup import NDL_SEARCH_BY_TITLE

    fake_internet.ndl = (200, NDL_SEARCH_BY_TITLE)
    titles = [r["title"] for r in _search(client, "達人プログラマー")]
    assert titles[0].startswith("達人プログラマー")


def test_同じ書名と著者の版違いは1件にまとめる(client, fake_internet):
    # ISBN は違うが同じ本。候補に何度も出ても選びようがない
    from fixtures_lookup import NDL_SEARCH_BY_TITLE

    fake_internet.ndl = (200, NDL_SEARCH_BY_TITLE)
    titles = [r["title"] for r in _search(client, "達人プログラマー")]
    assert titles.count("達人プログラマー : 職人から名匠への道") == 1


def test_ISBNが無い資料は検索結果に含めない(client, fake_internet):
    # ISBN が無いと本として登録できないので候補から外す
    from fixtures_lookup import NDL_SEARCH_BY_TITLE

    fake_internet.ndl = (200, NDL_SEARCH_BY_TITLE)
    titles = [r["title"] for r in _search(client, "達人プログラマー")]
    assert "ISBNが付いていない資料" not in titles


def test_検索結果のISBNは13桁に正規化される(client, fake_internet):
    from fixtures_lookup import NDL_SEARCH_BY_TITLE

    fake_internet.ndl = (200, NDL_SEARCH_BY_TITLE)
    results = _search(client, "達人プログラマー")
    assert results and all(
        len(r["isbn"]) == 13 and r["isbn"].isdigit() for r in results
    )


def test_検索結果の件数を指定できる(client, fake_internet):
    from fixtures_lookup import NDL_SEARCH_BY_TITLE

    fake_internet.ndl = (200, NDL_SEARCH_BY_TITLE)
    assert len(_search(client, "達人プログラマー", limit=1)) == 1


# --- 人名で探したとき ---

def test_人名で探すとその人が書いた本が返る(client, fake_internet):
    # 書名検索では「その人について書かれた本」しか出ないので著者でも引き直す
    from fixtures_lookup import NDL_SEARCH_ABOUT_AUTHOR, NDL_SEARCH_BY_CREATOR

    fake_internet.ndl_by_title = (200, NDL_SEARCH_ABOUT_AUTHOR)
    fake_internet.ndl_by_creator = (200, NDL_SEARCH_BY_CREATOR)
    titles = [r["title"] for r in _search(client, "村上春樹")]
    assert titles[0] == "ノルウェイの森"


def test_書名がクエリで始まる本が見つかれば著者では引き直さない(client, fake_internet):
    # 外部サービスは遅いので、要らない往復を増やさない
    from fixtures_lookup import NDL_SEARCH_BY_TITLE

    fake_internet.ndl_by_title = (200, NDL_SEARCH_BY_TITLE)
    fake_internet.ndl_by_creator = (200, NDL_SEARCH_BY_TITLE)
    _search(client, "達人プログラマー")
    creator_requests = [
        r for r in fake_internet.requests_to(NDL_HOST) if "creator" in r.url.params
    ]
    assert creator_requests == []


# --- 失敗したとき ---

def test_検索先が落ちていたら503を返す(client, fake_internet):
    # 「見つからなかった」と同じ空配列にすると、画面が
    # 「その本はありません」と嘘をつくことになる
    fake_internet.ndl = 500
    response = client.get("/api/search", params={"q": "達人プログラマー"})
    assert response.status_code == 503
    assert "少し待って" in response.json()["detail"]


def test_混み合っているとき429でも503を返す(client, fake_internet):
    # 国会図書館サーチは叩きすぎると 429 を返す（実測）
    fake_internet.ndl = 429
    assert client.get("/api/search", params={"q": "達人"}).status_code == 503


def test_引けたうえで0件なら空の配列を返す(client, fake_internet):
    # こちらは本当に「見つからなかった」ので 200 + 空配列
    from fixtures_lookup import NDL_NOT_FOUND

    fake_internet.ndl = (200, NDL_NOT_FOUND)
    response = client.get("/api/search", params={"q": "実在しない書名"})
    assert response.status_code == 200
    assert response.json() == []


def test_書名で引けなくても著者で引ければ結果を返す(client, fake_internet):
    # 片方が落ちていても、もう片方で引けていれば 503 にしない
    from fixtures_lookup import NDL_SEARCH_BY_CREATOR

    fake_internet.ndl_by_title = 500
    fake_internet.ndl_by_creator = (200, NDL_SEARCH_BY_CREATOR)
    titles = [r["title"] for r in _search(client, "村上春樹")]
    assert titles == ["ノルウェイの森"]


def test_空のクエリでは422になる(client, fake_internet):
    assert client.get("/api/search", params={"q": ""}).status_code == 422


def test_記号だけのクエリでは外部に問い合わせない(client, fake_internet):
    assert _search(client, "・・・") == []
    assert fake_internet.records == []


# --- Google Books はキーがあるときだけ引く ---

def test_APIキーが無ければGoogleBooksに問い合わせない(client, fake_internet, monkeypatch):
    # キー無しだと必ず 429 が返るだけなので、往復を1回省く
    from app import booklookup

    monkeypatch.setattr(booklookup, "GOOGLE_BOOKS_KEY", "")
    fake_internet.ndl = (200, NDL_NOT_FOUND)
    fake_internet.openbd = (200, OPENBD_NOT_FOUND)
    assert client.get("/api/isbn/9784274226298").status_code == 404
    assert fake_internet.requests_to(GOOGLE_HOST) == []


def test_APIキーがあればGoogleBooksに問い合わせる(client, fake_internet, google_key):
    fake_internet.ndl = (200, NDL_NOT_FOUND)
    fake_internet.openbd = (200, OPENBD_NOT_FOUND)
    fake_internet.google = (200, GOOGLE_BOOKS_FOUND)
    body = client.get("/api/isbn/9780201616224").json()
    assert body["source"] == "google_books"


def test_問い合わせにAPIキーを付ける(client, fake_internet, google_key):
    fake_internet.ndl = (200, NDL_NOT_FOUND)
    fake_internet.openbd = (200, OPENBD_NOT_FOUND)
    fake_internet.google = (200, GOOGLE_BOOKS_FOUND)
    client.get("/api/isbn/9780201616224")
    request = fake_internet.requests_to(GOOGLE_HOST)[0]
    assert request.url.params["key"] == "test-key"


# --- 混んでいるときのやり直しと、結果の使い回し ---

@pytest.fixture
def no_wait(monkeypatch):
    """やり直しの待ち時間はテストでは 0 にする"""
    from app import booklookup

    monkeypatch.setattr(booklookup, "RETRY_AFTER_SECONDS", 0)


def test_429が返っても一度やり直して取れれば成功にする(client, fake_internet, no_wait):
    # 国会図書館サーチは同じクエリでも通ったり通らなかったりする（実測）
    from fixtures_lookup import NDL_SEARCH_BY_TITLE

    fake_internet.ndl = [429, (200, NDL_SEARCH_BY_TITLE)]
    results = client.get("/api/search", params={"q": "達人プログラマー"}).json()
    assert len(results) > 0


def test_やり直しても駄目なら503にする(client, fake_internet, no_wait):
    fake_internet.ndl = 503
    assert client.get("/api/search", params={"q": "達人"}).status_code == 503


def test_やり直しは一度だけにする(client, fake_internet, no_wait):
    # 何度も叩くと、かえって締め出される
    fake_internet.ndl = 429
    client.get("/api/search", params={"q": "達人プログラマー"})
    ndl_calls = len(fake_internet.requests_to(NDL_HOST))
    # 書名で2回（本体＋やり直し）、著者で2回 = 4回まで
    assert ndl_calls <= 4


def test_同じ検索を繰り返しても外に出ていかない(client, fake_internet):
    # 打ち直すたびに問い合わせると、混雑に拍車をかける
    from fixtures_lookup import NDL_SEARCH_BY_TITLE

    fake_internet.ndl = (200, NDL_SEARCH_BY_TITLE)
    first = client.get("/api/search", params={"q": "達人プログラマー"}).json()
    calls = len(fake_internet.requests_to(NDL_HOST))
    second = client.get("/api/search", params={"q": "達人プログラマー"}).json()
    assert second == first
    assert len(fake_internet.requests_to(NDL_HOST)) == calls


def test_違う言葉なら改めて問い合わせる(client, fake_internet):
    from fixtures_lookup import NDL_SEARCH_BY_TITLE

    fake_internet.ndl = (200, NDL_SEARCH_BY_TITLE)
    client.get("/api/search", params={"q": "達人プログラマー"})
    calls = len(fake_internet.requests_to(NDL_HOST))
    client.get("/api/search", params={"q": "リーダブルコード"})
    assert len(fake_internet.requests_to(NDL_HOST)) > calls


def test_引けなかったときは覚えない(client, fake_internet, no_wait):
    # 失敗を覚えると、復旧しても出てこなくなる
    from fixtures_lookup import NDL_SEARCH_BY_TITLE

    fake_internet.ndl = 503
    assert client.get("/api/search", params={"q": "達人プログラマー"}).status_code == 503

    fake_internet.ndl = (200, NDL_SEARCH_BY_TITLE)
    assert len(client.get("/api/search", params={"q": "達人プログラマー"}).json()) > 0


# --- Google Books を書名検索の一番手にする ---

def test_キーがあれば書名はGoogleBooksで引く(client, fake_internet, google_key):
    # 国会図書館は初回 12〜39秒かかる（実測）。Google Books は1秒前後
    from fixtures_lookup import GOOGLE_BOOKS_SEARCH

    fake_internet.google = (200, GOOGLE_BOOKS_SEARCH)
    results = _search(client, "達人プログラマー")
    assert results[0]["source"] == "google_books"
    # 速い方で見つかったら、遅い方は引かない
    assert fake_internet.requests_to(NDL_HOST) == []


def test_GoogleBooksで見つからなければ国会図書館に落ちる(client, fake_internet, google_key):
    from fixtures_lookup import NDL_SEARCH_BY_TITLE

    fake_internet.google = (200, {"totalItems": 0})
    fake_internet.ndl = (200, NDL_SEARCH_BY_TITLE)
    results = _search(client, "達人プログラマー")
    assert results and results[0]["source"] == "ndl"


def test_キーが無ければ書名はGoogleBooksに問い合わせない(client, fake_internet, monkeypatch):
    from app import booklookup
    from fixtures_lookup import NDL_SEARCH_BY_TITLE

    monkeypatch.setattr(booklookup, "GOOGLE_BOOKS_KEY", "")
    fake_internet.ndl = (200, NDL_SEARCH_BY_TITLE)
    assert _search(client, "達人プログラマー")
    assert fake_internet.requests_to(GOOGLE_HOST) == []


def test_ISBNが分からない本は候補に出さない(client, fake_internet, google_key):
    from fixtures_lookup import GOOGLE_BOOKS_SEARCH

    fake_internet.google = (200, GOOGLE_BOOKS_SEARCH)
    titles = [r["title"] for r in _search(client, "達人プログラマー")]
    assert "ISBNが分からない本" not in titles


def test_表紙のURLをhttpsに直す(client, fake_internet, google_key):
    # http:// のままだと、HTTPS で開いたとき混在コンテンツとして弾かれる
    from fixtures_lookup import GOOGLE_BOOKS_SEARCH

    fake_internet.google = (200, GOOGLE_BOOKS_SEARCH)
    cover = _search(client, "達人プログラマー")[0]["cover_url"]
    assert cover.startswith("https://")


# --- 足りない項目を Google Books で埋める ---

def test_openBDに無いページ数をGoogleBooksで補う(client, fake_internet, google_key):
    # openBD はページ数・表紙・分類を1つも持っていない（実測8冊すべて）
    fake_internet.openbd = (200, OPENBD_FOUND)
    fake_internet.google = (200, GOOGLE_BOOKS_FOUND)
    fake_internet.cover = (404, b"")
    body = client.get("/api/isbn/9784274226298").json()
    assert body["source"] == "openbd"
    assert body["total"] == 321


def test_国会図書館に落ちたときGoogleBooksへ二度聞かない(client, fake_internet, google_key):
    # Google Books を素通りして国会図書館まで来た＝すでに「無い」と分かっている
    fake_internet.openbd = (200, OPENBD_NOT_FOUND)
    fake_internet.google = (200, {"totalItems": 0})
    fake_internet.ndl = (200, NDL_FOUND)
    fake_internet.cover = (200, COVER_BYTES)
    assert client.get("/api/isbn/9784274226298").json()["source"] == "ndl"
    assert len(fake_internet.requests_to(GOOGLE_HOST)) == 1


def test_ISBNは速いopenBDから先に引く(client, fake_internet, google_key):
    # 国会図書館は平均6.5秒かかり、30秒で返ってこないこともある（実測）
    fake_internet.openbd = (200, OPENBD_FOUND)
    fake_internet.cover = (200, COVER_BYTES)
    body = client.get("/api/isbn/9784274226298").json()
    assert body["source"] == "openbd"
    # 書影だけは国会図書館から取るので、検索APIを呼んでいないことを見る
    searches = [
        r for r in fake_internet.requests_to(NDL_HOST)
        if not r.url.path.startswith("/thumbnail/")
    ]
    assert searches == []


def test_openBDにもGoogleBooksにも無ければ国会図書館を引く(client, fake_internet, google_key):
    # 古い本や流通の少ない本は国会図書館にしか無いことがある
    fake_internet.openbd = (200, [None])
    fake_internet.google = (200, {"totalItems": 0})
    fake_internet.ndl = (200, NDL_FOUND)
    fake_internet.cover = (200, COVER_BYTES)
    assert client.get("/api/isbn/9784274226298").json()["source"] == "ndl"
