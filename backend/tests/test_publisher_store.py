"""出版社ノート（app/publisher_store.py）のテスト

著者ノートと同じ仕組み（author_store を NoteKind で切り替える）なので、ここでは出版社に固有の
ところ（名前の集め方・分けないこと・フォルダの別）と、安全策が出版社でも効いていることを見る。
DB はメモリ上、ノートとレポートは実ファイル。設計: docs/design/0006-katakana-split-and-publisher-notes.md
"""

import pytest
from sqlalchemy.orm import Session

from app import author_store, main, publisher_store, theme_store
from app.theme_store import END, START

from test_author_store import Shelf, read, write_note

HUB_NAME = publisher_store.HUB_NAME


@pytest.fixture(autouse=True)
def _forget_warned_notes():
    warned = (theme_store._warned_broken, theme_store._warned_write_failed,
              author_store._seen_doubts, author_store._warned_doubts)
    for each in warned:
        each.clear()
    yield
    for each in warned:
        each.clear()


@pytest.fixture
def db(db_engine):
    with Session(db_engine) as session:
        yield session


@pytest.fixture
def shelf(db):
    return Shelf(db)


@pytest.fixture
def publishers(tmp_path):
    # conftest が NOTES_REPORTS_DIR を tmp_path/reports に向けている
    directory = tmp_path / "reports" / "publishers"
    directory.mkdir(parents=True)
    return directory


@pytest.fixture
def themes(tmp_path):
    directory = tmp_path / "reports" / "themes"
    directory.mkdir(parents=True)
    return directory


def rebuild(db):
    return publisher_store.rebuild(db, quiet_seconds=0)


def note_names_in(directory):
    return sorted(p.name for p in directory.iterdir() if p.is_file() and p.name != HUB_NAME)


def collected(books):
    return {a.name: len(a.books) for a in publisher_store.collect_publishers(books).values()}


class TestCollectPublishers:
    def test_出版社欄ごとに本を集める(self, shelf):
        books = [shelf.add("本1", publisher="学研プラス"), shelf.add("本2", publisher="学研プラス"),
                 shelf.add("本3", publisher="ハーベスト")]

        assert collected(books) == {"学研プラス": 2, "ハーベスト": 1}

    def test_出版社欄は分けず全体を1つの名前にする(self, shelf):
        books = [shelf.add("本1", publisher="ディスカヴァー・トゥエンティワン"),
                 shelf.add("本2", publisher="オライリー・ジャパン ; オーム社 (発売)")]

        assert collected(books) == {"ディスカヴァー・トゥエンティワン": 1,
                                    "オライリー・ジャパン ; オーム社 (発売)": 1}

    def test_全角半角や空白や大文字小文字の違いは同じ出版社にする(self, shelf):
        books = [shelf.add("本1", publisher="ＨＳ"), shelf.add("本2", publisher="h s")]

        assert collected(books) == {"HS": 2}

    def test_表記揺れはまとめない(self, shelf):
        books = [shelf.add("本1", publisher="学研プラス"), shelf.add("本2", publisher="株式会社学研プラス")]

        assert collected(books) == {"学研プラス": 1, "株式会社学研プラス": 1}

    def test_著者欄の末尾のカタカナから出版社を集める(self, shelf):
        book = shelf.add("野草図鑑", author="茸本朗・ハーベスト")

        found = publisher_store.collect_publishers([book])

        assert [(a.name, a.books) for a in found.values()] == [("ハーベスト", (book,))]

    def test_出版社欄と一致して著者から外した名前の本もその出版社に入る(self, shelf):
        books = [shelf.add("本1", author="茸本朗, HS"), shelf.add("本2", publisher="HS")]

        assert collected(books) == {"HS": 2}

    def test_表示名は出版社欄の表記を優先する(self, shelf):
        books = [shelf.add("先の本", author="山田・ﾊｰﾍﾞｽﾄ"), shelf.add("後の本", publisher="ハーベスト　")]

        assert collected(books) == {"ハーベスト": 2}
        assert [a.name for a in publisher_store.collect_publishers(books).values()] == ["ハーベスト"]

    @pytest.mark.parametrize("publisher", [None, "", "  "])
    def test_出版社欄が空や空白だけの本はどの出版社にも入らない(self, shelf, publisher):
        book = shelf.add("本", author="熊野純彦", publisher=publisher)

        assert publisher_store.collect_publishers([book]) == {}

    def test_1冊の中で同じ出版社は1回だけ数える(self, shelf):
        book = shelf.add("野草図鑑", author="茸本朗・ハーベスト", publisher="ハーベスト")

        found = publisher_store.collect_publishers([book])

        assert [(a.name, len(a.books)) for a in found.values()] == [("ハーベスト", 1)]


class TestPublisherNoteNames:
    def test_ファイル名とaliasesを分けずに名前にする(self):
        names = publisher_store.note_names({"aliases": ["株式会社学研プラス"]}, "ディスカヴァー・トゥエンティワン")

        assert names == ("ディスカヴァー・トゥエンティワン", "株式会社学研プラス")

    def test_漢字どうしの中黒や読点も分けずに1つの名前にする(self):
        # 著者ノートは `東京大学・出版会` を2人に分けるが、出版社は文字列ごとに1つの名前
        assert publisher_store.note_names({}, "東京大学・出版会") == ("東京大学・出版会",)
        assert publisher_store.note_names({"aliases": ["甲社、乙社"]}, "丙社") == ("丙社", "甲社、乙社")

    def test_キーが同じ名前は1つにする(self):
        assert publisher_store.note_names({"aliases": ["ＨＳ"]}, "HS") == ("HS",)


class TestRebuild:
    def test_レポートのある出版社のノートとハブを作る(self, db, shelf, publishers):
        shelf.add_with_report("野草図鑑", id=12, publisher="ハーベスト")
        shelf.add("旧約聖書", publisher="学研プラス")

        written = rebuild(db)

        assert note_names_in(publishers) == ["ハーベスト.md"]
        text = read(publishers / "ハーベスト.md")
        assert text.startswith("---\ntype: publisher-note\n---\n\n# ハーベスト\n\n" + START)
        assert "## この出版社の本" in text
        assert "- [野草図鑑](../0012-野草図鑑.md)" in text
        assert text.rstrip().endswith(END)
        hub = read(publishers / HUB_NAME)
        assert hub.startswith("---\ntype: publisher-hub\n---\n")
        notes_part, no_note_part = hub.split("## ノートの無い出版社")
        assert "- [ハーベスト](ハーベスト.md) — 1冊（レポート 1）" in notes_part
        assert [l for l in no_note_part.splitlines() if l.startswith("- ")] == [
            "- 学研プラス — 1冊（レポート 0）"]
        assert publishers / "ハーベスト.md" in written and publishers / HUB_NAME in written

    def test_漢字どうしの中黒を含む出版社名のノートをその名前で作る(self, db, shelf, publishers):
        # 著者の分け方で名前を読むと、作ったノートが自分の名前を集められず毎回作り直しになる
        shelf.add_with_report("本", id=3, publisher="東京大学・出版会")

        rebuild(db)

        assert note_names_in(publishers) == ["東京大学・出版会.md"]
        assert "- [本](../0003-本.md)" in read(publishers / "東京大学・出版会.md")
        assert rebuild(db) == []

    def test_ユーザーが作った出版社ノートはレポートが無くても埋める(self, db, shelf, publishers):
        shelf.add("旧約聖書", publisher="学研プラス")
        note = write_note(publishers, "学研プラス.md", "自分のメモ\n")

        rebuild(db)

        text = read(note)
        assert text.startswith("自分のメモ\n")
        assert "- 旧約聖書" in text

    def test_aliasesで表記揺れをまとめたノートは両方の本を集め他方のノートを作らない(
            self, db, shelf, publishers):
        shelf.add_with_report("本1", publisher="学研プラス")
        shelf.add_with_report("本2", publisher="株式会社学研プラス")
        note = write_note(publishers, "学研プラス.md", "---\naliases: [株式会社学研プラス]\n---\n")

        rebuild(db)

        assert note_names_in(publishers) == ["学研プラス.md"]
        text = read(note)
        assert "本1" in text and "本2" in text
        assert "すべての出版社にノートがあります。" in read(publishers / HUB_NAME)

    def test_同じ本を含むテーマノートが関連するテーマに出る(self, db, shelf, publishers, themes):
        shelf.add_with_report("野草図鑑", publisher="ハーベスト", tags=["植物"])
        write_note(themes, "植物.md", "---\ntags: [植物]\n---\n")

        rebuild(db)

        assert "- [植物](../themes/植物.md) — 共通の本 1冊" in read(publishers / "ハーベスト.md")

    def test_2回目は何も書かない(self, db, shelf, publishers):
        shelf.add_with_report("野草図鑑", publisher="ハーベスト")
        shelf.add("旧約聖書", publisher="学研プラス")

        assert rebuild(db)
        assert rebuild(db) == []

    def test_編集中の出版社ノートがあれば作らず一覧とハブは書く(self, db, shelf, publishers):
        shelf.add_with_report("野草図鑑", publisher="ハーベスト")
        shelf.add("旧約聖書", publisher="学研プラス")
        write_note(publishers, "学研プラス.md", "---\naliases: [株式会社学研プラス, \n---\n")

        written = rebuild(db)

        assert note_names_in(publishers) == ["学研プラス.md"]   # ハーベスト.md は作らない
        assert "- 旧約聖書" in read(publishers / "学研プラス.md")
        assert publishers / HUB_NAME in written
        assert "- ハーベスト — 1冊（レポート 1）" in read(publishers / HUB_NAME)

    def test_著者ノートのフォルダとは別に作り同じ名前でもぶつからない(self, db, shelf, publishers):
        shelf.add_with_report("旧約聖書", author="学研プラス", publisher="学研プラス")

        rebuild(db)
        author_store.rebuild(db, quiet_seconds=0)

        assert note_names_in(publishers) == ["学研プラス.md"]
        assert not (publishers.parent / "authors" / "学研プラス.md").exists()

    @pytest.mark.parametrize("value, expected", [("0", False), ("false", False), (" OFF ", False),
                                                 ("1", True), ("", True)])
    def test_出版社ノートの止め方の環境変数を読む(self, monkeypatch, value, expected):
        monkeypatch.setenv("NOTES_PUBLISHERS_WATCH", value)

        assert main.env_enabled("NOTES_PUBLISHERS_WATCH") is expected

    def test_出版社ノートの環境変数が未設定なら動く(self, monkeypatch):
        monkeypatch.delenv("NOTES_PUBLISHERS_WATCH", raising=False)

        assert main.env_enabled("NOTES_PUBLISHERS_WATCH") is True
