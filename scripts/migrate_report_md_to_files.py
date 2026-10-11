#!/usr/bin/env python3
"""books.report_md（DB の TEXT 列）を reports/*.md のファイルへ移す1回限りの移行

2026-10-11 の方針変更（`Storage/_vault/document-storage-policy.md`）で、読書レポートの
本文は**ファイルが正**になった。このスクリプトは移行前に DB へ溜まっていた本文を
ファイルへ書き出す。

- **DB は変更しない。** `books.report_md` 列は凍結コピーとして残す（アプリはもう読まない）。
  万一の取りこぼしに気づいたとき、ここから再実行できるようにしておく。
- 冪等。既にファイルの本文が DB と同じ本は飛ばす（mtime を無駄に動かさない）。
- 既定は dry-run。実際に書くときは `--apply` を付ける。

使い方:
    .venv/bin/python scripts/migrate_report_md_to_files.py            # 下見
    .venv/bin/python scripts/migrate_report_md_to_files.py --apply    # 実行
    .venv/bin/python scripts/migrate_report_md_to_files.py --verify   # 突き合わせだけ

ORM は使わない（モデルから report_md 列を外したので読めない）。sqlite3 で直接読む。
"""

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app import report_store  # noqa: E402

DEFAULT_DB = REPO_ROOT / "backend" / "reading.db"

QUERY = """
SELECT b.id, b.title, b.author, b.isbn, b.genre, b.status, b.rating,
       b.started_on, b.finished_on, b.report_md
  FROM books AS b
 WHERE b.report_md IS NOT NULL AND TRIM(b.report_md) <> ''
 ORDER BY b.id
"""

TAGS_QUERY = """
SELECT t.name
  FROM tags AS t
  JOIN book_tags AS bt ON bt.tag_id = t.id
 WHERE bt.book_id = ?
 ORDER BY t.name
"""


def _as_date(value):
    """SQLite の文字列日付を date にする（読めない形はそのまま返す）。"""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return value


def load_books(db_path: Path) -> list[SimpleNamespace]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(QUERY).fetchall()
        books = []
        for row in rows:
            tags = [r["name"] for r in con.execute(TAGS_QUERY, (row["id"],))]
            books.append(SimpleNamespace(
                id=row["id"],
                title=row["title"],
                author=row["author"],
                isbn=row["isbn"],
                genre=row["genre"],
                status=row["status"],
                rating=row["rating"],
                started_on=_as_date(row["started_on"]),
                finished_on=_as_date(row["finished_on"]),
                tags=tags,
                report_md=row["report_md"],
            ))
        return books
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="読み込む reading.db")
    parser.add_argument("--apply", action="store_true", help="実際にファイルを書く")
    parser.add_argument("--verify", action="store_true",
                        help="書かずに、ファイルと DB の本文が一致しているかだけ調べる")
    args = parser.parse_args()

    if not args.db.is_file():
        print(f"DB が見つかりません: {args.db}", file=sys.stderr)
        return 1

    books = load_books(args.db)
    directory = report_store.reports_dir()
    print(f"DB: {args.db}")
    print(f"出力先: {directory}")
    print(f"本文を持つ本: {len(books)} 冊\n")

    written = skipped = mismatched = 0
    for book in books:
        body = book.report_md.strip()
        current = report_store.read(book.id)
        if current == body:
            skipped += 1
            print(f"  = {book.id:4} {book.title[:40]}（ファイルと一致。飛ばす）")
            continue
        if args.verify:
            mismatched += 1
            state = "ファイルなし" if current is None else "内容が違う"
            print(f"  ! {book.id:4} {book.title[:40]}（{state}）")
            continue
        if not args.apply:
            print(f"  + {book.id:4} {book.title[:40]}（{len(body)} 文字 → "
                  f"{report_store.filename_for(book)}）")
            written += 1
            continue

        path = report_store.save(book, body)
        # 書いた直後に読み戻して、本文が欠けていないことを確かめる
        roundtrip = report_store.read(book.id)
        if roundtrip != body:
            print(f"  ! {book.id:4} {book.title[:40]} … 読み戻しが一致しません", file=sys.stderr)
            return 2
        written += 1
        print(f"  + {book.id:4} {book.title[:40]} → {path.name}")

    print()
    if args.verify:
        print(f"一致 {skipped} 冊 / 不一致 {mismatched} 冊")
        return 1 if mismatched else 0
    if args.apply:
        print(f"書き出し {written} 冊 / 既に一致していて飛ばした {skipped} 冊")
        print("DB の books.report_md は変更していない（凍結コピーとして残す）。")
    else:
        print(f"下見のみ。--apply を付けると {written} 冊を書き出す"
              f"（既に一致 {skipped} 冊は飛ばす）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
