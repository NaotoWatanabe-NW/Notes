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
  その回は飛ばす（次の回で入る）。mtime が `QUIET_SECONDS` 秒以上未来のノートは
  （同期のずれなど）飛ばさず書く。
- マーカーは行全体がマーカーだけの行に限り、コードフェンスの中は無視する（使い方の例として
  書いたマーカーを本物と取り違えない）。マーカーが壊れている（片方だけ・複数ある・順序が逆・
  フェンスが閉じていない）ノートは触らず、警告を1回だけ出す。

更新は `ThemeWatcher` が数秒ごとに `rebuild()` を呼んで行う。ルーターから呼び出しを
差し込まないのは、Obsidian でノートを作った・タグを書き換えたといった、アプリの API を
通らない変化も拾う必要があるため。毎回 DB から全冊を引くが、100冊程度なら軽い。

書き込みはレポートと同じロック（`reports/.write.lock`）と原子的な置き換えを使う。

ここの `escape_text` / `md_link` / `wrap_block` / `update_file` / `book_sections` /
`replace_block` / `fill_block` は著者ノート（`author_store.py`）も使う共有部品。
`ThemeWatcher` も、テーマと著者の両方のジョブをまとめて数秒ごとに回す。
"""

import logging
import os
import re
import threading
import time
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

def escape_text(text: str) -> str:
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


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

# コードフェンスの開き・閉じ（CommonMark）。マーカーの例を書いたフェンスの中は探さない
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*$")

# 壊れたマーカーを警告済みのパス。5秒ごとに同じ警告を出さないために覚えておく
# （直ったら外す。rebuild はウォッチャーの1スレッドから呼ぶので、ロックは要らない）
_warned_broken: set[Path] = set()


def _marker_lines(lines: list[str]) -> Optional[tuple[list[int], list[int]]]:
    """コードフェンスの外にある START 行・END 行の番号。フェンスが閉じていなければ None。

    マーカーは行全体がマーカーだけの行（前後の空白は可）に限る。文中やインラインコードで
    触れているだけのものは数えない。
    """
    starts: list[int] = []
    ends: list[int] = []
    fence: Optional[tuple[str, int]] = None   # 開いているフェンスの（文字, 長さ）
    for number, line in enumerate(lines):
        if fence is not None:
            close = _FENCE_CLOSE.match(line)
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= fence[1]:
                fence = None
            continue
        opening = _FENCE_OPEN.match(line)
        if opening:
            fence = (opening.group(1)[0], len(opening.group(1)))
            continue
        stripped = line.strip()
        if stripped == START:
            starts.append(number)
        elif stripped == END:
            ends.append(number)
    return None if fence is not None else (starts, ends)


def replace_block(text: str, block: str) -> Optional[str]:
    """START 行から END 行までを `block` に差し替えた全文。マーカーが無ければ末尾に足す。

    マーカーが片方だけ・複数・順序が逆、またはコードフェンスが閉じていないなら None
    （ユーザーの文章を壊さないよう触らない。閉じていないフェンスの中に足すと、次の回に
    また足して増え続ける）。
    """
    lines = text.split("\n")
    found = _marker_lines(lines)
    if found is None:
        return None
    starts, ends = found
    if not starts and not ends:
        base = text.rstrip()
        return f"{base}\n\n{block}\n" if base else f"{block}\n"
    if len(starts) == 1 and len(ends) == 1 and starts[0] < ends[0]:
        return "\n".join(lines[:starts[0]] + [block] + lines[ends[0] + 1:])
    return None


def fill_block(path: Path, text: str, block: str) -> Optional[str]:
    """`replace_block` と同じ。壊れていて書けないときは、そのパスにつき1回だけ警告を出す。

    直ったら（文字列が返ったら）覚えを外すので、また壊れたらもう1回警告する。
    雛形（マーカーが無いと分かっているもの）には使わず、`replace_block` を直接呼ぶ。
    """
    new = replace_block(text, block)
    if new is not None:
        _warned_broken.discard(path)
    elif path not in _warned_broken:
        _warned_broken.add(path)
        logger.warning(
            "マーカーが壊れているので一覧を書かない"
            "（start と end を1組にするか、閉じていないコードフェンスを閉じると次の回で入る）: %s",
            path,
        )
    return new


def update_file(path: Path, make_text: Callable[[Optional[str]], Optional[str]],
                quiet_seconds: float, now: float) -> bool:
    """ロックの中で読み直して書き換える。書いたら True。

    mtime が `now` から `quiet_seconds` 以内なら、書いている最中かもしれないので飛ばす。
    未来側も含めて見るのは、`now` を rebuild の始めに1回だけ取るため（途中で保存された
    ノートの mtime は `now` より少し先になる）。一方、`quiet_seconds` 以上先の mtime
    （同期のずれなど）まで飛ばすと、そのノートを永久に更新できなくなる。
    """
    with report_store.write_lock(report_store.reports_dir()):
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            current = None
        else:
            if abs(now - mtime) < quiet_seconds:
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
                    name = f"{job.__module__}.{job.__name__}"
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
