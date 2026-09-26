#!/usr/bin/env bash
#
# 読書ノートアプリの起動スクリプト。
#
#   ./run.sh          開発モード（ホットリロードあり。ターミナル1つで両方動く）
#   ./run.sh serve    Tailscale 経由で他の端末から使う（HTTPS。いちばん安全）
#   ./run.sh start    このPC/LAN から使う（ビルドして FastAPI 1プロセスで配信）
#   ./run.sh test     テストと型チェック
#   ./run.sh setup    依存をインストール（初回や、依存を足したとき）
#
# ポートを変えたいとき:
#   API_PORT=8010 ./run.sh
#
# 既定は API 8765 / 画面 5765。よく使われる 8000・8080 や Vite の既定の 5173 を
# 避けてある（他のプロジェクトのサーバーとぶつかりやすいため）。
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
API_PORT="${API_PORT:-8765}"
WEB_PORT="${WEB_PORT:-5765}"
# Tailscale の HTTPS を出すポート。443 と 8443 は他のプロジェクトが使っているので避ける
TS_PORT="${TS_PORT:-8765}"
# 使い方の案内にそのまま出すための、呼ばれ方の記録
COMMAND="${1:-}"

# backend/.env があれば読ませる（GOOGLE_BOOKS_API_KEY などを置く場所）
ENV_FILE=""
[ -f "$ROOT/backend/.env" ] && ENV_FILE="--env-file $ROOT/backend/.env"

# ── 画面に出す文字の色。対話的なターミナルのときだけ色を付ける ──────────
if [ -t 1 ]; then
  BOLD=$'\e[1m'; DIM=$'\e[2m'; RED=$'\e[31m'; GREEN=$'\e[32m'; CYAN=$'\e[36m'; OFF=$'\e[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; CYAN=""; OFF=""
fi

info()  { printf '%s\n' "${CYAN}▸${OFF} $*"; }
ok()    { printf '%s\n' "${GREEN}✓${OFF} $*"; }
warn()  { printf '%s\n' "${RED}!${OFF} $*" >&2; }
die()   { warn "$*"; exit 1; }

# ── 事前チェック ────────────────────────────────────────────────────
need_backend() {
  [ -x "$VENV/bin/uvicorn" ] ||
    die "Python の依存が入っていません。先に ${BOLD}./run.sh setup${OFF} を実行してください。"
}

need_frontend() {
  [ -d "$ROOT/frontend/node_modules" ] ||
    die "npm の依存が入っていません。先に ${BOLD}./run.sh setup${OFF} を実行してください。"
}

# そのポートを使っているプロセスがいるか。いたら誰かを教えて止める。
# 勝手に kill しない（他のプロジェクトのサーバーかもしれないため）
check_port() {
  local port="$1" label="$2"
  local users
  users="$(ss -ltnp 2>/dev/null | awk -v p=":$port\$" '$4 ~ p' || true)"
  [ -n "$users" ] || return 0

  warn "ポート ${BOLD}$port${OFF}（$label）はすでに使われています:"
  printf '%s\n' "$DIM$users$OFF" >&2
  warn "別のポートを使うか、上のプロセスを止めてください:"
  warn "  ${BOLD}API_PORT=8010 $0 $COMMAND${OFF}"
  exit 1
}

# 起動した子プロセスを、Ctrl+C でも終了時でもまとめて止める
PIDS=()
cleanup() {
  trap - INT TERM EXIT
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  # 子が落ちきるのを待つ（待たないと端末が汚れる）
  wait 2>/dev/null || true
  printf '\n'
  ok "停止しました"
}

# API が応答を返すまで待つ。返らなければ諦める
wait_for_api() {
  for _ in $(seq 1 60); do
    curl -sf -o /dev/null "http://127.0.0.1:$API_PORT/api/books" && return 0
    sleep 0.5
  done
  return 1
}

# ── Tailscale ───────────────────────────────────────────────────────

# tailnet 内での自分の名前（MagicDNS）。取れなければ空
ts_dnsname() {
  tailscale status --json 2>/dev/null |
    python3 -c 'import sys,json;print((json.load(sys.stdin).get("Self") or {}).get("DNSName","").rstrip("."))' 2>/dev/null || true
}

# そのポートが、すでに別の用途で使われていないか。
# このPCでは 443 と 8443 が他のプロジェクトに使われている。
# 知らずに上書きすると、そちらが止まってしまう
ts_port_taken_by_other() {
  tailscale serve status --json 2>/dev/null | python3 -c '
import sys, json
port = sys.argv[1]
try:
    tcp = (json.load(sys.stdin) or {}).get("TCP") or {}
except Exception:
    sys.exit(1)
sys.exit(0 if port in tcp else 1)
' "$TS_PORT"
}

# serve の設定を変えるには権限が要る。operator が自分なら sudo 無しで通る。
# 「使われていない出口を外す」は何も壊さないので、これで権限だけ試す。
# ただし**出口がもともと無いときは失敗する**ので、その失敗は権限の問題と区別する。
# （区別しないと、初回に必ず「権限がありません」と出て先へ進めない）
ts_can_configure() {
  local out
  out="$(tailscale serve --https="$TS_PORT" off 2>&1)" && return 0
  printf '%s' "$out" | grep -qi 'handler does not exist' && return 0
  return 1
}

ts_teardown() {
  # **自分が足した1つだけ**を消す。`tailscale serve reset` は
  # 他のプロジェクトの設定まで消えるので絶対に使わない
  tailscale serve --https="$TS_PORT" off >/dev/null 2>&1 || true
}

# 他の端末から開くURLも出す。IPより名前のほうが打ちやすいので
# MagicDNS の名前を優先し、取れなければ Tailscale の IP を出す
print_urls() {
  local port="$1"
  printf '\n'
  ok "このPCから:   ${BOLD}http://localhost:$port${OFF}"

  local host
  host="$(ts_dnsname)"
  [ -n "$host" ] || host="$(tailscale ip -4 2>/dev/null | head -1 || true)"
  if [ -n "$host" ]; then
    ok "他の端末から: ${BOLD}http://$host:$port${OFF}  ${DIM}(Tailscale)${OFF}"
  fi
  printf '%s\n\n' "${DIM}   API のドキュメント: http://localhost:$API_PORT/docs   —   Ctrl+C で終了${OFF}"
}

# ── 各コマンド ──────────────────────────────────────────────────────

cmd_setup() {
  info "Python の仮想環境を用意します"
  [ -d "$VENV" ] || python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r "$ROOT/backend/requirements.txt"
  ok "Python の依存をインストールしました"

  info "npm の依存をインストールします（少し時間がかかります）"
  (cd "$ROOT/frontend" && npm install)
  ok "npm の依存をインストールしました"

  printf '\n'
  ok "準備ができました。${BOLD}./run.sh${OFF} で開発モードが起動します。"
}

# 開発モード: API と Vite を両方立てる。画面は Vite が配信し、/api を API に中継する
cmd_dev() {
  need_backend
  need_frontend
  check_port "$API_PORT" "API"
  check_port "$WEB_PORT" "画面"

  trap cleanup INT TERM EXIT

  info "API を起動します（127.0.0.1:$API_PORT・ファイルを保存すると再読み込み）"
  # cwd を backend にする。reading.db がそこにできる
  (cd "$ROOT/backend" && exec "$VENV/bin/uvicorn" app.main:app --reload --port "$API_PORT" $ENV_FILE) &
  PIDS+=($!)

  wait_for_api || die "API が起動しませんでした。上のログを確認してください。"
  ok "API が起動しました"

  info "画面を起動します（0.0.0.0:$WEB_PORT）"
  # API_PORT を渡す。vite.config.ts がこれを見てプロキシ先を決める
  (cd "$ROOT/frontend" && API_PORT="$API_PORT" exec npm run dev -- --port "$WEB_PORT" --strictPort) &
  PIDS+=($!)

  print_urls "$WEB_PORT"

  # どちらかが落ちたら、もう片方も止めて終わる
  wait -n
  warn "プロセスが終了したので、まとめて停止します"
}

# 日常利用モード: ビルドした静的ファイルを FastAPI から配信する（1プロセス）
cmd_start() {
  need_backend
  need_frontend
  check_port "$API_PORT" "API"

  info "画面をビルドします"
  (cd "$ROOT/frontend" && npm run build)
  ok "ビルドしました"

  trap cleanup INT TERM EXIT

  info "起動します（0.0.0.0:$API_PORT）"
  warn "このモードは ${BOLD}同じLANの誰からも${OFF} 見えます（認証はありません）。"
  warn "外から使うなら ${BOLD}./run.sh serve${OFF} の方が安全です（tailnet 内のみ・HTTPS）。"
  # 0.0.0.0 で待ち受ける。家の中で使うぶんには足りる
  (cd "$ROOT/backend" && exec "$VENV/bin/uvicorn" app.main:app --host 0.0.0.0 --port "$API_PORT" $ENV_FILE) &
  PIDS+=($!)

  wait_for_api || die "起動できませんでした。上のログを確認してください。"
  print_urls "$API_PORT"
  wait
}

# Tailscale 経由で他の端末から使う。
# アプリは 127.0.0.1 でだけ待ち受け、外への出口は Tailscale が持つ。
# LAN（喫茶店のWi-Fiなど）からは見えないので、認証の無いこのアプリには
# いちばん合っている。
cmd_serve() {
  need_backend
  need_frontend

  command -v tailscale >/dev/null ||
    die "tailscale が見つかりません。${BOLD}./run.sh start${OFF} を使ってください。"
  tailscale status >/dev/null 2>&1 ||
    die "Tailscale が動いていません。${BOLD}tailscale up${OFF} を実行してください。"

  local dns
  dns="$(ts_dnsname)"
  [ -n "$dns" ] || die "tailnet 内の名前を取れませんでした（MagicDNS は有効ですか）。"

  if ts_port_taken_by_other; then
    warn "ポート ${BOLD}$TS_PORT${OFF} は Tailscale ですでに別の用途に使われています:"
    tailscale serve status 2>/dev/null | sed "s/^/$DIM  /;s/\$/$OFF/" >&2
    warn "上書きするとそちらが止まります。別のポートを指定してください:"
    warn "  ${BOLD}TS_PORT=10000 $0 serve${OFF}"
    exit 1
  fi

  if ! ts_can_configure; then
    warn "Tailscale の設定を変える権限がありません。次のどちらかを一度だけ実行してください:"
    warn "  ${BOLD}sudo tailscale set --operator=$USER${OFF}   # 以後 sudo なしで使える（おすすめ）"
    warn "  ${BOLD}sudo tailscale serve --bg --https=$TS_PORT http://127.0.0.1:$API_PORT${OFF}"
    exit 1
  fi

  check_port "$API_PORT" "API"

  info "画面をビルドします"
  (cd "$ROOT/frontend" && npm run build)
  ok "ビルドしました"

  trap 'ts_teardown; cleanup' INT TERM EXIT

  info "アプリを起動します（127.0.0.1:$API_PORT・外には直接出しません）"
  (cd "$ROOT/backend" && exec "$VENV/bin/uvicorn" app.main:app --port "$API_PORT" $ENV_FILE) &
  PIDS+=($!)
  wait_for_api || die "起動できませんでした。上のログを確認してください。"

  info "Tailscale に出口を作ります（tailnet 内のみ）"
  if ! tailscale serve --bg --yes --https="$TS_PORT" "http://127.0.0.1:$API_PORT" >/dev/null 2>&1; then
    die "tailscale serve に失敗しました。${BOLD}tailscale serve status${OFF} で確認してください。"
  fi

  printf '\n'
  ok "他の端末から: ${BOLD}https://$dns:$TS_PORT${OFF}"
  ok "このPCから:   ${BOLD}http://localhost:$API_PORT${OFF}"
  printf '%s\n' "${DIM}   tailnet の中からだけ見えます（LAN・インターネットには出していません）${OFF}"
  printf '%s\n\n' "${DIM}   Ctrl+C で停止し、Tailscale の出口も外します${OFF}"

  wait
}

cmd_test() {
  need_backend
  info "バックエンドのテスト"
  (cd "$ROOT/backend" && "$VENV/bin/pytest" -q)
  if [ -d "$ROOT/frontend/node_modules" ]; then
    info "フロントエンドの型チェック"
    (cd "$ROOT/frontend" && npx tsc -b)
    ok "型チェックを通りました"
  fi
}

cmd_help() {
  cat <<EOF
${BOLD}読書ノートアプリ${OFF}

  ${BOLD}./run.sh${OFF}          開発モード。API と画面を両方立てる（ホットリロードあり）
  ${BOLD}./run.sh serve${OFF}    Tailscale 経由で他の端末から使う（HTTPS・tailnet 内のみ）
  ${BOLD}./run.sh start${OFF}    このPC/LAN から使う。ビルドして1プロセスで配信する
  ${BOLD}./run.sh test${OFF}     テストと型チェック
  ${BOLD}./run.sh setup${OFF}    依存をインストールする（初回・依存を足したとき）

環境変数:
  API_PORT   API のポート（既定 $API_PORT）
  WEB_PORT   開発モードの画面のポート（既定 $WEB_PORT）
  TS_PORT    Tailscale の HTTPS ポート（既定 $TS_PORT）

例:
  API_PORT=8010 ./run.sh        既定のポートが埋まっているとき
EOF
}

case "${1:-dev}" in
  dev|"")       cmd_dev ;;
  serve)        cmd_serve ;;
  start|prod)   cmd_start ;;
  test)         cmd_test ;;
  setup)        cmd_setup ;;
  help|-h|--help) cmd_help ;;
  *)            warn "知らないコマンド: $1"; printf '\n'; cmd_help; exit 1 ;;
esac
