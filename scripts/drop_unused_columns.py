#!/usr/bin/env python3
"""DB にあってモデルに無い列のうち、許可リストにあるものを消す1回限りの移行（books.report_md）

2026-10-11 に読書レポートの本文を `books.report_md` 列からファイルへ移し、列は移行前の
凍結コピーとして残した。同じデータを2か所に置かない原則（`docs/design/0001-storage-boundary.md`）
に合わないので、ユーザーの指示でこの列を DB から消す（`docs/design/0004-drop-unused-columns.md`）。

- 消すのは「DB にあってモデル（`Base.metadata`）に無い列」のうち、`DROP_ALLOWLIST` にある
  ものだけ。許可リストに無いモデル外の列は、名前・型・値のある行数を出すだけで消さない
  （どこにも移されていない本文かもしれない。消すかはユーザーが判断する）。
- 消す前に、`books.report_md` に本文がある本すべてに、本文が空でないレポートのファイルがある
  ことを確かめる。無い本があれば何も変えずに止まる（意図して消したレポートなら `--allow-missing`）。
- `--apply` は先に `locking_mode=EXCLUSIVE` で排他ロックを取る。ほかに DB を開いている
  プロセス（常駐のアプリなど）があれば取れないので、何も変えずに止まる。ロックは終わるまで放さない。
- 消す前に `backup/reading-YYYYmmdd-HHMMSS.db` へ写しを取り、写しを検査する。写しは別名
  （`.partial`）で作り、できあがってから正式な名前にする（途中で失敗・中断しても、検査に
  通っていない `reading-….db` は残らない）。
- 列は1つのトランザクションで消し、その中で integrity_check・foreign_key_check・残す列の
  中身の比較を流す。駄目なら（COMMIT の失敗も）ROLLBACK する。COMMIT のあとは VACUUM して、
  消した本文のバイトも物理的に消す。
- 冪等。消すものが無ければ何もしない（写しも VACUUM もしない）。`--apply` で空きページが残って
  いれば、前回の VACUUM が途中で止まった可能性として知らせるだけ。
- 列を名前で参照する索引・ビュー・トリガーがあれば、SQLite が通すかどうかにかかわらず消さない。
- `--db` が books テーブルのある SQLite の DB でなければ、書き込み用に開く前に止まる。
- 既定は下見（ロックを取らず、DB に書かない）。実際に消すときは `--apply` を付ける。

使い方:
    systemctl --user stop notes-web                                  # 先にアプリを止める
    .venv/bin/python scripts/drop_unused_columns.py                  # 下見
    .venv/bin/python scripts/drop_unused_columns.py --apply          # 実行
    systemctl --user start notes-web

`backend/.env` は読まない。アプリが `.env` で `NOTES_REPORTS_DIR` を変えているなら、同じ値を
付けて流す（`NOTES_REPORTS_DIR=… .venv/bin/python scripts/drop_unused_columns.py`）。

終了コードは、SQLite が 3.35.5 より古い・DB が無い／読めない／books テーブルが無い・ファイルなしの
本がある・DB を開いているプロセスがある・写しを取れない／検査に通らない・DROP が拒まれた・
DROP 後の検査や COMMIT に通らない・VACUUM に失敗したときに 1。許可リストに無いモデル外の列が
あることだけでは 1 にしない。
"""

import argparse
import json
import os
import re
import shlex
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# models を import するのは、テーブルを Base.metadata に登録させるため。app.database の
# engine / SessionLocal は使わない（sqlite:///./reading.db は作業ディレクトリ基準で、
# 別の場所に空の DB を作ってしまう）。create_engine は接続するまで何もしないので、import だけなら害はない
from app import models, report_store  # noqa: E402, F401
from app.database import Base  # noqa: E402

DEFAULT_DB = REPO_ROOT / "backend" / "reading.db"
DEFAULT_BACKUP_DIR = REPO_ROOT / "backup"
# ALTER TABLE … DROP COLUMN が入った版は 3.35.0 だが、3.35.0〜3.35.4 には DB を壊しうる不具合があり
# 3.35.5（2021-04-19）で直った
MIN_SQLITE = (3, 35, 5)
LOCK_TIMEOUT_SECONDS = 2.0     # 排他ロックを待つ秒数（テストは monkeypatch で短くする）

# 消してよい列 → 理由（出力に出す）。ここに無い「モデルに無い列」は名前を出すだけで消さない。
# books.report_html は入れない（HTML 時代の本文が残っていれば、どこにも移されていない唯一の
# 本文かもしれず、ファイルと突き合わせる方法も無い。0004 §5.2）
DROP_ALLOWLIST = {
    ("books", "report_md"): "読書レポート本文の凍結コピー（2026-10-11 にファイルへ移管。0001 §7.4）",
}

# ファイルとの突き合わせが要る列（本文を持つ列）
REPORT_COLUMN = ("books", "report_md")


class ExtraColumn(NamedTuple):
    table: str
    column: str
    type: str
    filled: int      # NULL でない行数
    drop: bool       # 許可リストにあるか


class ReportCheck(NamedTuple):
    total: int                                   # 本文のある本の数
    same: int                                    # ファイルの本文が DB と同じ本の数
    differ: list[tuple[int, str, int, int]]      # 違う本 (id, 書名, DB の文字数, ファイルの文字数)
    missing: list[tuple[int, str, int]]          # ファイルなしの本 (id, 書名, DB の文字数)


def _quote(identifier: str) -> str:
    """SQL の識別子を `"` で囲む（中の `"` は二重にする）。"""
    return '"' + identifier.replace('"', '""') + '"'


def _warn(message: str) -> None:
    print(f"  ! {message}", file=sys.stderr)


def _error(message: str) -> None:
    print(message, file=sys.stderr)


def _names(targets: list[ExtraColumn]) -> str:
    return "、".join(f"{target.table}.{target.column}" for target in targets)


# ── 対象の決め方 ────────────────────────────────────────────

def model_columns() -> dict[str, set[str]]:
    """モデルのテーブルごとの列名。"""
    return {table.name: {column.name for column in table.columns}
            for table in Base.metadata.sorted_tables}


def extra_columns(con: sqlite3.Connection) -> list[ExtraColumn]:
    """DB にあってモデルに無い列。DB にしか無いテーブル・モデルにしか無いテーブルは見ない。"""
    in_db = {name.lower(): name for (name,) in con.execute(
        "SELECT name FROM sqlite_schema WHERE type = 'table'")}
    extras = []
    for table, columns in model_columns().items():
        actual = in_db.get(table.lower())
        if actual is None:
            continue
        known = {column.lower() for column in columns}   # SQLite の列名は大文字小文字を区別しない
        for _, name, type_, *_ in con.execute(f"PRAGMA table_info({_quote(actual)})").fetchall():
            if name.lower() in known:
                continue
            filled = con.execute(
                f"SELECT COUNT({_quote(name)}) FROM {_quote(actual)}").fetchone()[0]
            extras.append(ExtraColumn(actual, name, type_, filled, (actual, name) in DROP_ALLOWLIST))
    return extras


def _print_extras(extras: list[ExtraColumn]) -> None:
    print("モデルに無い列:")
    for extra in extras:
        verdict = (f"消す: {DROP_ALLOWLIST[(extra.table, extra.column)]}" if extra.drop
                   else "消さない: 許可リストに無い。消すかはユーザーが判断")
        print(f"  - {extra.table}.{extra.column}（{extra.type or '型なし'}、"
              f"値あり {extra.filled} 行）… {verdict}")


# ── レポートのファイルの確認 ────────────────────────────────

def check_reports(con: sqlite3.Connection) -> ReportCheck:
    """books.report_md の本文とレポートのファイルを突き合わせる。

    「違う」は移管後に直した結果なので問題にしないが、どの本かは出す。「本文がある」の判定は
    `report_store.read()` と同じ `strip()`（SQL の TRIM は空白しか落とさない）。
    """
    rows = [(book_id, title, report_md.strip()) for book_id, title, report_md in con.execute(
        "SELECT id, title, report_md FROM books WHERE report_md IS NOT NULL ORDER BY id")]
    rows = [row for row in rows if row[2]]
    have = report_store.book_ids_with_report()
    same = 0
    differ = []
    missing = []
    for book_id, title, body in rows:
        if book_id not in have:
            missing.append((book_id, title, len(body)))
            continue
        in_file = report_store.read(book_id) or ""   # 読めなければ「違う」（文字数 0）
        if in_file == body:
            same += 1
        else:
            differ.append((book_id, title, len(body), len(in_file)))
    return ReportCheck(len(rows), same, differ, missing)


def _reports_are_ready(con: sqlite3.Connection, allow_missing: bool) -> bool:
    """突き合わせの結果を出す。先に進んでよければ True。"""
    total, same, differ, missing = check_reports(con)
    print(f"books.report_md の本文がある本: {total} 冊")
    print(f"  ファイルあり {total - len(missing)} 冊（本文が同じ {same} 冊・違う {len(differ)} 冊。"
          "違うのは移管後の編集なので構わない）")
    for book_id, title, db_length, file_length in differ:
        short = "。ファイルのほうがずっと短い" if file_length * 2 < db_length else ""
        print(f"  ~ {book_id:4} {title[:40]}（DB {db_length} 文字 / ファイル {file_length} 文字{short}）")
    suffix = "（--allow-missing で通す）" if missing and allow_missing else ""
    print(f"  ファイルなし {len(missing)} 冊{suffix}")
    for book_id, title, length in missing:
        _warn(f"{book_id:4} {title[:40]}（ファイルなし。DB の本文 {length} 文字）")
    print()
    if missing and not allow_missing:
        _error("レポートのファイルが無い本があるので止めました。DB は変えていません。\n"
               "  - 意図して消したレポート（reports/.trash/ にある）なら、--allow-missing を付けて流す。\n"
               "    DB の本文は写し（backup/）に残る。\n"
               '  - 取りこぼしなら、sqlite3 backend/reading.db "SELECT report_md FROM books '
               'WHERE id = <id>" で本文を出し、\n'
               "    アプリでレポートとして保存してから、もう一度流す。")
        return False
    return True


# ── 消す ────────────────────────────────────────────────────

def _references(con: sqlite3.Connection, column: str) -> list[str]:
    """列名が単語として現れる索引・ビュー・トリガー。"""
    word = re.compile(rf"\b{re.escape(column)}\b", re.IGNORECASE)
    return [f"{type_} {name}" for type_, name, sql in con.execute(
        "SELECT type, name, sql FROM sqlite_schema "
        "WHERE type IN ('index', 'view', 'trigger') AND sql IS NOT NULL") if word.search(sql)]


def _cannot_drop(target: ExtraColumn, reason: str, references: Sequence[str] = ()) -> str:
    """列を消さないときの説明。reason は SQLite のメッセージか、こちらで止めた理由。"""
    message = f"{target.table}.{target.column} を消せません: {reason}"
    if references:
        message += (f"\n  この列を参照しているもの: {', '.join(references)}"
                    "（消すかはユーザーが判断してください）")
    return message


def _post_checks(con: sqlite3.Connection, fk_before: set) -> list[str]:
    """DROP のあと、COMMIT の前に流す検査。駄目なときに DB を元のままにできるため、同じトランザクションの中で流す。"""
    problems = []
    integrity = [row[0] for row in con.execute("PRAGMA integrity_check")]
    if integrity != ["ok"]:
        problems.append("DROP のあとの integrity_check が ok ではありません: "
                        + " / ".join(integrity[:5]))
    fk_after = set(con.execute("PRAGMA foreign_key_check"))
    if fk_after != fk_before:
        problems.append("DROP のあとの foreign_key_check が DROP 前と違います"
                        f"（増えた不整合 {len(fk_after - fk_before)} 件・"
                        f"なくなった不整合 {len(fk_before - fk_after)} 件）")
    return problems


def _kept_content(con: sqlite3.Connection, targets: list[ExtraColumn]) -> dict[str, list[tuple]]:
    """消す列を持つ表の、残す列の中身（全行）。DROP の前後で比べる。"""
    dropping: dict[str, set[str]] = {}
    for target in targets:
        dropping.setdefault(target.table, set()).add(target.column.lower())
    content = {}
    for table, dropped in dropping.items():
        kept = [name for _, name, *_ in con.execute(f"PRAGMA table_info({_quote(table)})")
                if name.lower() not in dropped]
        content[table] = con.execute(
            f"SELECT {', '.join(_quote(name) for name in kept)} FROM {_quote(table)} "
            "ORDER BY rowid").fetchall()
    return content


def _kept_changes(con: sqlite3.Connection, targets: list[ExtraColumn],
                  before: dict[str, list[tuple]]) -> list[str]:
    """残す列の中身が DROP で変わっていないか。integrity_check では見つからない型の壊れ方
    （行の中身だけが入れ替わる）の備え。"""
    after = _kept_content(con, targets)
    return [f"DROP のあと {table} の残す列の中身が DROP 前と違います" for table in before
            if after[table] != before[table]]


def drop_columns(con: sqlite3.Connection, targets: list[ExtraColumn], *, commit: bool) -> list[str]:
    """BEGIN IMMEDIATE → DROP COLUMN → 同じトランザクションの中で検査。

    問題があれば ROLLBACK して問題の一覧を返す（COMMIT の失敗も含む）。問題が無ければ、
    commit なら COMMIT、そうでなければ ROLLBACK（下見の試し）して [] を返す。`con` は
    isolation_level=None（トランザクションの境目を自分で書く）であること。
    """
    fk_before = set(con.execute("PRAGMA foreign_key_check"))
    if fk_before:
        _warn(f"前からある外部キーの不整合 {len(fk_before)} 件（今回の変更とは関係ないので止めません）")
    problems: list[str] = []
    con.execute("BEGIN IMMEDIATE")
    try:
        kept_before = _kept_content(con, targets)
        for target in targets:
            # 列名を出す索引・ビュー・トリガーがあれば、SQLite が通すかどうかにかかわらず消さない。
            # 本体で列を更新するだけのトリガー（UPDATE … SET report_md）は SQLite が DROP を通すが、
            # 消したあとにそのトリガーが走る UPDATE が "no such column" で壊れる
            references = _references(con, target.column)
            if references:
                problems.append(_cannot_drop(target, "この列を名前で参照するものがあります", references))
                break
            try:
                con.execute(f"ALTER TABLE {_quote(target.table)} DROP COLUMN {_quote(target.column)}")
            except sqlite3.OperationalError as error:
                problems.append(_cannot_drop(target, str(error)))
                break
        else:
            try:
                problems = _post_checks(con, fk_before) + _kept_changes(con, targets, kept_before)
            except sqlite3.Error as error:
                problems = [f"DROP のあとの検査を流せませんでした: {error}"]
        if not problems and commit:
            try:
                con.execute("COMMIT")
            except sqlite3.Error as error:
                problems.append(f"COMMIT に失敗しました: {error}")
    finally:
        if con.in_transaction:
            con.execute("ROLLBACK")
    return problems


# ── 写し ────────────────────────────────────────────────────

def make_backup(con: sqlite3.Connection, backup_dir: Path) -> Path:
    """sqlite3 の backup API で写しを取る。既にある名前は上書きせず `-2`, `-3` … を足す。

    `<名前>.db.partial` に書き、backup と journal_mode の切り替えと close が済んでから
    `<名前>.db` に改名する。途中で失敗・中断しても、正式な名前のファイルは残らない
    （壊れた写しを、戻す手順で選んでしまわないため）。

    `con` が書き込みトランザクションの中にいると、backup は SQLITE_BUSY を待ち続けて戻らない。
    ロックだけを持った状態で呼ぶこと。
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    stem = f"reading-{datetime.now():%Y%m%d-%H%M%S}"
    path = backup_dir / f"{stem}.db"
    n = 2
    while path.exists() or _partial_of(path).exists():
        path = backup_dir / f"{stem}-{n}.db"
        n += 1
    partial = _partial_of(path)
    done = False
    try:
        dst = sqlite3.connect(partial)
        try:
            con.backup(dst)
            # 元の DB の「WAL」の印が写しのヘッダにも写る。そのままだと開くたびに -wal / -shm が
            # できるので、DELETE に戻して写しを1ファイルで完結させる
            dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
        os.replace(partial, path)
        done = True
    finally:
        if not done:
            partial.unlink(missing_ok=True)
            partial.with_name(partial.name + "-journal").unlink(missing_ok=True)
    return path


def _partial_of(path: Path) -> Path:
    return path.with_name(path.name + ".partial")


def verify_backup(path: Path, expected: dict[tuple[str, str], int]) -> list[str]:
    """写しの検査。問題の一覧を返す（空なら合格）。

    integrity_check が ok で、消す列の値のある行数が元と同じ（消す中身が全部入っている）こと。
    """
    problems = []
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        try:
            integrity = [row[0] for row in con.execute("PRAGMA integrity_check")]
            if integrity != ["ok"]:
                problems.append("integrity_check が ok ではありません: " + " / ".join(integrity[:5]))
            for (table, column), filled in expected.items():
                copied = con.execute(
                    f"SELECT COUNT({_quote(column)}) FROM {_quote(table)}").fetchone()[0]
                if copied != filled:
                    problems.append(f"{table}.{column} の値のある行数が元と違います"
                                    f"（元 {filled} 行・写し {copied} 行）")
        except sqlite3.DatabaseError as error:
            problems.append(f"写しを読めません: {error}")
    finally:
        con.close()
    return problems


# ── 接続 ────────────────────────────────────────────────────

def _open_readonly(db: Path) -> sqlite3.Connection:
    """下見用。ロックを取らず、書かない（アプリが動いていても流せる）。"""
    return sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)


def _open_exclusive(db: Path) -> sqlite3.Connection:
    """`--apply` 用。ほかに DB を開いている接続があれば sqlite3.OperationalError（`_is_locked`）。

    取った排他ロックは接続を閉じるまで持ち続ける（locking_mode=EXCLUSIVE）。
    `BEGIN EXCLUSIVE` だけでは足りない。WAL では EXCLUSIVE と IMMEDIATE は同じ意味で、
    いま書いている接続としか衝突せず、アプリの接続プールにいるアイドルの接続を見逃す。
    locking_mode=EXCLUSIVE だと書き込みの開始時に DB ファイルの排他ロックを取りに行くので、
    開いている接続が1つでもあれば SQLITE_BUSY になる。
    """
    # mode=rw: ファイルが無ければ作らずにエラーになる
    con = sqlite3.connect(db.resolve().as_uri() + "?mode=rw", uri=True,
                          timeout=LOCK_TIMEOUT_SECONDS, isolation_level=None)
    try:
        con.execute("PRAGMA locking_mode=EXCLUSIVE")   # 最初の読み書きより前に
        con.execute("BEGIN EXCLUSIVE")
        con.execute("COMMIT")   # ロックは閉じるまで残る
    except sqlite3.Error:
        con.close()
        raise
    return con


def _is_locked(error: sqlite3.Error) -> bool:
    """ほかの接続が DB を使っている（SQLITE_BUSY / SQLITE_LOCKED）ためのエラーか。

    権限・ディレクトリ・ファイルの種類が原因のエラーでアプリを止めるよう案内しないための区別。
    `sqlite_errorcode` は Python 3.11 から。無ければ区別できないので、従来どおり「開いている」とする。
    """
    code = getattr(error, "sqlite_errorcode", None)
    return code is None or code & 0xFF in (5, 6)


def _why_not_target(db: Path) -> Optional[str]:
    """`--db` が books テーブルのある SQLite の DB でなければ、その理由。

    書き込み用に開く前に、読み取り専用で確かめる。空のファイルを書き込み用に開くと、SQLite が
    ヘッダを書いて空の DB にしてしまう。
    """
    con = _open_readonly(db)
    try:
        found = con.execute("SELECT 1 FROM sqlite_schema WHERE type = 'table' "
                            "AND lower(name) = 'books'").fetchone()
    finally:
        con.close()
    return None if found else f"books テーブルがありません。--db が正しいか確かめてください: {db}"


def _unreadable(error: sqlite3.Error) -> int:
    _error(f"DB を読めません（SQLite: {error}）。DB は変えていません。")
    return 1


def _vacuum_command(db: Path) -> str:
    """sqlite3 の CLI が無くても流せる VACUUM のコマンド。"""
    code = f'import sqlite3; sqlite3.connect({json.dumps(str(db.resolve()), ensure_ascii=False)}).execute("VACUUM")'
    return f".venv/bin/python -c {shlex.quote(code)}"


# ── 下見と実行 ──────────────────────────────────────────────

def _preview(con: sqlite3.Connection, targets: list[ExtraColumn]) -> int:
    """メモリ上の写しで DROP COLUMN を試して ROLLBACK する。元の DB には触らない。"""
    mem = sqlite3.connect(":memory:", isolation_level=None)
    try:
        con.backup(mem)
        problems = drop_columns(mem, targets, commit=False)
    finally:
        mem.close()
    if problems:
        for problem in problems:
            _error(problem)
        _error("DB は変えていません。")
        return 1
    print("DROP COLUMN の試し（メモリ上の写し）: ok")
    print()
    print(f"下見のみ。--apply を付けると {_names(targets)} を消す。")
    print("--apply の前にアプリを止める: systemctl --user stop notes-web")
    return 0


def _apply(con: sqlite3.Connection, args: argparse.Namespace, targets: list[ExtraColumn]) -> int:
    try:
        backup = make_backup(con, args.backup_dir)
    except (OSError, sqlite3.Error) as error:
        _error(f"写しを取れませんでした（{type(error).__name__}: {error}）。置き場所: {args.backup_dir}\n"
               "DB は変えていません。")
        return 1
    problems = verify_backup(backup, {(t.table, t.column): t.filled for t in targets})
    if problems:
        _error(f"写しの検査に通りません: {backup}")
        for problem in problems:
            _error(f"  ! {problem}")
        _error("DB は変えていません。写しは調べるために残してあります。")
        return 1
    print(f"写し: {backup}（integrity_check ok）")

    size_before = args.db.stat().st_size
    problems = drop_columns(con, targets, commit=True)
    if problems:
        for problem in problems:
            _error(problem)
        _error(f"DB は変えていません（写しは {backup}）。")
        return 1

    foreign_keys = len(con.execute("PRAGMA foreign_key_check").fetchall())
    print(f"消した列: {_names(targets)}")
    print("integrity_check ok / foreign_key_check "
          + ("不整合なし" if not foreign_keys else f"は消す前と同じ（前からの不整合 {foreign_keys} 件）"))

    try:
        con.execute("VACUUM")
    except sqlite3.OperationalError as error:
        _error(f"VACUUM に失敗しました（列は消えています。DB は壊れていません）: {error}\n"
               f"あとでアプリを止めて、次を流してください:\n    {_vacuum_command(args.db)}")
        return 1
    remaining = [extra for extra in extra_columns(con) if extra.drop]
    if remaining:
        _error(f"消したはずの列が残っています: {_names(remaining)}")
        return 1
    con.close()
    print(f"DB の大きさ: {size_before:,} → {args.db.stat().st_size:,} バイト（VACUUM）")
    print("アプリを起動する: systemctl --user start notes-web")
    return 0


def _nothing_to_drop(con: sqlite3.Connection, args: argparse.Namespace) -> int:
    """消すものが無いときの終わり方（終了コード 0）。

    `--apply` で空きページが残っていれば知らせる。列を消した直後の VACUUM が途中で止まると
    （kill・SSH の切断・メモリ不足）、列は消えたまま消した本文のバイトが空きページに残り、
    もう一度流しても「消すものはありません」になって気づけないため。
    """
    free_pages = con.execute("PRAGMA freelist_count").fetchone()[0]
    if args.apply and free_pages:
        print(f"空きページが {free_pages} 個あります。列を消したあとの VACUUM が途中で止まっていると、\n"
              "消した本文のバイトがここに残っています（アプリの通常の使い方でも少しは出ます）。\n"
              "気になるときは、アプリを止めて次を流してください:\n"
              f"    {_vacuum_command(args.db)}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="実際に消す。無ければ下見")
    parser.add_argument("--allow-missing", action="store_true",
                        help="レポートのファイルが無い本があっても止めない（本文は写しに残る）")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="対象の DB")
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR, help="写しの置き場所")
    args = parser.parse_args(argv)

    # 呼ぶたびに読む（import 時に定数へ写さない。テストが古い版にする）
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        _error(f"SQLite {sqlite3.sqlite_version} では列を消せません"
               f"（{'.'.join(map(str, MIN_SQLITE))} 以上が必要）。DB は変えていません。")
        return 1
    if not args.db.is_file():
        _error(f"DB が見つかりません: {args.db}")
        return 1

    print(f"DB: {args.db.resolve()}（SQLite {sqlite3.sqlite_version}）")
    print(f"レポート: {report_store.reports_dir()}")
    print()

    try:
        not_target = _why_not_target(args.db)
    except sqlite3.Error as error:
        return _unreadable(error)
    if not_target:
        _error(f"{not_target}\nDB は変えていません。")
        return 1

    if args.apply:
        try:
            con = _open_exclusive(args.db)
        except sqlite3.Error as error:
            if not _is_locked(error):
                _error(f"DB を書き込み用に開けません（SQLite: {error}）。DB は変えていません。\n"
                       "権限・DB のあるディレクトリ・ファイルの種類を確かめてください。")
                return 1
            _error(f"DB を開いているプロセスがあるので止めました（SQLite: {error}）。DB は変えていません。\n"
                   "常駐のアプリを止めてから、もう一度流してください:\n"
                   "    systemctl --user stop notes-web\n"
                   "（./run.sh で動かしているならそれも止める。sqlite3 などで開いていれば閉じる）")
            return 1
    else:
        con = _open_readonly(args.db)

    try:
        try:
            extras = extra_columns(con)
        except sqlite3.Error as error:
            return _unreadable(error)
        if not extras:
            print("モデルに無い列はありません。消すものはありません。")
            return _nothing_to_drop(con, args)
        _print_extras(extras)
        targets = [extra for extra in extras if extra.drop]
        if not targets:
            print("消すものはありません。")
            return _nothing_to_drop(con, args)
        print()

        if (REPORT_COLUMN in {(t.table, t.column) for t in targets}
                and not _reports_are_ready(con, args.allow_missing)):
            return 1
        return _apply(con, args, targets) if args.apply else _preview(con, targets)
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
