# Handoff: Notes — 読書記録アプリ（Web＋モバイル）

## Overview
本を1冊ずつ管理し、ページ単位の「引用」「メモ」を残し、読みながら長文の「読書レポート」を書き足していく読書記録アプリ。
Webは3ペイン（アイコンレール／一覧／詳細）＋ ⌘K コマンドパレット。レポート執筆は全画面モードで、メモ・引用をフローティングウィンドウから本文に差し込む。モバイルは同じ情報構造をタブバー＋単一ペインに畳み、執筆中のメモ参照はハーフシートで行う。

## About the Design Files
同梱の `.dc.html` は **HTMLで作ったデザインリファレンス**（見た目と振る舞いを示すプロトタイプ）であり、そのまま出荷するコードではない。対象コードベースの既存環境（React / Next.js / SwiftUI など）とそのパターン・ライブラリで**再実装**すること。環境が未定なら、Web は React（Next.js）＋ contenteditable ベースのリッチテキスト（Tiptap / Lexical 等）を推奨。
ファイルはブラウザで直接開ける（`support.js` と `_ds/` が同じ階層に必要）。

## Fidelity
- **Web（`Notes Web.dc.html`）: ハイファイ。** 色・書体・余白・状態・インタラクションは最終。ピクセル単位で再現する。
- **執筆モード（`Notes Report.dc.html` の 4a／4b）: ハイファイ。** 4a は `Notes Web` に統合済み。
- **モバイル（`Notes Mobile.dc.html` 7a〜7g）: ハイファイの静止画。** 色・書体・余白・部品は最終。画面遷移とジェスチャーは下の説明に従う（クリックできるプロトタイプではない）。
- Turn 2（2a/2b）、3a/3b/3c、4c/4d は**不採用の比較案**。参照のみ。

---

## 採用案まとめ
| 領域 | 採用 | ファイル / id |
|---|---|---|
| Web ナビゲーション | 3ペイン＋⌘K | `Notes Base Design.dc.html` #2c → `Notes Web.dc.html` |
| レポート執筆（PC） | 紙面＋アウトライン＋フローティングのメモ窓 | `Notes Report.dc.html` #4a（`Notes Web` に統合済み） |
| レポート執筆（スマホ） | ハーフシート | `Notes Report.dc.html` #4b |
| モバイル全体 | タブバー＋単一画面（7画面） | `Notes Mobile.dc.html` #7a〜#7g（部品は `Notes Base Design.dc.html` #1a） |
| レポートのエディタ（PC） | Markdown 2ペイン＋メモ・記法のフローティング窓 | `Notes Report.dc.html` #6a（4a の本文エディタを置き換える。Notes Web には未統合） |
| 次に読む本 | 読了時ダイアログ | `Notes Next Book.dc.html` #5a（Notes Web には未統合） |

---

## Screens / Views — Web

### 全体レイアウト
- ルート: `height:100vh; min-width:1080px; display:grid; grid-template-columns: 76px 340px minmax(0,1fr)`、背景 `--color-bg`。
- 区切り線は使わない。ペインの差は背景色のみ: レール `--color-surface`(#eae9e9)、一覧 `--color-neutral-100`(#f8f4f4)、詳細 `--color-bg`(#f3f2f2)。

### A. アイコンレール（76px）
- 上から: ロゴ「N」(24px/600, mb 18px)、本棚／メモ／振り返り、（spacer）、探す、設定。
- 各項目: 60px 幅ボタン、padding 8px 0 6px、アイコン 24px（Phosphor duotone）＋ラベル 10px、gap 3px、radius 2px。
- 非選択: 文字 `--color-neutral-700`、背景透明、hover `--color-neutral-300`。選択: 背景 `--color-accent-100`(#e9f8ff)、文字 `--color-accent-700`(#006786)。
- アイコン: `ph-books` / `ph-quotes` / `ph-chart-line-up` / `ph-magnifying-glass` / `ph-gear`。
- 「探す」はビュー遷移ではなく ⌘K パレットを開く。

### B. 一覧ペイン（340px）
- padding 28px 18px、`display:grid; grid-auto-rows:max-content; gap:20px; overflow-y:auto`。
  - ⚠ flex column にすると `.seg`（overflow:hidden）が縮んで潰れる。grid か `flex-shrink:0` を使う。
- 見出し 24px/600。右肩に補助情報 12px `--color-neutral-700`。
- セグメント（`.seg` / `.seg-opt`）: 選択肢は `flex:1; justify-content:center; font-size:12px`。選択中 `background:--color-accent; color:--color-bg`。
- 行: padding 9px 8px（メモ行は 12px 10px）、radius 2px、hover `--color-neutral-200`、選択 `--color-accent-100`。

ビュー別の中身:
1. **本棚**: 「本棚」＋右肩ボタン「⌘K 検索・追加」（11px, bg `--color-neutral-200`, padding 3px 8px）。セグメント「読書中 n / 読了 n / 積読 n / すべて」。行 = 表紙 36×52（radius 1px, `--shadow-sm`）＋書名 14px/600/lh1.35 ＋メタ 11px。メタ: 読書中 `57% · メモ 4`、読了 `著者 · ★★★★`、積読 `著者`。
2. **メモ・引用**: 「メモ・引用」＋件数。セグメント「すべて / 引用 / メモ」。行 = 種別ラベル 11px（引用 `--color-accent-2-700`、メモ `--color-neutral-700`）、本文 14px/lh1.65（引用は「」付き・イタリック、42字で省略「…」）、出典 11px `書名 · p.96`。
3. **振り返り**: 期間リスト「2026年(1月〜9月) / 2026年9月(今月) / 2026年8月(先月) / 2025年」。行: ラベル 16px/600 ＋ サブ 11px、右に「42冊」13px。
4. **設定**: 読書目標 `ph-target` / 表示 `ph-eye` / データ `ph-export` / アカウント `ph-user-circle`。行 15px、アイコン 20px、gap 12px。

### C. 詳細ペイン
- `overflow-y:auto`、内側 `max-width:760px; padding:48px 64px 80px; flex column; gap:36px`。

**C-1 本の詳細（本棚）**
- ヘッダー行: 表紙 120×176（radius 2px, `--shadow-md`, padding 12px。書名 14px/600 と著者 10px を上下に配置）＋ 右に 状態タグ（`.tag-accent` 読書中 / `.tag-outline` 読了 / `.tag-neutral` 積読）、書名 32px/600/lh1.2、`著者 · 出版社` 13px。読了時は ★×5（20px, 選択 `--color-accent`, 未選択 `--color-neutral-400`、クリックで評価変更）。
- 読書中: 進捗行（`p.182 / 320` ／ `9月3日から · 57%` 12px）＋バー 3px（地 `--color-neutral-300`、値 `--color-accent`、max-width 520px）。ボタン: [メモを書く（primary, ph-pencil-simple-line）] [進捗を記録（secondary）] [レポートを書く（secondary, ph-article）]。
- 積読: [読み始める（primary, ph-book-open）]。
- 読了: [レポートを書く（primary）] [メモを追加（secondary）]。
- インライン編集パネル（背景 `--color-surface`, padding 18–22px, radius 2px）:
  - 進捗: 「読んだページ」数値入力(140px) ＋ `/ 320` ＋ [キャンセル（ghost）] [更新（primary）]。最終ページに達したら状態を「読了」にし、フィルタも読了に切り替える。
  - メモ: セグメント「引用 / メモ」＋ページ入力(110px) ＋ textarea（16px/lh1.7、引用時はイタリック、min-height 96px）＋ 引用時のみ「自分のメモ（任意）」入力 ＋ [キャンセル] [保存]（本文が空なら disabled）。
- 記録一覧: 見出し「メモ・引用 n件」22px/600 ＋ 右「ページ順」12px。ページ降順。各項目 max-width 620px: 種別 `引用 · p.182` 12px（色は上記）、引用 18px/lh1.75 イタリック「」付き、メモ 16px/lh1.75、補足メモ 14px `--color-neutral-800`。
- 空状態: 「まだ記録がありません。読んだページの引用や、そのとき考えたことを残せます。」15px `--color-neutral-700`。

**C-2 メモ・引用の詳細**
- 本の行（表紙 36×52 ＋ 書名 15px/600 ＋ 著者）＋ 右端「本を開く →」13px `--color-accent-700`（本棚ビューでその本を選択）。
- 種別・日付 13px、引用 28px/lh1.6 イタリック、メモ 22px/lh1.7、補足 16px。
- 「同じ本の記録」: 兄弟メモ 15px、クリックで切替。

**C-3 振り返り**
- サブ 12px ＋ 期間名 32px/600。
- 読了冊数: `.cmyk-num`（150px/600、C/M/Y 3版ずれ）＋「冊 読了」22px/600 ＋ 目標行 13px（`目標 50冊まで あと8冊` — 設定の目標値と連動）。
- 棒グラフ: 高さ 120px、gap 10px、棒 `--color-accent-300`、現在月／週は `--color-accent`、下にラベル 10px。年は月別、月は週別。
- 3列の数値: ページ / メモ・引用 / よく読む分野（28px/600 ＋ 12px ラベル）。
- 「いちばん残した言葉」（ラベル `--color-accent-2-700`）: 22px/lh1.65 イタリック ＋ 出典 12px。
- 「この期間に読み終えた本」: 表紙 72×104 の横並び。

**C-4 設定**
- 読書目標: 数値入力（max-width 200px, 18px）＋ 説明文（`今年はここまで42冊読了。目標まであと8冊、月に3冊のペースです。`）。
- 表示: 本棚の並び順（追加順 / 書名 / 進捗）— 一覧の並び順に即反映。引用の書体（イタリック / 標準）— アプリ全体の引用表示に反映。
- データ: Markdown / CSV の書き出しボタン（secondary）。
- アカウント: 名前・メール（表示のみ）＋ ログアウト。

### D. ⌘K コマンドパレット
- 開閉: ⌘K / Ctrl+K でトグル、Esc か背景クリックで閉じる。レールの「探す」、本棚ヘッダーのボタンでも開く。
- 背景 `color-mix(--color-neutral-900 45%)`、パネル 640px、上から 96px、`--shadow-lg`、radius 4px。
- 入力行: 検索アイコン 22px（accent）＋ 入力 20px（枠なし）＋「esc」。プレースホルダー「本棚・メモを検索、または本を追加」。
- 結果グループ（ラベル 11px, letter-spacing .06em）:
  - クエリ空: 「いま読んでいる」（読書中の本）。
  - 「本棚」: 書名・著者に一致（最大4）→ 本棚でその本を開く。
  - 「メモ・引用」: 本文・補足に一致（最大3）→ メモビューで開く。
  - 「本を追加」: 外部カタログ（本棚にない本）に一致（最大4）→ 積読として追加し、その本を選択、トースト表示。
  - 一致なし: 「「◯◯」に一致するものはありません。」
  - 「操作」: ISBN・バーコードで追加 / 「(選択中の本)」にメモを書く。
- 先頭の結果は `--color-accent-100` でハイライトし、Enter で実行。
- フッター（`--color-surface`, 11px）: `↵ 先頭を選択` `esc 閉じる` `⌘K 開閉`。

### E. レポート執筆モード（4a、統合済み）
- 起動: 本の詳細の「レポートを書く」。アプリ全体を覆う全画面（`position:absolute; inset:0; z-index:8`）。
- レイアウト: `grid-template-columns: 260px minmax(0,1fr)`。
- 左（`--color-neutral-100`, padding 28px 20px）:
  - [保存して戻る（ghost, ph-arrow-left）]
  - **アウトライン**: 本文の h3（14px/600, pl 8px）と h4（12px, pl 22px）から自動生成し、入力のたびに更新。クリックで該当見出しへスムーズスクロール（上に 24px の余白）。
  - **見出しを挿入**: 要約 / 感想 / 学び・行動（→見出し「行動に移すこと」）/ 章メモ（secondary, 12px）。さらに [p.{現在ページ} の章メモ（primary）]。
  - [メモ窓を開く/閉じる]
- 本文（`max-width:720px; padding:40px 64px 120px`）:
  - ラベル「読書レポート」12px `--color-accent-700`、書名 48px/600/lh1.1/ls -0.02em。
  - 題字罫: `border-top:3px solid --color-text; border-bottom:1px solid --color-text; padding:9px 0`（Broadsheet の thick-thin rule。**唯一使ってよい罫**）。中に 著者 / `p.182 / 320` / `n字`（空白を除いた文字数）/ ★評価 / おすすめ度セグメント「人にすすめたい / 人を選ぶ / 自分用」。
  - エディタ: 17px/lh1.95、見出しは自由（テンプレート強制なし）。h3 = 22px/600、margin 32px 0 10px。h4（章メモ）= 17px/600、`--color-accent-700`、`章名 · p.21` 形式。引用 blockquote = margin 6px 0 18px 24px、イタリック、`--color-accent-2-800`、末尾に `p.96`（12px, 正体, `--color-neutral-700`）。**左ボーダーは付けない**。
- **フローティングのメモ窓**: 幅 340px、`--shadow-lg`、radius 4px。初期位置は右上（右端から 380px、上から 88px）。
  - タイトルバー（`--color-surface`）: グリップ `ph-dots-six-vertical` ＋「メモ・引用 n」＋ 小さくする（— / 展開）＋ 閉じる（×）。タイトルバーのドラッグで移動し、執筆エリアの外には出ない。
  - フィルタ: すべて / 引用 / メモ。
  - リスト: max-height 360px。項目 hover `--color-accent-100`、cursor copy。**mousedown で preventDefault してエディタのキャレットを保持し**、キャレット位置に挿入する（キャレットが本文にないときは末尾）。
  - フッター: 「クリックでカーソル位置に挿入 · ドラッグで移動」。
- 終了: 「保存して戻る」または Esc。本文 HTML を本ごとに保存し、トースト「レポートを保存しました」。

### G. 次に読む本（5a・読了時ダイアログ）
- 表示のタイミング: 本が「読了」になった瞬間（進捗が最終ページに達した、または状態を読了に変えたとき）に**一度だけ**。閉じたあとは再表示しない。
- 背景 `color-mix(--color-neutral-900 50%)`、パネル 880px、padding 36px 40px 28px、radius 4px、`--shadow-lg`、中は `grid; gap:26px`。
- ヘッダー: ラベル「読了 · 23日間 · 引用・メモ 6件」12px `--color-accent-700` ＋ 見出し「『書名』を読み終えました」28px/600 ＋ 右に ★評価（24px、クリックで変更）。
- 条件の行: 「次に読む本」18px/600 ＋ 根拠トグル3つ（引用・メモから `ph-quotes` ／ 評価から `ph-star` ／ 分野から `ph-tag`。ON は bg `--color-accent-100`・文字 `--color-accent-800`、OFF は文字 `--color-neutral-600`。最低1つは ON）＋ 距離のセグメント（近い本 / 少し離れた本 / 両方）＋ [出し直す（ghost, ph-arrows-clockwise）]。
- 提案カード: 3列（gap 24px）。表紙 72×104 ＋ 書名 15px/600 ＋ 著者 11px ＋ **理由は一言** 13px/lh1.6 ＋ 根拠ラベル 10px（引用・メモ由来は `--color-accent-2-700`、それ以外は `--color-accent-700`）。
  - [積読に追加（secondary）] → `.tag-accent`「✓ 積読に追加しました」＋ [取り消す]。
  - [興味なし（ghost, neutral-700）] → そのカードを次の候補に入れ替え、その本は以後の提案から外す（フィードバックとして保存）。
- フッター: 左に根拠の要約 12px（例「引用・メモ6件、★5の本2冊、よく読む分野 #哲学 から選んでいます」。興味なしの後は「興味なし n件 — 似た本は次から出しません」、候補が3冊未満なら「条件に合う候補が少なくなりました…」）。右に [レポートを仕上げる（ghost）→ 執筆モード] [閉じる（primary）]。
- 推薦のデータ: 候補ごとに `{ bookRef, basis: 'note'|'rating'|'tag', distance: 'near'|'far', reason(一言) }`。出し直しは同じ条件で次の3冊（ページング）。条件を変えたら先頭から。興味なしにした本は `dismissedBookIds` に残し、除外と今後の学習に使う。
- 推薦エンジンは対象外。モックの候補と理由は仮のデータ。

### H. Markdownエディタ（6a）— 4a の本文エディタをこれに置き換える
- 上部バー（56px）: [本に戻る] 書名 14px/600 ｜ ツール（見出し `##` / 章 `###` / 引用 `>` / 箇条書き `-` / 太字 `**`、ghost ボタン、アイコン 18px）｜ spacer ｜ `n字 · 自動保存済み` 12px ｜ [メモ窓] ｜ 表示の切り替え「並べる / 書く / 読む」。
- 本体: `grid-template-columns: minmax(0,1fr) minmax(0,1fr)`（書く・読むのときは1列、読むは max-width 720px で中央寄せ）。
  - 左（背景 `--color-neutral-100`）: textarea。**セリフ体**（`--font-body`）16px/lh1.9、padding 36px 48px 120px、枠なし、`caret-color:--color-accent`、spellcheck off。
  - 右: 3c と同じ組み（ラベル「読書レポート」／書名 40px／題字罫の中に 著者・ページ・評価・おすすめ度）＋ Markdown のレンダリング結果。
  - 左のスクロール位置に合わせて、右を比率で連動させる（「並べる」のときだけ）。
- レンダリングの対応表: `#`/`##` → h3（28/22px 600）、`###` → h4 章見出し（17px 600 `--color-accent-700`）、`>` → 引用（イタリック `--color-accent-2-800`、左マージン 24px、**罫なし**）、`-`/`*`/`1.` → リスト、`- [ ]`/`- [x]` → ☐/☑、`**` 太字、`*` 斜体、`~~` 取り消し、`` ` `` → 背景 `--color-neutral-200` の語句、`[文字](URL)` → `--color-accent-700` のリンク、`---` → 40px の余白（罫は引かない）、行末や語の前後の `p.96` → 12px `--color-neutral-700` の正体。
- 文字数は空白と記法の記号を除いて数える。
- 挿入のルール（ツール・メモ窓で共通）:
  - ブロック（見出し・章・引用・リスト・メモ）は**必ず独立した段落**にする。前後の改行が2つに満たなければ補う。キャレットは挿入した行の末尾へ。
  - インライン（太字・斜体・取り消し・語句・リンク）は選択範囲を囲む。選択がなければ仮の文字を入れて囲む。
  - ボタン類は mousedown で preventDefault し、textarea の selectionStart/End を保持する。
- **フローティング窓**（320px、4a と同じ見た目・ドラッグ操作、初期位置は左下 x40 y420。上部バーの下からは出ない）:
  - タイトルバーに「メモ・引用 / 記法」のタブ。
  - メモ・引用: この本のメモを並べ、クリックで `> 「本文」 p.96`（メモは `本文（p.96）`）を挿入。
  - 記法: 12行。左に記法（13px `--color-neutral-800`、pre）、右に表示見本（実際の書体・太さ・色で）。クリックで挿入。フッター「クリックで挿入 · 太字・斜体は選択範囲を囲む」。
- スマホ（4b）も同じ Markdown 原文を扱う。アクセサリバーは [メモ] [見出し] [p.◯ 章メモ] のまま、ハーフシートにも「記法」タブを付ける。プレビューは「読む」表示への切り替えで見る（2ペインにはしない）。

### F. トースト
- 右下（right 32px, bottom 28px）、地 `--color-text`、文字 `--color-bg`、14px、`ph-check-circle`（`--color-accent-300`）、2.4秒で消える。

---

## Screens / Views — モバイル（iPhone, 390×844）— `Notes Mobile.dc.html` #7a〜7g
**正本は `Notes Mobile.dc.html`**（`Notes Base Design.dc.html` の 1b〜1e は旧案。1a の共通部品は引き続き有効）。静止画のモックで、画面遷移は下記の通り。
- 共通: ステータスバーの下に余白 18–20px。画面の左右 padding 20px。タップ領域は 44px 以上。
- **タブバー**（4つ）: 本棚 `ph-books` / メモ `ph-quotes` / 振り返り `ph-chart-line-up` / 探す `ph-magnifying-glass`。アイコン 24px ＋ ラベル 10px、選択 `--color-accent`、非選択 `--color-neutral-700`。padding 8px 0 28px、上端に `0 -1px 8px` の薄い影（罫は引かない）。詳細・執筆はタブの上にスタックで重ねる（タブバーは詳細では残し、執筆では隠す）。

### 7a 本棚
- ヘッダー: `9月26日 · 53冊` 12px ＋「本棚」34px/600。右に設定（`ph-gear`, btn-icon ghost）。
- 検索バー（高さ 44px、`--color-surface`、radius 2px）:「本棚・メモを検索、本を追加」＋ 右に `ph-barcode`。タップで 7c へ。
- 「いま読んでいる · 3冊」（12px `--color-accent-700`）: 横スクロールのカード（幅 252px、padding 12px、`--color-surface`）。表紙 56×82 ＋ 書名 15px/600 ＋ 著者 11px ＋ `p.182 / 320 · 57%` ＋ 3px の進捗バー。右端ははみ出させてスクロールできることを示す。
- セグメント: すべて / 読了 n / 積読 n（読書中は上のカードに出すので除く）。
- 一覧: 表紙 36×52 ＋ 書名 15px/600 ＋ `著者 · 状態 ★` 12px ＋ `ph-caret-right`。タップで 7b。

### 7b 本の詳細
- ナビ: [‹ 本棚] ／ `ph-dots-three`（編集・削除・状態変更）。
- 表紙 100×146（`--shadow-md`）＋ 状態タグ ＋ 書名 24px/600 ＋ 著者・出版社 12px。
- 進捗: `p.182 / 320` ／ `9月3日から · 57%` 12px ＋ 3px バー。
- 操作: 2列 [メモを書く（primary）] [進捗を記録（secondary）]（どちらも高さ 44px）。その下にフル幅の**レポート行**（`--color-surface`、`ph-article` 22px、「読書レポート」15px/600 ＋ `1,240字 · 9月24日に更新` 11px、右に「続きを書く ›」`--color-accent-700`）→ 7f。レポートがまだなければ「レポートを書く」。
- 「メモ・引用 n件 / ページ順」＋ ページ降順のリスト（種別ラベル 11px、本文 16px/lh1.7、引用はイタリック）。
- 「メモを書く」は 1d のモーダルシート（引用 / メモ、ページ、本文、補足）。**1d の「感想」タブは廃止**（感想はレポートに書く）。
- 読了にした瞬間に 7g を出す。

### 7c 探す（⌘K 相当）
- 検索欄（44px、フォーカス中は `inset 0 0 0 2px --color-accent`）＋ クリア ＋ [キャンセル]。キーボードは表示中（モックでは省略）。
- 結果は Web のパレットと同じ順: 本棚（先頭は `--color-accent-100`、右に「開く」）→ メモ・引用（`ph-quotes` `--color-accent-2-700`、一致箇所の抜粋 ＋ 出典。レポート本文も対象）→ 本を追加（右に + の btn-icon secondary 36px。タップで積読に追加）→「ISBN・バーコードを読み取る」。
- クエリが空のときは「いま読んでいる」と最近の検索を出す。

### 7d メモ
- ヘッダー: `186件` ＋「メモ・引用」34px。セグメント すべて / 引用 / メモ。
- 新しい順。**本ごとにまとめる**: 見出し行（表紙 22×32 ＋ 書名 14px/600 ＋ 最新の日付 11px）、その下に 32px 字下げした項目（種別 11px ＋ 本文 15px/lh1.7）。タップでメモの詳細（Web C-2 と同じ内容をフル画面で）。

### 7e 振り返り
- 「振り返り」34px。期間は横スクロールのチップ（選択 `.tag-accent`、他は `.tag-neutral`、padding 7px 14px）: 2026年 / 9月 / 8月 / 2025年 / …
- `.cmyk-num` 112px ＋「冊 読了」20px ＋ 目標行 12px。棒グラフ 高さ 96px、gap 8px（現在月は `--color-accent`）。3列の数値 22px。いちばん残した言葉 18px イタリック。
- 読み終えた本の表紙列は Web と同じく最下部（モックでは画面外）。

### 7f レポート（Markdown）
- 上部: ‹ ／ `書名 · n字` 13px ／ セグメント「書く / 読む」／ [完了]。タブバーは隠す。
- 「書く」: Markdown 原文。セリフ体 16px/lh1.9、padding 14px 22px。**提案**: 記法の記号（`## ` `### ` `** ` `> `）を `--color-neutral-500` で薄くし、見出し・章・太字・引用は仕上がりに近い書体と色で表示する（CodeMirror 6 などの装飾付きエディタが必要。難しければ Web の 6a と同じく単色でよい）。
- 「読む」: Web の 6a の右ペインと同じ表示（題字罫・評価・おすすめ度つき）を1列で表示。2ペインにはしない。
- キーボードの上のアクセサリバー: [メモ・記法（primary）] [見出し `ph-text-h`] [p.◯ 章メモ `ph-bookmark-simple`]。
- **ハーフシート**（4b）: 高さ 52%（グラバーのドラッグで 88%）、radius 14px 14px 0 0、`--shadow-lg`、背後は `neutral-900 18%`。
  - 上部にセグメント「メモ・引用 / 記法」＋ 閉じる。
  - メモ・引用: この本のメモ。タップで `> 「本文」 p.96` を挿入。
  - 記法: 2列（記法 14px `--color-neutral-800` ／ 仕上がりの見本）。見出し・章・太字・引用・箇条書き・チェックリスト・斜体（残りの記法はスクロールした先）。インライン記法は選択範囲を囲む。
  - **タップするとカーソル位置に挿入し、シートを自動で閉じる**。挿入のルールは Web の H と同じ（ブロックは独立した段落にする）。フッター「タップでカーソル位置に挿入し、シートを閉じる」。

### 7g 読了 → 次に読む本（5a のモバイル版）
- 読了にしたときに一度だけ出す、ほぼ全画面のシート（上 54px は背後の画面が暗く見える、radius 14px 14px 0 0）。
- ヘッダー: `読了 · 23日間 · 引用・メモ 6件` 12px `--color-accent-700` ＋「『書名』を読み終えました」22px/600 ＋ ★ 28px（タップで評価）。
- 「次に読む本」18px/600 ＋ [出し直す]。条件は横スクロールのチップ（引用・メモから / 評価から / 分野から は ON/OFF のトグル、最後に距離「近い本 / 少し離れた本 / 両方」。タップで切り替え）。
- 3冊を縦に並べる: 表紙 52×76 ＋ 書名 16px/600 ＋ `著者 · 根拠`（根拠の色は Web と同じ）＋ 理由は一言 13px ＋ [積読に追加（secondary, 36px）] [興味なし（ghost）]。追加後は「✓ 積読に追加しました」＋ [取り消す]。
- 下部に固定: [`ph-article` レポートを仕上げる（secondary, 幅 auto, 折り返さない）] [閉じる（primary, 残りの幅）]、高さ 44px。

### 設定（モックなし）
- 本棚ヘッダーの `ph-gear` から開く、iOS 標準のリスト画面。項目は Web の C-4 と同じ（読書目標 / 表示 / データ / アカウント）で、見た目はこのシステムの書体と色に揃える。

---

## Interactions & Behavior（要点）
- 選択状態・フィルタ・並び順・引用書体はすべて即時反映（ローディングなし）。
- キャレットを保持する: 挿入系ボタンやリスト項目は `mousedown` / `pointerdown` で `preventDefault()` し、保存しておいた Range を復元してから挿入する。
- ⌘K / Esc はグローバルなキーハンドラで扱う。Esc の優先順は パレット → 執筆モード → インライン編集。
- 進捗 ≥ 総ページ → 状態を「読了」にする。
- カタログからの追加は常に「積読」から始まる。
- 実装していないもの（モックでは動かない）: ISBN・バーコード読み取り、書き出し、アカウント、実データの取得。

## State Management
```
Book { id, title, author, publisher, status: 'reading'|'done'|'tsundoku', page, total, rating(0-5), startedAt, coverUrl?, recommend: 'strong'|'some'|'self', reportHtml }
Note { id, bookId, kind: 'quote'|'memo', page, text, memo?, createdAt }
UI   { view: 'library'|'notes'|'review'|'settings', libraryFilter, selectedBookId, noteFilter, selectedNoteId,
       palette: { open, query }, inlineEdit: 'none'|'note'|'progress', draft{kind,page,text,memo},
       writing: { open, bookId }, memoWindow: { open, minimized, x, y, filter },
       period, settings: { yearlyGoal, sort: 'recent'|'title'|'progress', quoteStyle: 'italic'|'plain' },
       mobileSheet: 'closed'|'half'|'full' }
```
- 必要なデータ: 書誌検索API（書名・著者・ISBN → 書名・著者・出版社・刊行年・ページ数・表紙）。
- 振り返りの数値は Book / Note から集計する（期間内の読了冊数、ページ合計、メモ件数、最頻タグ、月・週別の件数）。

## Design Tokens（Broadsheet — `_ds/.../styles.css` が正本）
- Colors: bg `#f3f2f2` / surface `#eae9e9` / text `#201e1d` / accent(cyan) `#0088b0` / accent-2(magenta) `#d6006c` / process-yellow `#edbb00`（`.cmyk-num` 専用）
  - accent: 100 `#e9f8ff` 200 `#cbeeff` 300 `#99e0ff` 600 `#1186ac` 700 `#006786` 800 `#004961` 900 `#0a303e`
  - accent-2: 100 `#fff1f4` 200 `#ffdee6` 700 `#aa0b56` 800 `#790e3d` 900 `#4b1528`
  - neutral: 100 `#f8f4f4` 200 `#eae7e7` 300 `#d7d3d3` 400 `#bab6b6` 500 `#9b9797` 600 `#7d7979` 700 `#605d5d` 800 `#444141` 900 `#2d2b2b`
- 色の役割: シアンは操作・選択・進捗、マゼンタは**引用だけ**。1つの小さな部品に両方の accent を使わない。本文に accent を使うときは 700 以上の濃い段階にする。
- Type: 欧文 Source Serif 4（400/600/400 italic）、和文 Noto Serif JP（400/600）。`--font-heading` と `--font-body` の両方を `"Source Serif 4","Noto Serif JP",serif` に上書きする（上書きしないとボタン内の和文が system-ui になる）。サンセリフは使わない。
  - スケール: 48 / 44 / 34 / 32 / 28 / 24 / 22 / 20 / 18 / 17 / 16 / 15 / 14 / 13 / 12 / 11 / 10 px。ラベル類は letter-spacing 0.04–0.06em。
- Spacing: 5 / 10 / 15 / 20 / 30 / 40 px（`--space-1..8`、density 1.25×。詰めない）。
- Radius: 1 / 2 / 4 px。
- Shadow: sm `0 1px 2px rgba(45,43,43,.14)` / md `0 3px 10px rgba(45,43,43,.16)` / lg `0 12px 32px rgba(45,43,43,.22)`。
- Focus: `outline:2px solid --color-accent; outline-offset:2px`。disabled は opacity .45。
- レイアウトの原則: 罫線・枠で区切らず、余白と書体の大きさで階層を作る（例外は執筆モードの題字罫だけ）。`.card` は使っていない。

## Assets
- アイコン: Phosphor Icons **duotone**（`@phosphor-icons/web@2.1.1`）。主に使うもの: books, quotes, chart-line-up, magnifying-glass, gear, plus, pencil-simple-line, article, book-open, star, cards, dots-six-vertical, minus, arrows-out-simple, x, bookmark-simple, text-h, arrow-left, barcode, target, eye, export, user-circle, file-text, file-csv, check-circle。
- 表紙: 今はプレースホルダー（ramp の 100–300 の塗り＋書名・著者）。実データでは書誌APIの表紙画像を 2:3 で使う。画像がない本は同じプレースホルダーにする。
- 本や引用の内容はすべて仮のデータ。

## Files
- `Notes Web.dc.html` — **Web 版の本体（採用）**。本棚／メモ・引用／振り返り／設定／⌘K／レポート執筆モード（4a 統合）。
- `Notes Report.dc.html` — 執筆モードの比較案。**#6a（Markdown エディタ）・#4a（PC のメモ窓）・#4b（スマホ）が採用**。#3a〜3c と #4c〜4d は不採用。
- `Notes Mobile.dc.html` — **モバイル版の本体（採用）**。#7a 本棚 / #7b 本の詳細 / #7c 探す / #7d メモ / #7e 振り返り / #7f レポート（Markdown＋ハーフシート）/ #7g 読了→次に読む本。
- `Notes Base Design.dc.html` — #1a 共通部品（有効）、#1b〜1e モバイルの旧案、#2a〜2c Web のナビゲーション比較（**#2c が採用**）。
- `Notes Next Book.dc.html` — 次に読む本の比較案。**#5a が採用**、#5b・#5c は不採用。
- `support.js` — 同梱の `.dc.html` をブラウザで表示するためのランタイム（再実装の対象外）。
- `_ds/broadsheet-…/styles.css` — デザイントークンと部品クラスの正本。`readme.md` はデザインシステムのガイド。
