#!/usr/bin/env python3
"""いまあるタグと本棚の著者の、テーマノート・著者ノートを一括で作る1回限りのスクリプト

設計: docs/design/0003-bulk-create-notes.md

アプリの方針は、テーマノートはユーザーが作り、著者ノートはアプリが自動で作る（レポートのある
著者だけ）。それは変えずに、いまあるタグ全部と本棚の著者全部のノートを、本文は空のまま
（マーカーの間のアプリが書く本の一覧だけ入れて）一度にまとめて作る。

- 対象: 1冊以上の本に付いているタグ全部 → `reports/themes/<タグ>.md`
        本棚の全部の本（積読も含む）の著者全部 → `reports/authors/<著者>.md`
- **既存のファイルは上書きも変更もしない**。既にどれかのノートが集めているタグ・著者
  （ファイル名か、テーマの `tags`・著者の `aliases` で）は作らない。ハブ（`テーマ一覧.md`・
  `著者一覧.md`）と既存ノートの一覧もこのスクリプトは触らない。アプリが動いていれば、数秒おきに
  書き直す仕組み（ThemeWatcher）が十数秒で新しいノートを含む形に更新する。
- DB は読み取り専用で開く（書かない・ファイルが無ければ作らない）。アプリが動いたままでも読める。
- 何度流しても同じ結果になる。増えたタグ・著者のノートも、もう一度流せば作られる。
  ただし消したノートは、もう一度流すと作り直される。
- 作れない・作らないものは、理由を標準エラーに `  ! ` つきで出す（ファイル名にできない
  タグ、別のタグや著者と見分けのつかない名前など）。
- 既定は下見（何も書かない）。実際に作るときは `--apply` を付ける。

使い方:
    .venv/bin/python scripts/create_notes.py                    # 下見
    .venv/bin/python scripts/create_notes.py --apply            # 作る
    .venv/bin/python scripts/create_notes.py --db /path/to/reading.db
    .venv/bin/python scripts/create_notes.py 2>&1 | less        # 下見を less で読む（理由は標準エラーなので 2>&1）

流す順序:
    1. Obsidian で編集中のテーマノート・著者ノートがあれば閉じる。直近10秒に更新された
       ノートや、書きかけ（空・frontmatter が壊れている）のノートがあるセクションは、
       集めるタグ・名前を読み違えるので作らずに待つ（終了コード 1）。frontmatter が空
       （`---` と `---` だけ）のノートも待つので、直すか、frontmatter ごと消す。
    2. 下見 → 作るファイルと作らない理由を確認 → `--apply`。
    3. 作った直後は20秒ほどおいてから、もう一度下見して「作る 0」を確認する。作ったノートが
       「直近に更新された」ので待つうえ、アプリが動いていると、既存ノートの「関連するテーマ」を
       作成から最大5秒後に書き直し、書き直したノートもその後10秒は「直近に更新された」になる。

終了コードは、DB が無い・読めない／ノートの置き場所が無い／ノートのフォルダが読めない／
待ったセクションがある／`--apply` で作れなかったファイルがあれば 1。作らない理由が恒久的な
もの（ファイル名にできないなど）だけなら 0。引数の誤りは 2。
"""

import argparse
import sqlite3
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app import author_store, report_store, theme_store  # noqa: E402
from app.models import Book  # noqa: E402

DEFAULT_DB = REPO_ROOT / "backend" / "reading.db"

WAIT_HINT = ("Obsidian で編集中なら閉じ、20秒ほどおいてもう一度流す。変わらなければ、そのノートの "
             "frontmatter が空か壊れている。直す（空なら `---` の間に書くか、frontmatter ごと消す）")


@dataclass
class _Result:
    """1つのセクション（テーマ／著者）の結果。"""
    made: int = 0                 # 作る予定（下見）／作った（--apply）数
    failed: int = 0               # 作れなかった数
    problem: bool = False         # 待った・フォルダを読めなかった（終了コード 1 の理由）
    themes: list = field(default_factory=list)   # テーマだけ: 著者ノートの「関連するテーマ」に出すノート


def open_readonly(path: Path) -> Engine:
    """`path` の SQLite を読み取り専用で開くエンジン。ファイルが無いときに作らない。

    URL 文字列（`sqlite:///file:<パス>?mode=ro&uri=true`）にしないのは、パスに `?` や `#` が
    あると URL がそこで切れて `mode=ro` が効かず、途中までの名前の空の DB ファイルを作って
    しまうため。`as_uri()` なら空白・`#`・`?`・`%`・日本語が符号化される。
    アプリの `configure_sqlite` は呼ばない（`PRAGMA journal_mode=WAL` は書き込みになる）。
    """
    uri = path.resolve().as_uri() + "?mode=ro"
    return create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))


def _read_books(path: Path) -> list[Book]:
    engine = open_readonly(path)
    try:
        with Session(engine) as db:
            return list(db.scalars(select(Book).options(selectinload(Book.tags)).order_by(Book.id)))
    finally:
        engine.dispose()


def _printable(text: str) -> str:
    """端末に出すと崩れる文字（制御文字・行区切り・サロゲート）を `\\r` `\\x1b` の形にして返す。

    タグや著者名は DB の値で、制御文字が入りうる。そのまま出すと行が崩れ、ESC は端末の制御列になる。
    """
    return "".join(ch.encode("unicode_escape").decode("ascii")
                   if unicodedata.category(ch) in ("Cc", "Zl", "Zp", "Cs") else ch
                   for ch in text)


def _warn(message: str) -> None:
    print(f"  ! {_printable(message)}", file=sys.stderr)


def _write_notes(directory: Path, planned: list, now: float, quiet: float) -> tuple[list, list]:
    """計画のノートを1つずつ作る。(作れたもの, 作れなかったもの)。無いときだけ作り、既存は触らない。"""
    if not planned:
        return [], []
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        _warn(f"{directory} を作れません: {error}")
        return [], list(planned)
    made, failed = [], []
    for item in planned:
        written = theme_store.create_file(item.note.path, item.text, quiet, now)
        (made if written else failed).append(item)
    return made, failed


def _apply_plan(plan, directory: Path, skipped: list[tuple[str, str]], extra, apply: bool,
                now: float, quiet: float) -> tuple[_Result, list]:
    """計画を表示し、`--apply` なら作る。テーマと著者で共通の出力。(結果, 作った（下見では作る予定の）もの)。"""
    for name, reason in skipped:
        _warn(f"{name}: {reason}")
    if apply:
        made, failed = _write_notes(directory, plan.notes, now, quiet)
    else:
        made, failed = plan.notes, []
    for item in made:
        print(f"  + {_printable(item.note.path.name + extra(item))}")
    for item in failed:
        _warn(f"{item.note.path.name}: 作れなかった（同名のファイルができていた、または書けなかった。"
              "もう一度流すと理由が出る）")
    counts = f"作った {len(made)} / 作れなかった {len(failed)}" if apply else f"作る {len(made)}"
    print(f"{counts} / 既にノートあり {len(plan.already)} / 作らない {len(plan.skipped)}")
    return _Result(made=len(made), failed=len(failed)), made


def _themes_section(books: list[Book], reports: dict[int, Path], apply: bool,
                    now: float, quiet: float) -> _Result:
    directory = theme_store.themes_dir()
    print("テーマノート（themes/）")
    try:
        reason = theme_store.unsettled_reason(directory, now, quiet)
        existing = theme_store.scan_notes(directory)
    except OSError as error:
        _warn(f"{directory} を読めません: {error}")
        return _Result(problem=True)
    if reason is not None:
        _warn(f"テーマノートを作らない: {reason}（{WAIT_HINT}）")
        print("  待ち（このセクションは作らない）")
        return _Result(problem=True, themes=existing)

    plan = theme_store.plan_new_notes(directory, books, reports, existing)

    def extra(item: theme_store.PlannedNote) -> str:
        # ファイル名がタグと違うときだけ、雛形に tags を入れたことを示す
        return f"（tags: {item.tag}）" if item.note.path.stem != item.tag else ""

    result, made = _apply_plan(plan, directory, plan.skipped, extra, apply, now, quiet)
    # 著者ノートの「関連するテーマ」には、この回に作った（下見では作る予定の）ノートも出す
    result.themes = existing + [item.note for item in made]
    return result


def _authors_section(books: list[Book], reports: dict[int, Path], theme_notes: list,
                     apply: bool, now: float, quiet: float) -> _Result:
    directory = author_store.authors_dir()
    print("著者ノート（authors/）")
    try:
        scan = author_store.scan_notes(directory)
    except FileNotFoundError:
        scan = author_store.NoteScan([], [])
    except OSError as error:
        _warn(f"{directory} を読めません: {error}")
        return _Result(problem=True)
    reason = scan.reason_to_wait(now, quiet)
    if reason is not None:
        _warn(f"著者ノートを作らない: {reason}（{WAIT_HINT}）")
        print("  待ち（このセクションは作らない）")
        return _Result(problem=True)

    authors = author_store.collect_authors(books)
    themes = [(note.path, {b.id for b in theme_store.books_for(note.tags, books)})
              for note in theme_notes]
    plan = author_store.plan_new_notes(directory, authors, scan.notes, reports, themes,
                                       include_without_report=True)

    def extra(item: author_store.PlannedNote) -> str:
        # ファイル名にすると名前が変わったときだけ、雛形に aliases を入れたことを示す
        if author_store.author_key(item.note.path.stem) != item.author.key:
            return f"（aliases: {item.author.name}）"
        return ""

    skipped = [(author.name, why) for author, why in plan.skipped]
    result, _ = _apply_plan(plan, directory, skipped, extra, apply, now, quiet)
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="実際にノートを作る（既定は下見）")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="読む DB（既定: %(default)s）")
    args = parser.parse_args(argv)

    directory = report_store.reports_dir()
    if not directory.is_dir():
        print(f"ノートの置き場所（レポートのディレクトリ）が見つかりません: {directory}", file=sys.stderr)
        return 1

    db_path = Path(args.db).expanduser().resolve()
    # mode=ro は無いファイルを作らないが、分かりやすいメッセージを出すために先に見る
    if not db_path.is_file():
        print(f"DB が見つかりません: {db_path}（--db で指定できます）", file=sys.stderr)
        return 1
    try:
        books = _read_books(db_path)
    except (SQLAlchemyError, LookupError, ValueError) as error:
        # LookupError / ValueError は、列の値が不正なとき（status が enum に無い・日付が日付でない）
        lines = str(error).splitlines()
        print(f"DB を読めません: {db_path}: {lines[0] if lines else type(error).__name__}",
              file=sys.stderr)
        return 1

    reports = report_store.report_paths()
    now = time.time()
    quiet = theme_store.QUIET_SECONDS

    tag_count = len({tag.name for book in books for tag in book.tags})
    author_count = len(author_store.collect_authors(books))
    print(f"DB（読み取り専用）: {db_path}")
    print(f"ノートの置き場所: {directory}")
    print(f"本 {len(books)} 冊・タグ {tag_count} 個・著者 {author_count} 人\n")

    themes = _themes_section(books, reports, args.apply, now, quiet)
    print()
    authors = _authors_section(books, reports, themes.themes, args.apply, now, quiet)
    print()

    made = themes.made + authors.made
    failed = themes.failed + authors.failed
    if args.apply:
        print(f"作った {made} / 作れなかった {failed}。"
              "アプリが動いていれば、ハブと既存ノートの一覧は十数秒で更新される。")
    else:
        print(f"下見のみ。--apply を付けると {made} 件を作る（既存のファイルは変えない）。")
    return 1 if failed or themes.problem or authors.problem else 0


if __name__ == "__main__":
    raise SystemExit(main())
