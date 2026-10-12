"""移行スクリプト scripts/strip_report_frontmatter.py のテスト

旧版がレポートの frontmatter に複製した書誌（title〜tags）を取り除くスクリプト。
実ファイルを書いて `main()` を呼ぶ（I/O がこのスクリプトの本体なのでモックしない）。
スクリプトは import できる場所（パッケージ）に無いので、パスから読み込む。
`reports/` は conftest.py が `NOTES_REPORTS_DIR` を向けた `tmp_path/reports`。
"""

import fcntl
import importlib.util
import os
import threading
from pathlib import Path

import pytest

from app import report_store

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "strip_report_frontmatter.py"

_spec = importlib.util.spec_from_file_location("strip_report_frontmatter", SCRIPT)
strip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(strip)

LEGACY_KEYS = ["title", "author", "isbn", "genre", "status", "rating",
               "started_on", "finished_on", "tags"]

# 旧版が書いたファイル（設計書 0001 §5.2）に、ユーザーが足した aliases が付いたもの
LEGACY_FRONT = """\
---
type: reading-report
book_id: 17
updated: 2026-10-12T21:50:00+09:00
title: '失敗の本質 : 日本軍の組織論的研究'
author: 戸部良一
isbn: '9784122018334'
genre: academic
status: finished
rating: 5
started_on: 2026-09-01
finished_on: 2026-09-20
tags:
- 組織論
- 戦史
aliases:
- 失敗の本質
---
"""
LEGACY_REPORT = LEGACY_FRONT + "\n## 第1章\n本文\n"

# 書き出すと別の値になって戻ってくる frontmatter。!!omap は読むと (キー, 値) の tuple の
# list になるが、SafeDumper は tuple を list として書くので、読み戻すと tuple ではなくなる
UNSTABLE_REPORT = LEGACY_FRONT.replace("aliases:", "order: !!omap\n- a: 1\naliases:") + "\n本文\n"

OLD_MTIME = 1_000_000_000  # 2001 年。いま書いたファイルの mtime と取り違えない


@pytest.fixture
def reports_dir(tmp_path):
    directory = tmp_path / "reports"
    directory.mkdir()
    return directory


def put(directory, name, text, mtime=None):
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def legacy_report(book_id, body):
    return LEGACY_FRONT.replace("book_id: 17", f"book_id: {book_id}") + f"\n{body}\n"


class TestPlan:
    def test_removes_only_the_legacy_keys_and_keeps_the_rest_in_order(self):
        new_text, removed = strip.plan(LEGACY_REPORT)

        meta, _ = report_store.split_front_matter(new_text)
        assert list(meta) == ["type", "book_id", "updated", "aliases"]
        assert meta["aliases"] == ["失敗の本質"]
        assert removed == LEGACY_KEYS

    def test_keeps_the_body_byte_for_byte(self):
        body = (
            "\n## 第1章\n"
            "---\n"                                   # frontmatter の閉じと紛らわしい行
            "行末に空白がある行   \n"
            "\n\n\n"                                  # 空行の連続
            "<!-- notes:books:start -->\n- 一覧\n<!-- notes:books:end -->\n"
            "CRLF の行\r\n"
            "最後の行（改行なし）"
        )

        new_text, _ = strip.plan(LEGACY_FRONT + body)

        assert new_text.endswith(body)
        assert new_text.startswith("---\ntype: reading-report\n")

    def test_does_not_change_updated(self):
        new_text, _ = strip.plan(LEGACY_REPORT)

        old_meta, _ = report_store.split_front_matter(LEGACY_REPORT)
        new_meta, _ = report_store.split_front_matter(new_text)
        assert new_meta["updated"] == old_meta["updated"]
        assert "updated: 2026-10-12T21:50:00+09:00\n" in new_text

    @pytest.mark.parametrize("text", [
        "---\ntype: reading-report\nbook_id: 17\nupdated: 2026-10-12T21:50:00+09:00\n---\n\n本文\n",
        "---\ntype: reading-report\nbook_id: 17\naliases:\n- 別名\n---\n\n本文\n",
        "# frontmatter の無いメモ\n",
    ])
    def test_returns_none_when_there_is_nothing_to_remove(self, text):
        assert strip.plan(text) is None

    def test_refuses_a_rewrite_that_does_not_read_back_the_same(self):
        with pytest.raises(ValueError):
            strip.plan(UNSTABLE_REPORT)


class TestMain:
    def test_dry_run_does_not_write_and_shows_the_diff(self, reports_dir, capsys):
        path = put(reports_dir, "0017-失敗の本質.md", LEGACY_REPORT, mtime=OLD_MTIME)
        before = path.read_bytes()

        assert strip.main([]) == 0

        assert path.read_bytes() == before
        assert path.stat().st_mtime == OLD_MTIME
        out = capsys.readouterr().out
        assert "0017-失敗の本質.md: title, author, isbn, genre, status, rating" in out
        assert "-title:" in out
        assert "-tags:" in out
        assert "下見のみ。--apply を付けると 1 件を書き換える" in out

    def test_apply_rewrites_and_keeps_the_mtime(self, reports_dir, capsys):
        path = put(reports_dir, "0017-失敗の本質.md", LEGACY_REPORT, mtime=OLD_MTIME)
        mtime_ns = path.stat().st_mtime_ns

        assert strip.main(["--apply"]) == 0

        meta, body = report_store.split_front_matter(path.read_text(encoding="utf-8"))
        assert list(meta) == ["type", "book_id", "updated", "aliases"]
        assert body == "\n## 第1章\n本文\n"
        assert path.stat().st_mtime_ns == mtime_ns
        assert "書き換え 1 / 旧キーなし 0 / 対象外 0 / 読めない・検証失敗 0" in capsys.readouterr().out

    def test_apply_does_not_change_which_duplicate_is_primary(self, reports_dir):
        # 同じ book_id のファイルが複数あると、索引は mtime が最新のものを主にする。
        # 移行で古いほうの mtime が新しくなると、主が入れ替わって別の本文が出てしまう。
        put(reports_dir, "0005-Foo.md", legacy_report(5, "古い本文"), mtime=OLD_MTIME)
        put(reports_dir, "0005-Foo 1.md", legacy_report(5, "新しい本文"), mtime=OLD_MTIME + 1000)
        assert report_store.read(5) == "新しい本文"

        assert strip.main(["--apply"]) == 0

        assert report_store.read(5) == "新しい本文"
        for path in reports_dir.glob("*.md"):
            meta, _ = report_store.split_front_matter(path.read_text(encoding="utf-8"))
            assert "title" not in meta

    def test_apply_keeps_crlf_line_endings_in_the_body(self, reports_dir):
        body = "## 第1章\r\n本文\r\n\r\n終わり\r\n".encode()
        path = reports_dir / "0017-失敗の本質.md"
        path.write_bytes(LEGACY_FRONT.encode() + b"\n" + body)

        assert strip.main(["--apply"]) == 0

        assert path.read_bytes().endswith(b"\n" + body)
        assert b"title:" not in path.read_bytes()

    def test_skips_files_that_are_not_reading_reports(self, reports_dir, capsys):
        legacy_like = "---\ntype: theme\ntitle: 仏教\ntags:\n- a\n---\n\n本文\n"
        untouched = {
            "themes/仏教.md": legacy_like,
            "authors/渡辺照宏.md": legacy_like,
            ".trash/20261012-120000-0001-Foo.md": LEGACY_REPORT,
            ".0002-hidden.md": LEGACY_REPORT,
            "メモ.md": "---\ntitle: 手書きメモ\ntags:\n- a\n---\n\n本文\n",   # type が無い
            "別の種類.md": "---\ntype: note\ntitle: x\n---\n\n本文\n",       # type が違う
            "壊れている.md": "---\ntype: reading-report\ntitle: [閉じていない\n---\n\n本文\n",
            "frontmatterなし.md": "# ただのメモ\n",
        }
        for name, text in untouched.items():
            put(reports_dir, name, text, mtime=OLD_MTIME)
        target = put(reports_dir, "0017-失敗の本質.md", LEGACY_REPORT, mtime=OLD_MTIME)

        assert strip.main(["--apply"]) == 0

        for name, text in untouched.items():
            assert (reports_dir / name).read_text(encoding="utf-8") == text, name
        assert "title" not in report_store.split_front_matter(target.read_text(encoding="utf-8"))[0]
        # themes/ authors/ .trash/ と . で始まるファイルは数えない。直下の 5 件のうち
        # 対象外は type が無い・違う・壊れている・frontmatter なしの 4 件
        assert "書き換え 1 / 旧キーなし 0 / 対象外 4 / 読めない・検証失敗 0" in capsys.readouterr().out

    def test_is_idempotent(self, reports_dir, capsys):
        path = put(reports_dir, "0017-失敗の本質.md", LEGACY_REPORT, mtime=OLD_MTIME)
        assert strip.main(["--apply"]) == 0
        capsys.readouterr()
        after_first = path.read_bytes()
        mtime_ns = path.stat().st_mtime_ns

        assert strip.main(["--apply"]) == 0

        assert path.read_bytes() == after_first
        assert path.stat().st_mtime_ns == mtime_ns
        assert "書き換え 0 / 旧キーなし 1 /" in capsys.readouterr().out

    def test_reports_a_file_that_fails_verification_and_goes_on_to_the_next(
        self, reports_dir, capsys
    ):
        bad = put(reports_dir, "0001-unstable.md", UNSTABLE_REPORT)
        good = put(reports_dir, "0002-ok.md", legacy_report(2, "本文"))

        assert strip.main(["--apply"]) == 1

        assert bad.read_text(encoding="utf-8") == UNSTABLE_REPORT
        assert "title" not in report_store.split_front_matter(good.read_text(encoding="utf-8"))[0]
        captured = capsys.readouterr()
        assert "! 0001-unstable.md" in captured.err
        assert "書き換え 1 / 旧キーなし 0 / 対象外 0 / 読めない・検証失敗 1" in captured.out

    def test_counts_an_unreadable_file_and_exits_with_1(self, reports_dir, capsys):
        broken = reports_dir / "0003-壊れた文字コード.md"
        broken.write_bytes(b"---\ntype: reading-report\n---\n\xff\xfe\n")

        assert strip.main([]) == 1

        captured = capsys.readouterr()
        assert "! 0003-壊れた文字コード.md" in captured.err
        assert "読めない・検証失敗 1" in captured.out

    def test_exits_with_1_when_the_reports_directory_is_missing(self, tmp_path, capsys):
        assert not (tmp_path / "reports").exists()

        assert strip.main([]) == 1

        assert "見つかりません" in capsys.readouterr().err

    def test_apply_rereads_the_file_after_taking_the_lock(self, reports_dir):
        # ロックを待つ間に本文が保存されても、先に読んだ古い本文で上書きしない
        path = put(reports_dir, "0017-失敗の本質.md", LEGACY_REPORT, mtime=OLD_MTIME)

        lock_file = open(reports_dir / report_store.LOCK_NAME, "w")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        thread = threading.Thread(target=strip.main, args=(["--apply"],))
        try:
            thread.start()
            thread.join(timeout=0.3)
            assert thread.is_alive()  # ロックを待っている
            path.write_text(LEGACY_REPORT.replace("本文", "待っている間に保存した本文"),
                            encoding="utf-8")
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
        thread.join(timeout=5)

        assert not thread.is_alive()
        meta, body = report_store.split_front_matter(path.read_text(encoding="utf-8"))
        assert body == "\n## 第1章\n待っている間に保存した本文\n"
        assert list(meta) == ["type", "book_id", "updated", "aliases"]
