"""著者ノート（`reports/authors/*.md`）に「この著者の本」の一覧を差し込むストア

著者ごとのノート。レポートを著者でつなぎ、Obsidian で「同じ著者のレポート」をたどれるようにする
（著者ノート → レポートのリンクがグラフに出て、レポート側のバックリンクに著者ノートが出る）。
テーマノート（`theme_store.py`）と同じ仕組みで、**本文はユーザーが書き**、アプリが書くのは
マーカー `<!-- notes:books:start --> … <!-- notes:books:end -->` の間だけ。部品（マーカーの
差し替え・書き込み・本の行）は `theme_store` のものを共有する。

- **著者の分け方**: `Book.author` を NFKC 正規化して（書式文字は落として）`,` `、` で分け、
  末尾の役割表記（`／著` `／訳` `（編著）` `(著, 編集)` など）を変化が無くなるまで落とす。括弧の中の
  区切りでは分けない。訳者も著者と同じに扱う（DB の著者欄に役割は無いことが多く、役割で分けると
  同じ人が本によって入ったり外れたりするため）。照合は空白・`・` `.` `=` を除き casefold した
  キーで行い、表記揺れを同じ人にまとめる。
- **ノートが集める名前**: ファイル名（stem）と frontmatter の `aliases`。別の文字種の表記
  （`H.G. Wells` と `H・G・ウェルズ`）は `aliases` でユーザーが1つにまとめる。
- **ノートを作るのは、レポートが1冊以上ある著者に限り、どのノートも集めていないときだけアプリ**。
  それ以外の著者はハブ `authors/著者一覧.md` に冊数付きの文字で出す。ユーザーが作ったノートは
  レポートの有無に関係なく埋める。アプリはノートを改名も削除もしない（消されたノートは、
  著者にレポートがある限り次の回に作り直される）。レポートの無い著者も含めて一括で作るときだけ、
  ユーザーが `scripts/create_notes.py` を流す（作ってよいかの判定は同じ `plan_new_notes`。
  設計: docs/design/0003-bulk-create-notes.md）。
- **自動作成は、ノートの名前を確かに読めた回だけ**。編集途中のノートは aliases を読めず、
  まとめたはずの著者のノートを作り直してしまう。frontmatter が解釈できない・空・読めない・
  直近に更新された、のどれかのノートが1つでもある回は、作るのを控える（一覧の書き直しとハブは行う）。
  作るノートが他の著者のキーや、既に集められているキーまで集めてしまうときも作らない。
- 書き直すのは中身が変わったときだけ、直近に更新されたノートは飛ばす、マーカーが壊れたノートは
  触らない、といった書き込みの規則は `theme_store` と同じ（`update_file` / `fill_block`）。

更新は `ThemeWatcher` が `theme_store.rebuild` の次に `rebuild()` を呼んで行う。
設計: docs/design/0002-author-notes.md
"""

import logging
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

logger = logging.getLogger(__name__)

AUTHORS_DIRNAME = "authors"
HUB_NAME = "著者一覧.md"
NOTE_TYPE = "author-note"
HUB_TYPE = "author-hub"

_SEPARATOR_CHARS = ",、"                      # NFKC のあとに使う（，→ , と ､ → 、は NFKC が揃える）
_ROLES_ANY = (
    "編著|共著|著者|訳者|編者|監修|監訳|翻訳|原作|解説|"
    "編集|編纂|編訳|校注|校閲|校訂|原著|原案|原画|序文|構成|企画|協力|脚本|漫画|作画|挿絵|"
    "イラストレーター|イラスト|写真|撮影|"
    "著|訳|編|作|絵|文|画"
)
# 空白区切りの役割に「作」「絵」「文」「画」など1文字の語を入れないのは、Google Books の
# 「山田 文」のような姓と1文字の名を役割と取り違えないため
_ROLES_SPACED = "編著|共著|著者|訳者|編者|監修|監訳|翻訳|著|訳|編"
# 括弧の中が役割だけ（`著`、`著, 編集`）のとき。1つでも役割でない語が混ざれば落とさない
_ROLE_LIST = rf"(?:{_ROLES_ANY})(?:\s*[{_SEPARATOR_CHARS}]\s*(?:{_ROLES_ANY}))*"
_ROLE_SUFFIX = re.compile(
    rf"(?:\s*/\s*(?:{_ROLES_ANY})"             # 「／著」「/訳」
    rf"|\s*[(\[]\s*{_ROLE_LIST}\s*[)\]]"       # 「（編著）」「[著]」「(著, 編集)」（NFKC で全角括弧も半角になる）
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

def _drop_format_chars(text: str) -> str:
    """書式文字（Unicode のカテゴリ Cf: ゼロ幅スペース・ソフトハイフン・BOM など）を落とす。

    見えないので、残すと見た目が同じ名前が別の著者・別のファイルになり、名前の見えないファイルもできる。
    """
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def _normalize(text: str) -> str:
    """書式文字を落として NFKC に揃える。

    順序は落としてから NFKC。書式文字が濁点などの結合文字の間にあると、落とした後で合成が
    変わる（`ｶ` `\\xad` `ﾞ` が、NFKC のあとに落とすと `ガ` のまま残り、もう一度通すと `ガ` になる）。
    NFKC は書式文字を作らないので、落としたあとに残ることはない。
    """
    return unicodedata.normalize("NFKC", _drop_format_chars(text))


def author_key(name: str) -> str:
    """照合キー。書式文字を除去 → NFKC → 空白と `・` `.` `=` `·` を除去 → casefold。

    出典ごとの表記揺れ（全角半角・空白・カナ表記の区切り・大文字小文字）を同じ人にまとめる。
    macOS の Obsidian が付ける NFD のファイル名も、NFKC で NFC に揃うので同じキーになる。
    """
    return _KEY_DROP.sub("", _normalize(name)).casefold()


def _split_outside_brackets(text: str) -> list[str]:
    """`,` `、` で分ける。対になった括弧 `(…)` `[…]` の中の区切りでは分けない。

    `山田太郎 (著, 編集), 鈴木花子 (翻訳)` を括弧の中でも切ると、`山田太郎 (著` と `編集)` に
    なってしまう。閉じていない括弧は無視する（開き括弧が残りの著者を飲み込まないように）。
    """
    opened: list[int] = []
    delta = [0] * (len(text) + 1)   # 位置ごとの括弧の深さの増減（入れ子が深くても1回の走査で済む）
    for i, ch in enumerate(text):
        if ch in "([":
            opened.append(i)
        elif ch in ")]" and opened:
            delta[opened.pop()] += 1
            delta[i + 1] -= 1
    parts: list[str] = []
    depth = 0
    begin = 0
    for i, ch in enumerate(text):
        depth += delta[i]
        if depth == 0 and ch in _SEPARATOR_CHARS:
            parts.append(text[begin:i])
            begin = i + 1
    parts.append(text[begin:])
    return parts


def _strip_roles(name: str) -> str:
    """末尾の役割表記を、変化が無くなるまで落とす（`山田太郎 編 著`、`山田太郎(編)/著`）。

    1回だけだと落とした名前にまだ役割が残り、その名前をもう一度 `split_authors` に通すと
    別の名前になる（ノートのファイル名や aliases に使った名前が、著者の名前と一致しなくなる）。
    """
    while True:
        stripped = _ROLE_SUFFIX.sub("", name, count=1).strip()
        if len(stripped) >= len(name):   # 短くならなければ止める
            return name
        name = stripped


def split_authors(author: Optional[str]) -> list[str]:
    """著者欄を人ごとの表示名に分ける。キーで重複を除き、出てきた順に返す。

    書式文字を除去 → NFKC → 括弧の外の `,` `、` で分割 → 空白を1つに詰めて strip
    → 末尾の役割表記を繰り返し落とす。キーが空になるもの（空文字・役割だけ）は捨てる。
    結果の各名前をもう一度この関数に通しても変わらない（ノートの stem や aliases に使えるように）。
    """
    if not author:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for part in _split_outside_brackets(_normalize(author)):
        name = _strip_roles(_SPACES.sub(" ", part).strip())
        key = author_key(name)
        if key and key not in seen:
            seen.add(key)
            names.append(name)
    return names


def note_stem(name: str) -> str:
    """自動作成するノートのファイル名（拡張子なし）。作れない名前なら空文字。

    書式文字と使えない文字を除き、空白を詰め、先頭・末尾の空白と `.` を落とす（隠しファイルにしない。
    `. .a` のように空白をはさんだ先頭の `.` も残さない）。
    長すぎれば UTF-8 で `_STEM_BYTES` バイトまでに切る（文字の途中では切らない）。
    文字（L*）か数字（N*）を1つも含まない名前（記号・絵文字・結合文字だけ）はファイル名にしない。
    """
    stem = _SPACES.sub(" ", _UNSAFE_NAME.sub("", _normalize(name))).strip(" .")
    stem = stem.encode("utf-8")[:_STEM_BYTES].decode("utf-8", errors="ignore").strip()
    if not any(unicodedata.category(ch)[0] in "LN" for ch in stem):
        return ""
    return stem


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
    mtime: Optional[float] = None   # 読んだときの更新時刻。scan_notes が読んだノートだけ入る


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


def _note_of(path: Path, meta: dict, mtime: Optional[float] = None) -> AuthorNote:
    names = note_names(meta, path.stem)
    return AuthorNote(path, names, frozenset(author_key(name) for name in names), mtime)


@dataclass(frozen=True)
class NoteScan:
    """`scan_notes` の結果。ノートの一覧と、名前を確かに読めなかったファイル。"""
    notes: list[AuthorNote]               # 読めたノート（ファイル名順）。doubts にあるものも含む
    doubts: list[tuple[Path, str]]        # aliases を確かめられないファイルと、その理由

    def reason_to_wait(self, now: float, quiet_seconds: float) -> Optional[str]:
        """ノートの名前をまだ信じられない理由。自動作成してよいなら None。

        編集途中のノートは aliases を読めない（閉じていない `[`、保存途中の空ファイル）。
        そのまま「どのノートも集めていない」と判定すると、aliases でまとめた著者のノートを
        作り直してしまい、直した後も残る。だから、ひとつでも怪しいノートがある回は作らない。
        直近に更新されたノートも同じ（`update_file` と同じ、`now` の前後 `quiet_seconds` 秒）。
        """
        if self.doubts:
            path, reason = self.doubts[0]
            return f"{path.name}: {reason}"
        for note in self.notes:
            if note.mtime is not None and abs(now - note.mtime) < quiet_seconds:
                return f"{note.path.name}: 直近に更新された"
        return None


# 前の回の doubts と、警告済みの doubts（rebuild はウォッチャーの1スレッドから呼ぶ）
_seen_doubts: set[tuple[Path, str]] = set()
_warned_doubts: set[tuple[Path, str]] = set()


def _warn_lasting_doubts(doubts: list[tuple[Path, str]]) -> None:
    """2回続けて残っている怪しいノートを、直るまでに1回だけ警告する。

    書きかけのノートは数秒で直るので黙っていてよいが、frontmatter が壊れたままのノートや
    先頭が `---`（水平線）のノートは、直すまで自動作成を止め続ける。黙っていると、
    ノートが作られない理由が分からない。1回だけの doubt（保存の途中など）では警告しない。
    """
    current = set(doubts)
    for path, reason in sorted(current & _seen_doubts - _warned_doubts):
        logger.warning("著者ノートの自動作成を止めている（直すと次の回で作る）: %s: %s",
                       path.name, reason)
    _warned_doubts.intersection_update(current)
    _warned_doubts.update(current & _seen_doubts)
    _seen_doubts.clear()
    _seen_doubts.update(current)


def scan_notes(directory: Path) -> NoteScan:
    """`authors/` 直下のノート（ハブと隠しファイルを除く）をファイル名順に読む。

    サブフォルダは見ない。1つのファイルが読めなくても（デコードできない・自分を指す symlink など）
    そこで止めず、他のノートは読む。読めなかったファイルは `doubts` に理由つきで残し、
    自動作成を控える理由にする（全部が見えなくなると、まとめたはずの著者のノートまで作り直す）。
    ディレクトリそのものを開けないときは例外を上げる（その回の更新を止める）。
    """
    with os.scandir(directory) as it:
        entries = sorted(
            (e for e in it
             if e.name.endswith(".md") and not e.name.startswith(".") and e.name != HUB_NAME),
            key=lambda e: e.name,
        )
    notes: list[AuthorNote] = []
    doubts: list[tuple[Path, str]] = []
    for entry in entries:
        path = Path(entry.path)
        try:
            if not entry.is_file():   # 壊れた symlink は例外にならず False（ノートではない）
                continue
            mtime = path.stat().st_mtime
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as error:
            doubts.append((path, f"読めない（{type(error).__name__}）"))
            continue
        meta, _ = report_store.split_front_matter(text)
        notes.append(_note_of(path, meta, mtime))
        doubt = theme_store.front_matter_doubt(text, meta)
        if doubt:
            doubts.append((path, doubt))
    return NoteScan(notes, doubts)


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


@dataclass(frozen=True)
class PlannedNote:
    author: Author
    note: AuthorNote      # 雛形を読み直したもの（mtime は None）
    text: str             # 書く全文（雛形 ＋ マーカー内の一覧）


@dataclass(frozen=True)
class CreatePlan:
    notes: list[PlannedNote]               # 作るもの（表示名の順）
    skipped: list[tuple[Author, str]]      # 作らない著者と理由
    already: list[Author]                  # 既にどれかのノートが集めている著者


def plan_new_notes(directory: Path, authors: dict[str, Author], notes: list[AuthorNote],
                   reports: dict[int, Path], themes: list[tuple[Path, set[int]]],
                   *, include_without_report: bool = False) -> CreatePlan:
    """どのノートも集めていない著者のノートの計画。何も書かない。

    既定は、レポートが1冊以上ある著者だけ（アプリの自動作成）。`include_without_report` が
    True なら全部の著者（`scripts/create_notes.py` の一括作成）。レポートが無くて対象から外れた
    著者は、`skipped` にも入れない（ハブに文字で出るだけ）。

    作る前に、次の3つを確かめる（満たさなければその著者は作らず、ハブに文字で出る）。
    - 作るノートが、次の回の `scan_notes` と同じ道（雛形を書いて frontmatter を読み、`note_names`）で
      その著者のキーを集める。集められないノートを作ると、毎回作り直しを試みる
    - 作るノートが、その著者のほかに集めるキー（ファイル名にしたときの `a: b` → `a b` のキー）が、
      他の著者のキーでも、既に集められているキーでもない。そうでないと、他の著者の本まで載せたり、
      同じ名前を2つのノートが集めたりする（`ABC*` と `Abc` から `ABC.md` と `Abc.md`）
    - 書く全文が UTF-8 で書ける。UTF-8 でない名前のテーマノートやレポートのファイルが一覧に入ると
      書くときに落ちる（`theme_store.can_encode`）

    計画した時点で、そのキーと名前を使用済みにする。書き込みに失敗したときは、後ろの重なる著者が
    その回は作られず、次の回に回る（安全側）。
    """
    covered = set().union(*(note.keys for note in notes))
    existing = {note.path.name for note in notes}
    planned: dict[str, Author] = {}              # この回に計画したファイル名 → 著者
    created: list[PlannedNote] = []
    skipped: list[tuple[Author, str]] = []
    already: list[Author] = []
    for author in sorted(authors.values(), key=lambda a: (a.name, a.key)):
        if author.key in covered:
            already.append(author)
            continue
        if not include_without_report and not any(b.id in reports for b in author.books):
            continue
        stem = note_stem(author.name)
        name = f"{stem}.md"
        if not stem:
            reason = "ファイル名にできる文字が無い"
        elif name == HUB_NAME:
            reason = f"ファイル名がハブ（{HUB_NAME}）と同じになる"
        elif name in existing:
            reason = f"{name} が既にあり、この名前を集めていない（そのノートの aliases に足すと集める）"
        elif name in planned:
            reason = f"{name} はこの回に「{planned[name].name}」のノートとして作る"
        elif os.path.lexists(directory / name):
            reason = f"{name} が既にある（著者ノートとして読めないファイル）"
        else:
            template = new_note_text(author, stem)
            meta, _ = report_store.split_front_matter(template)
            note = _note_of(directory / name, meta)
            if author.key not in note.keys:
                reason = "ノートに書くとこの名前を集められない"
            elif (note.keys - {author.key}) & (covered | authors.keys()):
                reason = "ファイル名にすると他の著者か既存のノートの名前と見分けがつかない"
            else:
                block = author_block(note, books_of(note, authors), reports, themes)
                text = theme_store.replace_block(template, block)
                if text is None:
                    reason = "一覧を書くとマーカーを読み戻せない（書名や著者名の文字のため）"
                elif not theme_store.can_encode(text):
                    reason = theme_store.UNENCODABLE_REASON
                else:
                    created.append(PlannedNote(author, note, text))
                    covered |= note.keys   # 同じ回の後ろの著者の判定に効かせる
                    planned[name] = author
                    continue
        skipped.append((author, reason))
    return CreatePlan(created, skipped, already)


def _create_notes(directory: Path, authors: dict[str, Author], notes: list[AuthorNote],
                  reports: dict[int, Path], themes: list[tuple[Path, set[int]]],
                  quiet_seconds: float, now: float) -> list[AuthorNote]:
    """レポートのある著者で、どのノートも集めていないもののノートを作る。作ったノートを返す。

    作ってよいかの判定は `plan_new_notes`。読んでからロックを取るまでに同じ名前のファイルが
    できていたら、`create_file` がその回は触らない。
    """
    plan = plan_new_notes(directory, authors, notes, reports, themes)
    return [p.note for p in plan.notes
            if theme_store.create_file(p.note.path, p.text, quiet_seconds, now)]


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
    scan = scan_notes(directory)   # ディレクトリを開けなければ例外（その回は何も書かない）
    _warn_lasting_doubts(scan.doubts)
    notes = scan.notes
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

    # 2. 自動作成: レポートのある著者で、どのノートも集めていないもの。
    #    ノートの名前を確かに読めた回だけ（読めていないノートの aliases が、その著者を集めているかもしれない）
    created: list[AuthorNote] = []
    if scan.reason_to_wait(now, quiet_seconds) is None:
        created = _create_notes(directory, authors, notes, reports, themes, quiet_seconds, now)
        written += [note.path for note in created]

    # 3. ハブ
    hub = directory / HUB_NAME
    block = hub_block(hub, notes + created, authors, reports)

    def make_hub(current: Optional[str]) -> Optional[str]:
        return theme_store.fill_block(hub, HUB_HEADER if current is None else current, block)

    if theme_store.update_file(hub, make_hub, quiet_seconds, now):
        written.append(hub)
    return written
