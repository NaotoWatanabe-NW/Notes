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
  全体の入口として、無ければアプリが作る。
- **書き直すのは中身が変わったときだけ**（mtime を動かさない）。さらに、直近
  `QUIET_SECONDS` 秒以内に更新されたノートは、Obsidian で書いている最中かもしれないので
  その回は飛ばす（次の回で入る）。
- マーカーが壊れている（片方だけ・複数ある・順序が逆）ノートは触らない。

更新は `ThemeWatcher` が数秒ごとに `rebuild()` を呼んで行う。ルーターから呼び出しを
差し込まないのは、Obsidian でノートを作った・タグを書き換えたといった、アプリの API を
通らない変化も拾う必要があるため。毎回 DB から全冊を引くが、100冊程度なら軽い。

書き込みはレポートと同じロック（`reports/.write.lock`）と原子的な置き換えを使う。
"""

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import report_store
from .models import Book, BookStatus

logger = logging.getLogger(__name__)

THEMES_DIRNAME = "themes"
HUB_NAME = "テーマ一覧.md"
START = "<!-- notes:books:start -->"
END = "<!-- notes:books:end -->"
# この秒数以内に更新されたノートは、書いている最中とみなしてその回は飛ばす
QUIET_SECONDS = 10.0
INTERVAL_SECONDS = 5.0

_STATUS_LABEL = {
    BookStatus.READING: "読書中",
    BookStatus.FINISHED: "読了",
    BookStatus.UNREAD: "積読",
}
# レポートの無い本は、読書中 → 読了 → 積読 の順に並べる
_STATUS_ORDER = {BookStatus.READING: 0, BookStatus.FINISHED: 1, BookStatus.UNREAD: 2}

# 一覧の文字に紛れると Markdown や Obsidian の記法になってしまう文字
# （`#` はタグ、`[` `]` はリンク、`*` `_` は強調）。
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]<>#|])")
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
    """`themes/` 直下のテーマノート（ハブと隠しファイルを除く）を名前順に返す。"""
    try:
        with os.scandir(directory) as it:
            entries = [
                e for e in it
                if e.is_file() and e.name.endswith(".md")
                and not e.name.startswith(".") and e.name != HUB_NAME
            ]
    except OSError:
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

def _escape_text(text: str) -> str:
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


def link_target(path: Path, start: Path) -> str:
    """`start` から見た `path` への相対リンク先（Obsidian でも vault の外でも同じ先に解決する）。"""
    relative = Path(os.path.relpath(path, start)).as_posix()
    return "".join(_LINK_ESCAPES.get(ch, ch) for ch in relative)


def _link(text: str, path: Path, start: Path) -> str:
    return f"[{_escape_text(text)}]({link_target(path, start)})"


def _book_line(book: Book, report: Optional[Path], start: Path, matched: list[str]) -> str:
    head = _link(book.title, report, start) if report else _escape_text(book.title)
    parts = []
    if book.author:
        parts.append(_escape_text(book.author))
    status = _STATUS_LABEL.get(book.status, str(book.status))
    if book.status == BookStatus.FINISHED and book.finished_on:
        status += f" {book.finished_on.isoformat()}"
    parts.append(status)
    if book.rating:
        parts.append("★" * book.rating)
    if matched:
        parts.append("・".join(_escape_text(tag) for tag in matched))
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


def _wrap(lines: list[str]) -> str:
    return "\n".join([START, *lines, END])


def theme_block(
    note: ThemeNote,
    books: list[Book],
    reports: dict[int, Path],
    notes: list[ThemeNote],
) -> str:
    """テーマノートに差し込む一覧（マーカー込み）。"""
    start = note.path.parent
    matched = books_for(note.tags, books)
    with_report = sorted((b for b in matched if b.id in reports), key=_report_order)
    without_report = sorted(
        (b for b in matched if b.id not in reports),
        key=lambda b: (_STATUS_ORDER.get(b.status, 9), b.title),
    )
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
            f"このタグの本はまだありません（集めるタグ: {'・'.join(_escape_text(t) for t in note.tags)}）。"
            "集めるタグはノートの frontmatter の `tags` で変えられます。"
        )
    else:
        lines.append(f"{len(matched)}冊（レポートあり {len(with_report)}冊）")
        if with_report:
            lines += ["", "### レポートのある本", ""]
            lines += [_book_line(b, reports[b.id], start, matched_tags(b)) for b in with_report]
        if without_report:
            lines += ["", "### まだレポートの無い本", ""]
            lines += [_book_line(b, None, start, matched_tags(b)) for b in without_report]

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
            f"- {_link(other.path.stem, other.path, start)} — 共通の本 {count}冊"
            for count, other in related
        ]
    return _wrap(lines)


def hub_block(hub: Path, books: list[Book], reports: dict[int, Path], notes: list[ThemeNote]) -> str:
    """ハブ（テーマ一覧）に差し込む一覧（マーカー込み）。"""
    start = hub.parent
    lines = ["## テーマノート", ""]
    if notes:
        for note in notes:
            matched = books_for(note.tags, books)
            reported = sum(1 for b in matched if b.id in reports)
            lines.append(
                f"- {_link(note.path.stem, note.path, start)} — "
                f"{'・'.join(_escape_text(t) for t in note.tags)} · {len(matched)}冊（レポート {reported}）"
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
            lines.append(f"- {_escape_text(name)} — {len(tagged)}冊（レポート {reported}）")
    else:
        lines.append("すべてのタグにノートがあります。")
    return _wrap(lines)


# ── 差し込み ────────────────────────────────────────────────

def replace_block(text: str, block: str) -> Optional[str]:
    """マーカーの間を `block` に差し替えた全文。マーカーが無ければ末尾に足す。

    マーカーが片方だけ・複数・順序が逆なら None（ユーザーの文章を壊さないよう触らない）。
    """
    starts, ends = text.count(START), text.count(END)
    if starts == 0 and ends == 0:
        base = text.rstrip()
        return f"{base}\n\n{block}\n" if base else f"{block}\n"
    if starts == 1 and ends == 1:
        begin, finish = text.index(START), text.index(END)
        if begin < finish:
            return text[:begin] + block + text[finish + len(END):]
    return None


def _update(path: Path, make_text: Callable[[Optional[str]], Optional[str]],
            quiet_seconds: float, now: float) -> bool:
    """ロックの中で読み直して書き換える。書いたら True。"""
    with report_store.write_lock(report_store.reports_dir()):
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            current = None
        else:
            if now - mtime < quiet_seconds:
                return False
            try:
                current = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                return False
        new = make_text(current)
        if new is None or new == current:
            return False
        report_store.write_atomic(path, new)
        return True


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
            return None if current is None else replace_block(current, block)

        if _update(note.path, make_note, quiet_seconds, now):
            written.append(note.path)

    hub = directory / HUB_NAME
    block = hub_block(hub, books, reports, notes)

    def make_hub(current: Optional[str]) -> Optional[str]:
        return replace_block(HUB_HEADER if current is None else current, block)

    if _update(hub, make_hub, quiet_seconds, now):
        written.append(hub)
    return written


# ── 定期実行 ────────────────────────────────────────────────

class ThemeWatcher:
    """`rebuild()` を数秒ごとに呼ぶスレッド。アプリの起動中だけ動かす。"""

    def __init__(self, session_factory: Callable[[], Session],
                 interval: float = INTERVAL_SECONDS):
        self._session_factory = session_factory
        self._interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_error: Optional[str] = None

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

    def _tick(self) -> None:
        try:
            with self._session_factory() as db:
                written = rebuild(db)
        except Exception as error:  # 止めると以後の更新が全部止まるので、記録して続ける
            # 同じ失敗を数秒ごとに書き続けないよう、変わったときだけ記録する
            if repr(error) != self._last_error:
                logger.exception("テーマノートの一覧を更新できなかった")
            self._last_error = repr(error)
            return
        self._last_error = None
        for path in written:
            logger.info("テーマノートの一覧を更新: %s", path.name)
