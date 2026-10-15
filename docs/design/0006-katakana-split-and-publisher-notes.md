# 0006 カタカナ名の `・` を分けない・末尾のカタカナを出版社にする・出版社ノート

## 1. 状態・日付

- 状態: 実装済み（2026-10-15）
- 日付: 2026-10-15
- 関連: [0005 著者の分け方の見直し](0005-author-split-rules.md) 決定1・2（`・` の分け方。**この設計書で変える**）・決定3・4（残す）、
  [0002 著者ノート](0002-author-notes.md)（仕組みを出版社にも使う）、[0003 一括作成](0003-bulk-create-notes.md)（`scripts/create_notes.py` に出版社を足す）、
  SPEC §4「著者ノート」、`backend/app/author_store.py`

## 2. 背景と目的

ユーザーの言葉（0005 の規則の見直し）:

> - カタカナに挟まれた or カタカナが連続する場合は（「・」で）分けない
> - 最後がカタカナの場合は出版社と判断して分ける
> - 出版社もリンク（ノート）を作っておきたい。表記ゆれはしょうがない。

0005 は括弧の外の `・` をすべて区切りにした。このため `ダニエル・L・エヴェレット` は `ダニエル` と `エヴェレット` に、
`マイケル・サンデル` は `マイケル` と `サンデル` に分かれ、同じ名を持つ別人（`マイケル・ルイス`）の本が同じノートに載る（0005 §5.7）。
また、著者欄に `茸本朗・ハーベスト` のように出版社が `・` でつながっていても、出版社欄に同じ表記が無ければ外れない。

目的は3つ。

1. カタカナ・英字イニシャルの名前（外国人名）を1人の名前のまま扱う。
2. 著者欄の末尾に `・` でつながったカタカナの出版社名を著者から外す。
3. 出版社ごとのノート `reports/publishers/<出版社>.md` を、著者ノートと同じ仕組みで作る。

## 3. 決定

1. **`・` の両隣が「名前の文字」なら分けない**。名前の文字 = カタカナ（長音 `ー` を含む）か ASCII の英字。判定は NFKC のあと
   （半角カナ・全角英字もこれになる）。両隣は、空白・`.`・`・` を飛ばした最も近い文字。どちらかが無い（端の `・`）か名前の文字でなければ、
   これまでどおり分ける。`,` `、` は従来どおり常に区切り。括弧の中で分けないのも従来どおり。
   - 分けない: `ダニエル・L・エヴェレット`、`H・G・ウェルズ`、`マイケル・サンデル`、`ダニエル・L.・エヴェレット`、`クロード・レヴィ=ストロース`
   - 分ける: `熊野純彦・大澤真幸`、`楊・文`、`山田・L・鈴木`（→ `山田`・`L`・`鈴木`。`L` は決定3で落ちる）
2. **末尾のカタカナを出版社にする**。`,` `、` で分けたまとまりが `・` で**2つ以上**に分かれ、**最後の部分がカタカナだけ**
   （カタカナ・`ー`・`・`・`=`・空白だけで、カタカナを1文字以上含む）なら、最後の部分を出版社として著者から外す。
   最後の部分が役割の語だけ（`イラスト`・`イラストレーター`）なら外さない（0005 のまま名前として残る）。
   - 例: `茸本朗・ハーベスト` → 著者 `茸本朗`、出版社 `ハーベスト`。
   - 「直前の部分の末尾がカタカナでない」はこの定義で自動的に満たされる（決定1により、最後の部分の先頭はカタカナなので、そこで
     分かれたのは直前の文字が名前の文字でないときだけ）。直前が英字（`茸本朗・HS` の逆、`ABC・ハーベスト`）なら決定1で分かれず、外れない。
   - 1つのまとまりに `・` で分かれる部分が1つしかない（`ハーベスト` だけ、`マイケル・サンデル`）なら外さない。
   - 外すのは**その本の著者欄の中だけ**（構文で決まる。DB の他の本には効かせない）。0005 の出版社欄の集合（`_publisher_keys`）には足さない。
3. **0005 の残す規則**: 英字1文字のイニシャルを捨てる規則（`_INITIAL_KEY`）は残す。決定1でほぼ出なくなるが、漢字の間の `・L・`
   （`山田・L・鈴木`）や `A, B` のような欄で1文字の名前を作らないために要る。消すとテストを直す差分だけ増える。
   出版社欄と一致する名前を外す規則（0005 決定4・`_drop_publishers`）も残し、決定2のあとにかける。照合キー（`author_key`）は変えない。
4. **決定1・2は `split_authors`（`_fragments`）の中で行う**。DB 側（著者欄）とノート側（`note_names`。ファイル名・aliases）の両方に効く。
   決定2はデータ（出版社欄）に依存しない構文の規則なので、0005 決定5（`note_names` に出版社欄の除外を効かせない）の理由に当たらない。
5. **出版社ノート**: `reports/publishers/<出版社>.md` とハブ `reports/publishers/出版社一覧.md`。著者ノートと同じ仕組み
   （マーカー、`theme_store` の部品、`update_file` / `fill_block`、`ThemeWatcher` のジョブ、自動作成の安全策・`plan_new_notes`）で作る。
   - 出版社の名前 = (a) `Book.publisher`（文字列全体。分けない）、(b) 決定2で著者欄から外した名前、(c) 0005 で出版社欄と一致して著者欄から外した名前。
   - 照合キーは `author_key`（`・`・空白・`.`・`=` を除き casefold）。表記揺れ（`学研プラス` と `株式会社学研プラス`、`HS` と `エイチエス`）はまとめない。
     まとめたいときは著者ノートと同じく `aliases` で手でまとめる。
   - ノートが集める名前 = ファイル名と `aliases`。**`,` `、` `・` で分けない**（文字列ごとに1つの名前。出版社欄を分けないのと揃える）。
   - 自動作成の範囲は著者ノートと同じ: **レポートが1冊以上ある出版社で、どのノートも集めていないもの**。全部の出版社は
     `scripts/create_notes.py` で作る。
   - マーカーの中: 「この出版社の本」（レポートへの相対リンク）と「関連するテーマ」。
6. **実装は `author_store.py` の仕組みを「ノートの種類」（`NoteKind`）で引数化し、出版社の分は新しい `publisher_store.py` に置く**。
   著者側の関数は既定値 `kind=AUTHOR` で今の呼び出し・テストのまま動く。安全策の入った `plan_new_notes` / `scan_notes` / `rebuild` を写さない
   （写すと片方だけ直る不具合が出る）。
7. **環境変数 `NOTES_PUBLISHERS_WATCH` を足す**。`0`（`false` / `off` / `no`）で出版社ノートだけ止まる。`NOTES_THEMES_WATCH=0` は3つとも止める。
8. **既存のノートは変えない**（改名・分割・削除しない。マーカーの中だけ従来どおり書き直す）。旧い規則（0002）で作った外国人名のノート
   （`ダニエル・L・エヴェレット.md`）は、再び名前全体で一致する。0005 で作られた断片のノート（`ダニエル.md`・`エヴェレット.md`）は
   本が無くなり、名前全体のノートがレポートのある著者には自動で作られる（§5.6）。
9. 変えないもの: frontend・API・DB のスキーマ、テーマノートの規則、`theme_store.py`（コメントの1行を除く）。

## 4. 全体像

```
 Book.author ─▶ _fragments（split_authors）
   "茸本朗・ハーベスト, 松浦俊輔"
     1. 書式文字を落として NFKC
     2. 括弧の外の , 、 でまとまりに分け、まとまりごとに役割表記を落とす（0005 のまま）
     3. まとまりを括弧の外の ・ で分ける。ただし両隣が カタカナ/英字 の ・ では分けない   ← 決定1
     4. 2つ以上に分かれ、最後の部分がカタカナだけ → 出版社（著者から外す）              ← 決定2
     5. 役割表記を落とし、キーが空・英字1文字・重複なら捨てる（0005 のまま）
        │                                   │
        ▼ 著者の名前                         ▼ 出版社の名前（publishers_in_author）
   collect_authors ─ _drop_publishers ─┐     ハーベスト
   （0005: 出版社欄と一致を外す）       └──▶ 外した名前の並び（0005）
        │                                   │       Book.publisher（文字列全体）
        ▼                                   ▼            │
   author_store.rebuild(kind=AUTHOR)     publisher_store.collect_publishers ◀┘
   reports/authors/*.md                  publisher_store.rebuild → author_store.rebuild(kind=PUBLISHER)
   reports/authors/著者一覧.md            reports/publishers/*.md, reports/publishers/出版社一覧.md

 ThemeWatcher（5秒ごと）: theme_store.rebuild → author_store.rebuild → publisher_store.rebuild
 scripts/create_notes.py: テーマ → 著者 → 出版社（同じ plan_new_notes に kind を渡す）
```

## 5. 詳細

### 5.1 分け方の変更（`backend/app/author_store.py`）

```python
# カタカナ（ァ〜ヺ、ー、ヽヾヿ、小書きの拡張 ㇰ〜ㇿ）。・(U+30FB) は含めない
_KATAKANA = "ァ-ヺー-ヿㇰ-ㇿ"
_NAME_CHAR = re.compile(rf"[A-Za-z{_KATAKANA}]")         # ・ の両隣がこれなら分けない（0006）
_NEIGHBOR_SKIP = " .・"                                   # 両隣を探すときに飛ばす文字（ほかに空白類）
_KATAKANA_ONLY = re.compile(rf"[{_KATAKANA}・= ]*[{_KATAKANA}][{_KATAKANA}・= ]*")   # 末尾の出版社の判定
_ROLE_WORD = re.compile(rf"(?:{_ROLES_ANY})")             # fullmatch で使う


def _joins_name(text: str, i: int) -> bool:
    """text[i] の `・` が名前の一部か。両隣（空白・`.`・`・` を飛ばした最も近い文字）がどちらも
    カタカナか ASCII の英字なら True（`ダニエル・L・エヴェレット`、`H・G・ウェルズ`）。端の `・` は False。"""


def _split_outside_brackets(text: str, separators: str = _SEPARATOR_CHARS,
                            keep: Optional[Callable[[str, int], bool]] = None) -> list[str]:
    # 既存の判定 `if depth == 0 and ch in separators:` に `and not (keep and keep(text, i))` を足すだけ


def _split_cluster(cluster: str) -> tuple[list[str], Optional[str]]:
    """役割を落としたまとまりを `・` で名前に分ける。(名前の並び, 末尾の出版社名か None)。

    `_split_outside_brackets(cluster, _NAME_SEPARATOR, _joins_name)` で分け、各部分の空白を詰めて
    役割表記を落とす。2つ以上に分かれ、最後の部分が `_KATAKANA_ONLY` に fullmatch し、
    `_ROLE_WORD` に fullmatch しなければ、最後の部分を出版社として名前の並びから外して返す。
    名前の並びにはキーが空・イニシャルのものも残る（捨てるのは呼び出し側）。
    """


def publishers_in_author(author: Optional[str], publishers: frozenset[str]) -> list[str]:
    """著者欄から著者として外した出版社の名前（表示名）。出てきた順、キーで重複なし。キーが空のものは入れない。

    - 決定2: まとまりごとの `_split_cluster` の出版社名
    - 0005: `_unique_names(_fragments(author))` のうち、隣り合う名前のキーをつないだものが `publishers`
      （出版社欄のキーの集合）と一致した並び。表示名は並びの名前を `・` でつないだもの
    """
```

- `_fragments` の内側のループを `for name in _split_cluster(cluster)[0]:` にする（キーが空・イニシャルを捨てる判定はそのまま）。
  `_fragments` / `split_authors` / `note_names` / `collect_authors` のシグネチャは変えない。
- `_drop_publishers` は「一致した並び」を探すところを `_publisher_runs(keys, publishers) -> list[tuple[int, int]]`（並びの
  `begin` と `end`。両端を含む）に切り出し、`_drop_publishers` と `publishers_in_author` の両方で使う。挙動は変えない。
- `_ROLE_LIST` / `_ROLE_SUFFIX` / `_INITIAL_KEY` / `author_key` / `_KEY_DROP` / `note_stem` は変えない。
- 冪等性: 分けた名前に、括弧の外で両隣が名前の文字でない `・` は残らない。出版社は外れている。だから
  `split_authors(", ".join(names)) == names` は保たれる（§5.7 の全例で確認）。
- モジュールの docstring の「著者の分け方」を新しい規則にし、「設計:」の行に 0006 を足す。

### 5.2 「末尾のカタカナは出版社」の正確な定義と誤判定

定義（決定2）: まとまり（`,` `、` で分けて役割を落としたもの）を決定1の規則で `・` で分け、部分が2つ以上で、最後の部分が
カタカナ（`ー` を含む）・`・`・`=`・空白だけからなり、カタカナを1文字以上含み、役割の語そのものではない。

| 著者欄 | 著者 | 出版社 | 正しいか |
|---|---|---|---|
| `茸本朗・ハーベスト` | `茸本朗` | `ハーベスト` | 正（意図した例） |
| `山田太郎・ディスカヴァー・トゥエンティワン 編` | `山田太郎` | `ディスカヴァー・トゥエンティワン` | 正 |
| `山田 (著)・ハーベスト` | `山田` | `ハーベスト` | 正 |
| `山田・ﾊｰﾍﾞｽﾄ`（半角） | `山田` | `ハーベスト` | 正 |
| `熊野純彦・サンデル` | `熊野純彦` | `サンデル` | **誤**（漢字名とカタカナ名の2人） |
| `村上春樹・ジェイ・ルービン` | `村上春樹` | `ジェイ・ルービン` | **誤**（同上。カタカナ名の中の `・` は分けないので名前全体が外れる） |
| `ジェイ・ルービン・村上春樹` | `ジェイ・ルービン`, `村上春樹` | なし | 正（最後が漢字） |
| `山田・ハーベスト・鈴木` | `山田`, `ハーベスト`, `鈴木` | なし | 出版社が途中にあると外れない |
| `茸本朗・HS` | `茸本朗`, `HS` | なし | 英字はカタカナではない（出版社欄に `HS` があれば 0005 で外れる） |
| `ハーベスト` / `マイケル・サンデル` | そのまま1人 | なし | 正（分かれていない） |
| `山田太郎・イラスト` | `山田太郎`, `イラスト` | なし | 役割の語は出版社にしない（0005 のまま） |

誤判定の帰結: 外された人はその本の著者にならず（著者ノートに載らない）、出版社ノート `サンデル.md` 側に本が載る。
ユーザーが気づくのは、出版社一覧に人名が出たとき。直す手段は今回は作らない（§9）。著者欄を `,` で区切り直せば正しく分かれる
（`熊野純彦, サンデル`）。

### 5.3 出版社ノート（`backend/app/publisher_store.py`、新規）

#### `author_store` の引数化（`NoteKind`）

```python
@dataclass(frozen=True)
class NoteKind:
    """ノートの種類（著者・出版社）ごとに違うところ。仕組み（scan・plan・rebuild）は共通。"""
    label: str          # "著者" / "出版社"。見出し・文言・ログに使う
    dirname: str        # "authors" / "publishers"
    hub_name: str       # "著者一覧.md" / "出版社一覧.md"
    note_type: str      # "author-note" / "publisher-note"
    hub_header: str     # ハブを新しく作るときの全文の頭（今の HUB_HEADER）
    source: str         # "著者欄" / "出版社欄と著者欄"。マーカー内のコメント「DB の{source}から書き直す」
    empty_hint: str     # 本が無いノートの文言の「（集める名前: …）。」のあと
    note_names: Callable[[dict, str], tuple[str, ...]]   # (frontmatter, stem) → 集める名前
    legacy_keys: Callable[[str], frozenset[str]]         # 旧い規則のまとまりのキー（expand_notes 用）。出版社は空
    collect: Callable[[list[Book]], dict[str, "Author"]] # 本 → キー → Author（名前と本の束）

AUTHOR = NoteKind(label="著者", dirname=AUTHORS_DIRNAME, hub_name=HUB_NAME, note_type=NOTE_TYPE,
                  hub_header=HUB_HEADER, source="著者欄",
                  empty_hint="集める名前はファイル名と frontmatter の `aliases` で決まります。出版社欄と同じ名前は著者にしません。",
                  note_names=note_names, legacy_keys=_cluster_keys, collect=collect_authors)
```

- `_cluster_keys(text) -> frozenset[str]` は今 `_note_of` の中にある `frozenset(ck for _, ck in _fragments(text))` を切り出したもの。
- `AUTHOR` は `collect_authors` と `note_names` の定義のあと、`kind=AUTHOR` を既定値に使う関数の定義より前に置く。
- `kind: NoteKind = AUTHOR`（キーワード）を足す関数と、使う場所:

| 関数 | `kind` で変わるところ |
|---|---|
| `_note_of(path, meta, mtime=None, kind=AUTHOR)` | `kind.note_names`、`kind.legacy_keys` |
| `scan_notes(directory, kind=AUTHOR)` | 除くハブの名前 `kind.hub_name`、`_note_of(..., kind=kind)` |
| `_warn_lasting_doubts(doubts, kind=AUTHOR)` | 警告文の「{label}ノートの自動作成を止めている」。`_seen_doubts` / `_warned_doubts` は `dict[str, set]`（`kind.dirname` ごと）にする（1回の tick で2種類を呼ぶと互いに消し合うため） |
| `author_block(note, books, reports, themes, kind=AUTHOR)` | 見出し `## この{label}の本`、コメントの `{source}`、`kind.empty_hint` |
| `hub_block(hub, notes, authors, reports, kind=AUTHOR)` | `## {label}ノート`、`## ノートの無い{label}`、`すべての{label}にノートがあります。` |
| `_new_note_meta` / `new_note_text(author, stem, kind=AUTHOR)` | `type: {kind.note_type}` |
| `plan_new_notes(..., *, include_without_report=False, kind=AUTHOR)` | `kind.hub_name`、`_note_of` / `new_note_text` / `author_block` に `kind` |
| `_create_notes(..., kind=AUTHOR)` | `plan_new_notes` に渡す |
| `rebuild(db, *, quiet_seconds=..., now=None, kind=AUTHOR)` | ディレクトリ `report_store.reports_dir() / kind.dirname`、`kind.collect(books)`、上の全部に `kind`、新規ハブは `kind.hub_header` |

`AUTHOR` で呼んだときの出力は今と1文字も変わらない（既存テストがそのまま通ること）。

#### `publisher_store.py`

```python
PUBLISHERS_DIRNAME = "publishers"
HUB_NAME = "出版社一覧.md"
NOTE_TYPE = "publisher-note"
HUB_TYPE = "publisher-hub"
HUB_HEADER = f"""---
type: {HUB_TYPE}
---

# 出版社一覧

出版社ノートの入口。レポートが1冊でもある出版社のノートは、このフォルダ（`publishers/`）にアプリが自動で作る。
レポートの無い出版社も「出版社名.md」を作れば本の一覧が入る。同じ出版社の別の表記（「学研プラス」と
「株式会社学研プラス」など）は、残すほうのノートの frontmatter の `aliases` に足すと1つにまとまる
（先に aliases を足してから、もう一方のノートを消す）。
ここにも自由に書いてよい（下の一覧の部分だけアプリが書き直す）。
"""

def publishers_dir() -> Path: ...           # reports_dir() / PUBLISHERS_DIRNAME

def publisher_name(text: str) -> str:
    """表示名: 書式文字を落として NFKC、空白を1つに詰めて strip（分けない・役割も落とさない）。"""

def note_names(meta: dict, stem: str) -> tuple[str, ...]:
    """stem と aliases（author_store._note_texts）を publisher_name にしたもの。キーが空のものを除き、キーで重複を除く。
    `,` `、` `・` では分けない。"""

def collect_publishers(books: list[Book]) -> dict[str, author_store.Author]:
    """id 順に本を見て、出版社の名前ごとに本を集める。legacy_keys は空。
    1冊の名前: 出版社欄（publisher_name。キーが空なら無し）＋ author_store.publishers_in_author(book.author, 出版社欄のキーの集合)。
    1冊の中でキーが同じものは1つ。
    表示名: そのキーを出版社欄に持つ本があれば、その最初の（id が最小の）本の出版社欄の表記。
            無ければ（著者欄からだけ出た名前）、最初に出た本の著者欄からの表記。"""

PUBLISHER = author_store.NoteKind(label="出版社", dirname=PUBLISHERS_DIRNAME, hub_name=HUB_NAME,
    note_type=NOTE_TYPE, hub_header=HUB_HEADER, source="出版社欄と著者欄",
    empty_hint="集める名前はファイル名と frontmatter の `aliases` で決まります。",
    note_names=note_names, legacy_keys=lambda text: frozenset(), collect=collect_publishers)

def rebuild(db: Session, *, quiet_seconds: float = theme_store.QUIET_SECONDS,
            now: Optional[float] = None) -> list[Path]:
    return author_store.rebuild(db, quiet_seconds=quiet_seconds, now=now, kind=PUBLISHER)
```

- `author_store.Author` を出版社にもそのまま使う（`key` / `name` / `books`。`legacy_keys` は空）。名前は変えない。
- 出版社欄の集合は `author_store._publisher_keys(books)`（0005 と同じもの）。`rebuild` も `create_notes.py` も全部の本を渡す。
- ファイル名は `author_store.note_stem`（使えない文字 `/` などを落とす。変わったら `aliases` に元の名前。今の仕組みのまま）。
- 生成物の例（`reports/publishers/ハーベスト.md`、自動作成）:

```markdown
---
type: publisher-note
---

# ハーベスト

<!-- notes:books:start -->
## この出版社の本

<!-- ここから end まではアプリが DB の出版社欄と著者欄から書き直す（手で編集しない）。集める名前: ハーベスト -->

（theme_store.book_sections の行。レポートのある本は ../0012-野草.md へのリンク）

### 関連するテーマ

- [植物](../themes/植物.md) — 共通の本 1冊
<!-- notes:books:end -->
```

#### `main.py`

```python
jobs = [theme_store.rebuild]
if env_enabled("NOTES_AUTHORS_WATCH"):
    jobs.append(author_store.rebuild)
if env_enabled("NOTES_PUBLISHERS_WATCH"):
    jobs.append(publisher_store.rebuild)
```

コメントに `NOTES_PUBLISHERS_WATCH=0` で出版社ノートだけ止まることを足す。`theme_store.ThemeWatcher` の docstring の
「ジョブは … `author_store.rebuild`」に `publisher_store.rebuild` を足す（コードは変えない）。

#### `scripts/create_notes.py`

- `_authors_section(books, reports, theme_notes, apply, now, quiet)` に `kind=author_store.AUTHOR` を足し、
  ディレクトリ（`report_store.reports_dir() / kind.dirname`）、見出し `{label}ノート（{dirname}/）`、`scan_notes(directory, kind)`、
  `kind.collect(books)`、`plan_new_notes(..., kind=kind)` を `kind` から取る。出版社は同じ関数を `kind=publisher_store.PUBLISHER` で呼ぶ。
- `main`: 著者のあとに出版社のセクション。冒頭の行を `本 N 冊・タグ T 個・著者 A 人・出版社 P 社` に。終了コードに出版社の `problem` / `failed` を含める。
- docstring の「対象」に `本棚の全部の本の出版社全部 → reports/publishers/<出版社>.md` を足し、設計の行に 0006 を足す。

### 5.4 名前の照合とノート側

| ノート | 集める名前（0005） | 集める名前（0006） |
|---|---|---|
| `authors/ダニエル・L・エヴェレット.md` | `ダニエル`、`エヴェレット` | `ダニエル・L・エヴェレット` |
| `authors/H・G・ウェルズ.md` | `ウェルズ` | `H・G・ウェルズ` |
| `authors/Wells.md`（`aliases: [H・G・ウェルズ]`） | `Wells`、`ウェルズ` | `Wells`、`H・G・ウェルズ` |
| `authors/熊野純彦・大澤真幸.md` | `熊野純彦`、`大澤真幸` | 同じ |
| `authors/茸本朗・ハーベスト.md`（0002 で作った） | `茸本朗`、`ハーベスト` | `茸本朗`（`ハーベスト` は出版社として外れる） |
| `authors/ダニエル.md`（0005 で作った断片） | `ダニエル` | `ダニエル`（同じ。ただし `ダニエル` というキーの著者はもういない） |
| `publishers/ディスカヴァー・トゥエンティワン.md` | — | `ディスカヴァー・トゥエンティワン`（分けない） |
| `publishers/学研プラス.md`（`aliases: [株式会社学研プラス, Gakken]`） | — | 3つ |

キーの例: `ダニエル・L・エヴェレット` と `ダニエル・L.エヴェレット` は同じキー `ダニエルlエヴェレット`（0002 と同じ）。
`ダニエル・エヴェレット`（L なし）は別のキー（0005 では断片で同じ人になっていた。0002 の挙動に戻る。`aliases` でまとめる）。

### 5.5 0005 の `legacy_keys` / `expand_notes` との関係

- 「まとまり」（`,` `、` で分けて役割を落とした単位）とそのキーは 0006 でも変わらない。`Author.legacy_keys` / `AuthorNote.legacy_keys` /
  `expand_notes` はコードも意味もそのまま。
- 0002 で作ったノートの stem は 0002 での表示名（＝まとまり）。0006 でカタカナ名は再びまとまりと同じ1つの名前になるので、多くは
  `keys` で直接一致する。`expand_notes` が効くのは、まとまりが `・` で分かれる場合（`熊野純彦・大澤真幸.md`、`茸本朗・ハーベスト.md`）と、
  表記揺れの組（`ジャレド ダイアモンド.md` と `ジャレド・ダイアモンド`。0006 ではキーが同じなので直接一致し、`expand_notes` は要らなくなる）。
- 0005 で作った断片のノートの `legacy_keys` は断片そのもの（`ダニエル`）。0006 の著者の `legacy_keys` はまとまり全体（`ダニエルlエヴェレット`）
  なので一致しない。断片のノートは何も集めない（§5.6）。
- 出版社ノートは `legacy_keys` を使わない（空）。`expand_notes` は何も足さない。

### 5.6 既存のノートへの影響

前提: ユーザーは 0002 の規則で `create_notes.py --apply` を流して全部の著者のノートを持ち、0005 を 2026-10-14 に入れた。0005 のあとに
足した本や `create_notes.py` の再実行で、断片のノートがいくつできたかは**未確認**。

| 既存のノート（でき方） | 0006 のあとに載る本 | ファイル |
|---|---|---|
| `ダニエル・L・エヴェレット.md`（0002） | `ダニエル・L・エヴェレット`（キーが同じ表記）の本 | マーカー内のコメントが「集める名前: ダニエル・L・エヴェレット」に戻り1回書き直す。新しいファイルは作らない |
| `マイケル・サンデル.md`（0002） | サンデルの本だけ（`マイケル・ルイス` の本は載らなくなる） | 同上 |
| `ダニエル.md`・`エヴェレット.md`（0005 の断片。自動か一括） | 無くなる。「この名前の本はまだありません」。ハブの「著者ノート」に `0冊（レポート 0）` | ファイルは残る。著者にレポートがあれば `ダニエル・L・エヴェレット.md` が次の回に自動で作られる（レポートが無ければハブの「ノートの無い著者」に出て、`create_notes.py` で作れる）。断片のノートに書いた本文は、ユーザーが移してから消す |
| `熊野純彦・大澤真幸.md`（0002）・`熊野純彦.md`（0005） | 変わらない | 変わらない |
| `茸本朗・ハーベスト.md`（0002） | 変わらない（`茸本朗` の本） | 「集める名前: 茸本朗」で1回書き直す |
| `学研プラス.md`（0002。0005 で空になった） | 変わらない（空のまま） | 変わらない。出版社ノートは `publishers/` に別に作る（同じ名前でもフォルダが違うのでぶつからない） |
| `ジャレド ダイアモンド.md`（0002） | 変わらない | 変わらない |

確かめたこと（`author_store` の写しに §5.1 の分け方を入れ、`rebuild` を実行）: `ダニエル.md`・`エヴェレット.md`（0005 の断片）・
`茸本朗・ハーベスト.md`・`熊野純彦・大澤真幸.md`・`H・G・ウェルズ.md` を置き、著者欄 `ダニエル・Ｌ・エヴェレット`・`茸本朗・ハーベスト`・
`熊野純彦・大澤真幸`・`Ｈ・Ｇ・ウェルズ` のレポートのある本で `rebuild` → 新しく作られたのは `ダニエル・L・エヴェレット.md` だけ。
ハブの「著者ノート」に `ダニエル.md`・`エヴェレット.md` が `0冊（レポート 0）`、「ノートの無い著者」は無し。2回目の `rebuild` は何も書かない。
出版社ノートの部分（§5.3）は未実装のため**未確認**。ユーザーの実データ（reading.db・reports/）では確かめていない（**未確認**）。

デプロイ直後の最初の回に起きること:
- 著者: 上の表の書き直し。0005 の断片のノートがあれば、名前全体のノートの自動作成。
- 出版社: `publishers/` とハブ `出版社一覧.md` を作り、レポートのある本の出版社のノートを自動で作る（レポートのある本の出版社の数だけ
  ファイルが増える）。レポートの無い出版社はハブに冊数付きの文字で出る。

### 5.7 確認済みの例

§5.1 の規則を Python で実行した結果（`author_store` の写しに `_joins_name`・`_split_cluster`・`publishers_in_author`（決定2の部分）を入れたもの）。
「通し直し」は `split_authors(", ".join(結果)) == 結果`。出版社欄による除外（0005）はこの表には効かせていない。

| 著者欄 | `split_authors` | キー | 外した出版社（決定2） | 通し直し |
|---|---|---|---|---|
| `ダニエル・Ｌ・エヴェレット, 松浦俊輔` | `ダニエル・L・エヴェレット`, `松浦俊輔` | `ダニエルlエヴェレット`, `松浦俊輔` | | 同じ |
| `ダニエル・L.・エヴェレット` | `ダニエル・L.・エヴェレット` | `ダニエルlエヴェレット` | | 同じ |
| `Ｈ・Ｇ・ウェルズ` | `H・G・ウェルズ` | `hgウェルズ` | | 同じ |
| `Ｊ・Ｋ・ローリング` | `J・K・ローリング` | `jkローリング` | | 同じ |
| `トマス・S・クーン` | `トマス・S・クーン` | `トマスsクーン` | | 同じ |
| `マイケル・サンデル` | `マイケル・サンデル` | `マイケルサンデル` | | 同じ |
| `ｻﾗ･ｲﾏﾘ･ｳｫｰｶｰ`（半角） | `サラ・イマリ・ウォーカー` | `サライマリウォーカー` | | 同じ |
| `クロード・レヴィ＝ストロース` | `クロード・レヴィ=ストロース` | `クロードレヴィストロース` | | 同じ |
| `ジョン・スミス・Jr.` | `ジョン・スミス・Jr.` | `ジョンスミスjr` | | 同じ |
| `H・G` | `H・G` | `hg` | | 同じ |
| `熊野純彦・大澤真幸` | `熊野純彦`, `大澤真幸` | | | 同じ |
| `楊・文` | `楊`, `文` | | | 同じ |
| `山田・L・鈴木` | `山田`, `鈴木` | | | 同じ |
| `東京大学・出版会` | `東京大学`, `出版会` | | | 同じ |
| `茸本朗・ハーベスト` | `茸本朗` | | `ハーベスト` | 同じ |
| `茸本朗・ハーベスト, 山田太郎` | `茸本朗`, `山田太郎` | | `ハーベスト` | 同じ |
| `茸本朗・ハーベスト・ジャパン` | `茸本朗` | | `ハーベスト・ジャパン` | 同じ |
| `山田太郎・ハーベスト 編` | `山田太郎` | | `ハーベスト` | 同じ |
| `山田 (著)・ハーベスト` | `山田` | | `ハーベスト` | 同じ |
| `山田・ﾊｰﾍﾞｽﾄ` | `山田` | | `ハーベスト` | 同じ |
| `山田太郎・ディスカヴァー・トゥエンティワン 編` | `山田太郎` | | `ディスカヴァー・トゥエンティワン` | 同じ |
| `熊野純彦・サンデル` | `熊野純彦` | | `サンデル`（誤判定） | 同じ |
| `村上春樹・ジェイ・ルービン` | `村上春樹` | | `ジェイ・ルービン`（誤判定） | 同じ |
| `ジェイ・ルービン・村上春樹` | `ジェイ・ルービン`, `村上春樹` | `ジェイルービン`, `村上春樹` | | 同じ |
| `山田・ハーベスト・鈴木` | `山田`, `ハーベスト`, `鈴木` | | | 同じ |
| `山田太郎・イラスト` | `山田太郎`, `イラスト` | | （役割の語なので外さない） | 同じ |
| `茸本朗, HS` / `茸本朗・HS` | `茸本朗`, `HS` | `茸本朗`, `hs` | | 同じ |
| `ハーベスト` | `ハーベスト` | | | 同じ |
| `ディスカヴァー・トゥエンティワン` | `ディスカヴァー・トゥエンティワン` | `ディスカヴァートゥエンティワン` | | 同じ |
| `DIAMONDハーバード・ビジネス・レビュー編集部` | 1つのまま | `diamondハーバードビジネスレビュー編集部` | | 同じ |
| `NHK「ヒューマン・ドキュメント」取材班` | 1つのまま | | | 同じ |
| `かこさとし 作・絵` | `かこさとし` | | | 同じ |
| `山田 (東京・大阪)` | `山田 (東京・大阪)` | `山田(東京大阪)` | | 同じ |
| `・山田・` | `山田` | | | 同じ |
| `A, B` | （なし） | | | 同じ |

### 5.8 エッジケース

| ケース | 振る舞い |
|---|---|
| `・` の隣が `.` や空白（`L.・エ`、`ル ・ L`） | 飛ばして次の文字で判定する |
| `・` が連続（`ダニエル・・エヴェレット`） | `・` も飛ばすので、両側が名前の文字なら分けない |
| カタカナ名の2人を `・` で並べた（`マイケル・サンデル・ジョン・スミス`） | 1人になる（区別できない。`,` で区切り直す） |
| 漢字名とカタカナ名の2人（`熊野純彦・サンデル`） | カタカナ名が出版社になる（§5.2） |
| 英字の出版社（`山田・HS`） | 決定2では外れない。出版社欄に同じ表記があれば 0005 で外れる |
| 1冊の出版社欄と著者欄の末尾で表記が違う（出版社欄 `ハーベスト社`、著者欄 `…・ハーベスト`） | 2つの出版社になり、本は両方のノートに載る（表記揺れはまとめない） |
| 出版社欄が空で、著者欄の末尾がカタカナ | 著者欄からの名前だけで出版社になる |
| 出版社欄に2社（`オライリー・ジャパン ; オーム社 (発売)`） | その文字列で1つの出版社 |
| 出版社名に `/` など使えない文字（`KADOKAWA/角川書店`） | ファイル名は `KADOKAWA角川書店.md`、`aliases` に元の名前（著者ノートと同じ） |
| 出版社ノートのファイル名がハブと同じ（出版社名 `出版社一覧`） | 作らない（`plan_new_notes` の既存の判定） |

## 6. 選ばなかった案と理由

- **`publisher_store.py` に著者側の仕組みを写す**: `plan_new_notes` / `scan_notes` / `rebuild` の安全策（編集中のノートで作らない、見分けのつかない名前を作らない、
  UTF-8 にできない一覧を書かない）を2か所で保つことになる。`NoteKind` で引数化すれば、著者側の既定の振る舞いは変えずに共有できる。
- **共通部分を新しいモジュールに移す**: `author_store` の公開名と多くのテストの import が変わる。今の差分の目的（出版社ノート）に対して大きすぎる。
- **0005 の断片のノートが名前全体の著者も集める（断片のキーを `legacy_keys` のように扱う）**: `マイケル.md` が別人のマイケルを集め続け、0006 の目的
  （別人を混ぜない）が断片のノートの分だけ残る。断片のノートは空にして、ユーザーが消す。
- **決定2で外した名前を出版社欄の集合（0005 決定4）にも足す**: 1冊の誤判定（`熊野純彦・サンデル`）が他の全部の本の `サンデル` を外す。構文の判定はその本の中だけにする。
- **出版社ノートの名前も `,` `、` `・` で分ける**: 出版社欄を分けない（0005 §6）のと食い違い、`ディスカヴァー・トゥエンティワン.md` が別の名前を集める。

## 7. 影響範囲・移行

### 7.1 変更するファイル

| ファイル | 変更 |
|---|---|
| `backend/app/author_store.py` | §5.1 の分け方、§5.3 の `NoteKind` / `AUTHOR` と `kind` 引数、`publishers_in_author`、`_publisher_runs`、`_cluster_keys`、docstring |
| `backend/app/publisher_store.py` | **新規**（§5.3） |
| `backend/app/main.py` | `publisher_store.rebuild` のジョブと `NOTES_PUBLISHERS_WATCH`、コメント |
| `backend/app/theme_store.py` | `ThemeWatcher` の docstring の1行だけ |
| `scripts/create_notes.py` | §5.3 |
| `backend/tests/test_author_store.py` / `test_create_notes.py` / `test_publisher_store.py`（新規） | §8 |
| `docs/SPEC.md` | §4「著者ノート」の「著者の分け方」「同じ人のまとめ方」「旧い規則で作ったノート」「更新と止め方」「一括で作る」、新しい小節「出版社ノート（`reports/publishers/`）」、冒頭の「最終更新」 |
| `docs/design/0006-…md` / `docs/design/README.md` | 実装後に状態を「実装済み（日付）」に |
| `CLAUDE.md` §3・§4 | `publisher_store.py`・`reports/publishers/`・`NOTES_PUBLISHERS_WATCH` の追記が要る。CLAUDE.md の変更はユーザーの確認を取ってから |

変えない: frontend、API、DB のスキーマ、`report_store.py`（`reports/` 直下だけを見るので `publishers/` はレポートとして読まない）。

### 7.2 デプロイ

DB の移行は無い。

```bash
cd ~/Notes
git pull
systemctl --user restart notes-web
```

- 再起動後の最初の回に、著者ノートのマーカー内（名前の変わるもの）と、`publishers/`（ハブとレポートのある出版社のノート）が書かれる。
- そのあと、ユーザーがすること（任意）:
  1. `authors/著者一覧.md` の「著者ノート」で `0冊` のノートを見る。0005 の断片のノート（`ダニエル.md` など）は、本文を移してから消してよい。
  2. 全部の出版社のノートが欲しければ `.venv/bin/python scripts/create_notes.py 2>&1 | less`（下見）→ `--apply`。
  3. `publishers/出版社一覧.md` で人名が出版社になっていないか（§5.2 の誤判定）を見る。あれば DB の著者欄を `,` で区切り直す。
  4. 表記揺れの出版社は、残すほうのノートの `aliases` に他方の名前を足し、他方のノートを消す。

## 8. テスト方針

テスト名は日本語（CLAUDE.md §7）。DB はメモリ上、ノートとレポートは実ファイル。全体: `cd backend && ../.venv/bin/pytest -q` が通ること
（作業前 990 passed, 1 skipped。減らない）。

### 8.1 期待値・入力を直す既存のテスト

§5.1 の分け方だけを写しに入れて流すと 28 件が落ちた。すべて規則が変わったことによるもの（他の失敗は無い）。テスト名は変えない
（中身が反対になる2件だけ名前を変える）。

| テスト | 直し方 |
|---|---|
| `TestSplitAuthors.test_半角の中黒もNFKCで中黒になって区切りになる` | 名前を `test_半角の中黒もNFKCで中黒になる` にし、`ｻﾗ･ｲﾏﾘ･ｳｫｰｶｰ` → `["サラ・イマリ・ウォーカー"]`、`山田･鈴木` → `["山田", "鈴木"]` |
| `TestSplitAuthors.test_名前の一部の中黒でも分ける` | 名前を `test_カタカナや英字に挟まれた中黒では分けない` にし、`ダニエル・Ｌ・エヴェレット, 松浦俊輔` → `["ダニエル・L・エヴェレット", "松浦俊輔"]`、`トマス・S・クーン` → `["トマス・S・クーン"]` |
| `TestSplitAuthors.test_英字1文字のイニシャルは名前にしない` | 組を `山田・L・鈴木` → `["山田", "鈴木"]`、`L` → `[]`、`A, B` → `[]`、`ダニエル, L.` → `["ダニエル"]` に（`Ｈ・Ｇ・ウェルズ`・`ダニエル・L.・エヴェレット`・`H・G` は 8.2 の分けないテストへ） |
| `TestSplitAuthors.test_イコールでは分けない` | `["クロード・レヴィ=ストロース"]` |
| `TestSplitAuthors.test_閉じていないかぎ括弧は後ろの著者を飲み込まない` | `["NHK「ヒューマン・ドキュメント", "山田"]` |
| `TestAuthorKey.test_中黒を含む出版社名のキーは分けた名前のキーをつないだものと同じ` | 入力を `東京大学・出版会`（漢字どうしで分かれる）に |
| `TestNoteNames.test_ファイル名とaliasesの中黒も著者欄と同じに分ける` | `("ダニエル・L・エヴェレット",)`、`("H.G. Wells", "H・G・ウェルズ")`。`熊野純彦・大澤真幸` → `("熊野純彦", "大澤真幸")` を足す |
| `TestCollectAuthors.test_collects_a_translator_like_an_author` | `["ダニエル・L・エヴェレット", "松浦俊輔"]` |
| `TestCreate.test_creates_a_note_for_each_author_of_a_book_with_a_report` | `["ダニエル・L・エヴェレット.md", "松浦俊輔.md"]`。先頭の確かめを `ダニエル・L・エヴェレット.md` と `# ダニエル・L・エヴェレット` に |
| `TestCreateWaitsForSettledNotes.test_waits_while_any_note_was_just_edited`（`[61-True]` `[-61-True]`） | 作られるファイル `ウェルズ.md` → `H・G・ウェルズ.md` |
| `TestScanNotes.test_reads_the_names_and_the_mtime_of_each_note` | `("Wells.md", ("Wells", "H・G・ウェルズ"), 1_000_000)` |
| `TestAuthorNote.test_collects_books_of_every_alias` | `集める名前: H.G. Wells、H・G・ウェルズ -->` |
| `TestHub.test_creates_the_hub_with_notes_and_authors_without_a_note` | 「著者ノート」を `渡辺照宏`（2冊）、`ダニエル・L・エヴェレット`、`松浦俊輔` に |
| `TestPlanNewNotes.test_既に集められている著者はalreadyに入る` | `["H・G・ウェルズ"]` |
| `TestPlanNewNotes.test_旧い規則で同じ人だった表記揺れの著者もalreadyに入り計画に入らない` | `already` を `["ジャレド ダイアモンド"]` と `["J.K.ローリング"]`（0006 では2つの表記が同じキーの1人になる） |
| `TestExistingNotesUnderTheSplitRules.test_旧い規則で作った中黒入りの名前のノートが分けた名前の本を集めて重複ノートを作らない` | `集める名前: ダニエル・L・エヴェレット -->` |
| `TestExistingNotesUnderTheSplitRules.test_イニシャルのノートは作らない` | 作られるのは `H・G・ウェルズ.md` |
| `TestExistingNotesUnderTheSplitRules.test_同じ名を持つ別人の本は同じノートに載る` | 名前を `test_同じ名を持つカタカナ名の別人は別の著者になる` にし、サンデルのノートに `フラッシュ・ボーイズ` が無く、`マイケル・ルイス.md` が作られることを確かめる |
| `test_create_notes.py` `TestPreview.test_下見で表示したファイルとapplyで作るファイルが同じ` | 著者ノートの数 `3` |
| `test_create_notes.py` `TestAuthorNotes.test_共著者と訳者もそれぞれノートを作る` | `ダニエル・L・エヴェレット.md`（`ダニエル.md`・`エヴェレット.md` の代わり） |
| `test_create_notes.py` `TestAuthorNotes.test_旧い規則の中黒入りのノートが集めている著者は作らない` | `既にノートあり 1` |
| `test_create_notes.py` `TestAuthorNotes.test_旧い規則で同じ人だった表記揺れの著者は旧いノートが集めているので作らない` | `already` を `1`（2つの組とも） |

出版社のセクションを足すと、`test_create_notes.py` の出力全体や終了コードを見るテストが変わりうる（出版社欄のある本を使うテストは
出版社ノートも作る）。どれが落ちるかは**未確認**。落ちたら、出版社欄を使わないテストは期待を変えず、出版社ノートが作られる分だけ
期待に足す（著者・テーマの結果の期待は変えない）。

### 8.2 足すテスト

`backend/tests/test_author_store.py`

`TestSplitAuthors`:
- `test_カタカナや英字に挟まれた中黒では分けない` — parametrize: `Ｈ・Ｇ・ウェルズ` → `["H・G・ウェルズ"]`、`ダニエル・L.・エヴェレット` → `["ダニエル・L.・エヴェレット"]`、`マイケル・サンデル` → 1つ、`H・G` → `["H・G"]`、`ダニエル・・エヴェレット` → 1つ
- `test_漢字やかなに接する中黒では分ける` — parametrize: `熊野純彦・大澤真幸`、`楊・文`、`東京大学・出版会`、`・山田・` → `["山田"]`
- `test_まとまりの最後のカタカナだけの部分は出版社として著者から外す` — parametrize: `茸本朗・ハーベスト` → `["茸本朗"]`、`山田太郎・ディスカヴァー・トゥエンティワン 編` → `["山田太郎"]`、`山田 (著)・ハーベスト` → `["山田"]`、`山田・ﾊｰﾍﾞｽﾄ` → `["山田"]`、`茸本朗・ハーベスト, 山田太郎` → `["茸本朗", "山田太郎"]`
- `test_最後の部分が出版社と判断されない場合` — parametrize: `ハーベスト`、`マイケル・サンデル`、`ジェイ・ルービン・村上春樹`、`山田・ハーベスト・鈴木`、`茸本朗・HS`、`山田太郎・イラスト`（それぞれ §5.7 の結果）
- `test_漢字名とカタカナ名を中黒で並べるとカタカナ名が出版社になる` — `熊野純彦・サンデル` → `["熊野純彦"]`（既知の誤判定を固定する）
- 既存の `test_splitting_the_names_again_changes_nothing` の parametrize に `茸本朗・ハーベスト`、`村上春樹・ジェイ・ルービン`、`ダニエル・L.・エヴェレット`、`ｻﾗ･ｲﾏﾘ･ｳｫｰｶｰ` を足す

`TestPublishersInAuthor`（新規クラス）:
- `test_末尾のカタカナの出版社名を返す` — `publishers_in_author("茸本朗・ハーベスト", frozenset())` → `["ハーベスト"]`
- `test_出版社欄と一致して外した名前も返す` — `publishers_in_author("茸本朗, HS", frozenset({"hs"}))` → `["HS"]`
- `test_出版社の無い著者欄は空` — `None`・`""`・`熊野純彦・大澤真幸` → `[]`
- `test_同じキーの出版社は1つだけ返す` — `茸本朗・ハーベスト, 山田・ﾊｰﾍﾞｽﾄ` → `["ハーベスト"]`

`TestNoteNames`:
- `test_旧いノートのファイル名の末尾のカタカナの出版社は集める名前にしない` — `note_names({}, "茸本朗・ハーベスト") == ("茸本朗",)`

`TestExistingNotesUnderTheSplitRules`（`rebuild`）:
- `test_旧い規則のカタカナ名のノートは名前全体で本を集め新しいノートを作らない` — `ダニエル・L・エヴェレット.md`・`マイケル・サンデル.md` を置き、レポートのある本 `ダニエル・Ｌ・エヴェレット`・`マイケル・サンデル` → ファイルは増えない、2回目の `rebuild` は `[]`
- `test_0005で作られた断片のノートは本が無くなり名前全体のノートが作られる` — `ダニエル.md`・`エヴェレット.md` を置き、レポートのある本 `ダニエル・Ｌ・エヴェレット` → `ダニエル・L・エヴェレット.md` ができ、`ダニエル.md` は「この名前の本はまだありません」、ハブに `- [ダニエル](ダニエル.md) — 0冊（レポート 0）`。断片のノートは消えない
- `test_旧い規則の出版社入りのノートは著者の本だけを集める` — `茸本朗・ハーベスト.md` を置き、レポートのある本 `茸本朗・ハーベスト` → ファイルは増えず、`集める名前: 茸本朗 -->` と本の行

`TestNoteKind`:
- `test_既定の種類で呼ぶと今までと同じ著者ノートとハブを書く` — 既存のテストが通ることで足りるので、`AUTHOR` を明示して `rebuild(db, kind=author_store.AUTHOR)` と `rebuild(db)` の書いたファイルの中身が同じことだけ確かめる

`backend/tests/test_publisher_store.py`（新規。小道具は `test_author_store` の `Shelf` などを import して使う）

`TestCollectPublishers`:
- `test_出版社欄ごとに本を集める` — 2冊が `学研プラス`、1冊が `ハーベスト` → 2社、冊数 2 と 1
- `test_出版社欄は分けず全体を1つの名前にする` — `ディスカヴァー・トゥエンティワン`、`オライリー・ジャパン ; オーム社 (発売)` → それぞれ1社
- `test_全角半角や空白や大文字小文字の違いは同じ出版社にする` — `ＨＳ` と `h s` → 1社
- `test_表記揺れはまとめない` — `学研プラス` と `株式会社学研プラス` → 2社
- `test_著者欄の末尾のカタカナから出版社を集める` — 出版社欄が空で著者欄 `茸本朗・ハーベスト` → `ハーベスト` にその本
- `test_出版社欄と一致して著者から外した名前の本もその出版社に入る` — 本1（著者 `茸本朗, HS`、出版社なし）、本2（出版社 `HS`）→ `HS` に2冊
- `test_表示名は出版社欄の表記を優先する` — 先の本（id 小）の著者欄 `山田・ﾊｰﾍﾞｽﾄ`、後の本の出版社欄 `ハーベスト　` → 表示名 `ハーベスト`（出版社欄の表記を正規化したもの）
- `test_出版社欄が空や空白だけの本はどの出版社にも入らない` — parametrize: `None`・`""`・`"  "`（著者欄に出版社なし）
- `test_1冊の中で同じ出版社は1回だけ数える` — 出版社欄 `ハーベスト`・著者欄 `茸本朗・ハーベスト` → `ハーベスト` に1冊

`TestPublisherNoteNames`:
- `test_ファイル名とaliasesを分けずに名前にする` — `note_names({"aliases": ["株式会社学研プラス"]}, "ディスカヴァー・トゥエンティワン")` → `("ディスカヴァー・トゥエンティワン", "株式会社学研プラス")`
- `test_キーが同じ名前は1つにする` — stem `HS`、aliases `["ＨＳ"]` → `("HS",)`

`TestRebuild`:
- `test_レポートのある出版社のノートとハブを作る` — レポートのある本（出版社 `ハーベスト`）とレポートの無い本（出版社 `学研プラス`）→ `ハーベスト.md`（`type: publisher-note`、`# ハーベスト`、`## この出版社の本`、レポートへの `../` リンク）とハブ `出版社一覧.md`（`type: publisher-hub`、「出版社ノート」に `ハーベスト`、「ノートの無い出版社」に `- 学研プラス — 1冊（レポート 0）`）。`学研プラス.md` は作らない
- `test_ユーザーが作った出版社ノートはレポートが無くても埋める` — `学研プラス.md` を置く → 本の行が入る
- `test_aliasesで表記揺れをまとめたノートは両方の本を集め他方のノートを作らない` — `学研プラス.md`（`aliases: [株式会社学研プラス]`）、レポートのある本が両方の表記 → ファイルは増えない
- `test_同じ本を含むテーマノートが関連するテーマに出る`
- `test_2回目は何も書かない`
- `test_編集中の出版社ノートがあれば作らず一覧とハブは書く` — frontmatter が壊れたノートを置く → 新しいノートは作らない（著者ノートと同じ安全策が `kind` で効いていること）
- `test_著者ノートのフォルダとは別に作り同じ名前でもぶつからない` — 著者欄・出版社欄とも `学研プラス` → `publishers/学研プラス.md` ができ、`authors/学研プラス.md` はできない
- `test_出版社ノートの止め方の環境変数を読む` — `main.env_enabled("NOTES_PUBLISHERS_WATCH")` が `0`/`false` で False、未設定で True

`backend/tests/test_create_notes.py`（小道具 `publishers` フィクスチャを足す）:
- `test_全部の出版社のノートをレポートの有無に関係なく作る` — 出版社欄 `学研プラス`（レポートなし）・`ハーベスト` → `--apply` で両方、stdout に `出版社 2 社`
- `test_既存の出版社ノートがaliasesで集めている出版社は作らない`
- `test_編集中の出版社ノートがあれば出版社ノートを作らず終了コード1になり著者ノートは作る`

## 9. 未決事項

- **誤判定（漢字名・カタカナ名の2人を `・` で並べた著者欄）を直す手段**: 今は著者欄を `,` で区切り直すしかない。多ければ「出版社にしない名前」の一覧
  （ハブの frontmatter など）を新しい番号で設計する。実データで何件あるかは**未確認**。
- **カタカナ名の2人を `・` で並べた著者欄**（`マイケル・サンデル・ジョン・スミス`）は1人になる。区別する手段は無い。
- **出版社名の表記揺れ**（`株式会社` の有無、英字表記、略称）: 自動ではまとめない（ユーザーの了承「表記ゆれはしょうがない」）。`aliases` でまとめる。
- 0005 の断片のノート（`ダニエル.md` など）の片付けを自動にするか（今はユーザーが消す）。
- テーマノートやレポートから出版社ノートへのリンク（今は出版社ノート → レポートの向きだけ）。
