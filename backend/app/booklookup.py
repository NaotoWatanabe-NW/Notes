"""ISBN から本の情報を調べる。

外部サービスを順に当たり、最初に見つかったものを使う。どれも落ちることが
あるので、1つ失敗しても次に進み、全部だめなら None を返して手入力に戻す。

実際に叩いて確かめた各サービスの性質（2026-09時点）:

- 国立国会図書館サーチ: 和書に強い。著者・出版社が項目ごとに分かれていて
  いちばん扱いやすい。XML(RSS) で返ってくる
- openBD: 和書・洋書とも JSON で1発。見つからないときは null が返る
- Google Books: 洋書に強いが、APIキーなしだと環境によって 429（レート制限）
  になる。そのため最後に回している
"""
import os
import re
import time
import xml.etree.ElementTree as ET

import httpx
from pydantic import BaseModel

from .isbn import InvalidIsbnError
from .isbn import normalize as normalize_isbn

# 外部サービスが遅いときに画面を待たせないよう、短めに切る
TIMEOUT = httpx.Timeout(5.0)
# 書名検索だけは長めにする。国会図書館サーチは同じクエリでも 0.1〜17秒と
# 応答時間のばらつきが大きく、5秒だと成功したりしなかったりするため。
# 画面には「探しています…」が出るので、待たせても迷子にはならない。
SEARCH_TIMEOUT = httpx.Timeout(12.0)

# 国会図書館サーチは、同じクエリでも通ったり通らなかったりする
# （実測: 3秒あけて 6件 → 503）。429 や 5xx はすぐ返ってくるので、
# 一呼吸おいて1度だけやり直す。時間切れのときは既に待っているのでやり直さない。
RETRY_AFTER_SECONDS = 0.8
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# 同じ言葉を続けて検索したときに、また外に出ていかないようにする。
# 本の情報はすぐ変わるものではないので、しばらく使い回してよい。
CACHE_TTL_SECONDS = 600
CACHE_MAX_ENTRIES = 200
_cache: dict[str, tuple[float, list["BookInfo"]]] = {}


def clear_cache() -> None:
    """テストや、取り直したいときに使う"""
    _cache.clear()


def _cache_get(key: str) -> "list[BookInfo] | None":
    found = _cache.get(key)
    if found is None:
        return None
    stored_at, value = found
    if time.monotonic() - stored_at > CACHE_TTL_SECONDS:
        del _cache[key]
        return None
    return value


def _cache_put(key: str, value: "list[BookInfo]") -> None:
    # 増えすぎたら古いものから捨てる（dict は入れた順を保つ）
    while len(_cache) >= CACHE_MAX_ENTRIES:
        del _cache[next(iter(_cache))]
    _cache[key] = (time.monotonic(), value)

NDL_ENDPOINT = "https://ndlsearch.ndl.go.jp/api/opensearch"
NDL_THUMBNAIL = "https://ndlsearch.ndl.go.jp/thumbnail/{isbn}.jpg"
OPENBD_ENDPOINT = "https://api.openbd.jp/v1/get"
GOOGLE_BOOKS_ENDPOINT = "https://www.googleapis.com/books/v1/volumes"

# Google Books は**キー無しだと1日あたりの上限が 0**で、必ず 429 が返る
# （実測: quota_limit_value = "0"）。キーがあるときだけ問い合わせる。
# 取り方と料金の話は backend/.env.example を参照。
GOOGLE_BOOKS_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY", "").strip()

# 国会図書館サーチのサムネイルは Referer がないと 403 になる。
# ブラウザから直接読むとこの Referer が付かないので、サーバー側で中継する。
NDL_REFERER = "https://ndlsearch.ndl.go.jp/"

_NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcndl": "http://ndl.go.jp/dcndl/terms/",
}
# xsi:type が付いた <dc:subject> は分類記号（NDC など）。人が読む件名は
# 属性の無いほうなので、それを見分けるために使う
_XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

# 「422p」「x, 422p」のような書き方からページ数だけ取り出す
_PAGES = re.compile(r"(\d+)\s*p")

# 著者名の末尾に付く生没年（例: "村上, 雅章, 1960-"）を落とすための正規表現
_LIFE_YEARS = re.compile(r",?\s*\d{4}\s*-\s*\d{0,4}\s*$")
_JAPANESE = re.compile(r"[ぁ-んァ-ヶ一-龥]")


class SearchUnavailable(RuntimeError):
    """外部サービスが混んでいて検索できなかった。

    「見つからなかった」とは意味が違う。混同すると、画面が
    「その本はありません」と嘘をつくことになるので分けている。
    """


class BookInfo(BaseModel):
    """ISBN 検索の結果。保存はせず、フォームの自動入力に使うだけ"""
    isbn: str
    title: str
    author: str | None = None
    publisher: str | None = None
    # 総ページ数。進捗バーと「p.182 / 320」の表示に使う
    total: int | None = None
    # 分野（国会図書館の件名）。振り返りの「よく読む分野」に使う
    category: str | None = None
    cover_url: str | None = None
    source: str


def get_http_client():
    """リクエストごとに HTTP クライアントを渡し、終わったら必ず閉じる。

    get_db と同じ形にしてあるので、テストでは dependency_overrides で
    差し替えられる（外部サービスを本当に叩かずに済む）。
    """
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        yield client


def _clean_person(name: str) -> str:
    """図書館の表記「姓, 名, 生年-」を、読みやすい形に直す。

    - 日本語の名前: 「村上, 雅章, 1960-」→「村上雅章」（姓名の順はそのまま）
    - 欧文の名前: 「Thomas, David, 1956-」→「David Thomas」（姓名をひっくり返す）
    """
    name = _LIFE_YEARS.sub("", name.strip()).strip().strip(",").strip()
    if "," not in name:
        return name
    surname, _, given = name.partition(",")
    surname, given = surname.strip(), given.strip()
    if not given:
        return surname
    if _JAPANESE.search(name):
        return f"{surname}{given}"
    return f"{given} {surname}"


def _join_people(names: list[str]) -> str | None:
    cleaned = [_clean_person(n) for n in names]
    # 同じ人が重複して入っていることがあるので、順番を保ったまま重複を除く
    unique = list(dict.fromkeys(n for n in cleaned if n))
    return ", ".join(unique) or None


def _ndl_item_to_info(item, isbn: str | None) -> BookInfo | None:
    """国会図書館サーチの <item> 1件を BookInfo に直す"""
    title = (item.findtext("dc:title", namespaces=_NS) or "").strip()
    if not title:
        return None

    if isbn is None:
        # 書名検索では ISBN が項目として入っている（ハイフン付き）
        raw = item.findtext(
            'dc:identifier[@{http://www.w3.org/2001/XMLSchema-instance}type='
            '"dcndl:ISBN"]',
            namespaces=_NS,
        )
        try:
            isbn = normalize_isbn(raw)
        except InvalidIsbnError:
            isbn = None
        if isbn is None:
            # ISBN が無い本は登録できないので候補から外す
            return None

    creators = [
        (element.text or "").strip()
        for element in item.findall("dc:creator", namespaces=_NS)
    ]

    # <dc:extent>422p</dc:extent> からページ数を取り出す
    extent = item.findtext("dc:extent", namespaces=_NS) or ""
    pages = _PAGES.search(extent)

    # 分類記号ではなく、人が読む件名のほうを分野として使う
    subjects = [
        (element.text or "").strip()
        for element in item.findall("dc:subject", namespaces=_NS)
        if element.get(_XSI_TYPE) is None
    ]

    return BookInfo(
        isbn=isbn,
        title=title,
        author=_join_people(creators),
        publisher=(item.findtext("dc:publisher", namespaces=_NS) or "").strip() or None,
        total=int(pages.group(1)) if pages else None,
        category=next((s for s in subjects if s), None),
        source="ndl",
    )


def _from_ndl(client: httpx.Client, isbn: str) -> BookInfo | None:
    """国立国会図書館サーチ（OpenSearch）。XML で返ってくる"""
    response = _get_with_retry(client, NDL_ENDPOINT, {"isbn": isbn}, TIMEOUT)

    item = ET.fromstring(response.text).find("./channel/item")
    if item is None:
        return None
    return _ndl_item_to_info(item, isbn)


def _for_match(text: str) -> str:
    """比較用に、空白と区切り記号を落として小文字に揃える"""
    return re.sub(r"[\s・:：,，.／/\-–—]", "", text).lower()


def _terms(query: str) -> list[str]:
    """クエリを語に分ける。

    「こころ 夏目漱石」のように書名と著者を並べて打つことがあるので、
    全体を1つの塊として探すと当たらない。語ごとに見る。
    """
    parts = [_for_match(part) for part in query.split()]
    return [part for part in parts if part] or [_for_match(query)]


def _relevance(info: BookInfo, terms: list[str]) -> int:
    """クエリとの一致の強さ。0 は「関係なし」で候補から外す。

    **打った語がすべて、書名か著者のどちらかに出てくること**を条件にする。
    国会図書館サーチは関連度順ではなく五十音順で返し、Google Books も
    関係の薄い本を混ぜてくるので、こちらで見て落とす。

    著者に当たったものを上に出すのは、人名で探したときに「その人が書いた本」
    より先に「その人について書かれた本」が並ぶと使いものにならないため。
    """
    title = _for_match(info.title)
    author = _for_match(info.author or "")

    if not all(term in title or term in author for term in terms):
        return 0
    if any(term in author for term in terms):
        return 4
    # 書名がクエリで始まるものを上に出す
    return 3 if title.startswith(terms[0]) else 2


def _identity(info: BookInfo) -> str:
    """同じ本の版違い・刷違いをまとめるための見分け方"""
    return f"{_for_match(info.title)}|{_for_match(info.author or '')}"


def _get_with_retry(client: httpx.Client, url: str, params: dict, timeout) -> httpx.Response:
    """混んでいて弾かれたときだけ、一呼吸おいて1度やり直す。

    時間切れ（ReadTimeout）はすでに長く待っているので、やり直さずに諦める。
    """
    response = client.get(url, params=params, timeout=timeout)
    if response.status_code in RETRYABLE_STATUS:
        time.sleep(RETRY_AFTER_SECONDS)
        response = client.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response


def _search_by(
    client: httpx.Client, key: str, query: str, terms: list[str], limit: int
) -> tuple[list[BookInfo], bool]:
    """国会図書館サーチを1回引く。

    戻りは (見つかったもの, 引けたかどうか)。混んでいて引けなかったときは
    第2要素が False になる。これを「0件」と同じにすると、画面が
    「その本はありません」と嘘をついてしまう。
    """
    try:
        response = _get_with_retry(
            client,
            NDL_ENDPOINT,
            {key: query, "cnt": 30, "mediatype": "books"},
            SEARCH_TIMEOUT,
        )
        items = ET.fromstring(response.text).findall("./channel/item")
    except (httpx.HTTPError, ET.ParseError):
        return [], False

    return _pick(items, terms, limit), True


def _pick(items, terms: list[str], limit: int) -> list[BookInfo]:
    scored: list[tuple[int, BookInfo]] = []
    seen: set[str] = set()
    for item in items:
        info = _ndl_item_to_info(item, None)
        if info is None:
            continue
        # 同じ本が版違い・刷違いで何度も並ぶので、書名と著者で重複を除く
        key = _identity(info)
        if key in seen:
            continue
        score = _relevance(info, terms)
        if score == 0:
            continue
        seen.add(key)
        scored.append((score, info))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [info for _, info in scored[:limit]]


def _google_search(
    client: httpx.Client, query: str, terms: list[str], limit: int
) -> tuple[list[BookInfo], bool]:
    """Google Books で書名を引く。

    国会図書館より**桁違いに速い**（実測 0.5〜1.1秒 対 初回12〜39秒）ので、
    キーがあるならこちらを先に引く。戻りは (見つかったもの, 引けたかどうか)。
    """
    if not GOOGLE_BOOKS_KEY:
        return [], False
    try:
        response = _get_with_retry(
            client,
            GOOGLE_BOOKS_ENDPOINT,
            {
                "q": f"intitle:{query}",
                "maxResults": min(limit * 3, 40),
                "key": GOOGLE_BOOKS_KEY,
                "country": "JP",
            },
            TIMEOUT,
        )
        items = response.json().get("items") or []
    except (httpx.HTTPError, ValueError, KeyError):
        return [], False

    found: list[BookInfo] = []
    for item in items:
        info = _volume_to_info(item, None)
        if info is not None:
            found.append(info)
    return _pick_scored(found, terms, limit), True


def search(client: httpx.Client, query: str, limit: int = 5) -> list[BookInfo]:
    """書名・著者で本を探す。⌘K の「本を追加」で使う。

    まず書名で引き、見つからなければ著者で引き直す。外部サービスは
    遅いことがあるので、いきなり2回引かずに必要なときだけ2回目に行く。
    ISBN が分からない本は登録できないので候補から外す。
    """
    terms = _terms(query)
    if not terms or not terms[0]:
        return []

    cache_key = f"{'|'.join(terms)}|{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # まず Google Books（速い）。見つかればそれで終わり
    found, reached = _google_search(client, query, terms, limit)

    # 見つからなければ国会図書館。和書の副題や旧版はこちらの方が詳しい
    if not found:
        by_title, reached_title = _search_by(client, "title", query, terms, limit)
        found = by_title
        reached = reached or reached_title

    # 書名がクエリで始まる本が見つかっていれば、それが探しものとみて打ち切る。
    # そうでないときだけ著者でも引く（外部サービスは遅いので往復を増やさない）
    if not any(_relevance(info, terms) >= 3 for info in found):
        by_author, reached_author = _search_by(client, "creator", query, terms, limit)
        reached = reached or reached_author
        merged = {_identity(info): info for info in found}
        for info in by_author:
            merged.setdefault(_identity(info), info)
        found = _pick_scored(list(merged.values()), terms, limit)

    if not reached:
        # 一度も引けていない。0件と言い切ってはいけない
        raise SearchUnavailable

    _cache_put(cache_key, found)
    return found


def _pick_scored(infos: list[BookInfo], terms: list[str], limit: int) -> list[BookInfo]:
    scored = [(_relevance(info, terms), info) for info in infos]
    scored = [pair for pair in scored if pair[0] > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [info for _, info in scored[:limit]]


def _from_openbd(client: httpx.Client, isbn: str) -> BookInfo | None:
    """openBD。見つからないときは配列の中身が null になる"""
    response = client.get(OPENBD_ENDPOINT, params={"isbn": isbn})
    response.raise_for_status()

    entries = response.json()
    if not entries or entries[0] is None:
        return None

    summary = entries[0].get("summary") or {}
    title = (summary.get("title") or "").strip()
    if not title:
        return None

    # openBD の著者は「姓,名,生年- 姓,名,生年-」のように空白区切りで並ぶ
    raw_author = (summary.get("author") or "").strip()
    return BookInfo(
        isbn=isbn,
        title=title,
        author=_join_people(raw_author.split()) if raw_author else None,
        publisher=(summary.get("publisher") or "").strip() or None,
        cover_url=(summary.get("cover") or "").strip() or None,
        source="openbd",
    )


def _volume_to_info(item: dict, isbn: str | None) -> BookInfo | None:
    """Google Books の1件を BookInfo に直す。

    isbn を渡さないとき（書名検索）は、返ってきた識別子から拾う。
    ISBN が分からない本は登録できないので候補から外す。
    """
    info = item.get("volumeInfo") or {}
    title = (info.get("title") or "").strip()
    if not title:
        return None

    if isbn is None:
        for identifier in info.get("industryIdentifiers") or []:
            if identifier.get("type") in ("ISBN_13", "ISBN_10"):
                try:
                    isbn = normalize_isbn(identifier.get("identifier"))
                except InvalidIsbnError:
                    isbn = None
                if isbn:
                    break
        if isbn is None:
            return None

    subtitle = (info.get("subtitle") or "").strip()
    images = info.get("imageLinks") or {}
    categories = info.get("categories") or []
    page_count = info.get("pageCount")

    # Google が返す表紙URLは http:// のまま。Tailscale 越しの HTTPS で開くと
    # 混在コンテンツとしてブラウザに弾かれるので、https に直す
    # （同じURLの https でそのまま読めることは実測で確認済み）
    cover = (images.get("thumbnail") or images.get("smallThumbnail") or "").strip()
    if cover.startswith("http://"):
        cover = "https://" + cover[len("http://") :]

    return BookInfo(
        isbn=isbn,
        title=f"{title} : {subtitle}" if subtitle else title,
        author=", ".join(info.get("authors") or []) or None,
        publisher=(info.get("publisher") or "").strip() or None,
        total=page_count if isinstance(page_count, int) and page_count > 0 else None,
        category=categories[0] if categories else None,
        cover_url=cover or None,
        source="google_books",
    )


def _from_google_books(client: httpx.Client, isbn: str) -> BookInfo | None:
    """Google Books で ISBN を引く。**APIキーが要る**。

    キーが無いと必ず 429 が返るだけなので、設定されていなければ引かない
    （無駄な往復を1回省ける）。
    """
    if not GOOGLE_BOOKS_KEY:
        return None

    response = _get_with_retry(
        client,
        GOOGLE_BOOKS_ENDPOINT,
        {"q": f"isbn:{isbn}", "key": GOOGLE_BOOKS_KEY, "country": "JP"},
        TIMEOUT,
    )
    items = response.json().get("items") or []
    return _volume_to_info(items[0], isbn) if items else None


def fetch_ndl_cover(client: httpx.Client, isbn: str) -> httpx.Response | None:
    """国会図書館サーチの書影を、必要な Referer を付けて取ってくる。

    Referer を付けないと 403 が返る。画像が無い本も 403 になるので、
    ここでは「200 で画像が返ったときだけ成功」とみなす。
    """
    try:
        response = client.get(
            NDL_THUMBNAIL.format(isbn=isbn), headers={"Referer": NDL_REFERER}
        )
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    if not response.headers.get("content-type", "").startswith("image/"):
        return None
    return response


def _fill_gaps(
    client: httpx.Client,
    info: BookInfo,
    extra: BookInfo | None = None,
    asked_google: bool = False,
) -> BookInfo:
    """足りない項目を Google Books で補う。

    openBD はページ数・表紙・分類を**1つも持っていない**（実測8冊すべて）。
    国会図書館もページ数は半分ほど（実測6冊中3冊）。Google Books は見つかった
    本のページ数をほぼ必ず持っている（実測5/5）ので、欠けているところだけ埋める。

    `asked_google` は、呼ぶ側がもう Google Books に聞いたあとという意味。
    同じ問い合わせを二度投げないために渡す。
    """
    if info.total and info.category and info.cover_url:
        return info

    if not asked_google:
        if not GOOGLE_BOOKS_KEY or info.isbn is None:
            return info
        try:
            extra = _from_google_books(client, info.isbn)
        except (httpx.HTTPError, ValueError, KeyError):
            return info
    if extra is None:
        return info

    info.total = info.total or extra.total
    info.category = info.category or extra.category
    info.cover_url = info.cover_url or extra.cover_url
    return info


def lookup(client: httpx.Client, isbn: str) -> BookInfo | None:
    """ISBN（13桁に正規化済み）から本の情報を探す。見つからなければ None

    openBD を先頭にしているのは、速くて取りこぼしが少ないため（実測 平均
    0.04秒・6冊中5冊）。国会図書館は最後に回す。平均 6.5秒かかるうえ
    30秒で返ってこないこともあり、しかも同じ6冊のうち2冊しか持っていない。
    ただし古い本や流通の少ない本は国会図書館にしか無いことがあるので残す。
    """
    from_google: BookInfo | None = None
    asked_google = False

    for source in (_from_openbd, _from_google_books, _from_ndl):
        try:
            info = source(client, isbn)
        except (httpx.HTTPError, ET.ParseError, ValueError, KeyError):
            # 1つのサービスが落ちていても、次のサービスで探せばよい
            info = None
        if source is _from_google_books:
            asked_google, from_google = True, info
        if info is None:
            continue

        if info.cover_url is None and fetch_ndl_cover(client, isbn) is not None:
            # 書影は Referer が要るので、ブラウザから直接ではなく
            # 自分のAPI経由で取らせる
            info.cover_url = f"/api/covers/{isbn}"

        # ページ数など、まだ空いているところを Google Books で埋める
        return _fill_gaps(client, info, from_google, asked_google)
    return None
