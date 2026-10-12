# 0001 DB と Markdown の境界（同じデータを2か所に保存しない）

## 1. 状態・日付

- 状態: 実装済み（2026-10-12）
- 日付: 2026-10-12
- 関連: SPEC §4「Book」「テーマノート」、§7「レポート本文は DB ではなくファイルに置く」、
  [0002 著者ノート](0002-author-notes.md)（この設計の代わりの導線）、
  `Storage/_vault/document-storage-policy.md`（リポジトリ外。内容は未確認）

## 2. 背景と目的

2026-10-11 に読書レポートの本文を DB の `books.report_md` 列から `reports/<book_id 4桁>-<タイトル>.md`
へ移した（ファイルが正）。そのとき、ファイル単体でも書誌が読めるよう、レポートの frontmatter に DB の
書誌（title / author / isbn / genre / status / rating / started_on / finished_on / tags）を**複製**した。

複製には次の問題がある。

- **同じ値が2か所にある**。正は DB だが、Obsidian の Properties で書き換えられてしまう。書き換えても
  次の保存で黙って DB の値に戻るので、どちらが正なのか紛らわしい。
- **本を更新するたびにレポートのファイルを書き直す**（`routers/books.py` の `_report_meta_snapshot` →
  `report_store.refresh_meta()`）。本文が変わっていないのに mtime と週次コミットの差分が動く。
- **2か所の対応を手で保つコード**が要る（`_REPORT_META_FIELDS` と `build_markdown` の項目を揃え続ける）。

Obsidian 対応を進めるにあたって、「DB に保存するもの」と「Markdown にするもの」の境界をはっきりさせ、
同じデータを2か所に保存しない形にする。

## 3. 決定

1. **データの持ち主は1か所**。
   - **DB（`reading.db`）が持つ**: 書誌・状態・進捗・評価・日付・タグ・引用/メモ・読了記録・表紙・提案・
     キーワード・設定。短い構造化データで、集計と外部キーが効くため。
   - **Markdown（`reports/`）が持つ**: レポート本文、テーマノートの本文（マーカーの外）、著者ノートの本文
     （マーカーの外、0002）。長文で、人が書く文章のため。
2. **レポートの frontmatter でアプリが持つキーは `type`・`book_id`・`updated` の3つだけ**。
   - `type: reading-report` … ファイルの種類
   - `book_id` … DB との結合キー（正の鍵。従来どおり）
   - `updated` … アプリから本文を最後に保存した時刻。ファイル自身のメタで、DB には無い
   - title / author / isbn / genre / status / rating / started_on / finished_on / tags は**もう書かない**。
3. **本の更新でレポートのファイルを書き直さない**。`report_store.refresh_meta()` と
   `routers/books.py` の `_REPORT_META_FIELDS` / `_report_meta_snapshot` を削除する。
4. **上の3つ以外のキーはユーザーのもの**。保存してもそのまま残す。旧版が書いた title〜tags も、
   保存時には消さない（ユーザーが Obsidian で意図的に足した `tags` などを黙って消さないため）。
5. **既存ファイルに残っている旧い複製キーは、一回限りの移行スクリプト
   `scripts/strip_report_frontmatter.py` で取り除く**（既定は dry-run で差分を表示、`--apply` で書き換え）。
6. **例外は「ビュー」だけ**。テーマノート・著者ノート・ハブのマーカー
   （`<!-- notes:books:start -->`〜`<!-- notes:books:end -->`）の中の一覧は、DB から毎回作り直す派生物。
   アプリは読み戻さず、正にしない。Obsidian でリンク・バックリンク・グラフを成立させるには実体の
   テキストが要るので、これだけはファイルに書く。**レポートのファイルにはビューを差し込まない**
   （レポートからテーマ・著者へは、Obsidian のバックリンクでたどる）。
7. **DB の `books.report_md`（凍結コピー）は今回消さない**。残っている重複として記録し、消す手順だけ書く
   （§7.4）。消すのはユーザーの確認後。

## 4. 全体像

```
            reading.db（SQLite）                         reports/（Markdown。git 管理外。Obsidian vault から symlink）
  ┌───────────────────────────────────┐         ┌────────────────────────────────────────────────────┐
  │ books   書誌・状態・進捗・評価・日付   │         │ 0013-言語の起源.md                                  │
  │ tags / book_tags                    │ book_id │   frontmatter: type / book_id / updated            │
  │ notes（引用・メモ） readings          │◀───────▶│              ＋ユーザーのキー（aliases など）         │
  │ book_covers  suggestions  topics    │ 結合キー │   本文 ………………………………………… 正（人が書く）          │
  │ dismissed_books  settings           │         │                                                    │
  │ （books.report_md 凍結コピー §7.4）  │         │ themes/*.md, authors/*.md                          │
  └───────────────┬───────────────────┘         │   マーカーの外 …………………………… 正（人が書く）          │
                  │                             │   マーカーの内 …………………………… ビュー（派生物）        │
                  │                             └────────────────────────────────────────────────────┘
                  │                                      ▲                     ▲
                  │   読み書き（API）                     │ 本文だけ読み書き      │ マーカーの内だけ書く
                  ▼                                      │                     │（読み戻さない）
        ┌──────────────────┐      report_store ─────────┘                     │
        │ FastAPI（app/）   │                                                   │
        │                  │      ThemeWatcher（5秒ごと）── DB を読む ──────────┘
        └──────────────────┘        theme_store.rebuild / author_store.rebuild（0002）
```

### ファイル構成（`reports/` の下）

```
reports/                         NOTES_REPORTS_DIR（既定 <repo>/reports。git 管理外、履歴は ~/.doc-history）
├── .write.lock                  書き込みロック（report_store / theme_store / author_store 共通）
├── .trash/                      消したレポート（隠しフォルダ。索引にも Obsidian にも出ない）
├── 0013-言語の起源.md            読書レポート。本文が正。frontmatter は type / book_id / updated（＋ユーザーのキー）
├── 0021-お経の話.md
├── themes/
│   ├── テーマ一覧.md             ハブ（アプリが作る）。マーカーの内はビュー
│   └── 仏教.md                   テーマノート（ユーザーが作る）。マーカーの外が正、内はビュー
└── authors/                     0002 で追加
    ├── 著者一覧.md               ハブ（アプリが作る）。マーカーの内はビュー
    └── 渡辺照宏.md               著者ノート（レポートのある著者はアプリが作る）。マーカーの外が正、内はビュー
```

## 5. 詳細

### 5.1 データの持ち主

| データ | 持ち主 | 置き場所 | 理由 |
|---|---|---|---|
| 書誌（title, author, publisher, isbn, category, genre, cover_url） | DB | `books` | 一覧・検索・集計・API が使う短い値 |
| 状態・進捗（status, page, total） | DB | `books` | 進捗ルール（`_apply_progress_rules`）が DB の値で動く |
| 評価（rating, recommend） | DB | `books` | CHECK 制約・集計 |
| 日付（started_on, finished_on, created_at, updated_at） | DB | `books` | 並び替え・振り返り |
| タグ | DB | `tags` / `book_tags` | 多対多。テーマノートも DB のタグで集める |
| 引用・メモ | DB | `notes` | 本への外部キー（cascade） |
| 読了記録 | DB | `readings` | 再読の回数・日付 |
| 表紙 | DB | `book_covers`（BLOB） | バックアップを `reading.db` 1つで済ませる方針（SPEC §4） |
| 提案・興味なし・キーワード | DB | `suggestions` / `dismissed_books` / `topics` / `topic_suggestions` | 外部キー・並び順 |
| 設定 | DB | `settings` | 1行の構造化データ |
| **レポート本文** | **Markdown** | `reports/<id>-<タイトル>.md` の本文 | 長文・人が書く・履歴を追いたい |
| **テーマノートの本文** | **Markdown** | `reports/themes/*.md` のマーカーの外 | 人が書く |
| **著者ノートの本文** | **Markdown** | `reports/authors/*.md` のマーカーの外（0002） | 人が書く |
| ハブの本文 | Markdown | `themes/テーマ一覧.md`・`authors/著者一覧.md` のマーカーの外 | 人が書いてよい |
| ファイル自身のメタ（`type`, `book_id`, `updated`） | Markdown | レポートの frontmatter | ファイルの種類・DB との結合キー・保存時刻。DB には無い |
| ユーザーが足した frontmatter のキー（aliases, cssclasses, 旧版の title〜tags など） | Markdown | レポートの frontmatter | アプリは解釈しない。保存しても残す |
| 一覧（ビュー） | **DB から作る派生物** | 各ノート・ハブのマーカーの内 | 正ではない。アプリは読み戻さない |

### 5.2 レポートの frontmatter の新しい形

アプリが新しく作るレポート:

```markdown
---
type: reading-report
book_id: 17
updated: 2026-10-12T21:41:04+09:00
---

## 第1章
……
```

- キーの順序は `type` → `book_id` → `updated` → ユーザーのキー（既存ファイルでの順序のまま）。
- `updated` は**アプリから本文を保存して、中身が変わったときだけ**更新する（従来どおり。本文も
  frontmatter も変わらない保存では書き直さない）。Obsidian での編集では動かない。ファイルの最終更新は
  mtime を見る。
- 書誌はファイルには無い。題名はファイル名（最初に保存したときのタイトル。改名しない規約は従来どおり）で
  分かるが、著者・評価・状態はアプリか DB を見る。

旧版が書いたファイル（移行前）を保存したときの形。旧キーは「ユーザーのキー」として残る:

```markdown
---
type: reading-report
book_id: 17
updated: 2026-10-12T21:50:00+09:00
title: '失敗の本質 : 日本軍の組織論的研究'
author: 戸部良一
isbn: '9784122018334'
genre: academic
status: finished
rating: 5
started_on: 2026-09-01
finished_on: 2026-09-20
tags:
- 組織論
- 戦史
aliases:
- 失敗の本質
---
```

移行スクリプトのあと（`updated` は動かさない）:

```markdown
---
type: reading-report
book_id: 17
updated: 2026-10-11T21:41:04+09:00
aliases:
- 失敗の本質
---
```

### 5.3 ビュー（マーカーの内）の扱い

- ビューを書くファイル: `themes/*.md`、`themes/テーマ一覧.md`、`authors/*.md`、`authors/著者一覧.md`。
  レポートのファイルには書かない。
- ビューは DB（とレポートの有無）から毎回作り直す。手で編集しても次の回で上書きされる。
- アプリはビューを読み戻さない。ビューの内容を正として使う処理を作らない。
- マーカーの外はユーザーのもの。アプリは触らない（ハブと著者ノートは、無いときに最初の雛形だけ作る）。
- マーカーの検出・書き換えの規則（コードフェンス内を無視する、壊れたら警告する等）は 0002 §5.9 で直す。

### 5.4 移行スクリプト `scripts/strip_report_frontmatter.py`

既存のレポートから旧い複製キーを取り除く1回限りのスクリプト。`scripts/migrate_report_md_to_files.py`
の作法（`sys.path` に `backend` を足して `report_store` を import、既定は下見、`--apply` で実行、
集計を最後に出す）に合わせる。

**対象**

- `report_store.reports_dir()` の**直下**の `*.md` で、名前が `.` で始まらない通常ファイル
  （`themes/`・`authors/`・`.trash/` は見ない）
- frontmatter が読めて（`report_store.split_front_matter` が空でない辞書を返す）、
  `type == "reading-report"` のもの。frontmatter が無い・壊れている・`type` が違うファイルは「対象外」と
  して数えるだけで触らない。ファイル自体が読めない（`OSError` / `UnicodeDecodeError`）ものは
  「読めない」に数える

**取り除くキー**（定数 `LEGACY_KEYS`。スクリプトの中だけに置く）

```python
LEGACY_KEYS = ("title", "author", "isbn", "genre", "status", "rating",
               "started_on", "finished_on", "tags")
```

**1ファイルの処理**（関数 `plan(text: str) -> Optional[tuple[str, list[str]]]`。取り除くものが無ければ None）

1. `meta, body = report_store.split_front_matter(text)`。`body` は frontmatter の閉じ `---` の行の
   直後からの**元の文字列そのまま**。
2. `removed = [k for k in LEGACY_KEYS if k in meta]`。空なら None。
3. `new_meta = {k: v for k, v in meta.items() if k not in LEGACY_KEYS}`（元の順序のまま。
   `updated` は触らない）。
4. `new_text = report_store.front_matter_text(new_meta) + body`（`front_matter_text` は §6.1 で足す）。
   **本文は1バイトも変えない**。BOM があった場合は書き出しで落ちる（アプリの保存と同じ）。
5. 検証: `split_front_matter(new_text)` が `(new_meta, body)` と等しいこと。等しくなければ
   そのファイルは書かずに `!` を付けて報告し、次のファイルへ進む（最後に終了コード 1）。

**実行**

- 既定（下見）: 書き換えるファイルごとに `- <ファイル名>: title, author, … を取り除く` と、frontmatter
  部分の unified diff（`difflib.unified_diff`、前後1行）を表示する。ファイルには触らない。
- `--apply`: ファイルごとに `with report_store.write_lock(reports_dir())` の中で**読み直してから**
  `plan()` → `report_store.write_atomic(path, new_text)`。書いたあと
  `os.utime(path, ns=(元の atime_ns, 元の mtime_ns))` で **mtime を元に戻す**。
  - 理由: 同じ `book_id` のファイルが複数あるとき（Obsidian の複製）、索引は mtime が最新のものを
    「主」にする。移行で古い複製の mtime が新しくなると、主が入れ替わって別の本文が出てしまう。
- 集計: `書き換え N / 旧キーなし M / 対象外 K / 読めない・検証失敗 E`。下見では
  「下見のみ。--apply を付けると N 件を書き換える」と出す。
- 終了コード: 正常 0、`reports/` が無い 1、検証失敗・読めないファイルがあった 1。
- 冪等。2回目の `--apply` は何も書かない。
- `main(argv: Optional[list[str]] = None) -> int` にして、テストから呼べるようにする。

**実行の順序**（重要）

1. 新しいコード（§6）をデプロイしてアプリを再起動する。**先にスクリプトを流すと、旧コードの
   `refresh_meta()` が次の本の更新でキーを書き戻す。**
2. Obsidian でレポートを編集中なら閉じる（開いたままのエディタが古い frontmatter で保存し直すことがある。
   その場合はもう一度流せばよい）。
3. `.venv/bin/python scripts/strip_report_frontmatter.py` で下見 → 差分を確認。
4. `.venv/bin/python scripts/strip_report_frontmatter.py --apply`。
5. もう一度下見して「書き換え 0」を確認。

**追記（2026-10-12、実装後のレビューを反映）**: 上の「1ファイルの処理」と「実行」は次のように変えた。
本文の方針（旧キーだけを取り除き、本文は変えない）は同じ。

- **方式**: frontmatter を YAML として読み直して書き出す方式をやめ、**旧キーの行だけを文字列として削除する**。
  YAML として書き直すと、残すキーのコメントが消え、`yes` → `true`、`0123` → `83`、`1:30` → `90` の
  ように値まで変わるため（全ファイルに一括で効く移行では避けたい）。削除するのはトップレベルの旧キーの行と
  その続きの行（先頭が空白の行・`- ` で始まる行・あとに続きが来る空行）だけ。残すキーの行・コメント・
  `---` の行・BOM・改行コード・本文は1バイトも変えない（手順4の「BOM は書き出しで落ちる」は誤りになった。
  BOM は残る）。スクリプトは `front_matter_text` を使わない。
- **検証**: 削除後の全文を `split_front_matter` で読み、`(元の meta から旧キーを除いた辞書, 元の本文)` と
  等しくなければ書かない（旧キーが複数行の引用符付き文字列・フロー形式・途中にコメントのあるリストなど、
  行の削除では安全に消せない書き方のとき）。
- **対象**: symlink の `*.md` と、先頭が `---` なのに frontmatter が読めないファイル（YAML の誤りや
  `2026-02-30` のような不正な日付）は書き換えず、名前を stderr に出して「対象外」に数える。
  あわせて `report_store.split_front_matter` が不正な日付（`ValueError`）でも落ちないようにした
  （それまでは索引が例外を投げ、本の一覧 API が 500 になっていた）。
- **`--apply`**: mtime に加えて mode も元に戻す。書く直前に stat し直し、`(mtime_ns, size)` が変わって
  いれば書かずに「途中で変更された」と報告する（ロックを取らない Obsidian の保存を失わないため）。
  書き込みの `OSError` は「書けない」として報告し、`*.md.tmp` を消して次のファイルへ進む。
- **集計と終了コード**: `書き換え N / 旧キーなし M / 対象外 K（symlink S・frontmatter が読めない B）/
  読めない・検証失敗・書けない・途中で変更 E`。終了コードは `reports/` が無いか E ≥ 1 のとき 1。

## 6. 実装手順（coder 向け）

0002 より先に入れる（0002 は §6.1 の `front_matter_text` を使う）。

### 6.1 `backend/app/report_store.py`

- **モジュールの docstring**: 25〜29 行目の段落（「frontmatter の書誌項目（title / author / status /
  rating / tags …）は、DB の値を…」）を次の趣旨に差し替える。
  - frontmatter でアプリが書くのは `type` / `book_id` / `updated` の3つだけ。書誌は DB にだけあり、
    ファイルには複製しない（`docs/design/0001-storage-boundary.md`）。本を更新してもレポートのファイルは
    書き直さない。
  - それ以外のキー（aliases など。旧版が書いた title〜tags も含む）はユーザーのもので、保存しても残す。
- **削除**: `_tag_names()`、`_enum_value()`、`refresh_meta()`。使われなくなった import（`date` など）も消す。
- **追加**: `front_matter_text(meta: dict) -> str`
  - いまの `build_markdown` の `yaml.dump(...)` の部分を切り出したもの。`_ReportDumper`、
    `allow_unicode=True, sort_keys=False, default_flow_style=False, width=float("inf")` のまま。
  - 戻り値は `f"---\n{front}\n---\n"`（閉じ `---` の後ろに改行1つ）。
- **変更**: `build_markdown(book, body, extra=None) -> str`
  - `meta = {"type": REPORT_TYPE, "book_id": book.id, "updated": <いまの時刻（秒まで、TZ 付き）>}`。
  - `extra` のうち `meta` に無いキーを元の順序で後ろに足す（いまと同じ）。
  - 戻り値は `front_matter_text(meta) + f"\n{body.strip()}\n"`（いまの出力と同じ並び）。
  - docstring を「アプリのキーは3つだけ。それ以外は既存ファイルのまま残す」に直す。
- **変更**: `_save_locked(book, body)` — `body is None` の分岐（`refresh_meta` 専用だった）を消し、
  `body: str` を受ける形にする。`save()` は空なら `delete()`、そうでなければ `_save_locked()` を呼ぶ（いまと同じ）。
- `save()` の docstring の「複製項目はアプリの値で上書きし」を「`type` / `book_id` / `updated` だけを
  アプリの値にし」に直す。
- `_same_except_updated()`、索引、ファイル名、ゴミ箱は変更しない。

### 6.2 `backend/app/routers/books.py`

- **削除**: `_REPORT_META_FIELDS`、`_report_meta_snapshot()`、`update_book` の
  `meta_before = _report_meta_snapshot(book)` と `elif _report_meta_snapshot(book) != meta_before:` の分岐
  （コメントごと）。
- `update_book` の「本文の保存は DB のコミット後。frontmatter に載せる書誌が確定してから書く。」を
  「本文の保存は DB のコミット後（DB の更新が失敗したらファイルも書かない。新しいファイル名に使う
  タイトルもここで確定している）。」に直す。

### 6.3 `scripts/strip_report_frontmatter.py`（新規）

§5.4 のとおり。docstring に目的・使い方・実行の順序（新コードのデプロイ後に流す）を書く。

### 6.4 `docs/SPEC.md`

- §3 ディレクトリの図に `docs/design/  設計書（なぜそう決めたか。README.md に一覧）` を足す。
- §4 Book の箇条書き「**frontmatter の書誌項目は DB の複製**（…）。値が変わったら…アプリが書き直し、
  Obsidian で書き換えた値は DB の値に戻る。aliases など自分で足したキーは残る。」を次に差し替える:
  「**frontmatter でアプリが書くのは `type: reading-report`・`book_id`・`updated`（アプリから本文を
  保存した時刻）の3つだけ**。書誌・状態・評価・タグは DB にだけあり、ファイルには書かない。本の書誌や
  状態を変えてもレポートのファイルは書き直さない。それ以外のキー（aliases や、2026-10-12 より前の版が
  書いた title〜tags）はユーザーのものとして保存しても残す（旧キーは `scripts/strip_report_frontmatter.py`
  で一度だけ取り除く）→ `docs/design/0001-storage-boundary.md`」。続く「本文も frontmatter も変わらない
  保存では書き直さない」はそのまま残す。
- 同じ節の「新しいタイトルは frontmatter の `title` に入る」を「新しいタイトルは DB にだけ入る」に直す。
- §7 設計判断メモに1項目足す: 「**レポートの frontmatter に書誌を複製しない**（2026-10-12）: 同じ値が
  2か所にあると、どちらが正か紛らわしく、本の更新のたびにファイルが動く。持ち主を1か所にし、Obsidian
  からの導線はテーマノートと著者ノートで作る → `docs/design/0001-storage-boundary.md`」。
- 実装が済んだら、この設計書と `docs/design/README.md` の一覧の状態を「実装済み」にする。

### 6.5 変更しないもの

- `scripts/migrate_report_md_to_files.py` … `report_store.save()` を呼ぶだけなので、そのまま動く
  （新しく書くファイルは新しい形になる）。
- `theme_store.py` … レポートの frontmatter を読んでいない（索引の `report_paths()` だけ使う）。
- frontend … frontmatter を読んでいない。

## 7. 影響範囲・移行

### 7.1 影響範囲

| ファイル | 変更 |
|---|---|
| `backend/app/report_store.py` | frontmatter を3キーに。`refresh_meta` ほか削除、`front_matter_text` 追加 |
| `backend/app/routers/books.py` | 本の更新でレポートを書き直す処理を削除 |
| `scripts/strip_report_frontmatter.py` | 新規（一回限りの移行） |
| `backend/tests/test_report_store.py` / `test_books.py` | §8 |
| `backend/tests/test_strip_report_frontmatter.py` | 新規 |
| `docs/SPEC.md` | §6.4 |

- 本番コードで frontmatter の書誌キーを読み戻している箇所は無い（読むのは `book_id` だけ。
  `report_store.py` の索引）。frontend・`.claude/skills`・`scripts` も読んでいない（調査済み）。
- リポジトリの外（`Storage/_vault` 側のスクリプト、Obsidian の Dataview クエリ）が title / status などを
  読んでいないかは**未確認**。ユーザーに確認する。

### 7.2 デプロイと移行の順序

1. §6 のコードを入れ、テストを通してアプリを再起動する。
2. §5.4「実行の順序」に従って移行スクリプトを流す。
3. 移行までの間に保存されたレポートは、旧キーを「ユーザーのキー」として残したまま保存される
   （値は古いまま）。移行スクリプトで消えるので問題ない。

### 7.3 戻し方

移行前の frontmatter は `~/.doc-history`（`reports/` の履歴）に残っている。コードを戻せば、次の保存で
旧形式の frontmatter が書かれる。

### 7.4 残っている重複

| 重複 | 状態 | 扱い |
|---|---|---|
| `books.report_md`（DB の凍結コピー） | 2026-10-11 の移行時点の本文。以後ファイルが編集されるほど古くなる | **今回は消さない**。下の手順で、ユーザーの確認後に消す |
| 移行前ファイルの旧い複製キー | 移行スクリプトで消える | §5.4 |
| ビュー（マーカーの内の一覧） | 意図した派生物 | 残す。正にしない（§5.3） |

`~/.doc-history` と `backup/` は過去の時点の写しで、「いまの値」を2か所に持つ重複ではないので数えない。

**`books.report_md` 列を消す手順**（破壊的。ユーザーの確認を取ってから。今回は実装しない）

1. ユーザーに「凍結コピーを消してよいか」を確認する。
2. DB を止めずに写しを取る: `sqlite3 backend/reading.db ".backup backup/reading-YYYYmmdd.db"`。
3. `scripts/migrate_report_md_to_files.py --verify` を流し、**「ファイルなし」が0件**であることを確かめる
   （「内容が違う」は移行後に Obsidian やアプリで直した結果なので構わない。「ファイルなし」は
   レポートを消した本か取りこぼしなので、1件ずつ確認する）。
4. アプリを止めて `ALTER TABLE books DROP COLUMN report_md;`（SQLite 3.35 以上。この環境の Python が
   使う SQLite は 3.45.1。実 DB での実行は未検証）。
5. `scripts/migrate_report_md_to_files.py` を削除する（列が無いと動かない）。`models.py` の凍結コピーの
   コメントと SPEC の `~~report_md~~` の行を「削除済み（日付）」に直す。

### 7.5 トレードオフ（正直に）

失うもの:

- **Obsidian の Properties / Dataview でレポートの書誌を引けなくなる**。`TABLE rating, status FROM "reports"`
  のようなクエリや、Properties での並び替え・絞り込みはできない。
- **タグペイン・タグ検索（`tag:#地政学`）にレポートが出なくなる**。frontmatter の `tags` が無くなるため。
- レポートのファイル単体では、著者・評価・状態・読了日が分からない（題名はファイル名で分かる）。
- `grep "status: finished" reports/` のようなファイル横断の検索ができない。

代わりの導線:

- **テーマノート**（タグ → 本の一覧 → レポート）と**著者ノート**（著者 → 本の一覧 → レポート、0002）、
  それぞれのハブ。一覧の行には著者・状態・読了日・評価が出る。
- Obsidian のバックリンクで、レポートから「どのテーマノート・著者ノートに載っているか」が見える。
- 書誌の確認・集計はアプリの画面、または `sqlite3` で DB を直接見る。

得るもの:

- 正が1か所になり、Obsidian で直した値が黙って戻される混乱が無くなる。
- 本の更新（評価・状態・タグ・進捗）でレポートのファイルが動かない。mtime と週次コミットの差分が
  本文の変更だけになる。
- 2か所の対応を保つコード（`refresh_meta`、`_report_meta_snapshot`）が消える。

## 8. テスト方針

### 8.1 `backend/tests/test_report_store.py`

| テスト | 扱い | 新しい内容 |
|---|---|---|
| `TestSaveAndRead.test_front_matter_copies_the_bibliographic_fields`（:44） | 置き換え | `test_front_matter_has_only_type_book_id_and_updated`: 書誌・タグを全部埋めた本を保存し、`list(meta) == ["type", "book_id", "updated"]`、`meta["type"] == "reading-report"`、`meta["book_id"] == 17`、ファイルの文字列に著者名・ISBN・タグ名が含まれないこと |
| `TestSaveAndRead.test_title_with_colon_does_not_break_the_front_matter`（:72） | 削除 | title を書かなくなったので意味が無い |
| `TestSaveAndRead.test_rewrites_the_file_when_only_the_bibliography_changed`（:115） | 置き換え | `test_does_not_rewrite_the_file_when_only_the_bibliography_changed`: 保存 → `book.rating = 4`・`book.status` を変える → 同じ本文で保存 → 文字列と `st_mtime_ns` が変わらない |
| `TestFilename.test_keeps_the_file_name_when_the_title_changes`（:127） | 修正 | 末尾の `meta["title"] == "新しいタイトル"` を `"title" not in meta` に。コメントの「新しいタイトルは frontmatter に入る」を「新しいタイトルは DB にだけある」に |
| `TestRefreshMeta`（:184〜202 の2件） | 削除 | `refresh_meta` を消すため |
| `TestRefreshMetaDoesNotLoseConcurrentSave.test_keeps_a_body_written_while_refresh_waits_for_the_lock`（:349） | 置き換え | `test_save_keeps_a_user_key_added_while_it_waits_for_the_lock`: ロックを握った状態で `save(book, "新しい本文")` をスレッドで走らせ、待っている間にファイルへ `aliases` を足す → ロックを放す → `aliases` が残り、本文が「新しい本文」。クラス名は `TestLocking` に変える（:373 の delete のテストはそのまま同じクラスに残す） |
| `TestUserFrontMatterKeys.test_refresh_meta_keeps_user_keys_and_puts_them_after_the_app_keys`（:434） | 置き換え | `test_save_puts_user_keys_after_the_app_keys`: `type:` の前に `zzz: 1` を差し込む → 別の本文で保存 → `list(meta)[:3] == ["type", "book_id", "updated"]`、最後が `zzz` |
| `TestUserFrontMatterKeys.test_app_values_overwrite_what_was_edited_in_obsidian`（:451） | 置き換え | `test_save_keeps_legacy_bibliographic_keys_as_they_are`: `_write_report` で `type: reading-report`、`title: 勝手に直した`、`status: reading`、`tags: [a]` を持つファイルを置く → 別の本文で保存 → 3つのキーが同じ値のまま残り、本文が新しい |

ほかのテスト（索引・複製・ゴミ箱・BOM・空の本文・`TestUserFrontMatterKeys.test_save_keeps_keys_the_user_added`）は
変更なしで通ること。

### 8.2 `backend/tests/test_books.py`

| テスト | 扱い | 新しい内容 |
|---|---|---|
| `test_本の書誌を直すとレポートのfrontmatterも追従する`（:221） | 置き換え | `test_本の書誌や状態を変えてもレポートのファイルは書き直さない`: `@pytest.mark.parametrize` で payload を `{"status": "finished", "rating": 5}`、`{"tags": ["設計", "入門"]}`、`{"page": 300}`（`total=300` で作った本。自動で読了になる）、`{"title": "新しい題"}` の4通り。レポートを書いたあとの文字列と `st_mtime_ns` を覚え、PATCH 後も同じであること。PATCH が効いたこと（GET で値が変わっている）も確かめる |
| `test_ページ数だけ送って自動で読了になるとレポートのfrontmatterも追従する`（:246） | 削除 | 上の parametrize の `{"page": 300}` に吸収 |
| `test_タグを変えるとレポートのfrontmatterのタグも追従する`（:260） | 削除 | 上の parametrize の `{"tags": …}` に吸収 |
| `test_ページ進捗の更新ではレポートのファイルを書き直さない`（:234） | そのまま | 変更なしで通る |
| （新規）`test_レポートのfrontmatterはtype・book_id・updatedだけ` | 追加 | API で書誌・タグ付きの本を作り、レポートを PATCH → ファイルの frontmatter のキーが `type`・`book_id`・`updated` だけ |

### 8.3 `backend/tests/test_strip_report_frontmatter.py`（新規）

スクリプトは `importlib.util.spec_from_file_location` で `<repo>/scripts/strip_report_frontmatter.py` から
読み込む。`reports/` は conftest の `NOTES_REPORTS_DIR`（`tmp_path/reports`）。

- `test_removes_only_the_legacy_keys_and_keeps_the_rest_in_order` — 旧形式（§5.2 の例）＋ `aliases` →
  `plan()` 後のキーが `type, book_id, updated, aliases` の順
- `test_keeps_the_body_byte_for_byte` — 本文に `---` の行、末尾の空白、空行の連続、`<!-- notes:books:start -->`
  を含めても、`new_text` の frontmatter より後ろが元と完全に同じ
- `test_does_not_change_updated` — `updated` の値が元のまま
- `test_returns_none_when_there_is_nothing_to_remove` — 新形式のファイルでは `plan()` が None
- `test_dry_run_does_not_write_and_shows_the_diff` — `main([])` のあとファイルが変わらず、出力（`capsys`）に
  `-title:` を含む差分が出る
- `test_apply_rewrites_and_keeps_the_mtime` — `main(["--apply"])` で旧キーが消え、`st_mtime_ns` が元のまま
- `test_apply_does_not_change_which_duplicate_is_primary` — 同じ `book_id` の2ファイル（mtime が違う）に
  `--apply` → `report_store.read(id)` が移行前と同じ本文を返す
- `test_skips_files_that_are_not_reading_reports` — `themes/` と `authors/` のノート、`.trash/` の中、
  `.` で始まるファイル、`type` の無い手書きメモ、frontmatter が壊れたファイルは変わらない
- `test_is_idempotent` — `--apply` を2回。2回目は書き換え0件で、ファイルも mtime も変わらない

## 9. 未決事項

- `books.report_md` 列を消すか（§7.4。ユーザーの確認待ち）。
- Dataview などで書誌を引きたくなった場合の受け皿。案: ビューとして書誌の一覧ファイル（例:
  `reports/本の一覧.md` のマーカー内に表）を作る。今回は作らない。
- `Storage/_vault/document-storage-policy.md`（リポジトリ外）への反映。「レポートの frontmatter は
  type / book_id / updated のみ」をユーザーに追記してもらう。
- リポジトリ外のスクリプト・Dataview クエリがレポートの書誌キーを読んでいないか（未確認）。
