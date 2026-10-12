"""著者ノート（`reports/authors/*.md`）に「この著者の本」の一覧を差し込むストア

著者ごとのノート。レポートを著者でつなぎ、Obsidian で「同じ著者のレポート」をたどれるようにする
（著者ノート → レポートのリンクがグラフに出て、レポート側のバックリンクに著者ノートが出る）。
テーマノート（`theme_store.py`）と同じ仕組みで、**本文はユーザーが書き**、アプリが書くのは
マーカー `<!-- notes:books:start --> … <!-- notes:books:end -->` の間だけ。部品（マーカーの
差し替え・書き込み・本の行）は `theme_store` のものを共有する。

- **著者の分け方**: `Book.author` を NFKC 正規化して `,` `、` で分け、末尾の役割表記
  （`／著` `／訳` `（編著）` など）を落とす。訳者も著者と同じに扱う（DB の著者欄に役割は無いことが
  多く、役割で分けると同じ人が本によって入ったり外れたりするため）。照合は空白・`・` `.` `=` を除き
  casefold したキーで行い、表記揺れを同じ人にまとめる。
- **ノートが集める名前**: ファイル名（stem）と frontmatter の `aliases`。別の文字種の表記
  （`H.G. Wells` と `H・G・ウェルズ`）は `aliases` でユーザーが1つにまとめる。
- **ノートを作るのは、レポートが1冊以上ある著者に限り、どのノートも集めていないときだけアプリ**。
  それ以外の著者はハブ `authors/著者一覧.md` に冊数付きの文字で出す。ユーザーが作ったノートは
  レポートの有無に関係なく埋める。アプリはノートを改名も削除もしない（消されたノートは、
  著者にレポートがある限り次の回に作り直される）。
- 書き直すのは中身が変わったときだけ、直近に更新されたノートは飛ばす、マーカーが壊れたノートは
  触らない、といった書き込みの規則は `theme_store` と同じ（`update_file` / `fill_block`）。

更新は `ThemeWatcher` が `theme_store.rebuild` の次に `rebuild()` を呼んで行う。
設計: docs/design/0002-author-notes.md
"""

import os
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import report_store, theme_store
from .models import Book
from .theme_store import escape_text, md_link, wrap_block

AUTHORS_DIRNAME = "authors"
HUB_NAME = "著者一覧.md"
NOTE_TYPE = "author-note"
HUB_TYPE = "author-hub"

_SEPARATORS = re.compile(r"[,、]")          # NFKC のあとに使う（，→ , と ､ → 、は NFKC が揃える）
_ROLES_ANY = "編著|共著|著者|訳者|編者|監修|監訳|翻訳|原作|解説|著|訳|編|作|絵|文|画"
# 空白区切りの役割に「作」「絵」「文」「画」を入れないのは、Google Books の「山田 文」のような
# 姓と1文字の名を役割と取り違えないため
_ROLES_SPACED = "編著|共著|著者|訳者|編者|監修|監訳|翻訳|著|訳|編"
_ROLE_SUFFIX = re.compile(
    rf"(?:\s*/\s*(?:{_ROLES_ANY})"             # 「／著」「/訳」
    rf"|\s*[(\[]\s*(?:{_ROLES_ANY})\s*[)\]]"   # 「（編著）」「[著]」（NFKC で全角括弧も半角になる）
    rf"|\s+(?:{_ROLES_SPACED}))\s*$"           # 「 編」「 訳」（空白区切りは紛れない役割だけ）
)
_SPACES = re.compile(r"\s+")
_KEY_DROP = re.compile(r"[\s・.=·]")          # 照合キーで無視する文字
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f\x7f]')   # ファイル名・Obsidian のリンクで困る文字
_STEM_BYTES = 200                              # ファイル名の上限（UTF-8 で 255 バイト未満に収める）

HUB_HEADER = f"""---
type: {HUB_TYPE}
---

# 著者一覧

著者ノートの入口。レポートが1冊でもある著者のノートは、このフォルダ（`authors/`）にアプリが自動で作る。
レポートの無い著者も「著者名.md」を作れば本の一覧が入る。同じ人の別の表記（「H.G. Wells」と
「H・G・ウェルズ」など）は、残すほうのノートの frontmatter の `aliases` に足すと1つにまとまる
（先に aliases を足してから、もう一方のノートを消す）。
ここにも自由に書いてよい（下の一覧の部分だけアプリが書き直す）。
"""


def authors_dir() -> Path:
    return report_store.reports_dir() / AUTHORS_DIRNAME


# ── 名前の扱い ──────────────────────────────────────────────

def author_key(name: str) -> str:
    """照合キー。NFKC → 空白と `・` `.` `=` `·` を除去 → casefold。

    出典ごとの表記揺れ（全角半角・空白・カナ表記の区切り・大文字小文字）を同じ人にまとめる。
    macOS の Obsidian が付ける NFD のファイル名も、NFKC で NFC に揃うので同じキーになる。
    """
    return _KEY_DROP.sub("", unicodedata.normalize("NFKC", name)).casefold()


def split_authors(author: Optional[str]) -> list[str]:
    """著者欄を人ごとの表示名に分ける。キーで重複を除き、出てきた順に返す。

    NFKC → `,` `、` で分割 → 各部分を strip → 末尾の役割表記を1回だけ落とす → 空白を1つに詰める。
    キーが空になるもの（空文字・役割だけ）は捨てる。
    """
    if not author:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for part in _SEPARATORS.split(unicodedata.normalize("NFKC", author)):
        name = _ROLE_SUFFIX.sub("", part.strip(), count=1)
        name = _SPACES.sub(" ", name).strip()
        key = author_key(name)
        if key and key not in seen:
            seen.add(key)
            names.append(name)
    return names


def note_stem(name: str) -> str:
    """自動作成するノートのファイル名（拡張子なし）。作れない名前なら空文字。

    使えない文字を除き、空白を詰め、先頭・末尾の `.` を落とす（隠しファイルにしない）。
    長すぎれば UTF-8 で `_STEM_BYTES` バイトまでに切る（文字の途中では切らない）。
    """
    stem = _SPACES.sub(" ", _UNSAFE_NAME.sub("", name)).strip().strip(".")
    stem = stem.encode("utf-8")[:_STEM_BYTES].decode("utf-8", errors="ignore")
    return stem.strip()


# ── DB 側: 著者の集計 ───────────────────────────────────────

@dataclass(frozen=True)
class Author:
    key: str
    name: str                 # 表示名。そのキーを最初に持つ（id が最小の）本の表記
    books: tuple[Book, ...]   # id 順。同じ本は1回だけ


def collect_authors(books: list[Book]) -> dict[str, Author]:
    """id 順に本を見て、`split_authors` の名前ごとに本を集める。キー → Author（出てきた順）。

    著者欄が null・空・区切りだけの本は、どの著者にも入らない。
    """
    names: dict[str, str] = {}
    collected: dict[str, list[Book]] = {}
    for book in sorted(books, key=lambda b: b.id):
        for name in split_authors(book.author):   # 1冊の中の同じ人はここで1つになっている
            key = author_key(name)
            names.setdefault(key, name)
            collected.setdefault(key, []).append(book)
    return {key: Author(key, names[key], tuple(found)) for key, found in collected.items()}


# ── ノート側: ノートが集める名前 ────────────────────────────

@dataclass(frozen=True)
class AuthorNote:
    path: Path
    names: tuple[str, ...]     # stem が先頭、続いて aliases。キーで重複を除いた順
    keys: frozenset[str]       # names の author_key


def note_names(meta: dict, stem: str) -> tuple[str, ...]:
    """stem と frontmatter の `aliases` を、著者欄と同じ規則（`split_authors`）で名前にする。

    aliases は文字列なら1つ、配列なら各要素（None は飛ばし、数値などは str にする）。
    それ以外は無視する。文字列の中の `,` や `、` も区切りとして扱う（著者欄が同じ規則で
    分かれるので、区切りを含む名前のままではどの著者とも一致しない）。
    """
    raw = meta.get("aliases")
    if isinstance(raw, str):
        aliases = [raw]
    elif isinstance(raw, list):
        aliases = [str(item) for item in raw if item is not None]
    else:
        aliases = []
    names: list[str] = []
    seen: set[str] = set()
    for item in [stem, *aliases]:
        for name in split_authors(item):
            key = author_key(name)
            if key not in seen:
                seen.add(key)
                names.append(name)
    return tuple(names)


def _note_of(path: Path, meta: dict) -> AuthorNote:
    names = note_names(meta, path.stem)
    return AuthorNote(path, names, frozenset(author_key(name) for name in names))


def scan_notes(directory: Path) -> list[AuthorNote]:
    """`authors/` 直下のノート（ハブと隠しファイルを除く）をファイル名順に返す。

    サブフォルダは見ない。読めないファイルは飛ばす。
    """
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
        notes.append(_note_of(path, meta))
    return notes


def books_of(note: AuthorNote, authors: dict[str, Author]) -> list[Book]:
    """ノートが集める名前のどれかを持つ著者の本（id 順）。同じ本は1回だけ。"""
    found: dict[int, Book] = {}
    for key in note.keys:
        author = authors.get(key)
        if author:
            for book in author.books:
                found[book.id] = book
    return [found[book_id] for book_id in sorted(found)]


# ── 一覧を組み立てる ────────────────────────────────────────

def author_block(note: AuthorNote, books: list[Book], reports: dict[int, Path],
                 themes: list[tuple[Path, set[int]]]) -> str:
    """著者ノートに差し込む一覧（マーカー込み）。themes は (テーマノートのパス, その本の id 集合)。"""
    start = note.path.parent
    # 名前の区切りに `・` を使わないのは、カナの名前の中の `・` と見分けられないため
    lines = [
        "## この著者の本",
        "",
        f"<!-- ここから end まではアプリが DB の著者欄から書き直す（手で編集しない）。"
        f"集める名前: {'、'.join(note.names)} -->",
        "",
    ]
    if not books:
        lines.append(
            f"この名前の本はまだありません（集める名前: {'、'.join(escape_text(n) for n in note.names)}）。"
            "集める名前はファイル名と frontmatter の `aliases` で決まります。"
        )
    else:
        # 本の行の著者部分には DB の著者欄をそのまま出す（共著者・訳者・役割表記も見える）
        lines += theme_store.book_sections(books, reports, start)

    # 同じ本を含むテーマノート。著者とテーマがグラフでつながり、著者 → テーマ → 他の本とたどれる。
    mine = {b.id for b in books}
    related = sorted(
        ((len(ids & mine), path) for path, ids in themes if ids & mine),
        key=lambda pair: (-pair[0], pair[1].name),
    )
    if related:
        lines += ["", "### 関連するテーマ", ""]
        lines += [f"- {md_link(path.stem, path, start)} — 共通の本 {count}冊" for count, path in related]
    return wrap_block(lines)


def _counts_text(books: list[Book], reports: dict[int, Path]) -> str:
    """ハブの行の「N冊（レポート M）」。テーマのハブと同じ形。"""
    return f"{len(books)}冊（レポート {sum(1 for b in books if b.id in reports)}）"


def hub_block(hub: Path, notes: list[AuthorNote], authors: dict[str, Author],
              reports: dict[int, Path]) -> str:
    """ハブ（著者一覧）に差し込む一覧（マーカー込み）。"""
    start = hub.parent
    lines = ["## 著者ノート", ""]
    if notes:
        rows = [(note, books_of(note, authors)) for note in notes]
        for note, books in sorted(rows, key=lambda row: (-len(row[1]), row[0].path.stem)):
            lines.append(f"- {md_link(note.path.stem, note.path, start)} — {_counts_text(books, reports)}")
    else:
        lines.append("まだありません。")

    covered = set().union(*(note.keys for note in notes))
    lines += ["", "## ノートの無い著者", ""]
    uncovered = [a for a in authors.values() if a.key not in covered]
    if uncovered:
        for author in sorted(uncovered, key=lambda a: (-len(a.books), a.name)):
            lines.append(f"- {escape_text(author.name)} — {_counts_text(list(author.books), reports)}")
    else:
        lines.append("すべての著者にノートがあります。")
    return wrap_block(lines)


# ── 自動作成 ────────────────────────────────────────────────

def _new_note_meta(author: Author, stem: str) -> dict:
    meta: dict = {"type": NOTE_TYPE}
    # ファイル名にするとき名前が変わった（使えない文字を落とした・切った）ときだけ、元の名前を
    # aliases に入れる。入れないと次の回に「どのノートも集めていない」と判定され続ける
    if author_key(stem) != author.key:
        meta["aliases"] = [author.name]
    return meta


def new_note_text(author: Author, stem: str) -> str:
    """自動作成するノートの雛形（マーカーはまだ無い）。"""
    return (report_store.front_matter_text(_new_note_meta(author, stem))
            + f"\n# {escape_text(author.name)}\n")


# ── 差し込み ────────────────────────────────────────────────

def rebuild(db: Session, *, quiet_seconds: float = theme_store.QUIET_SECONDS,
            now: Optional[float] = None) -> list[Path]:
    """著者ノートの一覧・自動作成・ハブを書き直す。書いた（作った）ファイルを返す。"""
    now = time.time() if now is None else now
    directory = authors_dir()
    directory.mkdir(parents=True, exist_ok=True)
    books = list(db.scalars(select(Book).options(selectinload(Book.tags)).order_by(Book.id)))
    reports = report_store.report_paths()
    authors = collect_authors(books)
    notes = scan_notes(directory)
    # テーマの所属は、著者ごとに books_for を呼び直さないよう1回だけ計算する
    themes = [(t.path, {b.id for b in theme_store.books_for(t.tags, books)})
              for t in theme_store.scan_notes(theme_store.themes_dir())]

    written = []
    # 1. 既存のノート（ユーザーが作ったもの・前に作ったもの）
    for note in notes:
        block = author_block(note, books_of(note, authors), reports, themes)

        def make_note(current: Optional[str], path: Path = note.path, block: str = block) -> Optional[str]:
            # 読んでからロックを取るまでに消されたノートは、ここでは作り直さない（2. で作る）
            return None if current is None else theme_store.fill_block(path, current, block)

        if theme_store.update_file(note.path, make_note, quiet_seconds, now):
            written.append(note.path)

    # 2. 自動作成: レポートのある著者で、どのノートも集めていないもの
    covered = set().union(*(note.keys for note in notes))
    taken = {note.path.name for note in notes} | {HUB_NAME}
    created: list[AuthorNote] = []
    for author in sorted(authors.values(), key=lambda a: (a.name, a.key)):
        if author.key in covered or not any(b.id in reports for b in author.books):
            continue
        stem = note_stem(author.name)
        if not stem or f"{stem}.md" in taken:
            continue
        path = directory / f"{stem}.md"
        note = _note_of(path, _new_note_meta(author, stem))
        block = author_block(note, books_of(note, authors), reports, themes)
        text = theme_store.replace_block(new_note_text(author, stem), block)

        def make_new(current: Optional[str], text: Optional[str] = text) -> Optional[str]:
            # 読んでからロックを取るまでに同じ名前のファイルができていたら、その回は触らない
            return text if current is None else None

        if theme_store.update_file(path, make_new, quiet_seconds, now):
            written.append(path)
            created.append(note)
            taken.add(path.name)

    # 3. ハブ
    hub = directory / HUB_NAME
    block = hub_block(hub, notes + created, authors, reports)

    def make_hub(current: Optional[str]) -> Optional[str]:
        return theme_store.fill_block(hub, HUB_HEADER if current is None else current, block)

    if theme_store.update_file(hub, make_hub, quiet_seconds, now):
        written.append(hub)
    return written
