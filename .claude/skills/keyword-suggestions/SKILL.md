---
name: keyword-suggestions
description: 読書ノートアプリに「キーワードのおすすめ」（「ゲーム理論」「統計」のようなキーワードに紐づくおすすめ本）を、本棚の本を手がかりに worker エージェントで選び、実在を ISBN で照合してから PUT /api/topics で登録する。勉強系は「同じテーマの難易度別／近いテーマ／少し離れたかんたんな本」の3区分で選ぶ。「〇〇についておすすめを追加して」「キーワードでおすすめを探して」「〇〇の本を難易度別に探して」「テーマ別のおすすめを作って」などで使う。本ごとの「次に読む本」は next-book-suggestions を使う。
---

# キーワードのおすすめづくり

キーワード（「ゲーム理論」など）ごとにおすすめの本を設定する。本棚の1冊に紐づく「次に読む本」
（next-book-suggestions）とは別物で、`topics` / `topic_suggestions` テーブルに入る（`docs/SPEC.md`）。
本棚の本は**選書の手がかり**にする。難しさの基準にし、すでに持っている本は避ける。

流れは **targets → エージェント → verify → apply** の4段で、next-book-suggestions と同じ。
スクリプトは `.claude/skills/keyword-suggestions/scripts/kws.py`（標準ライブラリだけで動く）。
本の照合は next-book-suggestions の `nbs.py` をそのまま使う。

## 区分

1キーワードにつき、既定で **6冊**。

| 区分 | 既定 | DB の距離 | 勉強系（study）での中身 |
|---|---|---|---|
| same | 2 | near | **同じテーマの難易度別**。手がかりの本より一段やさしい本と一段深い本 |
| adjacent | 2 | near | **近いテーマ** |
| side | 2 | far | **少し離れた、かんたんに読める本** |

- DB には区分の列が無い。区分は near / far に寄せ、難しさの違いは**理由の一言**に書く
  （2026-10-03 にユーザーが「near/far に寄せる」を選んだ）
- **小説・エッセイ・自己啓発は仮ルール**（`agent-brief.md` の表の（仮）の列）。ユーザーは
  「仮ルールで試して決める」を選んでいる。決まったら表の（仮）を外し、ここも直す
- ジャンルは、キーワードと手がかりの本からエージェントが決める。`--genre` で決め打ちもできる

## 使い分け

| やりたいこと | targets の引数 |
|---|---|
| キーワードのおすすめを作る（足りない分だけ補充） | `--keyword ゲーム理論` |
| 複数のキーワードをまとめて | `--keyword 統計 --keyword ゲーム理論`（1キーワードにエージェント1体） |
| 手がかりの本を指定する | `--keyword 統計 --books 25,31`（キーワード1つのときだけ） |
| ジャンルを決め打ちする | `--genre selfhelp`（study / novel / essay / selfhelp） |
| 作り直す | `--replace` |
| 数を変える | `--same 2 --adjacent 2 --side 2`（既定） |

キーワードは API と同じく全角/半角と空白をそろえて扱う（「ＡＩ　倫理」と「AI 倫理」は同じ）。

## 手順

### 0. 準備

```bash
curl -sf -o /dev/null http://127.0.0.1:8765/api/topics && echo ok
WORK=<スクラッチパッド>/kws-$(date +%Y%m%d-%H%M)   # 作業ディレクトリ（周回ごとに新しく）
KWS=.claude/skills/keyword-suggestions/scripts/kws.py
```

API は systemd の `notes-web` で常駐している（`docs/systemd-service.md`）。`/api/topics` が 404 なら
古いコードのまま動いているので `systemctl --user restart notes-web` で反映する。

### 1. targets — キーワードごとに頼む数を書き出す

```bash
python3 $KWS targets --dir $WORK --keyword ゲーム理論
```

`$WORK/batches/k01.json …`、本棚 `$WORK/shelf.json`（1冊1行・メモ付き）、照合用の `targets.json` /
`exclude.json`、**エージェントへの指示書 `$WORK/prompts/k01.md …`** ができる。

画面に出る「文字列で当たった本」は、キーワードを書名・タグ・メモに含む本というだけの**出発点**。
手がかりの本はエージェントが本棚全体から選び直す。

### 2. エージェント — キーワードごとに worker を1体

- プロンプトは短く「`$WORK/prompts/k01.md` を Read し、その指示どおりに作業してください」とだけ渡す（パスは絶対パス）
  - 選び方を変えたいときは `agent-brief.md` を直す。プロンプトに書き足さない
- `subagent_type: worker`、**`model: sonnet`**（haiku は和書の知識が足りず、架空の本が増える）、`run_in_background: true`
- **同時に4体まで**（next-book-suggestions で、8体同時だと利用上限に当たって全員止まった）
- エージェントの出力 JSON を会話に読み込まない。中身は verify の一覧で見れば足りる
- エージェントの返答に「仮ルールが選びにくかった」などがあれば、報告に添える
- **`$WORK/out/` にファイルが出そろってから verify する**。返答の書名や ISBN は当てにせず、正はファイルと verify の結果
  - パイロット（2026-10-03）では、エージェントの作業が終わる前に、実際の出力と食い違う「完了」の知らせが届いた。
    その知らせに沿って動くと、架空の ISBN を拾い、作業中のエージェントに要らない指示を送ることになる
  - 途中のエージェントに追加の指示を送らない。指示書と食い違う指示は、エージェントが（正しく）無視する

### 3. verify — 実在と重複を照合する

```bash
python3 $KWS verify --dir $WORK
```

キーワードごとに、エージェントが決めた**ジャンル**と**手がかりの本**、候補ごとの区分と状態が出る。
状態の意味と直し方（warn は目で見る、mismatch は `--accept <ISBN>`、unverified は捨てる）は
next-book-suggestions の SKILL.md の表と同じ。このスキルで増えるもの:

| 状態 | 意味 |
|---|---|
| invalid | 区分（slot）やカテゴリ（category）が不正、`from_book_id` が本棚に無い、理由が空か長すぎる |
| duplicate | このキーワードの候補にすでにある |
| extra | near / far が頼んだ数を超えた |

**手がかりの本も見る**。キーワードと関係の薄い本が混ざっていたら、`--books` で指定して作り直す。

### 4. apply — 登録する

```bash
python3 $KWS apply --dir $WORK --dry-run   # 何が入るかを見る
python3 $KWS apply --dir $WORK
```

- `PUT /api/topics` に `{keyword, suggestions}` を送る。キーワードが無ければ作られる
- 並びは 同じテーマ → 近いテーマ → 少し離れた。補充のときは既存を残して足す（近い本が先）
- **積読に追加済みの候補があるキーワードは補充しない**。PUT は全件を作り直すので印が消えるため

### 5. 足りなければ 1 に戻る

照合で弾かれて足りない分は、**新しい作業ディレクトリで** `targets` をもう一度実行すると、
足りない数だけが対象になる（`targets` は `out/` に出力が残っていると止まる）。

### 6. 報告

- キーワードごとに: ジャンル、手がかりにした本、登録した冊数（区分ごと）、弾いた件数（状態ごと）
- **仮ルールのジャンル**は、選書がルールどおりだったか・ルールが合っていそうかを一言添える。ユーザーがルールを決める材料になる
- 本の登録データの誤り（著者違いなど）に気づいたら、直さずに報告する

## 確認・消し方

```bash
curl -s http://127.0.0.1:8765/api/topics | python3 -m json.tool              # キーワードの一覧
curl -s http://127.0.0.1:8765/api/topics/1 | python3 -m json.tool            # 1つぶんの候補
curl -s -X DELETE http://127.0.0.1:8765/api/topics/1                         # キーワードごと消す
```

画面にはまだ出ない（2026-10-03 時点。API だけ）。

## テスト

```bash
.venv/bin/pytest .claude/skills/keyword-suggestions/scripts .claude/skills/next-book-suggestions/scripts -q
```

照合は `nbs.py` の `resolve_book` / `load_exclude` に頼っているので、`nbs.py` を変えたら両方を回す。
