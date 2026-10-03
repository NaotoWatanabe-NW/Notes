# 常駐化 — systemd ユーザーサービスで読書ノートアプリを動かし続ける

（2026-10-03 設定）

`./run.sh` を端末から手で叩いていたので、**端末を閉じる / ログアウトする / PC を再起動する**とアプリが止まっていた。スマホから本の記録を取ろうとした時に落ちていると困るので、systemd の**ユーザーサービス**として常駐させる。

母艦（`naoto-magnate-gmtb`）で動いている他のアプリ（`stocktrade-api` / `stocktrade-web` / `ideapool-web` / `recall-app`）と同じ方式に揃えてある。

## 何をしているか

| 項目 | 内容 |
|---|---|
| ユニット | `~/.config/systemd/user/notes-web.service` |
| 待ち受け | `127.0.0.1:8765`（API + ビルド済みの画面を単一プロセスで配信） |
| 外への出口 | `tailscale serve` の `https://<host>.<tailnet>.ts.net:8765/` → `http://127.0.0.1:8765`（tailnet 内のみ） |
| 起動時 | 画面を `npm run build` してから uvicorn を起動 |
| 落ちたとき | `Restart=always` で 3 秒後に自動復帰 |
| PC 再起動後 | `default.target` に enable 済み + `loginctl enable-linger naoto`（既に有効）なので、**ログインしなくても**自動起動 |

**`./run.sh serve` と同じ構成**を常駐させている（`./run.sh start` ではない）。このアプリには認証が無いので、`0.0.0.0` で待ち受けると同じ LAN（喫茶店の Wi-Fi など）の誰からでも読み書きできてしまう。`127.0.0.1` に閉じて TLS 終端と公開を Tailscale に任せれば、自分のデバイスからだけ見える。

## 日常の操作

```bash
# 状態を見る（Active: active (running) なら OK）
systemctl --user status notes-web

# コードを更新したあと反映する（画面のビルドもここで走る）
systemctl --user restart notes-web

# 止める / 起こす
systemctl --user stop notes-web
systemctl --user start notes-web

# ログ
journalctl --user -u notes-web -f
journalctl --user -u notes-web --since "1 hour ago"

# 常駐をやめる（自動起動もオフ）
systemctl --user disable --now notes-web
```

`git pull` や編集のあとは **`systemctl --user restart notes-web` だけでデプロイ完了**。`./run.sh` を叩く必要はない。

アクセス先:

- このPCから … <http://localhost:8765/>
- スマホ・他PCから … `https://<host>.<tailnet>.ts.net:8765/`（`tailscale status --json` で自ホスト名が分かる）

## ユニットファイル

```ini
[Unit]
Description=Notes Web (reading notes, FastAPI/uvicorn + Vite build)
StartLimitIntervalSec=1800
StartLimitBurst=5

[Service]
Type=exec
WorkingDirectory=/home/naoto/PythonProject/Notes/backend
Environment=PATH=/home/naoto/.nvm/versions/node/v24.14.1/bin:/usr/local/bin:/usr/bin:/bin
ExecStartPre=-/home/naoto/.nvm/versions/node/v24.14.1/bin/npm --prefix /home/naoto/PythonProject/Notes/frontend run build
ExecStart=/home/naoto/PythonProject/Notes/.venv/bin/uvicorn app.main:app \
    --host 127.0.0.1 --port 8765 \
    --env-file /home/naoto/PythonProject/Notes/backend/.env
TimeoutStartSec=900
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
```

意図的にそうしている点：

- **`ExecStartPre` の先頭の `-`** … ビルド失敗を無視する指定。`npm run build` は `tsc -b && vite build` なので型エラーで落ちるが、その場合も**前回ビルド済みの `frontend/dist` を配信してアプリは生かす**。画面が古いより常駐が止まる方が困る、という判断。
- **`WorkingDirectory` を `backend` にする** … `reading.db` が cwd 基準で解決されるため。`./run.sh` も `cd backend` してから uvicorn を起動するので、手起動時と同じ DB を使う。
- **`--env-file backend/.env`** … `GOOGLE_BOOKS_API_KEY` の渡し方を `run.sh` と揃えてある。uvicorn が `os.environ` に載せてから app を import するので、`booklookup.py` の import 時読み取りに間に合う。
- **`Environment=PATH` で nvm のパスを明示** … `node` / `npm` は nvm 配下にあり systemd の PATH には入らない。**nvm で Node を上げたらこのパスも更新すること**（`ls ~/.nvm/versions/node/`）。
- **`TimeoutStartSec=900`** … `ExecStartPre` のビルド時間を含むため長め（実測は 6 秒程度）。
- **`StartLimitBurst=5`** … 起動直後に落ち続ける場合は 5 回で諦めて停止し、無限リトライで CPU を焼かない。
- **`tailscale serve` は unit 化していない** … `tailscale serve --bg` は tailscaled 側に残る設定で、PC を再起動しても生きている。unit に入れると二重管理になる。

## つまずきポイント

- **`./run.sh serve` を使うと tailnet の出口が消える** … `cmd_serve` は終了時（Ctrl+C でも）に `ts_teardown` が走り、`tailscale serve --https=8765 off` を実行する。常駐用に作ってある出口まで消えるので、使ったあとは戻すこと:

  ```bash
  tailscale serve --bg --yes --https=8765 http://127.0.0.1:8765
  tailscale serve status   # 8765 の行が戻ったか確認
  ```

  なお `tailscale serve reset` は**絶対に使わない**（他プロジェクトの 443 → recall-app、8443 → IdeaPool の割り当てまで消える）。
- **`./run.sh` と同時に動かさない** … どちらも 8765 を掴む。`run.sh` の `check_port` が使用者を表示して中止してくれるので壊れはしないが、使うなら先に `systemctl --user stop notes-web`。
- **画面の変更が反映されていない** … `-` を付けているのでビルド失敗は静かに無視される。`journalctl --user -u notes-web | grep -iE "error|TS[0-9]"` でビルドログを確認する。
- **再起動しても上がってこない** … `loginctl show-user naoto | grep Linger` が `Linger=yes` か確認。no なら `loginctl enable-linger naoto`。
- **ユニットを書き換えたら** … `systemctl --user daemon-reload` してから `restart`。

## 導入時にやったこと（記録）

```bash
systemctl --user daemon-reload
systemctl --user enable --now notes-web.service     # linger は既に有効だった
tailscale serve --bg --yes --https=8765 http://127.0.0.1:8765

# 確認
curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/            # 200（画面）
curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/api/books   # 200（API）
curl -o /dev/null -w '%{http_code}\n' https://<host>:8765/              # 200（tailnet 経由）
kill -TERM <MainPID>                                                    # → 7 秒で自動復帰し 200 に戻ることを確認
```
