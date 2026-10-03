# 読書ノート アプリ 仕様・引き継ぎ

読書記録と学習ノート（本の要約・感想、技術書の勉強）を残す個人用Webアプリ。
**自動化・連携**（ISBNからの本情報取得、読了時の「次に読む本」提案）を最重視する。

- 最終更新: 2026-10-03（おすすめ一覧を足した。書名と紹介文でキーワード絞り込み）
- 現在地: **PC版・モバイル版とも完成**
- **デザインの正本は `Notes App Base Design/design_handoff_notes_reading_app/`**。README.md が画面仕様、`_ds/broadsheet-…/styles.css` がトークンの正本。同梱の `.dc.html` はプロトタイプで、React で再実装してある

---

## 1. 確定した仕様

| 項目 | 決定内容 |
|---|---|
| 記録手段 | PCでタイピング（手書き・スマホ入力は対象外） |
| 画面構成 | **3ペイン**（アイコンレール76px / 一覧340px / 詳細）＋ **⌘K コマンドパレット** |
| ビュー | 本棚 / メモ・引用 / 振り返り / **おすすめ** / 設定（おすすめはデザイン外の仮置き。下記） |
| 本の状態 | 積読 `unread` / 読書中 `reading` / 読了 `finished` |
| 進捗 | 読んだページ `page` と総ページ `total`。**`page >= total` で自動的に読了**にする |
| 評価 | ★1〜5（任意）。おすすめ度 `strong` / `some` / `self` |
| 記録 | **引用 `quote` / メモ `memo`** の2種類。ページ番号と、引用への補足メモを持てる |
| カテゴリ | 本に1つ。**小説 / ビジネス・実用 / エッセイ / 学術 / 雑誌 / その他**（決めていない本は「その他」）。本棚の大きな絞り込み。細かい分野はタグで持つ。見せ方はデザイン 8b（カテゴリ＝塗りのタグ、タグ＝#文字） |
| タグ | 本に付ける。複数可。本棚の絞り込みと、振り返りの「よく読む分野」に使う |
| 再読 | 読了にするたび **`readings` に1行**増える。何回読んだか・それぞれいつ読み終えたかが残る |
| 次に読む本 | 読了した瞬間に一度だけダイアログで出す（デザイン #5a）。**候補はその場で計算せず、本ごとにあらかじめ設定しておく**（下記） |
| 読書レポート | 1冊に1つ、**Markdown**。全画面の執筆モード（デザイン #6a）は上部バー＋2ペインで、「並べる / 書く / 読む」を切り替えられる。**自動保存**。本の詳細の下部にも表示する |
| 振り返り | 年・月ごとに 読了冊数 / ページ数 / 記録件数 / よく読む分野 / いちばん残した言葉 を集計 |
| 設定 | 年間の読書目標 / 本棚の並び順 / 引用の書体 |
| 自動化① | ISBN・書名からタイトル・著者・出版社・**ページ数・分野・表紙**を自動取得。**表紙が取れない本は手で入れられる** |
| 自動化② | 読了時に「次に読む本」を提案。候補は**手で設定**しておく（外部APIは使わない） |
| 読了日 `finished_on` | **一度入ったら残す**。状態を戻しても消さない。明示的に空にしたときだけ `null` |
| 日時の扱い | **すべて JST**。DB には naive（タイムゾーンなし）で保存 |
| ISBN | DB には常に**ハイフンなしの13桁**。入力はハイフン付き・ISBN-10 も受け付けて変換 |
| フロント配信 | 開発中は Vite dev server / 日常利用は `npm run build` → FastAPI から配信 |
| 実行環境 | ローカルPCで起動し、Tailscale 経由でリモートから利用 |
| 認証 | なし（tailnet 内のみで利用するため） |
| 見た目 | **Broadsheet デザインシステム**。Source Serif 4 ＋ Noto Serif JP、罫線で区切らず余白で階層を作る。シアン＝操作、マゼンタ＝引用だけ |
| 配置 | **左揃え**（Broadsheet の方針どおり）。詳細ペインの中身は最大920px で左に寄せ、余白は右に残す |
| スマホ | 幅820px以下では**モバイル版**（タブバー＋単一画面、デザイン #7a〜7g）に切り替える |

## 2. 構成

- バックエンド: FastAPI + SQLAlchemy 2.1 + Pydantic v2 + SQLite
- フロントエンド: React + TypeScript + Vite + Tailwind CSS
- Python 仮想環境は**リポジトリルートの `.venv/`** 1つ（backend 用。frontend は npm）

### 起動モードは2つある

**(A) 開発中: Vite dev server 経由**（ホットリロードが効く）

```
[ブラウザ（他端末）] --Tailscale--> [Vite dev server :5765 (0.0.0.0)]
                                         | /api をプロキシ
                                         v
                                  [FastAPI :8765 (127.0.0.1)] --> SQLite (reading.db)
                                         |--> Google Books / 国立国会図書館 API（ISBN）
                                         |--> Claude API（次に読む本の提案）
```

- **API は `127.0.0.1` で待ち受け、外に公開するのは Vite だけ**。フロントは相対パス `/api/...` で呼び、Vite の `server.proxy` で FastAPI に中継する（CORS 設定は不要）

```ts
// vite.config.ts（Step 2 で作成）
server: {
  host: "0.0.0.0",
  proxy: { "/api": "http://127.0.0.1:8765" },
}
```

**(B) 日常利用: FastAPI 1プロセスだけ**（ビルド済みの静的ファイルを配信）

```
[ブラウザ（他端末）] --Tailscale--> [FastAPI :8765 (0.0.0.0)]
                                      |--> / …… frontend/dist（HTML/JS/CSS）
                                      |--> /api …… API
                                      `--> SQLite (reading.db)
```

- 毎回 2 つのプロセスを立ち上げるのは面倒なので、普段使いはこちらに寄せる
- **マウント順が重要**。ルーター登録 → 静的ファイル、の順にする。逆にすると `/` にマウントした静的ファイルが `/api/...` まで飲み込む
- SPA（画面遷移をブラウザ側で行う作り）なので、**未知のパスは `index.html` を返す**必要がある。`StaticFiles(html=True)` はディレクトリ直下しか面倒を見ないため、キャッチオールのルートを自分で置く

```python
# app/main.py（Step 2 で実装済み）
app.include_router(books.router)           # ① API を先に登録する

DIST_DIR = (Path(__file__).resolve().parents[2] / "frontend" / "dist").resolve()

@app.get("/{full_path:path}", include_in_schema=False)   # ② 最後に登録する
def serve_frontend(full_path: str):
    if full_path.startswith("api/"):       # 存在しない API を index.html で返すと原因が分からなくなる
        raise HTTPException(status_code=404, detail="見つかりません")
    if not DIST_DIR.is_dir():
        raise HTTPException(status_code=404, detail="フロントエンドがまだビルドされていません（cd frontend && npm run build）")
    if full_path:                          # /assets/index-xxxx.js など実在するファイルはそのまま返す
        candidate = (DIST_DIR / full_path).resolve()
        if candidate.is_relative_to(DIST_DIR) and candidate.is_file():
            return FileResponse(candidate)
    return FileResponse(DIST_DIR / "index.html")          # それ以外は SPA に任せる
```

> `StaticFiles` の `mount` を使わず、このルート1つで済ませている理由:
> `mount` はディレクトリが**存在する前提**で登録されるため、サーバを起動したあとに
> `npm run build` しても拾われない。上の形なら、ビルド前に起動しても「ビルドしてください」と
> 案内でき、ビルド後は再起動なしで配信できる。
>
> `resolve()` + `is_relative_to()` は、`/../../backend/reading.db` のようなパスで
> `dist` の外のファイルを読み出されないための確認（**パストラバーサル**と呼ばれる古典的な穴）。
> テストで実際に塞げていることを確認している。

> 補足（新しい概念）: FastAPI は**登録した順に**ルートを照合する。だから「具体的なパス → 何でも拾うパス」の順に書く。

## 3. ディレクトリ

リポジトリのルートは `Notes/`。`reading-notes/` のような階層は**挟まない**（旧記述からの変更点）。

```
Notes/                          ← git リポジトリのルート
├── .venv/                      Python仮想環境（ルートに1つ。git管理外）
├── .gitignore
├── .claude/skills/next-book-suggestions/  「次に読む本」の候補づくり（SKILL.md が手順の正本）
├── .claude/skills/keyword-suggestions/    キーワードのおすすめづくり（照合は next-book-suggestions の nbs.py を使う）
├── docs/SPEC.md                このファイル
├── Notes App Base Design/      ClaudeDesign から受け取ったデザイン（正本。触らない）
│   └── design_handoff_notes_reading_app/
│       ├── README.md           画面仕様。実装で迷ったらここを見る
│       ├── Notes Web.dc.html   Web版のプロトタイプ（出荷コードではない）
│       ├── Notes Next Book.dc.html  「次に読む本」#5a（未実装）
│       └── _ds/broadsheet-…/   デザインシステム（styles.css がトークンの正本）
├── backend/
│   ├── requirements.txt / pytest.ini / reading.db(git管理外)
│   ├── app/
│   │   ├── main.py             入口（lifespan で create_all + ルーター + 静的配信）
│   │   ├── database.py         engine / Base / get_db / SQLite の PRAGMA
│   │   ├── timeutil.py         JST の now / today（日時はここ経由で取る）
│   │   ├── isbn.py             ISBN の正規化（ハイフン除去・10→13変換・検査）
│   │   ├── booklookup.py       本を探す（国会図書館 / openBD / Google Books）
│   │   ├── settings_store.py   設定の1行を読む（無ければ既定値で作る）
│   │   ├── models.py           Book / Note / Settings
│   │   ├── schemas.py          API入出力の型・バリデーション
│   │   └── routers/
│   │       ├── books.py  lookup.py  notes.py  reviews.py  settings.py
│   │       └── suggestions.py  Step 5（未作成）
│   └── tests/                  conftest / fixtures_lookup / test_*.py
└── frontend/
    ├── vite.config.ts          dev server の host / プロキシ設定
    └── src/
        ├── api.ts              バックエンドとの通信をここにまとめる
        ├── export.ts           Markdown / CSV の書き出し
        ├── types.ts            ビューと絞り込みの型
        ├── App.tsx             3ペインのシェル・ビュー切替・⌘K・執筆モード
        ├── styles/
        │   ├── broadsheet.css  デザインシステムの正本のコピー（触らない）
        │   └── app.css         アプリ固有。トークンだけを使う
        └── components/
            ├── Rail / LibraryPane / NotesPane / ReviewPane / SettingsPane
            ├── BookDetailView / NoteDetailView / ReviewView / SettingsView
            ├── CommandPalette / ReportEditor / MemoWindow
            └── Segmented / Cover / Stars / CmykNumber / Toast
```

> フロントの見た目（Tailwind のクラス）は仮置き。**後から ClaudeDesign のデザインに差し替える**前提なので、
> 構造とロジックはコンポーネントに、装飾は `className` に閉じ込めてある。

### .gitignore（ルートに置く）

```gitignore
.venv/
__pycache__/
*.py[cod]
reading.db
reading.db-wal
reading.db-shm
.env
node_modules/
frontend/dist/
.pytest_cache/
```

### 起動・確認コマンド

**`./run.sh` がすべての入口**。中身は薄いシェルスクリプトなので、困ったら読めば分かる。

```bash
./run.sh              # 開発モード。API と画面を両方立てる（ホットリロードあり）
./run.sh serve        # Tailscale 経由で他の端末から使う（HTTPS・tailnet 内のみ）
./run.sh start        # このPC/LAN から使う。ビルドして1プロセスで配信
./run.sh test         # pytest と型チェック
./run.sh setup        # 依存をインストール（初回・依存を足したとき）
./run.sh help         # 使い方
```

- **ポートが埋まっていたら、誰が使っているかを出して止まる**（勝手に kill しない）。
  他のプロジェクトのサーバーとぶつかることがあるため。
  そのときは `API_PORT=8010 ./run.sh` のように変えて逃げる
- `API_PORT` は Vite にも渡していて、`vite.config.ts` がプロキシ先を合わせる。
  ポートを変えても開発モードが壊れない
- 起動すると **Tailscale の IP を使ったURL** も出るので、スマホからはそれを開く
- Ctrl+C で API と画面の両方が止まる（`trap` でまとめて面倒を見ている）

手で動かしたいときは、スクリプトを使わず直接でもよい。

```bash
cd backend && ../.venv/bin/uvicorn app.main:app --reload    # API だけ
cd frontend && npm run dev                                  # 画面だけ
```

### リモート接続（Tailscale）

スマホやタブレットから使うときは **`./run.sh serve`**。

```
[iPhone / iPad] --Tailscale--> https://<このPCの名前>.<tailnet>.ts.net:8765
                                      | Tailscale が TLS を終端して中継
                                      v
                               [FastAPI 127.0.0.1:8765]
```

- アプリは **127.0.0.1 でだけ待ち受ける**。外への出口は Tailscale が持つので、
  **同じLAN（喫茶店のWi-Fiなど）からは見えない**。このアプリには認証が無いので、
  この差は大きい
- URL は **MagicDNS の名前＋HTTPS**。証明書は Tailscale が用意するので警告も出ない
- `tailscale serve` は **tailnet の中だけ**。`tailscale funnel`（インターネットに公開）は
  **使わない**。認証が無いアプリを公開してはいけない

**一度だけ必要な設定**（`tailscale serve` の変更には権限が要る）:

```bash
sudo tailscale set --operator=$USER   # 以後 sudo なしで ./run.sh serve が通る
```

**⚠ ポートに注意**。このPCでは Tailscale の **443 と 8443 が別のプロジェクトに使われている**。
`run.sh` は指定されたポートが既に使われていたら**上書きせずに止まる**（`tailscale serve reset` は
他の設定まで消すので使っていない）。ぶつかるときは `TS_PORT=10000 ./run.sh serve`。

`./run.sh start` は `0.0.0.0` で待ち受けるので Tailscale からも LAN からも見える。
家の中で使うぶんには足りるが、外に持ち出すなら `serve` を使う。

## 4. データモデル

### Book

| カラム | 型 | 備考 |
|---|---|---|
| id | int PK | |
| isbn | str(13) \| null | unique。**ハイフンなし13桁に正規化して保存** |
| title | str(255) | 必須 |
| author / publisher | str(255) \| null | ISBN検索で自動入力 |
| category | str(120) \| null | 分野。振り返りの「よく読む分野」に使う。国会図書館の件名から取る |
| genre | enum | **カテゴリ**。`novel`（小説）/ `business`（ビジネス・実用）/ `essay`（エッセイ）/ `academic`（学術）/ `magazine`（雑誌）/ `other`（その他）。既定 `other`。PATCH で null は 422（未分類は作らない）。列は後から足したので DB では null を許し、null の行は API が `other` として返す。`category`（件名）とは別物なので、コードでは genre と呼ぶ |
| cover_url | str(500) \| null | 実体は `/api/covers/{isbn}`（下記の書影の中継を参照） |
| status | enum | `unread` / `reading` / `finished`。既定 `unread` |
| rating | int \| null | DB側でも CHECK 1〜5 |
| recommend | enum \| null | `strong`（人にすすめたい）/ `some`（人を選ぶ）/ `self`（自分用） |
| page | int | 読んだところまで。既定 0。CHECK >= 0。**画面は％で入力**し、`total` との換算でここに入れる |
| total | int \| null | 総ページ数。CHECK > 0 |
| started_on | date \| null | 読み始めたら今日（JST）を自動設定 |
| finished_on | date \| null | 読了になったら今日（JST）を自動設定。**戻しても消さない** |
| report_html | text \| null | 読書レポートの本文 |
| created_at / updated_at | datetime | **Python側で JST を入れる**（`default=now_jst`） |

APIが足して返す値: `progress`（読んだ割合％。総ページ未設定なら `null`）、`note_count`、`has_report`。
**一覧では `report_html` を返さない**（長いため）。詳細だけが返す。

進捗と状態のつじつまは `_apply_progress_rules()` が1箇所で面倒を見る:
`page >= total` なら読了にする → 読書中/読了になったら開始日を入れる → 読了なら読了日を入れる。
日付はフォームから明示的に送られたときは上書きしない。

### Note（引用・メモ）

| カラム | 型 | 備考 |
|---|---|---|
| id | int PK | |
| book_id | FK → books.id | `ondelete="CASCADE"` ＋ index。本の削除でノートも消える |
| kind | enum | `quote`（引用）/ `memo`（自分の考え） |
| page | int \| null | 何ページの記録か。**任意**（CHECK > 0）。電子書籍は表示設定でページが変わるので、入力欄も既定は空にしてある |
| text | text | 引用なら抜き書き、メモなら自分の考え。必須 |
| memo | text \| null | 引用に添える自分のひとこと |
| created_at / updated_at | datetime | JST |

> 旧仕様の `title` / `body` から作り直した。デザインが「引用」と「メモ」を別物として扱い、
> ページ番号と引用への補足を持つため。

### Reading（読み終えた記録）

| カラム | 型 | 備考 |
|---|---|---|
| id | int PK | |
| book_id | FK → books.id | cascade ＋ index |
| finished_on | date | いつ読み終えたか |
| created_at | datetime | JST |

- **読了になった瞬間だけ1行増える**。読書中に戻してまた読了にすると2行目が増える（再読）
- 同じ日付の行があれば足さない（二重記録を防ぐ）
- `Book.read_count` はこの行数。`Book.finished_on` は「最後に読み終えた日」

### BookCover（自分で入れた表紙）

| カラム | 型 | 備考 |
|---|---|---|
| book_id | FK → books.id PK | cascade |
| data | BLOB | 縮めた JPEG |
| content_type | str(40) | `image/jpeg` |
| updated_at | datetime | JST |

- 国会図書館に書影が無い本（洋書・文庫の分冊など）があるので、手で入れられるようにしてある。
  **実測では8冊中6冊は自動で取れた**が、残りは手入力になる
- **ファイルではなくDBに入れる**。バックアップが `reading.db` 1つで済むという最初の方針を守るため
- 撮った写真をそのまま入れるとDBが膨らむので、**保存する前に 600×900 以内に縮めて JPEG に揃える**
  （`app/covers.py`）。透過は白で埋める
- `Book.cover_url` は `/api/books/{id}/cover?v=<更新時刻>` になる。**URL に更新時刻を付ける**のは、
  入れ替えてもURLが同じだとブラウザが古い画像を出し続けるため

### Tag / book_tags

| カラム | 型 | 備考 |
|---|---|---|
| tags.id | int PK | |
| tags.name | str(40) | unique。同じ名前のタグは1行だけ |
| book_tags | (book_id, tag_id) | 本とタグの多対多 |

- APIでは `tags: ["技術書", "設計"]` と**名前の配列**でやり取りし、行への変換はサーバー側でやる
- 無い名前はその場で作る。前後の空白は落とし、同じ名前は二重に付けない
- 本を消してもタグ自体は残る（結び付きだけ消える）。どの本にも付いていないタグは `/api/tags` に出さない

### DismissedBook（興味なし）

| カラム | 型 | 備考 |
|---|---|---|
| id / isbn / created_at | | isbn は unique |

おすすめの候補はまだ本棚に無い本なので、本のidではなく **ISBN で覚える**。

### Settings（1行だけ）

| カラム | 型 | 備考 |
|---|---|---|
| id | int PK | 常に 1 |
| yearly_goal | int | 年間の読書目標。既定 50 |
| sort | enum | `recent`（追加順）/ `title`（書名）/ `progress`（進捗）。既定 `recent` |
| quote_style | enum | `italic` / `plain`。既定 `italic` |

行が無ければ既定値で作ってから返す（`settings_store.get_settings`）。

### Suggestion（次に読む本）

| カラム | 型 | 備考 |
|---|---|---|
| id | int PK | |
| book_id | FK → books.id | **この本を読み終えたときに出す**候補。cascade ＋ index |
| title / author / isbn / cover_url | | isbn は13桁に正規化。分からなければ null |
| basis | enum | `note`（引用・メモから）/ `rating`（評価から）/ `tag`（分野から） |
| distance | enum | `near`（近い本）/ `far`（少し離れた本） |
| reason | text | **理由は一言**（200字まで）。画面にそのまま出る |
| position | int | 画面に出す順番 |
| added_book_id | FK → books.id \| null | 積読に追加済みならその本の id |
| created_at | datetime | JST |

**候補はその場で計算しない。**本ごとにあらかじめ設定しておいたものを読むだけ。

### Topic / TopicSuggestion（キーワードのおすすめ）

「ゲーム理論」「統計」のような**キーワードに紐づく**おすすめ（2026-10-03 追加）。
Suggestion が本棚の1冊に紐づくのに対し、こちらは本に紐づかない。本棚の本は選書の手がかりにするだけ。

| テーブル | カラム | 備考 |
|---|---|---|
| topics | id / keyword / created_at / updated_at | keyword は unique。**全角/半角と空白をそろえて保存**（「ＡＩ　倫理」→「AI 倫理」） |
| topic_suggestions | id / topic_id | topic_id は cascade ＋ index |
| | title / author / isbn / cover_url / reason / position / added_book_id | Suggestion と同じ意味 |
| | distance | `near` / `far`。勉強系の3区分（同じテーマの難易度別・近いテーマ → near、少し離れたかんたんな本 → far）を寄せたもの。**区分の列は持たない**（難しさの違いは reason に書く） |
| | from_book_id | 手がかりにした本棚の本（「『〇〇』より一段深く」の〇〇）。FK → books.id、**SET NULL**。無ければ null |

`basis`（根拠）は持たない。根拠は常にキーワードなので。

### マイグレーションについて

- 起動時に `Base.metadata.create_all`（無いテーブルを作る）と
  `database.add_missing_columns`（既存のテーブルに無い列を `ALTER TABLE … ADD COLUMN` で足す）を流す
- **実データが入ったので reading.db はもう作り直さない**（2026-10-03）。足せるのは **null を許す列だけ**。
  null を許さない列を足そうとすると起動時に止まる（既存の行に入れる値が無いため）
- 列の型変更・削除・null を許さない列の追加が要るようになったら、そのときに Alembic を入れる

### SQLite の接続設定

`database.py` の `configure_sqlite()` が接続のたびに PRAGMA を流す。

- `journal_mode=WAL`: 読み書きが同時に起きてもブロックしにくくなる
- `foreign_keys=ON`: **SQLite は外部キー制約が既定で無効**。ノートの cascade に必要

## 5. API

### 本（`/api/books`）

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/books?status=&sort=&tag=` | 一覧。`sort` を省くと設定の並び順に従う |
| GET | `/api/books/{id}` | 詳細（`report_html` 込み） |
| POST | `/api/books` | 登録（201） |
| PATCH | `/api/books/{id}` | 部分更新（送った項目だけ） |
| DELETE | `/api/books/{id}` | 削除（204） |
| PUT | `/api/books/{id}/cover` | 表紙の画像を入れ替える（multipart。10MBまで、大きすぎたら413） |
| GET | `/api/books/{id}/cover` | 自分で入れた表紙を返す |
| DELETE | `/api/books/{id}/cover` | 自分で入れた表紙を外す |

### 引用・メモ

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/books/{id}/notes` | その本の記録。**ページの大きい順**（本の詳細用） |
| POST | `/api/books/{id}/notes` | 作成（201） |
| GET | `/api/notes?kind=` | 全部の本を横断（新しい順）。出典の本が付いてくる |
| GET / PATCH / DELETE | `/api/notes/{id}` | 取得・更新・削除 |

### openBD について（ISBN 引きの一番手）

openBD **だけ**で作ることはできない。実測した結果:

| 調べたこと | 結果 |
|---|---|
| `/v1/get?title=...` | `[null]` — **ISBN でしか引けない** |
| `/v1/search` | **404** — 検索APIが無い |
| 8冊で 表紙 / ページ数 / 紹介文 / 件名 | **すべて無し** |

持っているのは実質 **書名・著者・出版社・刊行年だけ**。書名から候補を出すことも、
ページ数・分野・表紙を取ることもできない。

一方で **ISBN が分かっているときは速くて取りこぼしが少ない**（実測 平均 0.04秒・
6冊中5冊）。そこで **ISBN 引きの一番手**に置き、足りない項目は Google Books で
埋める（下の「探す順番」を参照）。

### ASIN について

Amazon の ASIN も、そのまま ISBN 欄・検索欄に入れてよい。

- **紙の本の ASIN は ISBN-10 と同じ値**なので、既存の「10桁→13桁」変換がそのまま効く
  （実測: `4274226298` → 達人プログラマー、`020161622X` → Pragmatic Programmer）
- **Kindle版の ASIN（`B` で始まる英数字10桁）は ISBN を持たない**ので調べられない。
  「チェックディジットが合いません」では何が悪いか伝わらないので、
  **Kindle版だと分かる文言で断る**（`isbn.py` の `_KINDLE_ASIN`）

### 本の情報を探す

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/isbn/{isbn}` | ISBN から本の情報（保存しない）。無ければ 404 |
| GET | `/api/search?q=&limit=` | 書名・著者で探す。⌘K の「本を追加」用 |
| GET | `/api/covers/{isbn}` | 書影を中継して返す。無ければ 404 |

#### 探す順番

**どのサービスに何が載っているかは本によって違う**ので、速い順に当たって、
足りない項目だけを後から埋める。

| | ISBN から引く | 書名から引く |
|---|---|---|
| 1番目 | **openBD**（0.04秒） | **Google Books**（0.6秒） |
| 2番目 | **Google Books**（0.5秒） | 国会図書館 `title=`（12〜39秒） |
| 3番目 | 国会図書館（6.5秒） | 国会図書館 `creator=` |
| 仕上げ | 空いている項目を Google Books で埋める | — |

同じ ISBN を Google Books に二度聞かない（1番目〜2番目で聞いた答えを仕上げに回す）。

**なぜ国会図書館を後ろに回したか**（ISBN 6件での実測）:

| | 見つかった | 平均 |
|---|---|---|
| openBD | 5 / 6 | 0.04秒 |
| Google Books | 6 / 6 | 0.52秒 |
| 国会図書館 | 2 / 6 | 6.54秒（30秒で返らない本が1件） |

遅いうえに取りこぼしが多い。ただし古い本や流通の少ない本は国会図書館にしか
無いことがあるので、**最後の受け皿としては残す**。

この並び替えで ISBN 引きは **平均 6.4秒 → 1.55秒**、8冊中7冊で表紙が付くようになった。

**引き換えに失ったもの**: 国会図書館にしかページ数が無い本（実測 8冊中1冊）は、
ページ数が空のままになる。ページ数は画面で手入力できるので、全件を 6.5秒
待たせるより空欄のほうがよいと判断した。

**Google Books を使うには APIキーを `backend/.env` に置く**（取り方と料金は `.env.example` に書いてある）。
未設定なら問い合わせない（キー無しでは必ず 429 になるので、往復が無駄になるため）。
キーが無いときは従来どおり 国会図書館 → openBD の順で動く。

料金は、2026-09 時点で公式ドキュメントを確認した範囲では**料金ページも課金対象の項目も存在せず、
記載がない**。制限は回数（割り当て）で管理されていて、自分のプロジェクトの上限は
Cloud Console の「割り当て」で確認できる。

### タグ・おすすめ

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/tags` | 使われているタグと冊数（多い順） |
| GET | `/api/suggestions` | 設定してある候補を**全部**、どの本の候補か（`book`: id・書名・著者）を添えて返す。本ごと・設定した順。「興味なし」の本は外す。おすすめ一覧用（本ごとに取ると100回以上の往復になるため） |
| GET | `/api/books/{id}/suggestions?basis=&distance=&page=&per_page=` | 設定してある候補を返す。`basis` は `note,rating,tag` のカンマ区切りで**最低1つ必要**、`distance` は `near`/`far`/`both`、`page` は「出し直す」で増やす、`per_page` は1ページの冊数（既定3＝読了ダイアログの3列。本の詳細画面は 20 を渡して全部出す） |
| PUT | `/api/books/{id}/suggestions` | その本の候補を**まとめて入れ替える**（20件まで。空配列で全消し） |
| POST | `/api/suggestions/{id}/add` | 候補を積読として本棚に追加（201）。同じISBNの本があれば使い回す |
| POST | `/api/suggestions/dismiss?isbn=` | 興味なし（204）。ほかの本のおすすめからも消える |

`GET` の戻りには **`configured`** が入る。`false`（候補を1件も設定していない）なら、
画面は「まだ決めていません」を出す。0件と「未設定」を同じ扱いにすると、
「条件に合う候補がありません」と出て、設定すれば出ることが伝わらない。

**候補の設定の仕方**: Claude Code のスキル **`next-book-suggestions`**
（`.claude/skills/next-book-suggestions/`）で行う。1冊につき **近い本2・少し離れた本2**。
worker エージェント（sonnet）が選書し、`scripts/nbs.py` が ISBN を `/api/isbn` で引いて
**書名が一致した本だけ**を流し込む（架空の本・本棚にある本・「興味なし」の本を弾く）。
足りない分だけ補充するので、何度回してもよい。読了後にメモから選び直すときは `--replace`。
手順の正本はスキルの `SKILL.md`。

流し込む形（手で1冊だけ直すときもこれ）:

```bash
curl -X PUT http://localhost:8765/api/books/1/suggestions \
  -H 'Content-Type: application/json' -d '[
  {"title": "リファクタリング", "author": "Martin Fowler", "isbn": "9784274224546",
   "cover_url": "/api/covers/9784274224546",
   "basis": "note", "distance": "near",
   "reason": "メモに書いた「リファクタリング」を、手順として1冊で追えます"}
]'
```

### キーワードのおすすめ

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/topics` | キーワードの一覧（`id` / `keyword` / `count` / `updated_at`）。設定し直した順。`count` は興味なしを除いた数 |
| GET | `/api/topics/{id}` | キーワード1つぶんの候補（設定した順。興味なしは外す） |
| PUT | `/api/topics` | 本文 `{keyword, suggestions}` で**まとめて入れ替える**。キーワードが無ければ作る。候補は1〜20件（空にはできない）。`from_book_id` が本棚に無ければ 422 |
| DELETE | `/api/topics/{id}` | キーワードごと消す（204） |
| POST | `/api/topic-suggestions/{id}/add` | 候補を積読として本棚に追加（201）。「次に読む本」と同じ処理（`suggestions.shelve`） |

- キーワードを**パスではなく本文**で受け取るのは、「CI/CD」のようなスラッシュ入りのキーワードを扱うため
- 「興味なし」（`POST /api/suggestions/dismiss`）はこちらにも効く。ISBN で覚えているので
- 設定は Claude Code のスキル **`keyword-suggestions`** で行う（手順の正本はスキルの `SKILL.md`）。
  **画面はまだ無い**（API だけ）

### 振り返り・設定

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/reviews` | 期間の一覧（`period` / `label` / `sub` / `count`） |
| GET | `/api/reviews/{period}` | `2026` か `2026-09`。集計結果 |
| GET / PATCH | `/api/settings` | 設定の読み書き |

### エラーの返し分け

| 状況 | コード |
|---|---|
| 入力の形が不正（★6、`title: null`、ISBNが13桁にならない、知らない項目） | 422 |
| ISBN が既存と重複 | 409 |
| それ以外の制約違反 | 400 |
| 対象が存在しない | 404 |

PATCH の約束: **項目を送らない＝変更しない、`null` を送る＝空にする**。
ただし `title` / `status` / `page` / `kind` / `text` は NOT NULL なので `null` は 422。

## 6. 実装ステップ

- [x] **Step 1: 本のCRUD（バックエンド）**
- [x] **Step 1.5: Step 1 の修正 + テスト** — 実際に動かして見つかった不具合4件を修正
  1. `_commit()` が `IntegrityError` を全部 409 にしていた（`title: null` が「ISBN重複」になる）
  2. 空文字 ISBN が登録でき、2冊目で 409 になる
  3. ハイフン付き ISBN が `max_length=13` で弾かれる（正規化が検証より後だった）
  4. `status=finished` の本の読了日を `null` で消せない（自動補完が無条件に走っていた）

  あわせて 日時のJST統一 / enumを値で保存 / WAL・foreign_keys / 一覧の既定の並び を直した。

- [x] **Step 2: フロントエンドの骨組み** — Vite + React + TS
- [x] **Step 3: ISBN 自動取得**
- [x] **Step 4: 引用・メモ**

- [x] **Step D: ClaudeDesign のデザイン適用**（今回の大きな作り直し）
  - **データモデルを作り直した**: Book に `publisher` / `category` / `page` / `total` /
    `started_on` / `recommend` / `report_html` を追加。Note を `title`/`body` から
    `kind`/`page`/`text`/`memo` へ。`Settings` テーブルを追加
  - **デザインシステムを導入**: Tailwind をやめ、`_ds/broadsheet-…/styles.css` を
    `frontend/src/styles/broadsheet.css` にコピーして正本にした。色・書体・余白・角丸・影は
    すべてこのファイルの変数から取り、hex や px を直書きしない
  - 書体（Source Serif 4 / Noto Serif JP）とアイコン（Phosphor duotone）は
    CDN ではなく npm で同梱し、ネットに出られなくても同じ見た目になるようにした
  - **3ペイン ＋ 4ビュー ＋ ⌘K ＋ 全画面のレポート執筆モード**を実装
  - 振り返りの読了冊数はデザインシステムの `.cmyk-num`（CMYK の版ずれ表現）を使う

- [ ] **Step 5: 次に読む本** — **デザインあり（`Notes Next Book.dc.html` #5a）。未着手**。
  読了した瞬間に一度だけ出るダイアログ。詳細は下記

- [x] **Step E: 画面の追加要望**（2026-09-26）
  1. **一覧＋詳細を画面の中央に寄せた**（レールは左端のまま）。
     ⚠ Broadsheet は「左揃えの非対称レイアウト」が方針なので、**デザインシステムとは逆**。
     デザインを作り直してもらうときは、この点を伝えること
  2. **レポートを Markdown に変えた**（`report_html` → `report_md`）。執筆画面は左に入力・右にプレビュー。
     contenteditable をやめたので、キャレット保持の細工は textarea の `selectionStart` に置き換わった
  3. **進捗パネルに「読み終えた」ボタン**を足した。総ページ数を打ち直さずに読了にできる
  4. **再読を記録できるようにした**（`readings` テーブル）。「もう一度読む」で進捗が0に戻り、
     もう一度読了にすると2回目として記録される
  5. **レポートを本の詳細の下部に表示**するようにした
  6. **本を追加する画面**を足した（本棚ヘッダーの「＋ 追加」）。書名検索・ISBN検索・手入力・タグ付けが1画面で済む
  7. **タグ**を足した。本棚をタグで絞り込め、振り返りの「よく読む分野」もタグを優先して見る
  8. **「次に読む本」の画面**を作った（デザイン #5a）。根拠トグル・距離・出し直す・興味なしまで動く。
     **候補の選び方（`suggest.py`）はまだ仮**で、自分の積読の中から選んでいるだけ

- [x] **Step F: 中央寄せの取り消しと Markdown エディタ**（2026-09-26）
  - **中央寄せをやめて左揃えに戻した**。Broadsheet は「左揃えの非対称レイアウト」が方針で、
    中央寄せはそれと真っ向からぶつかっていた。代わりに**詳細の幅を 760px → 920px に広げて**
    画面を使うようにした（記録の本文も 620px → 720px）
  - **執筆モードをデザイン #6a に作り直した**（`Notes Report.dc.html` #6a）:
    - 左サイドバー式をやめ、**上部バー56px**（[本に戻る] 書名 ｜ ツール5つ ｜ `n字 · 自動保存済み` ｜ [メモ窓] ｜ 並べる/書く/読む）
    - 本体は2ペイン。左は Markdown 原文（**セリフ体** 16px/1.9、`--color-neutral-100`）、
      右は紙面（ラベル・書名40px・題字罫＋レンダリング結果）
    - 「並べる」のときだけ**右のスクロールを左に連動**させる
    - **自動保存**（打つ手が止まって1.2秒）。閉じる操作とは別経路にしてある
    - メモ窓に**「記法」タブ**（12行。クリックで挿入、見本は実際の書体・色で表示）
  - **全画面のかぶせもの（執筆モード・⌘K・次に読む本）を `position: fixed` に変えた**。
    `absolute` だと、画面が `min-height:640px` より低いときにページごとスクロールして
    上部バーが隠れてしまう

- [x] **Step G: 「追加しても反映されない」の修正**（2026-09-26）
  - 症状: **絞り込みが効いている状態で本を追加すると、一覧に出てこない**。
    読了タブを見ているときに本を足すと、新しい本は「積読」なので弾かれる。
    詳細ペインには出るので「追加はできたのに反映されない」と見える
  - 同じことが ⌘K から本を開いたとき、メモの詳細やおすすめから本を開いたときにも起きていた
  - 対応: **その本を隠している絞り込みだけを外す**（`src/visibility.ts` の
    `filtersRevealing`）。関係のない絞り込みは残すので、ユーザーが選んだ状態を
    むやみに壊さない。例: 積読タブで積読の本を足しても、タブは積読のまま
  - 判定は条件分岐が絡んで回帰しやすいので、純粋関数に切り出して vitest で12件のテストを置いた

- [x] **Step H: 「次に読む本」の仕様確定 — 初期版 完成**（2026-09-26）
  - **候補はその場で計算しない。本ごとにあらかじめ設定しておく**方式に決めた。
    Claude との相談で1冊につき3件ほど選び、`PUT /api/books/{id}/suggestions` で流し込む
  - 実行時の推薦エンジン（`suggest.py`）は削除した。**外部APIを原則使わない**ので、
    ダイアログは待ち時間ゼロで開き、理由も人の言葉で書ける
  - 候補を1件も設定していない本は、`configured: false` を返して画面に
    **「まだ決めていません」**を出す（「条件に合う候補がありません」とは区別する）
  - `POST /api/suggestions/{id}/add` で積読に追加し、`added_book_id` を控える。
    ダイアログを開き直しても「✓ 積読に追加しました」が残る
  - 実測で見つけた不具合も直した: **国会図書館サーチの 429 / タイムアウトを「0件」と
    同じ扱いにしていた**。画面が「その本はありません」と嘘をつくので、
    引けなかったときは **503** を返し、⌘K と追加画面で別の文言を出すようにした
  - **候補づくりをスキル化した**（2026-09-26）: `.claude/skills/next-book-suggestions/`。
    6冊のパイロットで手順を決め、1冊 **near 2・far 2** に変更。選書は worker を sonnet で動かす
    （haiku は和書の知識が足りない）。照合で見つけた落とし穴:
    openBD は副題を持たないことがある / 翻訳書の著者はローマ字＋訳者で返る

- [x] **Step I: モバイル版**（2026-09-26、デザイン #7a〜7g）
  - 症状: スマホで本をタップしても詳細が出ない。実測すると、`.shell` の `min-width:1080px` に対して
    画面が 390px しかなく、**詳細ペインは x=416〜1080 で画面の外**にあった（横に690pxはみ出す）
  - 3ペイン前提のレイアウトを縮めても解けないので、**幅820px以下では画面ごと差し替える**ことにした
  - `useAppData()` にデータの読み書きをまとめ、PC版（`DesktopShell`）とモバイル版（`MobileApp`）が
    同じものを使う。**画面の組み立てだけが違う**
  - 実装した画面: 7a 本棚（いま読んでいるカード・検索バー・セグメント・行）/ 7b 本の詳細
    （2列ボタン・レポート行・記録一覧・メモのモーダルシート）/ 7c 探す / 7d メモ（**本ごとにまとめる**）/
    7e 振り返り（期間チップ・`.cmyk-num` 112px）/ 7f レポート（書く・読む＋ハーフシート）/
    7g 次に読む本
  - タブバーは 本棚 / メモ / 振り返り / 探す。**詳細ではタブバーを残し、執筆では隠す**（デザインの指定）
  - ハーフシートからの挿入は、**差し込んだらシートを自動で閉じる**（PC版との違い）

- [x] **Step J: 表紙を手で入れられるようにした**（2026-09-26）
  - 実測: ISBN から**8冊中6冊は表紙が自動で取れた**。取れなかったのは
    「ノルウェイの森（文庫・上巻）」と「The Pragmatic Programmer（洋書）」で、
    どちらも国会図書館に書影が無い
  - 残りのために `PUT /api/books/{id}/cover` を追加。本の詳細（PC・スマホ）と
    追加画面から「表紙を選ぶ」で入れられる
  - **スマホの探す画面に ISBN での追加を足した**。書名検索しか無く、
    ISBN を打っても何も起きなかった（PC版の ⌘K にはあった）

- [x] **Step K: ASIN と Google Books の整理**（2026-09-26）
  - **Google Books はキー無しでは使えない**と分かった。429 の中身が
    `quota_limit_value: "0"` で、「使いすぎた」のではなく**キー無しは0件**という意味だった。
    `GOOGLE_BOOKS_API_KEY` を読み、**未設定なら問い合わせない**ようにした（往復を1回省ける）
  - **ASIN は紙の本ならそのまま通る**（ASIN = ISBN-10）。Kindle版の ASIN は ISBN が無いので、
    そうと分かる文言で断るようにした
  - `run.sh` が `backend/.env` を読むようにした

- [x] **Step L: 書名検索が失敗する原因を突き止めた**（2026-09-26）
  - 症状: 同じ言葉を3秒あけて引くと、1回目は6件・2回目は503
  - 原因は**レート制限ではなかった**。タイムアウト60秒で測り直すと、
    初めて引く言葉は **12〜39秒（平均21秒）かかるが必ず成功**し、2回目は 0.0秒だった。
    **12秒で切っていたこちらが、成功するはずのものを失敗にしていた**
  - タイムアウトを 12秒 → **45秒**に。あわせて結果を10分キャッシュし、
    429/5xx のときだけ一度やり直すようにした
  - 画面にも「初めて調べる言葉は30秒ほどかかることがあります」と出す
  - **それでも不安定さは残る**（実測で4件中2件は成功、1件は0件、1件は失敗）。
    速い第二の経路が欲しければ **Google Books のAPIキー**を入れる（`backend/.env`）

- [x] **Step M: APIキーを入れて探す経路を組み直した**（2026-09-26）
  - Google Books のキーを `backend/.env` に設定し、実測で効果を確かめた
  - **書名検索を Google Books 先頭に**。国会図書館は初回12〜39秒だが、
    Google Books は **0.5〜1.1秒**で返る
  - **複合クエリが0件になる不具合を見つけて直した**。「こころ 夏目漱石」のように
    書名と著者を並べて打つと、クエリ全体を1つの塊として探していたため当たらなかった。
    空白で語に分け、すべての語が書名か著者に出てくることを条件にした
    （直す前 3/5 → 直したあと 6/7、当たったものは 0.5〜0.9秒）
  - **ISBN 引きを openBD → Google Books → 国会図書館 の順に**。
    実測で国会図書館だけが遅く（平均6.5秒）取りこぼしも多かった（6冊中2冊）。
    **平均 6.4秒 → 1.55秒**、表紙は8冊中7冊で付くようになった
  - 表紙URLは **`http://` を `https://` に書き換える**。Google Books は `http://` で
    返してくるので、Tailscale 越しの HTTPS では混在コンテンツとして弾かれる
  - 同じ ISBN を Google Books に二度聞かないようにした
  - テストを6件追加（計252件）

- [x] **Step N: `./run.sh serve` が必ず「権限がありません」で止まる不具合を修正**（2026-09-26）
  - 症状: operator が自分に設定されているのに、毎回 `sudo tailscale set --operator=...` を促して終了する
  - 原因は**権限ではなかった**。権限の有無を「使っていない出口を外せるか」
    （`tailscale serve --https=PORT off`）で試していたが、**出口がまだ無いとこの命令は
    `handler does not exist` で失敗する**。つまり初回は必ず失敗し、それを権限エラーと
    取り違えていた
  - 出力を見て `handler does not exist` なら権限ありと判定するように変更
  - 修正後に通しで確認: ビルド → API 起動（`.env` 読み込み）→ Tailscale の出口作成 →
    HTTPS 経由で画面・API・表紙の中継まで 200。他プロジェクトの 443 / 8443 の設定は無傷

### 画面の実装メモ

- **一覧のメタ表示は状態で変える**（デザイン指定）: 読書中 `57% · メモ 4` /
  読了 `著者 · ★★★★` / 積読 `著者`
- **一覧ペインは grid**。flex column にすると `overflow:hidden` の `.seg` が潰れる
- **⌘K の Esc の優先順**: パレット → 執筆モード。`ReportEditor` には `escActive` を渡して、
  パレットが開いているときは Esc を譲る
- **レポート執筆モードのキャレット保持**: メモ窓の項目・ツールバー・記法タブは
  `onMouseDown` で `preventDefault()` する。しないと押した瞬間に textarea の
  カーソルが外れて、どこに挿すか分からなくなる。直前の `selectionStart/End` を
  覚えておいて、そこに差し込む
- **表紙の画像はDBに入れる**: ファイルに置くと、バックアップが「reading.db 1つ」で
  済まなくなる。保存前に縮めるので、1冊あたり数十KBに収まる
- **表紙のURLに更新時刻を付ける**: `/api/books/1/cover` のままだと、画像を入れ替えても
  ブラウザが古いものを出し続ける。`?v=<時刻>` を付けて別のURLにしている
- **スマホとPCで画面を丸ごと分けた**: 3ペインとタブバー＋単一画面は情報の並べ方が違うので、
  1つの画面を伸び縮みさせるとどちらの設計にも合わないものになる。幅で `DesktopShell` と
  `MobileApp` を切り替え、**データの読み書き（`useAppData`）だけを共有**する
- **本を選んだら必ず見えるようにする**: 絞り込み中に本を追加・選択すると、一覧から
  消えて見える。`visibility.ts` の `filtersRevealing()` で「その本を隠している
  絞り込みだけ」を外してから選ぶ。本を選ぶ入口（追加画面・⌘K・メモの詳細・振り返り）は
  すべて `revealBook()` / `openBookById()` を通す
- **差し込みの規則は純粋関数に切り出してテストしてある**（`src/markdownInsert.ts`）。
  「ブロックは独立した段落にする（前後の改行が足りなければ補う）」「インラインは選択範囲を
  囲む。選択が無ければ仮の文字を入れて選んでおく」は、目で見て確かめにくく壊れやすいので、
  `npm test`（vitest）で19件の回帰テストを置いている
- **文字数は空白と記法の記号を除いて数える**（デザインの指定。`countCharacters()`）
- **本文は本が変わったときだけ流し込む**。毎回入れ直すと打っている最中に
  カーソルが先頭へ飛ぶ
- **引用の書体**はルート要素の `data-quote` 属性で切り替える（設定と連動）
- **書き出し（Markdown / CSV）はブラウザ側で組み立てる**。サーバーは関わらない。
  CSV は Excel で文字化けしないよう先頭に BOM を付ける
- **進捗は％で入れて％で見せる**（`進捗を記録` のパネル／シート、進捗行）。電子書籍は
  版や表示設定でページが変わるので、ページ数での記録は当てにならない。保存はこれまでどおり
  `page` で持ち、`frontend/src/progress.ts` の `pageFromPercent()` で換算する
  （**100％のときだけ総ページちょうど、あとは切り捨て**。四捨五入にすると10ページの本の
  99％が10になり、サーバーの「最後まで読んだら読了」で勝手に読了になる）
- **総ページが分からない本は 100 を分母にする**（`PERCENT_TOTAL`）。％を記録した時点で
  `total=100` を入れ、`page` に％をそのまま持つ。総ページを聞かずに全部の本で％記録
  できるようにしたもの。代わりに振り返りの「◯◯ページ読んだ」には、その本が
  100ページとして混ざる（ユーザーが選んだ割り切り）。ページ数が少ない本は、％の刻みが
  粗くなって入れた値と表示がずれる（10ページの本なら10％刻み）
- **記録のページは後から足せる・消せる**（PC版の記録一覧の「編集」にページ欄がある。
  空にして保存すると `page: null` で消える）。モバイル版に記録の編集はまだない
- **記録のページは空で開く**（`openNotePanel` / `NoteSheet`、プレースホルダは「ページ（任意）」）。
  進捗のページを既定で入れていたが、電子書籍は表示設定でページが変わるので、当てにならない
  数字が全部の記録に残る。入れたい人だけ打つ。一覧の並びの説明も、ページ付きの記録が
  1件も無ければ「ページ順」ではなく「新しい順」と出す（並び自体はサーバーが
  `page desc nulls last, created_at desc` で返す）
- **記録のパネルは「メモ」で開く**（PC版の `openNotePanel` / モバイルの `NoteSheet`）。
  開く入口が「メモを書く」なので、引用で開くと **本文（必須）と「自分のメモ（任意）」の
  2欄**が出て、メモのつもりで任意の欄に書いた人が保存できない（ボタンが disabled の
  まま）ところで詰まる。引用はセグメントで1クリック。それでも任意の欄だけ書いた
  ときのために、保存できない理由を一行出す
- **「次に読む本」は本の詳細にも出す**（PC版・モバイル版とも、メモ・引用の前）。
  読了ダイアログは根拠と距離で絞り込んで3冊ずつ出し直すのに対し、詳細のほうは
  絞り込みを持たず `per_page=20` で**設定してある候補を全部**並べる。読み終えた
  瞬間にしか候補を見られないと、積読の本で「読んだら次はこれ」を確かめられないため。
  候補を1件も設定していない本には一行だけ「まだ決めていません」と出す（`configured`）。
  データの出し入れは `useBookSuggestions`（PC版・モバイル版で共有）、カードの見た目は
  `components/SuggestionCard`（3列）と `mobile/SuggestionRow`（1列）に分けてあり、
  読了ダイアログ・読了シートも同じものを使う
- **おすすめ一覧**（2026-10-03、**デザイン外の仮置き**）。PC版はレールの「おすすめ」、
  モバイル版は**5つ目のタブ**「おすすめ」（デザインのタブバーは4つ。デザインが届いたら合わせる）。
  設定してある候補を全部、**持っている本ごとに**「『◯◯』を読み終えたら」のまとまりで並べる。
  PC版は一覧ペインで本を選ぶとその本の候補だけになり、「この本を開く」で本棚のその本へ移る
  （モバイル版は見出しをタップ）
  - **絞り込みは書名と紹介文（理由の一言）だけを見るキーワード検索**（ユーザーが決めた）。
    著者名・どの本の候補かは見ない。空白区切りは AND、全角半角・大小文字・ひらがなカタカナは
    区別しない。取ってきた一覧の中だけで探し、外部サービスにも Claude にも問い合わせない
    （`suggestionSearch.ts`）。分野やキーワードで**新しく本を探す機能は作らない**ことにした
  - 同じ本が何冊もの本の候補に出る（「予想どおりに不合理」は6冊ぶん）。1か所で積読に足したら、
    **本棚にある ISBN の候補は全部「追加済み」**にして見せる（サーバーは押した候補にしか印を
    付けないので、画面側の `markShelved` で補う）。「興味なし」は ISBN で覚えるので、
    同じ本はほかの本の候補からもまとめて消える
  - データの出し入れは `useAllSuggestions`（PC版・モバイル版で共有）。画面を開くたびに取り直し、
    閉じている間は読まない
  - 表紙に `loading="lazy"` を付けた（全部の画面に効く）。数百冊を並べると、書影の中継
    （国会図書館。混むと 429）にまとめて問い合わせてしまうため
- **カテゴリとタグはデザイン 8b「形で分ける」**（`Notes Category Tag.dc.html`、README の I・7a/7b）。
  カテゴリは塗り（`.tag-neutral`、絞り込みのチップは `.cat-chip`）、タグは枠なしの `#文字`。
  カテゴリごとの色は作らない。部品は `components/GenreChips`（カテゴリ）と `components/HashTags`（タグ）で、
  PC版・モバイル版が共有する
  - 本棚: 状態のセグメント → カテゴリのチップ（`すべて` ＋6つ。モバイルは1行で横スクロール）→
    「タグ」行（よく使う8つを `#文字`。選んでいるものは下線。PC版のみ）。3つの条件は同時に効く。
    判定は `visibility.ts`（`isVisible` / `filtersRevealing` / `topTags`）。0件なら「このカテゴリの本はありません。」
  - 行: 書名 → 状態のメタ（文字）→ `[カテゴリ]` ＋ `#タグ`
  - 本の詳細: `[状態][カテゴリ ▾]` → 書名 → 著者 → タグ行。▾ でカテゴリの選択肢が開く（モバイルはシート）。
    `#タグ` を押すと本棚をそのタグだけで絞り込む（モバイルは本棚に戻って「#タグ で絞り込み中 ×」を出す）。
    「＋ タグ」で入力（Enter で追加、Esc か「完了」で終わる。日本語入力の確定の Enter では足さない）、
    編集中はタグに × が付いて押すと外れる。入力欄はこれまでのタグを補完に出す（デザイン外の足し算）
  - 追加画面はデザインに無いので、カテゴリは詳細と同じ選択肢を置いた（既定はその他）
- **一覧ペインは畳める**（レール下の「隠す / 出す」・⌘B / Ctrl+B）。`.panes` に
  `panes-solo` を足して `display:none` にするだけで、**要素は残す**（戻したときに
  絞り込みも選択もそのまま）。畳んでいる間は `.detail` の幅を 1100px まで広げる

### Step 5 の詳細（次に読む本）

**画面はデザインで確定している**（`Notes Next Book.dc.html` #5a。README の「G. 次に読む本」が正本）。
要点だけ:

- **出るタイミング**: 本が読了になった瞬間に**一度だけ**。閉じたら再表示しない
- パネル 880px、背景 `color-mix(--color-neutral-900 50%)`
- ヘッダー: `読了 · 23日間 · 引用・メモ 6件` ＋ 「『書名』を読み終えました」＋ ★評価
- **条件の行**: 根拠トグル3つ（引用・メモ `ph-quotes` / 評価 `ph-star` / 分野 `ph-tag`。
  **最低1つはON**）＋ 距離のセグメント（近い本 / 少し離れた本 / 両方）＋ [出し直す]
- **提案カード3列**: 表紙72×104 ＋ 書名 ＋ 著者 ＋ **理由は一言** ＋ 根拠ラベル
  （引用・メモ由来はマゼンタ `--color-accent-2-700`、それ以外はシアン `--color-accent-700`）
  - [積読に追加] → `.tag-accent`「✓ 積読に追加しました」＋ [取り消す]
  - [興味なし] → そのカードを次の候補に差し替え、**以後の提案から外す**（`dismissedBookIds`）
- フッター: 左に根拠の要約、右に [レポートを仕上げる → 執筆モード] [閉じる]
- 候補の形: `{ bookRef, basis: 'note'|'rating'|'tag', distance: 'near'|'far', reason }`
- 「出し直す」は同じ条件で**次の3冊**（ページング）。条件を変えたら先頭から

> **README は「推薦エンジンは対象外」と明記している。**候補をどう作るかは実装側の判断で、
> 未決定。選択肢は2つ:
> 1. **国会図書館サーチだけで作る**（APIキー不要）: 読了本の分野・著者を鍵に NDL を引く。
>    「距離」は 同じ分野=近い / 隣接する分野=少し離れた とする。
>    ただし「引用・メモから」の根拠はキーワード抽出止まりで精度は落ちる
> 2. **Claude API を使う**（下記）: 引用・メモの中身を読めるので、3つの根拠をそのまま実現できる

### Claude API を使う場合の詳細

**起動の流れ**

1. `routers/books.py` の `update_book` にある `TODO(Step 5)` の位置（**読了になった瞬間だけ通る分岐**）で、`SuggestionJob(status="pending")` を作って commit
2. `BackgroundTasks` に生成処理を積んで、API はすぐ応答を返す
3. バックグラウンド処理では**リクエストのセッションを使い回さず** `SessionLocal()` で新しいセッションを開く（リクエストが終わるとセッションは閉じられるため）
4. 成功したら `Suggestion` を保存して `status="done"`、失敗したら `status="failed"` + `error`
5. 画面は `GET /api/books/{id}/suggestions` を**2秒間隔でポーリング**。`pending` の間は「提案を作成中」、`failed` なら「提案に失敗しました」＋再試行ボタン。30回（約60秒）で打ち切って「時間がかかっています」を出す

**SDK の使い方（2026-09時点の公式ドキュメントで確認済み。以下を優先する）**

- `pip install anthropic` / `client = anthropic.Anthropic()` — `ANTHROPIC_API_KEY` は環境変数から自動で読む。**コードに直書きしない**（`backend/.env` に置き、`uvicorn --env-file .env` で渡す）
- モデル ID は **`claude-opus-5`**（日付サフィックスは付けない）。料金は入力 $5 / 出力 $25 per 1M tokens
- **JSON は `client.messages.parse()` で受け取る**。Pydantic モデルを `output_format=` に渡すと、検証済みインスタンスが `response.parsed_output` に入る。旧仕様の「JSONのみ返すよう指示して手でパース、失敗したら保存しない」は**不要なので置き換える**

```python
class SuggestedBook(BaseModel):
    title: str
    author: str | None = None
    isbn: str | None = None
    reason: str

class SuggestionList(BaseModel):
    books: list[SuggestedBook]

response = client.with_options(timeout=60.0, max_retries=2).messages.parse(
    model="claude-opus-5",
    max_tokens=16000,
    messages=[{"role": "user", "content": prompt}],
    output_format=SuggestionList,
)
if response.stop_reason == "refusal":       # content を読む前に必ず確認する
    raise RuntimeError("モデルが応答を拒否しました")
suggestions = response.parsed_output.books
```

- **`thinking` パラメータは渡さない**。Opus 5 は既定で adaptive thinking が動く。`budget_tokens` を書くと 400 エラーになる
- **タイムアウトとリトライ**: SDK の既定タイムアウトは10分でバックグラウンドジョブには長すぎる。`with_options(timeout=60.0, max_retries=2)` で明示する（Python は**秒**単位）。SDK は 408/409/429/5xx と接続エラーを既定2回まで自動リトライする
- **例外は具体的なものから順に捕まえる**（`RateLimitError` は `APIStatusError` の、`APITimeoutError` は `APIConnectionError` のサブクラス。順番を間違えると細かい分岐に落ちない）

```python
except anthropic.APITimeoutError:    error = "応答が時間内に返りませんでした"
except anthropic.RateLimitError:     error = "APIの利用制限に達しました。少し待って再試行してください"
except anthropic.APIStatusError as e: error = f"APIエラー（{e.status_code}）"
except anthropic.APIConnectionError: error = "APIに接続できませんでした"
```

  捕まえたら `SuggestionJob.status = "failed"` と上のメッセージを保存する。広い `except Exception` 一発にはしない（ただし最後の保険として1つ置き、`error` に型名だけ残すのは可）
- Opus 5 にはサーバサイドの refusal fallback（beta `server-side-fallback-2026-07-01` + `fallbacks="default"`）があるが、これは `client.beta.messages.create` 用で `messages.parse()` との併用は公式ドキュメントに記載がない。**本アプリは構造化出力の確実さを優先して `parse()` を使い、fallback は使わない**

**AI に渡す入力の上限**（プロンプトが膨らむと遅く・高くなるので必ず切る）

| 項目 | 上限 |
|---|---|
| 読了本 | 読了日の新しい順に **20冊** |
| 1冊あたりのノート | **2件**まで（新しい順） |
| ノート1件の本文 | **400文字**（超えたら先頭400文字＋`…`） |
| 本のタイトル・著者 | それぞれ 100文字 |
| プロンプト全体 | **8,000文字**を目安に、超えたら古い本から落とす |
| 出力 | 2〜3冊 / `max_tokens=16000` |

## 7. 設計判断メモ

- **自作を選んだ理由**: 最優先が自動化・連携で、入力はPCのみ。Notion/GoodNotes だと結局外部スクリプトとの二重管理になるため、既存スタックで一体化した方が素直
- **ノートを SQLite に保存**: 本とノートの紐づけが容易、バックアップがDB1ファイル、提案時にAIへ渡すデータを一括取得しやすい
- **提案は裏で実行**: AI応答に数秒〜十数秒かかるため、読了操作のレスポンスを待たせない
- **models と schemas を分離**: DBの形とAPIの入出力を独立させ、片方の変更がもう片方を壊さないようにする
- **読了日は残す（明示したときだけ消す）**: 状態を「読書中」に戻しても `finished_on` は保持する。**一度読了した日付は記録として残したい。再読のとき「前回いつ読んだか」が見えるのが自然**だから。消したいときだけフォームで空にして送る
- **日時はすべて JST・naive で保存**: 本来はUTCで持って表示時に変換するのが定石だが、**日本国内からしか使わない個人アプリなので、`sqlite3` で直接DBを覗いたときにそのまま読める方を優先した**。UTC 保存だと `finished_on`（JST の日付）と同じ行で9時間ずれ、「読了日は25日なのに更新日時は24日」のような混乱が起きる。将来どうしても必要になったら `timeutil.py` だけ直せばよい状態にしてある
- **提案の進行状態は専用テーブル**: 提案の配列だけを返す設計では、`[]` が「生成中」なのか「失敗して0件」なのか区別できず、画面が永久に「作成中」を出し続ける。`SuggestionJob` で `pending` / `done` / `failed` を明示し、失敗時は理由と再試行ボタンを出せるようにする
- **フロントは開発と日常利用で配信方法を変える**: 開発中はホットリロードが効く Vite dev server、日常利用は `npm run build` した静的ファイルを FastAPI から配信してプロセスを1つにする。毎回2つ立ち上げるのは個人用途では面倒すぎる
- **一覧の既定の並びを `updated_at desc` → `created_at desc` に変更**: ★や状態を変えるたびにその本が先頭へ飛んでしまい、一覧の位置が定まらず操作しづらい。`created_at` なら並びが動かない。「読了タブだけは読了日順で見たい」という要求はあるので、`sort` クエリで切り替えられるようにし、フロントが読了タブでだけ指定する
- **enum は値で保存**: 既定の「名前で保存」だと DB に `'READING'`、API に `'reading'` が出て見比べたときに混乱する。`values_callable` で値を保存させる。実データがまだ無いうちに直す
- **WAL と foreign_keys**: Step 5 で裏側の書き込みと画面操作が重なるため WAL にする。SQLite は外部キーが既定で無効なので、Step 4 の cascade を効かせるには接続ごとに `foreign_keys=ON` が要る
- **ISBN の正規化を Pydantic の前段で行う**: 正規化をルーター側に置くと、`max_length` などの検証が**先に**走って正規化前の文字列を弾いてしまう。`BeforeValidator` に置けば「入力を整えてから検証する」順になり、ハイフン付きも10桁も素直に通る
- **ISBN 検索は openBD → Google Books → 国会図書館 の順**: 当初は国会図書館を最優先にしていたが、実測すると国会図書館は平均6.5秒かかるうえ6冊中2冊しか持っていなかった（openBD 5冊/0.04秒、Google Books 6冊/0.52秒）。APIキーを入れたことで Google Books が使えるようになったので、速い順に並べ替えた
- **書影を自前のAPIで中継する**: 国会図書館サーチのサムネイルは `Referer` が無いと 403 を返す。ブラウザから直接読ませると必ず失敗するので、サーバー側で Referer を付けて取り、`/api/covers/{isbn}` として配る。ブラウザには1日キャッシュさせて毎回取りに行かない
- **ノートの見出しは任意**: 「第3章のここが刺さった」のような一行メモに毎回見出しを付けさせると書かなくなる。本文だけ必須にした
- **デザインシステムを正本にして Tailwind をやめた**: ハンドオフの README が「hex・フォント名・px を
  トークンが持っているものは直書きするな、DS のクラスを使え」と明示している。Tailwind のユーティリティと
  トークンを混ぜると、どちらが正なのか分からなくなる
- **ISBN 検索は openBD → Google Books → 国会図書館 の順**: 当初は国会図書館を最優先に
  していたが、実測すると平均6.5秒かかるうえ6冊中2冊しか持っていなかった。速い順に並べ替えて
  平均 6.4秒 → 1.55秒 になった。国会図書館は古い本の受け皿として最後に残す
- **書名検索は打った語ごとに当たりを見る**: 「こころ 夏目漱石」のように書名と著者を並べて
  打つことがある。全体を1つの塊として探すと当たらないので、空白で語に分け、**すべての語が
  書名か著者のどちらかに出てくること**を条件にする。これを直す前は複合クエリが0件だった
- **書影を自前のAPIで中継する**: 国会図書館のサムネイルは `Referer` が無いと 403。ブラウザの
  `<img src>` にはその Referer が付かないので、`/api/covers/{isbn}` が付け直して取る
- **検索結果はこちらで絞り込む**: 国会図書館サーチは**関連度順ではなく五十音順**で返し、
  クエリと関係の薄い本も混ぜてくる。書名・著者との一致を見て並べ直し、一致しないものは落とす。
  **著者の一致をいちばん強く見る**のは、人名で探したときに「その人が書いた本」より先に
  「その人について書かれた本」が並ぶと使いものにならないため
- **書名検索のタイムアウトは45秒**: 国会図書館サーチのタイトル検索は**必ず成功するが、
  初回だけ極端に遅い**。実測すると、初めて引く言葉は **12〜39秒（平均21秒）**、
  同じ言葉の2回目は **0.0秒**（向こう側でキャッシュしている）。
  以前は12秒で切っていたため、**成功するはずのリクエストを失敗にしていた**（5件中3件）。
  短く切っても速くはならないので、待つ方に倒してある
- **検索結果は10分だけ覚えておく**（`booklookup._cache`）。打ち直すたびに外へ出ていくと、
  向こうの混雑に拍車をかける。失敗は覚えない（復旧しても出てこなくなるため）
- **429 や 5xx は一度だけやり直す**。これらはすぐ返ってくるので安い。
  時間切れはやり直さない（向こうは処理を続けているので、待ち直しても同じだけ待つ）
- **書名で見つかったら著者では引き直さない**: 往復を増やさないため、
  書名がクエリで始まる本が見つかった時点で打ち切る
- **ノートは引用とメモを別物として持つ**: デザインが両者を別の見た目・別の色（引用はマゼンタ）で
  扱い、ページ番号と引用への補足を持つため。旧 `title`/`body` では表現できない
- **一覧ではレポート本文を返さない**: 長くなるので `has_report` だけ返し、本文は詳細で取る
- **「次に読む本」を手で設定する方式にした**: 実行時に推薦を作ろうとすると、
  外部カタログ頼みになって遅く（国会図書館サーチは実測 0.1〜17秒）、理由も機械的になる。
  読み終わった直後に出す画面で数秒待たせるのは筋が悪い。**1冊につき3件を先に決めておけば、
  ダイアログは即座に開き、理由も自分の言葉で書ける**。候補を考えるのは Claude との
  相談でやればよく、アプリが API を持つ必要はない
- **「未設定」と「0件」を分ける**: どちらも空の配列だが、意味が違う。混ぜると
  「条件に合う候補がありません」と出て、**設定すれば出ることが伝わらない**。
  `configured` で分けている
- **外部検索の失敗を「0件」と混同しない**: 国会図書館サーチは叩きすぎると 429 を返し、
  混むとタイムアウトする。これを空配列にすると、画面が「その本はありません」と
  嘘をつく。`SearchUnavailable` を投げて **503** にし、文言を分けた
- **Alembic をまだ入れない**: 実データが無いうちは「DBを消して作り直す」で足りる。ノートが溜まって消せなくなった時点で導入する

## 8. 進め方の約束

- ユーザーは学習中。各 Step で**新しく出てきた概念を短く説明**し、動かし方と確認手順を添える
- 1 Step ずつ、動く状態で区切る。判断が必要な点は実装前に確認する
- 依頼された範囲を超えた機能追加・抽象化はしない。いま必要な最小限にとどめる

### テスト方針

- pytest + FastAPI TestClient。`backend/tests/` に置き、`cd backend && ../.venv/bin/pytest -q` で走る
- **本番の `reading.db` を汚さない**。テスト用に in-memory SQLite（`sqlite://`）を `StaticPool` で作り、`app.dependency_overrides[get_db]` で差し替える

```python
# conftest.py の骨子
engine = create_engine(
    "sqlite://",                                   # メモリ上のDB
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,                          # 接続を1つに固定しないとテーブルが消える
)
configure_sqlite(engine)                           # 本番と同じ PRAGMA を適用する
Base.metadata.create_all(bind=engine)
app.dependency_overrides[get_db] = _override_get_db
```

- **ハードコードでテストを通すこと、何もアサートしないテストは禁止**。実装の内部構造ではなく、API の入出力とDBの中身を検証する
- モックは最小限に。外部 I/O（Google Books / Claude API）だけ差し替え、DB は本物を使う
- テスト名は**何を検証しているか読んで分かる**ものにする（`test1` は不可）
- Step 1.5 で最低限そろえる回帰テスト:
  - `ハイフン付きISBNを登録すると13桁に正規化されて保存される`
  - `ISBN-10を登録するとISBN-13に変換されて保存される`
  - `チェックディジットが合わないISBNは422になる`
  - `ISBNに空文字を送るとnullとして保存され2冊目も登録できる`
  - `同じISBNを2回登録すると409になる`
  - `titleにnullを送ると409ではなく422になる`
  - `ratingに6を送ると422になる`
  - `読了にすると読了日に今日（JST）が入る`
  - `読書中に戻しても読了日は残る`
  - `読了日にnullを明示すると読了日が消える`
  - `created_atが現在のJST時刻と一致する`（UTC保存なら9時間ずれて落ちること）
  - `statusはDBに小文字の値で保存される`（生SQLで確認）
  - `一覧は登録が新しい順に返り、statusで絞り込める`
