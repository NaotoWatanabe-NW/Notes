# 0003 テーマノート・著者ノートの一括作成（`scripts/create_notes.py`）

## 1. 状態・日付

- 状態: 実装済み（2026-10-12）
- 日付: 2026-10-12
- 関連: [0002 著者ノート](0002-author-notes.md)（§5.5 自動作成の規則、§5.13 追記）、SPEC §4「テーマノート」「著者ノート」、
  `scripts/strip_report_frontmatter.py`（一回限りのスクリプトの作法）

## 2. 背景と目的

ユーザーの依頼: 「現状のタグと保有本の著者でテーマノート、著者ノートを空で作っておいて」。

いまの方針（0002）では、テーマノートはユーザーが作り、著者ノートはアプリが自動で作るがレポートのある著者だけ。
これを変えずに、**いまあるタグ全部と本棚の著者全部のノートを一度にまとめて作る**手段を用意する。

実データ（`backend/reading.db` と `reports/`）はユーザーの PC にだけあり、このリポジトリには無い。
だから**ユーザーが自分の PC で流すスクリプト**にする。何度流しても同じ結果になる（冪等）ので、あとで増えたタグ・
著者のノートも、もう一度流せば作られる。

## 3. 決定

1. **一回限りのスクリプト `scripts/create_notes.py`**。既定は下見（作るファイルと、作らないものとその理由を出すだけで、
   何も書かない）。`--apply` で作る。`--db PATH` で DB を変えられる（既定は `<repo>/backend/reading.db`）。
   作法は `scripts/strip_report_frontmatter.py` に合わせる（`sys.path` に `backend` を足して `app` を import、
   `main(argv=None) -> int`、最後に集計の1行、終了コード）。
2. **DB は読み取り専用で開き、一切書かない**。`sqlite3.connect(<パスの file: URI>?mode=ro, uri=True)` を
   SQLAlchemy の `creator` に渡す（§5.2）。URL 文字列 `sqlite:///file:<パス>?mode=ro&uri=true` は**使わない**。
   パスに `?` や `#` があると URL が途中で切れ、`mode=ro` が効かずに**空の DB ファイルを作ってしまう**（実測。§6）。
   DB のファイルが無ければ開かずに終了コード 1。`app.database` の `DATABASE_URL`・`engine`・`configure_sqlite` は使わない。
3. **置き場所**は `report_store.reports_dir()`（`NOTES_REPORTS_DIR` に従う）の `themes/` と `authors/`。
   `reports_dir()` が無ければ終了コード 1（設定の間違いで別の場所に作らないため）。
4. **対象**: テーマ＝1冊以上の本に付いているタグ全部（`/api/tags` と同じ集合）。著者＝本棚の全部の本（状態を問わない。
   積読も含む）を `author_store.collect_authors` で分けた著者全部（レポートの有無を問わない）。
5. **既存のファイルは上書きも変更もしない**。既にどれかのノートが集めているタグ・著者は作らない
   （テーマ: 既存の各テーマノートの `theme_tags` の和集合。著者: 既存ノートの stem＋aliases のキー）。
   **ハブ（`テーマ一覧.md`・`著者一覧.md`）と既存ノートのマーカー内もスクリプトは触らない**。それらはアプリの
   `ThemeWatcher` が普段どおり数秒で書き直す（§5.7）。
6. **著者ノートは自動作成と同じ確認を通す**。`author_store._create_notes` の中の「作ってよいかの判定」を、
   書かない公開関数 `plan_new_notes(..., include_without_report=False)` に切り出す。ウォッチャーの `_create_notes` は
   これを既定の引数で呼んで書くだけにし、振る舞いは変えない（レポートのある著者だけ）。スクリプトは
   `include_without_report=True` で計画を立て、`theme_store.create_file` で1つずつ作る。
   （オーケストレーターの決定「`_create_notes` に引数を足す」から変えた。下見で理由を出すには書かずに判定する関数が要り、
   スクリプトは `_create_notes` を呼ばないので、引数を `_create_notes` に置くと使われない。）
7. **テーマノートの雛形**: `type: theme-note` の frontmatter ＋ `# タグ名`。ファイル名はタグを
   `theme_store.note_stem` で整えたもの（**NFKC はかけない**。テーマの照合は文字列の完全一致なので、タグの表記の
   ままのほうが `tags` を書かずに済む）。ファイル名（拡張子なし）がタグと完全に一致しないときだけ `tags: [タグ名]` を入れる。
   作る前に雛形を `split_front_matter` → `theme_tags` で読み直し、集めるタグがちょうどそのタグ1つでなければ作らない。
8. **待つ条件**: 著者は `NoteScan.reason_to_wait`（編集中・壊れた・直近に更新されたノート）があれば著者ノートを作らない。
   **テーマにも同じ判定を足す**（`theme_store.unsettled_reason`）。どちらかで待ったら理由を出して終了コード 1
   （もう一度流してもらう）。片方が待っても、もう片方は作る。
   （オーケストレーターの決定に無い追加。テーマの `scan_notes` は読めないノートを黙って飛ばし、壊れた frontmatter は
   ファイル名だけを集めるとみなすので、そのまま判定すると、ユーザーが複数のタグをまとめたノートを書きかけのときに
   同じタグのノートを重ねて作ってしまう。決定 5 を確かに守るため。）
9. **「空で」＝ユーザーが書く本文が空**。マーカー内の一覧（アプリが書くビュー）は最初から入れる（テーマも著者も。§5.6）。
10. 書き込みは `theme_store.update_file` を使う新しい小関数 `theme_store.create_file(path, text, quiet_seconds, now)`
    （無いときだけ作る。`make_text` は `current is None` のときだけ文字列を返す。新規作成は `os.link` なので、
    直前に同名のファイルができていれば作らない）。
11. ウォッチャーの方針（テーマノートはユーザーが作る・著者ノートはレポートのある著者だけ自動）と、フロントエンド・API は変えない。
12. 終了コード: 0＝正常（作らないものがあっても、理由が恒久的なものなら 0）。1＝DB が無い・読めない／置き場所が無い／
    どちらかが待った／`--apply` で作れなかったファイルがある／ノートのフォルダが読めない。2＝引数の誤り（argparse）。

## 4. 全体像

```
 ユーザーの PC
 ┌──────────────────────────────────────────────────────────────────────────────────────┐
 │ .venv/bin/python scripts/create_notes.py [--apply] [--db PATH]                        │
 │                                                                                      │
 │  backend/reading.db ──(読み取り専用 mode=ro)──▶ books（＋tags）                          │
 │                                                  │                                   │
 │  reports/（NOTES_REPORTS_DIR）                    ▼                                   │
 │   ├ 0012-….md ── report_paths() ──▶ ┌───────────────────────────────┐                  │
 │   ├ themes/  ──── scan_notes ─────▶ │ 1. テーマ                        │                  │
 │   │   unsettled_reason（待つか）     │   theme_store.plan_new_notes    │── create_file ──▶ themes/<タグ>.md（新規だけ）
 │   │                                │   （書かない。作る/作らない＋理由）│                  │
 │   └ authors/ ──── scan_notes ─────▶ │ 2. 著者                          │                  │
 │       reason_to_wait（待つか）       │   author_store.plan_new_notes   │── create_file ──▶ authors/<著者>.md（新規だけ）
 │                                    │   (include_without_report=True) │                  │
 │                                    └───────────────────────────────┘                  │
 │  標準出力: + 作る（作った）ファイル   標準エラー: ! 作らない理由・待つ理由・作れなかったもの      │
 └──────────────────────────────────────────────────────────────────────────────────────┘
        ハブ（テーマ一覧.md・著者一覧.md）と既存ノートのマーカー内はスクリプトは触らない。
        アプリ（notes-web）が動いていれば ThemeWatcher が 5 秒ごとに書き直す（新しいノートは作成から 10 秒は飛ばす）。

 ウォッチャー側（変わらない）:
   author_store.rebuild → _create_notes(...) → plan_new_notes(...)（既定: レポートのある著者だけ）→ create_file
```

## 5. 詳細

### 5.1 変更・新規ファイル

| ファイル | 変更 |
|---|---|
| `scripts/create_notes.py` | **新規**。§5.8 |
| `backend/app/theme_store.py` | 追加: `NOTE_TYPE`・`note_stem`・`new_note_text`・`PlannedNote`・`CreatePlan`・`plan_new_notes`・`unsettled_reason`・`create_file`・`front_matter_doubt`（author_store から移す）。既存の関数は変えない |
| `backend/app/author_store.py` | 追加: `PlannedNote`・`CreatePlan`・`plan_new_notes`。変更: `_create_notes` を「計画 → `create_file`」に。`_doubt_of` と `_FRONT_MATTER_OPEN` を `theme_store.front_matter_doubt` へ移す（振る舞いは同じ） |
| `backend/tests/test_create_notes.py` | **新規**（§8.1） |
| `backend/tests/test_theme_store.py` | 追加（§8.2）。既存のテストは変更なしで通ること |
| `backend/tests/test_author_store.py` | 追加（§8.3）。既存のテストは変更なしで通ること |
| `docs/SPEC.md` | §3 の地図の `scripts/` の行、§4 のテーマノート・著者ノートの節に1行ずつ（§7） |
| `docs/design/README.md` | 一覧に 0003 |

フロントエンド・API・`main.py`・DB のスキーマは変えない。

### 5.2 DB を読み取り専用で開く（スクリプトの中）

```python
def open_readonly(path: Path) -> Engine:
    """`path` の SQLite を読み取り専用で開くエンジン。ファイルが無いときに作らない。"""
    uri = path.resolve().as_uri() + "?mode=ro"     # 空白・#・?・%・日本語は % で符号化される
    return create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
```

- 開く前に `path.is_file()` を確かめ、無ければ `DB が見つかりません: <パス>（--db で指定できます）` を stderr に出して 1。
  `mode=ro` は無いファイルを作らないが、メッセージを分かりやすくするため先に見る。
- `configure_sqlite` は呼ばない（`PRAGMA journal_mode=WAL` は WAL でない DB では書き込みになり失敗する。読むだけなら要らない）。
  `app.database` の `engine` / `SessionLocal` / `get_db` も使わない（`DATABASE_URL` は作業ディレクトリ基準）。
  `app.models` を import すると `app.database` の engine オブジェクトは作られるが、接続しないのでファイルはできない。
- 読み方: `with Session(engine) as db:` の中で
  `list(db.scalars(select(Book).options(selectinload(Book.tags)).order_by(Book.id)))` を読み、セッションを閉じてから使う
  （閉じたあとも、読み込み済みの列と `tags` は使える。ノートの組み立てが触るのは id・title・author・status・
  finished_on・rating・tags[].name だけ）。最後に `engine.dispose()`。
- `sqlalchemy.exc.SQLAlchemyError`（SQLite でないファイル・テーブルが無い・列が無い）は
  `DB を読めません: <パス>: <例外の1行目>` を stderr に出して 1。
- 書き込みは SQLite が拒否する（`attempt to write a readonly database`）。DB ファイルの中身と mtime は変わらない。
  ただし、アプリが止まっているときに開くと、SQLite が `reading.db-wal` / `reading.db-shm`（空）を作って残すことがある
  （実測。中身は変えない。`.gitignore` 済み。次にアプリが開けば普段どおり使われる）。
- アプリ（notes-web）が動いていても読める（WAL なので書き手を止めない。コミット済みの最新が見える）。

### 5.3 対象の集め方

- タグ: `{tag.name for book in books for tag in book.tags}`（どの本にも付いていないタグは入らない。`/api/tags` と同じ）。
- 著者: `author_store.collect_authors(books)`（全部の本。著者欄が空の本はどの著者にも入らない）。
- レポート: `report_store.report_paths()`（一覧のリンク先と、著者の「レポートあり」の判定に使う）。

### 5.4 テーマノート（`theme_store.py` に足すもの）

```python
NOTE_TYPE = "theme-note"
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f\x7f]')   # author_store._UNSAFE_NAME と同じ文字
_STEM_BYTES = 200
_FRONT_MATTER_OPEN = re.compile(r"---[ \t]*(?:\r?\n|\Z)")       # author_store から移す

def note_stem(tag: str) -> str:
    """テーマノートのファイル名（拡張子なし）。作れなければ空文字。

    1. 書式文字（Unicode のカテゴリ Cf）を落とす  2. _UNSAFE_NAME の文字を落とす
    3. 空白の連続を半角空白1つにして前後を strip  4. 先頭・末尾の "." を落とす
    5. UTF-8 で _STEM_BYTES バイトまでに切り（文字の途中では切らない）、もう一度 strip
    6. 文字・数字・句読点・記号（カテゴリ L / N / P / S）を1つも含まなければ ""
    NFKC はかけない（author_store.note_stem との違い。テーマの照合はタグ名の完全一致なので、
    表記を変えると tags を書かないと集められなくなる）。絵文字だけのタグ（S）は作れる。
    """

def new_note_text(tag: str, stem: str) -> str:
    """テーマノートの雛形（マーカーはまだ無い）。
    meta = {"type": NOTE_TYPE}。stem != tag のときだけ meta["tags"] = [tag]。
    戻り値: report_store.front_matter_text(meta) + f"\n# {escape_text(tag)}\n"
    """

def front_matter_doubt(text: str, meta: dict) -> str:
    """author_store._doubt_of をそのまま移したもの（空のファイル / frontmatter を解釈できない / ""）。"""

def create_file(path: Path, text: str, quiet_seconds: float, now: float) -> bool:
    """path が無いときだけ text で作る。作ったら True。
    update_file に `lambda current: text if current is None else None` を渡すだけ。
    既にある（ロックを取るまでに誰かが作った・Obsidian で作った）なら触らず False。書けない（OSError）も False
    （update_file がパスごとに1回 logger.warning を出す）。
    """

@dataclass(frozen=True)
class PlannedNote:
    tag: str
    note: ThemeNote       # path と、雛形を読み直した集めるタグ（= (tag,)）
    text: str             # 書く全文（雛形 ＋ マーカー内の一覧）

@dataclass(frozen=True)
class CreatePlan:
    notes: list[PlannedNote]           # 作るもの（下の 2. の順）
    skipped: list[tuple[str, str]]     # 作らないタグと理由
    already: list[str]                 # 既にどれかのノートが集めているタグ

def plan_new_notes(directory: Path, books: list[Book], reports: dict[int, Path],
                   notes: list[ThemeNote]) -> CreatePlan:
    """本に付いているタグのうち、どのテーマノートも集めていないもののノートの計画。何も書かない。"""

def unsettled_reason(directory: Path, now: float, quiet_seconds: float) -> Optional[str]:
    """テーマノートの集めるタグをまだ信じられない理由（"ファイル名: 理由"）。信じてよければ None。"""
```

**`plan_new_notes` の手順**

1. `tags` = 本に付いているタグの集合。`covered` = `notes` の `tags` の和集合。
2. `tags` を `(note_stem(tag) != tag, tag)` の順に見る（**ファイル名がタグと一致するタグを先に**。`C` と `C#` が
   どちらも `C.md` になるとき、`C.md` は `C` のノートにする）。各タグについて上から順に判定し、最初に当たった理由で作らない。

   | 判定 | 結果 |
   |---|---|
   | `tag in covered` | `already` に入れる（作らない。理由は出さない） |
   | `stem = note_stem(tag)` が空 | `ファイル名にできる文字が無い` |
   | `f"{stem}.md" == HUB_NAME` | `ファイル名がハブ（テーマ一覧.md）と同じになる` |
   | 既存ノートのファイル名と同じ | `<名前> が既にあり、このタグを集めていない（そのノートの frontmatter の tags に足すと集める）` |
   | この回に先に計画したファイル名と同じ | `<名前> はこの回に「<先のタグ>」のノートとして作る` |
   | `os.path.lexists(directory / 名前)`（ノートとして読めないファイル・壊れた symlink・同名のフォルダ） | `<名前> が既にある（テーマノートとして読めないファイル）` |
   | 雛形を `split_front_matter` → `theme_tags(meta, stem)` で読んだ結果が `(tag,)` でない | `ノートに書くと集めるタグが「<読んだタグ>」になり、このタグと一致しない` |

   通ったタグは「計画した名前」に記録して候補にする。
3. 候補の全部を `after = notes + 候補の ThemeNote` として、各候補の一覧を `theme_block(note, books, reports, after)` で作る
   （「関連するテーマ」に同じ回に作るノートも出る。アプリが次の回に作る一覧と同じ中身になるので、アプリは書き直さない）。
   `text = replace_block(雛形, block)`。`text is None` か `not _has_one_pair(text)` なら
   `一覧を書くとマーカーを読み戻せない（タグ名や書名の文字のため）` で作らない（`fill_block` と同じ自己検証）。
   ここで落ちた候補が他の候補の「関連するテーマ」に残ることがあるが、アプリが次の回に直す（起きるのは、タグや書名に
   改行とマーカーを仕込んだときくらい）。

**`unsettled_reason` の規則**（`author_store.NoteScan.reason_to_wait` と同じ判定をテーマにも）

- 対象は `scan_notes` と同じ: `directory` 直下の `*.md`。`.` で始まるものとハブ（`HUB_NAME`）は見ない。名前順。
- フォルダが無ければ None。フォルダ自体を開けない `OSError` は上げる（スクリプトが受けて終了コード 1）。
- 各ファイルについて、最初に当たったものを返す:
  - `entry.is_file()` が `OSError`、または stat・`read_text(encoding="utf-8-sig")` が `OSError` / `UnicodeDecodeError` → `読めない（<例外の型名>）`
  - `is_file()` が False（壊れた symlink・フォルダ）→ ノートではないので飛ばす
  - `front_matter_doubt(text, meta)` が空でない → その理由（`空のファイル` / `frontmatter を解釈できない`）
  - `abs(now - mtime) < quiet_seconds` → `直近に更新された`
- 返す文字列は `f"{path.name}: {理由}"`。

**`front_matter_doubt` の移動**: `author_store._doubt_of` と `_FRONT_MATTER_OPEN` を `theme_store` に移して公開名にし、
`author_store.scan_notes` は `theme_store.front_matter_doubt(text, meta)` を呼ぶ。中身は1文字も変えない
（循環 import を避けるため、下の層の `theme_store` に置く。author_store はもともと theme_store を import している）。

### 5.5 著者ノート（`author_store.py`）

```python
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
    既定はレポートが1冊以上ある著者だけ（ウォッチャーの自動作成）。True なら全部の著者。"""

def _create_notes(directory, authors, notes, reports, themes, quiet_seconds, now) -> list[AuthorNote]:
    """シグネチャは変えない。plan_new_notes(...)（既定の引数）の notes を順に
    theme_store.create_file(p.note.path, p.text, quiet_seconds, now) で作り、作れた p.note を返す。"""
```

**`plan_new_notes` の手順**（いまの `_create_notes` の判定を同じ順で。理由を付けるだけ）

`covered` = 全ノートの `keys` の和集合。著者を `(author.name, author.key)` の順に見て、最初に当たった理由で作らない。

| 判定 | 結果 |
|---|---|
| `author.key in covered` | `already` に入れる |
| `include_without_report` が False で、`author.books` のどれも `reports` に無い | 何にも入れない（いまと同じ。理由は出さない） |
| `stem = note_stem(author.name)` が空 | `ファイル名にできる文字が無い` |
| `f"{stem}.md" == HUB_NAME` | `ファイル名がハブ（著者一覧.md）と同じになる` |
| 既存ノートのファイル名と同じ | `<名前> が既にあり、この名前を集めていない（そのノートの aliases に足すと集める）` |
| この回に先に計画したファイル名と同じ | `<名前> はこの回に「<先の著者>」のノートとして作る` |
| `os.path.lexists(directory / 名前)` | `<名前> が既にある（著者ノートとして読めないファイル）` |
| 雛形（`new_note_text`）を読み直した `note.keys` に `author.key` が無い | `ノートに書くとこの名前を集められない` |
| `(note.keys - {author.key}) & (covered | authors.keys())` | `ファイル名にすると他の著者か既存のノートの名前と見分けがつかない` |

通ったら `text = replace_block(new_note_text(author, stem), author_block(note, books_of(note, authors), reports, themes))`、
`covered |= note.keys`、計画した名前に記録する。

**ウォッチャーへの影響**（既存のテストが変更なしで通ることで確かめる）

- いまは「書けたら」`covered` と `taken` に足していたのを「計画したら」足す。違いが出るのは書き込みに失敗したときだけで、
  そのときは後ろの重なる著者がその回は作られず、次の回に回る（安全側）。
- `lexists` の判定を足したので、同名の読めないファイル・壊れた symlink・フォルダがある著者は、書き込みで失敗する代わりに
  計画で外れる（見える結果は同じ。作られない）。こうしないと、ずっと書けない名前が計画で `covered` を占め続け、
  重なる別の著者まで永久に作られなくなる。
- 既存の `test_does_not_overwrite_a_file_that_appeared_after_the_scan`（`scan_notes` を空に差し替える）は、この `lexists` で
  外れるようになるが、アサーション（上書きしない・書いたファイルに入らない）はそのまま通る。走査とロックの間にできた
  ファイルを `os.link` が守ることは `TestCreateFile` と §8.1 の「計画のあとに同じ名前のファイルができていたら」で見る。
- 雛形は必ず `new_note_text`（モジュールの名前で引く）経由で作る。`_new_note_meta` を差し替える既存のテストがあるため。

### 5.6 マーカー内の一覧を最初から入れる（判断と理由）

**入れる**（テーマも著者も）。

- 著者ノートは既存の自動作成の道（`author_block` を雛形に差し込む）をそのまま使うので、もともと一覧が入る。テーマも揃える。
- アプリが止まっていても、作った直後から Obsidian で本の一覧が見える。スクリプトは DB を直接読むので、アプリの起動を前提にしない。
- 作った直後に `rebuild` を呼んで一覧を入れる方法は取れない。`update_file` は mtime が `quiet_seconds`（10秒）以内の
  ファイルを飛ばすので、作ったばかりのノートには入らない。さらに `rebuild` は既存ノートとハブも書き直す（決定 5 に反する）。
- 一覧はアプリの持ち物（ビュー）で、ユーザーが書く本文は空のまま。依頼の「空で」に反しない（0002 の自動作成と同じ形）。
- アプリが動いていれば、次の回（作成から10秒後以降）に同じ規則で作り直す。中身が同じなら書かない。

### 5.7 ハブと既存ノートはスクリプトが触らない

- ハブ（`テーマ一覧.md`・`著者一覧.md`）は作らない・書き直さない。既存ノートのマーカー内（「関連するテーマ」など）も触らない。
- アプリ（notes-web）が動いていれば、`ThemeWatcher` が5秒ごとにハブと既存ノートの一覧を書き直す（新しいノートが
  「テーマノート」「著者ノート」の側に移る）。止まっていれば次の起動で入る。これはアプリの普段の動きで、スクリプトの書き込みではない。

### 5.8 スクリプト `scripts/create_notes.py`

```
使い方:
    .venv/bin/python scripts/create_notes.py                    # 下見（何も書かない）
    .venv/bin/python scripts/create_notes.py --apply            # 作る
    .venv/bin/python scripts/create_notes.py --db /path/to/reading.db
```

- 冒頭: `REPO_ROOT = Path(__file__).resolve().parents[1]`、`sys.path.insert(0, str(REPO_ROOT / "backend"))`、
  `from app import author_store, report_store, theme_store`、`from app.models import Book`。
  `DEFAULT_DB = REPO_ROOT / "backend" / "reading.db"`。docstring に目的・使い方・流す前の注意（§7.2）を書く。
- 公開する関数: `open_readonly(path) -> Engine`（§5.2。テストから使う）、`main(argv: Optional[list[str]] = None) -> int`。
- ログの設定はしない（`update_file` の警告は Python の既定で stderr に出る）。

**`main` の流れ**

1. 引数: `--apply`（store_true）、`--db`（文字列。`Path(...).expanduser().resolve()`。既定 `DEFAULT_DB`）。
2. `directory = report_store.reports_dir()` が `is_dir()` でなければ
   `ノートの置き場所（レポートのディレクトリ）が見つかりません: <パス>` → 1。
3. DB を §5.2 のとおり読む（失敗は 1）。`reports = report_store.report_paths()`、`now = time.time()`、
   `quiet = theme_store.QUIET_SECONDS`（呼んだ時点の値を読む）。
4. **テーマ**: `theme_store.unsettled_reason(themes_dir, now, quiet)` が文字列なら、
   `テーマノートを作らない: <理由>（Obsidian で編集中なら閉じ、10秒ほどおいてもう一度流す）` を出して待ち（作らない）。
   そうでなければ `scan_notes` → `plan_new_notes` → 表示。`--apply` なら `themes_dir` を `mkdir(parents=True, exist_ok=True)`
   してから（作るものがあるときだけ）、計画の順に `create_file`。
5. **著者**: `authors_dir` が無ければ `NoteScan([], [])`、あれば `author_store.scan_notes`。`reason_to_wait(now, quiet)` が
   文字列なら `著者ノートを作らない: <理由>（…同上…）` で待ち。そうでなければ
   `themes = [(n.path, {b.id for b in theme_store.books_for(n.tags, books)}) for n in テーマノート]` を作り
   （テーマノート＝既存 ＋ この回に作った（下見では作る予定の）もの。著者ノートの「関連するテーマ」に新しいテーマノートも出す）、
   `plan_new_notes(..., include_without_report=True)` → 表示 → `--apply` なら同じように `mkdir` して `create_file`。
6. ノートのフォルダを開けない `OSError`（`unsettled_reason` / `scan_notes`）は `<フォルダ> を読めません: <例外>` を出して 1
   （他方は続ける）。
7. 終わりの行を出して、終了コードを返す（決定 12）。

**出力の形**（テストは部分文字列で見る。行頭の記号と主な文言は変えない）

標準出力:

```
DB（読み取り専用）: /home/naoto/Notes/backend/reading.db
ノートの置き場所: /home/naoto/Notes/reports
本 128 冊・タグ 24 個・著者 85 人

テーマノート（themes/）
  + 地政学.md
  + 日本史近代.md（tags: 日本史/近代）
作る 20 / 既にノートあり 3 / 作らない 1

著者ノート（authors/）
  + 渡辺照宏.md
  + 山田太郎.md（aliases: 山田*太郎）
作る 72 / 既にノートあり 12 / 作らない 1

下見のみ。--apply を付けると 92 件を作る（既存のファイルは変えない）。
```

- `+` の行の括弧: テーマは `stem != tag` のとき `（tags: <タグ>）`、著者は `author_key(stem) != author.key` のとき
  `（aliases: <表示名>）`（雛形にそのキーを入れたことを示す）。
- `--apply` のときは、`+` の行は実際に作れたものだけ。最後の行は
  `作った 92 / 作れなかった 0。アプリが動いていれば、ハブと既存ノートの一覧は十数秒で更新される。`
- 待ったセクションは `+` の行と集計の代わりに `待ち（このセクションは作らない）` を出す。

標準エラー（行頭 `  ! `）:

```
  ! #メモ: ノートに書くと集めるタグが「メモ」になり、このタグと一致しない
  ! ★★★: ファイル名にできる文字が無い
  ! 著者ノートを作らない: ウェルズ.md: 直近に更新された（Obsidian で編集中なら閉じ、10秒ほどおいてもう一度流す）
  ! 日本史近代.md: 作れなかった（同名のファイルができていた、または書けなかった。もう一度流すと理由が出る）
```

### 5.9 生成されるノートの例

テーマノート（ファイル名とタグが一致する。`themes/地政学.md`）:

```markdown
---
type: theme-note
---

# 地政学

<!-- notes:books:start -->
## このテーマの本

<!-- ここから end まではアプリが DB のタグから書き直す（手で編集しない）。集めるタグ: 地政学 -->

2冊（レポートあり 1冊）

### レポートのある本

- [地政学入門](../0001-地政学入門.md) — 曽村保信 · 読了 2026-09-20 · ★★★★

### まだレポートの無い本

- 明治維新 — 山田\*太郎／著, 鈴木花子 訳 · 積読

### 関連するテーマ

- [日本史近代](日本史近代.md) — 共通の本 1冊
<!-- notes:books:end -->
```

テーマノート（ファイル名に使えない `/` を落としたので一致しない。`themes/日本史近代.md`）。`tags` は
`front_matter_text` の書き方（ブロック形式）で入る。`theme_tags` はどちらの形も読む:

```markdown
---
type: theme-note
tags:
- 日本史/近代
---

# 日本史/近代

<!-- notes:books:start -->
## このテーマの本
…（同じ形）
<!-- notes:books:end -->
```

著者ノートは既存の雛形（`new_note_text`。0002 §5.8）のまま。レポートの無い著者でも同じ形で、一覧は
「まだレポートの無い本」の節だけになる（例: `authors/鈴木花子.md` に `明治維新` が積読で1行）。

### 5.10 エッジケース

| ケース | 例 | 結果 |
|---|---|---|
| タグにファイル名に使えない文字 | `日本史/近代`、`x:y`、`C#` | 作る。ファイル名は文字を落としたもの、`tags: [<タグ>]` を入れる |
| タグに見えない書式文字 | `地政​学` | 作る。ファイル名は落としたもの（`地政学.md`）＋ `tags`。`地政学` のタグもあれば、そちらが先に `地政学.md` を取り、こちらは「この回に作る」で作らない |
| NFKC で変わるタグ | `ＳＦ`、`ｶﾞｲﾄﾞ` | 作る。NFKC をかけないので `ＳＦ.md`、`tags` は入れない |
| `#` で始まるタグ | `#メモ` | 作らない。`theme_tags` が `#` を落とすので集められない（理由: 集めるタグが「メモ」になる） |
| 前後に空白のあるタグ | ` 歴史` | 作らない。`theme_tags` が strip するので一致しない |
| ハブと同名になるタグ・著者 | `テーマ一覧`、`著者一覧` | 作らない（ハブと同じ名前） |
| ファイル名にできる文字が無い | タグ `...`、著者 `★★★` | 作らない（著者は L/N を要する既存の `note_stem`、テーマは L/N/P/S） |
| 2つのタグが同じファイル名 | `C` と `C#` | ファイル名と一致する `C` が `C.md`。`C#` は「この回に `C` のノートとして作る」で作らない |
| 既存ノートが別のタグで同名 | `C.md` が既にあり `C` を集める。タグ `C#` | 作らない。理由で「そのノートの tags に足すと集める」と案内 |
| 既にテーマノートが集めているタグ | `歴史.md` に `tags: [日本史, 世界史]` | `日本史`・`世界史` は作らない（既にノートあり） |
| aliases で集められている著者 | `ウェルズ.md` に `aliases: [H・G・ウェルズ]` | 作らない（既にノートあり） |
| ファイル名にすると名前が変わる著者 | `山田*太郎` | 作る（`山田太郎.md` ＋ `aliases: [山田*太郎]`）。ただし `山田太郎` という著者もいれば作らない（見分けがつかない） |
| キーが重なる著者 | `A b*` と `Ab?`（ファイル名のキーがどちらも `ab`） | 先の1人だけ作る。後は「見分けがつかない」 |
| 同名の読めないファイル・壊れた symlink・フォルダ | `authors/山田太郎.md` が壊れた symlink | 作らない（既にある・読めないファイル） |
| 編集中・壊れた・直近10秒に更新されたノート | 空のファイル、閉じていない frontmatter、Obsidian で入力中 | そのセクション（テーマ／著者）だけ作らない。理由を出して終了コード 1。もう片方は作る |
| アプリが同時に動いている | notes-web 常駐中 | 作れる。DB は WAL で読める。同名のファイルをウォッチャーが先に作っていたら `os.link` が失敗して上書きしない（「作れなかった」・終了コード 1。もう一度流すと「既にノートあり」） |
| アプリが直前に既存ノートの一覧を書き直した | 本を足した直後 | そのノートが「直近に更新された」で待つ（終了コード 1）。10秒おいて流し直す |
| 作った直後にもう一度流す | `--apply` の直後 | 作ったノートが「直近に更新された」で待つ。10秒おけば「作る 0」 |
| DB が無い | `--db` の打ち間違い | 何も作らず（空の DB も作らず）終了コード 1 |
| DB が読めない | SQLite でないファイル、古いスキーマ | 終了コード 1。古いスキーマなら、アプリを新しいコードで一度起動して列を足してから流す |
| DB のパスに `?` `#` 空白・日本語 | `--db "~/a b#c/reading.db"` | 読める（`as_uri()` で符号化）。空のファイルを作らない |
| ノートの置き場所が無い | `NOTES_REPORTS_DIR` の打ち間違い | 何も作らず終了コード 1 |
| `themes/`・`authors/` が無い | 初めて | 下見は作らない。`--apply` で作るものがあるときだけ作る |
| サブフォルダのノート | `themes/歴史/日本史.md` | 見ない（アプリと同じ。0002 §9）。直下に同じタグのノートを作る。下見で確かめる |
| 大文字小文字を区別しないファイルシステム | `SF` と `sf` | Linux（母艦）では別のファイル。区別しない FS でも `os.link` が既存を検出して上書きしない |

## 6. 選ばなかった案と理由

- **SQLAlchemy の URL 文字列 `sqlite:///file:<パス>?mode=ro&uri=true`**: パスの `?` で URL が切れ、`#` 以降は
  フラグメントになる。`a b#c?d/r.db` で試すと `mode=ro` が効かず、**`a b` という空の DB ファイルができた**。
  `creator` と `Path.as_uri()` なら符号化されるので起きない。
- **`immutable=1`**: ロックも WAL も見ないので、アプリが動いているときに古い・食い違った中身を読む。
- **作ったあとに `theme_store.rebuild` / `author_store.rebuild` を呼ぶ**: 既存ノートとハブを書き直す（決定 5 に反する）うえ、
  作ったばかりのノートは静穏時間で飛ばされて一覧が入らない。
- **テーマのファイル名に `author_store.note_stem`（NFKC あり）を使う**: `ＳＦ` が `SF.md`＋`tags` になり、
  「タグ名.md を作るだけ」（ハブの説明）とずれる。`theme_store` から `author_store` を import すると循環にもなる。
- **アプリの API・ウォッチャーで全部を作る**: 方針（テーマはユーザーが作る・著者はレポートのある著者だけ）を変える。
  依頼は今ある分の一括作成なので、一回限りのスクリプトで足りる。

## 7. 影響範囲・移行

### 7.1 デプロイの順序

- DB のスキーマ・API・画面は変わらない。`author_store` / `theme_store` の変更はウォッチャーの振る舞いを変えない。
- スクリプトはリポジトリの `backend/app` を直接 import するので、アプリの再起動を待たずに流せる。コードの更新後は
  普段どおり `systemctl --user restart notes-web` してよい（順序の制約は無い）。

### 7.2 実行手順（ユーザー向け。SPEC とスクリプトの docstring にも書く）

```bash
cd ~/Notes
git pull                                                # この変更を取り込む
.venv/bin/python scripts/create_notes.py | less         # 1. 下見。作るファイルの数と名前、作らない理由を確かめる
.venv/bin/python scripts/create_notes.py --apply        # 2. 作る（既存のファイルは変えない）
# 3. 10秒ほどおいてからもう一度下見して「作る 0」を確かめる
.venv/bin/python scripts/create_notes.py
```

- 流す前に、Obsidian で編集中のテーマノート・著者ノートがあれば閉じる（直近10秒に更新されたノートがあると待つ）。
- アプリ（notes-web）は動いたままでよい。動いていれば、ハブ（`テーマ一覧.md`・`著者一覧.md`）と既存ノートの
  「関連するテーマ」が十数秒で新しいノートを含む形に更新される。止めていれば次の起動で入る。
- 「待ち」や「作れなかった」で終了コード 1 になったら、10秒ほどおいてもう一度流す（作ったものは「既にノートあり」になる）。
- 要らないノートは消してよい。ただしこのスクリプトをもう一度流すと作り直す（どれを消したかは覚えない）。
  レポートのある著者のノートは、これまでどおりアプリが作り直す（0002 §5.5）。

### 7.3 ドキュメント

- `docs/SPEC.md` §3 の地図: `scripts/` の行に `create_notes.py` を足す。
- `docs/SPEC.md` §4「テーマノート」に1行: 「いまあるタグのノートを一括で作るには `scripts/create_notes.py`（既定は下見、
  `--apply` で作る。既存のファイルは変えない）→ 0003」。「著者ノート」にも同様に「レポートの無い著者も含めて一括で作れる」。
- `theme_store.py` の docstring の「ノートを作るのはユーザー」に「一括で作るときは `scripts/create_notes.py`（ユーザーが流す）」を添える。
- 実装後、この設計書の状態を「実装済み（日付）」に、README の一覧も更新する。

## 8. テスト方針

テスト名は日本語（CLAUDE.md §7）。ノートとレポートは実ファイル、DB はテストごとに `tmp_path` に作る SQLite ファイル。
`conftest.py` が `NOTES_REPORTS_DIR` を `tmp_path/reports` に向ける（フォルダは作らないので、テストで `mkdir` する）。
モジュール変数の警告済み集合（`theme_store._warned_broken` / `_warned_write_failed`、`author_store._seen_doubts` /
`_warned_doubts`）は `test_author_store.py` と同じ autouse fixture で毎回空にする。

### 8.1 `backend/tests/test_create_notes.py`（新規）

小道具:
- スクリプトは `importlib.util.spec_from_file_location("create_notes", SCRIPT)` で読み込む（`test_strip_report_frontmatter.py` と同じ）。
- `make_db(path, books)`: `create_engine("sqlite://", creator=lambda: sqlite3.connect(str(path)))` に `configure_sqlite`（本番と同じ WAL）、
  `Base.metadata.create_all`、`Session` で `Book` と `Tag` を入れて commit、レポートが要る本は `report_store.save(book, "本文")`、
  最後に `engine.dispose()`。URL 文字列を使わない（特殊文字のパスのテストでも同じ小道具を使うため）。
- `run(*args)`: `create_notes.main(["--db", str(db_path), *args])` を呼び、終了コードを返す（出力は `capsys`）。
- `backdate(directory)`: 作ったノートの mtime を60秒前に戻す（`os.utime`。2回目を流すテスト用）。

DB:
- `test_DBが無ければ空のDBを作らずに終了コード1になる`
- `test_SQLiteでないファイルを渡すと終了コード1になる`
- `test_空白や井桁や疑問符を含むパスのDBも読めて途中までの名前のファイルを作らない`
- `test_applyしてもDBファイルの中身と更新時刻は変わらない`
- `test_読み取り専用で開いたDBには書き込めない`（`open_readonly` で INSERT すると `OperationalError`）
- `test_ノートの置き場所が無ければ何も作らずに終了コード1になる`

下見:
- `test_下見は何も書かず作るファイルと作らない理由を表示する`（`themes/`・`authors/` ができない。stdout に `+ 地政学.md`、stderr に理由）
- `test_下見で表示したファイルとapplyで作るファイルが同じ`

テーマノート:
- `test_本に付いているタグごとにテーマノートを作る`
- `test_どの本にも付いていないタグのノートは作らない`
- `test_ファイル名とタグが一致するノートにはtagsを書かない`
- `test_ファイル名に使えない文字や見えない文字を含むタグはtagsにタグ名を書く`（parametrize: `日本史/近代`・`C#`・`地政​学`）
- `test_全角や半角カナのタグはNFKCをかけずタグのままのファイル名にする`
- `test_作ったテーマノートはアプリが読むとそのタグの本を集める`（`theme_store.scan_notes` と `books_for` で確かめる）
- `test_既存のテーマノートがファイル名かtagsで集めているタグは作らない`
- `test_集められないタグやファイル名にできないタグは作らずに理由を出す`（parametrize: `#メモ`・` 歴史`・`テーマ一覧`・`...`）
- `test_同じファイル名になる2つのタグはタグと同じ名前のほうを作り他方は理由を出す`（`C` と `C#`）
- `test_同じ名前の既存ノートが別のタグを集めているときは作らずtagsに足すよう案内する`
- `test_テーマノートには最初から本の一覧と関連するテーマが入っている`
- `test_編集中や壊れたテーマノートがあればテーマノートを作らず終了コード1になり著者ノートは作る`
  （parametrize: 空のファイル・閉じていない frontmatter・デコードできない・mtime が今）

著者ノート:
- `test_レポートの無い著者や積読の本の著者のノートも作る`
- `test_共著者と訳者もそれぞれノートを作る`
- `test_aliasesで集められている著者のノートは作らない`
- `test_ファイル名にすると名前が変わる著者はaliasesに元の名前を入れる`
- `test_作った著者ノートはアプリが読むとその著者を集める`（`author_store.scan_notes` のキーに全著者のキーがある）
- `test_作れない著者は作らずに理由を出す`（parametrize: 文字の無い名前・`著者一覧`・見分けのつかない `山田*太郎` と `山田太郎`）
- `test_編集中の著者ノートがあれば著者ノートを作らず終了コード1になりテーマノートは作る`
- `test_著者ノートの関連するテーマに同じ回に作ったテーマノートが出る`

既存のファイル・並行・冪等:
- `test_既存のノートとハブは1バイトも変えず更新時刻も変えない`（古い一覧の入った既存ノート・両方のハブを置いて `--apply`）
- `test_ハブが無くてもハブは作らない`
- `test_計画のあとに同じ名前のファイルができていたら上書きせず終了コード1になる`
  （`theme_store.plan_new_notes` を包む monkeypatch で、計画の直後にそのファイルを書く。中身が残ることを見る）
- `test_2回目は何も作らず終了コード0になる`（`--apply` → `backdate` → もう一度。stdout に `作る 0`）
- `test_作った直後にもう一度流すと直近に更新されたノートがあるので待って終了コード1になる`

### 8.2 `backend/tests/test_theme_store.py`（追加）

- `TestNoteStem`: `test_ファイル名に使えない文字を落とす`・`test_見えない書式文字を落とす`・`test_NFKCをかけない`・
  `test_使える文字が無ければ空になる`（`...`・`#^[]`・結合文字だけ）・`test_絵文字だけのタグはファイル名にできる`・
  `test_UTF8で200バイトまでに文字の途中で切らずに収める`
- `TestNewNoteText`: `test_ファイル名とタグが同じならtagsを書かない`・`test_ファイル名とタグが違えばtagsにタグ名だけを書く`
- `TestPlanNewNotes`: `test_計画は何も書かない`・`test_既に集められているタグはalreadyに入る`・
  `test_壊れたsymlinkと同じ名前のタグは作らない`
- `TestUnsettledReason`: `test_編集途中や壊れたノートがあれば理由を返す`（parametrize: 空・空白だけ・閉じていない frontmatter・
  YAML の誤り・デコードできない・mtime が今・mtime が少し先）・`test_ハブと隠しファイルは見ない`・
  `test_落ち着いたノートだけなら理由は無い`（正しい frontmatter・frontmatter なし）・`test_フォルダが無ければ理由は無い`
- `TestCreateFile`: `test_無ければ作る`・`test_既にあれば上書きしない`

### 8.3 `backend/tests/test_author_store.py`（追加）

- `TestPlanNewNotes`: `test_既定ではレポートの無い著者を計画に入れない`・`test_レポートの無い著者も含めると全員を計画に入れる`・
  `test_計画は何も書かない`・`test_既に集められている著者はalreadyに入る`・
  `test_作らない著者には理由を付ける`（parametrize: 文字の無い名前・ハブと同名・既存ノートと同名で集めていない・
  壊れた symlink と同名・見分けのつかない名前）
- 既存の `TestCreate*`・`TestCreateWaitsForSettledNotes`・`TestScanNotes` は**変更なしで通ること**
  （`_create_notes` の書き換えと `front_matter_doubt` の移動の確認）。

全体: `cd backend && ../.venv/bin/pytest -q` が通ること（作業前 723 passed, 1 skipped。減らない）。フロントエンドは変えないので vitest・lint は対象外。

## 追記（2026-10-12、実装とレビューを反映）

採用後の追記は誤記の訂正だけにする（`docs/design/README.md`）。下の内容は決定を変えず、実装で見つかった誤記を正す。

- **§5.4 `note_stem` の手順 3・4（誤記の訂正）**: 「空白を詰めて strip → 先頭・末尾の `.` を落とす」の順だと、`. .a` が `.a`（隠しファイル）になり、「隠しファイルにしない」に反する。実装は空白と `.` を `strip(" .")` で一度に落とす。ほかの入力では結果は同じ。著者側 `author_store.note_stem`（0002）にも同じ修正を入れた。
- **待ちの時間は 10 秒ではなく 20 秒（誤記の訂正）**: 作った直後にもう一度流すと、ThemeWatcher が作成から最大 5 秒後に既存ノートの「関連するテーマ」を書き直す。書き直されたノートはその後 10 秒「直近に更新された」になるため、10 秒では待ちが残りうる（実装時の実行で確認）。§7.2 の手順 3 と「待ち」の段落、§5.10 の「作った直後にもう一度流す」「直前に既存ノートの一覧を書き直した」の行の「10秒」は、**20秒**と読む。
- **§7.2 の下見のコマンド（誤記の訂正）**: 理由は標準エラーに出る。`| less` だけでは理由が見えないので、下見は `.venv/bin/python scripts/create_notes.py 2>&1 | less` とする。
- **§5.8 の待ちの文言（誤記の訂正）**: 実装では `WAIT_HINT` を使う。「Obsidian で編集中なら閉じ、20秒ほどおいてもう一度流す。変わらなければ、そのノートの frontmatter が空か壊れている。直す（空なら `---` の間に書くか、frontmatter ごと消す）」。空の frontmatter（`---` と `---` だけ）のノートは「frontmatter を解釈できない」として、直すまで待つ。

## 追記（2026-10-12、レビュー後の修正。決定は変えず §5 の詳細を補う）

レビュー（reviewer・adversary）で再現した穴を、作らない理由を増やす形で塞いだ。どれも「作らずに理由を出す」側に
倒すだけで、決定（既存のファイルを変えない・DB に書かない・作ったノートが自分のタグ・著者を集める）は同じ。

- **§5.4 手順2（名前の重なり）**: ファイル名を NFC でそろえて比べ、既にあるか先に作るノートと同じ名前になるなら
  作らない（NFC と NFD だけが違う2つのタグから、見た目が同じノートを2つ作らないため）。
- **§5.4 手順3（自己検証）**: 書こうとする全文を「次の回に読み戻した形」（CR を LF にした文字列）で確かめる。
  マーカーの組がちょうど1つ見えない／読み戻すと内容が変わる（タグに CR が入る）／UTF-8 で書けない
  （UTF-8 でない名前のノート・レポートが一覧に入る）のどれかなら作らない。最後の判定の部品として
  `theme_store.can_encode(text)` と理由の文言 `UNENCODABLE_REASON` を足し、著者側 `author_store.plan_new_notes`
  も同じ確認をする。UTF-8 にできないことで作らないのは、名前を直せば作れる恒久的な理由なので終了コードは 0。
- **§5.8 スクリプト**: DB の列の値が不正（enum に無い値・不正な日付で `LookupError` / `ValueError`）でも
  トレースバックにせず「DB を読めません」で終了コード 1。`  + ` / `  ! ` の行は制御文字を `\r` `\x1b` の形で出す。
  ノートのフォルダを作れないときは全件「作れなかった」に数えて終了コード 1。`--apply` はセクションごとに
  `作った N / 作れなかった N / 既にノートあり N / 作らない N` を出す。`--db` は `~` を展開する。
- **見送ったもの**（§9 に加える）: `report_store.write_atomic` は tmp の名前（`<名前>.md.tmp`）に symlink が
  あるとリンク先に書く／tmp への書き込みが `UnicodeEncodeError` で落ちると tmp が残る（どちらも既存の共有部分。
  レポートの保存の書き方も変わるので別項目）。テーマノートのマーカー内のコメント行は集めるタグをそのまま書くので、
  ユーザーが手で CR 入りのタグを書いたノートは書き直しが止まらない（既存の振る舞い）。

## 9. 未決事項

- 消したノートを覚えて作り直さない手段（除外の一覧など）。いまはこのスクリプトをもう一度流すと作り直す（0002 §9 の「作らせたくない著者」と同じ課題）。
- 今後増えたタグ・著者を自動で作るか（ウォッチャーの方針の変更）。今回は変えない。必要なら新しい番号で設計する。
- ~~`CLAUDE.md` §3 の地図（`scripts/` の行）に `create_notes.py` を足すか。~~（2026-10-12 解決: CLAUDE.md は
  ユーザーの指示で「アプリの現時点での構成」をまとめたものなので、地図に足した）
- `report_store.write_atomic` の tmp の symlink と、tmp が残る場合（上の追記の「見送ったもの」）。
- サブフォルダ（`themes/*/`・`authors/*/`）のノートを見ない点は 0002 §9 のまま。
