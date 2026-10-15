"""著者ノート（`reports/authors/*.md`）に「この著者の本」の一覧を差し込むストア

著者ごとのノート。レポートを著者でつなぎ、Obsidian で「同じ著者のレポート」をたどれるようにする
（著者ノート → レポートのリンクがグラフに出て、レポート側のバックリンクに著者ノートが出る）。
テーマノート（`theme_store.py`）と同じ仕組みで、**本文はユーザーが書き**、アプリが書くのは
マーカー `<!-- notes:books:start --> … <!-- notes:books:end -->` の間だけ。部品（マーカーの
差し替え・書き込み・本の行）は `theme_store` のものを共有する。

- **著者の分け方**: `Book.author` を NFKC 正規化して（書式文字は落として）`,` `、` `・` で分け
  （ただし `・` の両隣がカタカナか英字なら外国人名の一部として分けない。`ダニエル・L・エヴェレット` は
  1人、`熊野純彦・大澤真幸` は分ける）、`・` で2つ以上に分かれたまとまりの最後がカタカナだけなら
  出版社として著者から外し（`茸本朗・ハーベスト` → 著者は `茸本朗`）、末尾の役割表記（`／著` `／訳` `（編著）` `(著, 編集)` など）を変化が無くなるまで落とす。`作・絵` のように
  `・` でつないだ役割の並びは、`・` で分ける前に丸ごと落とす。括弧（`()` `[]` `「」` `『』` `【】` `〈〉`
  `《》`）の中の区切りでは分けない。英字1文字のイニシャル（`L` `L.`）は名前にしない。訳者も著者と同じに扱う
  （DB の著者欄に役割は無いことが多く、役割で分けると同じ人が本によって入ったり外れたりするため）。
  照合は空白・`・` `.` `=` を除き casefold したキーで行い、表記揺れを同じ人にまとめる。
  どれかの本の出版社欄と同じ名前は著者にしない（`collect_authors` だけ。ノートの名前には効かせない）。
- **ノートが集める名前**: ファイル名（stem）と frontmatter の `aliases`。別の文字種の表記
  （`H.G. Wells` と `H・G・ウェルズ`）は `aliases` でユーザーが1つにまとめる。
  旧い規則（`,` `、` だけで分ける）で作ったノートは、`・` で分ける前のまとまりのキーでも本を集める
  （`expand_notes`。`ジャレド ダイアモンド.md` に `ジャレド・ダイアモンド` の本も載り、断片のノートは作らない）。
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
設計: docs/design/0002-author-notes.md、著者の分け方は docs/design/0005-author-split-rules.md と
docs/design/0006-katakana-split-and-publisher-notes.md。出版社ノートは `publisher_store.py` が、この
モジュールの仕組みを `NoteKind` で切り替えて使う。
"""

import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Optional

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

# 区切り。NFKC のあとに使う（，→ ,、､ → 、、･ → ・ は NFKC が揃える）。· (U+00B7) と = は区切りにしない
_CLUSTER_SEPARATORS = ",、"   # 旧い規則（0002）の区切り。これで分けたまとまりが、旧い規則での1人分
_NAME_SEPARATOR = "・"        # 0005 で足した区切り。まとまりをさらに名前に分ける
_SEPARATOR_CHARS = _CLUSTER_SEPARATORS + _NAME_SEPARATOR
# 対になる括弧。中の区切りでは分けない（団体名の「」の中の `・` など）。役割表記の括弧は `(` `[` だけ
_OPEN_BRACKETS = "([「『【〈《"
_CLOSE_BRACKETS = ")]」』】〉》"
# カタカナ（ァ〜ヺ、ー、ヽヾヿ、小書きの拡張 ㇰ〜ㇿ）。・(U+30FB) は含めない
_KATAKANA = "ァ-ヺー-ヿㇰ-ㇿ"
_NAME_CHAR = re.compile(rf"[A-Za-z{_KATAKANA}]")    # ・ の両隣がこれなら分けない（0006）
_NEIGHBOR_SKIP = " .・"                              # 両隣を探すときに飛ばす文字（ほかに空白類）
_KATAKANA_ONLY = re.compile(rf"[{_KATAKANA}・= ]*[{_KATAKANA}][{_KATAKANA}・= ]*")   # 末尾の出版社の判定
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
_ROLE_WORD = re.compile(rf"(?:{_ROLES_ANY})")        # fullmatch で使う（役割の語だけの部分は出版社にしない）
_ROLE_LIST = rf"(?:{_ROLES_ANY})(?:\s*[{_SEPARATOR_CHARS}]\s*(?:{_ROLES_ANY}))*"
# `・` でつないだ役割の並び（`作・絵`、`訳・解説`）は、`・` で分ける前に落とす。分けると `絵` `解説` が
# 名前の断片として残り、別の人どうしをつなぐ「著者」になる
_ROLE_JOINED = rf"\s*{_NAME_SEPARATOR}\s*(?:{_ROLES_ANY})"
_ROLE_SUFFIX = re.compile(
    rf"(?:\s*/\s*(?:{_ROLES_ANY})(?:{_ROLE_JOINED})*"   # 「／著」「/訳」「／作・絵」
    rf"|\s*[(\[]\s*{_ROLE_LIST}\s*[)\]]"              # 「（編著）」「[著]」「(著, 編集)」（NFKC で全角括弧も半角になる）
    rf"|\s+(?:{_ROLES_ANY})(?:{_ROLE_JOINED})+"          # 「 作・絵」「 訳・解説」（空白のあとが役割2つ以上の並び）
    rf"|\s+(?:{_ROLES_SPACED}))\s*$"                   # 「 編」「 訳」（空白区切りは紛れない役割だけ）
)
_SPACES = re.compile(r"\s+")
_INITIAL_KEY = re.compile(r"[a-z]")           # 照合キーが英字1文字の名前（L、L.、Ｌ）はイニシャル。名前にしない
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
    `・` を除くのは、`・` を含む出版社名（`ディスカヴァー・トゥエンティワン`）のキーを、`・` で分けた
    名前のキーをつないだものと同じにするため（0005）。
    """
    return _KEY_DROP.sub("", _normalize(name)).casefold()


def _joins_name(text: str, i: int) -> bool:
    """text[i] の `・` が名前の一部か。両隣（空白・`.`・`・` を飛ばした最も近い文字）がどちらも
    カタカナか ASCII の英字なら True（`ダニエル・L・エヴェレット`、`H・G・ウェルズ`）。端の `・` は False。

    NFKC のあとの文字列に使う（半角カナ・全角英字は揃っている）。
    """
    def neighbor(indexes) -> str:
        for j in indexes:
            if not (text[j] in _NEIGHBOR_SKIP or text[j].isspace()):
                return text[j]
        return ""

    left = neighbor(range(i - 1, -1, -1))
    right = neighbor(range(i + 1, len(text)))
    return bool(left and right and _NAME_CHAR.fullmatch(left) and _NAME_CHAR.fullmatch(right))


def _split_outside_brackets(text: str, separators: str = _SEPARATOR_CHARS,
                            keep: Optional[Callable[[str, int], bool]] = None) -> list[str]:
    """`separators` の文字で分ける。対になった括弧 `(…)` `[…]` `「…」` などの中の区切りでは分けない。

    `keep(text, i)` が True を返す位置の区切りでも分けない（`・` の両隣が名前の文字のとき。0006）。

    `山田太郎 (著, 編集), 鈴木花子 (翻訳)` を括弧の中でも切ると、`山田太郎 (著` と `編集)` に
    なってしまう。`NHK「ヒューマン・ドキュメント」取材班` の `・` も同じ。
    閉じていない括弧は無視する（開き括弧が残りの著者を飲み込まないように）。
    """
    opened: list[int] = []
    delta = [0] * (len(text) + 1)   # 位置ごとの括弧の深さの増減（入れ子が深くても1回の走査で済む）
    for i, ch in enumerate(text):
        if ch in _OPEN_BRACKETS:
            opened.append(i)
        elif ch in _CLOSE_BRACKETS and opened:
            delta[opened.pop()] += 1
            delta[i + 1] -= 1
    parts: list[str] = []
    depth = 0
    begin = 0
    for i, ch in enumerate(text):
        depth += delta[i]
        if depth == 0 and ch in separators and not (keep and keep(text, i)):
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


def _clusters(author: Optional[str]) -> list[str]:
    """著者欄を、旧い規則（0002）が1人としていたまとまり（括弧の外の `,` `、` で分け、役割表記を落とした文字列）に分ける。"""
    if not author:
        return []
    return [_strip_roles(_SPACES.sub(" ", cluster).strip())
            for cluster in _split_outside_brackets(_normalize(author), _CLUSTER_SEPARATORS)]


def _split_cluster(cluster: str) -> tuple[list[str], Optional[str]]:
    """役割を落としたまとまりを `・` で名前に分ける。(名前の並び, 末尾の出版社名か None)。

    `・` の両隣がカタカナか英字なら分けない（`_joins_name`）。2つ以上に分かれ、最後の部分がカタカナだけ
    （`_KATAKANA_ONLY`）で役割の語そのものでなければ、最後の部分を出版社として名前の並びから外して返す
    （`茸本朗・ハーベスト`）。名前の並びにはキーが空・イニシャルのものも残る（捨てるのは呼び出し側）。
    これは著者欄の構文だけで決まる規則で、DB の他の本の出版社欄は見ない。
    """
    names = [_strip_roles(_SPACES.sub(" ", part).strip())
             for part in _split_outside_brackets(cluster, _NAME_SEPARATOR, _joins_name)]
    last = names[-1]
    if len(names) >= 2 and _KATAKANA_ONLY.fullmatch(last) and not _ROLE_WORD.fullmatch(last):
        return names[:-1], last
    return names, None


def _fragments(author: Optional[str]) -> list[tuple[str, str]]:
    """著者欄を (名前, その名前が出たまとまりの照合キー) に分ける。名前の重複は除かない。

    まとまりは、旧い規則（0002）が1人としていた単位（`_clusters`）。
    旧い規則で作ったノート（`ジャレド ダイアモンド.md`）は、このキーでも本を集める（`expand_notes`）。
    まとまりごとに先に役割表記を落とすのは、`作・絵` のような `・` でつないだ役割の並びを、`・` で
    分ける前に丸ごと落とすため。名前はまとまりを `_split_cluster` で分けたもので、
    キーが空の名前とイニシャルを捨てる。
    """
    fragments: list[tuple[str, str]] = []
    for cluster in _clusters(author):
        cluster_key = author_key(cluster)
        for name in _split_cluster(cluster)[0]:
            key = author_key(name)
            if key and not _INITIAL_KEY.fullmatch(key):
                fragments.append((name, cluster_key))
    return fragments


def _unique_names(fragments: list[tuple[str, str]]) -> list[str]:
    """名前をキーで重複を除き、出てきた順に返す。"""
    names: list[str] = []
    seen: set[str] = set()
    for name, _ in fragments:
        key = author_key(name)
        if key not in seen:
            seen.add(key)
            names.append(name)
    return names


def split_authors(author: Optional[str]) -> list[str]:
    """著者欄を人ごとの表示名に分ける。キーで重複を除き、出てきた順に返す。

    書式文字を除去 → NFKC → 括弧の外の `,` `、` で分割 → 空白を1つに詰めて strip → 末尾の役割表記を
    繰り返し落とす（`作・絵` のような `・` でつないだ役割の並びも、ここで丸ごと落とす）→ 括弧の外の
    `・` で分割 → 末尾の役割表記を落とす。ただし両隣がカタカナか英字の `・` では分けない
    （`ダニエル・L・エヴェレット` は1人。0006）。`・` で分かれた最後がカタカナだけなら出版社として
    外す（`茸本朗・ハーベスト` → `茸本朗`。0006）。キーが空になるもの（空文字・役割だけ）と、キーが
    英字1文字のもの（`山田・L・鈴木` の `L`。イニシャル）は捨てる。
    結果の各名前をもう一度この関数に通しても変わらない（ノートの stem や aliases に使えるように）。
    """
    return _unique_names(_fragments(author))


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
    # この名前が出たまとまり（旧い規則で1人としていた単位。`_fragments`）の照合キー。旧い規則で作った
    # ノートが、`・` で分ける前のキーで本を集めるのに使う（`expand_notes`）
    legacy_keys: frozenset[str] = frozenset()


def _publisher_keys(books: list[Book]) -> frozenset[str]:
    """本の出版社欄（文字列全体）の照合キー。null・空・キーが空になるもの（空白だけ）は入れない。"""
    return frozenset(key for key in (author_key(b.publisher) for b in books if b.publisher) if key)


def _publisher_runs(keys: list[str], publishers: frozenset[str]) -> list[tuple[int, int]]:
    """名前のキーの並びのうち、隣り合う1つ以上をつないだものが出版社のキーと一致する範囲 (begin, end)（両端を含む）。

    `ディスカヴァー・トゥエンティワン` は `・` で2つに分かれることがあるが、つないだキーは出版社欄のキー
    （author_key は `・` を除く）と同じになる。つないだ長さが出版社のキーの最長を超えたら打ち切る。
    """
    longest = max(map(len, publishers), default=0)
    runs: list[tuple[int, int]] = []
    for begin in range(len(keys)):
        joined = ""
        for end in range(begin, len(keys)):
            joined += keys[end]
            if len(joined) > longest:
                break
            if joined in publishers:
                runs.append((begin, end))
    return runs


def _drop_publishers(names: list[str], publishers: frozenset[str]) -> list[str]:
    """著者欄から分けた名前のうち、出版社の名前を落とす（出てきた順は保つ）。

    隣り合う1つ以上の名前のキーをつないだものが出版社のキーと一致したら、その名前をまとめて落とす
    （`_publisher_runs`）。
    """
    dropped: set[int] = set()
    for begin, end in _publisher_runs([author_key(name) for name in names], publishers):
        dropped.update(range(begin, end + 1))
    return [name for i, name in enumerate(names) if i not in dropped]


def publishers_in_author(author: Optional[str], publishers: frozenset[str]) -> list[str]:
    """著者欄から著者として外した出版社の名前（表示名）。出てきた順、キーで重複なし。キーが空のものは入れない。

    - 0006: まとまりの末尾のカタカナ（`_split_cluster` の出版社名）。その本の著者欄の構文だけで決まる
    - 0005: 分けた名前のうち、隣り合う名前のキーをつないだものが `publishers`（出版社欄のキーの集合）と
      一致した並び。表示名は並びの名前を `・` でつないだもの
    """
    found: dict[str, str] = {}
    for cluster in _clusters(author):
        publisher = _split_cluster(cluster)[1]
        if publisher and author_key(publisher):
            found.setdefault(author_key(publisher), publisher)
    names = _unique_names(_fragments(author))
    for begin, end in _publisher_runs([author_key(name) for name in names], publishers):
        name = "・".join(names[begin:end + 1])
        if author_key(name):
            found.setdefault(author_key(name), name)
    return list(found.values())


def collect_authors(books: list[Book]) -> dict[str, Author]:
    """id 順に本を見て、`split_authors` の名前ごとに本を集める。キー → Author（出てきた順）。

    出版社の名前は著者にしない（`_drop_publishers`）。比べる出版社は、渡された本すべての出版社欄
    （呼び出し側は本棚の全部の本を渡す。rebuild と scripts/create_notes.py はそうしている）。
    著者欄が null・空・区切りだけ・捨てる名前（イニシャル・出版社）だけの本は、どの著者にも入らない。
    """
    publishers = _publisher_keys(books)
    names: dict[str, str] = {}
    collected: dict[str, list[Book]] = {}
    legacy: dict[str, set[str]] = {}
    for book in sorted(books, key=lambda b: b.id):
        fragments = _fragments(book.author)
        clusters: dict[str, set[str]] = {}
        for name, cluster_key in fragments:
            clusters.setdefault(author_key(name), set()).add(cluster_key)
        # 1冊の中の同じ人は _unique_names で1つになっている
        for name in _drop_publishers(_unique_names(fragments), publishers):
            key = author_key(name)
            names.setdefault(key, name)
            collected.setdefault(key, []).append(book)
            legacy.setdefault(key, set()).update(clusters[key])
    return {key: Author(key, names[key], tuple(found), frozenset(legacy[key]))
            for key, found in collected.items()}


# ── ノート側: ノートが集める名前 ────────────────────────────

@dataclass(frozen=True)
class AuthorNote:
    path: Path
    names: tuple[str, ...]     # stem が先頭、続いて aliases。キーで重複を除いた順
    keys: frozenset[str]       # names の author_key
    mtime: Optional[float] = None   # 読んだときの更新時刻。scan_notes が読んだノートだけ入る
    # stem と aliases の、旧い規則でのまとまり（`_fragments`）の照合キー。`expand_notes` が使う
    legacy_keys: frozenset[str] = frozenset()


def _note_texts(meta: dict, stem: str) -> list[str]:
    """ノートが名前として書いている文字列。stem が先頭、続いて frontmatter の `aliases`。

    aliases は文字列なら1つ、配列なら各要素（None は飛ばし、数値などは str にする）。
    それ以外は無視する。
    """
    raw = meta.get("aliases")
    if isinstance(raw, str):
        aliases = [raw]
    elif isinstance(raw, list):
        aliases = [str(item) for item in raw if item is not None]
    else:
        aliases = []
    return [stem, *aliases]


def note_names(meta: dict, stem: str) -> tuple[str, ...]:
    """stem と frontmatter の `aliases` を、著者欄と同じ規則（`split_authors`）で名前にする。

    文字列の中の `,` `、` `・` も区切りとして扱う（著者欄が同じ規則で分かれるので、区切りを含む
    名前のままではどの著者とも一致しない）。カタカナ名の `・` は分けず、末尾のカタカナの出版社は
    名前にしない（`茸本朗・ハーベスト.md` は `茸本朗` だけを集める。0006）。
    """
    names: list[str] = []
    seen: set[str] = set()
    for item in _note_texts(meta, stem):
        for name in split_authors(item):
            key = author_key(name)
            if key not in seen:
                seen.add(key)
                names.append(name)
    return tuple(names)


def _cluster_keys(text: str) -> frozenset[str]:
    """文字列の、旧い規則でのまとまりの照合キー（`expand_notes` 用）。"""
    return frozenset(cluster_key for _, cluster_key in _fragments(text))


@dataclass(frozen=True)
class NoteKind:
    """ノートの種類（著者・出版社）ごとに違うところ。仕組み（scan・plan・rebuild）は共通。

    出版社ノート（`publisher_store.py`）は仕組みを写さずにこれを渡す。安全策の入った
    `plan_new_notes` / `scan_notes` / `rebuild` を2か所に写すと、片方だけ直る不具合が出るため。
    """
    label: str          # "著者" / "出版社"。見出し・文言・ログに使う
    dirname: str        # "authors" / "publishers"
    hub_name: str       # "著者一覧.md" / "出版社一覧.md"
    note_type: str      # "author-note" / "publisher-note"
    hub_header: str     # ハブを新しく作るときの全文の頭
    source: str         # マーカー内のコメント「DB の{source}から書き直す」
    empty_hint: str     # 本が無いノートの文言の「（集める名前: …）。」のあと
    note_names: Callable[[dict, str], tuple[str, ...]]   # (frontmatter, stem) → 集める名前
    legacy_keys: Callable[[str], frozenset[str]]         # 旧い規則のまとまりのキー（expand_notes 用）。出版社は空
    collect: Callable[[list[Book]], dict[str, Author]]   # 本 → キー → Author（名前と本の束）


AUTHOR = NoteKind(
    label="著者", dirname=AUTHORS_DIRNAME, hub_name=HUB_NAME, note_type=NOTE_TYPE,
    hub_header=HUB_HEADER, source="著者欄",
    empty_hint="集める名前はファイル名と frontmatter の `aliases` で決まります。出版社欄と同じ名前は著者にしません。",
    note_names=note_names, legacy_keys=_cluster_keys, collect=collect_authors,
)


def _note_of(path: Path, meta: dict, mtime: Optional[float] = None, kind: NoteKind = AUTHOR) -> AuthorNote:
    names = kind.note_names(meta, path.stem)
    legacy = frozenset(key for text in _note_texts(meta, path.stem) for key in kind.legacy_keys(text))
    return AuthorNote(path, names, frozenset(author_key(name) for name in names), mtime, legacy)


def expand_notes(notes: list[AuthorNote], authors: dict[str, Author]) -> list[AuthorNote]:
    """旧い規則でのまとまりが同じ著者も、ノートが集める著者に足す（0005 の移行）。

    旧い規則は空白・`・` `.` を除いたキーで、`ジャレド ダイアモンド` と `ジャレド・ダイアモンド` を
    1人の著者にまとめ、ノートの名前は最初の本の表記だった。いまは `・` で分けるので、ノートの名前
    （`ジャレド ダイアモンド`）と、もう一方の表記から出る名前（`ジャレド` `ダイアモンド`）が一致せず、
    ノートから本が抜け、断片の著者ノートが作られてしまう。そこで、ノートの stem と aliases の旧い
    まとまりのキーを持つ著者を、そのノートが集める著者（`keys`）に足す。`names`（「集める名前」の表示）は変えない。
    """
    by_legacy: dict[str, list[str]] = {}
    for author in authors.values():
        for legacy in author.legacy_keys:
            by_legacy.setdefault(legacy, []).append(author.key)
    expanded = []
    for note in notes:
        extra = {key for legacy in note.legacy_keys for key in by_legacy.get(legacy, ())}
        expanded.append(replace(note, keys=note.keys | extra) if extra - note.keys else note)
    return expanded


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
# ノートの種類（kind.dirname）ごと。1回の tick で著者と出版社の両方を呼ぶので、混ぜると互いに消し合う
_seen_doubts: dict[str, set[tuple[Path, str]]] = {}
_warned_doubts: dict[str, set[tuple[Path, str]]] = {}


def _warn_lasting_doubts(doubts: list[tuple[Path, str]], kind: NoteKind = AUTHOR) -> None:
    """2回続けて残っている怪しいノートを、直るまでに1回だけ警告する。

    書きかけのノートは数秒で直るので黙っていてよいが、frontmatter が壊れたままのノートや
    先頭が `---`（水平線）のノートは、直すまで自動作成を止め続ける。黙っていると、
    ノートが作られない理由が分からない。1回だけの doubt（保存の途中など）では警告しない。
    """
    current = set(doubts)
    seen = _seen_doubts.setdefault(kind.dirname, set())
    warned = _warned_doubts.setdefault(kind.dirname, set())
    for path, reason in sorted(current & seen - warned):
        logger.warning("%sノートの自動作成を止めている（直すと次の回で作る）: %s: %s",
                       kind.label, path.name, reason)
    warned.intersection_update(current)
    warned.update(current & seen)
    seen.clear()
    seen.update(current)


def scan_notes(directory: Path, kind: NoteKind = AUTHOR) -> NoteScan:
    """`authors/`（出版社は `publishers/`）直下のノート（ハブと隠しファイルを除く）をファイル名順に読む。

    サブフォルダは見ない。1つのファイルが読めなくても（デコードできない・自分を指す symlink など）
    そこで止めず、他のノートは読む。読めなかったファイルは `doubts` に理由つきで残し、
    自動作成を控える理由にする（全部が見えなくなると、まとめたはずの著者のノートまで作り直す）。
    ディレクトリそのものを開けないときは例外を上げる（その回の更新を止める）。
    """
    with os.scandir(directory) as it:
        entries = sorted(
            (e for e in it
             if e.name.endswith(".md") and not e.name.startswith(".") and e.name != kind.hub_name),
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
        notes.append(_note_of(path, meta, mtime, kind))
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
                 themes: list[tuple[Path, set[int]]], kind: NoteKind = AUTHOR) -> str:
    """著者（出版社）ノートに差し込む一覧（マーカー込み）。themes は (テーマノートのパス, その本の id 集合)。"""
    start = note.path.parent
    # 名前を `、` でつなぐのは、名前の中に括弧の外の `、` は残らない（`split_authors` が分ける）ので、
    # つないでも名前の境目が曖昧にならないため
    lines = [
        f"## この{kind.label}の本",
        "",
        f"<!-- ここから end まではアプリが DB の{kind.source}から書き直す（手で編集しない）。"
        f"集める名前: {'、'.join(note.names)} -->",
        "",
    ]
    if not books:
        lines.append(
            f"この名前の本はまだありません（集める名前: {'、'.join(escape_text(n) for n in note.names)}）。"
            + kind.empty_hint
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
              reports: dict[int, Path], kind: NoteKind = AUTHOR) -> str:
    """ハブ（著者一覧・出版社一覧）に差し込む一覧（マーカー込み）。"""
    start = hub.parent
    lines = [f"## {kind.label}ノート", ""]
    if notes:
        rows = [(note, books_of(note, authors)) for note in notes]
        for note, books in sorted(rows, key=lambda row: (-len(row[1]), row[0].path.stem)):
            lines.append(f"- {md_link(note.path.stem, note.path, start)} — {_counts_text(books, reports)}")
    else:
        lines.append("まだありません。")

    covered = set().union(*(note.keys for note in notes))
    lines += ["", f"## ノートの無い{kind.label}", ""]
    uncovered = [a for a in authors.values() if a.key not in covered]
    if uncovered:
        for author in sorted(uncovered, key=lambda a: (-len(a.books), a.name)):
            lines.append(f"- {escape_text(author.name)} — {_counts_text(list(author.books), reports)}")
    else:
        lines.append(f"すべての{kind.label}にノートがあります。")
    return wrap_block(lines)


# ── 自動作成 ────────────────────────────────────────────────

def _new_note_meta(author: Author, stem: str, kind: NoteKind = AUTHOR) -> dict:
    meta: dict = {"type": kind.note_type}
    # ファイル名にするとき名前が変わった（使えない文字を落とした・切った）ときだけ、元の名前を
    # aliases に入れる。入れないと次の回に「どのノートも集めていない」と判定され続ける
    if author_key(stem) != author.key:
        meta["aliases"] = [author.name]
    return meta


def new_note_text(author: Author, stem: str, kind: NoteKind = AUTHOR) -> str:
    """自動作成するノートの雛形（マーカーはまだ無い）。"""
    return (report_store.front_matter_text(_new_note_meta(author, stem, kind))
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
                   *, include_without_report: bool = False, kind: NoteKind = AUTHOR) -> CreatePlan:
    """どのノートも集めていない著者のノートの計画。何も書かない。

    既定は、レポートが1冊以上ある著者だけ（アプリの自動作成）。`include_without_report` が
    True なら全部の著者（`scripts/create_notes.py` の一括作成）。レポートが無くて対象から外れた
    著者は、`skipped` にも入れない（ハブに文字で出るだけ）。

    旧い規則でのまとまりが同じ著者も、既存のノートが集めているものとして扱う（`expand_notes`）。

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
    notes = expand_notes(notes, authors)
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
        elif name == kind.hub_name:
            reason = f"ファイル名がハブ（{kind.hub_name}）と同じになる"
        elif name in existing:
            reason = f"{name} が既にあり、この名前を集めていない（そのノートの aliases に足すと集める）"
        elif name in planned:
            reason = f"{name} はこの回に「{planned[name].name}」のノートとして作る"
        elif os.path.lexists(directory / name):
            reason = f"{name} が既にある（著者ノートとして読めないファイル）"
        else:
            template = new_note_text(author, stem, kind)
            meta, _ = report_store.split_front_matter(template)
            note = _note_of(directory / name, meta, kind=kind)
            if author.key not in note.keys:
                reason = "ノートに書くとこの名前を集められない"
            elif (note.keys - {author.key}) & (covered | authors.keys()):
                reason = "ファイル名にすると他の著者か既存のノートの名前と見分けがつかない"
            else:
                block = author_block(note, books_of(note, authors), reports, themes, kind)
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
                  quiet_seconds: float, now: float, kind: NoteKind = AUTHOR) -> list[AuthorNote]:
    """レポートのある著者（出版社）で、どのノートも集めていないもののノートを作る。作ったノートを返す。

    作ってよいかの判定は `plan_new_notes`。読んでからロックを取るまでに同じ名前のファイルが
    できていたら、`create_file` がその回は触らない。
    """
    plan = plan_new_notes(directory, authors, notes, reports, themes, kind=kind)
    return [p.note for p in plan.notes
            if theme_store.create_file(p.note.path, p.text, quiet_seconds, now)]


# ── 差し込み ────────────────────────────────────────────────

def rebuild(db: Session, *, quiet_seconds: float = theme_store.QUIET_SECONDS,
            now: Optional[float] = None, kind: NoteKind = AUTHOR) -> list[Path]:
    """著者（`kind` が出版社なら出版社）ノートの一覧・自動作成・ハブを書き直す。書いた（作った）ファイルを返す。"""
    now = time.time() if now is None else now
    directory = report_store.reports_dir() / kind.dirname
    directory.mkdir(parents=True, exist_ok=True)
    books = list(db.scalars(select(Book).options(selectinload(Book.tags)).order_by(Book.id)))
    reports = report_store.report_paths()
    authors = kind.collect(books)
    scan = scan_notes(directory, kind)   # ディレクトリを開けなければ例外（その回は何も書かない）
    _warn_lasting_doubts(scan.doubts, kind)
    notes = expand_notes(scan.notes, authors)
    # テーマの所属は、著者ごとに books_for を呼び直さないよう1回だけ計算する
    themes = [(t.path, {b.id for b in theme_store.books_for(t.tags, books)})
              for t in theme_store.scan_notes(theme_store.themes_dir())]

    written = []
    # 1. 既存のノート（ユーザーが作ったもの・前に作ったもの）
    for note in notes:
        block = author_block(note, books_of(note, authors), reports, themes, kind)

        def make_note(current: Optional[str], path: Path = note.path, block: str = block) -> Optional[str]:
            # 読んでからロックを取るまでに消されたノートは、ここでは作り直さない（2. で作る）
            return None if current is None else theme_store.fill_block(path, current, block)

        if theme_store.update_file(note.path, make_note, quiet_seconds, now):
            written.append(note.path)

    # 2. 自動作成: レポートのある著者で、どのノートも集めていないもの。
    #    ノートの名前を確かに読めた回だけ（読めていないノートの aliases が、その著者を集めているかもしれない）
    created: list[AuthorNote] = []
    if scan.reason_to_wait(now, quiet_seconds) is None:
        created = _create_notes(directory, authors, notes, reports, themes, quiet_seconds, now, kind)
        written += [note.path for note in created]

    # 3. ハブ
    hub = directory / kind.hub_name
    block = hub_block(hub, notes + created, authors, reports, kind)

    def make_hub(current: Optional[str]) -> Optional[str]:
        return theme_store.fill_block(hub, kind.hub_header if current is None else current, block)

    if theme_store.update_file(hub, make_hub, quiet_seconds, now):
        written.append(hub)
    return written
