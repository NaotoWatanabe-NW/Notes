---
name: next-book-suggestions
description: 読書ノートアプリに登録した本それぞれの「次に読む本」（読了ダイアログに出す候補）を、worker エージェントを並列に使って選び、実在を ISBN で照合してから PUT /api/books/{id}/suggestions で登録する。「おすすめ本を探して」「次に読む本を選んで」「候補を設定して」「候補が足りない本を埋めて」「読み終えた本の候補をメモから作り直して」などで使う。
---

# 次に読む本の候補づくり

本ごとに **近い本（near）2冊 ＋ 少し離れた本（far）2冊** をあらかじめ設定しておく。
アプリは実行時に推薦を計算しない（`docs/SPEC.md` の Step H）ので、ここで作ったものがそのまま読了ダイアログに出る。

流れは **targets → エージェント → verify → apply** の4段。どれも同じ作業ディレクトリを使う。
スクリプトは `.claude/skills/next-book-suggestions/scripts/nbs.py`（標準ライブラリだけで動く）。

## 使い分け

| やりたいこと | targets の引数 |
|---|---|
| 候補が足りない本を全部埋める（既定） | なし |
| 特定の本だけ | `--ids 19,39` |
| 読み終えてメモ・評価が付いた本を作り直す | `--ids 19 --replace` |
| 数を変える | `--near 2 --far 2`（既定） |

**補充（既定）は足りない分だけ頼む。** near が2冊あって far が1冊なら、far を1冊だけ頼み、既存の候補は残す。
なので、照合で弾かれて足りなくなった本も、同じ手順をもう一度回せば欠けた分だけが対象になる。

## 手順

### 0. 準備

```bash
curl -sf -o /dev/null http://127.0.0.1:8765/api/books && echo ok   # 落ちていたら ./run.sh
WORK=<スクラッチパッド>/nbs-$(date +%Y%m%d-%H%M)                   # 作業ディレクトリ
NBS=.claude/skills/next-book-suggestions/scripts/nbs.py
```

### 1. targets — 対象の本をバッチに分ける

```bash
python3 $NBS targets --dir $WORK
```

`$WORK/batches/b01.json …`（既定で1バッチ4冊）、除外リスト `$WORK/shelf.txt`、
照合用の `targets.json` / `exclude.json`、そして**エージェントへの指示書 `$WORK/prompts/b01.md …`**
（`agent-brief.md` にパスを埋めたもの）ができる。対象が 0 冊なら終わり。

### 2. エージェント — バッチごとに worker を1体

- プロンプトは短く「`$WORK/prompts/b01.md` を Read し、その指示どおりに作業してください」とだけ渡す（パスは絶対パス）
  - 選び方を変えたいときは `agent-brief.md` を直す。プロンプトに書き足さない
- `subagent_type: worker`、**`model: sonnet`**（既定の haiku は和書の知識が足りず、架空の本が増える）、`run_in_background: true`
- **同時に8体まで**。終わった分から次のバッチを投げる
- 目安: 4冊のバッチ1体で 8〜10分、1冊あたり約2万トークン
- エージェントの出力 JSON を会話に読み込まない。中身は verify の一覧で見れば足りる

### 3. verify — 実在と重複を照合する

```bash
python3 $NBS verify --dir $WORK        # $WORK/out/*.json をまとめて照合
```

各候補の ISBN をアプリの `/api/isbn` で引き、**書名が一致したものだけ**を通す。
ISBN で合わなければ `/api/search`（遅い: 1件10秒以上）で書名から探し直す。

| 状態 | 意味 | 扱い |
|---|---|---|
| ok | 実在し、本棚にも無い | そのまま登録 |
| warn | 実在するが、書名が頭だけ一致 / 著者が違う | **一覧を目で見る**。別の本なら `verified.json` から消す |
| unverified | ISBN でも書名でも見つからない（架空の本・写し間違い） | 捨てる |
| excluded | 本棚にある / 興味なしにした本 | 捨てる |
| duplicate / extra | 既存の候補と同じ / 頼んだ数を超えた | 捨てる |

書名・ISBN・表紙は照合した書誌を正として保存する。著者だけは、書誌がローマ字＋訳者
（「Guy Deutscher, 椋田直子」）のとき、エージェントのカナ表記を使う。

### 4. apply — 登録する

```bash
python3 $NBS apply --dir $WORK --dry-run   # 何が入るかを見る
python3 $NBS apply --dir $WORK
```

- 補充モードは「既存 ＋ 新規」をまとめて PUT する。**近い本を先に並べる**（ダイアログの既定「両方」で最初の3冊に near 2・far 1 が出る。「出し直す」で残りの far）
- **積読に追加済みの候補がある本は補充しない**。PUT は全件を作り直すので「✓ 積読に追加しました」の印が消えるため。その本は手で直すか `--replace` を使う

### 5. 足りない本があれば 1 に戻る

`targets` をもう一度実行すると、足りない本だけが残る。**2周しても埋まらない本**は、
その本の書名・著者が正しいか（`GET /api/books/{id}`）を確かめてから、手で選ぶか報告する。

### 6. 報告

- 登録した冊数、弾いた件数（状態ごと）、2周しても埋まらなかった本
- 選書が弱いもの（シリーズの途中の巻、元の本とのつながりが薄い理由など）があれば挙げる
- 本の登録データの誤り（著者違いなど）に気づいたら、直さずに報告する

## 確認のしかた

```bash
curl -s http://127.0.0.1:8765/api/books/19/suggestions | python3 -m json.tool
```

画面では、その本を読了にした瞬間にダイアログが出る。

## テスト

```bash
.venv/bin/pytest .claude/skills/next-book-suggestions/scripts -q
```
