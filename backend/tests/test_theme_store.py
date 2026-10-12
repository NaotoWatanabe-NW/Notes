"""テーマノートの一覧づくり（app/theme_store.py）のテスト

DB はメモリ上の SQLite、ノートとレポートは実ファイル（I/O がこの機能の本体なのでモックしない）。
書き直しの「直近に更新されたノートは飛ばす」を避けたいテストでは quiet_seconds=0 で呼ぶ。
"""

import logging
import os
import threading
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import report_store, theme_store
from app.models import Book, BookStatus, Tag
from app.theme_store import END, HUB_NAME, START


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


class TestMarkers:
    def test_ignores_a_marker_mentioned_inline_and_appends(self, db, shelf, themes):
        shelf.add("地政学入門", tags=["地政学"])
        original = f"使い方: `{START}` と書くと一覧が入る\n"
        note = write_note(themes, "地政学.md", original)

        rebuild(db)

        text = note.read_text(encoding="utf-8")
        assert text.startswith(original + "\n" + START + "\n")
        assert text.count(f"`{START}`") == 1
        assert "- 地政学入門 — 積読" in text

    def test_ignores_a_marker_pair_inside_a_code_fence_and_appends(self, db, shelf, themes):
        shelf.add("地政学入門", tags=["地政学"])
        fenced = f"```\n{START}\n例\n{END}\n```\n"
        note = write_note(themes, "地政学.md", fenced)

        rebuild(db)

        text = note.read_text(encoding="utf-8")
        assert text.startswith(fenced + "\n" + START + "\n")
        assert "例" in text
        assert "- 地政学入門 — 積読" in text

    def test_replaces_only_the_real_pair_when_a_fenced_pair_also_exists(self, db, shelf, themes):
        shelf.add("地政学入門", tags=["地政学"])
        fenced = f"~~~\n{START}\n例\n{END}\n~~~\n"
        note = write_note(themes, "地政学.md", f"{fenced}\n{START}\n古い一覧\n{END}\n末尾\n")

        rebuild(db)

        text = note.read_text(encoding="utf-8")
        assert text.startswith(fenced + "\n" + START + "\n## このテーマの本")
        assert "古い一覧" not in text
        assert text.endswith(f"{END}\n末尾\n")
        assert "- 地政学入門 — 積読" in text

    def test_does_not_touch_a_note_with_an_unclosed_fence(self, db, shelf, themes):
        shelf.add("地政学入門", tags=["地政学"])
        original = f"```\nコードの途中\n\n{START}\n古い一覧\n{END}\n"
        note = write_note(themes, "地政学.md", original)

        rebuild(db)

        assert note.read_text(encoding="utf-8") == original

    def test_accepts_a_marker_line_with_surrounding_spaces(self, db, shelf, themes):
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", f"上\n  {START}  \n古い一覧\n\t{END}\n下\n")

        rebuild(db)

        text = note.read_text(encoding="utf-8")
        assert text.startswith(f"上\n{START}\n## このテーマの本")
        assert text.endswith(f"{END}\n下\n")
        assert "古い一覧" not in text

    @pytest.mark.parametrize("fenced", [
        "````\n```\nSTART\nEND\n````\n",     # 開きより短い ``` では閉じない
        "~~~\n```\nSTART\nEND\n~~~\n",       # 別の文字（```）では閉じない
    ])
    def test_a_fence_is_closed_only_by_the_same_character_and_at_least_the_same_length(self, fenced):
        text = fenced.replace("START", START).replace("END", END)

        replaced = theme_store.replace_block(text, "新しい一覧")

        assert replaced == text.rstrip() + "\n\n新しい一覧\n"


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

    def test_warns_once_about_a_note_whose_markers_are_broken(self, db, shelf, themes, caplog):
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", f"{START}\n書きかけ\n")

        def warnings():
            return [r for r in caplog.records
                    if r.levelno == logging.WARNING and str(note) in r.getMessage()]

        with caplog.at_level(logging.WARNING, logger="app.theme_store"):
            rebuild(db)
            rebuild(db)
            assert len(warnings()) == 1

            # 直ると警告は出ない。一覧が書かれ、警告済みの覚えも外れる
            note.write_text(f"{START}\n書きかけ\n{END}\n", encoding="utf-8")
            rebuild(db)
            assert len(warnings()) == 1
            assert "地政学入門" in note.read_text(encoding="utf-8")

            # また壊すと、もう1回だけ警告する
            note.write_text(f"{START}\n{START}\n{END}\n", encoding="utf-8")
            rebuild(db)
            rebuild(db)
            assert len(warnings()) == 2

    def test_writes_a_note_whose_mtime_is_far_in_the_future(self, db, shelf, themes):
        # 同期のずれで mtime が未来のノートを、永久に飛ばさない
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", "")
        now = 1_800_000_000.0
        os.utime(note, (now + 3600, now + 3600))

        written = theme_store.rebuild(db, quiet_seconds=10, now=now)

        assert note in written
        assert "地政学入門" in note.read_text(encoding="utf-8")

    def test_skips_a_note_whose_mtime_is_just_ahead_of_now(self, db, shelf, themes):
        # rebuild の途中で保存されたノート（mtime が now より少し先）は、書いている最中とみなす
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", "")
        now = 1_800_000_000.0
        os.utime(note, (now + 1, now + 1))

        written = theme_store.rebuild(db, quiet_seconds=10, now=now)

        assert note not in written
        assert note.read_text(encoding="utf-8") == ""

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


class TestWatcher:
    @pytest.fixture
    def session_factory(self, db_engine):
        return lambda: Session(db_engine)

    def test_runs_every_job_with_one_session(self, session_factory):
        sessions = []

        def first_job(db):
            sessions.append(("first", db))
            return []

        def second_job(db):
            sessions.append(("second", db))
            return []

        theme_store.ThemeWatcher(session_factory, jobs=[first_job, second_job])._tick()

        assert [name for name, _ in sessions] == ["first", "second"]
        assert sessions[0][1] is sessions[1][1]

    def test_runs_only_the_theme_rebuild_when_no_jobs_are_given(self, session_factory, tmp_path):
        theme_store.ThemeWatcher(session_factory)._tick()

        assert (tmp_path / "reports" / "themes" / HUB_NAME).is_file()

    def test_a_failing_job_does_not_stop_the_others(self, session_factory, caplog):
        calls = []
        errors = ["同じ失敗", "同じ失敗", "別の失敗"]

        def failing_job(db):
            # 書きかけのまま失敗したトランザクションを、次のジョブへ持ち越さない確認も兼ねる
            db.add(Book(title="書きかけの本"))
            raise RuntimeError(errors.pop(0))

        def healthy_job(db):
            calls.append(len(db.scalars(select(Book)).all()))
            return []

        watcher = theme_store.ThemeWatcher(session_factory, jobs=[failing_job, healthy_job])
        with caplog.at_level(logging.ERROR, logger="app.theme_store"):
            watcher._tick()
            watcher._tick()
            assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1

            watcher._tick()
            assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 2

        assert calls == [0, 0, 0]

    def test_logs_a_failure_again_after_the_job_recovered(self, session_factory, caplog):
        outcomes = [RuntimeError("失敗"), None, RuntimeError("失敗")]

        def flaky_job(db):
            outcome = outcomes.pop(0)
            if outcome:
                raise outcome
            return []

        watcher = theme_store.ThemeWatcher(session_factory, jobs=[flaky_job])
        with caplog.at_level(logging.ERROR, logger="app.theme_store"):
            for _ in range(3):
                watcher._tick()

        assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 2

    def test_keeps_going_when_the_session_cannot_be_opened(self, caplog):
        calls = []

        def broken_factory():
            calls.append(1)
            raise OSError("開けない")

        watcher = theme_store.ThemeWatcher(broken_factory, jobs=[lambda db: []])
        with caplog.at_level(logging.ERROR, logger="app.theme_store"):
            watcher._tick()
            watcher._tick()

        assert len(calls) == 2
        assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1
