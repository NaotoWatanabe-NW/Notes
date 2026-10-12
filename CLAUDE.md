# CLAUDE.md

このリポジトリで作業するときの地図と約束ごと。毎セッションの最初に読む。
仕様の正本は `docs/SPEC.md`。ここには要点と入口だけを書く。

## 1. このアプリとドキュメントの所在

- 個人用の読書記録・学習ノートの Web アプリ。本の登録（ISBN・書名から自動取得）、状態・進捗・評価、引用とメモ、本ごとの読書レポート（Markdown）、読了時の「次に読む本」、キーワードのおすすめ、振り返りを扱う。
- PC は3ペイン、幅820px以下のスマホはタブバーの単一画面。認証は無いので、tailnet（Tailscale）の中だけで使う。
- 入口:
  - `docs/SPEC.md` … いまの仕様・構成・データモデル・API・実装の経緯（正本）
  - `docs/design/` … 設計書 `NNNN-名前.md`。実装の前に書く（§8）
  - `docs/systemd-service.md` … 母艦の常駐（systemd ユーザーサービス `notes-web`）
  - デザインの正本: `Notes App Base Design/design_handoff_notes_reading_app/README.md`（画面仕様）と `_ds/broadsheet-…/styles.css`（トークン）。**触らない**

## 2. 技術スタックと起動構成

- バックエンド: Python / FastAPI / SQLAlchemy 2系 / Pydantic v2 / SQLite（WAL）。Pillow（表紙）、PyYAML（レポートの frontmatter）、httpx（外部 API）
- フロントエンド: React 19 / TypeScript / Vite 8 / react-markdown。**Tailwind は使わない**
- Python の仮想環境はリポジトリ直下の `.venv/` 1つ（git 管理外）。frontend は npm
- DB は `backend/reading.db`。`sqlite:///./reading.db` は作業ディレクトリ基準なので、uvicorn は必ず `backend/` で起動する（`run.sh` はそうしている）

開発モード（`./run.sh`）: 画面は Vite が配信し、`/api` を FastAPI へ中継する
```
ブラウザ → Vite dev server 0.0.0.0:5765 → (/api を中継) → FastAPI 127.0.0.1:8765 → reading.db
```
日常利用（`./run.sh start` / `serve` / 常駐）: FastAPI 1プロセスが画面も配信する
```
start : ブラウザ → FastAPI 0.0.0.0:8765            （同じ LAN から見える）
serve : ブラウザ → tailscale serve (HTTPS) → FastAPI 127.0.0.1:8765   （tailnet 内のみ）
        / は frontend/dist（SPA）、/api/... は API
```

## 3. ディレクトリ地図

```
Notes/
├── run.sh                      起動・テスト・セットアップの入口（§5）
├── docs/
│   ├── SPEC.md                 仕様・引き継ぎ（正本）
│   ├── systemd-service.md      母艦の常駐（notes-web）の手順
│   └── design/                 設計書（§8）
├── books.txt                   本のメモ（用途の記載なし。アプリは読まない）
├── reports/                    読書レポート・テーマノート・著者ノート（git 管理外。§4）
├── backup/                     DB の写し（git 管理外。drop_unused_columns.py も消す前にここへ取る）
├── scripts/                    一回限りのスクリプト（strip_report_frontmatter.py / create_notes.py / drop_unused_columns.py）
├── Notes App Base Design/      デザインの正本（触らない）
├── .claude/
│   ├── agents/                 サブエージェントの定義（§9）
│   └── skills/                 next-book-suggestions / keyword-suggestions（§9）
├── backend/
│   ├── requirements.txt        Python の依存
│   ├── pytest.ini              テストは tests/ 以下
│   ├── .env.example            .env にコピーして使う（GOOGLE_BOOKS_API_KEY）。.env と reading.db は git 管理外
│   ├── app/
│   │   ├── main.py             入口。lifespan（テーブル作成・列追加・テーマ・著者ノートの更新の開始）、ルーター登録、SPA 配信
│   │   ├── database.py         engine・セッション・get_db・SQLite の PRAGMA・add_missing_columns
│   │   ├── models.py           DB のテーブル定義（Book / Note / Reading / BookCover / Tag / Settings / Suggestion / Topic …）
│   │   ├── schemas.py          API の入出力の型と入力チェック（ISBN の正規化もここ）
│   │   ├── report_store.py     読書レポート（reports/<id>-<タイトル>.md）の読み書き・索引・ゴミ箱
│   │   ├── theme_store.py      テーマノートとハブへの一覧の差し込み。ThemeWatcher（5秒ごと）
│   │   ├── author_store.py     著者ノートとハブへの一覧の差し込み（部品は theme_store を使う）
│   │   ├── booklookup.py       ISBN・書名から本を探す（openBD / Google Books / 国会図書館）。検索結果の10分キャッシュ
│   │   ├── isbn.py             ISBN の正規化と検査（ハイフン除去・10→13桁・Kindle の ASIN を判定）
│   │   ├── covers.py           手で入れる表紙を 600×900 以内の JPEG に縮める
│   │   ├── timeutil.py         now_jst / today_jst（日時はここ経由で取る）
│   │   ├── settings_store.py   設定の1行を読む（無ければ既定値で作る）
│   │   └── routers/
│   │       ├── books.py        本の CRUD・読了時の処理・表紙（/api/books）
│   │       ├── notes.py        引用・メモ（/api/books/{id}/notes, /api/notes）
│   │       ├── lookup.py       ISBN・書名の検索と書影の中継（保存はしない）
│   │       ├── suggestions.py  次に読む本（本ごとの候補・積読への追加・興味なし）
│   │       ├── topics.py       キーワードのおすすめ（/api/topics）
│   │       ├── recommendations.py  おすすめ一覧（本棚に無い本を1列に）
│   │       ├── reviews.py      振り返り（期間ごとの集計）
│   │       ├── tags.py         タグの一覧
│   │       └── settings.py     設定
│   └── tests/                  conftest.py（共通の準備）・fixtures_lookup.py（外部応答の実例）・test_*.py
└── frontend/
    ├── package.json            scripts: dev / build / lint / test（§5）
    ├── vite.config.ts          host 0.0.0.0。/api を API_PORT の FastAPI へ中継
    ├── index.html, tsconfig*.json, .oxlintrc.json
    └── src/
        ├── main.tsx            エントリ。index.css を読む
        ├── App.tsx             幅820px以下は mobile/MobileApp、それ以外は DesktopShell
        ├── DesktopShell.tsx    PC版（3ペイン・⌘K・執筆モード）
        ├── useAppData.ts       本・記録・タグ・設定の読み書き（PC版・モバイル版で共有）
        ├── useBookSuggestions.ts / useRecommendations.ts   次に読む本・おすすめ一覧の読み書き
        ├── api.ts              /api への fetch と型をここにまとめる
        ├── types.ts            画面と絞り込みの型
        ├── visibility.ts       絞り込みの判定（isVisible / filtersRevealing / topTags）
        ├── progress.ts         進捗の ％ ⇄ ページの換算
        ├── recommendations.ts  おすすめの見せ方の小道具
        ├── markdownInsert.ts   執筆モードの差し込み規則（純粋関数）
        ├── export.ts           Markdown / CSV の書き出し（ブラウザ側で組み立てる）
        ├── isbnLike.ts         検索欄の文字列が ISBN らしいかの判定
        ├── *.test.ts           vitest（上の純粋関数のテスト）
        ├── components/         PC版の部品（Rail / LibraryPane / BookDetailView / ReportEditor / CommandPalette など）
        ├── mobile/             モバイル版（MobileApp が切り替え。TabBar。画面はデザイン番号 7a〜7i に対応）
        └── styles/
            ├── broadsheet.css  デザインのトークンの正本のコピー（触らない）
            ├── app.css         PC版の見た目（トークンを使う）
            └── mobile.css      モバイル版の見た目（同上）
```

## 4. データの持ち主（DB と Markdown の境界）

> 実装済み（2026-10-12）。詳細は [0001 保存の境界](docs/design/0001-storage-boundary.md) と [0002 著者ノート](docs/design/0002-author-notes.md)。

- **原則: 同じデータを2か所に保存しない。持ち主は1か所。**
- **DB**（`backend/reading.db`、git 管理外）: 書誌・状態・進捗・評価・日付・タグ・引用/メモ・読了記録・表紙画像・次に読む本・キーワードのおすすめ・興味なし・設定
- **Markdown**（リポジトリ直下の `reports/`、git 管理外。Obsidian の vault から symlink で開く。場所は環境変数 `NOTES_REPORTS_DIR` で変えられる）
  - 読書レポート本文: `reports/<book_id 4桁>-<タイトル>.md`
    - frontmatter でアプリが持つのは `type`・`book_id`・`updated` だけ
    - 正の鍵は `book_id`。ファイル名は人が読むための飾りで、タイトルを直しても改名しない
    - 同じ `book_id` のファイルが複数あれば mtime が最新のものを使う。保存は主の1つにだけ書き、他は上書き・削除しない
  - テーマノート: `reports/themes/*.md`（タグごと。**ユーザーが作る**。いまあるタグと本棚の著者のノートは `scripts/create_notes.py` で一括で作れる。0003）
  - 著者ノート: `reports/authors/*.md`（レポートのある著者はアプリが自動で作る。ユーザーが手で作ってもよい。0002）
  - ハブ `reports/authors/著者一覧.md`（アプリが作る。ノートの無い著者を冊数つきで並べる）
- **ビュー（例外）**: テーマノート・著者ノート・ハブ（`reports/themes/テーマ一覧.md`・`reports/authors/著者一覧.md`）の `<!-- notes:books:start -->` 〜 `<!-- notes:books:end -->` の間は、DB から数秒ごとに作り直す一覧。アプリは読み戻さない。**手で編集しない**（マーカーの外は自由に書いてよい）
- **一覧の更新**: アプリの起動中、`ThemeWatcher` が5秒ごとに書き直す（Obsidian でノートを作った・タグを書き換えたといった API を通らない変化も拾う）。止めるときは `NOTES_THEMES_WATCH=0`（テーマと著者の両方）か `NOTES_AUTHORS_WATCH=0`（著者ノートだけ）
- リンクは Wikiリンク（`[[ ]]`）ではなく**相対 Markdown リンク**
- 書き込み: `report_store.write_lock`（flock。`reports/.write.lock`）の中で `write_atomic`（tmp に書く → fsync → `os.replace`）。読み手はロックを取らない
- 削除はファイルを消さず `reports/.trash/` へ移す
- **旧い複製キーの移行**: 2026-10-12 より前の版が書いたレポートには、書誌項目（title / author / isbn / genre / status / rating / started_on / finished_on / tags）が frontmatter に残っている。既存ファイルからは `scripts/strip_report_frontmatter.py` で一度だけ取り除く（既定は下見。`--apply` で書く。本文は変えない）。**新しいコードをデプロイして再起動したあとに流す**（先に流すと、旧コードが次の本の更新でキーを書き戻す）。DB の `books.report_md` 列（移管前の本文の凍結コピー）は `scripts/drop_unused_columns.py` で消す（アプリを止めて一度だけ流す。既定は下見、`--apply` で消す。手順は `systemctl --user stop notes-web` → 下見（引数なし）→ `--apply` → `systemctl --user start notes-web`。消す前の写しは `backup/`。0004）
- `reports/`・`reading.db`・`backup/`・`backend/.env` はコミットしない（`.gitignore`。この repo は public）

## 5. よく使うコマンド

```bash
./run.sh                 # 開発モード。API :8765 と画面 :5765 を同時に起動（保存で再読み込み）
./run.sh start           # ビルドして FastAPI 1プロセスで配信（0.0.0.0。同じ LAN から見える・認証なし）
./run.sh serve           # Tailscale の HTTPS で配信（127.0.0.1 で待ち受け。tailnet 内のみ）
./run.sh test            # pytest と tsc -b（vitest と lint は含まない）
./run.sh setup           # 依存のインストール（初回・依存を足したとき）
API_PORT=8010 ./run.sh   # ポートを変える（WEB_PORT / TS_PORT も）。使用中なら止まる。kill はしない

cd backend && ../.venv/bin/pytest -q     # バックエンドのテスト
cd frontend && npm test                  # フロントのテスト（vitest run）
cd frontend && npm run build             # tsc -b && vite build（frontend/dist を作る）
cd frontend && npm run lint              # oxlint
```

- 母艦では systemd `notes-web` が常駐している。`./run.sh` を使う前に `systemctl --user stop notes-web` を実行する。コードの更新を反映するのは `systemctl --user restart notes-web`（画面のビルドも走る）
- `./run.sh serve` は終了時に自分の `tailscale serve` の出口（:8765）を消す。常駐の出口も消えるので、終わったら `tailscale serve --bg --yes --https=8765 http://127.0.0.1:8765` で戻す（`docs/systemd-service.md`）。`tailscale serve reset` は他の設定まで消すので使わない

## 6. 守る約束

**データ**
- 日時: DB の日時は JST・naive（タイムゾーンなし）。`timeutil.now_jst()` / `today_jst()` で取る（レポートのファイル側の時刻は `report_store` が直接取る）
- ISBN: DB には常にハイフンなし13桁。正規化は `schemas.py` の `BeforeValidator` で、検証より前に行う
- enum は値（`reading` など）で保存する
- 読了の判定と日付の補完（`page >= total` で読了、開始日・読了日の自動入力）は `books.py` の `_apply_progress_rules()` だけで行う。フォームから送られた日付は上書きしない
- 読了日 `finished_on` は一度入ったら残す。消すのは `null` を明示的に送ったときだけ
- PATCH は「項目を送らない＝変更しない、`null` を送る＝空にする」。ただし title / status / page / kind / text は NOT NULL なので `null` は 422
- DB のスキーマは作り直さない（実データがある）。足せるのは null を許す列だけ（`database.add_missing_columns`）。型の変更・削除・NOT NULL の追加が要るときは、先に Alembic の導入をユーザーに相談する
- エラーの返し分け: 入力の形が不正 → 422 ／ ISBN 重複 → 409 ／ それ以外の制約違反 → 400 ／ 対象が無い → 404
- 外部検索の失敗を「0件」と混同しない（503 を返し、画面は「見つからない」と別の文言を出す）
- アプリは Claude API などの AI API を呼ばない。「次に読む本」の候補は手で（スキルで）設定する

**API と配信**
- `main.py` では API のルーターを先に登録し、SPA 配信のキャッチオール（`/{full_path:path}`）を最後に置く。逆にすると `/api/...` を飲み込む。存在しない `/api/` は 404 を返す（index.html は返さない）
- `index.html` は `Cache-Control: no-cache`。`assets/` はファイル名にハッシュが付くのでキャッシュしてよい（古い index.html が残ると画面が空になる）
- 一覧では `report_md` を返さない（長いため）。詳細だけが返す。有無は `has_report`
- 本の検索: ISBN は openBD → Google Books → 国会図書館の順、書名は Google Books → 国会図書館の順。Google Books は `GOOGLE_BOOKS_API_KEY` が無いと問い合わせない

**フロントエンド**
- 見た目（色・余白・角丸・影）は `styles/broadsheet.css` のトークンだけを使い、hex や px を直書きしない。配置は左揃え（Broadsheet の方針）。Tailwind は使わない
- PC版（`DesktopShell`）とモバイル版（`mobile/MobileApp`）は画面の組み立てを分ける。共有するのはデータ層（`useAppData.ts` と `use*.ts`）だけ。切り替えは `App.tsx` の幅 820px
- 通信は `api.ts` にまとめる。コンポーネントから直接 `fetch` しない
- 本を選ぶ入口（追加画面・⌘K・メモの詳細・振り返り）は、絞り込みで隠れていれば絞り込みを外してから開く（`DesktopShell.tsx` の `revealBook()` / `openBookById()`。判定は `visibility.ts` の `filtersRevealing`）

**進め方**
- ユーザーは学習中。新しい概念（ライブラリや仕組み）は短く説明し、動かし方と確認手順を添える
- 依頼された範囲を超える機能追加・抽象化はしない。判断が要る点は実装の前に確認する
- ハードコードでテストを通さない（§7）

## 7. テスト方針

- バックエンドは pytest + FastAPI TestClient（`backend/tests/`）。API の入出力と DB の中身を見る。実装の内部構造は見ない
- **本番の `reading.db` を汚さない。** `conftest.py` の `db_engine` が in-memory SQLite（`sqlite://`）を `StaticPool` で作り、`configure_sqlite` で本番と同じ PRAGMA を入れる。`client` は `app.dependency_overrides[get_db]` で差し替え、`TestClient(app)` は `with` を付けない（lifespan を動かさない）
- `conftest.py` の autouse fixture が、全テストで `NOTES_REPORTS_DIR` を一時ディレクトリに、`NOTES_THEMES_WATCH=0` にする。検索キャッシュもテストごとに消す
- レポートは実ファイルで読み書きする（ファイル I/O が機能の本体なので、モックしない）
- **外部 I/O だけ差し替える**: `test_lookup.py` の `fake_internet` が `get_http_client` を `httpx.MockTransport` に差し替える。応答の形は `fixtures_lookup.py` の実レスポンスの抜粋を使う。キーの有無は `monkeypatch` で切り替える
- 禁止: ハードコードでテストを通すこと。何もアサートしないテスト
- テスト名は日本語で、何を検証しているか読んで分かる文にする（例: `同じISBNを2回登録すると409になる`）。`test1` は不可
- フロントエンドは vitest。純粋関数（`visibility` / `progress` / `markdownInsert` / `isbnLike` / `recommendations`）を `*.test.ts` で見る。コンポーネントのテストは無い
- `./run.sh test` に vitest と lint は含まれない。それぞれ `npm test` / `npm run lint` で回す

## 8. 設計書の約束（ユーザーの指示）

> コードを書くときは設計書を残して、意図や全体像が追跡できるようにする。

- 新機能・構成の変更・データの持ち方の変更をするときは、**実装の前に** `docs/design/NNNN-名前.md` を書く（既存のものがあれば更新する）。章立ては `docs/design/README.md` に従う
- 設計の中身は architect、文書の整形は docwriter が担当する（`.claude/agents/`）
- 実装後は `docs/SPEC.md` の該当節も更新する
- コミットメッセージに設計書のパスを書く

## 9. サブエージェントとスキル

サブエージェント（`.claude/agents/`）
- `architect`（opus）: 全体設計・仕様書・設計書の作成、詰まったエラーの原因究明。実装はしない
- `coder`（sonnet）: 設計が固まった実装・編集・テスト実行
- `tester`（sonnet）: テスト方針の策定と、テストの追加・実行
- `reviewer`（sonnet）: 差分をレビューし、指摘と優先度を返す（書き換えない）
- `adversary`（opus）: 境界値・並行性・悪意ある入力を狙う敵対的レビュー（書き換えない）
- `explorer`（haiku）: 読み取り専用の横断探索
- `summarizer`（haiku）: 長い文書・ログを読んで要約する（読み取りのみ）
- `docwriter`（haiku）: README・使い方メモ・コメントの作成と整形。仕様は決めない
- `worker`（haiku）: 指示が具体的な小タスクの大量処理。選書では `sonnet` を指定して使う
- `researcher`（sonnet）: Web で外部の情報を調べ、出典付きで返す
- `scout`（haiku）: 1つの狭い問いについて Web の生の事実を集める。結論は出さない
- `challenger` / `conservative` / `judge`（opus）: 方針協議の3役（進歩的案・保守案・裁定）

スキル（`.claude/skills/`）
- `next-book-suggestions`: 本ごとの「次に読む本」（近い本2冊・少し離れた本2冊）を選び、ISBN で実在を照合して `PUT /api/books/{id}/suggestions` で登録する
- `keyword-suggestions`: キーワードのおすすめを選び、照合して `PUT /api/topics` で登録する
- どちらも `127.0.0.1:8765` の API が起動していることが前提

## 10. 外部サービス

- 本の情報は外部から取る。ISBN 引きは openBD（速いが ISBN 引きのみ）→ Google Books → 国立国会図書館サーチの順。国会図書館は遅く取りこぼしが多いので最後の受け皿。実測の根拠は `docs/SPEC.md` §5
- Google Books は `backend/.env` の `GOOGLE_BOOKS_API_KEY` が必要（取り方は `backend/.env.example`）。未設定なら呼ばない
- 国会図書館の書名検索は初回 12〜39 秒かかることがある。429 やタイムアウトは 503 として返す（0件とは別扱い）
- 書影は `/api/covers/{isbn}` で中継する（国会図書館は `Referer` が無いと 403 を返すため、ブラウザから直接読ませない）。手で入れた表紙は DB に入る
