"""テーマノート（`reports/themes/*.md`）に「このテーマの本」の一覧を差し込むストア

テーマノートは、タグ（または複数のタグ）ごとに本をまたいで考えをまとめるノート。
**本文はユーザーが Obsidian で書く**。アプリが書くのは、マーカー

    <!-- notes:books:start --> … <!-- notes:books:end -->

で囲んだ一覧の部分だけで、その外には触れない。一覧は各レポートへの相対 Markdown
リンクなので、Obsidian ではレポート側のバックリンクにテーマノートが出て、グラフでも
つながる（相互リンク）。レポートがまだ無い本もリンクなしで並べる（DB にしか無い情報）。

- **どの本を集めるか**: ノートの frontmatter の `tags`（どれか1つでも持つ本）。
  `tags` が無ければファイル名をタグ名とみなす（`themes/地政学.md` を作るだけでよい）。
- **ノートを作るのはユーザー**。アプリはタグごとのノートを勝手に作らない。
  例外はハブ `themes/テーマ一覧.md` で、全テーマノートとノートのまだ無いタグを並べる
  全体の入口として、無ければアプリが作る。いまあるタグのノートを一括で作るときだけ、
  ユーザーが `scripts/create_notes.py` を流す（設計: docs/design/0003-bulk-create-notes.md）。
- **書き直すのは中身が変わったときだけ**（mtime を動かさない）。さらに、直近
  `QUIET_SECONDS` 秒以内に更新されたノートは、Obsidian で書いている最中かもしれないので
  その回は飛ばす（次の回で入る）。mtime が `QUIET_SECONDS` 秒以上未来のノートは
  （同期のずれなど）飛ばさず書く。
- マーカーは行全体がマーカーだけの行（行頭の空白は3個まで。アプリは常に行頭に書くので、
  タブや4個以上の字下げは字下げのコードブロックとみなして数えない）に限り、コードフェンスと
  複数行の HTML コメントの中は無視する（使い方の例として書いたマーカーを本物と取り違えない）。
  マーカーが壊れている（片方だけ・複数ある・順序が逆・フェンスやコメントが閉じていない）ノート
  は触らず、警告を1回だけ出す。
- **書く前に読み直す**: 書こうとする全文を同じ規則で読み直し、マーカーの組がちょうど1つ見え
  ないなら書かない（書名などに紛れた文字が、アプリ自身でフェンスを開いて以後そのノートを
  止めてしまうのを防ぐ）。

更新は `ThemeWatcher` が数秒ごとに `rebuild()` を呼んで行う。ルーターから呼び出しを
差し込まないのは、Obsidian でノートを作った・タグを書き換えたといった、アプリの API を
通らない変化も拾う必要があるため。毎回 DB から全冊を引くが、100冊程度なら軽い。

書き込みはレポートと同じロック（`reports/.write.lock`）と原子的な置き換えを使う。ただし
Obsidian はこのロックを取らないので、読んでから置き換えるまでの間にユーザーが保存したら、
置き換えずにその回は諦める（`report_store.write_atomic` の `expect`。次の回でやり直す）。
1ファイルの書き込み失敗でジョブ全体は止めず、パスごとに警告を1回だけ出して続ける。

ここの `escape_text` / `md_link` / `wrap_block` / `update_file` / `create_file` / `book_sections` /
`replace_block` / `fill_block` / `front_matter_doubt` / `can_encode` は著者ノート（`author_store.py`）も使う共有部品。
`ThemeWatcher` も、テーマと著者の両方のジョブをまとめて数秒ごとに回す。
"""

import logging
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import report_store
from .models import Book, BookStatus

logger = logging.getLogger(__name__)

THEMES_DIRNAME = "themes"
HUB_NAME = "テーマ一覧.md"
NOTE_TYPE = "theme-note"
START = "<!-- notes:books:start -->"
END = "<!-- notes:books:end -->"
# この秒数以内に更新されたノートは、書いている最中とみなしてその回は飛ばす
QUIET_SECONDS = 10.0
INTERVAL_SECONDS = 5.0

_SPACES = re.compile(r"\s+")
_FRONT_MATTER_OPEN = re.compile(r"---[ \t]*(?:\r?\n|\Z)")   # 先頭の行が `---` だけ（match で使う）
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f\x7f]')   # ファイル名・Obsidian のリンクで困る文字
_STEM_BYTES = 200                              # ファイル名の上限（UTF-8 で 255 バイト未満に収める）

_STATUS_LABEL = {
    BookStatus.READING: "読書中",
    BookStatus.FINISHED: "読了",
    BookStatus.UNREAD: "積読",
}
# レポートの無い本は、読書中 → 読了 → 積読 の順に並べる
_STATUS_ORDER = {BookStatus.READING: 0, BookStatus.FINISHED: 1, BookStatus.UNREAD: 2}

# 一覧の文字に紛れると Markdown や Obsidian の記法になってしまう文字
# （`#` はタグ、`[` `]` はリンク、`*` `_` は強調、`~` は取り消し線。`~~~` で始まる書名は
# 行頭が `- ~~~` になり、コードフェンスの開きになる）。
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]<>#|~])")
# 行区切りになる文字（`str.splitlines()` が区切るもの）。書名や著者欄に紛れると一覧が複数行になる。
_LINE_BREAKS = re.compile(r"[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]+")
# リンク先に生で書くとリンクが壊れる文字。Obsidian は % エンコードを解釈する。
_LINK_ESCAPES = {"%": "%25", " ": "%20", "(": "%28", ")": "%29", "#": "%23", "<": "%3C", ">": "%3E"}

HUB_HEADER = """---
type: theme-hub
---

# テーマ一覧

テーマノートの入口。このフォルダ（`themes/`）に「タグ名.md」を作ると、そのタグの本の一覧が
数秒で入る。複数のタグをまとめたいときは、ノートの frontmatter に `tags: [歴史, 地政学]` と書く。
ここにも自由に書いてよい（下の一覧の部分だけアプリが書き直す）。
"""


def themes_dir() -> Path:
    return report_store.reports_dir() / THEMES_DIRNAME


# ── テーマノートを読む ──────────────────────────────────────

@dataclass(frozen=True)
class ThemeNote:
    path: Path
    tags: tuple[str, ...]


def theme_tags(meta: dict, stem: str) -> tuple[str, ...]:
    """frontmatter の `tags` を集めるタグにする。無ければファイル名をタグ名とみなす。

    Obsidian は `tags: 地政学` / `tags: [地政学, 歴史]` / `#地政学` のどれでも書けるので
    全部受ける。
    """
    raw = meta.get("tags")
    if isinstance(raw, str):
        items = re.split(r"[,\s]+", raw)
    elif isinstance(raw, list):
        items = [str(item) for item in raw if item is not None]
    else:
        items = []
    tags: list[str] = []
    for item in items:
        name = item.strip().lstrip("#").strip()
        if name and name not in tags:
            tags.append(name)
    return tuple(tags) or (stem,)


def scan_notes(directory: Path) -> list[ThemeNote]:
    """`themes/` 直下のテーマノート（ハブと隠しファイルを除く）を名前順に返す。

    ディレクトリがまだ無いのは「ノート0件」。それ以外で読めないときは例外を上げる（0件と
    みなすと、ノートの一覧が全部つながりを失った状態で他のジョブが進んでしまう）。
    壊れた symlink（自分を指す・権限の無い先）など、種別を調べられない項目はその1件だけ飛ばす。
    """
    entries = []
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if (not entry.name.endswith(".md") or entry.name.startswith(".")
                        or entry.name == HUB_NAME):
                    continue
                try:
                    if entry.is_file():
                        entries.append(entry)
                except OSError:
                    continue
    except FileNotFoundError:
        return []
    notes = []
    for entry in sorted(entries, key=lambda e: e.name):
        path = Path(entry.path)
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        meta, _ = report_store.split_front_matter(text)
        notes.append(ThemeNote(path, theme_tags(meta, path.stem)))
    return notes


# ── 一覧を組み立てる ────────────────────────────────────────

def escape_text(text: str) -> str:
    """一覧の1行に入れる文字にする。記法になる文字はエスケープし、行区切りは空白1つにする。

    DB の書名・著者欄には改行が入りうる（コピー＆ペースト）。そのまま書くと一覧が複数行になり、
    次の行の頭が `~~~` なら、アプリ自身が開いたフェンスで END が隠れてノートが止まる。
    CR は `read_text` が LF に直すので、書いた内容が読み戻すたびに違って見え、毎回書き直す。
    """
    return _MARKDOWN_SPECIAL.sub(r"\\\1", _LINE_BREAKS.sub(" ", text))


def link_target(path: Path, start: Path) -> str:
    """`start` から見た `path` への相対リンク先（Obsidian でも vault の外でも同じ先に解決する）。"""
    relative = Path(os.path.relpath(path, start)).as_posix()
    return "".join(_LINK_ESCAPES.get(ch, ch) for ch in relative)


def md_link(text: str, path: Path, start: Path) -> str:
    return f"[{escape_text(text)}]({link_target(path, start)})"


def _book_line(book: Book, report: Optional[Path], start: Path, matched: list[str]) -> str:
    head = md_link(book.title, report, start) if report else escape_text(book.title)
    parts = []
    if book.author:
        parts.append(escape_text(book.author))
    status = _STATUS_LABEL.get(book.status, str(book.status))
    if book.status == BookStatus.FINISHED and book.finished_on:
        status += f" {book.finished_on.isoformat()}"
    parts.append(status)
    if book.rating:
        parts.append("★" * book.rating)
    if matched:
        parts.append("・".join(escape_text(tag) for tag in matched))
    return f"- {head} — {' · '.join(parts)}"


def _tag_names(book: Book) -> set[str]:
    return {tag.name for tag in book.tags}


def books_for(tags: tuple[str, ...], books: list[Book]) -> list[Book]:
    wanted = set(tags)
    return [book for book in books if _tag_names(book) & wanted]


def _report_order(book: Book) -> tuple:
    """レポートのある本は読了日の新しい順。読了日の無い本は後ろ。"""
    finished = book.finished_on or date.min
    return (book.finished_on is None, -finished.toordinal(), book.title)


def wrap_block(lines: list[str]) -> str:
    return "\n".join([START, *lines, END])


def book_sections(
    books: list[Book],
    reports: dict[int, Path],
    start: Path,
    matched_tags: Optional[Callable[[Book], list[str]]] = None,
) -> list[str]:
    """「N冊（レポートあり M冊）」と、レポートのある本・まだ無い本の節の行。

    テーマノートと著者ノートで同じ行の形にするための部品。`books` は空でない前提
    （空のときの文言はノートの種類ごとに違うので呼び出し側が出す）。
    `matched_tags` は、その本をどのタグで集めたかを添えたいときに渡す。
    """
    with_report = sorted((b for b in books if b.id in reports), key=_report_order)
    without_report = sorted(
        (b for b in books if b.id not in reports),
        key=lambda b: (_STATUS_ORDER.get(b.status, 9), b.title),
    )

    def tags_of(book: Book) -> list[str]:
        return matched_tags(book) if matched_tags else []

    lines = [f"{len(books)}冊（レポートあり {len(with_report)}冊）"]
    if with_report:
        lines += ["", "### レポートのある本", ""]
        lines += [_book_line(b, reports[b.id], start, tags_of(b)) for b in with_report]
    if without_report:
        lines += ["", "### まだレポートの無い本", ""]
        lines += [_book_line(b, None, start, tags_of(b)) for b in without_report]
    return lines


def theme_block(
    note: ThemeNote,
    books: list[Book],
    reports: dict[int, Path],
    notes: list[ThemeNote],
) -> str:
    """テーマノートに差し込む一覧（マーカー込み）。"""
    start = note.path.parent
    matched = books_for(note.tags, books)
    # 複数のタグを集めるノートでは、どのタグで入った本かを添える
    show_matched = len(note.tags) > 1

    def matched_tags(book: Book) -> list[str]:
        return [tag for tag in note.tags if tag in _tag_names(book)] if show_matched else []

    lines = [
        "## このテーマの本",
        "",
        f"<!-- ここから end まではアプリが DB のタグから書き直す（手で編集しない）。"
        f"集めるタグ: {'・'.join(note.tags)} -->",
        "",
    ]
    if not matched:
        lines.append(
            f"このタグの本はまだありません（集めるタグ: {'・'.join(escape_text(t) for t in note.tags)}）。"
            "集めるタグはノートの frontmatter の `tags` で変えられます。"
        )
    else:
        lines += book_sections(matched, reports, start, matched_tags)

    # 同じ本を共有している他のテーマノート。テーマどうしもグラフでつながる。
    mine = {b.id for b in matched}
    related = []
    for other in notes:
        if other.path == note.path:
            continue
        shared = mine & {b.id for b in books_for(other.tags, books)}
        if shared:
            related.append((len(shared), other))
    if related:
        related.sort(key=lambda pair: (-pair[0], pair[1].path.name))
        lines += ["", "### 関連するテーマ", ""]
        lines += [
            f"- {md_link(other.path.stem, other.path, start)} — 共通の本 {count}冊"
            for count, other in related
        ]
    return wrap_block(lines)


def hub_block(hub: Path, books: list[Book], reports: dict[int, Path], notes: list[ThemeNote]) -> str:
    """ハブ（テーマ一覧）に差し込む一覧（マーカー込み）。"""
    start = hub.parent
    lines = ["## テーマノート", ""]
    if notes:
        for note in notes:
            matched = books_for(note.tags, books)
            reported = sum(1 for b in matched if b.id in reports)
            lines.append(
                f"- {md_link(note.path.stem, note.path, start)} — "
                f"{'・'.join(escape_text(t) for t in note.tags)} · {len(matched)}冊（レポート {reported}）"
            )
    else:
        lines.append("まだありません。")

    covered = {tag for note in notes for tag in note.tags}
    counts: dict[str, list[Book]] = {}
    for book in books:
        for name in _tag_names(book):
            if name not in covered:
                counts.setdefault(name, []).append(book)
    lines += ["", "## ノートのまだ無いタグ", ""]
    if counts:
        for name, tagged in sorted(counts.items(), key=lambda item: (-len(item[1]), item[0])):
            reported = sum(1 for b in tagged if b.id in reports)
            lines.append(f"- {escape_text(name)} — {len(tagged)}冊（レポート {reported}）")
    else:
        lines.append("すべてのタグにノートがあります。")
    return wrap_block(lines)


# ── 差し込み ────────────────────────────────────────────────

# マーカーの行。行頭の空白は3個まで（4個以上・タブは字下げのコードブロックなので数えない。
# アプリは常に行頭に書く）。後ろの空白は可。
_START_LINE = re.compile(r" {0,3}" + re.escape(START) + r"\s*\Z")
_END_LINE = re.compile(r" {0,3}" + re.escape(END) + r"\s*\Z")

# コードフェンスの開き・閉じ（CommonMark）。マーカーの例を書いたフェンスの中は探さない。
# フェンスの前に付く引用 `>`・リスト記号（`-` `*` `+` `1.` `1)`）とタブ・字下げは、剥がしてから見る。
# Obsidian の既定ではリスト内のコードブロックはタブ字下げで、CommonMark の正確な規則
# （どこまでがフェンスか）を再現するより、広めにフェンスとみなして隠すほうが安全だから
# （隠しすぎた場合に起こるのは、一覧が足されない・重複して足されるだけで、ユーザーの文章は消えない）。
_CONTAINER_PREFIX = re.compile(r"[ \t]*(?:>|(?:[-*+]|\d+[.)])(?=[ \t]))")
_FENCE = re.compile(r"(`{3,}|~{3,})(.*)\Z")

# 壊れたマーカーを警告済みのパス。5秒ごとに同じ警告を出さないために覚えておく
# （直ったら外す。rebuild はウォッチャーの1スレッドから呼ぶので、ロックは要らない）
_warned_broken: set[Path] = set()
# 書き込めなかったパスの警告済み。同じ理由で毎回出さない（書けたら外す）
_warned_write_failed: set[Path] = set()


def _unwrap(line: str) -> str:
    """行頭の引用・リスト記号・空白とタブを剥がす（フェンスと HTML コメントの判定用）。"""
    while True:
        prefix = _CONTAINER_PREFIX.match(line)
        if prefix is None:
            return line.lstrip(" \t")
        line = line[prefix.end():]


def _fence_of(line: str) -> Optional[tuple[str, int, str]]:
    """フェンスの行なら（文字, 長さ, 後ろの文字列）。

    バッククォートのフェンスは、後ろの文字列にバッククォートを含まない（CommonMark）。
    "```js```" のような行はフェンスではなく文中のコード。
    """
    found = _FENCE.match(_unwrap(line))
    if found is None:
        return None
    ticks, rest = found.groups()
    if ticks[0] == "`" and "`" in rest:
        return None
    return ticks[0], len(ticks), rest


def _marker_lines(lines: list[str]) -> Optional[tuple[list[int], list[int]]]:
    """コードブロックの外にある START 行・END 行の番号。閉じていないものが残れば None。

    マーカーは行全体がマーカーだけの行（行頭の空白3個まで）に限る。文中やインラインコードで
    触れているだけのものは数えない。コードフェンスの中と、複数行の HTML コメント
    （`<!--` で始まり、同じ行で `-->` が閉じないもの）の中は無視する。

    コメントの中のマーカー行は、それ自体が `-->` を含むのでコメントを閉じる行とは見ない。
    例として書いたマーカーをコメントで囲んだつもりのユーザーは、素直に読むと最初のマーカー行で
    コメントが閉じて END だけが外に残り、触れなくなってしまうため。
    """
    starts: list[int] = []
    ends: list[int] = []
    fence: Optional[tuple[str, int]] = None   # 開いているフェンスの（文字, 長さ）
    in_comment = False
    for number, line in enumerate(lines):
        if fence is not None:
            closing = _fence_of(line)
            if (closing and closing[0] == fence[0] and closing[1] >= fence[1]
                    and not closing[2].strip()):
                fence = None
            continue
        is_start = _START_LINE.match(line) is not None
        is_end = _END_LINE.match(line) is not None
        if in_comment:
            if not (is_start or is_end) and "-->" in line:
                in_comment = False
            continue
        if is_start:
            starts.append(number)
            continue
        if is_end:
            ends.append(number)
            continue
        opening = _fence_of(line)
        if opening:
            fence = opening[:2]
            continue
        unwrapped = _unwrap(line)
        if unwrapped.startswith("<!--") and "-->" not in unwrapped[4:]:
            in_comment = True
    return None if fence is not None or in_comment else (starts, ends)


def _has_one_pair(text: str) -> bool:
    """`text` を読んだとき、コードブロックの外にマーカーの組がちょうど1つ見えるか。"""
    found = _marker_lines(text.split("\n"))
    if found is None:
        return False
    starts, ends = found
    return len(starts) == 1 and len(ends) == 1 and starts[0] < ends[0]


def replace_block(text: str, block: str) -> Optional[str]:
    """START 行から END 行までを `block` に差し替えた全文。マーカーが無ければ末尾に足す。

    マーカーが片方だけ・複数・順序が逆、またはコードフェンスや HTML コメントが閉じていない
    なら None（ユーザーの文章を壊さないよう触らない。閉じていないフェンスの中に足すと、
    次の回にまた足して増え続ける）。

    末尾に足すとき落とすのは、末尾の改行と空白だけの行まで。最後の文章の行末の空白
    （Markdown の改行になる半角スペース2つ）は残す。
    """
    lines = text.split("\n")
    found = _marker_lines(lines)
    if found is None:
        return None
    starts, ends = found
    if not starts and not ends:
        kept = list(lines)
        while kept and not kept[-1].strip():
            kept.pop()
        base = "\n".join(kept)
        return f"{base}\n\n{block}\n" if base else f"{block}\n"
    if len(starts) == 1 and len(ends) == 1 and starts[0] < ends[0]:
        return "\n".join(lines[:starts[0]] + [block] + lines[ends[0] + 1:])
    return None


def fill_block(path: Path, text: str, block: str) -> Optional[str]:
    """`replace_block` と同じ。書けないときは、そのパスにつき1回だけ警告を出す。

    書けないのは、マーカーが壊れているとき、または `block` を差し込んだ全文がマーカーの組を
    ちょうど1つとして読み戻せないとき（`block` の中身がフェンスやコメントを開いてしまう）。
    後者を書くと、そのノートは以後ずっと壊れたマーカーの扱いになって止まる。

    直ったら（文字列が返ったら）覚えを外すので、また壊れたらもう1回警告する。
    雛形（マーカーが無いと分かっているもの）には使わず、`replace_block` を直接呼ぶ。
    """
    new = replace_block(text, block)
    if new is None:
        reason = ("マーカーが壊れているので一覧を書かない（start と end を1組にするか、"
                  "閉じていないコードフェンスや HTML コメントを閉じると次の回で入る）")
    elif not _has_one_pair(new):
        new = None
        reason = ("一覧を書くとマーカーを読み戻せなくなるので書かない（一覧に入る書名・著者名・"
                  "タグの文字がコードフェンスなどを開いている。DB の値を直すと次の回で入る）")
    else:
        _warned_broken.discard(path)
        return new
    if path not in _warned_broken:
        _warned_broken.add(path)
        logger.warning("%s: %s", reason, path)
    return None


def update_file(path: Path, make_text: Callable[[Optional[str]], Optional[str]],
                quiet_seconds: float, now: float) -> bool:
    """ロックの中で読み直して書き換える。書いたら True。

    mtime が `now` から `quiet_seconds` 以内なら、書いている最中かもしれないので飛ばす。
    未来側も含めて見るのは、`now` を rebuild の始めに1回だけ取るため（途中で保存された
    ノートの mtime は `now` より少し先になる）。一方、`quiet_seconds` 以上先の mtime
    （同期のずれなど）まで飛ばすと、そのノートを永久に更新できなくなる。

    Obsidian はロックを取らない。読む前に調べた（mtime, サイズ）を `write_atomic` に渡し、
    置き換える直前にもう一度調べて違えば、ユーザーの保存を消さないよう書かずに False を返す
    （次の回でやり直す）。無かったファイルは「まだ無いはず」として作る。

    書き込みの OSError（tmp が作れない・権限など）は、パスごとに1回だけ警告して False を返す。
    1つのノートの失敗で、残りのノートやハブの更新（ジョブ全体）を止めないため。
    """
    with report_store.write_lock(report_store.reports_dir()):
        try:
            return _update_locked(path, make_text, quiet_seconds, now)
        except OSError as error:
            if path not in _warned_write_failed:
                _warned_write_failed.add(path)
                logger.warning("ノートを更新できなかったので飛ばす（次の回にまた試す）: %s: %s",
                               path, error)
            return False


def _update_locked(path: Path, make_text: Callable[[Optional[str]], Optional[str]],
                   quiet_seconds: float, now: float) -> bool:
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        current = None
        expect = report_store.ABSENT
    else:
        if abs(now - stat_result.st_mtime) < quiet_seconds:
            return False
        expect = (stat_result.st_mtime_ns, stat_result.st_size)
        try:
            current = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return False
    new = make_text(current)
    written = False
    if new is not None and new != current:
        written = report_store.write_atomic(path, new, expect=expect)
    # 例外なく書き込みまで進んだ（書く必要が無かった・条件が合わず諦めた場合も含む）ので、
    # 前の失敗は直ったとみなす
    _warned_write_failed.discard(path)
    return written


def create_file(path: Path, text: str, quiet_seconds: float, now: float) -> bool:
    """`path` が無いときだけ `text` で作る。作ったら True。

    既にある（ロックを取るまでに誰かが作った・Obsidian で作った）なら触らず False。
    新規作成は `write_atomic` の `ABSENT`（`os.link`）なので、直前にできた同名のファイルも
    上書きしない。書けない（OSError）ときも False（警告は `update_file` が出す）。
    """
    def make_new(current: Optional[str]) -> Optional[str]:
        return text if current is None else None

    return update_file(path, make_new, quiet_seconds, now)


# ── 一括作成（scripts/create_notes.py が使う）────────────────────

def note_stem(tag: str) -> str:
    """タグから作るテーマノートのファイル名（拡張子なし）。作れない名前なら空文字。

    書式文字と使えない文字を除き、空白を詰め、先頭・末尾の `.` を落とす（隠しファイルにしない）。
    長すぎれば UTF-8 で `_STEM_BYTES` バイトまでに切る（文字の途中では切らない）。
    文字・数字・句読点・記号（L/N/P/S）を1つも含まない名前（結合文字・空白だけ）はファイル名にしない。

    著者ノートの `author_store.note_stem` と違い NFKC はかけない。テーマの照合はタグ名の
    完全一致なので、表記を変えるとノートに `tags` を書かないと集められなくなる。
    記号（S）を許すのは、絵文字だけのタグも作れるようにするため。
    """
    kept = "".join(ch for ch in tag if unicodedata.category(ch) != "Cf")
    # 空白も一緒に落とすのは、`. .a` のように空白をはさんだ先頭の `.` を残さないため
    stem = _SPACES.sub(" ", _UNSAFE_NAME.sub("", kept)).strip(" .")
    stem = stem.encode("utf-8")[:_STEM_BYTES].decode("utf-8", errors="ignore").strip()
    if not any(unicodedata.category(ch)[0] in "LNPS" for ch in stem):
        return ""
    return stem


def new_note_text(tag: str, stem: str) -> str:
    """一括作成するテーマノートの雛形（マーカーはまだ無い）。

    ファイル名がタグと違うとき（使えない文字を落とした・切った）だけ `tags` を書く。
    書かないと、ファイル名をタグ名とみなす規則で別のタグを集めてしまう。
    """
    meta: dict = {"type": NOTE_TYPE}
    if stem != tag:
        meta["tags"] = [tag]
    return report_store.front_matter_text(meta) + f"\n# {escape_text(tag)}\n"


def front_matter_doubt(text: str, meta: dict) -> str:
    """読めたノートの frontmatter を信じてよいか。信じられない理由（信じてよければ空文字）。

    `---` で始まるのに frontmatter が解釈できないのは、書きかけか壊れているとき
    （`split_front_matter` は壊れていても例外にせず空の辞書を返すので、ここで見分ける）。
    著者ノートの aliases とテーマノートの tags の両方が、書きかけのノートを待つ判定に使う。
    """
    if not text.strip():
        return "空のファイル"
    if not meta and _FRONT_MATTER_OPEN.match(text):
        return "frontmatter を解釈できない"
    return ""


def unsettled_reason(directory: Path, now: float, quiet_seconds: float) -> Optional[str]:
    """テーマノートの集めるタグをまだ信じられない理由（`ファイル名: 理由`）。信じてよければ None。

    `scan_notes` は読めないノートを黙って飛ばし、壊れた frontmatter はファイル名だけを集める
    とみなす。そのまま「どのノートも集めていない」と判定すると、複数のタグをまとめたノートを
    書きかけのときに、同じタグのノートを重ねて作ってしまう。だから、読めない・空・frontmatter が
    解釈できない・直近に更新された（`update_file` と同じ、`now` の前後 `quiet_seconds` 秒）ノートが
    ひとつでもある間は、一括作成を待つ。ディレクトリがまだ無いのは「怪しいノート無し」。
    """
    try:
        with os.scandir(directory) as it:
            entries = sorted(
                (e for e in it
                 if e.name.endswith(".md") and not e.name.startswith(".") and e.name != HUB_NAME),
                key=lambda e: e.name,
            )
    except FileNotFoundError:
        return None
    for entry in entries:
        path = Path(entry.path)
        try:
            if not entry.is_file():   # 壊れた symlink は例外にならず False（ノートではない）
                continue
            mtime = path.stat().st_mtime
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as error:
            return f"{path.name}: 読めない（{type(error).__name__}）"
        meta, _ = report_store.split_front_matter(text)
        doubt = front_matter_doubt(text, meta)
        if doubt:
            return f"{path.name}: {doubt}"
        if abs(now - mtime) < quiet_seconds:
            return f"{path.name}: 直近に更新された"
    return None


UNENCODABLE_REASON = ("一覧に UTF-8 にできない文字が入る"
                      "（UTF-8 でない名前のノートやレポートのファイルがある。名前を直すと作る）")


def can_encode(text: str) -> bool:
    """`write_atomic` が UTF-8 で書ける全文か。

    UTF-8 でないバイトのファイル名（文字コードの違う zip の展開など）は、読むとサロゲートの
    文字になる。一覧のリンクや名前に入ると、書くときに UnicodeEncodeError で落ちて一時ファイルが残る。
    """
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _name_key(name: str) -> str:
    """ファイル名の重なりを見る鍵。NFC に揃えて、見た目が同じ名前を同じとみなす。

    macOS / iOS のファイルシステムは NFC と NFD を区別しないので、vault を同期すると衝突する。
    Linux では別のファイルとして作れてしまうが、Obsidian の一覧に同じ名前が2つ並ぶ。
    """
    return unicodedata.normalize("NFC", name)


@dataclass(frozen=True)
class PlannedNote:
    tag: str
    note: ThemeNote       # 作るパスと、雛形を読み直した集めるタグ（= (tag,)）
    text: str             # 書く全文（雛形 ＋ マーカー内の一覧）


@dataclass(frozen=True)
class CreatePlan:
    notes: list[PlannedNote]           # 作るもの（ファイル名がタグと一致するタグが先、あとはタグ順）
    skipped: list[tuple[str, str]]     # 作らないタグと理由（タグ順）
    already: list[str]                 # 既にどれかのノートが集めているタグ（タグ順）


def plan_new_notes(directory: Path, books: list[Book], reports: dict[int, Path],
                   notes: list[ThemeNote]) -> CreatePlan:
    """本に付いているタグのうち、どのテーマノートも集めていないもののノートの計画。何も書かない。

    作る前に、そのタグごとに次を確かめる（満たさなければ作らず、理由を `skipped` に残す）。
    - ファイル名にできる名前があり、ハブ・既存のノート・この回に先に計画したノートと重ならず
      （Unicode の NFC と NFD だけが違う名前も重なりとみなす）、同名の読めないファイル
      （壊れた symlink・フォルダ）も無い
    - 雛形を書いて frontmatter を読み直す（次の回の `scan_notes` と同じ道）と、集めるタグが
      ちょうどそのタグ1つになる。ならないノートを作ると、毎回作り直しを試みる
    - 書く全文が、次の回に読み戻したとき（`read_text` は CR を LF に直す）もマーカーの組が1つ見え、
      書いた内容と同じで、UTF-8 で書ける

    ファイル名がタグと一致するタグを先に見る（`C` と `C#` が両方 `C.md` になるとき、`C.md` は `C` のもの）。
    """
    tags = {tag.name for book in books for tag in book.tags}
    covered = {tag for note in notes for tag in note.tags}
    existing = {note.path.name for note in notes}
    planned: dict[str, str] = {}                 # この回に計画したファイル名 → タグ
    candidates: list[tuple[str, ThemeNote, str]] = []
    skipped: list[tuple[str, str]] = []
    already: list[str] = []
    for tag in sorted(tags, key=lambda t: (note_stem(t) != t, t)):
        if tag in covered:
            already.append(tag)
            continue
        stem = note_stem(tag)
        name = f"{stem}.md"
        if not stem:
            reason = "ファイル名にできる文字が無い"
        elif name == HUB_NAME:
            reason = f"ファイル名がハブ（{HUB_NAME}）と同じになる"
        elif name in existing:
            reason = (f"{name} が既にあり、このタグを集めていない"
                      "（そのノートの frontmatter の tags に足すと集める）")
        elif name in planned:
            reason = f"{name} はこの回に「{planned[name]}」のノートとして作る"
        elif _name_key(name) in {_name_key(other) for other in (*existing, *planned)}:
            reason = (f"{name} は、既にあるか先に作るノートの名前と Unicode の正規化（NFC）で"
                      "同じ名前になる")
        elif os.path.lexists(directory / name):
            reason = f"{name} が既にある（テーマノートとして読めないファイル）"
        else:
            template = new_note_text(tag, stem)
            meta, _ = report_store.split_front_matter(template)
            read = theme_tags(meta, stem)
            if read != (tag,):
                reason = f"ノートに書くと集めるタグが「{'・'.join(read)}」になり、このタグと一致しない"
            else:
                planned[name] = tag
                candidates.append((tag, ThemeNote(directory / name, read), template))
                continue
        skipped.append((tag, reason))

    # 一覧の「関連するテーマ」には、同じ回に作るノートも出す（アプリが次の回に作る一覧と同じ中身に
    # なるので、アプリは書き直さない）
    after = notes + [note for _, note, _ in candidates]
    created: list[PlannedNote] = []
    for tag, note, template in candidates:
        text = replace_block(template, theme_block(note, books, reports, after))
        # fill_block と同じ自己検証を、次の回の scan_notes が読む形（read_text は CR を LF に直す）で行う。
        # 書名などの文字がフェンスを開くと、以後そのノートが止まる
        read_back = None if text is None else text.replace("\r\n", "\n").replace("\r", "\n")
        if read_back is None or not _has_one_pair(read_back):
            reason = "一覧を書くとマーカーを読み戻せない（タグ名や書名の文字のため）"
        elif read_back != text:
            # 集めるタグはコメントの行に生で書くので、CR を含むタグがそのまま入る。読み戻すと別の中身に
            # なって毎回書き直され、CR が行を分けてマーカーを隠すこともある
            reason = "一覧に CR の文字が入り、書いた内容が読み戻すと変わる（タグ名や書名の文字のため）"
        elif not can_encode(text):
            reason = UNENCODABLE_REASON
        else:
            created.append(PlannedNote(tag, note, text))
            continue
        skipped.append((tag, reason))
    return CreatePlan(created, sorted(skipped), sorted(already))


def rebuild(db: Session, *, quiet_seconds: float = QUIET_SECONDS,
            now: Optional[float] = None) -> list[Path]:
    """全テーマノートとハブの一覧を書き直す。書き換えたファイルを返す。"""
    now = time.time() if now is None else now
    directory = themes_dir()
    directory.mkdir(parents=True, exist_ok=True)
    books = list(db.scalars(select(Book).options(selectinload(Book.tags))))
    reports = report_store.report_paths()
    notes = scan_notes(directory)

    written = []
    for note in notes:
        block = theme_block(note, books, reports, notes)

        def make_note(current: Optional[str], block: str = block) -> Optional[str]:
            # 読んでからロックを取るまでに消されたノートは作り直さない
            return None if current is None else fill_block(note.path, current, block)

        if update_file(note.path, make_note, quiet_seconds, now):
            written.append(note.path)

    hub = directory / HUB_NAME
    block = hub_block(hub, books, reports, notes)

    def make_hub(current: Optional[str]) -> Optional[str]:
        return fill_block(hub, HUB_HEADER if current is None else current, block)

    if update_file(hub, make_hub, quiet_seconds, now):
        written.append(hub)
    return written


# ── 定期実行 ────────────────────────────────────────────────

def _job_name(job: Callable) -> str:
    """ログと「同じ失敗を繰り返し記録しない」の鍵にするジョブ名。

    `functools.partial` や呼び出せるオブジェクトは `__name__` を持たない。名前づくりで
    例外を出すと、セッションを開けない失敗として扱われて残りのジョブまで止まる。
    """
    qualname = getattr(job, "__qualname__", None)
    if not qualname:
        return repr(job)
    module = getattr(job, "__module__", None)
    return f"{module}.{qualname}" if module else qualname


class ThemeWatcher:
    """ノートの一覧（ビュー）を作り直すジョブを数秒ごとに呼ぶスレッド。アプリの起動中だけ動かす。

    ジョブは `(db) -> 書いたファイルのリスト` の関数（`rebuild` と `author_store.rebuild`）。
    1つのセッションで順に呼び、1つが失敗しても他は止めない。
    """

    def __init__(self, session_factory: Callable[[], Session],
                 interval: float = INTERVAL_SECONDS,
                 jobs: Optional[Sequence[Callable[[Session], list[Path]]]] = None):
        self._session_factory = session_factory
        self._interval = interval
        self._jobs = tuple(jobs) if jobs is not None else (rebuild,)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_errors: dict[str, str] = {}

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="theme-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 5)

    def _run(self) -> None:
        while True:
            self._tick()
            if self._stop.wait(self._interval):
                return

    def _record_error(self, name: str, error: Exception) -> None:
        # 同じ失敗を数秒ごとに書き続けないよう、ジョブごとに変わったときだけ記録する
        # （except の中から呼ぶので、logger.exception でトレースバックが付く）
        if repr(error) != self._last_errors.get(name):
            logger.exception("ノートの一覧を更新できなかった: %s", name)
        self._last_errors[name] = repr(error)

    def _tick(self) -> None:
        try:
            with self._session_factory() as db:
                for job in self._jobs:
                    name = _job_name(job)
                    try:
                        written = job(db)
                    except Exception as error:  # 1つの失敗で他のジョブまで止めない
                        self._record_error(name, error)
                        db.rollback()   # 失敗したジョブの途中のトランザクションを次へ持ち越さない
                        continue
                    self._last_errors.pop(name, None)
                    for path in written:
                        logger.info("ノートの一覧を更新: %s/%s", path.parent.name, path.name)
        except Exception as error:  # セッションを開けない場合。止めると以後の更新が全部止まる
            self._record_error("session", error)
            return
        self._last_errors.pop("session", None)
