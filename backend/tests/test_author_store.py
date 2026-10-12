"""著者ノートの一覧づくり（app/author_store.py）のテスト

DB はメモリ上の SQLite、ノートとレポートは実ファイル（I/O がこの機能の本体なのでモックしない）。
書き直しの「直近に更新されたノートは飛ばす」を避けたいテストでは quiet_seconds=0 で呼ぶ。
名前の扱い（分割・照合キー・ファイル名）は DB もファイルも使わない。
"""

import logging
import os
import threading
import unicodedata
from datetime import date

import pytest
from sqlalchemy.orm import Session

from app import author_store, report_store, theme_store
from app.models import Book, BookStatus, Tag
from app.theme_store import END, START

HUB_NAME = author_store.HUB_NAME


@pytest.fixture(autouse=True)
def _forget_warned_notes():
    # 壊れたマーカーの警告済みパスはモジュール変数。テストをまたいで残さない
    theme_store._warned_broken.clear()
    yield
    theme_store._warned_broken.clear()


@pytest.fixture
def db(db_engine):
    with Session(db_engine) as session:
        yield session


@pytest.fixture
def authors(tmp_path):
    # conftest が NOTES_REPORTS_DIR を tmp_path/reports に向けている
    directory = tmp_path / "reports" / "authors"
    directory.mkdir(parents=True)
    return directory


@pytest.fixture
def themes(tmp_path):
    directory = tmp_path / "reports" / "themes"
    directory.mkdir(parents=True)
    return directory


class Shelf:
    """本とタグを DB に入れる小道具。タグは名前で使い回す。"""

    def __init__(self, db: Session):
        self.db = db
        self.tags: dict[str, Tag] = {}

    def add(self, title, tags=(), status=BookStatus.UNREAD, **kwargs) -> Book:
        book = Book(title=title, status=status, **kwargs)
        book.tags = [self.tags.setdefault(name, Tag(name=name)) for name in tags]
        self.db.add(book)
        self.db.commit()
        return book

    def add_with_report(self, title, **kwargs) -> Book:
        book = self.add(title, **kwargs)
        report_store.save(book, "本文")
        return book


@pytest.fixture
def shelf(db):
    return Shelf(db)


def write_note(directory, name, text):
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def read(path):
    return path.read_text(encoding="utf-8")


def rebuild(db):
    return author_store.rebuild(db, quiet_seconds=0)


def note_names_in(directory):
    """ハブ以外のノートのファイル名。"""
    return sorted(p.name for p in directory.iterdir() if p.is_file() and p.name != HUB_NAME)


def line_of(text, needle):
    return next(line for line in text.splitlines() if needle in line)


class TestSplitAuthors:
    def test_splits_on_ascii_fullwidth_and_ideographic_commas(self):
        # 半角 , のほか、全角 ，（U+FF0C）・読点 、（U+3001）・半角読点 ､（U+FF64）で分かれる
        assert author_store.split_authors("A，B、C､D, E") == ["A", "B", "C", "D", "E"]

    @pytest.mark.parametrize("raw, expected", [
        ("ダニエル・Ｌ・エヴェレット", "ダニエル・L・エヴェレット"),
        ("渡辺　照宏 ", "渡辺 照宏"),
        ("渡辺   照宏", "渡辺 照宏"),
    ])
    def test_normalizes_width_and_collapses_spaces_for_the_display_name(self, raw, expected):
        assert author_store.split_authors(raw) == [expected]

    @pytest.mark.parametrize("raw, expected", [
        ("J．カバットジン／著", "J.カバットジン"),
        ("春木豊／訳", "春木豊"),
        ("山田太郎 編", "山田太郎"),
        ("山田太郎（編著）", "山田太郎"),
        ("山田太郎 [著]", "山田太郎"),
        ("山田太郎／監修", "山田太郎"),
    ])
    def test_strips_a_trailing_role_marker(self, raw, expected):
        assert author_store.split_authors(raw) == [expected]

    def test_keeps_a_one_letter_given_name_after_a_space(self):
        # 「文」は役割にもなるが、空白区切りでは姓と1文字の名を取り違えないよう落とさない
        assert author_store.split_authors("山田 文") == ["山田 文"]

    @pytest.mark.parametrize("raw", [None, "", " , 、 ", "／著"])
    def test_returns_nothing_for_none_empty_separators_or_a_bare_role(self, raw):
        assert author_store.split_authors(raw) == []

    def test_lists_a_name_repeated_in_one_book_once(self):
        assert author_store.split_authors("渡辺照宏, 渡辺 照宏") == ["渡辺照宏"]

    def test_keeps_a_name_made_only_of_symbols(self):
        # ファイル名にはできない（note_stem が空）が、著者としては残してハブに出す
        assert author_store.split_authors("???") == ["???"]


class TestAuthorKey:
    @pytest.mark.parametrize("a, b", [
        ("渡辺 照宏", "渡辺照宏"),
        ("H.G. Wells", "ＨＧ Ｗｅｌｌｓ"),
        ("H.G. Wells", "h.g. WELLS"),
        ("ダニエル・L・エヴェレット", "ダニエル・L.エヴェレット"),
        ("クロード・レヴィ＝ストロース", "クロード・レヴィ=ストロース"),
        (unicodedata.normalize("NFD", "ガルシア・マルケス"), "ガルシア・マルケス"),
    ])
    def test_ignores_spaces_width_case_and_name_dots(self, a, b):
        assert author_store.author_key(a) == author_store.author_key(b) != ""

    def test_keeps_different_scripts_apart(self):
        # 別の文字種の表記は別の著者。ユーザーが aliases でまとめる
        assert author_store.author_key("H.G. Wells") != author_store.author_key("H・G・ウェルズ")


class TestNoteStem:
    @pytest.mark.parametrize("name, expected", [
        ("A/B: C?", "AB C"),
        (".隠れ", "隠れ"),
        ("山田*太郎", "山田太郎"),
        ("???", ""),
    ])
    def test_drops_characters_that_cannot_be_in_a_file_name(self, name, expected):
        assert author_store.note_stem(name) == expected

    def test_caps_the_name_at_200_bytes_without_splitting_a_character(self):
        stem = author_store.note_stem("a" + "あ" * 100)

        # 200 バイト目は「あ」(3バイト)の途中。途中の文字は捨てて 199 バイトになる
        assert stem == "a" + "あ" * 66
        assert len(stem.encode("utf-8")) == 199


class TestNoteNames:
    @pytest.mark.parametrize("aliases, expected", [
        (None, ("渡辺照宏",)),
        ("別名", ("渡辺照宏", "別名")),
        (["別名", None, 3], ("渡辺照宏", "別名", "3")),
        ({"x": 1}, ("渡辺照宏",)),
        ("甲、乙", ("渡辺照宏", "甲", "乙")),
    ])
    def test_reads_aliases_as_a_string_or_a_list(self, aliases, expected):
        assert author_store.note_names({"aliases": aliases}, "渡辺照宏") == expected

    def test_the_file_name_comes_first_and_duplicates_are_dropped(self):
        meta = {"aliases": ["渡辺 照宏", "別名", "べつ めい"]}

        assert author_store.note_names(meta, "渡辺照宏") == ("渡辺照宏", "別名", "べつ めい")


class TestCollectAuthors:
    def test_uses_the_spelling_of_the_book_with_the_smallest_id(self, db, shelf):
        first = shelf.add("仏教 第二版", author="渡辺 照宏")
        second = shelf.add("お経の話", author="渡辺照宏")

        # 渡す順が id 順でなくても、表示名は id が小さい本の表記
        collected = author_store.collect_authors([second, first])

        author = collected[author_store.author_key("渡辺照宏")]
        assert author.name == "渡辺 照宏"
        assert [b.id for b in author.books] == [first.id, second.id]

    def test_collects_a_translator_like_an_author(self, db, shelf):
        book = shelf.add("言語の起源", author="ダニエル・Ｌ・エヴェレット, 松浦俊輔")

        collected = author_store.collect_authors([book])

        assert [a.name for a in collected.values()] == ["ダニエル・L・エヴェレット", "松浦俊輔"]
        assert all(a.books == (book,) for a in collected.values())

    def test_skips_a_book_without_an_author(self, db, shelf):
        books = [shelf.add("著者なし"), shelf.add("区切りだけ", author=" , 、 ")]

        assert author_store.collect_authors(books) == {}


class TestCreate:
    def test_creates_a_note_for_each_author_of_a_book_with_a_report(self, db, shelf, authors):
        shelf.add_with_report("言語の起源", id=13, author="ダニエル・Ｌ・エヴェレット, 松浦俊輔")

        rebuild(db)

        assert note_names_in(authors) == ["ダニエル・L・エヴェレット.md", "松浦俊輔.md"]
        text = read(authors / "ダニエル・L・エヴェレット.md")
        assert text.startswith(
            "---\ntype: author-note\n---\n\n# ダニエル・L・エヴェレット\n\n" + START)
        assert text.rstrip().endswith(END)
        assert "- [言語の起源](../0013-言語の起源.md)" in text

    def test_does_not_create_a_note_for_an_author_without_a_report(self, db, shelf, authors):
        shelf.add("マインドフルネスストレス低減法", author="J．カバットジン／著, 春木豊／訳")

        rebuild(db)

        assert note_names_in(authors) == []
        hub = read(authors / HUB_NAME)
        assert "- 春木豊 — 1冊（レポート 0）" in hub
        assert "- J.カバットジン — 1冊（レポート 0）" in hub

    def test_creates_a_note_when_only_one_of_the_authors_books_has_a_report(self, db, shelf, authors):
        shelf.add("仏教 第二版", author="渡辺 照宏", status=BookStatus.READING)
        shelf.add_with_report("お経の話", author="渡辺照宏")

        rebuild(db)

        assert note_names_in(authors) == ["渡辺 照宏.md"]

    def test_does_not_create_a_second_note_for_a_spelling_variant(self, db, shelf, authors):
        shelf.add_with_report("仏教 第二版", author="渡辺 照宏")
        shelf.add_with_report("お経の話", author="渡辺照宏")

        rebuild(db)

        assert note_names_in(authors) == ["渡辺 照宏.md"]
        text = read(authors / "渡辺 照宏.md")
        assert "仏教 第二版" in text and "お経の話" in text

    def test_does_not_create_a_note_when_an_alias_of_another_note_covers_the_author(
            self, db, shelf, authors):
        shelf.add_with_report("透明人間", author="H・G・ウェルズ")
        write_note(authors, "Wells.md", "---\naliases: [H・G・ウェルズ]\n---\n")

        rebuild(db)

        assert note_names_in(authors) == ["Wells.md"]
        assert "透明人間" in read(authors / "Wells.md")

    def test_recreates_a_deleted_note_while_the_author_has_a_report(self, db, shelf, authors):
        # 既知の挙動: 消しても、レポートがある著者のノートは次の回に作り直される
        shelf.add_with_report("お経の話", author="渡辺照宏")
        rebuild(db)
        (authors / "渡辺照宏.md").unlink()

        rebuild(db)

        assert note_names_in(authors) == ["渡辺照宏.md"]

    def test_adds_the_original_name_to_aliases_when_the_file_name_had_to_change(
            self, db, shelf, authors):
        shelf.add_with_report("お経の話", author="山田*太郎")

        rebuild(db)

        assert note_names_in(authors) == ["山田太郎.md"]
        text = read(authors / "山田太郎.md")
        meta, _ = report_store.split_front_matter(text)
        assert meta == {"type": "author-note", "aliases": ["山田*太郎"]}
        assert r"# 山田\*太郎" in text
        # 次の回も同じ著者を集めるので、ノートは増えず、一覧にその本が載っている
        written = rebuild(db)
        assert note_names_in(authors) == ["山田太郎.md"]
        assert written == []
        assert "- [お経の話](" in read(authors / "山田太郎.md")

    def test_does_not_overwrite_an_existing_file_with_the_same_name(self, db, shelf, authors):
        # ユーザーの山田太郎.md（キー「山田太郎」）と、別のキーの著者「山田*太郎」。
        # 後者のファイル名も山田太郎.md になるが、上書きしない
        shelf.add_with_report("お経の話", author="山田*太郎")
        mine = write_note(authors, "山田太郎.md", "ユーザーの文章\n")

        rebuild(db)

        assert note_names_in(authors) == ["山田太郎.md"]
        text = read(mine)
        assert text.startswith("ユーザーの文章\n\n" + START)
        assert "この名前の本はまだありません" in text
        assert r"- 山田\*太郎 — 1冊（レポート 1）" in read(authors / HUB_NAME)

    def test_does_not_overwrite_a_file_that_appeared_after_the_scan(
            self, db, shelf, authors, monkeypatch):
        # 走査のあと、ロックを取るまでの間にできたファイルを再現する
        # （走査は何も見ておらず、書くときにはもう在る）
        shelf.add_with_report("お経の話", author="渡辺照宏")
        mine = write_note(authors, "渡辺照宏.md", "ユーザーの文章\n")
        monkeypatch.setattr(author_store, "scan_notes", lambda directory: [])

        written = rebuild(db)

        assert read(mine) == "ユーザーの文章\n"
        assert mine not in written

    def test_skips_an_author_whose_name_has_no_usable_characters(self, db, shelf, authors):
        shelf.add_with_report("謎の本", author="???")

        rebuild(db)

        assert note_names_in(authors) == []
        assert "- ??? — 1冊（レポート 1）" in read(authors / HUB_NAME)

    def test_does_not_create_a_note_named_like_the_hub(self, db, shelf, authors):
        shelf.add_with_report("謎の本", author="著者一覧")

        rebuild(db)

        assert note_names_in(authors) == []
        hub = read(authors / HUB_NAME)
        assert hub.startswith("---\ntype: author-hub\n---\n")
        assert "- 著者一覧 — 1冊（レポート 1）" in hub

    def test_a_created_note_is_not_rewritten_on_the_next_run(self, db, shelf, authors):
        shelf.add_with_report("お経の話", author="渡辺照宏")
        rebuild(db)
        note = authors / "渡辺照宏.md"
        os.utime(note, (1_000_000, 1_000_000))

        written = rebuild(db)

        assert note not in written
        assert note.stat().st_mtime == 1_000_000


class TestAuthorNote:
    def test_fills_a_note_the_user_created_even_without_a_report(self, db, shelf, authors):
        shelf.add("マインドフルネスストレス低減法", author="J．カバットジン／著, 春木豊／訳")
        note = write_note(authors, "春木豊.md", "# 春木豊\n\nメモ。\n")

        rebuild(db)

        text = read(note)
        assert text.startswith("# 春木豊\n\nメモ。\n\n" + START)
        assert "### まだレポートの無い本" in text
        assert "- マインドフルネスストレス低減法 — J．カバットジン／著, 春木豊／訳 · 積読" in text

    def test_rewrites_only_between_the_markers_and_keeps_the_user_text(self, db, shelf, authors):
        shelf.add("お経の話", author="渡辺照宏")
        note = write_note(authors, "渡辺照宏.md", f"上の文章\n\n{START}\n古い一覧\n{END}\n\n下の文章\n")

        rebuild(db)

        text = read(note)
        assert text.startswith(f"上の文章\n\n{START}\n")
        assert text.endswith(f"{END}\n\n下の文章\n")
        assert "古い一覧" not in text
        assert "お経の話" in text

    def test_lists_books_like_a_theme_note(self, db, shelf, authors):
        shelf.add_with_report("お経の話", id=21, author="渡辺照宏", status=BookStatus.FINISHED,
                              finished_on=date(2026, 8, 2), rating=5)
        shelf.add("仏教 第二版", id=34, author="渡辺 照宏", status=BookStatus.READING)

        rebuild(db)

        text = read(authors / "渡辺照宏.md")
        assert "集める名前: 渡辺照宏 -->" in text
        assert "2冊（レポートあり 1冊）" in text
        report_section, rest = text.split("### まだレポートの無い本")
        assert "- [お経の話](../0021-お経の話.md) — 渡辺照宏 · 読了 2026-08-02 · ★★★★★" in report_section
        assert "- 仏教 第二版 — 渡辺 照宏 · 読書中" in rest

    def test_the_link_resolves_to_the_report_file(self, db, shelf, authors):
        # 文字列の形ではなく、リンク先を実際にたどってレポートに着くことを確かめる
        book = shelf.add("[増補版]神道はなぜ教えがないのか", author="山折哲雄")
        report = report_store.save(book, "本文")

        rebuild(db)

        line = line_of(read(authors / "山折哲雄.md"), "神道")
        target = line.split("](", 1)[1].split(")", 1)[0]
        assert (authors / target).resolve() == report.resolve()

    def test_collects_books_of_every_alias(self, db, shelf, authors):
        shelf.add("タイムマシン", author="H.G. Wells")
        shelf.add("透明人間", author="H・G・ウェルズ")
        shelf.add("関係ない本", author="別の人")
        note = write_note(authors, "H.G. Wells.md", "---\naliases: [H・G・ウェルズ]\n---\n")

        rebuild(db)

        text = read(note)
        assert "集める名前: H.G. Wells、H・G・ウェルズ -->" in text
        assert "- タイムマシン — H.G. Wells · 積読" in text
        assert "- 透明人間 — H・G・ウェルズ · 積読" in text
        assert "関係ない本" not in text
        assert text.startswith("---\naliases: [H・G・ウェルズ]\n---\n")

    def test_a_book_matched_by_two_names_of_one_note_is_listed_once(self, db, shelf, authors):
        shelf.add("共訳の本", author="渡辺照宏, 松浦俊輔")
        note = write_note(authors, "渡辺照宏.md", "---\naliases: [松浦俊輔]\n---\n")

        rebuild(db)

        text = read(note)
        assert text.count("- 共訳の本") == 1
        assert "1冊（レポートあり 0冊）" in text

    def test_two_notes_sharing_a_name_both_list_the_book(self, db, shelf, authors):
        shelf.add("共著の本", author="共通の人")
        first = write_note(authors, "甲.md", "---\naliases: [共通の人]\n---\n")
        second = write_note(authors, "乙.md", "---\naliases: [共通の人]\n---\n")

        rebuild(db)

        assert "- 共著の本" in read(first)
        assert "- 共著の本" in read(second)

    def test_links_related_themes_that_share_books(self, db, shelf, authors, themes):
        shelf.add("お経の話", author="渡辺照宏", tags=["仏教", "歴史"])
        shelf.add("仏教 第二版", author="渡辺 照宏", tags=["仏教"])
        shelf.add("数学の本", author="別の人", tags=["数学"])
        write_note(themes, "仏教.md", "")
        write_note(themes, "歴史.md", "")
        write_note(themes, "数学.md", "")
        note = write_note(authors, "渡辺照宏.md", "")

        rebuild(db)

        text = read(note)
        assert "### 関連するテーマ" in text
        related = text.split("### 関連するテーマ")[1]
        assert related.index("- [仏教](../themes/仏教.md) — 共通の本 2冊") < related.index(
            "- [歴史](../themes/歴史.md) — 共通の本 1冊")
        assert "数学.md" not in text

    def test_says_so_when_no_book_matches(self, db, shelf, authors):
        note = write_note(authors, "未知の人.md", "")

        rebuild(db)

        assert "この名前の本はまだありません（集める名前: 未知の人）" in read(note)

    def test_follows_an_author_change_in_the_db(self, db, shelf, authors):
        book = shelf.add_with_report("お経の話", author="渡辺照宏")
        rebuild(db)
        assert "お経の話" in read(authors / "渡辺照宏.md")

        book.author = "渡辺照宏の弟子"
        db.commit()
        rebuild(db)

        # 古いノートは残り、本は新しい名前のノートへ移る（アプリは消さない）
        assert "この名前の本はまだありません" in read(authors / "渡辺照宏.md")
        assert note_names_in(authors) == ["渡辺照宏.md", "渡辺照宏の弟子.md"]
        assert "お経の話" in read(authors / "渡辺照宏の弟子.md")

    def test_a_renamed_note_collects_by_its_new_name(self, db, shelf, authors):
        shelf.add("お経の話", author="渡辺照宏")
        old = write_note(authors, "誰か.md", "")
        rebuild(db)
        assert "この名前の本はまだありません" in read(old)

        renamed = old.rename(authors / "渡辺照宏.md")
        rebuild(db)

        assert "お経の話" in read(renamed)

    def test_recreates_the_old_name_when_a_renamed_note_does_not_keep_it_as_an_alias(
            self, db, shelf, authors):
        shelf.add_with_report("お経の話", author="渡辺照宏")
        rebuild(db)

        (authors / "渡辺照宏.md").rename(authors / "照宏.md")
        rebuild(db)

        assert note_names_in(authors) == ["渡辺照宏.md", "照宏.md"]
        assert "この名前の本はまだありません" in read(authors / "照宏.md")
        assert "お経の話" in read(authors / "渡辺照宏.md")

    def test_does_not_recreate_a_renamed_note_that_keeps_the_old_name_as_an_alias(
            self, db, shelf, authors):
        shelf.add_with_report("お経の話", author="渡辺照宏")
        rebuild(db)
        old = authors / "渡辺照宏.md"
        renamed = old.rename(authors / "照宏.md")
        renamed.write_text(
            read(renamed).replace("type: author-note", "type: author-note\naliases: [渡辺照宏]"),
            encoding="utf-8")

        rebuild(db)

        assert note_names_in(authors) == ["照宏.md"]
        assert "お経の話" in read(renamed)

    def test_does_not_touch_a_note_whose_markers_are_broken(self, db, shelf, authors, caplog):
        shelf.add("お経の話", author="渡辺照宏")
        original = f"{START}\n書きかけ\n"
        note = write_note(authors, "渡辺照宏.md", original)

        with caplog.at_level(logging.WARNING, logger="app.theme_store"):
            rebuild(db)
            rebuild(db)

        assert read(note) == original
        warnings = [r for r in caplog.records if str(note) in r.getMessage()]
        assert len(warnings) == 1

    def test_skips_a_note_that_was_just_edited(self, db, shelf, authors):
        # Obsidian で書いている最中かもしれないので、その回は書かない
        shelf.add("お経の話", author="渡辺照宏")
        note = write_note(authors, "渡辺照宏.md", "書いている途中")

        author_store.rebuild(db, quiet_seconds=60)
        assert read(note) == "書いている途中"

        author_store.rebuild(db, quiet_seconds=60, now=note.stat().st_mtime + 61)
        assert "お経の話" in read(note)

    def test_ignores_hidden_files_and_subfolders(self, db, shelf, authors):
        shelf.add("お経の話", author="渡辺照宏")
        hidden = write_note(authors, ".渡辺照宏.md", "")
        (authors / "旧").mkdir()
        nested = write_note(authors / "旧", "渡辺照宏.md", "")

        rebuild(db)

        assert read(hidden) == "" and read(nested) == ""
        assert author_store.scan_notes(authors) == []


class TestHub:
    def _add_the_example_books(self, shelf):
        shelf.add_with_report("言語の起源", id=13, author="ダニエル・Ｌ・エヴェレット, 松浦俊輔")
        shelf.add_with_report("お経の話", id=21, author="渡辺照宏")
        shelf.add("仏教 第二版", id=34, author="渡辺 照宏", status=BookStatus.READING)
        shelf.add("マインドフルネスストレス低減法", id=40, author="J．カバットジン／著, 春木豊／訳")

    def test_creates_the_hub_with_notes_and_authors_without_a_note(self, db, shelf, authors):
        self._add_the_example_books(shelf)

        rebuild(db)

        text = read(authors / HUB_NAME)
        assert text.startswith("---\ntype: author-hub\n---\n\n# 著者一覧\n")
        assert text.rstrip().endswith(END)
        notes_part, no_note_part = text.split("## ノートの無い著者")
        # 冊数の多い順、同数ならファイル名の順
        assert [l for l in notes_part.splitlines() if l.startswith("- ")] == [
            "- [渡辺照宏](渡辺照宏.md) — 2冊（レポート 1）",
            "- [ダニエル・L・エヴェレット](ダニエル・L・エヴェレット.md) — 1冊（レポート 1）",
            "- [松浦俊輔](松浦俊輔.md) — 1冊（レポート 1）",
        ]
        assert [l for l in no_note_part.splitlines() if l.startswith("- ")] == [
            "- J.カバットジン — 1冊（レポート 0）",
            "- 春木豊 — 1冊（レポート 0）",
        ]

    def test_says_so_when_there_are_no_notes_and_no_authors(self, db, authors):
        rebuild(db)

        text = read(authors / HUB_NAME)
        assert "まだありません。" in text
        assert "すべての著者にノートがあります。" in text

    def test_keeps_what_the_user_wrote_in_the_hub(self, db, shelf, authors):
        shelf.add("お経の話", author="渡辺照宏")
        rebuild(db)
        hub = authors / HUB_NAME
        hub.write_text(read(hub).replace("# 著者一覧\n", "# 著者一覧\n\n全体のまとめ。\n"), encoding="utf-8")

        write_note(authors, "渡辺照宏.md", "")
        rebuild(db)

        text = read(hub)
        assert "全体のまとめ。" in text
        assert "- [渡辺照宏](渡辺照宏.md) — 1冊（レポート 0）" in text

    def test_links_to_a_note_whose_name_has_a_space(self, db, shelf, authors):
        shelf.add("お経の話", author="渡辺 照宏")
        write_note(authors, "渡辺 照宏.md", "")

        rebuild(db)

        assert "- [渡辺 照宏](渡辺%20照宏.md) — 1冊（レポート 0）" in read(authors / HUB_NAME)

    def test_the_hub_is_not_treated_as_an_author_note(self, db, authors):
        rebuild(db)

        assert (authors / HUB_NAME).is_file()
        assert author_store.scan_notes(authors) == []

    def test_creates_the_authors_folder_when_it_is_missing(self, db, tmp_path):
        rebuild(db)

        assert (tmp_path / "reports" / "authors" / HUB_NAME).is_file()


class TestReportsAreNotConfused:
    def test_author_notes_are_not_indexed_as_reports(self, db, shelf, authors):
        book = shelf.add("お経の話", author="渡辺照宏")
        write_note(authors, "渡辺照宏.md", f"---\nbook_id: {book.id}\n---\n本文\n")
        rebuild(db)

        assert report_store.has_report(book.id) is False
        assert report_store.book_ids_with_report() == set()


class TestLock:
    def test_waits_for_the_report_lock_before_writing(self, db, shelf, authors):
        # レポートの保存と同じロックを使う（同時に書いて片方を潰さない）
        import fcntl

        shelf.add("お経の話", author="渡辺照宏")
        note = write_note(authors, "渡辺照宏.md", "")
        lock_path = authors.parent / report_store.LOCK_NAME
        with open(lock_path, "w") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            thread = threading.Thread(target=rebuild, args=(db,))
            thread.start()
            thread.join(timeout=0.5)
            assert thread.is_alive()
            assert read(note) == ""
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        thread.join(timeout=5)
        assert "お経の話" in read(note)
