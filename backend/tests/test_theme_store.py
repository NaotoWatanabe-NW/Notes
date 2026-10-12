"""テーマノートの一覧づくり（app/theme_store.py）のテスト

DB はメモリ上の SQLite、ノートとレポートは実ファイル（I/O がこの機能の本体なのでモックしない）。
書き直しの「直近に更新されたノートは飛ばす」を避けたいテストでは quiet_seconds=0 で呼ぶ。
"""

import functools
import logging
import os
import threading
import time
import unicodedata
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import report_store, theme_store
from app.models import Book, BookStatus, Tag
from app.theme_store import END, HUB_NAME, START


@pytest.fixture(autouse=True)
def _forget_warned_notes():
    # 壊れたマーカー・書き込み失敗の警告済みパスはモジュール変数。テストをまたいで残さない
    theme_store._warned_broken.clear()
    theme_store._warned_write_failed.clear()
    yield
    theme_store._warned_broken.clear()
    theme_store._warned_write_failed.clear()


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

    def test_accepts_a_marker_line_with_up_to_three_leading_spaces_and_trailing_whitespace(
            self, db, shelf, themes):
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", f"上\n  {START}  \n古い一覧\n   {END}\t\n下\n")

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


# ユーザーが例として書いたマーカー（またはマーカーに見える行）を含むノートの断片。
# どれも「閉じ済み」で、マーカーの組は本物ではない。壊れた入力ではなく、普通に書かれうる書き方。
_EXAMPLE_NOTES = {
    "tab_indented_markers": f"本文\n\n\t{START}\n\t例の一覧\n\t{END}\n\n後半\n",
    "four_space_indented_markers": f"本文\n\n    {START}\n    例の一覧\n    {END}\n\n後半\n",
    # Obsidian の既定ではリスト内のコードブロックはタブ字下げ
    "tab_indented_fence_in_a_list": f"- 例:\n\t```\n\t{START}\n\t例の一覧\n\t{END}\n\t```\n",
    # 字下げの無いマーカー行は、フェンスを見落とすと本物と取り違える
    "markers_inside_a_tab_indented_fence": f"- 例:\n\t```\n{START}\n例の一覧\n{END}\n\t```\n",
    "fence_opened_on_the_list_marker_line":
        f"- ```\n  {START}\n  例の一覧\n  {END}\n  ```\n- ```bash\n  ls\n  ```\n",
    "fence_in_an_ordered_list": f"1. ```\n   {START}\n   例の一覧\n   {END}\n   ```\n",
    "fence_in_a_nested_list_with_8_spaces":
        f"- 親\n    - 子:\n        ```\n        {START}\n        例の一覧\n        {END}\n        ```\n",
    "fence_inside_nested_blockquotes": f"> > ```\n{START}\n例の一覧\n{END}\n> > ```\n",
    # "```js```" は文中のコードで、フェンスの開きではない（開きと取り違えると、次の本物の
    # フェンスの開きと閉じが逆になり、中のマーカーが外に出る）
    "backticks_in_the_info_string_is_not_a_fence":
        f"```js``` と ```py``` の違い\n\n```\n{START}\n例の一覧\n{END}\n```\n\n```python\nx = 1\n```\n",
    # チルダのフェンスは info 文字列にバッククォートがあってもフェンス
    "tilde_fence_with_a_backtick_in_the_info_string": f"~~~ a`b\n{START}\n例の一覧\n{END}\n~~~\n",
    "markers_inside_a_multi_line_html_comment": f"<!--\n{START}\n例の一覧\n{END}\n-->\n",
    # コメントの中の ``` はフェンスの開きではない（開きと取り違えると閉じていないフェンスになる）
    "fence_inside_a_multi_line_html_comment": "<!--\n```\nコメントアウトしたコード\n-->\n本文\n",
}
_REAL_BLOCK = f"{START}\n古い一覧\n{END}"


@pytest.mark.parametrize("example", _EXAMPLE_NOTES.values(), ids=_EXAMPLE_NOTES.keys())
class TestMarkersInsideCodeBlocks:
    def test_appends_the_list_after_the_example_and_changes_nothing_the_next_time(
            self, db, shelf, themes, example):
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", example)

        written = rebuild(db)

        text = note.read_text(encoding="utf-8")
        assert note in written
        assert text.startswith(example + "\n" + START + "\n## このテーマの本")
        assert text.endswith(END + "\n")
        assert text.count(START) == example.count(START) + 1
        assert "- 地政学入門 — 積読" in text

        assert note not in rebuild(db)
        assert note.read_text(encoding="utf-8") == text

    def test_replaces_only_the_real_pair_after_the_example(self, db, shelf, themes, example):
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", f"{example}\n{_REAL_BLOCK}\n末尾\n")

        written = rebuild(db)

        text = note.read_text(encoding="utf-8")
        assert note in written
        assert text.startswith(example + "\n" + START + "\n## このテーマの本")
        assert text.endswith(f"{END}\n末尾\n")
        assert "古い一覧" not in text
        assert "- 地政学入門 — 積読" in text

        assert note not in rebuild(db)
        assert note.read_text(encoding="utf-8") == text


class TestUnclosedCodeBlocks:
    @pytest.mark.parametrize("original", [
        f"- ```\n  メモ\n\n{START}\n古い一覧\n{END}\n",         # リストの行で開いたフェンスが閉じない
        f"\t```\n{START}\n古い一覧\n{END}\n",                   # タブ字下げのフェンスが閉じない
        f"<!--\n下書き\n\n{START}\n古い一覧\n{END}\n",           # コメントが閉じない
        "```js\nコードの途中\n",
    ], ids=["list_fence", "tab_fence", "html_comment", "fence_without_markers"])
    def test_does_not_touch_a_note_with_something_left_open(self, db, shelf, themes, original):
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", original)

        written = rebuild(db)

        assert note not in written
        assert note.read_text(encoding="utf-8") == original

    def test_a_one_line_html_comment_does_not_hide_what_follows(self, db, shelf, themes):
        # 1行で閉じたコメント（マーカー自身も1行のコメント）は、複数行コメントの開きではない
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", f"<!-- メモ -->\n{_REAL_BLOCK}\n末尾\n")

        rebuild(db)

        text = note.read_text(encoding="utf-8")
        assert text.startswith(f"<!-- メモ -->\n{START}\n## このテーマの本")
        assert "古い一覧" not in text
        assert "- 地政学入門 — 積読" in text


class TestAppendingKeepsTheEndOfTheUsersText:
    def test_keeps_the_trailing_spaces_that_make_a_markdown_line_break(self, db, shelf, themes):
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", "# 地政学\n\n最後の行  \n\n \n\n")

        rebuild(db)

        assert note.read_text(encoding="utf-8").startswith("# 地政学\n\n最後の行  \n\n" + START + "\n")

    def test_drops_only_trailing_blank_lines_when_the_note_is_blank(self):
        assert theme_store.replace_block("  \n\n", "一覧") == "一覧\n"


class TestLineBreaksInTitlesAndAuthors:
    @pytest.mark.parametrize("raw", [
        "\n", "\r", "\r\n", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", " ", " ",
    ], ids=["LF", "CR", "CRLF", "VT", "FF", "FS", "GS", "RS", "NEL", "LS", "PS"])
    def test_escape_text_turns_a_line_break_into_one_space(self, raw):
        assert theme_store.escape_text(f"上{raw}下") == "上 下"
        assert len(theme_store.escape_text(f"上{raw}{raw}下").splitlines()) == 1

    def test_escape_text_escapes_the_tilde_that_would_open_a_fence_at_the_head_of_a_list_item(self):
        assert theme_store.escape_text("~~~ 巻末") == r"\~\~\~ 巻末"

    @pytest.mark.parametrize("title, author", [
        ("本A\n~~~", "著者"),
        ("本A\r\n下巻", "著者"),
        ("本A", "著者\r"),
        ("本A", "著者\n~~~"),
        ("本A \x85下巻", "著者"),
        ("本A\n- 本物のようで偽の本", "著者"),
    ])
    def test_a_title_or_author_with_line_breaks_stays_one_list_line_and_does_not_stop_the_note(
            self, db, shelf, themes, title, author):
        shelf.add(title, author=author, tags=["仏教"])
        note = write_note(themes, "仏教.md", "# 仏教\n\n自分のメモ\n")

        written = rebuild(db)

        text = note.read_text(encoding="utf-8")
        assert note in written
        assert text.startswith("# 仏教\n\n自分のメモ\n\n" + START)
        assert len([l for l in text.split("\n") if l.startswith("- ")]) == 1
        # 2回目は何も書かない（CR が残っていると、読み戻した内容が毎回違って見える）
        assert note not in rebuild(db)
        assert note.read_text(encoding="utf-8") == text

        # 以後も更新が止まらない（開きっぱなしのフェンスで END が隠れていない）
        shelf.add("本B", tags=["仏教"])
        assert note in rebuild(db)
        assert "- 本B — 積読" in note.read_text(encoding="utf-8")


class TestSelfCheckBeforeWriting:
    def test_does_not_write_a_block_that_would_open_a_fence_and_warns_once(self, caplog):
        path = Path("/notes/仏教.md")
        original = "# 仏教\n\n自分のメモ\n"
        bad = theme_store.wrap_block(["- 本A", "~~~", "- 本B"])    # END が開きっぱなしのフェンスに隠れる
        good = theme_store.wrap_block(["- 本A"])

        with caplog.at_level(logging.WARNING, logger="app.theme_store"):
            assert theme_store.fill_block(path, original, bad) is None
            assert theme_store.fill_block(path, original, bad) is None
            assert len(caplog.records) == 1
            assert str(path) in caplog.records[0].getMessage()

            # 直れば書ける。警告済みの覚えも外れ、また壊れたらもう1回警告する
            assert theme_store.fill_block(path, original, good) == f"{original}\n{good}\n"
            assert theme_store.fill_block(path, original, bad) is None
            assert len(caplog.records) == 2

    def test_does_not_write_a_block_that_opens_an_html_comment(self):
        block = theme_store.wrap_block(["<!-- 閉じ忘れ"])
        assert theme_store.fill_block(Path("/notes/仏教.md"), "メモ\n", block) is None

    def test_leaves_a_note_alone_when_its_tag_would_open_a_fence_in_the_list(self, db, shelf, themes, caplog):
        # 集めるタグはコメントの行に生で書く。frontmatter のタグに改行があると、その次の行が
        # コメントの外に出て、フェンスを開いてしまう
        original = '---\ntags: ["a -->\\n~~~"]\n---\n自分のメモ\n'
        note = write_note(themes, "仏教.md", original)

        with caplog.at_level(logging.WARNING, logger="app.theme_store"):
            written = rebuild(db)
            rebuild(db)

        assert note not in written
        assert note.read_text(encoding="utf-8") == original
        assert (themes / HUB_NAME).is_file()      # 他のノートやハブは書かれる
        assert len([r for r in caplog.records if str(note) in r.getMessage()]) == 1


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


class TestConcurrentEditsInObsidian:
    # Obsidian はロックを取らないので、アプリが読んでから置き換えるまでの間にも保存しうる。
    # その瞬間を、write_atomic の呼び出しの手前で書き換えて再現する。

    @staticmethod
    def edit_once_before_writing(monkeypatch, target, edit):
        write_atomic = report_store.write_atomic
        edited = []

        def write_after_the_user_saved(path, text, **kwargs):
            if path == target and not edited:
                edited.append(True)
                edit()
            return write_atomic(path, text, **kwargs)

        monkeypatch.setattr(report_store, "write_atomic", write_after_the_user_saved)

    def test_keeps_a_paragraph_the_user_saved_after_the_note_was_read(self, db, shelf, themes, monkeypatch):
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", "# 地政学\n\n古いメモ\n")
        saved = "# 地政学\n\n古いメモ\n\nいま書いた大事な段落\n"
        self.edit_once_before_writing(monkeypatch, note, lambda: note.write_text(saved, encoding="utf-8"))

        written = rebuild(db)

        assert note not in written
        assert note.read_text(encoding="utf-8") == saved
        assert not list(themes.glob("*.tmp"))

        # 次の回は、保存された段落を残したまま一覧を足す
        assert note in rebuild(db)
        text = note.read_text(encoding="utf-8")
        assert text.startswith(saved + "\n" + START)
        assert "- 地政学入門 — 積読" in text

    def test_keeps_a_note_the_user_saved_with_the_same_length_by_its_mtime(self, db, shelf, themes, monkeypatch):
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", "メモA\n")

        def save_same_size():
            note.write_text("メモB\n", encoding="utf-8")
            stat = note.stat()
            os.utime(note, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))

        self.edit_once_before_writing(monkeypatch, note, save_same_size)

        assert note not in rebuild(db)
        assert note.read_text(encoding="utf-8") == "メモB\n"

    def test_does_not_bring_back_a_note_the_user_deleted_meanwhile(self, db, shelf, themes, monkeypatch):
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", "")
        self.edit_once_before_writing(monkeypatch, note, note.unlink)

        assert note not in rebuild(db)
        assert not note.exists()

    def test_does_not_overwrite_a_hub_the_user_created_meanwhile(self, db, shelf, themes, monkeypatch):
        hub = themes / HUB_NAME
        mine = "# 自分で作ったテーマ一覧\n"
        self.edit_once_before_writing(monkeypatch, hub, lambda: hub.write_text(mine, encoding="utf-8"))

        assert hub not in rebuild(db)
        assert hub.read_text(encoding="utf-8") == mine
        assert not list(themes.glob("*.tmp"))

        # 次の回は、ユーザーのハブに一覧を足す
        assert hub in rebuild(db)
        assert hub.read_text(encoding="utf-8").startswith(mine + "\n" + START)


class TestScanNotes:
    def test_skips_only_the_entry_it_cannot_inspect(self, themes):
        write_note(themes, "あ.md", "")
        write_note(themes, "う.md", "")
        os.symlink("い.md", themes / "い.md")                       # 自分を指す（ELOOP）
        os.symlink("存在しない.md", themes / "え.md")               # 先が無い

        assert [note.path.name for note in theme_store.scan_notes(themes)] == ["あ.md", "う.md"]

    def test_other_notes_and_the_hub_are_still_written_next_to_a_broken_symlink(self, db, shelf, themes):
        shelf.add("地政学入門", tags=["地政学"])
        note = write_note(themes, "地政学.md", "")
        os.symlink("loop.md", themes / "loop.md")

        written = rebuild(db)

        assert note in written
        assert "- 地政学入門 — 積読" in note.read_text(encoding="utf-8")
        assert themes / HUB_NAME in written

    def test_a_missing_directory_has_no_notes(self, tmp_path):
        assert theme_store.scan_notes(tmp_path / "無い") == []

    def test_raises_when_the_directory_cannot_be_read(self, tmp_path):
        # 「ノート0件」ではなく失敗にする（ウォッチャーが記録して、その回は何も書かない）
        not_a_directory = tmp_path / "themes"
        not_a_directory.write_text("", encoding="utf-8")

        with pytest.raises(OSError):
            theme_store.scan_notes(not_a_directory)


class TestOneFailureDoesNotStopTheJob:
    def make_unwritable(self, note):
        # tmp の名前をディレクトリで塞ぐと、その1ファイルだけ書き込みに失敗する
        (note.parent / (note.name + report_store.TMP_SUFFIX)).mkdir()

    def test_writes_the_other_notes_and_the_hub_and_warns_once(self, db, shelf, themes, caplog):
        shelf.add("本", tags=["あ", "い", "う"])
        first = write_note(themes, "あ.md", "")
        broken = write_note(themes, "い.md", "")
        last = write_note(themes, "う.md", "")
        self.make_unwritable(broken)

        def warnings():
            return [r for r in caplog.records
                    if r.levelno == logging.WARNING and str(broken) in r.getMessage()]

        with caplog.at_level(logging.WARNING, logger="app.theme_store"):
            written = rebuild(db)
            rebuild(db)

        assert set(written) == {first, last, themes / HUB_NAME}
        assert broken.read_text(encoding="utf-8") == ""
        assert len(warnings()) == 1

        # 直れば次の回で書ける。警告済みの覚えも外れ、また書けなくなればもう1回警告する
        (themes / "い.md.tmp").rmdir()
        with caplog.at_level(logging.WARNING, logger="app.theme_store"):
            assert broken in rebuild(db)
            assert len(warnings()) == 1

            broken.write_text("", encoding="utf-8")
            self.make_unwritable(broken)
            rebuild(db)
            rebuild(db)
            assert len(warnings()) == 2

    def test_does_not_count_a_skipped_note_as_recovered(self, db, shelf, themes, caplog):
        # 書いている最中として飛ばした回は、書き込みを試していない。警告済みの覚えを外さない
        shelf.add("本", tags=["い"])
        broken = write_note(themes, "い.md", "")
        self.make_unwritable(broken)

        with caplog.at_level(logging.WARNING, logger="app.theme_store"):
            rebuild(db)
            theme_store.rebuild(db, quiet_seconds=60)      # 直近に更新されたので飛ばす
            rebuild(db)

        assert len([r for r in caplog.records if str(broken) in r.getMessage()]) == 1


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

    def test_a_job_without_a_name_does_not_stop_the_others(self, session_factory):
        # functools.partial は __name__ を持たない。名前づくりで落ちて、後ろのジョブまで止めない
        calls = []

        def labeled_job(db, label):
            calls.append(label)
            return []

        def plain_job(db):
            calls.append("plain")
            return []

        watcher = theme_store.ThemeWatcher(
            session_factory, jobs=[functools.partial(labeled_job, label="partial"), plain_job])
        watcher._tick()

        assert calls == ["partial", "plain"]

    def test_logs_a_failing_job_without_a_name_once_and_keeps_going(self, session_factory, caplog):
        calls = []

        def failing_job(db, label):
            raise RuntimeError("同じ失敗")

        def healthy_job(db):
            calls.append("healthy")
            return []

        watcher = theme_store.ThemeWatcher(
            session_factory, jobs=[functools.partial(failing_job, label="partial"), healthy_job])
        with caplog.at_level(logging.ERROR, logger="app.theme_store"):
            watcher._tick()
            watcher._tick()

        assert calls == ["healthy", "healthy"]
        assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1


# ── 一括作成（scripts/create_notes.py が使う部品）──────────────────

def settle(path, age=60):
    """ノートの更新時刻を `age` 秒前にする（直近に更新されたノートとして待たれないように）。"""
    mtime = time.time() - age
    os.utime(path, (mtime, mtime))


class TestNoteStem:
    @pytest.mark.parametrize("tag, expected", [
        ("日本史/近代", "日本史近代"),
        ("x:y", "xy"),
        ("C#", "C"),
        ("a  b", "a b"),
        (".隠れ", "隠れ"),
        (". .a", "a"),
    ])
    def test_ファイル名に使えない文字を落とす(self, tag, expected):
        assert theme_store.note_stem(tag) == expected

    @pytest.mark.parametrize("invisible", ["​", "⁠", "­", "﻿"])
    def test_見えない書式文字を落とす(self, invisible):
        assert theme_store.note_stem(f"{invisible}地政{invisible}学{invisible}") == "地政学"

    @pytest.mark.parametrize("tag", ["ＳＦ", "ｶﾞｲﾄﾞ", "Ａ１"])
    def test_NFKCをかけない(self, tag):
        # テーマの照合はタグ名の完全一致。表記を変えるとノートに tags を書かないと集められない
        assert theme_store.note_stem(tag) == tag

    @pytest.mark.parametrize("tag", ["...", "#^[]", "́́", "​", "   "])
    def test_使える文字が無ければ空になる(self, tag):
        assert theme_store.note_stem(tag) == ""

    def test_絵文字だけのタグはファイル名にできる(self):
        assert theme_store.note_stem("📚") == "📚"

    def test_UTF8で200バイトまでに文字の途中で切らずに収める(self):
        stem = theme_store.note_stem("a" + "あ" * 100)

        # 200 バイト目は「あ」(3バイト)の途中。途中の文字は捨てて 199 バイトになる
        assert stem == "a" + "あ" * 66
        assert len(stem.encode("utf-8")) == 199

    def test_切り詰めた末尾が空白ならその空白も落とす(self):
        # 200 バイト目がちょうど空白。ファイル名の末尾に空白を残さない
        assert theme_store.note_stem("a" * 199 + " あ") == "a" * 199


class TestNewNoteText:
    def test_ファイル名とタグが同じならtagsを書かない(self):
        text = theme_store.new_note_text("地政学", "地政学")

        meta, body = report_store.split_front_matter(text)
        assert meta == {"type": "theme-note"}
        assert body == "\n# 地政学\n"

    def test_ファイル名とタグが違えばtagsにタグ名だけを書く(self):
        text = theme_store.new_note_text("日本史/近代", "日本史近代")

        meta, body = report_store.split_front_matter(text)
        assert meta == {"type": "theme-note", "tags": ["日本史/近代"]}
        assert body == "\n# 日本史/近代\n"

    @pytest.mark.parametrize("tag, stem, heading", [
        ("C#", "C", "# C\\#"),
        ("*a*", "a", "# \\*a\\*"),
    ])
    def test_見出しは記号をエスケープしたタグ名にする(self, tag, stem, heading):
        # 生で書くと、Obsidian では # がタグ・* が強調になり、見出しがタグ名どおりに読めない
        text = theme_store.new_note_text(tag, stem)

        assert text.endswith(f"\n{heading}\n")


class TestPlanNewNotes:
    def plan(self, db, themes):
        books = list(db.scalars(select(Book).options(selectinload(Book.tags)).order_by(Book.id)))
        return theme_store.plan_new_notes(themes, books, report_store.report_paths(),
                                          theme_store.scan_notes(themes))

    def test_計画は何も書かない(self, db, shelf, themes):
        shelf.add("地政学入門", tags=["地政学", "日本史/近代"])

        plan = self.plan(db, themes)

        assert [p.note.path.name for p in plan.notes] == ["地政学.md", "日本史近代.md"]
        assert list(themes.iterdir()) == []

    def test_既に集められているタグはalreadyに入る(self, db, shelf, themes):
        shelf.add("本1", tags=["日本史", "世界史", "経済"])
        write_note(themes, "歴史.md", "---\ntags: [日本史, 世界史]\n---\n")

        plan = self.plan(db, themes)

        assert plan.already == ["世界史", "日本史"]
        assert [p.tag for p in plan.notes] == ["経済"]
        assert plan.skipped == []

    def test_壊れたsymlinkと同じ名前のタグは作らない(self, db, shelf, themes):
        shelf.add("本1", tags=["地政学"])
        os.symlink("存在しない.md", themes / "地政学.md")

        plan = self.plan(db, themes)

        assert plan.notes == []
        assert plan.skipped == [("地政学", "地政学.md が既にある（テーマノートとして読めないファイル）")]

    @pytest.mark.parametrize("tags, owner, other", [
        (["C#", "C"], "C", "C#"),
        # タグ順では「日本史/近代」が先。ファイル名と一致する「日本史近代」が日本史近代.md を取る
        (["日本史/近代", "日本史近代"], "日本史近代", "日本史/近代"),
    ])
    def test_同じファイル名になるタグはファイル名と一致するほうを先に作る(self, db, shelf, themes, tags, owner, other):
        shelf.add("本1", tags=tags)

        plan = self.plan(db, themes)

        assert [p.tag for p in plan.notes] == [owner]
        assert plan.skipped == [(other, f"{plan.notes[0].note.path.name} はこの回に「{owner}」のノートとして作る")]
        assert theme_store.theme_tags(
            report_store.split_front_matter(plan.notes[0].text)[0], plan.notes[0].note.path.stem) == (owner,)

    def test_一覧がフェンスを開いてしまうタグは作らずに理由を出す(self, db, shelf, themes):
        # 集めるタグはコメントの行に生で書く。タグに改行があると、次の行がコメントの外に出てフェンスを開く
        tag = "a -->\n~~~"
        shelf.add("本1", tags=[tag, "地政学"])

        plan = self.plan(db, themes)

        assert [p.tag for p in plan.notes] == ["地政学"]
        assert plan.skipped == [(tag, "一覧を書くとマーカーを読み戻せない（タグ名や書名の文字のため）")]

    @pytest.mark.parametrize("tag", ["a\rb", "a\r\nb"])
    def test_CRを含むタグは読み戻すと内容が変わるので作らずに理由を出す(self, db, shelf, themes, tag):
        # CR は read_text が LF に直す。書いた内容と読み戻した内容が違うと、アプリが毎回書き直す
        shelf.add("本1", tags=[tag, "地政学"])

        plan = self.plan(db, themes)

        assert [p.tag for p in plan.notes] == ["地政学"]
        assert plan.skipped == [
            (tag, "一覧に CR の文字が入り、書いた内容が読み戻すと変わる（タグ名や書名の文字のため）")]

    @pytest.mark.parametrize("tag", ["x -->\r~~~", "-->\r<!-- notes:books:end -->\ry"])
    def test_CRで行が分かれてマーカーを隠すタグは作らずに理由を出す(self, db, shelf, themes, tag):
        # 書く前の文字列は1行に見えるが、読み戻すと CR で行が分かれ、フェンスが開く・END が増える
        shelf.add("本1", tags=[tag, "地政学"])

        plan = self.plan(db, themes)

        assert [p.tag for p in plan.notes] == ["地政学"]
        assert plan.skipped == [(tag, "一覧を書くとマーカーを読み戻せない（タグ名や書名の文字のため）")]

    def test_作らないタグは理由が出た段階によらずタグ順に並ぶ(self, db, shelf, themes):
        # 「\u0301」は計画の段階で、「a\rb」は一覧を作ったあとの検証で外れる。後者のほうが先に並ぶタグ
        shelf.add("本1", tags=["\u0301", "a\rb"])

        plan = self.plan(db, themes)

        assert [tag for tag, _ in plan.skipped] == ["a\rb", "\u0301"]

    def test_alreadyはタグ順に並ぶ(self, db, shelf, themes):
        # 「a/」はファイル名にすると別の名前になるので、計画ではあとに回る。並びはタグ順
        shelf.add("本1", tags=["b", "a/"])
        write_note(themes, "歴史.md", "---\ntags: [b, a/]\n---\n")

        plan = self.plan(db, themes)

        assert plan.already == ["a/", "b"]

    def test_NFCとNFDだけが違うタグはファイル名が重なるので片方だけ作る(self, db, shelf, themes):
        # 見た目が同じ名前が2つ並ぶ。macOS / iOS のファイルシステムは区別せず、同期すると衝突する
        nfc = unicodedata.normalize("NFC", "ガイド")
        nfd = unicodedata.normalize("NFD", "ガイド")
        assert nfc != nfd
        shelf.add("本1", tags=[nfc, nfd])

        plan = self.plan(db, themes)

        assert len(plan.notes) == 1
        assert [tag for tag, _ in plan.skipped] == [t for t in (nfc, nfd) if t != plan.notes[0].tag]
        assert "Unicode の正規化（NFC）で同じ名前になる" in plan.skipped[0][1]

    def test_既存のノートとNFCで同じ名前になるタグは作らない(self, db, shelf, themes):
        nfc = unicodedata.normalize("NFC", "ガイド")
        nfd = unicodedata.normalize("NFD", "ガイド")
        shelf.add("本1", tags=[nfc])
        write_note(themes, f"{nfd}.md", "# メモ\n")    # macOS から同期されたような NFD の名前

        plan = self.plan(db, themes)

        assert plan.notes == []
        assert [tag for tag, _ in plan.skipped] == [nfc]
        assert "Unicode の正規化（NFC）で同じ名前になる" in plan.skipped[0][1]

    def test_UTF8でない名前のノートが一覧に入るタグは作らずに理由を出す(self, db, shelf, themes):
        # UTF-8 でないバイトの名前（文字コードの違う zip の展開など）は、読むとサロゲートの文字になる。
        # 一覧のリンクに入ると、書くときに UnicodeEncodeError で落ちて一時ファイルが残る
        shelf.add("本1", tags=["T", "U"])
        shelf.add("本2", tags=["V"])
        bad = os.path.join(os.fsencode(themes), b"caf\xe9.md")
        try:
            with open(bad, "wb") as handle:
                handle.write("---\ntags: [T]\n---\n".encode())
        except OSError:
            pytest.skip("このファイルシステムは UTF-8 でない名前のファイルを作れない")

        plan = self.plan(db, themes)

        # 本1を共有する U は、T を集めるノートを「関連するテーマ」に出すので作れない。V は関係ない
        assert [p.tag for p in plan.notes] == ["V"]
        assert plan.skipped == [("U", theme_store.UNENCODABLE_REASON)]
        assert all(theme_store.can_encode(p.text) for p in plan.notes)


class TestCanEncode:
    def test_ふつうの文字は書ける(self):
        assert theme_store.can_encode("地政学 café 📚\r\n") is True

    def test_UTF8でないバイトの名前から来るサロゲートは書けない(self):
        assert theme_store.can_encode(os.fsdecode(b"caf\xe9")) is False


class TestUnsettledReason:
    @pytest.mark.parametrize("content, age, expected", [
        (b"", 60, "空のファイル"),
        (b"\n  \n", 60, "空のファイル"),
        ("---\ntags: [歴史]\n\n# 歴史\n".encode(), 60, "frontmatter を解釈できない"),
        ("---\ntags: [歴史, \n---\n".encode(), 60, "frontmatter を解釈できない"),
        # BOM つきでも frontmatter として読む（utf-8-sig）
        (b"\xef\xbb\xbf" + "---\ntags: [歴史, \n---\n".encode(), 60, "frontmatter を解釈できない"),
        # 正しく閉じた空の frontmatter（Obsidian のプロパティを全部消すとできる）も待つ。解釈できた
        # 辞書が空なのか、壊れているのか、ここでは見分けない
        ("---\n---\n自分のメモ\n".encode(), 60, "frontmatter を解釈できない"),
        (b"---\ntags: [H\xff]\n---\n", 60, "読めない（UnicodeDecodeError）"),
        ("# 歴史\n".encode(), 0, "直近に更新された"),
        ("# 歴史\n".encode(), -5, "直近に更新された"),   # mtime が now より少し先（保存の途中）
    ])
    def test_編集途中や壊れたノートがあれば理由を返す(self, themes, content, age, expected):
        path = themes / "歴史.md"
        path.write_bytes(content)
        settle(path, age)

        reason = theme_store.unsettled_reason(themes, time.time(), 10.0)

        assert reason == f"歴史.md: {expected}"

    def test_怪しいノートが複数あれば名前順で最初のものを返す(self, themes):
        for name in ["a.md", "b.md", "c.md", "d.md", "e.md", "f.md"]:
            settle(write_note(themes, name, ""))

        assert theme_store.unsettled_reason(themes, time.time(), 10.0) == "a.md: 空のファイル"

    def test_更新時刻が大きく先のノートは待たない(self, themes):
        # 同期のずれなどで1分以上先の mtime のノートを待ち続けると、永久に作れない（update_file と同じ）
        settle(write_note(themes, "歴史.md", "# 歴史\n"), age=-3600)

        assert theme_store.unsettled_reason(themes, time.time(), 10.0) is None

    def test_ハブと隠しファイルは見ない(self, themes):
        for name in [HUB_NAME, ".下書き.md", "メモ.txt"]:
            write_note(themes, name, "")           # 空で、いま書いたばかり
        (themes / "サブ").mkdir()
        write_note(themes / "サブ", "歴史.md", "")

        assert theme_store.unsettled_reason(themes, time.time(), 10.0) is None

    @pytest.mark.parametrize("content", ["---\ntags: [歴史]\n---\n\n# 歴史\n", "# 歴史\n\n自分のまとめ。\n"])
    def test_落ち着いたノートだけなら理由は無い(self, themes, content):
        settle(write_note(themes, "歴史.md", content))
        settle(write_note(themes, "地政学.md", "# 地政学\n"))

        assert theme_store.unsettled_reason(themes, time.time(), 10.0) is None

    def test_壊れたsymlinkはノートではないので待たない(self, themes):
        os.symlink("存在しない.md", themes / "歴史.md")

        assert theme_store.unsettled_reason(themes, time.time(), 10.0) is None

    def test_フォルダが無ければ理由は無い(self, tmp_path):
        assert theme_store.unsettled_reason(tmp_path / "無い", time.time(), 10.0) is None

    def test_フォルダを開けなければ例外を上げる(self, tmp_path):
        # 「怪しいノートは無い」ではなく失敗にする（呼び出し側が受けて作るのをやめる）
        not_a_directory = tmp_path / "themes"
        not_a_directory.write_text("", encoding="utf-8")

        with pytest.raises(OSError):
            theme_store.unsettled_reason(not_a_directory, time.time(), 10.0)


class TestCreateFile:
    def test_無ければ作る(self, themes):
        path = themes / "地政学.md"

        assert theme_store.create_file(path, "# 地政学\n", 10.0, time.time()) is True

        assert path.read_text(encoding="utf-8") == "# 地政学\n"
        assert not (themes / ("地政学.md" + report_store.TMP_SUFFIX)).exists()

    def test_既にあれば上書きしない(self, themes):
        path = write_note(themes, "地政学.md", "ユーザーの本文\n")
        settle(path)

        assert theme_store.create_file(path, "# 地政学\n", 10.0, time.time()) is False

        assert path.read_text(encoding="utf-8") == "ユーザーの本文\n"
