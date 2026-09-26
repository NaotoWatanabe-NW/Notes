"""振り返り（期間ごとの集計）のAPIのテスト"""
from app.timeutil import today_jst


def _finished(client, title, finished_on, **fields):
    payload = {
        "title": title,
        "status": "finished",
        "finished_on": finished_on,
    } | fields
    response = client.post("/api/books", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _note(client, book_id, **fields):
    payload = {"kind": "memo", "text": "メモ"} | fields
    return client.post(f"/api/books/{book_id}/notes", json=payload).json()


# --- 期間の指定 ---

def test_年の振り返りを取得できる(client):
    _finished(client, "1月に読んだ本", "2026-01-20")
    body = client.get("/api/reviews/2026").json()
    assert body["label"] == "2026年"
    assert body["finished_count"] == 1


def test_月の振り返りを取得できる(client):
    _finished(client, "9月に読んだ本", "2026-09-10")
    body = client.get("/api/reviews/2026-09").json()
    assert body["label"] == "2026年9月"
    assert body["finished_count"] == 1


def test_期間外に読んだ本は数えない(client):
    _finished(client, "去年の本", "2025-12-31")
    _finished(client, "今年の本", "2026-01-01")
    assert client.get("/api/reviews/2026").json()["finished_count"] == 1


def test_月の振り返りは同じ月の本だけ数える(client):
    _finished(client, "8月の本", "2026-08-31")
    _finished(client, "9月の本", "2026-09-01")
    assert client.get("/api/reviews/2026-09").json()["finished_count"] == 1


def test_読了していない本は数えない(client):
    client.post("/api/books", json={"title": "読書中の本", "status": "reading"})
    assert client.get("/api/reviews/2026").json()["finished_count"] == 0


def test_期間の指定が不正だと422になる(client):
    assert client.get("/api/reviews/2026-13").status_code == 422
    assert client.get("/api/reviews/こんげつ").status_code == 422


# --- 集計の中身 ---

def test_読んだページ数を合計する(client):
    _finished(client, "A", "2026-03-01", total=300)
    _finished(client, "B", "2026-04-01", total=220)
    assert client.get("/api/reviews/2026").json()["pages"] == 520


def test_総ページが分からない本は読んだところまでを足す(client):
    _finished(client, "総ページ不明", "2026-03-01", page=120)
    assert client.get("/api/reviews/2026").json()["pages"] == 120


def test_期間内に書いたノートの件数を数える(client):
    book = _finished(client, "A", "2026-03-01")
    _note(client, book["id"])
    _note(client, book["id"], kind="quote", text="引用", page=10)
    # ノートは今日の日時で作られるので、今年の振り返りに入る
    body = client.get(f"/api/reviews/{today_jst().year}").json()
    assert body["note_count"] == 2


def test_よく読む分野は最も多い分野を返す(client):
    _finished(client, "A", "2026-03-01", category="プログラミング")
    _finished(client, "B", "2026-04-01", category="プログラミング")
    _finished(client, "C", "2026-05-01", category="経済")
    assert client.get("/api/reviews/2026").json()["top_category"] == "プログラミング"


def test_分野が1件も無ければnullを返す(client):
    _finished(client, "A", "2026-03-01")
    assert client.get("/api/reviews/2026").json()["top_category"] is None


def test_読み終えた本の一覧が新しい順に入る(client):
    _finished(client, "先に読んだ本", "2026-03-01")
    _finished(client, "後に読んだ本", "2026-06-01")
    titles = [b["title"] for b in client.get("/api/reviews/2026").json()["books"]]
    assert titles == ["後に読んだ本", "先に読んだ本"]


# --- 目標 ---

def test_年の振り返りには目標と残りが入る(client):
    client.patch("/api/settings", json={"yearly_goal": 50})
    _finished(client, "A", "2026-03-01")
    body = client.get("/api/reviews/2026").json()
    assert body["yearly_goal"] == 50
    assert body["remaining_to_goal"] == 49


def test_目標を超えたら残りは0になる(client):
    client.patch("/api/settings", json={"yearly_goal": 1})
    _finished(client, "A", "2026-03-01")
    _finished(client, "B", "2026-04-01")
    assert client.get("/api/reviews/2026").json()["remaining_to_goal"] == 0


def test_月の振り返りには年間目標を出さない(client):
    # 目標は年間のものなので、月の集計に並べると誤解を招く
    body = client.get("/api/reviews/2026-09").json()
    assert body["yearly_goal"] is None
    assert body["remaining_to_goal"] is None


# --- 棒グラフ ---

def test_年の棒グラフは12ヶ月ぶん返る(client):
    _finished(client, "3月の本", "2026-03-15")
    bars = client.get("/api/reviews/2026").json()["bars"]
    assert len(bars) == 12
    assert bars[2] == {"label": "3月", "value": 1, "current": False}
    assert bars[0]["value"] == 0


def test_月の棒グラフは週ぶん返る(client):
    _finished(client, "第1週の本", "2026-09-03")
    _finished(client, "第3週の本", "2026-09-17")
    bars = client.get("/api/reviews/2026-09").json()["bars"]
    assert len(bars) == 5
    assert bars[0]["value"] == 1
    assert bars[2]["value"] == 1
    assert bars[1]["value"] == 0


def test_今月の棒だけが現在としてハイライトされる(client):
    today = today_jst()
    bars = client.get(f"/api/reviews/{today.year}").json()["bars"]
    current = [i for i, bar in enumerate(bars) if bar["current"]]
    assert current == [today.month - 1]


def test_過去の年にはハイライトされる棒が無い(client):
    bars = client.get("/api/reviews/2020").json()["bars"]
    assert not any(bar["current"] for bar in bars)


# --- いちばん残した言葉 ---

def test_評価の高い本の引用が選ばれる(client):
    low = _finished(client, "評価3の本", "2026-03-01", rating=3)
    high = _finished(client, "評価5の本", "2026-03-02", rating=5)
    _note(client, low["id"], kind="quote", text="評価3の本からの引用", page=1)
    _note(client, high["id"], kind="quote", text="評価5の本からの引用", page=2)
    quote = client.get(f"/api/reviews/{today_jst().year}").json()["top_quote"]
    assert quote["text"] == "評価5の本からの引用"
    assert quote["book_title"] == "評価5の本"
    assert quote["page"] == 2


def test_メモは引用として選ばれない(client):
    book = _finished(client, "A", "2026-03-01", rating=5)
    _note(client, book["id"], kind="memo", text="これはメモ")
    assert client.get(f"/api/reviews/{today_jst().year}").json()["top_quote"] is None


def test_引用が無ければnullを返す(client):
    assert client.get("/api/reviews/2026").json()["top_quote"] is None


# --- 期間の一覧 ---

def test_期間の一覧に今年と今月が入る(client):
    today = today_jst()
    periods = [row["period"] for row in client.get("/api/reviews").json()]
    assert str(today.year) in periods
    assert f"{today.year}-{today.month:02d}" in periods


def test_期間の一覧に読了した本のある年が入る(client):
    _finished(client, "2024年に読んだ本", "2024-05-01")
    assert "2024" in [row["period"] for row in client.get("/api/reviews").json()]


def test_期間の一覧に冊数が入る(client):
    today = today_jst()
    _finished(client, "今年の本", f"{today.year}-01-15")
    _finished(client, "今年の本その2", f"{today.year}-02-20")
    rows = {row["period"]: row["count"] for row in client.get("/api/reviews").json()}
    assert rows[str(today.year)] == 2


def test_期間の一覧に今月と先月の目印が付く(client):
    subs = {row["period"]: row["sub"] for row in client.get("/api/reviews").json()}
    assert "今月" in subs.values()
    assert "先月" in subs.values()


def test_今年の行には何月までかが入る(client):
    today = today_jst()
    rows = {row["period"]: row for row in client.get("/api/reviews").json()}
    assert rows[str(today.year)]["sub"] == f"1月〜{today.month}月"
