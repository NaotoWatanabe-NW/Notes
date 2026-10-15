"""出版社ノート（`reports/publishers/*.md`）に「この出版社の本」の一覧を差し込むストア

出版社ごとのノート。著者ノート（`author_store.py`）と同じ仕組みで、**本文はユーザーが書き**、
アプリが書くのはマーカー `<!-- notes:books:start --> … <!-- notes:books:end -->` の間だけ。
仕組み（走査・自動作成の安全策・差し込み）は `author_store` を `NoteKind`（`PUBLISHER`）で
切り替えて使う。安全策の入った関数を写さないのは、写すと片方だけ直る不具合が出るため。

- **出版社の名前**: (a) `Book.publisher`（文字列全体。`,` `・` で分けない）、(b) 著者欄の末尾の
  カタカナ（`茸本朗・ハーベスト` の `ハーベスト`）、(c) 出版社欄と一致して著者欄から外した名前
  （`author_store.publishers_in_author`）。
- **照合**: `author_store.author_key`（`・`・空白・`.`・`=` を除き casefold）。表記揺れ
  （`学研プラス` と `株式会社学研プラス`）はまとめない。まとめたいときはノートの `aliases` に足す。
- **ノートが集める名前**: ファイル名と `aliases`。`,` `、` `・` で分けない（出版社欄を分けないのと揃える）。
- **ノートを作るのは、レポートが1冊以上ある出版社に限り、どのノートも集めていないときだけ**
  （著者ノートと同じ）。全部の出版社は `scripts/create_notes.py` で作る。

更新は `ThemeWatcher` が `author_store.rebuild` の次に `rebuild()` を呼んで行う。
設計: docs/design/0006-katakana-split-and-publisher-notes.md
"""

from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from . import author_store, report_store, theme_store
from .models import Book

PUBLISHERS_DIRNAME = "publishers"
HUB_NAME = "出版社一覧.md"
NOTE_TYPE = "publisher-note"
HUB_TYPE = "publisher-hub"

HUB_HEADER = f"""---
type: {HUB_TYPE}
---

# 出版社一覧

出版社ノートの入口。レポートが1冊でもある出版社のノートは、このフォルダ（`publishers/`）にアプリが自動で作る。
レポートの無い出版社も「出版社名.md」を作れば本の一覧が入る。同じ出版社の別の表記（「学研プラス」と
「株式会社学研プラス」など）は、残すほうのノートの frontmatter の `aliases` に足すと1つにまとまる
（先に aliases を足してから、もう一方のノートを消す）。
ここにも自由に書いてよい（下の一覧の部分だけアプリが書き直す）。
"""


def publishers_dir() -> Path:
    return report_store.reports_dir() / PUBLISHERS_DIRNAME


def publisher_name(text: str) -> str:
    """表示名: 書式文字を落として NFKC、空白を1つに詰めて strip（分けない・役割も落とさない）。"""
    return author_store._SPACES.sub(" ", author_store._normalize(text)).strip()


def note_names(meta: dict, stem: str) -> tuple[str, ...]:
    """stem と frontmatter の `aliases` を `publisher_name` にしたもの。

    キーが空のものを除き、キーで重複を除く。`,` `、` `・` では分けない（`ディスカヴァー・トゥエンティワン.md` は
    その1つの名前を集める）。
    """
    names: list[str] = []
    seen: set[str] = set()
    for text in author_store._note_texts(meta, stem):
        name = publisher_name(text)
        key = author_store.author_key(name)
        if key and key not in seen:
            seen.add(key)
            names.append(name)
    return tuple(names)


def collect_publishers(books: list[Book]) -> dict[str, author_store.Author]:
    """id 順に本を見て、出版社の名前ごとに本を集める。キー → Author（出てきた順。`legacy_keys` は空）。

    1冊の名前: 出版社欄（`publisher_name`。キーが空なら無し）＋ 著者欄から外した出版社
    （`author_store.publishers_in_author`。比べる出版社欄は渡された本すべて）。1冊の中でキーが同じものは1つ。
    表示名: そのキーを出版社欄に持つ本があれば、その最初の（id が最小の）本の出版社欄の表記。
    無ければ（著者欄からだけ出た名前）、最初に出た本の著者欄からの表記。
    """
    ordered = sorted(books, key=lambda b: b.id)
    publisher_keys = author_store._publisher_keys(books)

    # 出版社欄の表記を先に決める（著者欄からの表記より優先するため）
    from_field: dict[str, str] = {}
    for book in ordered:
        if book.publisher:
            name = publisher_name(book.publisher)
            from_field.setdefault(author_store.author_key(name), name)
    from_field.pop("", None)

    names: dict[str, str] = {}
    collected: dict[str, list[Book]] = {}
    for book in ordered:
        found: dict[str, str] = {}   # この本の中のキー → 表記
        if book.publisher:
            name = publisher_name(book.publisher)
            if author_store.author_key(name):
                found.setdefault(author_store.author_key(name), name)
        for name in author_store.publishers_in_author(book.author, publisher_keys):
            name = publisher_name(name)
            if author_store.author_key(name):
                found.setdefault(author_store.author_key(name), name)
        for key, name in found.items():
            names.setdefault(key, from_field.get(key, name))
            collected.setdefault(key, []).append(book)
    return {key: author_store.Author(key, names[key], tuple(found_books))
            for key, found_books in collected.items()}


PUBLISHER = author_store.NoteKind(
    label="出版社", dirname=PUBLISHERS_DIRNAME, hub_name=HUB_NAME, note_type=NOTE_TYPE,
    hub_header=HUB_HEADER, source="出版社欄と著者欄",
    empty_hint="集める名前はファイル名と frontmatter の `aliases` で決まります。",
    note_names=note_names, legacy_keys=lambda text: frozenset(), collect=collect_publishers,
)


def rebuild(db: Session, *, quiet_seconds: float = theme_store.QUIET_SECONDS,
            now: Optional[float] = None) -> list[Path]:
    """出版社ノートの一覧・自動作成・ハブを書き直す。書いた（作った）ファイルを返す。"""
    return author_store.rebuild(db, quiet_seconds=quiet_seconds, now=now, kind=PUBLISHER)
