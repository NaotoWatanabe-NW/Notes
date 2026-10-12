"""移行スクリプト scripts/strip_report_frontmatter.py のテスト

旧版がレポートの frontmatter に複製した書誌（title〜tags）を取り除くスクリプト。
実ファイルを書いて `main()` を呼ぶ（I/O がこのスクリプトの本体なのでモックしない）。
OSError を起こせない箇所（書き込み・chmod・utime の失敗）と、Obsidian の保存が割り込む
タイミングだけは、monkeypatch で差し込む。
スクリプトは import できる場所（パッケージ）に無いので、パスから読み込む。
`reports/` は conftest.py が `NOTES_REPORTS_DIR` を向けた `tmp_path/reports`。
"""

import errno
import fcntl
import importlib.util
import os
import stat
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

BOM = chr(0xFEFF)

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

# LEGACY_FRONT から旧キーの行だけを消したもの
CLEANED_FRONT = """\
---
type: reading-report
book_id: 17
updated: 2026-10-12T21:50:00+09:00
aliases:
- 失敗の本質
---
"""

# 残すキーに、YAML を読んで書き直すと値や見た目が変わるものを集めた（コメント、`yes`、
# 8進数に読まれる `0123`、60進数に読まれる `1:30`、フロー形式、値が空のキー、重複キー、
# !!omap）。旧キーはその間に挟まる
MIXED_FRONT = """\
---
type: reading-report
book_id: 17
title: 旧タイトル
# 自分で足したキー（コメントも残る）
flag: yes
code: 0123
duration: 1:30
author: 旧著者
aliases: [a, 'b c']
empty_aliases:
dup: 1
tags:
- 組織論

dup: 2
order: !!omap
- a: 1
updated: 2026-10-12T21:50:00+09:00
---
"""
MIXED_CLEANED_FRONT = """\
---
type: reading-report
book_id: 17
# 自分で足したキー（コメントも残る）
flag: yes
code: 0123
duration: 1:30
aliases: [a, 'b c']
empty_aliases:
dup: 1

dup: 2
order: !!omap
- a: 1
updated: 2026-10-12T21:50:00+09:00
---
"""

# YAML としては正しいが、旧キーの行を消すと残りが壊れる（または旧キーが残る）書き方。
# 行を消したあとの検証で弾かれて、書かれないはず
UNDELETABLE_LEGACY_VALUES = [
    pytest.param('title: "失敗の\n本質"\n', id="multi-line-quoted-string-not-indented"),
    pytest.param("tags: [a,\nb]\n", id="multi-line-flow-list-not-indented"),
    pytest.param("tags:\n- a\n# 途中のコメント\n- b\n", id="comment-inside-block-list"),
    pytest.param('"title": 旧タイトル\n', id="quoted-key"),
]


def with_legacy_value(value):
    """aliases の前に旧キーの値（の書き方）を差し込んだ、検証で弾かれるはずのレポート。"""
    return LEGACY_FRONT.replace("aliases:", value + "aliases:") + "\n本文\n"


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


def summary(rewrite=0, clean=0, skipped=0, symlink=0, broken=0, errors=0):
    """main() が最後に出す集計行。"""
    return (f"書き換え {rewrite} / 旧キーなし {clean} / "
            f"対象外 {skipped}（symlink {symlink}・frontmatter が読めない {broken}）/ "
            f"読めない・検証失敗・書けない・途中で変更 {errors}")


class TestPlan:
    def test_removes_only_the_legacy_keys_and_keeps_the_rest_in_order(self):
        new_text, removed = strip.plan(LEGACY_REPORT)

        assert new_text == CLEANED_FRONT + "\n## 第1章\n本文\n"
        assert removed == LEGACY_KEYS

    def test_keeps_the_keys_it_leaves_byte_for_byte(self):
        # YAML を読んで書き直すと、コメントが消える・`yes` が `true`・`0123` が `83`・
        # `1:30` が `90` になる・フロー形式がブロック形式になる・`empty_aliases:` が
        # `empty_aliases: null` になる・重複キーの片方が消える。残すキーの行は触らない
        new_text, removed = strip.plan(MIXED_FRONT + "\n本文\n")

        assert new_text == MIXED_CLEANED_FRONT + "\n本文\n"
        assert removed == ["title", "author", "tags"]

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

        assert new_text == CLEANED_FRONT + body

    def test_does_not_change_updated(self):
        new_text, _ = strip.plan(LEGACY_REPORT)

        old_meta, _ = report_store.split_front_matter(LEGACY_REPORT)
        new_meta, _ = report_store.split_front_matter(new_text)
        assert new_meta["updated"] == old_meta["updated"]
        assert "updated: 2026-10-12T21:50:00+09:00\n" in new_text

    @pytest.mark.parametrize("tags", [
        pytest.param("tags:\n- a\n- b\n", id="block-list-at-key-indent"),
        pytest.param("tags:\n  - a\n  - b\n", id="indented-block-list"),
        pytest.param("tags: [a, b]\n", id="flow-list"),
        pytest.param("tags: [a,\n  b]\n", id="flow-list-over-two-lines"),
        pytest.param("tags: []\n", id="empty-list"),
        pytest.param("tags:\n", id="empty-value"),
    ])
    def test_removes_tags_in_any_list_style_and_not_the_next_key(self, tags):
        text = f"---\ntype: reading-report\nbook_id: 17\n{tags}aliases:\n- x\n---\n本文\n"

        new_text, removed = strip.plan(text)

        assert new_text == "---\ntype: reading-report\nbook_id: 17\naliases:\n- x\n---\n本文\n"
        assert removed == ["tags"]

    @pytest.mark.parametrize("title", [
        pytest.param("title: |\n  一行目\n\n  二行目\n", id="literal-block-with-a-blank-line"),
        pytest.param("title: >-\n  折りたたまれた\n  文字列\n", id="folded-block"),
        pytest.param('title: "二行に\n  またがる"\n', id="quoted-string-over-two-lines"),
    ])
    def test_removes_a_multi_line_legacy_value(self, title):
        text = f"---\ntype: reading-report\nbook_id: 17\n{title}aliases:\n- x\n---\n本文\n"

        new_text, _ = strip.plan(text)

        assert new_text == "---\ntype: reading-report\nbook_id: 17\naliases:\n- x\n---\n本文\n"

    def test_keeps_blank_lines_and_comments_around_a_legacy_value(self):
        # 旧キーの値の続きは、インデントのある行と `- ` の行まで。そのあとの空行やコメントは
        # 次のキーの前置きとしてユーザーのもの
        text = (
            "---\ntype: reading-report\nbook_id: 17\n"
            "author: 旧著者\n"
            "\n"
            "# ここから自分のキー\n"
            "tags:\n- a\n"
            "# 次のキーの説明\n"
            "aliases: x\n"
            "---\n本文\n"
        )

        new_text, _ = strip.plan(text)

        assert new_text == (
            "---\ntype: reading-report\nbook_id: 17\n"
            "\n"
            "# ここから自分のキー\n"
            "# 次のキーの説明\n"
            "aliases: x\n"
            "---\n本文\n"
        )

    def test_keeps_keys_that_only_look_like_legacy_keys(self):
        # 名前が前方一致するだけのキーと、ユーザーのキーの中の入れ子の title / tags は旧キーではない
        text = (
            "---\ntype: reading-report\nbook_id: 17\n"
            "title: 旧タイトル\n"
            "titles: 複数形\n"
            "title_en: English\n"
            "tags_extra:\n- z\n"
            "meta:\n  title: 入れ子\n  tags: [x]\n"
            "---\n本文\n"
        )

        new_text, removed = strip.plan(text)

        assert removed == ["title"]
        assert new_text == (
            "---\ntype: reading-report\nbook_id: 17\n"
            "titles: 複数形\n"
            "title_en: English\n"
            "tags_extra:\n- z\n"
            "meta:\n  title: 入れ子\n  tags: [x]\n"
            "---\n本文\n"
        )

    def test_keeps_crlf_line_endings_in_the_front_matter_and_the_body(self):
        text = (LEGACY_FRONT + "\n## 第1章\n本文\n").replace("\n", "\r\n")

        new_text, removed = strip.plan(text)

        assert new_text == (CLEANED_FRONT + "\n## 第1章\n本文\n").replace("\n", "\r\n")
        assert removed == LEGACY_KEYS

    def test_keeps_the_bom(self):
        new_text, _ = strip.plan(BOM + LEGACY_REPORT)

        assert new_text == BOM + CLEANED_FRONT + "\n## 第1章\n本文\n"

    @pytest.mark.parametrize("text", [
        "---\ntype: reading-report\nbook_id: 17\nupdated: 2026-10-12T21:50:00+09:00\n---\n\n本文\n",
        "---\ntype: reading-report\nbook_id: 17\naliases:\n- 別名\n---\n\n本文\n",
        "# frontmatter の無いメモ\n",
    ])
    def test_returns_none_when_there_is_nothing_to_remove(self, text):
        assert strip.plan(text) is None

    @pytest.mark.parametrize("value", UNDELETABLE_LEGACY_VALUES)
    def test_refuses_when_deleting_the_lines_breaks_the_rest(self, value):
        with pytest.raises(ValueError):
            strip.plan(with_legacy_value(value))

    def test_refuses_when_removing_the_keys_leaves_no_front_matter(self):
        # 旧キーの行を消すと YAML 部分が空になり、frontmatter として読めなくなる
        with pytest.raises(ValueError):
            strip.plan("---\ntitle: 旧タイトル\n---\n本文\n")


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

        assert path.read_text(encoding="utf-8") == CLEANED_FRONT + "\n## 第1章\n本文\n"
        assert path.stat().st_mtime_ns == mtime_ns
        assert summary(rewrite=1) in capsys.readouterr().out

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

    def test_apply_keeps_the_file_mode(self, reports_dir):
        # 一時ファイルは umask で作られるので、そのまま置き換えると 0600 が 0644 になる
        path = put(reports_dir, "0017-失敗の本質.md", LEGACY_REPORT, mtime=OLD_MTIME)
        path.chmod(0o600)

        old_umask = os.umask(0o022)
        try:
            assert strip.main(["--apply"]) == 0
        finally:
            os.umask(old_umask)

        assert "title:" not in path.read_text(encoding="utf-8")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_apply_keeps_crlf_line_endings_in_the_body(self, reports_dir):
        body = "## 第1章\r\n本文\r\n\r\n終わり\r\n".encode()
        path = reports_dir / "0017-失敗の本質.md"
        path.write_bytes(LEGACY_FRONT.encode() + b"\n" + body)

        assert strip.main(["--apply"]) == 0

        assert path.read_bytes().endswith(b"\n" + body)
        assert b"title:" not in path.read_bytes()

    def test_apply_keeps_bom_and_crlf_everywhere_byte_for_byte(self, reports_dir):
        # BOM 付きで、frontmatter も本文も CRLF（Windows のエディタで保存したファイル）
        body = "\n## 第1章\n本文\n\n終わり".replace("\n", "\r\n").encode()
        path = reports_dir / "0017-失敗の本質.md"
        path.write_bytes(
            (BOM + LEGACY_FRONT.replace("\n", "\r\n")).encode("utf-8") + body
        )

        assert strip.main(["--apply"]) == 0

        assert path.read_bytes() == (
            (BOM + CLEANED_FRONT.replace("\n", "\r\n")).encode("utf-8") + body
        )

    def test_apply_leaves_the_keys_it_keeps_untouched_on_disk(self, reports_dir):
        path = put(reports_dir, "0017-失敗の本質.md", MIXED_FRONT + "\n本文\n")

        assert strip.main(["--apply"]) == 0

        assert path.read_text(encoding="utf-8") == MIXED_CLEANED_FRONT + "\n本文\n"

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
        captured = capsys.readouterr()
        assert summary(rewrite=1, skipped=4, broken=1) in captured.out
        # 先頭が --- なのに読めないファイルだけが、旧キーが残るかもしれないので名前を出す
        assert "! 壊れている.md" in captured.err
        for name in ("メモ.md", "別の種類.md", "frontmatterなし.md"):
            assert name not in captured.err

    @pytest.mark.parametrize("argv", [[], ["--apply"]], ids=["dry-run", "apply"])
    @pytest.mark.parametrize("bad_date", ["2026-02-30", "2026-13-01", "0000-01-01"])
    def test_goes_on_past_a_file_whose_date_is_invalid(
        self, reports_dir, capsys, argv, bad_date
    ):
        # YAML としては正しいが日付として不正な値。PyYAML は ValueError を投げる
        bad_text = LEGACY_REPORT.replace("started_on: 2026-09-01", f"started_on: {bad_date}")
        bad = put(reports_dir, "0001-bad-date.md", bad_text, mtime=OLD_MTIME)
        good = put(reports_dir, "0002-ok.md", legacy_report(2, "本文"))

        assert strip.main(argv) == 0

        captured = capsys.readouterr()
        assert bad.read_text(encoding="utf-8") == bad_text
        assert "! 0001-bad-date.md" in captured.err
        assert "0002-ok.md: title" in captured.out
        # 他のファイルは下見なら書かず、--apply なら書く
        assert ("title:" not in good.read_text(encoding="utf-8")) == ("--apply" in argv)
        assert summary(rewrite=1, skipped=1, broken=1) in captured.out

    def test_names_a_symlink_as_skipped_and_does_not_replace_it(
        self, reports_dir, tmp_path, capsys
    ):
        # アプリの索引は symlink を辿るので見えているファイル。書き換えるとリンクが実ファイルに
        # 置き換わってしまう（リンク先は変わらない）ので触らず、黙って飛ばさず名前を出す
        outside = put(tmp_path / "elsewhere", "0017-失敗の本質.md", LEGACY_REPORT, mtime=OLD_MTIME)
        link = reports_dir / "0017-link.md"
        link.symlink_to(outside)
        assert report_store.has_report(17) is True

        assert strip.main(["--apply"]) == 0

        assert link.is_symlink()
        assert outside.read_text(encoding="utf-8") == LEGACY_REPORT
        captured = capsys.readouterr()
        assert "直下の *.md: 1 件" in captured.out
        assert summary(skipped=1, symlink=1) in captured.out
        assert "! 0017-link.md" in captured.err

    def test_is_idempotent(self, reports_dir, capsys):
        path = put(reports_dir, "0017-失敗の本質.md", LEGACY_REPORT, mtime=OLD_MTIME)
        assert strip.main(["--apply"]) == 0
        capsys.readouterr()
        after_first = path.read_bytes()
        mtime_ns = path.stat().st_mtime_ns

        assert strip.main(["--apply"]) == 0

        assert path.read_bytes() == after_first
        assert path.stat().st_mtime_ns == mtime_ns
        assert summary(clean=1) in capsys.readouterr().out

    @pytest.mark.parametrize("value", UNDELETABLE_LEGACY_VALUES)
    def test_reports_a_file_that_fails_verification_and_goes_on_to_the_next(
        self, reports_dir, capsys, value
    ):
        bad_text = with_legacy_value(value)
        bad = put(reports_dir, "0001-undeletable.md", bad_text)
        good = put(reports_dir, "0002-ok.md", legacy_report(2, "本文"))

        assert strip.main(["--apply"]) == 1

        assert bad.read_text(encoding="utf-8") == bad_text
        assert "title" not in report_store.split_front_matter(good.read_text(encoding="utf-8"))[0]
        captured = capsys.readouterr()
        assert "! 0001-undeletable.md" in captured.err
        assert summary(rewrite=1, errors=1) in captured.out

    def test_counts_an_unreadable_file_and_exits_with_1(self, reports_dir, capsys):
        broken = reports_dir / "0003-壊れた文字コード.md"
        broken.write_bytes(b"---\ntype: reading-report\n---\n\xff\xfe\n")

        assert strip.main([]) == 1

        captured = capsys.readouterr()
        assert "! 0003-壊れた文字コード.md" in captured.err
        assert summary(errors=1) in captured.out

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

    def test_apply_does_not_overwrite_a_save_made_after_reading(
        self, reports_dir, monkeypatch, capsys
    ):
        # Obsidian はアプリのロックを取らない。読んだあと書くまでの間に保存されたら、
        # その保存を失わないよう書かずに報告する（mtime を戻すのも古い値になってしまう）
        path = put(reports_dir, "0017-失敗の本質.md", LEGACY_REPORT, mtime=OLD_MTIME)
        other = put(reports_dir, "0018-別の本.md", legacy_report(18, "本文"))
        saved = LEGACY_REPORT.replace("本文", "Obsidian が保存した本文")
        examine = strip._examine

        def examine_then_save(target):
            result = examine(target)
            if target == path:
                target.write_text(saved, encoding="utf-8")
            return result

        monkeypatch.setattr(strip, "_examine", examine_then_save)

        assert strip.main(["--apply"]) == 1

        assert path.read_text(encoding="utf-8") == saved
        assert "title" not in report_store.split_front_matter(other.read_text(encoding="utf-8"))[0]
        captured = capsys.readouterr()
        assert "! 0017-失敗の本質.md" in captured.err
        assert "変更された" in captured.err
        assert summary(rewrite=1, errors=1) in captured.out

    def test_apply_reports_a_file_it_cannot_write_and_removes_the_temporary_file(
        self, reports_dir, monkeypatch, capsys
    ):
        bad_text = legacy_report(1, "本文")
        bad = put(reports_dir, "0001-cannot-write.md", bad_text)
        good = put(reports_dir, "0002-ok.md", legacy_report(2, "本文"))
        write_atomic = report_store.write_atomic

        def failing_write_atomic(path, text):
            if path == bad:
                # ディスクが埋まった、など。一時ファイルを作ったところで失敗する
                path.with_name(path.name + report_store.TMP_SUFFIX).write_text("途中まで")
                raise OSError(errno.ENOSPC, "No space left on device")
            write_atomic(path, text)

        monkeypatch.setattr(report_store, "write_atomic", failing_write_atomic)

        assert strip.main(["--apply"]) == 1

        assert bad.read_text(encoding="utf-8") == bad_text
        assert not list(reports_dir.glob("*" + report_store.TMP_SUFFIX))
        assert "title" not in report_store.split_front_matter(good.read_text(encoding="utf-8"))[0]
        captured = capsys.readouterr()
        assert "! 0001-cannot-write.md" in captured.err
        assert "No space left on device" in captured.err
        assert summary(rewrite=1, errors=1) in captured.out

    @pytest.mark.parametrize("failing", ["chmod", "utime"])
    def test_apply_reports_a_file_whose_mode_or_mtime_cannot_be_restored_and_goes_on(
        self, reports_dir, monkeypatch, capsys, failing
    ):
        bad = put(reports_dir, "0001-cannot-restore.md", legacy_report(1, "本文"))
        good = put(reports_dir, "0002-ok.md", legacy_report(2, "本文"))
        real = getattr(os, failing)

        def fail_for_bad(path, *args, **kwargs):
            if Path(path) == bad:
                raise PermissionError(errno.EPERM, "Operation not permitted")
            return real(path, *args, **kwargs)

        monkeypatch.setattr(os, failing, fail_for_bad)

        assert strip.main(["--apply"]) == 1

        assert not list(reports_dir.glob("*" + report_store.TMP_SUFFIX))
        assert "title" not in report_store.split_front_matter(good.read_text(encoding="utf-8"))[0]
        captured = capsys.readouterr()
        assert "! 0001-cannot-restore.md" in captured.err
        assert "Operation not permitted" in captured.err
        assert summary(rewrite=1, errors=1) in captured.out
