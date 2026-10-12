#!/usr/bin/env python3
"""レポートの frontmatter から、DB の書誌の複製（旧版が書いた title〜tags）を取り除く1回限りの移行

2026-10-12 の方針変更（`docs/design/0001-storage-boundary.md`）で、レポートの
frontmatter でアプリが書くのは `type` / `book_id` / `updated` の3つだけになった。
書誌は DB にだけ置く（同じ値を2か所に持たない）。旧版が書いたファイルには
title / author / isbn / genre / status / rating / started_on / finished_on / tags が
残っているので、このスクリプトで一度だけ取り除く。

- 対象は `reports/` の直下の `*.md` で、`type: reading-report` のもの。`themes/` や
  `authors/`、`.trash/`、`.` で始まるファイル、frontmatter の無い手書きメモは見ない。
- 取り除くのは上の9個のキーだけ。`updated` や、ユーザーが足した aliases などは触らない。
  **本文は1バイトも変えない。**
- DB は読まない・変えない。
- 冪等。取り除くものが無いファイルは書かない（mtime を無駄に動かさない）。
- 既定は dry-run（差分を表示するだけ）。実際に書くときは `--apply` を付ける。
- `--apply` では書いたあとに mtime を元に戻す。同じ `book_id` のファイルが複数あるとき
  （Obsidian での複製）、索引は mtime が最新のものを「主」にする。移行で古い複製の
  mtime が新しくなると、主が入れ替わって別の本文が出てしまうため。

使い方:
    .venv/bin/python scripts/strip_report_frontmatter.py            # 下見（差分を表示）
    .venv/bin/python scripts/strip_report_frontmatter.py --apply    # 実行

流す順序（重要）:
    1. 新しいコード（旧キーを書かない版）をデプロイしてアプリを再起動する。**先に流すと、
       旧コードの refresh_meta() が次の本の更新でキーを書き戻す。**
    2. Obsidian でレポートを編集中なら閉じる（開いたままのエディタが古い frontmatter で
       保存し直すことがある。その場合はもう一度流せばよい）。
    3. 下見 → 差分を確認 → `--apply` → もう一度下見して「書き換え 0」を確認する。
"""

import argparse
import difflib
import os
import sys
from pathlib import Path
from typing import NamedTuple, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app import report_store  # noqa: E402

# 旧版が DB から複製していた書誌のキー。このスクリプトの中だけで使う
LEGACY_KEYS = ("title", "author", "isbn", "genre", "status", "rating",
               "started_on", "finished_on", "tags")

# _examine() が返すファイルの状態
REWRITE = "rewrite"        # 旧キーがあり、取り除ける
CLEAN = "clean"            # レポートだが旧キーが無い
OTHER = "other"            # レポートではない（frontmatter が無い・壊れている・type が違う）
UNREADABLE = "unreadable"  # ファイルが読めない
INVALID = "invalid"        # 取り除いた結果が検証に通らない


class _Examined(NamedTuple):
    state: str
    old_text: str = ""
    new_text: str = ""    # REWRITE のときだけ
    removed: tuple = ()   # REWRITE のときだけ。取り除くキー


def plan(text: str) -> Optional[tuple[str, list[str]]]:
    """旧キーを取り除いた (新しい全文, 取り除いたキー) を返す。取り除くものが無ければ None。

    `type` は見ない（レポートかどうかの判定は呼び出し側）。本文は元の文字列のまま
    つなぐ。書き出した frontmatter を読み戻して、残したキーと本文が元のままであることを
    確かめ、違えば ValueError（その場合は書いてはいけない）。
    """
    meta, body = report_store.split_front_matter(text)
    removed = [key for key in LEGACY_KEYS if key in meta]
    if not removed:
        return None
    new_meta = {key: value for key, value in meta.items() if key not in LEGACY_KEYS}
    new_text = report_store.front_matter_text(new_meta) + body
    if report_store.split_front_matter(new_text) != (new_meta, body):
        raise ValueError("書き出した frontmatter を読み戻すと元と一致しない")
    return new_text, removed


def _read(path: Path) -> str:
    # 改行を変換しない（read_text だと CRLF が LF になり、本文が変わってしまう）
    return path.read_bytes().decode("utf-8")


def _examine(path: Path) -> _Examined:
    """ファイルを読んで、書き換えられるかを調べる。書かない。"""
    try:
        text = _read(path)
    except (OSError, UnicodeDecodeError):
        return _Examined(UNREADABLE)
    meta, _ = report_store.split_front_matter(text)
    if meta.get("type") != report_store.REPORT_TYPE:
        return _Examined(OTHER, text)
    try:
        result = plan(text)
    except ValueError:
        return _Examined(INVALID, text)
    if result is None:
        return _Examined(CLEAN, text)
    new_text, removed = result
    return _Examined(REWRITE, text, new_text, tuple(removed))


def _front_lines(text: str) -> list[str]:
    """frontmatter 部分（閉じの `---` の行まで）の行。差分の表示に使う。"""
    text = text.removeprefix("\ufeff")
    _, body = report_store.split_front_matter(text)
    return text[: len(text) - len(body)].splitlines()


def _show_diff(path: Path, examined: _Examined) -> None:
    diff = difflib.unified_diff(
        _front_lines(examined.old_text), _front_lines(examined.new_text),
        fromfile=f"a/{path.name}", tofile=f"b/{path.name}", n=1, lineterm="",
    )
    for line in diff:
        print(f"    {line}")


def _target_files(directory: Path) -> list[Path]:
    """`reports/` の直下の通常の `*.md`（`.` で始まるものと、サブディレクトリの中は除く）。"""
    with os.scandir(directory) as it:
        return sorted(
            Path(entry.path) for entry in it
            if entry.name.endswith(".md")
            and not entry.name.startswith(".")
            and entry.is_file(follow_symlinks=False)
        )


def _apply(directory: Path, path: Path) -> _Examined:
    """ロックの中で読み直してから書き、mtime を元に戻す。

    アプリが同じファイルを保存中でも、古い内容で上書きしないよう読み直す。
    """
    with report_store.write_lock(directory):
        try:
            before = path.stat()
        except OSError:
            return _Examined(UNREADABLE)
        examined = _examine(path)
        if examined.state == REWRITE:
            report_store.write_atomic(path, examined.new_text)
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        return examined


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="実際にファイルを書き換える")
    args = parser.parse_args(argv)

    directory = report_store.reports_dir()
    if not directory.is_dir():
        print(f"レポートのディレクトリが見つかりません: {directory}", file=sys.stderr)
        return 1

    files = _target_files(directory)
    print(f"対象: {directory}")
    print(f"直下の *.md: {len(files)} 件\n")

    counts = {REWRITE: 0, CLEAN: 0, OTHER: 0, UNREADABLE: 0, INVALID: 0}
    for path in files:
        examined = _apply(directory, path) if args.apply else _examine(path)

        counts[examined.state] += 1
        if examined.state == REWRITE:
            print(f"- {path.name}: {', '.join(examined.removed)} を取り除く")
            if not args.apply:
                _show_diff(path, examined)
        elif examined.state == UNREADABLE:
            print(f"  ! {path.name}（読めません）", file=sys.stderr)
        elif examined.state == INVALID:
            print(f"  ! {path.name}（書き出した frontmatter が元と一致しないので書きません）",
                  file=sys.stderr)

    errors = counts[UNREADABLE] + counts[INVALID]
    print()
    print(f"書き換え {counts[REWRITE]} / 旧キーなし {counts[CLEAN]} / "
          f"対象外 {counts[OTHER]} / 読めない・検証失敗 {errors}")
    if not args.apply:
        print(f"下見のみ。--apply を付けると {counts[REWRITE]} 件を書き換える。")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
