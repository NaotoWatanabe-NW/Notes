"""一回限りのスクリプト scripts/drop_unused_columns.py のテスト

DB にあってモデルに無い列（books.report_md）を消すスクリプト（設計書 0004）。
DB は tmp_path の実ファイル（本番と同じ WAL）、レポートは conftest.py が `NOTES_REPORTS_DIR` を
向けた `tmp_path/reports` の実ファイルで置き、`main()` を呼んで結果（DB・ファイル・出力）を見る。
ファイルと DB の I/O がこのスクリプトの本体なのでモックしない。差し込むのは、作れない失敗
（写しの検査・DROP 後の検査の失敗）、ロックの待ち時間、SQLite の版、ロックを持っている間の
割り込みの観察だけ。ディスクが足りない失敗は、プロセスのファイルサイズ上限（RLIMIT_FSIZE）を
下げて本物の書き込みエラーにする（`file_size_limit`。Python は SIGXFSZ を無視するので
プロセスは落ちず、書き込みが EFBIG で失敗する）。
`main()` には必ず `--db` と `--backup-dir` を渡す（既定は本番の `backend/reading.db` と `backup/`）。
スクリプトは import できる場所（パッケージ）に無いので、パスから読み込む。
"""

import contextlib
import importlib.util
import re
import resource
import shlex
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect

from app import report_store
from app.database import Base, add_missing_columns, configure_sqlite

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "drop_unused_columns.py"

_spec = importlib.util.spec_from_file_location("drop_unused_columns", SCRIPT)
drop = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drop)

NOW = "2026-10-11 21:00:00.000000"
COVER = bytes(range(256)) * 4   # 表紙の BLOB（バイト列がそのまま残ることを見る）

# (id, 書名, report_md)。3 冊目は本文を持たない
BOOKS = [
    (1, "失敗の本質", "## 第1章\n旧い本文その1\n"),
    (2, "統計学入門", "## メモ\n旧い本文その2\n"),
    (3, "本文のない本", None),
]


# ── 準備 ────────────────────────────────────────────────────

def make_db(tmp_path, books, extra_sql=()) -> Path:
    """2026-10-11 より前の版の DB（books.report_md がある）を tmp_path に作る。"""
    path = tmp_path / "reading.db"
    engine = create_engine(f"sqlite:///{path}")
    configure_sqlite(engine)   # 本番と同じ WAL
    Base.metadata.create_all(engine)
    # プールの接続が共有ロックを持ち続けると、スクリプトが「DB を開いているプロセスがある」で止まる
    engine.dispose()

    con = sqlite3.connect(path)
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        con.execute("ALTER TABLE books ADD COLUMN report_md TEXT")
        for book_id, title, report_md in books:
            con.execute(
                "INSERT INTO books (id, title, status, page, created_at, updated_at, report_md) "
                "VALUES (?, ?, 'reading', 10, ?, ?, ?)",
                (book_id, title, NOW, NOW, report_md),
            )
        first = books[0][0]
        con.execute("INSERT INTO tags (id, name) VALUES (1, '統計')")
        con.execute("INSERT INTO book_tags (book_id, tag_id) VALUES (?, 1)", (first,))
        con.execute(
            "INSERT INTO notes (book_id, kind, page, text, memo, created_at, updated_at) "
            "VALUES (?, 'quote', 12, '引用の本文', 'ひとこと', ?, ?)", (first, NOW, NOW))
        con.execute(
            "INSERT INTO book_covers (book_id, data, content_type, updated_at) "
            "VALUES (?, ?, 'image/jpeg', ?)", (first, COVER, NOW))
        for sql in extra_sql:
            con.execute(sql)
        con.commit()
    finally:
        con.close()
    return path


def put_report(book_id, title, body):
    report_store.save(SimpleNamespace(id=book_id, title=title), body)


def standard(tmp_path) -> Path:
    """BOOKS の DB と、本文のある 2 冊のレポート（DB の本文と同じ）。"""
    db = make_db(tmp_path, BOOKS)
    for book_id, title, report_md in BOOKS:
        if report_md:
            put_report(book_id, title, report_md)
    return db


def run(db, tmp_path, *args) -> int:
    return drop.main(["--db", str(db), "--backup-dir", str(tmp_path / "backup"), *args])


def output(capsys) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


def snapshot(db) -> dict:
    """テーブルごとの (列名, 全行) と、スキーマ（索引・ビューを含む）。"""
    con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        names = [name for (name,) in con.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name")]
        snap = {
            name: ([row[1] for row in con.execute(f'PRAGMA table_info("{name}")')],
                   con.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall())
            for name in names
        }
        snap["__schema__"] = con.execute(
            "SELECT type, name, sql FROM sqlite_schema ORDER BY type, name").fetchall()
        return snap
    finally:
        con.close()


def without_report_md(books_snapshot):
    """books の (列名, 行) から report_md の列を取り除いたもの。"""
    columns, rows = books_snapshot
    index = columns.index("report_md")
    return ([c for i, c in enumerate(columns) if i != index],
            [tuple(v for i, v in enumerate(row) if i != index) for row in rows])


def backups(tmp_path) -> list[Path]:
    return sorted((tmp_path / "backup").glob("reading-*.db"))


def read_all(db, sql, params=()):
    con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def book_columns(db) -> list[str]:
    return [row[1] for row in read_all(db, 'PRAGMA table_info("books")')]


def open_idle_connection(db) -> sqlite3.Connection:
    """アプリの接続プールにいるアイドルの接続。1回読んで開いたままにする。"""
    other = sqlite3.connect(db)
    other.execute("SELECT count(*) FROM books").fetchall()
    return other


@contextlib.contextmanager
def file_size_limit(limit: int):
    """このプロセスが書くファイルの大きさの上限を下げる（ディスク不足の再現）。抜けたら戻す。"""
    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, hard))
    try:
        yield
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))


def intrude(db) -> str:
    """別の接続で DB を読んでみる。ロックを持ち続けていれば 'database is locked'。"""
    intruder = sqlite3.connect(db, timeout=0.1)
    try:
        intruder.execute("SELECT count(*) FROM books").fetchall()
        return "読めた"
    except sqlite3.OperationalError as error:
        return str(error)
    finally:
        intruder.close()


def orphan_an_index(path, index_name):
    """索引の定義だけを消して、索引のページを孤児にする。integrity_check が ok 以外の行を
    返す（例外にはならない）壊れ方。"""
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA writable_schema=ON")
        con.execute("DELETE FROM sqlite_schema WHERE type = 'index' AND name = ?", (index_name,))
        con.commit()
    finally:
        con.close()


# ── 下見 ────────────────────────────────────────────────────

def test_下見はDBを変えず消す列と本文の突き合わせを表示する(tmp_path, capsys):
    db = standard(tmp_path)
    before, before_bytes = snapshot(db), db.read_bytes()

    assert run(db, tmp_path) == 0

    out = output(capsys)
    assert snapshot(db) == before
    assert db.read_bytes() == before_bytes
    assert backups(tmp_path) == []
    assert "books.report_md" in out
    assert "値あり 2 行" in out          # NULL の 3 冊目は数えない
    assert "本文がある本: 2 冊" in out
    assert "ファイルあり 2 冊（本文が同じ 2 冊・違う 0 冊" in out
    assert "DROP COLUMN の試し（メモリ上の写し）: ok" in out
    assert "--apply" in out


def test_下見はほかの接続がDBを開いていても動く(tmp_path, capsys):
    db = standard(tmp_path)
    before = snapshot(db)
    other = open_idle_connection(db)
    try:
        code = run(db, tmp_path)
    finally:
        other.close()

    assert code == 0
    assert snapshot(db) == before


# ── --apply ─────────────────────────────────────────────────

def test_applyでreport_md列が消え他の列と行はそのまま(tmp_path, capsys):
    db = standard(tmp_path)
    before = snapshot(db)

    assert run(db, tmp_path, "--apply") == 0

    after = snapshot(db)
    assert "report_md" not in after["books"][0]
    assert set(after["books"][0]) == {c.name for c in Base.metadata.tables["books"].columns}
    assert after["books"] == without_report_md(before["books"])
    # 表紙の BLOB・引用・タグを含む、ほかのテーブルは1行も変わらない
    others = [name for name in before if name not in ("books", "__schema__")]
    assert others, "books 以外のテーブルが無いと比べられない"
    for name in others:
        assert after[name] == before[name], name
    assert after["book_covers"][1][0][1] == COVER
    # books の表の定義以外のスキーマ（索引など）も変わらない
    assert [s for s in after["__schema__"] if s[1] != "books"] == \
        [s for s in before["__schema__"] if s[1] != "books"]
    out = output(capsys)
    assert "消した列: books.report_md" in out
    assert "integrity_check ok / foreign_key_check 不整合なし" in out


def test_applyは消す前の写しをbackupに取る(tmp_path, capsys):
    db = standard(tmp_path)

    assert run(db, tmp_path, "--apply") == 0

    [backup] = backups(tmp_path)
    assert re.fullmatch(r"reading-\d{8}-\d{6}\.db", backup.name)
    assert read_all(backup, "PRAGMA integrity_check") == [("ok",)]
    assert read_all(backup, "SELECT id, report_md FROM books ORDER BY id") == \
        [(book_id, report_md) for book_id, _, report_md in BOOKS]
    # 写しは1ファイルで完結している（-wal / -shm を連れていない）
    assert [p.name for p in (tmp_path / "backup").iterdir()] == [backup.name]
    assert f"写し: {backup}" in output(capsys)


def test_applyのあとVACUUMで空きページが残らない(tmp_path):
    big = [(book_id, f"長い本{book_id}", f"## 章\n{'本文' * 15000}\n") for book_id in range(1, 6)]
    db = make_db(tmp_path, big)
    for book_id, title, report_md in big:
        put_report(book_id, title, report_md)
    size_before = db.stat().st_size

    assert run(db, tmp_path, "--apply") == 0

    assert read_all(db, "PRAGMA freelist_count") == [(0,)]
    assert db.stat().st_size < size_before


def test_VACUUMに失敗しても列は消えたままDBは壊れず手で流すコマンドを出す(tmp_path, capsys, monkeypatch):
    big = [(book_id, f"長い本{book_id}", f"## 章\n{'本文' * 15000}\n") for book_id in range(1, 6)]
    db = make_db(tmp_path, big)
    for book_id, title, report_md in big:
        put_report(book_id, title, report_md)
    before = snapshot(db)
    disk = contextlib.ExitStack()
    real_drop = drop.drop_columns

    def drop_then_fill_the_disk(con, targets, *, commit):
        problems = real_drop(con, targets, commit=commit)
        # COMMIT が済んだあと、VACUUM が新しい DB を書くところで書き込みが失敗する
        disk.enter_context(file_size_limit(db.stat().st_size // 4))
        return problems

    monkeypatch.setattr(drop, "drop_columns", drop_then_fill_the_disk)
    try:
        code = run(db, tmp_path, "--apply")
    finally:
        disk.close()

    assert code == 1
    out = output(capsys)
    assert "VACUUM に失敗しました（列は消えています。DB は壊れていません）" in out
    assert str(db.resolve()) in out and "VACUUM" in out.split("次を流してください")[1]   # --db の DB を指す
    assert "backend/reading.db" not in out and "sqlite3 backend" not in out            # CLI にも既定の場所にも頼らない
    assert read_all(db, "PRAGMA integrity_check") == [("ok",)]
    after = snapshot(db)
    assert "report_md" not in after["books"][0]
    assert after["books"] == without_report_md(before["books"])


def test_消したあと起動時の列の追加を流してもreport_mdは戻らない(tmp_path):
    db = standard(tmp_path)
    assert run(db, tmp_path, "--apply") == 0

    engine = create_engine(f"sqlite:///{db}")
    try:
        Base.metadata.create_all(engine)    # アプリの lifespan と同じ順
        assert add_missing_columns(engine) == []
        columns = [c["name"] for c in inspect(engine).get_columns("books")]
    finally:
        engine.dispose()

    assert "report_md" not in columns


# ── レポートのファイルの確認 ────────────────────────────────

@pytest.mark.parametrize("args", [[], ["--apply"]], ids=["下見", "apply"])
def test_レポートのファイルが無い本があると何も変えずに止まる(tmp_path, capsys, args):
    books = [(1, "失敗の本質", "## 第1章\n本文\n"), (2, "統計学入門", "## 本文はDBにだけある\n")]
    db = make_db(tmp_path, books)
    put_report(1, "失敗の本質", books[0][2])   # 2 冊目のファイルは作らない
    before = snapshot(db)

    assert run(db, tmp_path, *args) == 1

    out = output(capsys)
    [line] = [l for l in out.splitlines() if "統計学入門" in l]
    assert "ファイルなし" in line and f"{2:4}" in line
    assert "失敗の本質" not in out.split("ファイルなし 1 冊")[1]   # ファイルのある本は挙げない
    assert "--allow-missing" in out
    assert snapshot(db) == before
    assert backups(tmp_path) == []


def test_本文が空のレポートファイルはファイルなしとして止まる(tmp_path, capsys):
    db = make_db(tmp_path, [(1, "失敗の本質", "## 第1章\n本文\n")])
    reports = report_store.reports_dir()
    reports.mkdir(parents=True)
    (reports / "0001-失敗の本質.md").write_text(
        "---\ntype: reading-report\nbook_id: 1\n---\n", encoding="utf-8")
    before = snapshot(db)

    assert run(db, tmp_path, "--apply") == 1

    assert "ファイルなし" in output(capsys)
    assert snapshot(db) == before
    assert backups(tmp_path) == []


def test_allow_missingを付けるとファイルが無くても消し本文は写しに残る(tmp_path, capsys):
    books = [(1, "失敗の本質", "## 第1章\n本文\n"), (2, "統計学入門", "## 本文はDBにだけある\n")]
    db = make_db(tmp_path, books)
    put_report(1, "失敗の本質", books[0][2])

    assert run(db, tmp_path, "--apply", "--allow-missing") == 0

    assert "report_md" not in book_columns(db)
    [backup] = backups(tmp_path)
    assert read_all(backup, "SELECT report_md FROM books WHERE id = 2") == [(books[1][2],)]
    out = output(capsys)
    assert "ファイルなし 1 冊（--allow-missing で通す）" in out
    assert "統計学入門" in out


def test_本文が違うだけなら止めずにどの本かを文字数つきで出す(tmp_path, capsys):
    db = standard(tmp_path)
    edited = "移管のあとで直した本文\n"
    put_report(1, "失敗の本質", edited)

    assert run(db, tmp_path, "--apply") == 0

    assert "report_md" not in book_columns(db)
    out = output(capsys)
    assert "違う 1 冊" in out
    [line] = [l for l in out.splitlines() if l.startswith("  ~")]
    assert f"{1:4} 失敗の本質" in line
    assert f"DB {len(BOOKS[0][2].strip())} 文字 / ファイル {len(edited.strip())} 文字" in line
    assert "統計学入門" not in line     # 同じ本は挙げない
    assert "ずっと短い" not in line      # 直しただけ（半分以上ある）の本には印を付けない


def test_ファイルがDBの本文よりずっと短い本には印を付けるが止めない(tmp_path, capsys):
    long_body = "## 長い章\n" + "本文" * 2000 + "\n"
    db = make_db(tmp_path, [(1, "長いレポート", long_body)])
    put_report(1, "長いレポート", "TODO\n")   # 中身が置き換わってしまったファイル

    assert run(db, tmp_path, "--apply") == 0

    out = output(capsys)
    [line] = [l for l in out.splitlines() if l.startswith("  ~")]
    assert f"DB {len(long_body.strip())} 文字 / ファイル 4 文字" in line
    assert "ファイルのほうがずっと短い" in line
    [backup] = backups(tmp_path)
    assert read_all(backup, "SELECT report_md FROM books") == [(long_body,)]   # 本文は写しに残る


def test_report_mdがNULLや空白だけの本はファイルが無くても止めない(tmp_path, capsys):
    db = make_db(tmp_path, [(1, "NULLの本", None), (2, "空文字の本", ""), (3, "空白だけの本", "  \n")])
    assert not report_store.reports_dir().exists()

    assert run(db, tmp_path, "--apply") == 0

    assert "report_md" not in book_columns(db)
    assert "本文がある本: 0 冊" in output(capsys)


# ── ロック ──────────────────────────────────────────────────

def test_ほかの接続がDBを開いているとapplyは止まり何も変えない(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(drop, "LOCK_TIMEOUT_SECONDS", 0.1)
    db = standard(tmp_path)
    before = snapshot(db)
    other = open_idle_connection(db)   # BEGIN EXCLUSIVE だけでは見つからない、アイドルの接続
    try:
        code = run(db, tmp_path, "--apply")
    finally:
        other.close()

    assert code == 1
    out = output(capsys)
    assert "systemctl --user stop notes-web" in out
    assert "database is locked" in out
    assert snapshot(db) == before
    assert backups(tmp_path) == []


def test_applyはロックを取ってから終わるまで放さず別の接続は割り込めない(tmp_path, monkeypatch):
    db = standard(tmp_path)
    intrusions = {}
    real_verify, real_drop, real_extras = drop.verify_backup, drop.drop_columns, drop.extra_columns
    extras_calls = []

    def verify_and_intrude(path, expected):
        intrusions["写しの検査"] = intrude(db)
        return real_verify(path, expected)

    def drop_and_intrude(con, targets, *, commit):
        intrusions["DROP の直前"] = intrude(db)
        return real_drop(con, targets, commit=commit)

    def extras_and_intrude(con):
        extras_calls.append(1)
        if len(extras_calls) == 2:   # 1回目は main の最初。2回目が VACUUM のあとの確認
            intrusions["VACUUM のあと"] = intrude(db)
        return real_extras(con)

    monkeypatch.setattr(drop, "verify_backup", verify_and_intrude)
    monkeypatch.setattr(drop, "drop_columns", drop_and_intrude)
    monkeypatch.setattr(drop, "extra_columns", extras_and_intrude)

    assert run(db, tmp_path, "--apply") == 0

    assert intrusions == {"写しの検査": "database is locked",
                          "DROP の直前": "database is locked",
                          "VACUUM のあと": "database is locked"}


def test_ロック以外の理由でDBを書き込み用に開けないときはアプリを止める案内をしない(tmp_path, capsys, monkeypatch):
    db = standard(tmp_path)
    before = snapshot(db)

    def refuse(path):
        # 権限エラーの代わりに、ロックではない本物の OperationalError（SQLITE_ERROR）
        sqlite3.connect(":memory:").execute("SELECT * FROM no_such_table")

    monkeypatch.setattr(drop, "_open_exclusive", refuse)

    assert run(db, tmp_path, "--apply") == 1

    out = output(capsys)
    assert "DB を書き込み用に開けません" in out and "no such table" in out
    assert "systemctl" not in out and "開いているプロセス" not in out
    assert snapshot(db) == before
    assert backups(tmp_path) == []


# ── 許可リスト ──────────────────────────────────────────────

def test_許可リストに無いモデル外の列は消さずに名前を出す(tmp_path, capsys):
    db = make_db(tmp_path, BOOKS, extra_sql=[
        "ALTER TABLE books ADD COLUMN report_html TEXT",
        "UPDATE books SET report_html = '<p>HTML 時代の本文</p>' WHERE id = 1",
        "ALTER TABLE notes ADD COLUMN legacy INTEGER",
        "UPDATE notes SET legacy = 7",
    ])
    for book_id, title, report_md in BOOKS:
        if report_md:
            put_report(book_id, title, report_md)

    assert run(db, tmp_path, "--apply") == 0

    assert "report_md" not in book_columns(db)
    assert "report_html" in book_columns(db)
    assert read_all(db, "SELECT id, report_html FROM books ORDER BY id") == \
        [(1, "<p>HTML 時代の本文</p>"), (2, None), (3, None)]
    assert read_all(db, "SELECT legacy FROM notes") == [(7,)]
    out = output(capsys)
    for line in ("books.report_html（TEXT、値あり 1 行）… 消さない",
                 "notes.legacy（INTEGER、値あり 1 行）… 消さない",
                 "books.report_md（TEXT、値あり 2 行）… 消す"):
        assert line in out


def test_許可リストに無い列しかなければ何も消さず終了コード0(tmp_path, capsys):
    db = make_db(tmp_path, BOOKS, extra_sql=[
        "ALTER TABLE books DROP COLUMN report_md",
        "ALTER TABLE books ADD COLUMN report_html TEXT",
    ])
    before = snapshot(db)

    assert run(db, tmp_path, "--apply") == 0

    out = output(capsys)
    assert "books.report_html" in out and "消さない" in out
    assert "消すものはありません。" in out
    assert snapshot(db) == before
    assert backups(tmp_path) == []


# ── 冪等・入口の確認 ────────────────────────────────────────

def test_2回目のapplyは消すものなしで終了コード0になり写しを増やさない(tmp_path, capsys):
    db = standard(tmp_path)
    assert run(db, tmp_path, "--apply") == 0
    after_first = snapshot(db)
    mtime = db.stat().st_mtime_ns
    capsys.readouterr()

    assert run(db, tmp_path, "--apply") == 0

    out = output(capsys)
    assert "消すものはありません" in out
    assert "空きページ" not in out     # VACUUM が済んでいるので、知らせることは無い
    assert len(backups(tmp_path)) == 1
    assert snapshot(db) == after_first
    assert db.stat().st_mtime_ns == mtime   # VACUUM もしていない


def test_消すものが無くても空きページが残っていればapplyは知らせるがVACUUMはしない(tmp_path, capsys):
    # 列は消えたのに VACUUM が途中で止まった DB（消した本文のバイトが空きページに残っている）
    big = [(book_id, f"長い本{book_id}", f"## 章\n{'本文' * 15000}\n") for book_id in range(1, 6)]
    db = make_db(tmp_path, big, extra_sql=["ALTER TABLE books DROP COLUMN report_md"])
    [(free_pages,)] = read_all(db, "PRAGMA freelist_count")
    assert free_pages > 0, "空きページが無いと、知らせるかどうかを見られない"
    before = snapshot(db)

    assert run(db, tmp_path, "--apply") == 0

    out = output(capsys)
    assert "モデルに無い列はありません。消すものはありません。" in out
    assert f"空きページが {free_pages} 個あります" in out
    assert "VACUUM" in out and str(db.resolve()) in out    # 流すコマンドは --db の DB を指す
    assert read_all(db, "PRAGMA freelist_count") == [(free_pages,)]   # 知らせるだけで、勝手に VACUUM しない
    assert snapshot(db) == before
    assert backups(tmp_path) == []

    # 案内されたコマンドをそのまま流すと空きページが無くなる（先頭の .venv/bin/python だけ今の python にする）
    [command] = [line.strip() for line in out.splitlines() if line.strip().startswith(".venv/bin/python")]
    _, flag, code = shlex.split(command)
    subprocess.run([sys.executable, flag, code], check=True)
    assert read_all(db, "PRAGMA freelist_count") == [(0,)]


@pytest.mark.parametrize("args", [[], ["--apply"]], ids=["下見", "apply"])
def test_存在しないDBを指定するとDBを作らずに終了コード1(tmp_path, capsys, args):
    missing = tmp_path / "nothing.db"

    assert run(missing, tmp_path, *args) == 1

    assert "DB が見つかりません" in output(capsys)
    assert not missing.exists()
    assert not (tmp_path / "backup").exists()


@pytest.mark.parametrize("args", [[], ["--apply"]], ids=["下見", "apply"])
def test_SQLiteのファイルでないものを指定すると読めないと伝えて何も変えない(tmp_path, capsys, args):
    not_db = tmp_path / "not-a-db.db"
    not_db.write_bytes("SQLite ではないバイト列".encode() * 500)
    before = not_db.read_bytes()

    assert run(not_db, tmp_path, *args) == 1

    out = output(capsys)
    assert "DB を読めません" in out and "file is not a database" in out
    assert "DB は変えていません" in out
    assert not_db.read_bytes() == before
    assert not (tmp_path / "backup").exists()


@pytest.mark.parametrize("args", [[], ["--apply"]], ids=["下見", "apply"])
def test_表のページが壊れていて途中で読めなくなっても読めないと伝えて何も変えない(tmp_path, capsys, args):
    db = standard(tmp_path)
    [(root_page,)] = read_all(db, "SELECT rootpage FROM sqlite_schema WHERE name = 'books'")
    [(page_size,)] = read_all(db, "PRAGMA page_size")
    with open(db, "r+b") as f:
        f.seek((root_page - 1) * page_size)
        f.write(b"\x00")      # b-tree のページの種類を壊す。スキーマ（1ページ目）は読める
    before = db.read_bytes()

    assert run(db, tmp_path, *args) == 1

    out = output(capsys)
    assert "DB を読めません" in out and "malformed" in out
    assert "DB は変えていません" in out
    assert db.read_bytes() == before
    assert not (tmp_path / "backup").exists()


@pytest.mark.parametrize("args", [[], ["--apply"]], ids=["下見", "apply"])
@pytest.mark.parametrize("kind", ["空のファイル", "booksの無いDB"])
def test_booksテーブルの無いDBを指定すると何も書き込まずに終了コード1(tmp_path, capsys, args, kind):
    target = tmp_path / "other.db"
    if kind == "空のファイル":
        target.write_bytes(b"")
    else:
        con = sqlite3.connect(target)
        con.execute("CREATE TABLE memo (id INTEGER PRIMARY KEY, text TEXT)")
        con.commit()
        con.close()
    before = target.read_bytes()

    assert run(target, tmp_path, *args) == 1

    assert "books テーブルがありません" in output(capsys)
    assert target.read_bytes() == before     # 空のファイルを SQLite のヘッダで 4096 バイトにしない
    assert not (tmp_path / "backup").exists()


@pytest.mark.parametrize("args", [[], ["--apply"]], ids=["下見", "apply"])
def test_WALのファイルを作れずDBを開けないときはロックのせいにしない(tmp_path, capsys, args):
    db = standard(tmp_path)
    (tmp_path / "reading.db-wal").mkdir()   # -wal を作れない（ロックではない開けない理由）

    assert run(db, tmp_path, *args) == 1

    out = output(capsys)
    assert "DB を読めません" in out and "unable to open database file" in out
    assert "systemctl" not in out and "開いているプロセス" not in out
    assert not (tmp_path / "backup").exists()


@pytest.mark.parametrize("args", [[], ["--apply"]], ids=["下見", "apply"])
@pytest.mark.parametrize("version", [(3, 34, 1), (3, 35, 4)], ids=["3.34.1", "3.35.4"])
def test_SQLiteが3_35_5より古いと何も変えずに止まる(tmp_path, capsys, monkeypatch, args, version):
    # 3.35.0〜3.35.4 は DROP COLUMN が使えるが、DB を壊しうる不具合があった（3.35.5 で修正）
    db = standard(tmp_path)
    before = snapshot(db)
    text = ".".join(map(str, version))
    monkeypatch.setattr(drop.sqlite3, "sqlite_version_info", version)
    monkeypatch.setattr(drop.sqlite3, "sqlite_version", text)

    assert run(db, tmp_path, *args) == 1

    assert f"SQLite {text} では列を消せません（3.35.5 以上が必要）" in output(capsys)
    assert snapshot(db) == before
    assert backups(tmp_path) == []


def test_SQLiteが3_35_5ちょうどなら動く(tmp_path, monkeypatch):
    db = standard(tmp_path)
    monkeypatch.setattr(drop.sqlite3, "sqlite_version_info", (3, 35, 5))

    assert run(db, tmp_path) == 0


# ── 失敗したら DB を元のままにする ──────────────────────────

@pytest.mark.parametrize("args", [[], ["--apply"]], ids=["下見", "apply"])
def test_列を参照する索引があると消さずに索引の名前を出す(tmp_path, capsys, args):
    db = make_db(tmp_path, BOOKS, extra_sql=["CREATE INDEX ix_books_report_md ON books(report_md)"])
    for book_id, title, report_md in BOOKS:
        if report_md:
            put_report(book_id, title, report_md)
    before = snapshot(db)

    assert run(db, tmp_path, *args) == 1

    out = output(capsys)
    assert "books.report_md を消せません" in out
    assert "この列を参照しているもの: index ix_books_report_md" in out
    assert "report_md" in book_columns(db)
    assert snapshot(db) == before
    assert len(backups(tmp_path)) == (1 if args else 0)   # apply は消す前に写しを取っている


@pytest.mark.parametrize("args", [[], ["--apply"]], ids=["下見", "apply"])
@pytest.mark.parametrize("trigger_sql, name", [
    ("CREATE TRIGGER clear_report AFTER UPDATE OF title ON books "
     "BEGIN UPDATE books SET report_md = NULL WHERE id = new.id; END", "clear_report"),
    ("CREATE TRIGGER clear_report_on_note AFTER INSERT ON notes "
     "BEGIN UPDATE books SET report_md = NULL WHERE id = new.book_id; END", "clear_report_on_note"),
], ids=["booksのトリガー", "別の表のトリガー"])
def test_列を本体で更新するトリガーがあると消さずにトリガーの名前を出す(tmp_path, capsys, args, trigger_sql, name):
    # SQLite はこの列の DROP を通すが、消したあとにそのトリガーが走る UPDATE が壊れる
    db = make_db(tmp_path, BOOKS, extra_sql=[trigger_sql])
    for book_id, title, report_md in BOOKS:
        if report_md:
            put_report(book_id, title, report_md)
    before = snapshot(db)

    assert run(db, tmp_path, *args) == 1

    out = output(capsys)
    assert "books.report_md を消せません" in out
    assert f"この列を参照しているもの: trigger {name}" in out
    assert "report_md" in book_columns(db)
    assert snapshot(db) == before


def test_写しの検査に通らなければ消さない(tmp_path, capsys, monkeypatch):
    db = standard(tmp_path)
    before = snapshot(db)
    # 壊れた写しは作れないので、検査が問題を返したことにする
    monkeypatch.setattr(drop, "verify_backup", lambda path, expected: ["作った不一致"])

    assert run(db, tmp_path, "--apply") == 1

    out = output(capsys)
    assert "写しの検査に通りません" in out and "作った不一致" in out
    assert "report_md" in book_columns(db)
    assert snapshot(db) == before
    assert len(backups(tmp_path)) == 1   # 調べるために写しは消さない


def test_DROP後の検査に通らなければROLLBACKして列は残る(tmp_path, capsys, monkeypatch):
    db = standard(tmp_path)
    before = snapshot(db)
    # DROP 後の不整合は起こせないので、検査が問題を返したことにする。
    # COMMIT より前に流れていなければ、列はもう消えている
    monkeypatch.setattr(drop, "_post_checks", lambda con, fk_before: ["作った不整合"])

    assert run(db, tmp_path, "--apply") == 1

    assert "作った不整合" in output(capsys)
    assert "report_md" in book_columns(db)
    assert snapshot(db) == before


def test_DROP後の検査を流せなければROLLBACKして列は残る(tmp_path, capsys, monkeypatch):
    db = standard(tmp_path)
    before = snapshot(db)

    def unreadable(con, fk_before):
        raise sqlite3.DatabaseError("database disk image is malformed")   # 検査中の読み出しの失敗

    monkeypatch.setattr(drop, "_post_checks", unreadable)

    assert run(db, tmp_path, "--apply") == 1

    out = output(capsys)
    assert "DROP のあとの検査を流せませんでした" in out and "malformed" in out
    assert "DB は変えていません（写しは" in out
    assert "report_md" in book_columns(db)
    assert snapshot(db) == before


def test_COMMITで書き込みに失敗してもROLLBACKして変えていませんと伝える(tmp_path, capsys, monkeypatch):
    db = standard(tmp_path)
    before = snapshot(db)
    real_drop = drop.drop_columns

    def drop_on_a_full_disk(con, targets, *, commit):
        # 小さい DB では DROP の変更はページキャッシュに収まり、WAL に書かれるのは COMMIT のとき。
        # 書き込みを本物のエラーにして、COMMIT を失敗させる
        with file_size_limit(0):
            return real_drop(con, targets, commit=commit)

    monkeypatch.setattr(drop, "drop_columns", drop_on_a_full_disk)

    assert run(db, tmp_path, "--apply") == 1

    out = output(capsys)
    assert "COMMIT に失敗しました" in out
    assert "DB は変えていません（写しは" in out
    assert "report_md" in book_columns(db)
    assert read_all(db, "PRAGMA integrity_check") == [("ok",)]
    assert snapshot(db) == before


def test_DROP後の検査はforeign_key_checkがDROP前と違えば問題を返す(tmp_path):
    db = make_db(tmp_path, BOOKS, extra_sql=[
        "INSERT INTO notes (book_id, kind, page, text, created_at, updated_at) "
        f"VALUES (999, 'memo', 1, '親の無いメモ', '{NOW}', '{NOW}')",
    ])
    con = sqlite3.connect(db)
    try:
        measured = set(con.execute("PRAGMA foreign_key_check"))
        assert len(measured) == 1, "親の無い行が1つ無いと比べられない"

        # DROP 前は不整合なしだったのに、いまは1件ある（増えた）
        [problem] = drop._post_checks(con, set())
        assert "foreign_key_check が DROP 前と違います" in problem and "増えた不整合 1 件" in problem
        # DROP 前にあった不整合が、いまは無い（なくなった）
        [problem] = drop._post_checks(con, measured | {("notes", 12345, "books", 0)})
        assert "なくなった不整合 1 件" in problem
        # 前からある不整合と同じなら問題にしない
        assert drop._post_checks(con, measured) == []
    finally:
        con.close()


def test_DROP後の検査はintegrity_checkがok以外なら問題を返す(tmp_path):
    db = make_db(tmp_path, BOOKS, extra_sql=["CREATE INDEX ix_notes_text ON notes(text)"])
    con = sqlite3.connect(db)
    try:
        assert drop._post_checks(con, set()) == []     # 壊す前は通る
    finally:
        con.close()
    orphan_an_index(db, "ix_notes_text")

    con = sqlite3.connect(db)
    try:
        [problem] = drop._post_checks(con, set())
    finally:
        con.close()

    assert "DROP のあとの integrity_check が ok ではありません" in problem and "never used" in problem


def test_残す列の中身がDROPの前後で違えば問題を返す(tmp_path):
    db = standard(tmp_path)
    con = sqlite3.connect(db)
    try:
        targets = [t for t in drop.extra_columns(con) if t.drop]
        before = drop._kept_content(con, targets)
        assert set(before) == {"books"}
        assert len(before["books"]) == 3
        assert "失敗の本質" in before["books"][0]            # 残す列の中身は入っている
        assert all(BOOKS[0][2] not in row for row in before["books"])   # 消す列（report_md）は入っていない
        assert drop._kept_changes(con, targets, before) == []     # 変わっていなければ通る

        # DROP COLUMN の不具合で、別の列の値がすり替わったことにする
        con.execute("UPDATE books SET title = '書き換わった書名' WHERE id = 1")
        [problem] = drop._kept_changes(con, targets, before)
    finally:
        con.close()

    assert "books の残す列の中身が DROP 前と違います" in problem


def test_前からある外部キーの不整合は警告するだけで止めない(tmp_path, capsys):
    db = make_db(tmp_path, BOOKS, extra_sql=[
        "INSERT INTO notes (book_id, kind, page, text, created_at, updated_at) "
        f"VALUES (999, 'memo', 1, '親の無いメモ', '{NOW}', '{NOW}')",
    ])
    for book_id, title, report_md in BOOKS:
        if report_md:
            put_report(book_id, title, report_md)

    assert run(db, tmp_path, "--apply") == 0

    assert "report_md" not in book_columns(db)
    out = output(capsys)
    assert "前からある外部キーの不整合 1 件" in out
    assert "foreign_key_check は消す前と同じ（前からの不整合 1 件）" in out


# ── 写しの作り方・検査 ──────────────────────────────────────

def test_同じ秒に写しを2回取っても上書きせず連番を付ける(tmp_path, monkeypatch):
    db = standard(tmp_path)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 12, 22, 30, 15)

    monkeypatch.setattr(drop, "datetime", FixedDatetime)
    con = sqlite3.connect(db)
    try:
        first = drop.make_backup(con, tmp_path / "backup")
        second = drop.make_backup(con, tmp_path / "backup")
    finally:
        con.close()

    assert first.name == "reading-20261012-223015.db"
    assert second.name == "reading-20261012-223015-2.db"


def test_写しの置き場所がファイルだと何も変えずに終了コード1で写しも残さない(tmp_path, capsys):
    db = standard(tmp_path)
    before = snapshot(db)
    (tmp_path / "backup").write_text("ディレクトリではなくファイル")

    assert run(db, tmp_path, "--apply") == 1

    out = output(capsys)
    assert "写しを取れませんでした" in out and "DB は変えていません" in out
    assert list(tmp_path.rglob("reading-*")) == []
    assert "report_md" in book_columns(db)
    assert snapshot(db) == before


def test_写しを取る途中でディスクが足りなくなっても正式な名前の写しは残らない(tmp_path, capsys, monkeypatch):
    db = standard(tmp_path)
    before = snapshot(db)
    real_backup = drop.make_backup
    created = []

    def backup_on_a_full_disk(con, backup_dir):
        # 写しの途中（元の DB より小さい大きさ）で書き込みが失敗する
        with file_size_limit(db.stat().st_size // 4):
            try:
                return real_backup(con, backup_dir)
            finally:
                created.extend(backup_dir.iterdir())

    monkeypatch.setattr(drop, "make_backup", backup_on_a_full_disk)

    assert run(db, tmp_path, "--apply") == 1

    out = output(capsys)
    assert "写しを取れませんでした" in out and "disk I/O error" in out
    assert "DB は変えていません" in out
    assert created == []                                   # 失敗した時点で .partial も -journal も片付いている
    assert list((tmp_path / "backup").iterdir()) == []
    assert "report_md" in book_columns(db)
    assert snapshot(db) == before


def test_写しは完成してから正式な名前になる(tmp_path, monkeypatch):
    db = standard(tmp_path)
    seen = []
    real_replace = drop.os.replace

    def replace_and_look(src, dst):
        # 改名の直前は、まだ .partial のまま。正式な名前のファイルは無い
        seen.append(sorted(p.name for p in (tmp_path / "backup").iterdir()))
        return real_replace(src, dst)

    monkeypatch.setattr(drop.os, "replace", replace_and_look)
    con = sqlite3.connect(db)
    try:
        backup = drop.make_backup(con, tmp_path / "backup")
    finally:
        con.close()

    assert len(seen) == 1 and len(seen[0]) == 1
    assert seen[0][0] == backup.name + ".partial"
    assert [p.name for p in (tmp_path / "backup").iterdir()] == [backup.name]


def test_写しの検査は値のある行数が元と違うと問題を返す(tmp_path):
    db = standard(tmp_path)
    con = sqlite3.connect(db)
    try:
        backup = drop.make_backup(con, tmp_path / "backup")
    finally:
        con.close()

    assert drop.verify_backup(backup, {("books", "report_md"): 2}) == []
    [problem] = drop.verify_backup(backup, {("books", "report_md"): 3})
    assert "books.report_md" in problem and "元 3 行・写し 2 行" in problem


def test_写しが壊れていると検査が問題を返す(tmp_path):
    broken = tmp_path / "broken.db"
    broken.write_bytes("SQLite ではないバイト列".encode() * 100)

    problems = drop.verify_backup(broken, {("books", "report_md"): 2})

    assert problems and "写しを読めません" in problems[0]


def test_写しのintegrity_checkがok以外なら検査が問題を返す(tmp_path):
    db = make_db(tmp_path, BOOKS, extra_sql=["CREATE INDEX ix_notes_text ON notes(text)"])
    con = sqlite3.connect(db)
    try:
        backup = drop.make_backup(con, tmp_path / "backup")
    finally:
        con.close()
    assert drop.verify_backup(backup, {("books", "report_md"): 2}) == []     # 壊す前は合格
    orphan_an_index(backup, "ix_notes_text")

    [problem] = drop.verify_backup(backup, {("books", "report_md"): 2})

    assert "integrity_check が ok ではありません" in problem and "never used" in problem
