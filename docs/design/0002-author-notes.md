# 0002 著者ノート（`reports/authors/`）と、ノートへの差し込みの共通修正

## 1. 状態・日付

- 状態: 実装済み（2026-10-12）
- 日付: 2026-10-12
- 依存: [0001](0001-storage-boundary.md) を先に実装する（`report_store.front_matter_text` を使う）
- 関連: SPEC §4「テーマノート」、`backend/app/theme_store.py`
- 著者の分け方は [0005](0005-author-split-rules.md) で変更（2026-10-14）

## 2. 背景と目的

0001 でレポートの frontmatter から `author` を外すと、Obsidian の側で「同じ著者のレポート」をたどる
手段が無くなる。テーマノート（タグごと）と同じ仕組みで**著者ごとのノート**を置き、レポートを著者で
つなぐ。Obsidian では、著者ノート → レポートのリンクがグラフに出て、レポート側のバックリンクに
著者ノートが出る。

あわせて、テーマノートで見つかった「差し込み部品」の弱点のうち3つ（マーカーの誤検出、壊れたマーカーを
黙って飛ばす、mtime が未来のノートを永久に飛ばす）を、著者ノートも使う共通部分で直す（§5.9）。

## 3. 決定

1. **著者ノートは `reports/authors/<著者名>.md`**。テーマノートと同じマーカー
   `<!-- notes:books:start -->`〜`<!-- notes:books:end -->` の間だけアプリが書く。マーカーの外は
   ユーザーのもの。
2. **著者の分け方**: `Book.author` を NFKC 正規化してから `,` `、`（NFKC で `，` `､` もこれになる）で
   分け、末尾の役割表記（`／著` `／訳` `（編著）` `[著]` ` 編` など）を落とす。
   - **表示名** = 空白を1つに詰めて trim したもの。同じキーで表記が揺れたら、id の小さい本の表記。
   - **照合キー** = 表示名を NFKC → 空白と `・` `.` `=` `·` を除去 → casefold。
     （オーケストレーターの決定「NFKC＋空白除去＋casefold」に、カナ表記の区切り `・` `.` `=` の除去を
     足した。「ダニエル・L・エヴェレット」と「ダニエル・L.エヴェレット」のような出典ごとの揺れを
     同じ人にまとめるため。別人を混ぜる心配はほぼ無い。）
3. **訳者も著者と同じに扱う**。DB の著者欄に役割は無いことが多く（NDL / openBD / Google Books の整形結果は
   「名前, 名前」だけ）、役割で分けると同じ人が本によって入ったり外れたりする。「同じ訳者の本」も導線として
   役に立つ。役割表記は照合と表示名のために落とすだけで、どこにも保存しない。
4. **ノートが集める名前** = ファイル名（stem）＋ frontmatter の `aliases`（文字列か配列）。
   別表記（「H.G. Wells」と「H・G・ウェルズ」）は `aliases` で1つのノートにまとめる。
5. **レポートが1冊以上ある著者は、どのノートも集めていなければアプリが自動で作る**。レポートの無い著者の
   ノートは作らず、ハブに冊数付きで出す。ユーザーが手で作った著者ノートは、レポートの有無に関係なく埋める。
   アプリは著者ノートを改名も削除もしない。
6. 自動で作るノートは `type: author-note` の frontmatter ＋ `# 著者名` ＋ マーカー内の一覧。
   ファイル名を作るときに名前が変わった（使えない文字を落とした・長すぎて切った）場合だけ、
   元の名前を `aliases` に入れる（次の回でも同じ著者を集めるため）。
7. **マーカー内**: 「この著者の本」（テーマノートと同じ行の形。レポートのある本は `../<レポート>.md` への
   相対リンク）と「関連するテーマ」（同じ本を含むテーマノートへのリンク）。
   - 関連するテーマを入れる理由: 0001 で失うタグペインの代わりに「著者 → テーマ → 他の本」の導線になり、
     グラフで著者とテーマがつながる。部品（`theme_store.scan_notes` / `books_for`）は既にあり、追加は
     十数行で済む。テーマノート側には「関連する著者」を足さない（範囲外。バックリンクで逆向きは見える）。
8. **ハブ `reports/authors/著者一覧.md`** をアプリが作る（ノートのある著者＝リンク、無い著者＝冊数付きの文字）。
9. **新しいモジュール `backend/app/author_store.py`**。部品は `theme_store.py` を持ち主のまま共有する
   （新しい共通モジュールは作らない）。著者ノートが使う部品だけ公開名にする（§5.9）。
10. **更新は既存の `ThemeWatcher` の周期に相乗りする**。ウォッチャーに「ジョブの列」を渡せるようにし、
    `main.py` が `theme_store.rebuild` と `author_store.rebuild` を渡す。1つのジョブの失敗で他を止めない。
11. **環境変数**: `NOTES_THEMES_WATCH=0` でウォッチャーごと止まる（テーマも著者も。従来どおり
    「ファイルを一切触らせたくないとき」用）。`NOTES_AUTHORS_WATCH=0` で著者ノートだけ止まる。
12. **共通部分の修正**（テーマノートにも効く）:
    - マーカーは「行全体がマーカーだけ（前後の空白は可）の行」に限り、コードフェンス（```` ``` ```` / `~~~`）の
      内側の行は無視して探す。差し替えるのは START 行〜END 行だけ。閉じていないフェンスがあれば触らない。
    - マーカーが壊れて書けないノートは `logger.warning` を出す。同じパスは直るまで繰り返さない。
    - 「直近に更新されたので飛ばす」は `|now - mtime| < quiet_seconds` のときだけにする（mtime が
      quiet_seconds 以上未来のノートを永久に飛ばさない。§5.9.3）。
13. Web 画面（frontend）と API は変更しない。

## 4. 全体像

```
 reading.db                         author_store.rebuild(db)            reports/authors/
 ┌──────────────────────┐          ┌──────────────────────────┐        ┌──────────────────────────────┐
 │ books.author          │─────────▶│ collect_authors()         │        │ 渡辺照宏.md                   │
 │ "ダニエル・Ｌ・エヴェ…, │ 分割・    │  key → Author(名前, 本)   │        │   マーカー外: 本文（ユーザー）    │
 │  松浦俊輔"             │ 役割除去・│                          │        │   マーカー内: 一覧（ビュー）     │
 │ books.tags（関連テーマ）│ キー化    │ scan_notes(authors/)      │◀───────│ H.G. Wells.md                │
 └──────────────────────┘          │  ノート → 名前（stem＋     │ 読む    │   aliases: [H・G・ウェルズ]     │
 report_store.report_paths() ─────▶│   aliases）→ キーの集合     │        │ 著者一覧.md（ハブ）            │
 （レポートのある本 → パス）         │                          │        └──────────────────────────────┘
 theme_store.scan_notes(themes/) ─▶│ 1. 既存ノートのマーカー内を   │ 書く（マーカー内だけ）    ▲
 （関連するテーマ）                  │    書き直す                │──────────────────────────┤
                                   │ 2. レポートのある、どのノート │ 新規作成（無いときだけ）   │
                                   │    も集めていない著者のノート │──────────────────────────┤
                                   │    を作る                  │                          │
                                   │ 3. ハブを書き直す            │──────────────────────────┘
                                   └──────────────────────────┘
                 ThemeWatcher（5秒ごと）: theme_store.rebuild → author_store.rebuild（同じ DB セッション、ジョブごとに例外を分ける）
                 書き込みはすべて theme_store.update_file（reports/.write.lock ＋ write_atomic）

 Obsidian で見たときのつながり:
   themes/仏教.md ──▶ 0021-お経の話.md ◀── authors/渡辺照宏.md ──▶ themes/仏教.md（関連するテーマ）
                                    ▲
                     authors/著者一覧.md ──▶ authors/渡辺照宏.md
```

## 5. 詳細

### 5.1 変更・新規ファイル

| ファイル | 変更 |
|---|---|
| `backend/app/author_store.py` | **新規**。著者の分割・ノートの走査・一覧の組み立て・自動作成・ハブ・`rebuild()` |
| `backend/app/theme_store.py` | 共有部品の公開名への改名、`book_sections()` の切り出し、`fill_block()` 追加、`replace_block()` の検出規則、`update_file()` の静穏判定、`ThemeWatcher` のジョブ化（§5.9） |
| `backend/app/main.py` | ウォッチャーに2つのジョブを渡す。`NOTES_AUTHORS_WATCH`（§5.10） |
| `backend/tests/test_author_store.py` | **新規**（§8.1） |
| `backend/tests/test_theme_store.py` | 追加（§8.2）。既存のテストは変更なしで通ること |
| `docs/SPEC.md` | §7 |

### 5.2 名前の扱い

定数（`author_store.py`）:

```python
AUTHORS_DIRNAME = "authors"
HUB_NAME = "著者一覧.md"
NOTE_TYPE = "author-note"
HUB_TYPE = "author-hub"

_SEPARATORS = re.compile(r"[,、]")          # NFKC のあとに使う（，→ , と ､ → 、は NFKC が揃える）
_ROLES_ANY = "編著|共著|著者|訳者|編者|監修|監訳|翻訳|原作|解説|著|訳|編|作|絵|文|画"
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
```

- 空白区切りの役割に「作」「絵」「文」「画」を入れないのは、Google Books の「山田 文」のような
  姓と1文字の名を役割と取り違えないため。

関数:

```python
def split_authors(author: Optional[str]) -> list[str]:
    """著者欄を人ごとの表示名に分ける。キーで重複を除き、出てきた順に返す。

    NFKC → _SEPARATORS で分割 → 各部分を strip → _ROLE_SUFFIX を1回だけ落とす
    → _SPACES を " " に詰めて strip。キーが空になるもの（空文字・役割だけ）は捨てる。
    """

def author_key(name: str) -> str:
    """照合キー。NFKC → _KEY_DROP を除去 → casefold。"""

def note_stem(name: str) -> str:
    """自動作成するノートのファイル名（拡張子なし）。

    _UNSAFE_NAME を除去 → 空白を詰めて strip → 先頭・末尾の "." を落とす（隠しファイルにしない）
    → UTF-8 で _STEM_BYTES バイトまでに切る（文字の途中で切らない）→ strip。空文字なら作れない。
    """
```

確認済みの例（この規則を Python で実行して確かめた）:

| 著者欄 | `split_authors` | `author_key` |
|---|---|---|
| `ダニエル・Ｌ・エヴェレット, 松浦俊輔` | `ダニエル・L・エヴェレット`, `松浦俊輔` | `ダニエルlエヴェレット`, `松浦俊輔` |
| `J．カバットジン／著, 春木豊／訳` | `J.カバットジン`, `春木豊` | `jカバットジン`, `春木豊` |
| `渡辺　照宏 `（全角空白） | `渡辺 照宏` | `渡辺照宏` |
| `渡辺照宏, 渡辺 照宏` | `渡辺照宏`（1つ） | `渡辺照宏` |
| `山田太郎 編` / `山田太郎（編著）` / `山田太郎 [著]` | `山田太郎` | `山田太郎` |
| `山田 文` | `山田 文`（落とさない） | `山田文` |
| `A，B、C､D` | `A`, `B`, `C`, `D` | |
| `クロード・レヴィ＝ストロース` | `クロード・レヴィ=ストロース` | `クロードレヴィストロース` |
| `H.G. Wells` / `ＨＧ Ｗｅｌｌｓ` | `H.G. Wells` / `HG Wells` | どちらも `hgwells` |
| `None` / `""` / `" , 、 "` / `／著` | （なし） | |
| `???` | `???` | `note_stem` は空文字 → ノートは作らない |

### 5.3 DB 側: 著者の集計

```python
@dataclass(frozen=True)
class Author:
    key: str
    name: str                 # 表示名。そのキーを最初に持つ（id が最小の）本の表記
    books: tuple[Book, ...]   # id 順。同じ本は1回だけ

def collect_authors(books: list[Book]) -> dict[str, Author]:
    """id 順に本を見て、split_authors の名前ごとに本を集める。キー → Author（出てきた順）。"""
```

- 1冊の中で同じ人が2回出ても `split_authors` がキーで1つにするので、本は1回だけ入る。
- 著者欄が null・空・区切りだけの本は、どの著者にも入らない（著者ノートにもハブにも出ない）。

### 5.4 ノート側: ノートが集める名前

```python
@dataclass(frozen=True)
class AuthorNote:
    path: Path
    names: tuple[str, ...]     # stem が先頭、続いて aliases。キーで重複を除いた順
    keys: frozenset[str]       # names の author_key

def note_names(meta: dict, stem: str) -> tuple[str, ...]:
    """stem と frontmatter の aliases を、著者欄と同じ規則（split_authors）で名前にする。

    aliases は文字列なら1つ、配列なら各要素（None は飛ばす、数値などは str にする）。それ以外は無視。
    文字列の中の , や 、 も区切りとして扱う（著者欄が同じ規則で分かれるので、区切りを含む名前は
    どの著者とも一致しない）。
    """

def scan_notes(directory: Path) -> list[AuthorNote]:
    """authors/ 直下の *.md（ハブと "." で始まるものを除く）をファイル名順に返す。

    サブフォルダは見ない。読めない（OSError / UnicodeDecodeError）ファイルは飛ばす。
    frontmatter は report_store.split_front_matter で読む（BOM 付きも読む）。
    """

def books_of(note: AuthorNote, authors: dict[str, Author]) -> list[Book]:
    """note.keys のどれかを持つ著者の本。同じ本は1回だけ。"""
```

- 照合キーは NFKC＋除去＋casefold なので、Obsidian（macOS）が付けた NFD のファイル名や、大文字小文字の
  違いでも同じ著者に当たる（テーマノートで指摘された NFD・大文字小文字の問題は著者ノートでは起きない）。

### 5.5 自動作成の規則

`rebuild()` の中で、既存ノートを書き直したあとに行う。

1. `covered` = 全ノートの `keys` の和集合。
2. `authors` を表示名の順（`(author.name, author.key)`）に見て、次をすべて満たす著者のノートを作る。
   - `author.key not in covered`
   - `author.books` のどれかが `reports`（`report_store.report_paths()`）にある
   - `stem = note_stem(author.name)` が空でない
   - `f"{stem}.md"` が `taken`（既存ノートのファイル名 ＋ `HUB_NAME` ＋ この回に作ったファイル名）に無い
3. 中身は `replace_block(new_note_text(author, stem), block)`。書き込みは `update_file` で、
   `make_text(current)` は **`current is None` のときだけ** 文字列を返す（ロックを取るまでの間に
   同じ名前のファイルができていたら、その回は触らない）。
4. 作ったノートは、その回のハブにも載せる。

```python
def new_note_text(author: Author, stem: str) -> str:
    """自動作成するノートの雛形（マーカーはまだ無い）。

    meta = {"type": NOTE_TYPE}
    author_key(stem) != author.key なら meta["aliases"] = [author.name]
    戻り値: report_store.front_matter_text(meta) + f"\n# {escape_text(author.name)}\n"
    """
```

- `aliases` を入れるのは、`note_stem` で名前が変わってファイル名のキーが著者のキーと一致しない
  ときだけ（例: `山田*太郎` → `山田太郎.md` ＋ `aliases: [山田*太郎]`）。こうしないと次の回に
  「どのノートも集めていない」と判定され続ける。
- 既知の挙動: **Obsidian で消した自動作成ノートは、その著者にレポートがある限り次の回（5秒以内）で
  作り直される**。作り直させないには、別のノートの `aliases` にその名前を足す。

### 5.6 マーカー内の中身（著者ノート）

```python
def author_block(note: AuthorNote, books: list[Book], reports: dict[int, Path],
                 themes: list[tuple[Path, set[int]]]) -> str:
    """著者ノートに差し込む一覧（マーカー込み）。themes は (テーマノートのパス, そのテーマの本の id 集合)。"""
```

行の組み立て（`start = note.path.parent`）:

```python
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
    lines += book_sections(books, reports, start)      # theme_store（§5.9.1）。テーマノートと同じ行
mine = {b.id for b in books}
related = sorted(((len(ids & mine), path) for path, ids in themes if ids & mine),
                 key=lambda pair: (-pair[0], pair[1].name))
if related:
    lines += ["", "### 関連するテーマ", ""]
    lines += [f"- {md_link(path.stem, path, start)} — 共通の本 {count}冊" for count, path in related]
return wrap_block(lines)
```

- 名前の区切りに `・` を使わないのは、カナの名前の中の `・` と見分けられないため。
- 本の行の著者部分には DB の著者欄をそのまま出す（共著者・訳者・役割表記も見える）。

### 5.7 ハブ（`authors/著者一覧.md`）

```python
HUB_HEADER = """---
type: author-hub
---

# 著者一覧

著者ノートの入口。レポートが1冊でもある著者のノートは、このフォルダ（`authors/`）にアプリが自動で作る。
レポートの無い著者も「著者名.md」を作れば本の一覧が入る。同じ人の別の表記（「H.G. Wells」と
「H・G・ウェルズ」など）は、残すほうのノートの frontmatter の `aliases` に足すと1つにまとまる
（先に aliases を足してから、もう一方のノートを消す）。
ここにも自由に書いてよい（下の一覧の部分だけアプリが書き直す）。
"""

def hub_block(hub: Path, notes: list[AuthorNote], authors: dict[str, Author],
              reports: dict[int, Path]) -> str:
```

- 「## 著者ノート」: 全ノートを `(-冊数, stem)` の順に `- [stem](stem.md) — N冊（レポート M）`。
  無ければ「まだありません。」。
- 「## ノートの無い著者」: どのノートの `keys` にも無い著者を `(-冊数, 表示名)` の順に
  `- 表示名 — N冊（レポート M）`（表示名は `escape_text`）。無ければ「すべての著者にノートがあります。」。
- 冊数の数え方・行の形はテーマのハブ（`- 歴史 — 2冊（レポート 1）`）に揃える。

### 5.8 生成される Markdown の例

前提（DB）:

| id | 書名 | 著者欄 | 状態 | 読了日 | 評価 | タグ | レポート |
|---|---|---|---|---|---|---|---|
| 13 | 言語の起源 | ダニエル・Ｌ・エヴェレット, 松浦俊輔 | 読了 | 2026-09-20 | 4 | 言語学 | `0013-言語の起源.md` |
| 21 | お経の話 | 渡辺照宏 | 読了 | 2026-08-02 | 5 | 仏教 | `0021-お経の話.md` |
| 34 | 仏教 第二版 | 渡辺 照宏 | 読書中 | | | 仏教 | なし |
| 40 | マインドフルネスストレス低減法 | J．カバットジン／著, 春木豊／訳 | 積読 | | | | なし |

`themes/仏教.md` がある（tags なし → ファイル名「仏教」で集める）。

自動で作られるノート: `渡辺照宏.md`、`ダニエル・L・エヴェレット.md`、`松浦俊輔.md`。
`J.カバットジン` と `春木豊` はレポートが無いので作らない。

`reports/authors/渡辺照宏.md`（自動作成直後）:

```markdown
---
type: author-note
---

# 渡辺照宏

<!-- notes:books:start -->
## この著者の本

<!-- ここから end まではアプリが DB の著者欄から書き直す（手で編集しない）。集める名前: 渡辺照宏 -->

2冊（レポートあり 1冊）

### レポートのある本

- [お経の話](../0021-お経の話.md) — 渡辺照宏 · 読了 2026-08-02 · ★★★★★

### まだレポートの無い本

- 仏教 第二版 — 渡辺 照宏 · 読書中

### 関連するテーマ

- [仏教](../themes/仏教.md) — 共通の本 2冊
<!-- notes:books:end -->
```

`reports/authors/著者一覧.md`:

```markdown
---
type: author-hub
---

# 著者一覧

著者ノートの入口。（HUB_HEADER の説明文。略）

<!-- notes:books:start -->
## 著者ノート

- [渡辺照宏](渡辺照宏.md) — 2冊（レポート 1）
- [ダニエル・L・エヴェレット](ダニエル・L・エヴェレット.md) — 1冊（レポート 1）
- [松浦俊輔](松浦俊輔.md) — 1冊（レポート 1）

## ノートの無い著者

- J.カバットジン — 1冊（レポート 0）
- 春木豊 — 1冊（レポート 0）
<!-- notes:books:end -->
```

リンク先は `theme_store.link_target` で作るので、空白・括弧・`#` などは % エンコードされる
（例: `渡辺 照宏.md` → `渡辺%20照宏.md`）。

### 5.9 共通部分の修正（`theme_store.py`）

#### 5.9.1 部品の共有（改名と切り出し。振る舞いは変えない）

`theme_store.py` を部品の持ち主のままにし、`author_store.py` が使うものだけ公開名にする。

| いまの名前 | 新しい名前 | 備考 |
|---|---|---|
| `_escape_text` | `escape_text` | 改名だけ |
| `_link` | `md_link` | 改名だけ |
| `_wrap` | `wrap_block` | 改名だけ |
| `_update` | `update_file` | 改名＋静穏判定の修正（§5.9.3） |
| （`theme_block` の中） | `book_sections(books, reports, start, matched_tags=None) -> list[str]` | 切り出し |

`book_sections` は `theme_block` の「`N冊（レポートあり M冊）`」「### レポートのある本」「### まだレポートの
無い本」の行をそのまま関数にしたもの。`books` は空でない前提（空のときの文言は呼び出し側）。
`matched_tags` は `Callable[[Book], list[str]]`（None なら常に `[]`）。並び順（レポートのある本は読了日の
新しい順、無い本は読書中→読了→積読→書名）と行の形は変えない。`theme_block` はこれを呼ぶ形に直す。

そのまま使う公開部品: `START` / `END` / `QUIET_SECONDS` / `replace_block` / `link_target` /
`scan_notes` / `books_for` / `themes_dir`。`_book_line` / `_report_order` / `_STATUS_ORDER` は
`book_sections` の中だけで使うので private のまま。

#### 5.9.2 マーカーの検出（`replace_block` を書き直す）

いまは `text.count(START)` で数えるので、コードフェンスの中やインラインコードで例として書いたマーカーも
数え、その間をユーザーの文章ごと一覧で上書きしてしまう（再現済み）。

新しい規則:

- 行は `text.split("\n")` で分ける（`\r` は行の中身に残るが、比較では strip するので構わない）。
- **マーカーの行** = `line.strip() == START`（または END）の行。インラインの言及（`` `<!-- … -->` `` や
  文中の言及）は数えない。
- **コードフェンスの内側の行は無視する**。開き = `^ {0,3}(`{3,}|~{3,})`、閉じ = 同じ文字で開きと同じ長さ
  以上、後ろは空白だけ（`^ {0,3}(`{3,}|~{3,})\s*$`）。
- **閉じていないフェンスが残ったら None**（触らない）。末尾に足すと一覧がフェンスの中に入り、次の回に
  また足す…と増え続けるため。
- フェンス外のマーカーが START 0・END 0 → いまと同じく末尾に足す（`f"{base}\n\n{block}\n"`）。
- START 1・END 1 で START が先 → **START 行から END 行までを `block` に差し替える**:
  `"\n".join(lines[:s] + [block] + lines[e + 1:])`。それ以外 → None。

```python
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*$")

def _marker_lines(lines: list[str]) -> Optional[tuple[list[int], list[int]]]:
    """フェンスの外にある START 行・END 行の番号。フェンスが閉じていなければ None。"""

def replace_block(text: str, block: str) -> Optional[str]:   # シグネチャは変えない
```

既存のテスト（`test_rewrites_only_between_the_markers` など）の期待値はこの規則でも変わらない
（アプリが書くマーカーは常に単独の行にある）。

#### 5.9.3 壊れたマーカーの警告と、未来の mtime

```python
_warned_broken: set[Path] = set()   # 警告済みのパス。直ったら外す（rebuild はウォッチャーの1スレッドから呼ぶ）

def fill_block(path: Path, text: str, block: str) -> Optional[str]:
    """replace_block と同じ。None（壊れている）なら logger.warning を出す。

    同じパスは直るまで繰り返さない（5秒ごとに同じ警告を出さない）。replace_block が文字列を返したら
    _warned_broken から外す（また壊れたら、また1回警告する）。
    文言: "マーカーが壊れているので一覧を書かない（start と end を1組にするか、閉じていないコードフェンスを
    閉じると次の回で入る）: %s"
    """
```

- テーマノート・テーマのハブ・著者ノート・著者のハブの書き直しは `fill_block` を使う。自動作成の雛形
  （マーカーが無いと分かっている）は `replace_block` のままでよい。ハブへの表示はしない。
- `update_file`（旧 `_update`）の静穏判定を `if now - mtime < quiet_seconds` から
  **`if abs(now - mtime) < quiet_seconds`** に変える。
  - mtime が quiet_seconds 以上未来（同期のずれ）のノートは書く（いまは永久に飛ばしている）。
  - オーケストレーターの指定は「`0 <= now - mtime < quiet` のときだけ飛ばす」だったが、`now` は rebuild の
    始めに1回だけ取るので、rebuild の途中で Obsidian が保存したノート（mtime が `now` より少し未来）を
    「書いている最中」と見なせなくなる。`abs` にしても「未来のノートを永久に飛ばす」は直り、
    少しだけ未来のノートは最大で `2 × quiet_seconds` 待つだけで済む。

#### 5.9.4 ウォッチャーのジョブ化

```python
class ThemeWatcher:
    """ノートの一覧（ビュー）を作り直すジョブを数秒ごとに呼ぶスレッド。アプリの起動中だけ動かす。"""

    def __init__(self, session_factory: Callable[[], Session],
                 interval: float = INTERVAL_SECONDS,
                 jobs: Optional[Sequence[Callable[[Session], list[Path]]]] = None):
        # jobs が None なら (rebuild,)（いまと同じ）
```

- `_tick()`: セッションを1つ開き、ジョブを順に呼ぶ。**ジョブごとに try/except** し、例外のあとは
  `db.rollback()` して次のジョブへ進む。「同じ失敗を繰り返し記録しない」はジョブ名
  （`f"{job.__module__}.{job.__name__}"`）ごとの `self._last_errors: dict[str, str]` で行う。
  セッションを開けない例外も、いまと同じく記録して続ける（キー `"session"`）。
- 書いたファイルのログは `logger.info("ノートの一覧を更新: %s/%s", path.parent.name, path.name)`
  （`themes/` と `authors/` を見分けられるように）。
- クラス名・スレッド名（`theme-watcher`）は変えない（改名の差分を増やさないため）。

### 5.10 `main.py` と環境変数

```python
from . import author_store, theme_store
...
    # テーマノート（reports/themes/）と著者ノート（reports/authors/）の一覧を数秒ごとに書き直す。
    # NOTES_THEMES_WATCH=0 で両方止まる（一時的にファイルを触らせたくないとき）。
    # NOTES_AUTHORS_WATCH=0 で著者ノートだけ止まる（ノートの自動作成を止めたいとき）。
    watcher = None
    if os.environ.get("NOTES_THEMES_WATCH", "1") != "0":
        jobs = [theme_store.rebuild]
        if os.environ.get("NOTES_AUTHORS_WATCH", "1") != "0":
            jobs.append(author_store.rebuild)
        watcher = theme_store.ThemeWatcher(SessionLocal, jobs=jobs)
        watcher.start()
```

`conftest.py` は `NOTES_THEMES_WATCH=0` を立てているので変更不要。

### 5.11 `author_store.rebuild` の流れ

```python
def authors_dir() -> Path:
    return report_store.reports_dir() / AUTHORS_DIRNAME

def rebuild(db: Session, *, quiet_seconds: float = theme_store.QUIET_SECONDS,
            now: Optional[float] = None) -> list[Path]:
    """著者ノート・自動作成・ハブを書き直す。書いた（作った）ファイルを返す。"""
    now = time.time() if now is None else now
    directory = authors_dir()
    directory.mkdir(parents=True, exist_ok=True)
    books = list(db.scalars(select(Book).options(selectinload(Book.tags)).order_by(Book.id)))
    reports = report_store.report_paths()
    authors = collect_authors(books)
    notes = scan_notes(directory)
    themes = [(t.path, {b.id for b in theme_store.books_for(t.tags, books)})
              for t in theme_store.scan_notes(theme_store.themes_dir())]   # 所属は1回だけ計算する

    written = []
    # 1. 既存ノート（ユーザーが作ったもの・前に作ったもの）
    for note in notes:
        block = author_block(note, books_of(note, authors), reports, themes)
        make = lambda current, path=note.path, block=block: (
            None if current is None else theme_store.fill_block(path, current, block))
        if theme_store.update_file(note.path, make, quiet_seconds, now):
            written.append(note.path)

    # 2. 自動作成（§5.5）
    covered = set().union(*(n.keys for n in notes))
    taken = {n.path.name for n in notes} | {HUB_NAME}
    created = []
    for author in sorted(authors.values(), key=lambda a: (a.name, a.key)):
        ...（§5.5 の条件。作ったら created.append(AuthorNote(path, names, keys))、taken に足す）

    # 3. ハブ
    hub = directory / HUB_NAME
    block = hub_block(hub, notes + created, authors, reports)
    make_hub = lambda current: theme_store.fill_block(
        hub, HUB_HEADER if current is None else current, block)
    if theme_store.update_file(hub, make_hub, quiet_seconds, now):
        written.append(hub)
    return written
```

- 作ったノートの `AuthorNote` は `note_names(new_meta, stem)` から作る（次の回の `scan_notes` と同じ結果に
  なるので、2回目以降は書き直しが起きない）。
- 量の目安: 100冊で著者ノート数十〜百数十。5秒ごとに全ノートを読むが、小さいファイルなので数十ミリ秒。
  初回は数十ファイルを作る（1ファイルごとに fsync するので1〜2秒かかりうる）。

### 5.12 エッジケース

| ケース | 振る舞い |
|---|---|
| 著者欄が null・空文字・区切りだけ・役割だけ（`／著`） | どの著者にも入らない。ノートにもハブにも出ない |
| 同じ本に同じ人が2回（`渡辺照宏, 渡辺 照宏`） | キーで1つにする。本は1回だけ載る |
| 表記揺れ（空白・全角・大文字小文字・`・` `.` `=`） | 同じキー → 同じ著者。表示名は id の小さい本の表記。既にあるノートのファイル名は変えない |
| 表記揺れ（別の文字種: `H.G. Wells` と `H・G・ウェルズ`） | 別の著者。ユーザーが `aliases` でまとめる |
| 役割表記（`／訳`、`（編著）`、` 編`） | 落としてから照合・表示。訳者も著者と同じに扱う |
| 区切りの無い役割（`山田太郎著`）、`ほか`・`他`、`A／B`（スラッシュで並べた2人） | 落とさない・分けない（未決事項） |
| 姓名の順の手入力（`Wells, H. G.`） | `,` で2人に分かれる（既知の制限。著者欄を「名 姓」に直す） |
| ファイル名に使えない文字を含む（`山田*太郎`） | `山田太郎.md` を作り、`aliases: [山田*太郎]` を入れる |
| 名前が使えない文字だけ（`???`） | ノートを作らない。ハブの「ノートの無い著者」に文字で出る |
| 長すぎる名前（200 バイト超） | 切ったファイル名で作り、元の名前を `aliases` に入れる |
| ファイル名の衝突（作ろうとした名前のファイルが既にあり、そのノートはこの著者を集めていない） | 作らない（上書きしない）。ハブに文字で出る |
| 著者名が `著者一覧` | ハブと同じ名前になるので作らない |
| `aliases` が他のノートの名前・別名と重なる | **両方のノートに同じ本が載る**（どちらからも本を隠さない）。キーは集められているので自動作成もしない。ハブで警告はしない |
| ユーザーが著者ノートを改名した | ノートが集める名前は新しい stem ＋ aliases になる。旧名を aliases に入れていなければ、その著者はどのノートにも集められなくなり、レポートがあれば次の回（5秒以内）に旧名でノートが作り直される。**改名するときは先に旧名を aliases に足す**（空白・`・` だけ違う名前への改名なら同じキーなので問題ない）。ハブのリンクは次の回に新しい名前で書き直される |
| ユーザーが自動作成ノートを消した・別フォルダへ移した | レポートがある限り次の回に作り直される（既知の挙動） |
| Obsidian のノート統合（Note composer）で2つを1つにした | マーカーの組が2つになり「壊れている」扱い → 書かずに警告。片方の組を消し、消えた側の名前を aliases に足す |
| DB の著者欄を直した（誤字の修正など） | 新しい名前のノートが（レポートがあれば）作られ、古いノートは残って「この名前の本はまだありません」になる。アプリは消さない |
| 本を削除・レポートを空にした | 次の回に一覧から消える・「まだレポートの無い本」へ移る。ノートは消さない |
| ユーザーが作った著者ノートで、名前がどの本にも当たらない | 「この名前の本はまだありません（集める名前: …）」 |
| 直近 10 秒以内に更新されたノート | その回は飛ばす（テーマと同じ） |
| マーカーが壊れている・フェンスが閉じていない | 触らない。警告を1回だけ出す（§5.9.3） |
| `authors/` のサブフォルダ・`.` で始まるファイル | 見ない（テーマと同じ。未決事項） |
| `authors/` 内のファイルとレポートの索引 | 索引は `reports/` 直下しか見ないので、著者ノートがレポートと取り違えられることは無い |

## 6. 選ばなかった案と理由

- **著者ノートもユーザーが作る（テーマと同じ方式）**: レポートが著者でつながらない。0001 で frontmatter の
  `author` を外す代わりの導線にならない。
- **著者を DB のテーブルにする（authors / book_authors、役割付き）**: スキーマ・API・画面・書誌検索の
  変更が要る。今回は Markdown 側だけで完結させる。役割（著・訳）を正しく持ちたくなったら再検討する。
- **訳者を除外する**: §3-3 のとおり、役割の分かる本が少なく、同じ人の扱いが本によって変わる。
- **共通部品を新しいモジュール（例: `note_views.py`）へ切り出す**: 移動の差分が大きく、テーマ側の変更が
  読みにくくなる。ノートの種類は2つなので theme_store を持ち主にして必要な部品だけ公開する。
  3つ目の種類が来たら切り出す。
- **著者用に別スレッドを立てる**: 周期もロックも同じ。相乗りでよい。
- **`aliases` が重なったら先に見つけたノートだけに載せる**: 載る本がファイル名の順に依存し、片方から本が
  黙って消える。両方に載せるほうが予測しやすく、何も隠さない。
- **レポートの無い著者のノートも全部作る**: 100冊で100以上のほぼ空のファイルが vault に増える。
  ハブの文字で足りる。
- **レポートに著者ノートへのリンクを差し込む**: レポートは本文だけにする（0001）。逆向きは Obsidian の
  バックリンクで見える。
- **nbs（次に読む本のスキル）と同じ甘い照合（部分一致・姓だけの一致）を使う**: 別人を混ぜる。ファイルの
  同一性には厳しい一致が要る。
- **Wikiリンク**: 規約で相対 Markdown リンク（SPEC のテーマノート節）。

## 7. 影響範囲・移行

- DB・API・frontend は変わらない。データの移行は無い。
- 初回の起動で、レポートのある著者のノートが `reports/authors/` にまとめて作られる（数十ファイル）。
  `reports/` は git 管理外なので、履歴は `~/.doc-history` の週次コミットに入る。
- テーマノートへの影響: マーカーの検出が厳しくなる（行単独・フェンス外）。アプリが書いたマーカーは常に
  単独の行なので、既存のノートの見た目は変わらない。壊れたマーカーには警告が出るようになる。
- 止め方: `NOTES_AUTHORS_WATCH=0` で再起動。作られたノートを消したいときは、止めてから `reports/authors/` を消す
  （止めずに消すと作り直される）。
- `docs/SPEC.md` の更新（実装と同じコミット）:
  - §4 に「### 著者ノート（`reports/authors/`、2026-10-12）」を、テーマノートの節の後ろに足す。中身は
    §3 の決定 1〜8・11 を SPEC の文体で（分け方・照合、集める名前、自動作成と作り直し、マーカー内、ハブ、
    `NOTES_AUTHORS_WATCH`）。詳細は「→ `docs/design/0002-author-notes.md`」へリンク。
  - テーマノートの節の「マーカーが無ければ末尾に足し、壊れていれば触らない」を「マーカーは行単独のものだけを
    数え、コードフェンスの中は無視する。無ければ末尾に足し、壊れていれば触らずに警告を1回出す」に、
    「直近10秒以内に更新されたノートは…」に「mtime が10秒以上未来のノートは書く」を足す。
    「`NOTES_THEMES_WATCH=0` で止められる」を「（著者ノートも止まる）」に。
  - 実装が済んだら、この設計書と `docs/design/README.md` の状態を「実装済み」にする。

## 8. テスト方針

DB はメモリ上の SQLite、ノートとレポートは実ファイル（`test_theme_store.py` と同じ作法。`db` / `Shelf` /
`write_note` の小道具を同じ形で用意し、`rebuild` は `quiet_seconds=0` で呼ぶ）。

### 8.1 `backend/tests/test_author_store.py`（新規）

名前の扱い（DB もファイルも使わない）:

- `TestSplitAuthors.test_splits_on_ascii_fullwidth_and_ideographic_commas` — `A，B、C､D` → 4人
- `TestSplitAuthors.test_normalizes_width_and_collapses_spaces_for_the_display_name` — `ダニエル・Ｌ・エヴェレット` → `ダニエル・L・エヴェレット`、`渡辺　照宏 ` → `渡辺 照宏`
- `TestSplitAuthors.test_strips_a_trailing_role_marker` — parametrize: `J．カバットジン／著`、`春木豊／訳`、`山田太郎 編`、`山田太郎（編著）`、`山田太郎 [著]`、`山田太郎／監修`
- `TestSplitAuthors.test_keeps_a_one_letter_given_name_after_a_space` — `山田 文` は `山田 文` のまま
- `TestSplitAuthors.test_returns_nothing_for_none_empty_separators_or_a_bare_role` — `None`、`""`、`" , 、 "`、`／著`
- `TestSplitAuthors.test_lists_a_name_repeated_in_one_book_once` — `渡辺照宏, 渡辺 照宏` → 1人
- `TestAuthorKey.test_ignores_spaces_width_case_and_name_dots` — parametrize で同じキーになる組（`渡辺 照宏`/`渡辺照宏`、`H.G. Wells`/`ＨＧ Ｗｅｌｌｓ`、`ダニエル・L・エヴェレット`/`ダニエル・L.エヴェレット`、NFD の `が` を含む名前/NFC）
- `TestNoteStem.test_drops_characters_that_cannot_be_in_a_file_name` — `A/B: C?` → `AB C`、`.隠れ` → `隠れ`
- `TestNoteStem.test_caps_the_name_at_200_bytes_without_splitting_a_character`
- `TestNoteNames.test_reads_aliases_as_a_string_or_a_list` — parametrize: `None`、`"別名"`、`["別名", None, 3]`、`{"x": 1}`（無視）
- `TestNoteNames.test_the_file_name_comes_first_and_duplicates_are_dropped`

DB 側:

- `TestCollectAuthors.test_uses_the_spelling_of_the_book_with_the_smallest_id`
- `TestCollectAuthors.test_collects_a_translator_like_an_author`

自動作成（`rebuild`）:

- `TestCreate.test_creates_a_note_for_each_author_of_a_book_with_a_report` — §5.8 の `言語の起源` で `ダニエル・L・エヴェレット.md` と `松浦俊輔.md` ができ、先頭が `"---\ntype: author-note\n---\n\n# ダニエル・L・エヴェレット\n\n" + START`
- `TestCreate.test_does_not_create_a_note_for_an_author_without_a_report` — ファイルは無く、ハブの「ノートの無い著者」に `- 春木豊 — 1冊（レポート 0）`
- `TestCreate.test_does_not_create_a_second_note_for_a_spelling_variant` — `渡辺 照宏`（id 小）と `渡辺照宏` の2冊にレポート → `渡辺 照宏.md` だけ
- `TestCreate.test_does_not_create_a_note_when_an_alias_of_another_note_covers_the_author`
- `TestCreate.test_recreates_a_deleted_note_while_the_author_has_a_report`（既知の挙動）
- `TestCreate.test_adds_the_original_name_to_aliases_when_the_file_name_had_to_change` — `山田*太郎` → `山田太郎.md` ＋ `aliases: [山田*太郎]`。もう一度 `rebuild` しても新しいファイルは増えず、ノートの一覧にその本が載っている
- `TestCreate.test_does_not_overwrite_an_existing_file_with_the_same_name` — ユーザーが作った `山田太郎.md`（キー `山田太郎`）があり、別のキーの著者 `山田*太郎` にレポートがある → `note_stem` が同じ `山田太郎` になるが新しいファイルは作られず、`山田太郎.md` のマーカーの外は変わらない。ハブの「ノートの無い著者」に `山田\*太郎` が出る
- `TestCreate.test_skips_an_author_whose_name_has_no_usable_characters` — `???` → ファイルは無く、ハブに出る
- `TestCreate.test_does_not_create_a_note_named_like_the_hub` — 著者 `著者一覧`
- `TestCreate.test_a_created_note_is_not_rewritten_on_the_next_run` — 2回目の `rebuild` の戻り値に入らず、mtime も変わらない

著者ノートの一覧:

- `TestAuthorNote.test_fills_a_note_the_user_created_even_without_a_report`
- `TestAuthorNote.test_rewrites_only_between_the_markers_and_keeps_the_user_text`
- `TestAuthorNote.test_lists_books_like_a_theme_note` — §5.8 の行がそのまま出る（`- [お経の話](../0021-お経の話.md) — 渡辺照宏 · 読了 2026-08-02 · ★★★★★`、`- 仏教 第二版 — 渡辺 照宏 · 読書中`、`2冊（レポートあり 1冊）`）
- `TestAuthorNote.test_the_link_resolves_to_the_report_file` — リンク先を実際にたどってレポートに着く
- `TestAuthorNote.test_collects_books_of_every_alias`
- `TestAuthorNote.test_a_book_matched_by_two_names_of_one_note_is_listed_once`
- `TestAuthorNote.test_two_notes_sharing_a_name_both_list_the_book`
- `TestAuthorNote.test_links_related_themes_that_share_books` — `- [仏教](../themes/仏教.md) — 共通の本 2冊`
- `TestAuthorNote.test_says_so_when_no_book_matches`
- `TestAuthorNote.test_follows_an_author_change_in_the_db` — 著者欄を直すと、古いノートは「まだありません」、新しい名前のノートが作られる
- `TestAuthorNote.test_a_renamed_note_collects_by_its_new_name`（旧名を aliases に入れていなければ旧名のノートが作り直されることも確かめる）
- `TestAuthorNote.test_does_not_touch_a_note_whose_markers_are_broken`
- `TestAuthorNote.test_skips_a_note_that_was_just_edited`
- `TestAuthorNote.test_ignores_hidden_files_and_subfolders`

ハブとその他:

- `TestHub.test_creates_the_hub_with_notes_and_authors_without_a_note` — §5.8 の並びと行の形
- `TestHub.test_keeps_what_the_user_wrote_in_the_hub`
- `TestHub.test_the_hub_is_not_treated_as_an_author_note`
- `TestReportsAreNotConfused.test_author_notes_are_not_indexed_as_reports` — `authors/` に `book_id` 付きのノートがあってもレポート扱いされない
- `TestLock.test_waits_for_the_report_lock_before_writing`（テーマと同じ）

### 8.2 `backend/tests/test_theme_store.py`（追加。既存のテストは変更なしで通ること）

マーカーの検出:

- `TestMarkers.test_ignores_a_marker_mentioned_inline_and_appends` — 本文に `` `<!-- notes:books:start -->` と書く `` という行 → その行は変わらず、末尾に一覧が足される
- `TestMarkers.test_ignores_a_marker_pair_inside_a_code_fence_and_appends` — ```` ``` ```` の中に START/例/END → フェンスの中身は変わらず、末尾に足される
- `TestMarkers.test_replaces_only_the_real_pair_when_a_fenced_pair_also_exists` — `~~~` の中の1組＋本物の1組 → 本物だけ差し替わる
- `TestMarkers.test_does_not_touch_a_note_with_an_unclosed_fence`
- `TestMarkers.test_accepts_a_marker_line_with_surrounding_spaces`

警告と静穏判定:

- `TestWhenToWrite.test_warns_once_about_a_note_whose_markers_are_broken` — `caplog` で2回 `rebuild` → 警告は1件。直して `rebuild` → 警告なし。また壊して `rebuild` → もう1件
- `TestWhenToWrite.test_writes_a_note_whose_mtime_is_far_in_the_future` — mtime を `now + 3600` にして `quiet_seconds=10, now=now` → 書かれる
- `TestWhenToWrite.test_skips_a_note_whose_mtime_is_just_ahead_of_now` — mtime を `now + 1` → 飛ばす

ウォッチャー:

- `TestWatcher.test_runs_every_job_with_one_session` — 2つのジョブ（`def` で定義）が同じセッションで呼ばれる（`_tick()` を直接呼ぶ）
- `TestWatcher.test_a_failing_job_does_not_stop_the_others` — 1つ目が例外 → 2つ目は呼ばれる。同じ例外を2回起こしてもログは1回

### 5.13 追記（2026-10-12、実装後の敵対的レビューを反映）

上の §5.2〜§5.12 から次のように変えた。決定（§3）は変えていない。

**差し込みの共通部分（`theme_store.py` / `report_store.write_atomic`）**

- マーカー行は「行頭の空白0〜3個（タブ不可）＋マーカー＋末尾の空白」だけを数える。フェンスはリスト記号・
  引用 `>`・字下げを剥がしてから判定する（Obsidian の既定のリスト内コードブロックはタブ字下げ）。
  info 文字列にバッククォートがある行はバッククォートのフェンスの開きにしない。複数行の HTML コメントの中も
  隠す。これまでは、例として書いたマーカーの間をユーザーの文章ごと一覧で上書きしていた（再現済み）。
- `escape_text` は改行類（`\n \r \v \f \x1c-\x1e \x85 \u2028 \u2029`）を空白1つにし、`~` も逃がす。
  書名に `\n~~~` があるとアプリ自身が開いたフェンスを書いて以後止まる、`\r` で毎回書き直し続ける、を防ぐ。
- `fill_block` は差し込んだ全文を読み直し、マーカーの組がちょうど1つ見えなければ書かない（自己検証）。
- `report_store.write_atomic(path, text, *, expect=None) -> bool`。`expect=(mtime_ns, size)` なら置き換えの
  直前に stat し直して違えば置き換えない。`expect=ABSENT` なら `os.link` で作り、既にあれば作らない。
  `update_file` は最初の stat の値を渡す（読んでから置き換えるまでの Obsidian の保存を消さない。stat から
  置き換えまでの数マイクロ秒の窓と、mtime と size が同じままの書き換えは見分けられない）。ハードリンクの
  使えないファイルシステムでは新規作成が「書けない」になる。
- `update_file` は stat・read・write の `OSError` をパスごとに1回だけ警告して続ける。`scan_notes` は項目ごとに
  飛ばし（自分を指す symlink 1つで全ノートが見えなくならない）、ディレクトリ自体を開けないときは例外にする。
  同じ問題があったレポートの索引（`report_store._ReportIndex`）も項目ごとに飛ばすようにした。
- 末尾に足すときは末尾の改行と空白だけの行を落とす（ユーザーの最終行の行末の空白2つ＝改行を消さない）。
- ウォッチャーのジョブ名は `__qualname__`（無ければ `repr`）から作る。

**著者ノート（`author_store.py`）**

- 名前: 書式文字（Unicode の Cf。ゼロ幅空白など）を先に落としてから NFKC。括弧の外の `,` `、` だけで分け、
  括弧の中が役割だけ（`(著, 編集)` など）なら丸ごと落とす。役割の除去は変化が無くなるまで繰り返す
  （`山田太郎 編 著` → `山田太郎`。`split_authors` は冪等）。役割の語に 編集・翻訳・イラスト・写真 などを足した。
  `note_stem` は文字か数字を1つも含まなければ空（作らない）。
- `scan_notes(directory) -> NoteScan(notes, doubts)`。空・`---` で始まるのに解釈できない frontmatter・
  読めないファイルを `doubts` に残す。`doubts` があるか、直近 `quiet_seconds` 以内に更新されたノートがある回は
  **自動作成だけ**控える（編集途中で `aliases` を読めないノートのせいで、まとめた著者のノートを作り直して
  残さないため）。2回続けて残っている `doubts` は、直るまでに1回だけ警告する。
- 自動作成の前に、雛形を読み直して自分の著者を集めることを確かめる。ファイル名にしたときのキーが他の著者の
  キーか既に集められているキーと重なるなら作らない（`a: b` と `AB`、`Ab*Cd` と `Ab Cd` など）。作るたびに
  その回の `covered` に足す。
- `main.env_enabled(name)`: `0` `false` `off` `no`（大文字小文字・前後の空白を無視）で止まる。

- `note_stem`（2026-10-12、0003 の実装で訂正）: 空白と先頭・末尾の `.` を `strip(" .")` で一度に落とす
  （「空白を詰めて strip → `.` を落とす」の順だと `. .a` が隠しファイル `.a.md` になるため）。

**見送ったもの**（今の規模・環境では起きにくい。§9 に加える）: Windows の予約名（`CON.md` など）、
引用符なしの aliases が YAML 1.1 の型に変わる（`yes` → true）、1回の rebuild が quiet を超えたときの静穏判定、
テーマの「関連するテーマ」の O(n²)。

## 9. 未決事項

- 作らせたくない著者（一度きりの訳者・共著者など）を除外する手段（例: ハブの frontmatter に `exclude`）。
  いまは消しても作り直される。
- 区切りの無い役割表記（`山田太郎著`）、`ほか`・`他`、スラッシュで並べた複数著者（`A／B`）の扱い。
- 著者を DB のテーブルにして役割（著・訳・編）を持つか。
- テーマノートにも「関連する著者」を出すか（いまは著者 → テーマの片方向）。
- ハブの並びを五十音にするか（読みが DB に無い）。
- 以下はテーマノート側で指摘された弱点で、今回は直さない（ユーザーの判断待ち）。著者ノートも同じ部品を
  使うので、NFD・大文字小文字以外は著者ノートにも当てはまる。
  - サブフォルダ（`themes/*/`・`authors/*/`）のノートを無視している。
  - テーマノートの frontmatter の `tags` の YAML の読み違い。
  - タグ照合の大文字小文字・ネストしたタグ（`親/子`）・NFD の扱い（著者ノートの照合キーは NFKC＋除去＋
    casefold なので、著者側では起きない）。
  - CRLF・BOM・symlink のノートを書き換えると、LF・BOM なし・通常ファイルに変わる。
  - 関連テーマの計算が O(n²)（著者ノートはテーマの所属を1回だけ計算する）。
- （2026-10-12 追記）レビューで見送ったもの: Windows の予約名のファイル名、引用符なしの aliases の型変換、
  rebuild が quiet_seconds を超えたときの静穏判定（時刻を1回しか取らない）、テーマ側の O(n²)。
