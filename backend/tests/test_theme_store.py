"""テーマノートの一覧づくり（app/theme_store.py）のテスト

DB はメモリ上の SQLite、ノートとレポートは実ファイル（I/O がこの機能の本体なのでモックしない）。
書き直しの「直近に更新されたノートは飛ばす」を避けたいテストでは quiet_seconds=0 で呼ぶ。
"""

import os
import threading
from datetime import date

import pytest
from sqlalchemy.orm import Session

from app import report_store, theme_store
from app.models import Book, BookStatus, Tag
from app.theme_store import END, HUB_NAME, START


@pytest.fixture
def db(db_engine):
    with Session(db_engine) as session:
        yield session


@pytest.fixture
def themes(tmp_path):
    # conftest が NOTES_REPORTS_DIR を tmp_path/reports に向けている
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


@pytest.fixture
def shelf(db):
    return Shelf(db)


def write_note(directory, name, text):
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def rebuild(db):
    return theme_store.rebuild(db, quiet_seconds=0)


class TestThemeNote:
    def test_appends_the_book_list_and_keeps_what_the_user_wrote(self, db, shelf, themes):
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", "# 地政学\n\n自分のまとめ。\n")

        rebuild(db)

        text = note.read_text(encoding="utf-8")
        assert text.startswith("# 地政学\n\n自分のまとめ。\n\n" + START)
        assert text.rstrip().endswith(END)
        assert "- 地政学入門 — 積読" in text

    def test_rewrites_only_between_the_markers(self, db, shelf, themes):
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", f"上の文章\n\n{START}\n古い一覧\n{END}\n\n下の文章\n")

        rebuild(db)

        text = note.read_text(encoding="utf-8")
        assert text.startswith(f"上の文章\n\n{START}\n")
        assert text.endswith(f"{END}\n\n下の文章\n")
        assert "古い一覧" not in text
        assert "地政学入門" in text

    def test_links_books_that_have_a_report_with_a_relative_path(self, db, shelf, themes):
        book = shelf.add("失敗の本質", tags=["歴史"], status=BookStatus.FINISHED,
                         finished_on=date(2026, 9, 20), rating=5, author="戸部良一")
        shelf.add("まだの本", tags=["歴史"])
        report_store.save(book, "## 感想")
        note = write_note(themes, "歴史.md", "")

        rebuild(db)

        text = note.read_text(encoding="utf-8")
        assert (f"- [失敗の本質](../{book.id:04d}-失敗の本質.md) — 戸部良一 · 読了 2026-09-20 · ★★★★★"
                in text)
        assert "2冊（レポートあり 1冊）" in text
        report_section, rest = text.split("### まだレポートの無い本")
        assert "失敗の本質" in report_section
        assert "- まだの本 — 積読" in rest

    def test_the_link_resolves_to_the_report_file(self, db, shelf, themes):
        # 文字列の形ではなく、リンク先を実際にたどってレポートに着くことを確かめる
        book = shelf.add("[増補版]神道はなぜ教えがないのか", tags=["宗教"])
        report = report_store.save(book, "本文")
        note = write_note(themes, "宗教.md", "")

        rebuild(db)

        line = next(l for l in note.read_text(encoding="utf-8").splitlines() if "神道" in l)
        target = line.split("](", 1)[1].split(")", 1)[0]
        assert (themes / target).resolve() == report.resolve()
        assert line.startswith(r"- [\[増補版\]神道はなぜ教えがないのか](")

    def test_encodes_characters_that_would_break_the_link(self, themes):
        path = themes.parent / "0005-a (b) #1.md"
        assert theme_store.link_target(path, themes) == "../0005-a%20%28b%29%20%231.md"

    def test_escapes_a_hash_so_a_title_does_not_become_an_obsidian_tag(self, db, shelf, themes):
        shelf.add("C#入門", tags=["IT"])
        note = write_note(themes, "IT.md", "")

        rebuild(db)

        assert r"- C\#入門 — 積読" in note.read_text(encoding="utf-8")

    def test_uses_the_file_name_as_the_tag_when_there_are_no_tags(self, db, shelf, themes):
        shelf.add("地政学入門", tags=["地政学"])
        shelf.add("数学の本", tags=["数学"])
        note = write_note(themes, "地政学.md", "")

        rebuild(db)

        text = note.read_text(encoding="utf-8")
        assert "地政学入門" in text
        assert "数学の本" not in text

    def test_collects_books_having_any_of_the_front_matter_tags(self, db, shelf, themes):
        shelf.add("地政学入門", tags=["地政学"])
        shelf.add("日本史", tags=["歴史"])
        shelf.add("数学の本", tags=["数学"])
        note = write_note(themes, "近代と戦争.md", "---\ntags: [歴史, 地政学]\n---\n本文\n")

        rebuild(db)

        text = note.read_text(encoding="utf-8")
        assert "- 地政学入門 — 積読 · 地政学" in text
        assert "- 日本史 — 積読 · 歴史" in text
        assert "数学の本" not in text
        assert text.startswith("---\ntags: [歴史, 地政学]\n---\n本文\n")

    @pytest.mark.parametrize("raw, expected", [
        ("地政学", ("地政学",)),
        ("#地政学, 歴史", ("地政学", "歴史")),
        (["#地政学", "歴史", "歴史"], ("地政学", "歴史")),
        (None, ("ファイル名",)),
        ([], ("ファイル名",)),
    ])
    def test_reads_tags_in_every_form_obsidian_writes(self, raw, expected):
        assert theme_store.theme_tags({"tags": raw}, "ファイル名") == expected

    def test_says_so_when_no_book_has_the_tag(self, db, shelf, themes):
        note = write_note(themes, "未知.md", "")
        rebuild(db)
        assert "このタグの本はまだありません（集めるタグ: 未知）" in note.read_text(encoding="utf-8")

    def test_links_related_themes_that_share_books(self, db, shelf, themes):
        shelf.add("地政学と歴史", tags=["地政学", "歴史"])
        shelf.add("日本史", tags=["歴史"])
        geo = write_note(themes, "地政学.md", "")
        write_note(themes, "歴史.md", "")
        write_note(themes, "数学.md", "")

        rebuild(db)

        text = geo.read_text(encoding="utf-8")
        assert "### 関連するテーマ" in text
        assert "- [歴史](歴史.md) — 共通の本 1冊" in text
        assert "数学.md" not in text

    def test_does_not_touch_a_note_whose_markers_are_broken(self, db, shelf, themes):
        shelf.add("地政学入門", tags=["地政学"])
        original = f"{START}\n書きかけ\n"
        note = write_note(themes, "地政学.md", original)

        rebuild(db)

        assert note.read_text(encoding="utf-8") == original

    def test_follows_a_tag_added_later(self, db, shelf, themes):
        note = write_note(themes, "地政学.md", "")
        rebuild(db)
        assert "まだありません" in note.read_text(encoding="utf-8")

        shelf.add("地政学入門", tags=["地政学"])
        rebuild(db)

        assert "地政学入門" in note.read_text(encoding="utf-8")


class TestWhenToWrite:
    def test_does_not_rewrite_when_nothing_changed(self, db, shelf, themes):
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", "")
        rebuild(db)
        os.utime(note, (1_000_000, 1_000_000))

        written = rebuild(db)

        assert note not in written
        assert note.stat().st_mtime == 1_000_000

    def test_skips_a_note_that_was_just_edited(self, db, shelf, themes):
        # Obsidian で書いている最中かもしれないので、その回は書かない
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", "書いている途中")

        theme_store.rebuild(db, quiet_seconds=60)
        assert note.read_text(encoding="utf-8") == "書いている途中"

        theme_store.rebuild(db, quiet_seconds=60, now=note.stat().st_mtime + 61)
        assert "地政学入門" in note.read_text(encoding="utf-8")

    def test_ignores_hidden_files(self, db, shelf, themes):
        hidden = write_note(themes, ".下書き.md", "")
        rebuild(db)
        assert hidden.read_text(encoding="utf-8") == ""

    def test_waits_for_the_report_lock_before_writing(self, db, shelf, themes):
        # レポートの保存と同じロックを使う（同時に書いて片方を潰さない）
        import fcntl

        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", "")
        lock_path = themes.parent / report_store.LOCK_NAME
        with open(lock_path, "w") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            thread = threading.Thread(target=rebuild, args=(db,))
            thread.start()
            thread.join(timeout=0.5)
            assert thread.is_alive()
            assert note.read_text(encoding="utf-8") == ""
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        thread.join(timeout=5)
        assert "地政学入門" in note.read_text(encoding="utf-8")


class TestHub:
    def test_creates_the_hub_with_every_note_and_the_tags_without_one(self, db, shelf, themes):
        book = shelf.add("地政学入門", tags=["地政学", "歴史"])
        shelf.add("日本史", tags=["歴史"])
        shelf.add("数学の本", tags=["数学"])
        report_store.save(book, "本文")
        write_note(themes, "地政学.md", "")

        rebuild(db)

        text = (themes / HUB_NAME).read_text(encoding="utf-8")
        assert text.startswith("---\ntype: theme-hub\n---\n")
        notes_part, no_note_part = text.split("## ノートのまだ無いタグ")
        assert "- [地政学](地政学.md) — 地政学 · 1冊（レポート 1）" in notes_part
        assert no_note_part.index("- 歴史 — 2冊（レポート 1）") < no_note_part.index("- 数学 — 1冊（レポート 0）")
        assert "地政学 —" not in no_note_part

    def test_keeps_what_the_user_wrote_in_the_hub(self, db, shelf, themes):
        shelf.add("地政学入門", tags=["地政学"])
        rebuild(db)
        hub = themes / HUB_NAME
        hub.write_text(hub.read_text(encoding="utf-8").replace(
            "# テーマ一覧\n", "# テーマ一覧\n\n全体のまとめ。\n"), encoding="utf-8")

        write_note(themes, "地政学.md", "")
        rebuild(db)

        text = hub.read_text(encoding="utf-8")
        assert "全体のまとめ。" in text
        assert "- [地政学](地政学.md)" in text

    def test_the_hub_is_not_treated_as_a_theme_note(self, db, shelf, themes):
        rebuild(db)
        assert theme_store.scan_notes(themes) == []

    def test_creates_the_themes_folder_when_it_is_missing(self, db, tmp_path):
        rebuild(db)
        assert (tmp_path / "reports" / "themes" / HUB_NAME).is_file()


class TestReportsAreNotConfusedWithThemes:
    def test_theme_notes_and_the_hub_are_not_indexed_as_reports(self, db, shelf, themes):
        book = shelf.add("地政学入門", tags=["地政学"])
        write_note(themes, "地政学.md", f"---\nbook_id: {book.id}\n---\n本文\n")
        rebuild(db)

        assert report_store.has_report(book.id) is False
        assert report_store.book_ids_with_report() == set()
