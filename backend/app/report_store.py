"""読書レポート本文（Markdown ファイル）のストア

読書レポートは **ファイルが正**（2026-10-11 の方針変更。
`Storage/_vault/document-storage-policy.md`）。長文を DB の TEXT 列に入れていると:

- サービス経由でしか読めない（`grep` も Obsidian も効かない）
- 上書きで前の本文が消える（履歴が無い）
- バックアップが「DB を丸ごとコピー」しかない

の3点が、読書レポートの性質（長文・あとから読み返す・推移を追いたい）と合わない。

一方で**書誌・進捗・採点・タグ・引用メモ・提案（books / notes / suggestions）は DB に残す**。
短い構造化レコードで、SQL の集計と外部キーが効くほうが素直なため。この境界が
「一部だけファイルに移管した」の意味。移管前に本文を入れていた `books.report_md` 列は
モデルから外してあり（**アプリは読み書きしない**）、`scripts/drop_unused_columns.py` で DB からも消す
（`docs/design/0004-drop-unused-columns.md`）。

置き場所: `<repo>/reports/<book_id>-<タイトル>.md`（環境変数 `NOTES_REPORTS_DIR` で変更可）

正の鍵は **frontmatter の `book_id`**。ファイル名は人が読むための飾りなので、
Obsidian で改名されても索引は壊れない。ファイル名は最初に保存したときのタイトルで決まり、
あとでタイトルを直しても**アプリは改名しない**。テーマノート（`themes/`）や他のレポートから
手で張った相対リンクが、アプリの改名で切れないようにするため（Obsidian は自分で改名した
ときしかリンクを直さない）。

frontmatter でアプリが書くのは `type` / `book_id` / `updated` の3つだけ。書誌
（title / author / status / rating / tags …）は DB にだけあり、ファイルには複製しない
（`docs/design/0001-storage-boundary.md`）。同じ値が2か所にあると、どちらが正か紛らわしく、
本の更新のたびにファイルが動くため。本を更新してもレポートのファイルは書き直さない。
それ以外のキー（aliases / cssclasses など。旧版が書いた title〜tags も含む）はユーザーの
ものとして、保存しても残す。

同じ `book_id` のファイルが複数あることがある（Obsidian での複製 "0005-Foo 1.md" など）。
読み出しに使う「主」は **mtime が最も新しいもの**（同値ならパス名順）で、主を消せば
残りが繰り上がる。保存は主にしか書かず、他のファイルを上書きも削除もしない。
本の削除では、id が再利用されても孤児が新しい本に紐づかないよう、その `book_id` を
持つ全ファイルを対象にする。

消したファイルは unlink せず `reports/.trash/` へ移す（隠しディレクトリなので索引にも
Obsidian にも出ない）。

書き込みは IdeaPool の reviews と同じ作法:

    flock(.write.lock) → tmp に書く → flush → fsync → os.replace → 親を fsync

読み手はロックを取らない（`os.replace` が原子的なので、常に古いか新しいかの
どちらか完全な内容を読む）。索引は mtime+size での再検証付きインメモリ辞書。
「索引から主を引く → 本文を読む → 書く」はロックの中で1つの臨界区間にする
（ロックの外で読んだ本文で、その間に完了した別の保存を上書きしないため）。
"""

import fcntl
import os
import re
import threading
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, Union

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"

LOCK_NAME = ".write.lock"
TMP_SUFFIX = ".tmp"
TRASH_NAME = ".trash"
# ファイル名に使えない文字と制御文字。タイトルから落とす。
_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_SPACES = re.compile(r"\s+")
_FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_SLUG_LIMIT = 60

REPORT_TYPE = "reading-report"


def reports_dir() -> Path:
    return Path(os.environ.get("NOTES_REPORTS_DIR", str(DEFAULT_REPORTS_DIR)))


# ── frontmatter ─────────────────────────────────────────────

def split_front_matter(text: str) -> tuple[dict, str]:
    """先頭の frontmatter を辞書として切り出し、(メタ, 本文) を返す。

    frontmatter が無い・壊れている・マッピングでない場合は `({}, text)`。
    本文を失わないことを優先する（レポート本文はユーザーが書いた一次データで、
    メタ情報は DB から作り直せる）。先頭に BOM があれば取り除いて解釈する。

    「壊れている」には、YAML としては正しいが日付として不正な値（`started_on: 2026-02-30`
    など）も含む。PyYAML は timestamp の構築で YAMLError ではなく ValueError を投げる。
    これを通すと索引まで伝わり、1ファイルのせいで本の一覧が 500 になる。
    """
    text = text.removeprefix("\ufeff")
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1))
    except (yaml.YAMLError, ValueError):
        return {}, text
    if not isinstance(meta, dict):
        return {}, text
    return meta, text[match.end():]


class _ReportDumper(yaml.SafeDumper):
    """日時を ISO 8601（`T` 区切り）の裸のスカラーとして書く SafeDumper。

    PyYAML の既定の timestamp 表現は `2026-10-11 21:41:04+09:00` とスペース区切りだが、
    IdeaPool 側の frontmatter は `T` 区切りで揃っている。手で開いたときに
    書式が1つだけ違うと、どちらが正なのか分からなくなるので合わせる。
    """


def _represent_datetime(dumper: yaml.SafeDumper, data: datetime) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:timestamp", data.isoformat())


_ReportDumper.add_representer(datetime, _represent_datetime)


def build_markdown(book, body: str, extra: Optional[dict] = None) -> str:
    """frontmatter ＋ 本文 の Markdown を組み立てる。

    アプリのキーは `type` / `book_id` / `updated` の3つだけ。`extra`（既存ファイルの
    frontmatter）のそれ以外のキーはユーザーのものとして、3つの後ろに元の順で残す。
    旧版が書いた title〜tags もここでは消さない（`scripts/strip_report_frontmatter.py`
    が一度だけ取り除く）。
    """
    meta = {
        "type": REPORT_TYPE,
        "book_id": book.id,
        "updated": datetime.now().astimezone().replace(microsecond=0),
    }
    for key, value in (extra or {}).items():
        if key not in meta:
            meta[key] = value
    return front_matter_text(meta) + f"\n{body.strip()}\n"


def front_matter_text(meta: dict) -> str:
    """frontmatter（`---` で囲んだ YAML）を、閉じの `---` の後ろの改行まで含めて返す。

    レポートのほか、著者ノートの雛形も同じ書き方で書く。
    width を無限にするのは、折り返しで "key: value" の形が崩れるのを防ぐため。
    """
    front = yaml.dump(
        meta, Dumper=_ReportDumper, allow_unicode=True, sort_keys=False,
        default_flow_style=False, width=float("inf"),
    ).strip()
    return f"---\n{front}\n---\n"


# ── ファイル名 ──────────────────────────────────────────────

def _slug(title: str) -> str:
    text = _UNSAFE_CHARS.sub("", title or "")
    text = _SPACES.sub("-", text.strip()).strip("-.")
    return text[:_SLUG_LIMIT].strip("-.") or "untitled"


def filename_for(book) -> str:
    """`<book_id 4桁>-<タイトル>.md`。並べたときに id 順になるよう0詰めする。"""
    return f"{book.id:04d}-{_slug(book.title)}.md"


# ── 索引 ────────────────────────────────────────────────────

def _parse_book_id(value) -> Optional[int]:
    """frontmatter の `book_id` を int にする。解釈できなければ None。

    Obsidian の Properties UI は数値を文字列 "5" や 5.0 で書き直すことがある。
    bool は int のサブクラスだが book_id ではないので除く。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        return int(value.strip())
    return None


def _read_text(path: Path) -> str:
    # utf-8-sig: 先頭の BOM を取り除く（BOM なしならそのまま読める）
    return path.read_text(encoding="utf-8-sig")


@dataclass(frozen=True)
class _Entry:
    path: Path
    mtime_ns: int
    has_body: bool


class _ReportIndex:
    """book_id → 候補ファイル の索引。mtime+size が変わったファイルだけ読み直す。

    毎リクエスト再検証するのは、Obsidian やエディタからの直接編集を取り込むため。
    frontmatter の `book_id` が鍵なので、ファイル名が変わっても追従できる。
    同じ book_id の候補が複数あれば、mtime が新しい順（同値ならパス名順）に並べ、
    先頭を「主」とする。本文の有無も索引に持つので、一覧で全ファイルを読み直さない。
    """

    def __init__(self, directory: Path):
        self._directory = directory
        self._lock = threading.Lock()
        self._state: dict[Path, tuple[int, int]] = {}
        # book_id を持つファイルだけ入る
        self._info: dict[Path, tuple[int, int, bool]] = {}

    def _refresh(self) -> dict[int, list[_Entry]]:
        with self._lock:
            entries = []
            try:
                with os.scandir(self._directory) as it:
                    for e in it:
                        # 自分を指す symlink などは is_file() が例外を出す。1つのせいで
                        # 全レポートが見えなくならないよう、その項目だけ飛ばす
                        try:
                            if e.is_file() and e.name.endswith(".md"):
                                entries.append(e)
                        except OSError:
                            continue
            except OSError:
                entries = []

            seen: set[Path] = set()
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                path = Path(entry.path)
                seen.add(path)
                try:
                    stat_result = entry.stat()
                except OSError:
                    seen.discard(path)
                    continue
                state = (stat_result.st_mtime_ns, stat_result.st_size)
                if self._state.get(path) == state:
                    continue
                try:
                    text = _read_text(path)
                except (OSError, UnicodeDecodeError):
                    continue
                meta, body = split_front_matter(text)
                book_id = _parse_book_id(meta.get("book_id"))
                self._info.pop(path, None)
                if book_id is not None:
                    self._info[path] = (book_id, state[0], bool(body.strip()))
                self._state[path] = state

            # 消えたファイルを索引から外す。`_state` だけでなく `_info` も
            # 走査対象にする（invalidate() で state を落としたパスが残るため）。
            for path in (set(self._state) | set(self._info)) - seen:
                self._info.pop(path, None)
                self._state.pop(path, None)

            grouped: dict[int, list[_Entry]] = {}
            for path, (book_id, mtime_ns, has_body) in self._info.items():
                grouped.setdefault(book_id, []).append(_Entry(path, mtime_ns, has_body))
            for candidates in grouped.values():
                candidates.sort(key=lambda e: (-e.mtime_ns, e.path.name))
            return grouped

    def entries(self) -> dict[int, list[_Entry]]:
        return self._refresh()

    def candidates_of(self, book_id: int) -> list[_Entry]:
        """主を先頭にした、その book_id を持つ全ファイル。"""
        return self._refresh().get(book_id, [])

    def path_of(self, book_id: int) -> Optional[Path]:
        candidates = self.candidates_of(book_id)
        return candidates[0].path if candidates else None

    def invalidate(self, path: Path) -> None:
        """自分で書き換えた直後に、次回の再検証を確実にする。"""
        with self._lock:
            self._state.pop(path, None)


_INDEXES: dict[Path, _ReportIndex] = {}
_INDEXES_LOCK = threading.Lock()


def _index() -> _ReportIndex:
    """ディレクトリごとに索引を1つ持つ（テストが環境変数で置き場所を変えるため）。"""
    key = Path(os.path.abspath(reports_dir()))
    with _INDEXES_LOCK:
        index = _INDEXES.get(key)
        if index is None:
            index = _ReportIndex(key)
            _INDEXES[key] = index
        return index


# ── 読み取り ────────────────────────────────────────────────

def read(book_id: int) -> Optional[str]:
    """レポート本文（frontmatter を除いた Markdown）。無ければ None。"""
    path = _index().path_of(book_id)
    if path is None:
        return None
    return _read_body(path)


def _read_body(path: Path) -> Optional[str]:
    try:
        text = _read_text(path)
    except (OSError, UnicodeDecodeError):
        return None
    _, body = split_front_matter(text)
    return body.strip() or None


def has_report(book_id: int) -> bool:
    """本文が空でないレポートがあるか（`read` が None を返さないことと一致させる）。"""
    candidates = _index().candidates_of(book_id)
    return bool(candidates) and candidates[0].has_body


def report_paths() -> dict[int, Path]:
    """本文が空でないレポートの主のパスを book_id ごとに返す（テーマノートのリンク先）。

    本ごとに stat しないよう1回の走査でまとめて引く。
    """
    return {
        book_id: candidates[0].path
        for book_id, candidates in _index().entries().items()
        if candidates[0].has_body
    }


def book_ids_with_report() -> set[int]:
    """一覧で使う。本ごとに stat しないよう1回の走査でまとめて返す。"""
    return set(report_paths())


# ── 書き込み ────────────────────────────────────────────────

@contextmanager
def write_lock(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / LOCK_NAME
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _fsync_dir(directory: Path) -> None:
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


class _Absent:
    """`write_atomic` の `expect` に渡す「まだ無いはず」の目印（`ABSENT`）。"""

    def __repr__(self) -> str:
        return "ABSENT"


ABSENT = _Absent()


def _stat_key(path: Path) -> Optional[tuple[int, int]]:
    """`write_atomic` の `expect` と比べる（mtime_ns, サイズ）。ファイルが無ければ None。"""
    try:
        result = path.stat()
    except FileNotFoundError:
        return None
    return result.st_mtime_ns, result.st_size


def write_atomic(path: Path, text: str, *,
                 expect: Union[tuple[int, int], _Absent, None] = None) -> bool:
    """tmp に書いて fsync し、`path` を原子的に置き換える。置き換えたら True。

    `expect` は、Obsidian のようにロックを取らない書き手と競合しないための条件。
    置き換える直前に `path` を調べ直し、合わなければ tmp を消して、置き換えずに False を返す
    （相手の保存を消さない。呼び出し側は次の機会にやり直す）。

    - `(st_mtime_ns, st_size)`: 呼び出し側が読む前に調べた値。違う（変わった・消えた）なら False
    - `ABSENT`: まだ無いはず。置き換えの代わりに `os.link` で作るので、直前に同名のファイルが
      できていれば上書きせず False（`os.replace` は黙って上書きしてしまう）
    - `None`（既定）: 条件なし。必ず置き換える

    直前の確認と置き換えの間は、ロックが無い以上ゼロにはできない（マイクロ秒）。ここで防ぐのは、
    読んでから tmp を書いて fsync するまでの長い間（ミリ秒〜）の保存。mtime とサイズが
    どちらも同じままの書き換えは見分けられない。
    """
    tmp = path.with_name(path.name + TMP_SUFFIX)
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        if expect is ABSENT:
            try:
                os.link(tmp, path)
            except FileExistsError:
                tmp.unlink()
                return False
            tmp.unlink()
        else:
            if expect is not None and _stat_key(path) != expect:
                tmp.unlink()
                return False
            os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)
    return True


def _free_name(directory: Path, filename: str) -> Path:
    """`0005-Foo.md` が埋まっていれば `0005-Foo-2.md`、`-3` … と空きを探す。"""
    stem = filename.removesuffix(".md")
    n = 2
    while (directory / f"{stem}-{n}.md").exists():
        n += 1
    return directory / f"{stem}-{n}.md"


def _same_except_updated(new_text: str, old_text: str) -> bool:
    """`updated` 以外の frontmatter と本文が同じか。"""
    new_meta, new_body = split_front_matter(new_text)
    old_meta, old_body = split_front_matter(old_text)
    new_meta.pop("updated", None)
    old_meta.pop("updated", None)
    return new_meta == old_meta and new_body.strip() == old_body.strip()


def _save_locked(book, body: str) -> Path:
    """`write_lock` を取った状態で呼ぶ。

    既にレポートがあれば主にそのまま書く（タイトルが変わっていても改名しない）。
    新規なら `filename_for` の名前、それが埋まっていれば衝突しない別名にする。
    主以外のファイルには触れない。
    """
    directory = reports_dir()
    index = _index()
    current = index.path_of(book.id)

    extra: dict = {}
    current_text = ""
    if current is not None:
        try:
            current_text = _read_text(current)
        except (OSError, UnicodeDecodeError):
            current_text = ""
        extra, _ = split_front_matter(current_text)

    if current is not None:
        dest = current
    else:
        target = directory / filename_for(book)
        dest = _free_name(directory, target.name) if target.exists() else target

    text = build_markdown(book, body, extra)
    if current is not None and _same_except_updated(text, current_text):
        # エディタは閉じるたびに同じ本文を送ってくる。中身が変わらないのに
        # `updated` と mtime だけ動くと、週次コミットの差分がノイズになる。
        return dest
    write_atomic(dest, text)
    index.invalidate(dest)
    return dest


def _trash(path: Path, directory: Path) -> bool:
    """`.trash/<YYYYmmdd-HHMMSS>-<元のファイル名>` へ移す。名前が衝突したら連番。"""
    trash = directory / TRASH_NAME
    trash.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = trash / f"{stamp}-{path.name}"
    n = 2
    while dest.exists():
        dest = trash / f"{stamp}-{path.stem}-{n}.md"
        n += 1
    try:
        os.replace(path, dest)
    except FileNotFoundError:
        return False
    _fsync_dir(trash)
    _fsync_dir(directory)
    return True


def _delete_locked(book_id: int) -> bool:
    directory = reports_dir()
    index = _index()
    moved = False
    for entry in index.candidates_of(book_id):
        try:
            moved = _trash(entry.path, directory) or moved
        finally:
            index.invalidate(entry.path)
    return moved


def save(book, body: Optional[str]) -> Optional[Path]:
    """レポート本文を保存する。空文字・None なら削除（ゴミ箱へ）する。

    タイトルが変わっていてもファイル名は変えない（手で張ったリンクを切らないため）。
    既存ファイルの frontmatter は `type` / `book_id` / `updated` だけをアプリの値に
    し、ユーザーが足したキーは残す。
    """
    if body is None or not body.strip():
        delete(book.id)
        return None

    with write_lock(reports_dir()):
        return _save_locked(book, body)


def delete(book_id: int) -> bool:
    """その book_id を持つ全ファイルを `.trash/` へ移す。移したら True。

    本の削除で id が再利用されたとき、孤児のレポートが新しい本に紐づくのを防ぐため、
    主だけでなく複製も対象にする。
    """
    with write_lock(reports_dir()):
        return _delete_locked(book_id)
