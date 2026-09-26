"""ISBN 検索テスト用の応答サンプル。

実際に各サービスを叩いて得たレスポンスから、必要な部分だけを抜き出したもの。
形を勝手に作らず、本物に合わせてある。
"""

# 国立国会図書館サーチ（達人プログラマー）。実レスポンスから項目を抜粋
NDL_FOUND = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:openSearch="http://a9.com/-/spec/opensearchrss/1.0/"
     xmlns:dcndl="http://ndl.go.jp/dcndl/terms/"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.0">
  <channel>
    <openSearch:totalResults>1</openSearch:totalResults>
    <item>
      <title>達人プログラマー : 熟達に向けたあなたの旅</title>
      <dc:title>達人プログラマー : 熟達に向けたあなたの旅</dc:title>
      <dc:creator>Thomas, David, 1956-</dc:creator>
      <dc:creator>Hunt, Andrew, 1964-</dc:creator>
      <dc:creator>村上, 雅章, 1960-</dc:creator>
      <dcndl:edition>第2版</dcndl:edition>
      <dc:publisher>オーム社</dc:publisher>
      <dc:extent>422p</dc:extent>
      <dc:subject>プログラミング (コンピュータ)</dc:subject>
      <dc:subject xsi:type="dcndl:NDC10">007.64</dc:subject>
      <dcterms:issued xmlns:dcterms="http://purl.org/dc/terms/">2020.11</dcterms:issued>
    </item>
  </channel>
</rss>
"""

# 見つからなかったとき。HTTP 200 のまま item が無いだけ（実測で確認）
NDL_NOT_FOUND = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:openSearch="http://a9.com/-/spec/opensearchrss/1.0/" version="2.0">
  <channel>
    <openSearch:totalResults>0</openSearch:totalResults>
  </channel>
</rss>
"""

# openBD。summary に必要な項目がまとまっている
OPENBD_FOUND = [
    {
        "summary": {
            "isbn": "9784873115658",
            "title": "リーダブルコード : より良いコードを書くためのシンプルで実践的なテクニック",
            "publisher": "オーム社",
            "pubdate": "201206",
            "author": "Boswell,Dustin Foucher,Trevor 角,征典",
            "cover": "",
        }
    }
]

# 見つからないときは配列の中身が null になる（実測で確認）
OPENBD_NOT_FOUND = [None]

GOOGLE_BOOKS_FOUND = {
    "totalItems": 1,
    "items": [
        {
            "volumeInfo": {
                "title": "The Pragmatic Programmer",
                "subtitle": "From Journeyman to Master",
                "authors": ["Andrew Hunt", "David Thomas"],
                "publisher": "Addison-Wesley Professional",
                "pageCount": 321,
                "categories": ["Computers"],
                "imageLinks": {
                    "smallThumbnail": "http://books.google.com/books/content?id=5wBQEp6ruIAC&img=1&zoom=5",
                    "thumbnail": "http://books.google.com/books/content?id=5wBQEp6ruIAC&img=1&zoom=1",
                },
            }
        }
    ],
}

GOOGLE_BOOKS_NOT_FOUND = {"totalItems": 0}

# JPEG のマジックナンバーだけの、ごく小さな画像
COVER_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32


# 書名検索の結果（⌘K の「本を追加」用）。
# 国会図書館サーチは関連度順ではなく五十音順で返し、クエリと関係の薄い本も
# 混ぜてくる。実際のレスポンスのその性質に合わせてある。
NDL_SEARCH_BY_TITLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:openSearch="http://a9.com/-/spec/opensearchrss/1.0/"
     xmlns:dcndl="http://ndl.go.jp/dcndl/terms/"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.0">
  <channel>
    <openSearch:totalResults>5</openSearch:totalResults>
    <item>
      <dc:title>愛の花束 : 2005年度新鋭随筆家傑作撰</dc:title>
      <dc:creator>徳光, 彩子</dc:creator>
      <dc:identifier xsi:type="dcndl:ISBN">978-4-88933-302-2</dc:identifier>
    </item>
    <item>
      <dc:title>実践JUnit : 達人プログラマーのユニットテスト技法</dc:title>
      <dc:creator>Langr, Jeff</dc:creator>
      <dc:identifier xsi:type="dcndl:ISBN">978-4-87311-730-0</dc:identifier>
    </item>
    <item>
      <dc:title>ISBNが付いていない資料</dc:title>
      <dc:creator>だれか</dc:creator>
      <dc:identifier xsi:type="dcndl:NDLBibID">000000001</dc:identifier>
    </item>
    <item>
      <dc:title>達人プログラマー : 職人から名匠への道</dc:title>
      <dc:creator>Hunt, Andrew, 1964-</dc:creator>
      <dc:publisher>オーム社</dc:publisher>
      <dc:extent>360p</dc:extent>
      <dc:identifier xsi:type="dcndl:ISBN">978-4-274-21933-7</dc:identifier>
    </item>
    <item>
      <dc:title>達人プログラマー : 職人から名匠への道</dc:title>
      <dc:creator>Hunt, Andrew, 1964-</dc:creator>
      <dc:identifier xsi:type="dcndl:ISBN">978-4-274-06885-0</dc:identifier>
    </item>
  </channel>
</rss>
"""

# 著者検索の結果。人名で探したときに使われる
NDL_SEARCH_BY_CREATOR = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:openSearch="http://a9.com/-/spec/opensearchrss/1.0/"
     xmlns:dcndl="http://ndl.go.jp/dcndl/terms/"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.0">
  <channel>
    <openSearch:totalResults>1</openSearch:totalResults>
    <item>
      <dc:title>ノルウェイの森</dc:title>
      <dc:creator>村上, 春樹, 1949-</dc:creator>
      <dc:publisher>講談社</dc:publisher>
      <dc:identifier xsi:type="dcndl:ISBN">978-4-06-274868-1</dc:identifier>
    </item>
  </channel>
</rss>
"""

# 「村上春樹」を書名で引いたとき。その人について書かれた本しか出てこない
NDL_SEARCH_ABOUT_AUTHOR = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:openSearch="http://a9.com/-/spec/opensearchrss/1.0/"
     xmlns:dcndl="http://ndl.go.jp/dcndl/terms/"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.0">
  <channel>
    <openSearch:totalResults>1</openSearch:totalResults>
    <item>
      <dc:title>アイロンをかける青年 : 村上春樹とアメリカ</dc:title>
      <dc:creator>千石, 英世</dc:creator>
      <dc:identifier xsi:type="dcndl:ISBN">978-4-7917-6100-5</dc:identifier>
    </item>
  </channel>
</rss>
"""


# Google Books の書名検索の結果。表紙URLが http:// で返ってくる点が大事
GOOGLE_BOOKS_SEARCH = {
    "totalItems": 2,
    "items": [
        {
            "volumeInfo": {
                "title": "達人プログラマー",
                "subtitle": "熟達に向けたあなたの旅",
                "authors": ["David Thomas", "Andrew Hunt"],
                "publisher": "オーム社",
                "pageCount": 422,
                "categories": ["Computers"],
                "industryIdentifiers": [
                    {"type": "ISBN_13", "identifier": "9784274226298"}
                ],
                "imageLinks": {
                    "thumbnail": "http://books.google.com/books/content?id=XXX&img=1"
                },
            }
        },
        {
            "volumeInfo": {
                "title": "ISBNが分からない本",
                "authors": ["だれか"],
                "industryIdentifiers": [{"type": "OTHER", "identifier": "XYZ"}],
            }
        },
    ],
}


# ページ数（dc:extent）を持っていない国会図書館の応答。実測でよくある
NDL_FOUND_NO_EXTENT = NDL_FOUND.replace("      <dc:extent>422p</dc:extent>\n", "")
