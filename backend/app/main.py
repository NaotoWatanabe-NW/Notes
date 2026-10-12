"""アプリの入口。ここから uvicorn で起動する"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from . import author_store, theme_store
from .database import Base, SessionLocal, add_missing_columns, engine
from .routers import (
    books, lookup, notes, recommendations, reviews, settings, suggestions, tags, topics,
)

# frontend/dist（npm run build の出力）。backend/app/main.py から2つ上が Notes/
DIST_DIR = (Path(__file__).resolve().parents[2] / "frontend" / "dist").resolve()


_OFF_VALUES = {"0", "false", "off", "no"}


def env_enabled(name: str) -> bool:
    """環境変数 `name` が「止める」値でなければ True（未設定も True）。

    止める値は `0` `false` `off` `no`（大文字小文字・前後の空白は無視）。`0` だけだと、
    `=false` と書いた人の意図に反して止まらず、ノートを書き換え続けてしまう。
    """
    return os.environ.get(name, "1").strip().lower() not in _OFF_VALUES


@asynccontextmanager
async def lifespan(app: FastAPI):
    """起動時に一度だけ走る処理。

    テーブルがなければ作る（すでにあれば何もしない）。
    import しただけで DB ファイルができると、テストが本番の reading.db を
    触ってしまうので、起動時まで遅らせている。
    """
    Base.metadata.create_all(bind=engine)
    # 既存のテーブルに後から足した列（create_all では反映されない）
    add_missing_columns(engine)
    # テーマノート（reports/themes/）と著者ノート（reports/authors/）の一覧を数秒ごとに書き直す。
    # NOTES_THEMES_WATCH=0 で両方止まる（一時的にファイルを触らせたくないとき）。
    # NOTES_AUTHORS_WATCH=0 で著者ノートだけ止まる（ノートの自動作成を止めたいとき）。
    # 0 のほか false / off / no でも止まる
    watcher = None
    if env_enabled("NOTES_THEMES_WATCH"):
        jobs = [theme_store.rebuild]
        if env_enabled("NOTES_AUTHORS_WATCH"):
            jobs.append(author_store.rebuild)
        watcher = theme_store.ThemeWatcher(SessionLocal, jobs=jobs)
        watcher.start()
    yield
    if watcher is not None:
        watcher.stop()


app = FastAPI(title="読書ノート API", lifespan=lifespan)

# ① API を先に登録する。順番が逆だと、下のキャッチオールが /api/... まで
#    飲み込んでしまう（FastAPI は登録した順にパスを照合するため）
app.include_router(books.router)
app.include_router(lookup.router)
app.include_router(notes.book_notes_router)
app.include_router(notes.notes_router)
app.include_router(reviews.router)
app.include_router(settings.router)
app.include_router(suggestions.router)
app.include_router(tags.router)
app.include_router(topics.router)
app.include_router(recommendations.router)


# ② 最後に登録する ＝ 他のどのルートにも一致しなかったときだけ通る。
#    開発中は Vite dev server を使うので、ここは日常利用（ビルド済み）専用。
@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str):
    """ビルド済みのフロントエンドを配信する。

    画面遷移はブラウザ側で行う（SPA）ので、実在しないパスでも index.html を
    返して React に任せる。ただし /api/... だけは 404 にする。存在しない API を
    index.html で返すと、フロント開発中に原因が分からなくなるため。
    """
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="見つかりません")

    if not DIST_DIR.is_dir():
        raise HTTPException(
            status_code=404,
            detail="フロントエンドがまだビルドされていません（cd frontend && npm run build）",
        )

    # /assets/index-xxxx.js のように実在するファイルはそのまま返す。
    # resolve() + is_relative_to で dist の外に出る細工を防ぐ。
    if full_path:
        candidate = (DIST_DIR / full_path).resolve()
        if candidate.is_relative_to(DIST_DIR) and candidate.is_file():
            return FileResponse(candidate)

    # index.html は毎回サーバーに確かめさせる（no-cache）。古い index.html が残ると、
    # デプロイ後も前のビルドの JS を読み続け、消した API を呼んで画面が空になる
    # （2026-10-04、スマホで「おすすめが出ない」になった）。assets/ は名前にハッシュが
    # 付いて中身が変われば名前も変わるので、キャッシュさせてよい
    return FileResponse(DIST_DIR / "index.html", headers={"Cache-Control": "no-cache"})
