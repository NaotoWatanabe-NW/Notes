"""読書レポート本文のファイルストア（app/report_store.py）のテスト

ファイルを実際に書いて読ませる（I/O がこの機能の本体なのでモックしない）。
Book は DB に入れずその場で作る（ストアは属性しか見ない）。
"""

import fcntl
import os
import re
import threading
from datetime import date

import pytest

from app import report_store
from app.models import Book, BookStatus, Genre, Tag


@pytest.fixture
def reports_dir(tmp_path, monkeypatch):
    directory = tmp_path / "reports"
    monkeypatch.setenv("NOTES_REPORTS_DIR", str(directory))
    return directory


def make_book(book_id=1, title="失敗の本質 : 日本軍の組織論的研究", **kwargs):
    book = Book(title=title, status=kwargs.pop("status", BookStatus.READING))
    book.id = book_id
    for key, value in kwargs.items():
        setattr(book, key, value)
    return book


class TestSaveAndRead:
    def test_saves_body_to_a_file_named_after_the_book(self, reports_dir):
        book = make_book()
        path = report_store.save(book, "## 第1章\n要点を書く。\n")

        assert path.parent == reports_dir
        assert path.name == "0001-失敗の本質-日本軍の組織論的研究.md"
        assert report_store.read(1) == "## 第1章\n要点を書く。"

    def test_front_matter_has_only_type_book_id_and_updated(self, reports_dir):
        book = make_book(
            book_id=17,
            author="戸部良一",
            isbn="9784122018334",
            genre=Genre.ACADEMIC,
            status=BookStatus.FINISHED,
            rating=5,
            started_on=date(2026, 9, 1),
            finished_on=date(2026, 9, 20),
        )
        book.tags = [Tag(name="組織論"), Tag(name="戦史")]
        path = report_store.save(book, "本文")

        text = path.read_text(encoding="utf-8")
        meta, body = report_store.split_front_matter(text)
        assert list(meta) == ["type", "book_id", "updated"]
        assert meta["type"] == "reading-report"
        assert meta["book_id"] == 17
        for value in ("戸部良一", "9784122018334", "組織論", "戦史"):
            assert value not in text
        assert body.strip() == "本文"

    def test_read_returns_none_when_there_is_no_report(self, reports_dir):
        assert report_store.read(1) is None
        assert report_store.has_report(1) is False

    def test_empty_body_deletes_the_file(self, reports_dir):
        book = make_book()
        path = report_store.save(book, "本文")
        assert path.exists()

        assert report_store.save(book, "   ") is None
        assert not path.exists()
        assert report_store.read(1) is None

    def test_leaves_no_temporary_file_behind(self, reports_dir):
        report_store.save(make_book(), "本文")
        assert list(reports_dir.glob("*.tmp")) == []

    def test_overwrites_the_body_on_the_next_save(self, reports_dir):
        book = make_book()
        report_store.save(book, "最初の本文")
        report_store.save(book, "直した本文")
        assert report_store.read(1) == "直した本文"
        assert len(list(reports_dir.glob("*.md"))) == 1

    def test_does_not_rewrite_the_file_when_nothing_changed(self, reports_dir):
        # エディタは閉じるたびに同じ本文を送る。updated と mtime を動かさない。
        book = make_book()
        path = report_store.save(book, "本文")
        before_text = path.read_text(encoding="utf-8")
        before_mtime = path.stat().st_mtime_ns

        assert report_store.save(book, "本文\n") == path

        assert path.stat().st_mtime_ns == before_mtime
        assert path.read_text(encoding="utf-8") == before_text

    def test_does_not_rewrite_the_file_when_only_the_bibliography_changed(self, reports_dir):
        # 書誌は DB にだけある。本の評価や状態が変わってもファイルは動かない。
        book = make_book()
        path = report_store.save(book, "本文")
        before_text = path.read_text(encoding="utf-8")
        before_mtime = path.stat().st_mtime_ns

        book.rating = 4
        book.status = BookStatus.FINISHED
        report_store.save(book, "本文")

        assert path.read_text(encoding="utf-8") == before_text
        assert path.stat().st_mtime_ns == before_mtime


class TestFilename:
    def test_keeps_the_file_name_when_the_title_changes(self, reports_dir):
        # テーマノートなどから手で張ったリンクを、アプリの改名で切らない。
        # 新しいタイトルは DB にだけある。
        book = make_book(title="旧タイトル")
        old = report_store.save(book, "本文")

        book.title = "新しいタイトル"
        path = report_store.save(book, "本文")

        assert path == old
        assert [p.name for p in reports_dir.glob("*.md")] == ["0001-旧タイトル.md"]
        meta, _ = report_store.split_front_matter(path.read_text(encoding="utf-8"))
        assert "title" not in meta

    def test_resolves_by_book_id_after_a_manual_rename(self, reports_dir):
        # Obsidian で改名されても、正の鍵は frontmatter の book_id なので追える。
        path = report_store.save(make_book(), "本文")
        path.rename(reports_dir / "手で付けた名前.md")

        assert report_store.read(1) == "本文"
        assert report_store.has_report(1) is True

    def test_falls_back_when_the_title_has_only_unusable_characters(self, reports_dir):
        path = report_store.save(make_book(title="///"), "本文")
        assert path.name == "0001-untitled.md"


class TestExternalEdits:
    def test_reflects_an_edit_made_outside_the_app(self, reports_dir):
        # Obsidian やエディタからの直接編集を、再起動なしで読み直す。
        path = report_store.save(make_book(), "最初の本文")
        assert report_store.read(1) == "最初の本文"

        text = path.read_text(encoding="utf-8").replace("最初の本文", "外で直した本文")
        path.write_text(text, encoding="utf-8")

        assert report_store.read(1) == "外で直した本文"

    def test_ignores_a_file_without_book_id(self, reports_dir):
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "手書きメモ.md").write_text("# ただのメモ\n", encoding="utf-8")
        assert report_store.book_ids_with_report() == set()

    def test_notices_a_file_deleted_outside_the_app(self, reports_dir):
        path = report_store.save(make_book(), "本文")
        path.unlink()
        assert report_store.has_report(1) is False
        assert report_store.read(1) is None

    def test_ignores_hidden_files(self, reports_dir):
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / ".draft.md").write_text(
            "---\nbook_id: 9\n---\n下書き\n", encoding="utf-8"
        )
        assert report_store.has_report(9) is False


class TestDelete:
    def test_removes_the_file(self, reports_dir):
        path = report_store.save(make_book(), "本文")
        assert report_store.delete(1) is True
        assert not path.exists()
        assert report_store.has_report(1) is False

    def test_returns_false_when_there_is_nothing_to_delete(self, reports_dir):
        assert report_store.delete(1) is False


class TestBookIdsWithReport:
    def test_lists_every_book_that_has_a_report(self, reports_dir):
        report_store.save(make_book(book_id=1, title="A"), "本文A")
        report_store.save(make_book(book_id=5, title="B"), "本文B")
        assert report_store.book_ids_with_report() == {1, 5}


def _write_report(directory, name, book_id, body="本文", mtime=None, extra_front=""):
    """book_id 付きのレポートを直接置く（Obsidian での複製・手書きを再現する）。"""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(
        f"---\nbook_id: {book_id}\n{extra_front}---\n\n{body}\n", encoding="utf-8"
    )
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class TestDuplicateFilesForOneBook:
    def test_reads_the_most_recently_modified_file(self, reports_dir):
        _write_report(reports_dir, "0005-Foo.md", 5, "古い本文", mtime=1_000_000)
        _write_report(reports_dir, "0005-Foo 1.md", 5, "新しい本文", mtime=2_000_000)
        assert report_store.read(5) == "新しい本文"

    def test_breaks_an_mtime_tie_by_path_name(self, reports_dir):
        _write_report(reports_dir, "0005-b.md", 5, "b", mtime=1_000_000)
        _write_report(reports_dir, "0005-a.md", 5, "a", mtime=1_000_000)
        assert report_store.read(5) == "a"

    def test_promotes_the_remaining_copy_when_the_primary_is_removed(self, reports_dir):
        old = _write_report(reports_dir, "0005-Foo.md", 5, "古い本文", mtime=1_000_000)
        new = _write_report(reports_dir, "0005-Foo 1.md", 5, "新しい本文", mtime=2_000_000)
        new.unlink()

        assert report_store.has_report(5) is True
        assert report_store.read(5) == "古い本文"
        assert report_store.book_ids_with_report() == {5}
        assert old.exists()

    def test_save_leaves_the_copy_alone_and_writes_to_the_primary(self, reports_dir):
        book = make_book(book_id=5, title="Foo")
        report_store.save(book, "最初")
        copy = _write_report(reports_dir, "0005-Foo 1.md", 5, "複製の本文", mtime=1_000_000)
        primary = reports_dir / "0005-Foo.md"
        os.utime(primary, (2_000_000, 2_000_000))

        report_store.save(book, "直した本文")

        assert report_store.read(5) == "直した本文"
        assert "複製の本文" in copy.read_text(encoding="utf-8")
        assert sorted(p.name for p in reports_dir.glob("*.md")) == [
            "0005-Foo 1.md", "0005-Foo.md",
        ]

    def test_save_does_not_overwrite_a_copy_sitting_on_the_target_name(self, reports_dir):
        # 主は filename_for の名前ではない。その名前を埋めている複製を潰さず主に書く。
        primary = _write_report(reports_dir, "手で付けた名前.md", 5, "主の本文", mtime=2_000_000)
        copy = _write_report(reports_dir, "0005-Foo.md", 5, "複製の本文", mtime=1_000_000)

        path = report_store.save(make_book(book_id=5, title="Foo"), "直した本文")

        assert path == primary
        assert "直した本文" in primary.read_text(encoding="utf-8")
        assert "複製の本文" in copy.read_text(encoding="utf-8")

    def test_save_does_not_overwrite_a_foreign_file_on_the_target_name(self, reports_dir):
        # book_id の無いメモが target と同じ名前でも、上書きせず別名にする
        memo = reports_dir / "0005-Foo.md"
        reports_dir.mkdir(parents=True)
        memo.write_text("# ただのメモ\n", encoding="utf-8")

        path = report_store.save(make_book(book_id=5, title="Foo"), "本文")

        assert path.name == "0005-Foo-2.md"
        assert memo.read_text(encoding="utf-8") == "# ただのメモ\n"
        assert report_store.read(5) == "本文"

    def test_save_does_not_overwrite_a_file_of_another_book_on_the_target_name(self, reports_dir):
        other = _write_report(reports_dir, "0005-Foo.md", 9, "別の本")
        path = report_store.save(make_book(book_id=5, title="Foo"), "本文")

        assert path.name == "0005-Foo-2.md"
        assert "別の本" in other.read_text(encoding="utf-8")
        assert report_store.read(9) == "別の本"

    def test_delete_moves_every_file_with_that_book_id(self, reports_dir):
        _write_report(reports_dir, "0005-Foo.md", 5, "本文", mtime=1_000_000)
        _write_report(reports_dir, "0005-Foo 1.md", 5, "複製", mtime=2_000_000)
        other = _write_report(reports_dir, "0006-Bar.md", 6, "別の本")

        assert report_store.delete(5) is True

        assert report_store.has_report(5) is False
        assert report_store.read(5) is None
        assert other.exists()
        assert report_store.has_report(6) is True


class TestTrash:
    def test_delete_moves_the_file_into_a_timestamped_trash_entry(self, reports_dir):
        path = report_store.save(make_book(), "消す本文")
        report_store.delete(1)

        assert not path.exists()
        (trashed,) = (reports_dir / ".trash").iterdir()
        assert re.fullmatch(r"\d{8}-\d{6}-" + re.escape(path.name), trashed.name)
        assert "消す本文" in trashed.read_text(encoding="utf-8")

    def test_trashed_files_are_not_indexed(self, reports_dir):
        report_store.save(make_book(), "本文")
        report_store.delete(1)
        assert report_store.has_report(1) is False
        assert report_store.book_ids_with_report() == set()

    def test_numbers_the_trash_entry_when_the_name_collides(self, reports_dir):
        # 同じ秒に同じ名前のファイルを2回消しても、先のゴミ箱の中身を潰さない
        book = make_book()
        for body in ("一回目", "二回目"):
            report_store.save(book, body)
            report_store.delete(1)

        bodies = sorted(p.read_text(encoding="utf-8") for p in (reports_dir / ".trash").iterdir())
        assert len(bodies) == 2
        assert any("一回目" in b for b in bodies) and any("二回目" in b for b in bodies)

    def test_saving_an_empty_body_also_goes_to_the_trash(self, reports_dir):
        report_store.save(make_book(), "本文")
        report_store.save(make_book(), "")
        assert len(list((reports_dir / ".trash").iterdir())) == 1


class TestLocking:
    def test_save_keeps_a_user_key_added_while_it_waits_for_the_lock(self, reports_dir):
        # frontmatter はロックを取ってから読む。待っている間に足されたキーを、
        # 先に読んだ古い内容で消してしまわない
        book = make_book()
        path = report_store.save(book, "古い本文")

        lock_file = open(reports_dir / report_store.LOCK_NAME, "w")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        thread = threading.Thread(target=report_store.save, args=(book, "新しい本文"))
        try:
            thread.start()
            thread.join(timeout=0.3)
            assert thread.is_alive()  # ロックを待っている
            # 待っている間に、Obsidian でキーを足した状態を再現する
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "\n---\n", "\naliases:\n- 別名\n---\n", 1
                ),
                encoding="utf-8",
            )
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
        thread.join(timeout=5)

        assert not thread.is_alive()
        meta, _ = report_store.split_front_matter(path.read_text(encoding="utf-8"))
        assert meta["aliases"] == ["別名"]
        assert report_store.read(1) == "新しい本文"

    def test_delete_looks_up_the_path_after_taking_the_lock(self, reports_dir):
        # ロック待ちの間に改名されても、改名後のファイルを消せる
        book = make_book(title="旧")
        path = report_store.save(book, "本文")

        lock_file = open(reports_dir / report_store.LOCK_NAME, "w")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        results = []
        thread = threading.Thread(target=lambda: results.append(report_store.delete(1)))
        try:
            thread.start()
            thread.join(timeout=0.3)
            assert thread.is_alive()
            path.rename(reports_dir / "改名後.md")
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
        thread.join(timeout=5)

        assert results == [True]
        assert report_store.has_report(1) is False
        assert list(reports_dir.glob("*.md")) == []


class TestBookIdSpelling:
    @pytest.mark.parametrize("spelling", ['"5"', "5.0", "'5'", "5"])
    def test_accepts_integer_like_book_ids(self, reports_dir, spelling):
        reports_dir.mkdir(parents=True)
        (reports_dir / "x.md").write_text(
            f"---\nbook_id: {spelling}\n---\n本文\n", encoding="utf-8"
        )
        assert report_store.read(5) == "本文"

    @pytest.mark.parametrize("spelling", ["true", "false", "5.5", '"abc"', "[5]", "null"])
    def test_rejects_values_that_are_not_a_book_id(self, reports_dir, spelling):
        reports_dir.mkdir(parents=True)
        (reports_dir / "x.md").write_text(
            f"---\nbook_id: {spelling}\n---\n本文\n", encoding="utf-8"
        )
        assert report_store.book_ids_with_report() == set()
        assert report_store.has_report(1) is False


class TestUserFrontMatterKeys:
    def test_save_keeps_keys_the_user_added(self, reports_dir):
        book = make_book(title="Foo")
        path = report_store.save(book, "本文")
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "\n---\n", "\naliases:\n- 別名\ncssclasses: wide\n---\n", 1
            ),
            encoding="utf-8",
        )

        report_store.save(book, "直した本文")

        meta, _ = report_store.split_front_matter(path.read_text(encoding="utf-8"))
        assert meta["aliases"] == ["別名"]
        assert meta["cssclasses"] == "wide"
        assert report_store.read(1) == "直した本文"

    def test_save_puts_user_keys_after_the_app_keys(self, reports_dir):
        book = make_book(title="Foo")
        path = report_store.save(book, "本文")
        path.write_text(
            path.read_text(encoding="utf-8").replace("type:", "zzz: 1\ntype:", 1),
            encoding="utf-8",
        )

        report_store.save(book, "別の本文")

        meta, _ = report_store.split_front_matter(path.read_text(encoding="utf-8"))
        assert meta["zzz"] == 1
        keys = list(meta)
        assert keys[:3] == ["type", "book_id", "updated"] and keys[-1] == "zzz"
        assert report_store.read(1) == "別の本文"

    def test_save_keeps_legacy_bibliographic_keys_as_they_are(self, reports_dir):
        # 旧版が書いた title〜tags は、ユーザーが足したキーと区別できない。
        # 保存では消さない（消すのは移行スクリプトだけ）。
        path = _write_report(
            reports_dir, "0001-Foo.md", 1,
            extra_front="type: reading-report\ntitle: 勝手に直した\nstatus: reading\ntags: [a]\n",
        )

        report_store.save(make_book(book_id=1, title="Foo", status=BookStatus.FINISHED), "別の本文")

        meta, _ = report_store.split_front_matter(path.read_text(encoding="utf-8"))
        assert meta["title"] == "勝手に直した"
        assert meta["status"] == "reading"
        assert meta["tags"] == ["a"]
        assert report_store.read(1) == "別の本文"


class TestBom:
    def test_indexes_and_reads_a_file_starting_with_a_bom(self, reports_dir):
        reports_dir.mkdir(parents=True)
        (reports_dir / "bom.md").write_bytes(
            "---\nbook_id: 3\n---\n本文\n".encode("utf-8-sig")
        )
        assert report_store.has_report(3) is True
        assert report_store.read(3) == "本文"

    def test_does_not_write_a_bom_when_saving(self, reports_dir):
        path = _write_report(reports_dir, "bom.md", 3)
        path.write_bytes(path.read_bytes().replace(b"---", "﻿---".encode(), 1))
        report_store.save(make_book(book_id=3, title="Foo"), "直した")
        for md in reports_dir.glob("*.md"):
            assert not md.read_bytes().startswith(b"\xef\xbb\xbf")


class TestEmptyBody:
    def test_a_file_with_only_front_matter_has_no_report(self, reports_dir):
        _write_report(reports_dir, "0004-Foo.md", 4, body="   ")
        assert report_store.read(4) is None
        assert report_store.has_report(4) is False
        assert report_store.book_ids_with_report() == set()

    def test_reflects_a_body_added_to_an_empty_file(self, reports_dir):
        path = _write_report(reports_dir, "0004-Foo.md", 4, body="")
        assert report_store.has_report(4) is False
        path.write_text("---\nbook_id: 4\n---\n\n書いた\n", encoding="utf-8")
        assert report_store.has_report(4) is True


class TestBrokenSymlinkInTheReportsDirectory:
    def test_other_reports_stay_visible_next_to_a_symlink_that_points_to_itself(self, reports_dir):
        # 自分を指す symlink は is_file() が ELOOP で例外を出す。1つのせいで索引が空になると、
        # 全レポートが「無い」ことになり、次の保存で同じ本のレポートが2つ目として作られてしまう
        _write_report(reports_dir, "0008-ok.md", 8, body="残っている本文")
        (reports_dir / "loop.md").symlink_to("loop.md")

        assert report_store.book_ids_with_report() == {8}
        assert report_store.read(8) == "残っている本文"
        path = report_store.save(make_book(book_id=8, title="別のタイトル"), "書き直した本文")
        assert path == reports_dir / "0008-ok.md"


class TestFrontMatterWithAnInvalidDate:
    # YAML としては正しいが日付として不正な値。PyYAML は YAMLError ではなく ValueError を投げる
    BAD_DATES = ["2026-02-30", "2026-13-01", "0000-01-01"]

    @pytest.mark.parametrize("bad_date", BAD_DATES)
    def test_one_such_file_does_not_break_the_index(self, reports_dir, bad_date):
        # 1ファイルのせいで索引が落ちると、本の一覧 API 全体が 500 になる
        _write_report(reports_dir, "0007-bad-date.md", 7,
                      extra_front=f"started_on: {bad_date}\n")
        _write_report(reports_dir, "0008-ok.md", 8)

        assert report_store.book_ids_with_report() == {8}

    @pytest.mark.parametrize("bad_date", BAD_DATES)
    def test_such_a_file_does_not_count_as_a_report(self, reports_dir, bad_date):
        # frontmatter が読めない = book_id が分からない、という壊れた frontmatter と同じ扱い
        _write_report(reports_dir, "0007-bad-date.md", 7,
                      extra_front=f"started_on: {bad_date}\n")

        assert report_store.has_report(7) is False
        assert report_store.read(7) is None

    @pytest.mark.parametrize("bad_date", BAD_DATES)
    def test_split_front_matter_returns_the_whole_text_as_the_body(self, bad_date):
        text = f"---\nbook_id: 7\nstarted_on: {bad_date}\n---\n\n本文\n"

        assert report_store.split_front_matter(text) == ({}, text)


class TestWriteAtomicExpect:
    """`expect`: ロックを取らない書き手（Obsidian）の保存を消さない条件付きの置き換え。

    競合は、tmp を書いて fsync している間に相手が保存した、という形で再現する
    （fsync を差し替えて、その1回目の中で相手の保存を入れる）。
    """

    @staticmethod
    def act_while_syncing(monkeypatch, action):
        fsync = os.fsync
        acted = []

        def fsync_after_someone_saved(fd):
            fsync(fd)
            if not acted:
                acted.append(True)
                action()

        monkeypatch.setattr(os, "fsync", fsync_after_someone_saved)

    @staticmethod
    def key(path):
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size

    def test_replaces_the_file_when_it_is_as_expected(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("古い", encoding="utf-8")

        assert report_store.write_atomic(path, "新しい", expect=self.key(path)) is True

        assert path.read_text(encoding="utf-8") == "新しい"
        assert list(tmp_path.glob("*.tmp")) == []

    def test_replaces_unconditionally_without_expect(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("古い", encoding="utf-8")

        assert report_store.write_atomic(path, "新しい") is True

        assert path.read_text(encoding="utf-8") == "新しい"

    def test_does_not_replace_a_file_saved_while_it_was_being_written(self, tmp_path, monkeypatch):
        path = tmp_path / "a.md"
        path.write_text("古い", encoding="utf-8")
        expect = self.key(path)
        self.act_while_syncing(monkeypatch, lambda: path.write_text("古い\n\nいま書いた段落", encoding="utf-8"))

        assert report_store.write_atomic(path, "新しい", expect=expect) is False

        assert path.read_text(encoding="utf-8") == "古い\n\nいま書いた段落"
        assert list(tmp_path.glob("*.tmp")) == []

    def test_notices_a_save_of_the_same_size_by_its_mtime(self, tmp_path, monkeypatch):
        path = tmp_path / "a.md"
        path.write_text("AAAA", encoding="utf-8")
        expect = self.key(path)

        def save_same_size():
            path.write_text("BBBB", encoding="utf-8")
            stat = path.stat()
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))

        self.act_while_syncing(monkeypatch, save_same_size)

        assert report_store.write_atomic(path, "CCCC", expect=expect) is False
        assert path.read_text(encoding="utf-8") == "BBBB"

    def test_does_not_bring_back_a_file_deleted_while_it_was_being_written(self, tmp_path, monkeypatch):
        path = tmp_path / "a.md"
        path.write_text("古い", encoding="utf-8")
        expect = self.key(path)
        self.act_while_syncing(monkeypatch, path.unlink)

        assert report_store.write_atomic(path, "新しい", expect=expect) is False

        assert not path.exists()
        assert list(tmp_path.glob("*.tmp")) == []

    def test_removes_the_tmp_file_when_the_replace_itself_fails(self, tmp_path, monkeypatch):
        path = tmp_path / "a.md"
        path.write_text("古い", encoding="utf-8")

        def failing_replace(src, dst):
            raise PermissionError("置き換えられない")

        monkeypatch.setattr(os, "replace", failing_replace)

        with pytest.raises(PermissionError):
            report_store.write_atomic(path, "新しい", expect=self.key(path))

        assert path.read_text(encoding="utf-8") == "古い"
        assert list(tmp_path.glob("*.tmp")) == []

    def test_absent_creates_a_new_file_and_leaves_no_tmp_link_behind(self, tmp_path):
        path = tmp_path / "a.md"

        assert report_store.write_atomic(path, "新規", expect=report_store.ABSENT) is True

        assert path.read_text(encoding="utf-8") == "新規"
        assert path.stat().st_nlink == 1
        assert list(tmp_path.glob("*.tmp")) == []

    def test_absent_does_not_overwrite_a_file_created_while_it_was_being_written(self, tmp_path, monkeypatch):
        path = tmp_path / "a.md"
        self.act_while_syncing(monkeypatch, lambda: path.write_text("ユーザーが作った", encoding="utf-8"))

        assert report_store.write_atomic(path, "新規", expect=report_store.ABSENT) is False

        assert path.read_text(encoding="utf-8") == "ユーザーが作った"
        assert list(tmp_path.glob("*.tmp")) == []

    def test_absent_does_not_overwrite_a_file_that_already_exists(self, tmp_path):
        path = tmp_path / "a.md"
        path.write_text("既にある", encoding="utf-8")

        assert report_store.write_atomic(path, "新規", expect=report_store.ABSENT) is False

        assert path.read_text(encoding="utf-8") == "既にある"

    def test_absent_does_not_write_through_a_dangling_symlink(self, tmp_path):
        path = tmp_path / "a.md"
        target = tmp_path / "別の場所.md"
        os.symlink(target, path)

        assert report_store.write_atomic(path, "新規", expect=report_store.ABSENT) is False

        assert not target.exists()
        assert path.is_symlink()
        assert list(tmp_path.glob("*.tmp")) == []
