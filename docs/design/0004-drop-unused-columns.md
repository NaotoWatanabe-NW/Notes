# 0004 DB の不要な列を消す（`books.report_md`）

## 1. 状態・日付

- 状態: 採用（未実装）
- 日付: 2026-10-12
- 関連: [0001 DB と Markdown の境界](0001-storage-boundary.md) §7.4（列を消す手順）・§9（未決事項）、
  SPEC §4「Book」「マイグレーションについて」、§7「Alembic をまだ入れない」

## 2. 背景と目的

- 2026-10-11 に読書レポートの本文を `books.report_md` 列から `reports/<book_id 4桁>-<タイトル>.md` へ移した。
  列はモデルから外し、移行前の本文の**凍結コピー**として DB に残した（0001 §3-7・§7.4）。
- 凍結コピーは、ファイルが編集されるほど古くなる「同じデータの2つ目」で、0001 の原則（持ち主は1か所）に
  合わない。0001 §9 で「消すか」をユーザーの確認待ちにしていたところ、ユーザーから「DB の不要列は削除」と
  指示があったので消す。
- 実データ（`backend/reading.db`・`reports/`）はユーザーの PC にあり、開発環境には無い。だから
  **ユーザーが自分の PC で一度だけ流すスクリプト**にし、「消してよいか」の確認・写し・検査をスクリプトの中で行う。
- 目的は2つ。列を消してもレポートの本文を1つも失わないこと。アプリを止め忘れて流しても DB を壊さないこと。

## 3. 決定

1. **一回限りのスクリプト `scripts/drop_unused_columns.py` を足す**。既定は下見、`--apply` で実行。
   `main(argv: Optional[list[str]] = None) -> int`。作法は `scripts/strip_report_frontmatter.py` に合わせる
   （`sys.path` に `backend` を足して `app` を import、集計を最後に出す、冪等）。
2. **消すのは「DB にあってモデル（`Base.metadata`）に無い列」のうち、許可リストにあるものだけ**。
   許可リストは **`books.report_md` の1つだけ**。許可リストに無いモデル外の列は消さず、名前・型・値のある行数を
   出す（消すかはユーザーが判断）。`books.report_html` は許可リストに入れない（§5.2）。
3. **消す前の確認**。どれかに引っかかったら DB を変えずに終了コード 1。
   - SQLite が 3.35 以上（`ALTER TABLE … DROP COLUMN` の要件）。
   - `books.report_md` の本文が空でない本すべてに、本文が空でないレポートのファイルがある（`report_store` の索引）。
     無い本は id と書名を出す。意図して消したレポートなら `--allow-missing` で通せる（本文は写しに残る）。
   - （`--apply` のみ）ほかに DB を開いているプロセスが無い。`PRAGMA locking_mode=EXCLUSIVE` にしてから
     `BEGIN EXCLUSIVE` を 2 秒待ち、取れなければ「`systemctl --user stop notes-web` してから」と出す。
     取った排他ロックは終わるまで持ち続ける。**`BEGIN EXCLUSIVE` だけでは稼働中のアプリを検出できない**（§5.5）。
   - DROP COLUMN が通る（列を参照する索引・ビュー・表の CHECK 制約があると SQLite が拒む）。下見ではメモリ上の
     写しで実際に試す。
4. **写し**: `--apply` では DROP の前に、sqlite3 の backup API で `<repo>/backup/reading-YYYYmmdd-HHMMSS.db` を
   作り、写しの `PRAGMA integrity_check` が `ok` で、消す列の値のある行数が元と同じでなければ止める。
   置き場所は `--backup-dir` で変えられる（テストが本番の `backup/` を汚さないため）。
5. **実行**: `BEGIN IMMEDIATE` → 消す列をすべて DROP COLUMN → **同じトランザクションの中で**
   `integrity_check` が `ok`、`foreign_key_check` が DROP 前と同じ → COMMIT。どれかが駄目なら ROLLBACK。
6. **COMMIT のあと毎回 VACUUM する**（フラグにしない。§5.8）。
7. **冪等**: 消すものが無ければ「消すものはありません」で終了コード 0。写しも VACUUM もしない。
8. **Alembic は入れない**（§6）。
9. **片付け**: `scripts/migrate_report_md_to_files.py` を削除する（列が無いと動かない。`--verify` の判定は §5.4 へ
   移した）。コメント・docstring・SPEC・CLAUDE.md・0001 は §7.2 の文言に直す。アプリの動き（API・画面）は変えない。

## 4. 全体像

```
ユーザーの PC
  systemctl --user stop notes-web
            │
            ▼
  .venv/bin/python scripts/drop_unused_columns.py [--apply] [--allow-missing]
                                                  [--db backend/reading.db] [--backup-dir backup/]
            │ import（sys.path に <repo>/backend）
            ├── app.database.Base ＋ app.models …… モデルの列（engine / SessionLocal は使わない）
            └── app.report_store ………………………… reports_dir() / book_ids_with_report() / read()

  下見（既定）                                   --apply
  ────────────────────────────                  ─────────────────────────────────────────────────
  ① SQLite ≥ 3.35                                ① SQLite ≥ 3.35
  ② mode=ro で開く（ロックを取らない）             ② mode=rw・locking_mode=EXCLUSIVE・
                                                    BEGIN EXCLUSIVE → COMMIT（ロックは持ち続ける）
                                                    取れなければ「notes-web を止めて」で終了
  ③ モデル外の列 → 消す／消さない                  ③ 同じ（消すものが無ければ終了コード 0）
  ④ report_md の本文 ↔ reports/ のファイル         ④ 同じ（ファイルなし → 止める）
  ⑤ メモリ上の写しで DROP を試して ROLLBACK        ⑤ 写し backup/reading-….db → 写しを検査
                                                 ⑥ BEGIN IMMEDIATE → DROP COLUMN
                                                    → integrity_check / foreign_key_check → COMMIT
                                                    （駄目なら ROLLBACK）
                                                 ⑦ VACUUM
                                                 ⑧ 閉じる（ロックを放す。WAL は DB に書き戻して消える）
            │
            ▼
  systemctl --user start notes-web
    lifespan: create_all ……………… 無いテーブルだけ作る（books は触らない）
              add_missing_columns … モデルにある列だけ足す → report_md は戻らない
```

## 5. 詳細

### 5.1 コマンドラインと定数

```
.venv/bin/python scripts/drop_unused_columns.py [--apply] [--allow-missing] [--db PATH] [--backup-dir DIR]
```

| 引数 | 既定 | 意味 |
|---|---|---|
| `--apply` | なし | 実際に消す。無ければ下見 |
| `--allow-missing` | なし | 「ファイルなし」の本があっても止めない（§5.4） |
| `--db` | `<repo>/backend/reading.db` | 対象の DB。ファイルでなければ作らずに終了コード 1 |
| `--backup-dir` | `<repo>/backup` | 写しの置き場所。無ければ作る（`.gitignore` 済み） |

- 既定のパスは `__file__` から作る。作業ディレクトリに依存しない。
- レポートの場所は `report_store.reports_dir()`（`NOTES_REPORTS_DIR`、既定 `<repo>/reports`）。スクリプトは
  `backend/.env` を読まないので、アプリが `.env` で `NOTES_REPORTS_DIR` を変えているなら同じ値を付けて流す。
  冒頭に、使った DB・SQLite の版・レポートの場所を出す。

```python
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "backend" / "reading.db"
DEFAULT_BACKUP_DIR = REPO_ROOT / "backup"
MIN_SQLITE = (3, 35, 0)        # ALTER TABLE … DROP COLUMN が入った版
LOCK_TIMEOUT_SECONDS = 2.0     # 排他ロックを待つ秒数（テストは monkeypatch で短くする）

# 消してよい列 → 理由（出力に出す）。ここに無い「モデルに無い列」は名前を出すだけで消さない
DROP_ALLOWLIST = {
    ("books", "report_md"): "読書レポート本文の凍結コピー（2026-10-11 にファイルへ移管。0001 §7.4）",
}
```

### 5.2 対象の決め方

- **モデルの列**: `from app.database import Base` と `import app.models`（テーブルを `Base.metadata` に登録させる）。
  `{table.name: {column.name for column in table.columns} for table in Base.metadata.sorted_tables}`。
  - `app.database` の `engine` / `SessionLocal` は**使わない**。`sqlite:///./reading.db` は作業ディレクトリ基準なので、
    別の場所に空の DB を作ってしまう。`create_engine` は接続するまで何もしないので、import するだけなら害はない。
- **DB の列**: モデルにあるテーブルのうち DB にもあるものについて `PRAGMA table_info("<table>")`。
  DB にしか無いテーブル・モデルにしか無いテーブルは見ない（今回の対象は列。§9）。
- 列名は大文字小文字を区別せずに比べる（SQLite の列名は区別しない）。
- モデルに無い列ごとに `ExtraColumn(table, column, type, filled, drop)` を作る。
  `filled` は `SELECT COUNT("<column>") FROM "<table>"`（NULL でない行数）。識別子は `"` で囲み、中の `"` は二重にする。
  `drop` は `(table, column)` が `DROP_ALLOWLIST` にあるか。
- 2026-10-11 より後に作った DB には `report_md` がそもそも無い。その場合「モデルに無い列はありません」で終了コード 0。

**`books.report_html` を許可リストに入れない理由**

- HTML から Markdown へ移った（SPEC §6 Step E）のは git の履歴より前で、最初のコミット（22bec5a）のモデルは
  既に `report_md`。当時は DB を作り直していた時期（作り直さなくなったのは 2026-10-03）なので、ユーザーの DB に
  この列が残っているかは**分からない（未確認）**。
- 残っていれば中身は HTML の本文で、`migrate_report_md_to_files.py` は `report_md` しか移していない。
  **どこにも移されていない唯一の本文かもしれない**うえ、ファイルと突き合わせる方法も無い。黙って消してよい列ではない。
- 残っていた場合は「消さない」として値のある行数つきで出る。消すと決めたら、この設計書に追記して許可リストに足す。

### 5.3 SQLite の版

- `sqlite3.sqlite_version_info < MIN_SQLITE` なら
  `SQLite {sqlite3.sqlite_version} では列を消せません（3.35 以上が必要）。DB は変えていません。` と出して終了コード 1。
  下見でも同じ（DROP の試しが通らないため）。DB は開かない。
- 判定は呼ぶたびに `sqlite3.sqlite_version_info` を読む（import 時に定数へ写さない。テストが monkeypatch で古い版にする）。
- 参考: 開発環境の Python 3.13 の SQLite は 3.45.1。ユーザーの PC の版は**未確認**。Linux の Python はシステムの
  libsqlite3 を使うので、OS が古いと 3.35 に届かない（例: Ubuntu 20.04 は 3.31.1、Debian 11 は 3.34.1、Ubuntu 22.04 は 3.37.2）。
  手順の前に `.venv/bin/python -c "import sqlite3; print(sqlite3.sqlite_version)"` で確かめる（§7.3）。

### 5.4 レポートのファイルの確認（`books.report_md` を消すときだけ）

`migrate_report_md_to_files.py --verify` の考え方をここへ移す。

1. `SELECT id, title, report_md FROM books WHERE report_md IS NOT NULL ORDER BY id`。Python で
   `report_md.strip()` が空の行を除く（`report_store.read()` と同じ `strip()` の判定。SQL の `TRIM` は空白しか落とさない）。
2. `have = report_store.book_ids_with_report()`（本文が空でない主ファイルのある book_id）。1回の走査で済む。
3. 本ごとに:
   - `id not in have` → **ファイルなし**（本文が空のファイルしか無い場合も含む）
   - それ以外は `report_store.read(id) == report_md.strip()` で「同じ」「違う」を数える。「違う」は移管後に
     Obsidian やアプリで直した結果なので止めない（件数だけ出す）
4. ファイルなしが1件でもあり `--allow-missing` が無ければ、全件を
   `  ! {id:4} {title[:40]}（ファイルなし。DB の本文 {len} 文字）` で出し、続けて次の案内を出して終了コード 1
   （`--apply` でも写しを取る前に止まる）。
   ```
   レポートのファイルが無い本があるので止めました。DB は変えていません。
     - 意図して消したレポート（reports/.trash/ にある）なら、--allow-missing を付けて流す。
       DB の本文は写し（backup/）に残る。
     - 取りこぼしなら、sqlite3 backend/reading.db "SELECT report_md FROM books WHERE id = <id>" で本文を出し、
       アプリでレポートとして保存してから、もう一度流す。
   ```
5. `--allow-missing` のときは同じ行を出したうえで続ける（集計に「ファイルなし N 冊（--allow-missing で通す）」）。

- `reports_dir()` が無いときは `book_ids_with_report()` が空を返す。本文のある本が1冊でもあれば全部「ファイルなし」に
  なって止まるので、レポートの場所の取り違え（`NOTES_REPORTS_DIR` の付け忘れ）に気づける。本文のある本が無ければ止まらない。
- 同じ `book_id` のファイルが複数あれば、索引の主（mtime が最新）と比べる（`read()` と同じ）。

### 5.5 アプリが止まっていることの確認（`--apply`）

```python
con = sqlite3.connect(db.resolve().as_uri() + "?mode=rw", uri=True,
                      timeout=LOCK_TIMEOUT_SECONDS, isolation_level=None)
con.execute("PRAGMA locking_mode=EXCLUSIVE")   # 最初の読み書きより前に
con.execute("BEGIN EXCLUSIVE")                  # ← 取れなければ OperationalError
con.execute("COMMIT")                           # ロックは閉じるまで持ち続ける（locking_mode=EXCLUSIVE）
```

- `mode=rw`: ファイルが無ければ作らずにエラーになる（`--db` の `is_file()` 判定に重ねた安全策）。
  `as_uri()` で URI にするのは、空白や `?`・`#` を含むパスでも壊れないため。
- `isolation_level=None`: Python の自動 BEGIN を止め、トランザクションの境目を自分で書く。
- **なぜ `BEGIN EXCLUSIVE` だけでは足りないか**: WAL では EXCLUSIVE と IMMEDIATE は同じ意味で、
  いま書き込み中の接続としか衝突しない。アプリの接続プールにいるアイドルの接続があっても取れてしまう。
- **なぜ `locking_mode=EXCLUSIVE` だと検出できるか**: WAL では、開いている接続はそれぞれ DB ファイルの
  共有ロックを持ち続ける。`locking_mode=EXCLUSIVE` の接続が書き込みトランザクションを始めると、SQLite は
  DB ファイルの排他ロックを取りに行くので、ほかに開いている接続が1つでもあれば `database is locked`（SQLITE_BUSY）になる。
- **実験で確認した**（SQLite 3.45.1）:
  - 別プロセスで、SQLAlchemy の QueuePool（アプリと同じ）で1回読んで接続をアイドルにした状態で、
    `BEGIN EXCLUSIVE` だけは取れ、`locking_mode=EXCLUSIVE` ＋ `BEGIN EXCLUSIVE` は待ち時間 0.5 秒で `database is locked`。
  - 同じプロセスの別の接続が開いていても同じく取れない（テストで再現できる）。
  - 取ったあとは、COMMIT しても別プロセスからの読み出しが `database is locked` になる（DROP までの間に割り込まれない）。
- アプリは起動時（lifespan）に接続を開き、`ThemeWatcher` が5秒ごとに DB を読むので、動いている間はプールに接続が
  残っている。`./run.sh` や `sqlite3` で開いている場合も同じく検出される。
- 取れなかったら接続を閉じ、次を出して終了コード 1:
  ```
  DB を開いているプロセスがあるので止めました（SQLite: database is locked）。DB は変えていません。
  常駐のアプリを止めてから、もう一度流してください:
      systemctl --user stop notes-web
  （./run.sh で動かしているならそれも止める。sqlite3 などで開いていれば閉じる）
  ```
  `BEGIN EXCLUSIVE` で出た `sqlite3.OperationalError` はすべてこの扱いにし、SQLite のメッセージを括弧内にそのまま出す。
- 待ち時間 2 秒: アプリが動いていれば接続は開きっぱなしなので、長く待っても取れない。一瞬の読み出しを
  やり過ごせれば足りる。
- 下見はロックを取らない（§5.9）。止まっているかは `--apply` だけで確かめる。
- 本番の DB は `configure_sqlite` で常に WAL。WAL でない DB ではアイドルの接続を見分けられないが、
  排他ロックを持っている間はほかの接続は読み書きできないので、壊れはしない。

### 5.6 写し（`--apply`）

ロックを取り、§5.2・§5.4 の確認が済んでから、DROP の前に取る。

- 名前: `<backup-dir>/reading-{datetime.now():%Y%m%d-%H%M%S}.db`。既にあれば `-2`, `-3` … を足す（上書きしない）。
  `backup-dir` は `mkdir(parents=True, exist_ok=True)`。
- 手順: `dst = sqlite3.connect(path)` → `con.backup(dst)` → `dst.execute("PRAGMA journal_mode=DELETE")` → `dst.close()`。
  - `journal_mode=DELETE` にするのは、元の DB の「WAL」の印が写しのヘッダにも写るため。そのままだと写しを開く
    たびに `-wal` / `-shm` ができる。DELETE にすれば写しは1ファイルで完結する（実験で確認）。
- **`con.backup()` は、`con` が書き込みトランザクションの中にいるときに呼んではいけない**。SQLite は SQLITE_BUSY を
  返し、Python の `Connection.backup` はそれを待ち続けて戻らない（実験で固まった）。だから §5.5 で
  `BEGIN EXCLUSIVE` のあとすぐ COMMIT し、ロックだけを持った状態で写しを取る。
- 検査 `verify_backup(path: Path, expected: dict[tuple[str, str], int]) -> list[str]`（問題の一覧。空なら合格）:
  - `mode=ro` で開き、`PRAGMA integrity_check` が `[("ok",)]`
  - 消す列ごとに、写しの `SELECT COUNT("<column>") FROM "<table>"` が元（§5.2 の `filled`）と同じ
    （消す中身が写しに全部入っていること）
  - 問題があれば `写しの検査に通りません: {path}` と問題を出して終了コード 1。DB は変えていない。
    写しのファイルは消さない（調べるため）。

### 5.7 実行（`--apply`）

1. `fk_before = con.execute("PRAGMA foreign_key_check").fetchall()`。空でなければ
   「前からある外部キーの不整合 N 件」を警告として出す（今回の変更とは関係ないので止めない）。
2. `BEGIN IMMEDIATE`（ロックは既に持っているので待たない）。
3. 消す列ごとに `ALTER TABLE "<table>" DROP COLUMN "<column>"`。SQLite の DDL はトランザクションに入るので、
   途中で失敗しても ROLLBACK で全部戻る。
   - `sqlite3.OperationalError` なら ROLLBACK し、次の形で出して終了コード 1:
     ```
     books.report_md を消せません: error in index ix_x after drop column: no such column: report_md
       この列を参照しているもの: index ix_x
     DB は変えていません（写しは backup/reading-….db）。参照しているものを消すかは、ユーザーが判断してください。
     ```
   - 主になるのは SQLite のメッセージ（「error in index / view / table … after drop column」の形で原因を名指しする）。
     「参照しているもの」は手がかりで、`sqlite_schema` の `type IN ('index', 'view', 'trigger')` のうち `sql` に列名が
     単語として現れる（`\b<column>\b`、大文字小文字を区別しない）ものを `type name` で並べる。無ければこの行は出さない。
   - 実験（3.45.1）: 列に張った索引・列を使うビュー・列を使う表の CHECK 制約は失敗する。`UPDATE OF report_md` だけの
     トリガーは失敗しない。
   - ユーザーの DB の `books` は create_all で作られ、モデルの履歴上 `report_md` に索引・制約を付けたことは無い
     （`mapped_column(Text)` のみ）ので、通る見込み。
4. 同じトランザクションの中で検査する。
   - `PRAGMA integrity_check` が `[("ok",)]`
   - `PRAGMA foreign_key_check` の結果が `fk_before` と同じ（集合で比べる）
   - どちらかが違えば ROLLBACK し、問題を出して終了コード 1。
   - COMMIT の前に検査するのは、駄目なときに DB を元のままにできるため（実験で、DROP 後のトランザクションの中で
     どちらも流せることを確認）。
5. `COMMIT`。
6. `VACUUM`（§5.8）。
7. 消した列が `PRAGMA table_info` に無いことを確かめ、集計を出す。
8. `con.close()`。排他ロックを放す。最後の接続なので WAL は DB に書き戻されて消える。

### 5.8 VACUUM

- COMMIT のあと、消した列があったときだけ毎回流す。フラグにしない。
- 理由:
  - DROP COLUMN は全行を書き直すが、消した値の分のページは空きページ（freelist）になるだけで、ファイルは
    小さくならない。実験では 200 行×5000 文字の列を消して空きページが 200、VACUUM で 0 になった。
  - 空きページには消した本文のバイトが残る。「同じデータを2か所に置かない」の後始末として、生きている DB からは
    物理的にも消す（本文は写しに残る）。
  - アプリを止めて排他ロックを持っている今が、全体を書き直す VACUUM を流すのに一番安全なとき。一回限りの
    スクリプトなので、フラグで分岐を増やす意味がない。
- 注意: VACUUM は一時的に DB と同じくらいの空き容量を使う（表紙の BLOB が大半。実サイズは未確認）。
- 失敗したら（ディスク不足など）、列はもう消えていて DB は壊れていない（VACUUM は全部か無しか）。次を出して終了コード 1:
  `VACUUM に失敗しました（列は消えています。DB は壊れていません）: <メッセージ>。あとでアプリを止めて sqlite3 backend/reading.db "VACUUM" を流してください。`
- 出力: `DB の大きさ: {before:,} → {after:,} バイト`（after は close のあとに測る）。

### 5.9 下見（既定）

- `sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)`。ロックは取らない。書かない。アプリが動いていても流せる。
- §5.2・§5.4 は `--apply` と同じ。
- DROP の試し: `mem = sqlite3.connect(":memory:", isolation_level=None)`、`ro.backup(mem)`、`mem` で §5.7 の 1〜4 を流して
  ROLLBACK。失敗の出し方は §5.7 と同じで、末尾は「DB は変えていません」。元の DB には触らない。
- 終了コード: 版・ファイルなし（`--allow-missing` なし）・DROP の試しのどれかが駄目なら 1、それ以外は 0。
  下見が 0 なら、アプリを止めれば `--apply` は通る見込み。
- 最後に `下見のみ。--apply を付けると books.report_md を消す。` と `--apply の前にアプリを止める: systemctl --user stop notes-web` を出す。
- 読み取り専用の接続は、DB の横に `-wal` / `-shm` を作って残すことがある（中身は変えない。次にアプリが開いて閉じたときに片付く）。

### 5.10 出力の例

下見:

```
DB: /home/naoto/PythonProject/Notes/backend/reading.db（SQLite 3.45.1）
レポート: /home/naoto/PythonProject/Notes/reports

モデルに無い列:
  - books.report_md（TEXT、値あり 42 行）… 消す: 読書レポート本文の凍結コピー（2026-10-11 にファイルへ移管。0001 §7.4）
  - books.report_html（TEXT、値あり 3 行）… 消さない: 許可リストに無い。消すかはユーザーが判断

books.report_md の本文がある本: 40 冊
  ファイルあり 40 冊（本文が同じ 31 冊・違う 9 冊。違うのは移管後の編集なので構わない）
  ファイルなし 0 冊

DROP COLUMN の試し（メモリ上の写し）: ok

下見のみ。--apply を付けると books.report_md を消す。
--apply の前にアプリを止める: systemctl --user stop notes-web
```

`--apply` の後半:

```
写し: /home/naoto/PythonProject/Notes/backup/reading-20261012-223015.db（integrity_check ok）
消した列: books.report_md
integrity_check ok / foreign_key_check 不整合なし
DB の大きさ: 18,350,080 → 17,920,000 バイト（VACUUM）
アプリを起動する: systemctl --user start notes-web
```

2回目（`report_html` が残っている場合）:

```
モデルに無い列:
  - books.report_html（TEXT、値あり 3 行）… 消さない: 許可リストに無い。消すかはユーザーが判断
消すものはありません。
```

モデルに無い列が1つも無ければ `モデルに無い列はありません。消すものはありません。`

### 5.11 終了コード

| 状況 | 下見 | `--apply` |
|---|---|---|
| 消した／消すものなし／下見で問題なし | 0 | 0 |
| DB が無い（ファイルでない） | 1 | 1 |
| SQLite が 3.35 より古い | 1 | 1 |
| ファイルなしの本がある（`--allow-missing` なし） | 1 | 1（写しも取らない） |
| ほかに DB を開いているプロセスがある | （見ない） | 1 |
| 写しの検査に通らない | — | 1 |
| DROP が拒まれた／DROP 後の検査に通らない | 1（試し） | 1（ROLLBACK 済み） |
| VACUUM の失敗 | — | 1（列は消えている） |

許可リストに無いモデル外の列があることは、それだけでは 1 にしない（情報として出す）。

### 5.12 関数（目安）

テストが `main()` と結果（DB・ファイル・出力）で確かめるので、内部の分け方は coder に任せる。目安:

```python
class ExtraColumn(NamedTuple):
    table: str
    column: str
    type: str
    filled: int      # NULL でない行数
    drop: bool       # 許可リストにあるか

def model_columns() -> dict[str, set[str]]
def extra_columns(con: sqlite3.Connection) -> list[ExtraColumn]
def check_reports(con: sqlite3.Connection) -> tuple[int, int, int, list[tuple[int, str, int]]]
    # (本文のある本の数, 同じ, 違う, ファイルなし [(id, title, 文字数)])
def drop_columns(con: sqlite3.Connection, targets: list[ExtraColumn], *, commit: bool) -> list[str]
    # BEGIN IMMEDIATE〜§5.7 の 4 まで。問題があれば ROLLBACK して問題の一覧を返す。
    # 問題が無ければ commit=True で COMMIT、False で ROLLBACK（下見の試し）して [] を返す
def make_backup(con: sqlite3.Connection, backup_dir: Path) -> Path
def verify_backup(path: Path, expected: dict[tuple[str, str], int]) -> list[str]
def main(argv: Optional[list[str]] = None) -> int
```

## 6. 選ばなかった案と理由

- **モデルに無い列を全部消す**: 書くことは少ないが、実 DB を見ずに流すスクリプトで「見つけたものを全部消す」は、
  知らない列（`report_html` のような、どこにも移されていないかもしれない本文）まで黙って消す。列の削除は写しから
  戻すしかない操作なので、消すものは名前で決め打ちし、それ以外は見せるだけにする。許可リストでも「モデルに無い列」の
  洗い出しはするので、見落としは出力で分かる。
- **Alembic を入れる**（SPEC「マイグレーションについて」の当初の方針）: 今回は1列を一度消すだけで、ユーザーの指示がある。
  Alembic は依存・`env.py`・版のディレクトリ・既存 DB への版の刻印（`stamp`）が要り、学習中のユーザーに覚えることが
  増える。しかも SQLite の列削除は Alembic でも batch モード（表の作り直し）になる。SQLite 3.35 以上のネイティブな
  DROP COLUMN を一回限りのスクリプトで流すほうが小さい。型変更や削除が繰り返し要るようになったら入れる（先にユーザーに相談）。
- **表を作り直す（新しい表を作って写し、古い表を消して改名する SQLite の12手順）**: 3.35 より前の唯一の方法だが、
  索引・外部キー・CHECK を手で作り直す必要があり、間違える余地が大きい。3.35 以上を要件にして DROP COLUMN を使う。
- **ロックの確認を `BEGIN EXCLUSIVE` だけにする**: WAL ではアイドルの接続を検出できない（§5.5 の実験）。
- **`systemctl --user is-active notes-web` で確かめる**: `./run.sh` や `sqlite3` で開いている場合を見逃し、systemd にも
  依存する。DB のロックなら開いている人すべてに効く。
- **写しを `sqlite3` CLI の `.backup` で先に取る**（0001 §7.4 の手順2）: CLI が入っているか分からず、写しと DROP の
  間にアプリが書き込む隙が残る。スクリプトの中で、ロックを持ったまま写しを取る。
- **VACUUM をフラグにする・しない**: §5.8。
- **`books.report_html` も許可リストに入れる**: §5.2。

## 7. 影響範囲・移行

### 7.1 変更するファイル

| ファイル | 変更 |
|---|---|
| `scripts/drop_unused_columns.py` | 新規（§5） |
| `backend/tests/test_drop_unused_columns.py` | 新規（§8） |
| `scripts/migrate_report_md_to_files.py` | **削除**。`report_md` 列が無いと動かない。`--verify` の判定（「ファイルなし」「内容が違う」）は §5.4 へ移した。書き出し（`--apply`）は移さない（ファイルへの移行は 2026-10-11 に済んでいる） |
| `backend/app/models.py` | コメントだけ（§7.2） |
| `backend/app/report_store.py` | モジュールの docstring だけ |
| `backend/app/database.py` | `add_missing_columns` の docstring だけ |
| `docs/SPEC.md` | §3・§4・§7 |
| `CLAUDE.md` | §3・§4 |
| `docs/design/0001-storage-boundary.md` | §7.4・§9 に追記 |
| `docs/design/README.md` | 一覧に 0004 を足す |

- アプリのコード（routers・schemas・frontend）は変えない。API の `report_md`（`BookDetail` / `BookUpdate`）は
  DB の列ではなく、`report_store` が読み書きするファイルの本文の名前なのでそのまま。
- アプリのコードで `report_md` 列を SQL で読んでいる箇所は無い（`routers/books.py` は Python の属性に
  `report_store.read()` の結果を付けるだけ）。`.claude/skills/next-book-suggestions/scripts/nbs.py` も DB を読むが
  `dismissed_books` だけ。`SELECT *` は無い（調査済み）。
- 列が有っても無くてもアプリは同じに動く（モデルに無いため）。だから**コードのデプロイとスクリプトの実行の順序は
  問わない**（0001 の strip のような「先に流すと書き戻される」問題は無い）。

### 7.2 文言の直し方

**`backend/app/models.py`**（129〜131 行目の3行を差し替える。前後の行はそのまま）

いま:
```
    # 旧 report_md 列は移行前の凍結コピーとして DB に残っているが、ここでマップ
    # しないことで「アプリからは読み書きしない」を構造的に保証している
    # （SQLite の列削除は add_missing_columns() の範囲外なので列自体は消さない）。
```
直したあと（前の2行「読書レポートの本文…」「app/report_store.py が…」と、後ろの「理由と境界: …」は残す）:
```
    # 移管前に本文を入れていた report_md 列は、凍結コピーとして残したあと
    # scripts/drop_unused_columns.py で DB から消す（docs/design/0004-drop-unused-columns.md）。
    # 消す前の DB に列が残っていても、ここでマップしないのでアプリは読み書きしない。
```

**`backend/app/report_store.py`**（docstring 13〜15 行目）

いま: 「この境界が「一部だけファイルに移管した」の意味。`books.report_md` 列は移行後の凍結コピーとして
残っているが、**アプリはもう読み書きしない**（モデルからも外した）。」

直したあと: 「この境界が「一部だけファイルに移管した」の意味。移管前に本文を入れていた `books.report_md` 列は
モデルから外してあり（**アプリは読み書きしない**）、`scripts/drop_unused_columns.py` で DB からも消す
（`docs/design/0004-drop-unused-columns.md`）。」

**`backend/app/database.py`**（`add_missing_columns` の docstring の最後の1行）

いま: 「列の型変更・削除が要るようになったら Alembic を入れる。」

直したあと:
「モデルに無い列は足さないので、消した列が起動時に戻ることはない。
列の型変更・削除はここではしない。不要になった `books.report_md` は一回限りのスクリプトで消した
（`scripts/drop_unused_columns.py`、docs/design/0004）。型変更・削除が繰り返し要るようになったら
Alembic を入れる（先にユーザーに相談）。」

**`docs/SPEC.md`**

- §3 ディレクトリ（135 行目）:
  `├── scripts/                    一回限りの移行スクリプト（strip_report_frontmatter.py / drop_unused_columns.py）`
  その次の `reports/` の行の後ろに1行足す:
  `├── backup/                     DB の写し（git 管理外。drop_unused_columns.py も消す前にここへ取る）`
- §4 Book の表の `~~report_md~~` の行（287 行目）を次に差し替える:
  ```
  | ~~report_md~~ | （削除） | 読書レポートの本文だった列。2026-10-11 にファイル（`reports/<book_id>-<タイトル>.md`）へ移管し、凍結コピーとして残していた。モデルには無く、アプリは読み書きしない。`scripts/drop_unused_columns.py` で DB から消す（消す前の DB は `backup/reading-*.db`）→ `docs/design/0004-drop-unused-columns.md` |
  ```
- §4 Book の表の下（292〜293 行目）「…API の形（`BookDetail.report_md` / `BookUpdate.report_md`）は移管の前後で
  変えていない。」の末尾を「…変えていない（名前が残っているだけで、DB の列ではない）。」にする。
- §4「マイグレーションについて」の3つ目の箇条（464 行目）「列の型変更・削除・null を許さない列の追加が要るように
  なったら、そのときに Alembic を入れる」を次の2つに差し替える:
  ```
  - 列の削除は自動ではしない。不要になった `books.report_md`（レポート本文の凍結コピー）は、2026-10-12 に一回限りの
    スクリプト `scripts/drop_unused_columns.py`（SQLite 3.35 以上の `ALTER TABLE … DROP COLUMN`）で消した。
    `add_missing_columns` はモデルにある列しか足さないので、消した列は起動時に戻らない → `docs/design/0004-drop-unused-columns.md`
  - 列の型変更・削除・null を許さない列の追加が繰り返し要るようになったら Alembic を入れる（先にユーザーに相談）
  ```
- §7 設計判断メモの「**Alembic をまだ入れない**: 実データが無いうちは…」（1049 行目）を次に差し替える:
  ```
  - **Alembic をまだ入れない**: 列を足すのは `add_missing_columns`、一度きりの列の削除（2026-10-12、`books.report_md`）は
    一回限りのスクリプトで足りた。Alembic は依存・設定・既存 DB への版の刻印が要り、1回の変更には重い。型変更や削除が
    繰り返し要るようになったら入れる（先にユーザーに相談）→ `docs/design/0004-drop-unused-columns.md`
  ```

**`CLAUDE.md`**

- §3（45 行目）: `├── scripts/                    移行スクリプト（strip_report_frontmatter.py / drop_unused_columns.py。一回限り）`
  その前の `reports/` の行の後ろに1行足す:
  `├── backup/                     DB の写し（git 管理外。drop_unused_columns.py も消す前にここへ取る）`
- §4「旧い複製キーの移行」の箇条（124 行目）の最後の文
  「DB の `books.report_md` 列は凍結コピーで、アプリは読み書きしない（消す手順は 0001 §7.4。ユーザーの確認後）」を
  次に差し替える:
  「DB の `books.report_md` 列（移管前の本文の凍結コピー）は `scripts/drop_unused_columns.py` で消す（アプリを止めて
  一度だけ流す。既定は下見、`--apply` で消す。消す前の写しは `backup/`。0004）」
- §4 最後の箇条（125 行目）: 「`reports/`・`reading.db`・`backup/`・`backend/.env` はコミットしない（`.gitignore`。この repo は public）」
- §6「DB のスキーマは作り直さない …型の変更・削除・NOT NULL の追加が要るときは、先に Alembic の導入をユーザーに相談する」は
  **変えない**。「先にユーザーに相談する」という約束は今回も守られていて（ユーザーの指示で消す）、文言を緩めると
  次の削除で相談が抜けるため。

**`docs/design/0001-storage-boundary.md`**（README の約束どおり、決定の本文は書き換えず追記だけ）

- §7.4 の「`books.report_md` 列を消す手順」の番号付きリストの後ろに足す:
  ```
  **追記（2026-10-12）**: ユーザーの確認が取れたので列を消す。上の手順 2〜5 は
  [0004](0004-drop-unused-columns.md) の `scripts/drop_unused_columns.py` 1本に置き換えた（アプリを止めて排他ロックを
  取ってから写しを取る。「ファイルなし」の確認はスクリプトの中で行う。`migrate_report_md_to_files.py` は削除した）。
  ```
- §9 の1つ目の箇条を次にする:
  「`books.report_md` 列を消すか（§7.4。ユーザーの確認待ち）。→ **解決（2026-10-12）**: 消す。手順は
  [0004](0004-drop-unused-columns.md)。」

**`docs/design/README.md`** の一覧に1行足す:
`| [0004](0004-drop-unused-columns.md) | DB の不要な列を消す（books.report_md） | 採用（未実装） | 2026-10-12 |`
（実装とテストが入り SPEC を直したら「実装済み（日付）」にする。この設計書の §1 も同じ）

### 7.3 ユーザーの PC での手順

1. このスクリプトが入った版を取り込む（`git pull`）。アプリのコードはコメントしか変わらないので、再起動は手順5でよい。
   SQLite の版を確かめる: `.venv/bin/python -c "import sqlite3; print(sqlite3.sqlite_version)"`（3.35 以上。§5.3）。
2. アプリを止める: `systemctl --user stop notes-web`
   （`./run.sh` で動かしていれば Ctrl-C。`sqlite3` などで `reading.db` を開いていれば閉じる）
3. 下見: `.venv/bin/python scripts/drop_unused_columns.py`
   - `backend/.env` で `NOTES_REPORTS_DIR` を変えているなら、同じ値を付けて流す
     （`NOTES_REPORTS_DIR=… .venv/bin/python scripts/drop_unused_columns.py`）。出力の「レポート:」の行で場所を確かめる。
   - 「ファイルなし」が出たら止まる。§5.4 の案内に従って1件ずつ確かめる。
   - 「消さない」の列が出たら、名前と行数を控えて知らせる（今回は消さない。§9）。
4. 実行: `.venv/bin/python scripts/drop_unused_columns.py --apply`
   - 「写し:」の場所と「消した列: books.report_md」を確かめる。
   - もう一度下見して「消すものはありません」を確かめる。
5. アプリを起動: `systemctl --user start notes-web`（画面のビルドも走る）。
6. 確かめる: 本の一覧が出る、レポートのある本の詳細で本文が出る、レポートを保存できる。
   `journalctl --user -u notes-web -n 50` にエラーが無い。

起動時に列が戻らないこと: lifespan の `create_all` は無いテーブルしか作らず、`add_missing_columns` は
`Base.metadata` の列（モデルにある列）だけを見て足す。`report_md` はモデルに無いので足されない
（開発環境で、create_all → `report_md` を足す → DROP → `add_missing_columns` が `[]` を返し列が無いことを確認した）。

### 7.4 戻し方

- アプリは列の有無に関係なく同じに動くので、通常は戻す必要がない。
- 1冊の旧本文が要るとき: `sqlite3 backup/reading-YYYYmmdd-HHMMSS.db "SELECT report_md FROM books WHERE id = 13"`
- DB ごと戻すとき: アプリを止めて `cp backup/reading-YYYYmmdd-HHMMSS.db backend/reading.db`。写しは1ファイルで完結
  している（§5.6）。写しを取ったあとの変更（本・記録の追加など）は失われる。
- 写しは、消した本文の最後のコピー。消すかはユーザーが決める（§9）。

## 8. テスト方針

ファイル: `backend/tests/test_drop_unused_columns.py`（新規）。テスト名は日本語（CLAUDE.md §7）。

- スクリプトは `importlib.util.spec_from_file_location("drop_unused_columns", <repo>/scripts/drop_unused_columns.py)` で
  読み込む（`test_strip_report_frontmatter.py` と同じ作法）。
- DB は `tmp_path` の実ファイル。レポートは conftest の `NOTES_REPORTS_DIR`（`tmp_path/reports`）に実ファイルで置く。
  モックしない（ファイルと DB の I/O がこのスクリプトの本体）。差し込むのは、作れない失敗（写しの検査の失敗）と
  ロックの待ち時間、SQLite の版だけ。
- `main()` には**必ず `--db` と `--backup-dir` を渡す**（既定は本番の `backend/reading.db` と `backup/`）。

**準備（ヘルパー）**

- `make_db(tmp_path, books, extra_sql=()) -> Path`
  1. `engine = create_engine(f"sqlite:///{path}")` → `configure_sqlite(engine)`（本番と同じ WAL）→
     `Base.metadata.create_all(engine)` → **`engine.dispose()`**（しないとプールの接続が共有ロックを持ち続け、
     スクリプトが「DB を開いているプロセスがある」で止まる）。
  2. `sqlite3` で `ALTER TABLE books ADD COLUMN report_md TEXT`（2026-10-11 より前の版の DB を再現）。
     本（id, title, status, page, created_at, updated_at, report_md）、タグと `book_tags`、引用（`notes`）、
     表紙（`book_covers` の BLOB）を数行入れる。`extra_sql` を流す（余分な列・索引）。閉じる。
- `put_report(book_id, title, body)`: `report_store.save(SimpleNamespace(id=book_id, title=title), body)`
- `run(db, tmp_path, *args) -> int`: `drop.main(["--db", str(db), "--backup-dir", str(tmp_path / "backup"), *args])`
- `snapshot(db) -> dict`: テーブルごとに（列名のリスト, 全行を主キー順に）を `mode=ro` で読む。
- `backups(tmp_path) -> list[Path]`: `sorted((tmp_path / "backup").glob("reading-*.db"))`

**テスト**

| テスト | 確かめること |
|---|---|
| `test_下見はDBを変えず消す列と本文の突き合わせを表示する` | 終了コード 0。`snapshot` が前と同じ。写しが無い。出力に `books.report_md` と「ファイルあり」「--apply」 |
| `test_下見はほかの接続がDBを開いていても動く` | `sqlite3` の接続で1回読んで開いたまま、下見が 0。DB は同じ |
| `test_applyでreport_md列が消え他の列と行はそのまま` | 終了コード 0。`books` の列がモデルの列と同じ。`books` の残りの列の全行と、ほかのテーブル（表紙の BLOB を含む）の `snapshot` が前と同じ |
| `test_applyは消す前の写しをbackupに取る` | 写しがちょうど1つ。写しの `integrity_check` が ok で、`report_md` に元の本文がそのまま入っている |
| `test_applyのあとVACUUMで空きページが残らない` | 本文を長く（数万文字×数冊）して流す。`PRAGMA freelist_count` が 0 で、ファイルが前より小さい |
| `test_消したあと起動時の列の追加を流してもreport_mdは戻らない` | apply 後に `create_all` と `add_missing_columns(engine)` を流すと `[]` が返り、`books` に `report_md` が無い |
| `test_レポートのファイルが無い本があると何も変えずに止まる` | `@pytest.mark.parametrize` で下見と `--apply`。終了コード 1。出力にその本の id と書名と「ファイルなし」。`snapshot` が前と同じ。写しが無い |
| `test_本文が空のレポートファイルはファイルなしとして止まる` | frontmatter（`type: reading-report`、`book_id`）だけで本文が空のファイルを直接置く。終了コード 1、「ファイルなし」 |
| `test_allow_missingを付けるとファイルが無くても消し本文は写しに残る` | `--apply --allow-missing` で 0。列が消え、写しの `report_md` にその本の本文がある |
| `test_本文が違うだけなら止めずに件数を出す` | ファイルの本文を DB と違うものにして `--apply` が 0。出力に「違う 1」 |
| `test_report_mdがNULLや空白だけの本はファイルが無くても止めない` | `NULL`・`''`・`'  \n'` の本だけ。レポートのディレクトリも無い。`--apply` が 0 で列が消える |
| `test_ほかの接続がDBを開いているとapplyは止まり何も変えない` | `sqlite3` の接続で1回読んで開いたまま、`LOCK_TIMEOUT_SECONDS` を 0.1 に。終了コード 1、出力に `systemctl --user stop notes-web`。接続を閉じたあと `snapshot` が前と同じ。写しが無い |
| `test_許可リストに無いモデル外の列は消さずに名前を出す` | `books.report_html TEXT`（値あり）と `notes.legacy INTEGER` を足す。`--apply` が 0。`report_md` だけ消え、2つは値ごと残る。出力に両方の名前と「消さない」 |
| `test_2回目のapplyは消すものなしで終了コード0になり写しを増やさない` | 2回目が 0、出力に「消すものはありません」、写しは1つのまま、`snapshot` が1回目のあとと同じ |
| `test_存在しないDBを指定するとDBを作らずに終了コード1` | 下見・`--apply` とも 1。そのパスにファイルができていない。写しが無い |
| `test_SQLiteが3_35より古いと何も変えずに止まる` | `monkeypatch.setattr(drop.sqlite3, "sqlite_version_info", (3, 34, 1))`（と `sqlite_version`）。下見・`--apply` とも 1。`snapshot` が前と同じ。写しが無い |
| `test_列を参照する索引があると消さずに索引の名前を出す` | `CREATE INDEX ix_books_report_md ON books(report_md)`。下見・`--apply` とも 1。出力に `ix_books_report_md`。`report_md` が残り、`snapshot` が前と同じ |
| `test_写しの検査に通らなければ消さない` | `drop.verify_backup` を問題を返す関数に差し替える（壊れた写しは作れないため）。`--apply` が 1、`report_md` が残る |

試さないもの（作れない失敗）: DROP 後に外部キーの不整合が増える（SQLite は外部キーの列の削除を拒むので起こせない）、
VACUUM の失敗（ディスク不足）。

既存のテストは変えない。`./run.sh test`（pytest）で全部通ること。

## 9. 未決事項

- `books.report_html` など、許可リストに無いモデル外の列が見つかった場合の扱い（ユーザーの判断。消すならこの設計書に
  追記して許可リストに足す）。
- DB にだけあってモデルに無いテーブルは見ない（今回の対象は列）。
- リポジトリの外（`Storage/_vault` 側のスクリプト、DB のダンプを読む仕組みなど）が `books.report_md` を読んでいないか（未確認。ユーザーに確認）。
- 実 DB での実行は未検証（この環境に無い）。ユーザーの PC の SQLite の版、DB の大きさ、VACUUM にかかる時間は未確認。
  版が 3.35 より古かった場合の手当て（新しい SQLite を使う方法）は、そのときに決める。
- `backup/` の写しをいつ消すか（消した本文の最後のコピー。ユーザーが決める）。
