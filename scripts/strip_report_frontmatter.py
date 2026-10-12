#!/usr/bin/env python3
"""レポートの frontmatter から、DB の書誌の複製（旧版が書いた title〜tags）を取り除く1回限りの移行

2026-10-12 の方針変更（`docs/design/0001-storage-boundary.md`）で、レポートの
frontmatter でアプリが書くのは `type` / `book_id` / `updated` の3つだけになった。
書誌は DB にだけ置く（同じ値を2か所に持たない）。旧版が書いたファイルには
title / author / isbn / genre / status / rating / started_on / finished_on / tags が
残っているので、このスクリプトで一度だけ取り除く。

- 対象は `reports/` の直下の `*.md` で、`type: reading-report` のもの。`themes/` や
  `authors/`、`.trash/`、`.` で始まるファイル、frontmatter の無い手書きメモは見ない。
  symlink の `*.md` はアプリの索引には見えるが、書き換えるとリンクを実ファイルに
  置き換えてしまうので、名前を出して対象外にする。
- 取り除くのは上の9個のキーだけ。**旧キーの行だけを文字列として削除する**ので、
  `updated` や、ユーザーが足した aliases などの行は1バイトも変わらない（YAML を読んで
  書き直すと、コメントが消える・`yes` が `true` になる・`0123` が `83` になる・フロー形式が
  ブロック形式になるなど、残すキーまで変わるため）。BOM・改行コード（CRLF）・本文も元のまま。
- 行を消したあとの全文を読み直し、残したキーが「元から旧キーを除いたもの」と、本文が
  元と等しいことを確かめる。旧キーがフロー形式で複数行にまたがる、引用符付き文字列が
  複数行になっているなど、行の削除では壊れる書き方はここで弾かれる（書かずに報告する）。
- DB は読まない・変えない。
- 冪等。取り除くものが無いファイルは書かない（mtime を無駄に動かさない）。
- 既定は dry-run（差分を表示するだけ）。実際に書くときは `--apply` を付ける。
- `--apply` では書いたあとに mode と mtime を元に戻す。同じ `book_id` のファイルが複数
  あるとき（Obsidian での複製）、索引は mtime が最新のものを「主」にする。移行で古い複製の
  mtime が新しくなると、主が入れ替わって別の本文が出てしまうため。mode は、一時ファイルが
  umask で作られて 0600 のファイルが 0644 になるのを防ぐ。

使い方:
    .venv/bin/python scripts/strip_report_frontmatter.py            # 下見（差分を表示）
    .venv/bin/python scripts/strip_report_frontmatter.py --apply    # 実行

流す順序（重要）:
    1. 新しいコード（旧キーを書かない版）をデプロイしてアプリを再起動する。**先に流すと、
       旧コードの refresh_meta() が次の本の更新でキーを書き戻す。**
    2. Obsidian でレポートを編集中なら閉じる（開いたままのエディタが古い frontmatter で
       保存し直すことがある。その場合はもう一度流せばよい）。
    3. 下見 → 差分を確認 → `--apply` → もう一度下見して「書き換え 0」を確認する。

終了コードは、読めない・検証に通らない・書けない・読んでから書くまでの間に変更された
ファイルがあれば 1。先頭が `---` なのに frontmatter が読めないファイル（YAML の誤りや
`started_on: 2026-02-30` のような不正な日付）は対象外として名前を stderr に出す。
旧キーが残っていても取り除けないので、手で直してからもう一度流す。
"""

import argparse
import difflib
import os
import re
import stat
import sys
from collections import Counter
from contextlib import suppress
from pathlib import Path
from typing import NamedTuple, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app import report_store  # noqa: E402

# 旧版が DB から複製していた書誌のキー。このスクリプトの中だけで使う
LEGACY_KEYS = ("title", "author", "isbn", "genre", "status", "rating",
               "started_on", "finished_on", "tags")

# トップレベル（インデントなし）の旧キーの行。コロンの後ろが空白か行末のときだけキーとみなす
# （`tags:foo` は YAML ではキーではない）
_LEGACY_KEY_LINE = re.compile(
    r"(?:%s)[ \t]*:(?:[ \t]|$)" % "|".join(re.escape(key) for key in LEGACY_KEYS)
)
# 旧キーの値の続き。インデント付きの行と、`tags:\n- a` のようにキーと同じ位置から始まる
# ブロック形式のリストの要素
_CONTINUATION_LINE = re.compile(r"[ \t]|-(?:[ \t]|$)")
# 改行は \n だけで切る（str.splitlines() は U+2028 などでも切るので値の中身を壊す）
_LINE = re.compile(r"[^\n]*\n|[^\n]+")

# _examine() / _apply() が返すファイルの状態
REWRITE = "rewrite"            # 旧キーがあり、取り除ける
CLEAN = "clean"                # レポートだが旧キーが無い
OTHER = "other"                # レポートではない（frontmatter が無い・type が違う）
BROKEN = "broken"              # 先頭が --- なのに frontmatter が読めない（OTHER の一種）
SYMLINK = "symlink"            # symlink（書き換えない）
UNREADABLE = "unreadable"      # ファイルが読めない
INVALID = "invalid"            # 取り除いた結果が検証に通らない
CHANGED = "changed"            # 読んでから書くまでの間に変更された
WRITE_FAILED = "write_failed"  # 書き込み・mode と mtime の復元で OSError

ERROR_STATES = (UNREADABLE, INVALID, CHANGED, WRITE_FAILED)


class _Examined(NamedTuple):
    state: str
    old_text: str = ""
    new_text: str = ""    # REWRITE のときだけ
    removed: tuple = ()   # REWRITE のときだけ。取り除くキー
    detail: str = ""      # WRITE_FAILED のときだけ。エラーの内容


def _split_front_matter_lines(text: str) -> tuple[str, list[str], str]:
    """(BOM, frontmatter の行, 本文) に分ける。frontmatter が無ければ行は空。

    行は改行付きで、開きの `---` の行から閉じの `---` の行まで。3つをつなぐと元の文字列に戻る。
    """
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    text = text[len(bom):]
    _, body = report_store.split_front_matter(text)
    return bom, _LINE.findall(text[: len(text) - len(body)]), body


def _drop_legacy_lines(lines: list[str]) -> list[str]:
    """YAML 部分の行から、旧キーの行とその値の続きの行を取り除く。それ以外の行は触らない。

    値の続きは、旧キーの行の後ろの、先頭が空白の行と `- ` で始まる行。トップレベルの
    別のキーの行、`#` で始まるコメントの行で終わる（そこから先はユーザーのもの）。
    空行は、あとに値の続きが来るときだけ値の一部（ブロック文字列の中の空行）として消し、
    そうでなければ残す。
    """
    kept: list[str] = []
    blanks: list[str] = []   # 値の続きが来るまで保留する空行
    deleting = False
    for line in lines:
        content = line.rstrip("\r\n")
        if deleting and not content.strip(" \t"):
            blanks.append(line)
            continue
        if deleting and _CONTINUATION_LINE.match(content):
            blanks.clear()
            continue
        kept.extend(blanks)
        blanks.clear()
        deleting = bool(_LEGACY_KEY_LINE.match(content))
        if not deleting:
            kept.append(line)
    kept.extend(blanks)
    return kept


def plan(text: str) -> Optional[tuple[str, list[str]]]:
    """旧キーを取り除いた (新しい全文, 取り除いたキー) を返す。取り除くものが無ければ None。

    `type` は見ない（レポートかどうかの判定は呼び出し側）。旧キーの行を消すだけで、
    残りの行・開きと閉じの `---`・BOM・改行コード・本文は元の文字列のまま。消したあとの全文を
    読み直して、残したキーと本文が元のままであることを確かめ、違えば ValueError
    （その場合は書いてはいけない）。
    """
    meta, _ = report_store.split_front_matter(text)
    removed = [key for key in LEGACY_KEYS if key in meta]
    if not removed:
        return None
    bom, lines, body = _split_front_matter_lines(text)
    opening, yaml_lines, closing = lines[0], lines[1:-1], lines[-1]
    new_text = bom + opening + "".join(_drop_legacy_lines(yaml_lines)) + closing + body
    expected = {key: value for key, value in meta.items() if key not in LEGACY_KEYS}
    if report_store.split_front_matter(new_text) != (expected, body):
        raise ValueError("旧キーの行を消したあとの frontmatter を読むと、残すキーか本文が元と一致しない")
    return new_text, removed


def _read(path: Path) -> str:
    # 改行を変換しない（read_text だと CRLF が LF になり、本文が変わってしまう）
    return path.read_bytes().decode("utf-8")


def _examine(path: Path) -> _Examined:
    """ファイルを読んで、書き換えられるかを調べる。書かない。"""
    if path.is_symlink():
        return _Examined(SYMLINK)
    try:
        text = _read(path)
    except (OSError, UnicodeDecodeError):
        return _Examined(UNREADABLE)
    meta, _ = report_store.split_front_matter(text)
    if meta.get("type") != report_store.REPORT_TYPE:
        # 先頭が --- で始まるのに読めないのは、frontmatter があるつもりのファイルが壊れている
        # ということ。旧キーが残っていても分からないので、無いファイルとは分けて知らせる
        broken = not meta and text.removeprefix("\ufeff").startswith("---")
        return _Examined(BROKEN if broken else OTHER, text)
    try:
        result = plan(text)
    except ValueError:
        return _Examined(INVALID, text)
    if result is None:
        return _Examined(CLEAN, text)
    new_text, removed = result
    return _Examined(REWRITE, text, new_text, tuple(removed))


def _show_diff(path: Path, examined: _Examined) -> None:
    def front_lines(text: str) -> list[str]:
        _, lines, _ = _split_front_matter_lines(text)
        return [line.rstrip("\r\n") for line in lines]

    diff = difflib.unified_diff(
        front_lines(examined.old_text), front_lines(examined.new_text),
        fromfile=f"a/{path.name}", tofile=f"b/{path.name}", n=1, lineterm="",
    )
    for line in diff:
        print(f"    {line}")


def _target_files(directory: Path) -> list[Path]:
    """`reports/` の直下の `*.md`（`.` で始まるものと、サブディレクトリの中は除く）。

    symlink も含める。アプリの索引は symlink を辿るので、見えているファイルを黙って
    飛ばさず、`_examine` が名前を出して対象外にする。
    """
    with os.scandir(directory) as it:
        return sorted(
            Path(entry.path) for entry in it
            if entry.name.endswith(".md")
            and not entry.name.startswith(".")
            and entry.is_file()
        )


def _apply(directory: Path, path: Path) -> _Examined:
    """ロックの中で読み直してから書き、mode と mtime を元に戻す。

    アプリが同じファイルを保存中でも、古い内容で上書きしないよう読み直す。ただしこのロックは
    Obsidian には効かないので、読んだあとに保存されることがある。書く直前に stat し直し、
    (mtime, size) が変わっていたら書かない（その保存を失わず、戻す mtime も古くならない
    ように。もう一度流せばよい）。
    """
    with report_store.write_lock(directory):
        try:
            before = path.stat()
        except OSError:
            return _Examined(UNREADABLE)
        examined = _examine(path)
        if examined.state != REWRITE:
            return examined

        try:
            now = path.stat()
        except OSError:
            return _Examined(CHANGED)
        if (now.st_mtime_ns, now.st_size) != (before.st_mtime_ns, before.st_size):
            return _Examined(CHANGED)

        try:
            report_store.write_atomic(path, examined.new_text)
            os.chmod(path, stat.S_IMODE(before.st_mode))
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        except OSError as error:
            # 一時ファイルへの書き込みの途中で失敗すると、それが残ることがある
            with suppress(OSError):
                path.with_name(path.name + report_store.TMP_SUFFIX).unlink()
            return _Examined(WRITE_FAILED, detail=str(error))
        return examined


def _warn(message: str) -> None:
    print(f"  ! {message}", file=sys.stderr)


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

    counts: Counter = Counter()
    for path in files:
        examined = _apply(directory, path) if args.apply else _examine(path)

        counts[examined.state] += 1
        if examined.state == REWRITE:
            print(f"- {path.name}: {', '.join(examined.removed)} を取り除く")
            if not args.apply:
                _show_diff(path, examined)
        elif examined.state == SYMLINK:
            _warn(f"{path.name}（symlink なので対象外。リンク先は書き換えません）")
        elif examined.state == BROKEN:
            _warn(f"{path.name}（frontmatter が読めないので対象外。旧キーが残っていても"
                  "取り除けません。YAML や日付の誤りを直してください）")
        elif examined.state == UNREADABLE:
            _warn(f"{path.name}（読めません）")
        elif examined.state == INVALID:
            _warn(f"{path.name}（旧キーの行を消すと frontmatter が元と一致しないので書きません）")
        elif examined.state == CHANGED:
            _warn(f"{path.name}（読んでから書くまでの間に変更されたので書きません。"
                  "もう一度流してください）")
        elif examined.state == WRITE_FAILED:
            _warn(f"{path.name}（書けません: {examined.detail}）")

    errors = sum(counts[state] for state in ERROR_STATES)
    skipped = counts[OTHER] + counts[BROKEN] + counts[SYMLINK]
    print()
    print(f"書き換え {counts[REWRITE]} / 旧キーなし {counts[CLEAN]} / "
          f"対象外 {skipped}（symlink {counts[SYMLINK]}・frontmatter が読めない {counts[BROKEN]}）/ "
          f"読めない・検証失敗・書けない・途中で変更 {errors}")
    if not args.apply:
        print(f"下見のみ。--apply を付けると {counts[REWRITE]} 件を書き換える。")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
