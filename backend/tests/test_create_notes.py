"""一括作成スクリプト scripts/create_notes.py のテスト

いまあるタグと本棚の著者の、テーマノート・著者ノートを空で作るスクリプト。
DB はテストごとに tmp_path へ作る SQLite のファイル（スクリプトがファイルを読み取り専用で開くため、
メモリ上の DB は使えない）、ノートとレポートは実ファイルで、`main()` を呼んで見る。
スクリプトは import できる場所（パッケージ）に無いので、パスから読み込む。
`reports/` は conftest.py が `NOTES_REPORTS_DIR` を向けた `tmp_path/reports`。
"""

import importlib.util
import os
import sqlite3
import time
from datetime import date
from pathlib import Path
from typing import NamedTuple

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import author_store, report_store, theme_store
from app.database import Base, configure_sqlite
from app.models import Book, BookStatus, Tag
from app.theme_store import END, START

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "create_notes.py"

_spec = importlib.util.spec_from_file_location("create_notes", SCRIPT)
create_notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(create_notes)

THEME_HUB = theme_store.HUB_NAME
AUTHOR_HUB = author_store.HUB_NAME


@pytest.fixture(autouse=True)
def _forget_warned_notes():
    # 警告済みのパス（壊れたマーカー・書けなかったファイル・自動作成を止めているノート）は
    # モジュール変数。テストをまたいで残さない
    warned = (theme_store._warned_broken, theme_store._warned_write_failed,
              author_store._seen_doubts, author_store._warned_doubts)
    for each in warned:
        each.clear()
    yield
    for each in warned:
        each.clear()


@pytest.fixture
def reports(tmp_path):
    # conftest が NOTES_REPORTS_DIR を tmp_path/reports に向けている（フォルダは作らない）
    directory = tmp_path / "reports"
    directory.mkdir()
    return directory


@pytest.fixture
def themes(reports):
    return reports / "themes"


@pytest.fixture
def authors(reports):
    return reports / "authors"


@pytest.fixture
def publishers(reports):
    return reports / "publishers"


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "reading.db"


class Output(NamedTuple):
    code: int
    out: str
    err: str


@pytest.fixture
def run(db_path, capsys):
    """スクリプトを流して (終了コード, 標準出力, 標準エラー) を返す。"""
    def _run(*args):
        code = create_notes.main(["--db", str(db_path), *args])
        captured = capsys.readouterr()
        return Output(code, captured.out, captured.err)
    return _run


def book(title, author=None, tags=(), status=BookStatus.UNREAD, report=False, publisher=None):
    return dict(title=title, author=author, tags=list(tags), status=status, report=report,
                publisher=publisher)


def make_db(path, books, unused_tags=()):
    """`path` に本とタグの入った SQLite を作る。本は `book()` の辞書。

    スクリプトと同じく URL 文字列を使わない（特殊文字のパスのテストでも同じ小道具を使うため）。
    `report` が True の本には、レポートを実ファイルで書く。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(str(path)))
    configure_sqlite(engine)
    Base.metadata.create_all(engine)
    tags: dict[str, Tag] = {}
    with Session(engine) as db:
        for name in unused_tags:
            db.add(tags.setdefault(name, Tag(name=name)))
        for spec in books:
            row = Book(title=spec["title"], author=spec["author"], publisher=spec["publisher"],
                       status=spec["status"])
            if spec["status"] == BookStatus.FINISHED:
                row.finished_on = date(2026, 9, 20)
            row.tags = [tags.setdefault(name, Tag(name=name)) for name in spec["tags"]]
            db.add(row)
            db.commit()
            if spec["report"]:
                report_store.save(row, "本文")
    engine.dispose()


def write_note(directory, name, content, age=60):
    """ノートを置き、更新時刻を `age` 秒前にする（直近に更新されたノートとして待たれないように）。"""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    mtime = time.time() - age
    os.utime(path, (mtime, mtime))
    return path


def backdate(*directories, age=60):
    """作ったノートの更新時刻を `age` 秒前に戻す（2回目を流すテスト用）。"""
    for directory in directories:
        for path in directory.iterdir():
            mtime = time.time() - age
            os.utime(path, (mtime, mtime))


def read(path):
    return path.read_text(encoding="utf-8")


def meta_of(path):
    meta, _ = report_store.split_front_matter(read(path))
    return meta


def names_in(directory):
    """ハブ以外のノートのファイル名の集合。"""
    if not directory.exists():
        return set()
    return {p.name for p in directory.iterdir()
            if p.is_file() and p.name not in (THEME_HUB, AUTHOR_HUB)}


def snapshot(directory):
    """ファイルごとの (中身, 更新時刻) 。1バイトも更新時刻も変わっていないことを見る。"""
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir() if p.is_file()}


def listed(out):
    """標準出力の `+` の行を、セクションごとのファイル名の集合にする。"""
    names: dict[str, set[str]] = {"themes": set(), "authors": set(), "publishers": set()}
    section = None
    for line in out.splitlines():
        if line.startswith("テーマノート"):
            section = "themes"
        elif line.startswith("著者ノート"):
            section = "authors"
        elif line.startswith("出版社ノート"):
            section = "publishers"
        elif line.startswith("  + "):
            names[section].add(line[len("  + "):].split("（")[0])
    return names


class TestDatabase:
    def test_DBが無ければ空のDBを作らずに終了コード1になる(self, tmp_path, reports, run, db_path):
        result = run()

        assert result.code == 1
        assert "DB が見つかりません" in result.err
        assert not db_path.exists()
        assert sorted(p.name for p in tmp_path.iterdir()) == ["reports"]

    def test_SQLiteでないファイルを渡すと終了コード1になる(self, reports, themes, run, db_path):
        db_path.write_text("これはSQLiteのファイルではない" * 20, encoding="utf-8")
        before = db_path.read_bytes()

        result = run("--apply")

        assert result.code == 1
        assert "DB を読めません" in result.err
        assert db_path.read_bytes() == before
        assert not themes.exists()

    def test_空白や井桁や疑問符を含むパスのDBも読めて途中までの名前のファイルを作らない(
            self, tmp_path, reports, capsys):
        # URL 文字列で開くと、パスの `?` `#` で URL が切れて mode=ro が効かず、`a b` という空の DB を作る
        folder = tmp_path / "a b#c?d%e日本語"
        special = folder / "r.db"
        make_db(special, [book("地政学入門", author="曽村保信", tags=["地政学"])])
        before = sorted(p.name for p in tmp_path.iterdir())

        code = create_notes.main(["--db", str(special)])

        assert code == 0
        assert "本 1 冊・タグ 1 個・著者 1 人" in capsys.readouterr().out
        assert sorted(p.name for p in tmp_path.iterdir()) == before

    def test_applyしてもDBファイルの中身と更新時刻は変わらない(self, reports, run, db_path):
        make_db(db_path, [book("地政学入門", author="曽村保信", tags=["地政学"])])
        before = (db_path.read_bytes(), db_path.stat().st_mtime_ns)

        result = run("--apply")

        assert result.code == 0
        assert (db_path.read_bytes(), db_path.stat().st_mtime_ns) == before

    def test_読み取り専用で開いたDBには書き込めない(self, db_path):
        make_db(db_path, [book("地政学入門", tags=["地政学"])])
        before = db_path.read_bytes()
        engine = create_notes.open_readonly(db_path)

        with pytest.raises(OperationalError, match="readonly"):
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO tags (name) VALUES ('追加')"))

        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM tags")).scalar() == 1
        engine.dispose()
        assert db_path.read_bytes() == before

    @pytest.mark.parametrize("update", [
        "UPDATE books SET status = 'xxx'",              # enum に無い値（LookupError）
        "UPDATE books SET finished_on = '2026-13-45'",  # 日付でない値（ValueError）
    ])
    def test_列の値が不正なDBはトレースバックを出さず1行のメッセージで終了コード1になる(
            self, reports, themes, run, db_path, update):
        make_db(db_path, [book("地政学入門", author="曽村保信", tags=["地政学"])])
        connection = sqlite3.connect(str(db_path))
        connection.execute(update)
        connection.commit()
        connection.close()

        result = run("--apply")

        assert result.code == 1
        assert result.err.startswith(f"DB を読めません: {db_path}: ")
        assert len(result.err.strip().splitlines()) == 1
        assert not themes.exists()

    def test_DBのパスのチルダはホームに展開して読む(self, tmp_path, monkeypatch, reports, capsys):
        home = tmp_path / "home"
        make_db(home / "r.db", [book("地政学入門", author="曽村保信", tags=["地政学"])])
        monkeypatch.setenv("HOME", str(home))

        code = create_notes.main(["--db", "~/r.db"])

        assert code == 0
        assert "本 1 冊・タグ 1 個・著者 1 人" in capsys.readouterr().out

    def test_ノートの置き場所が無ければ何も作らずに終了コード1になる(self, tmp_path, monkeypatch, run, db_path):
        make_db(db_path, [book("地政学入門", author="曽村保信", tags=["地政学"])])
        missing = tmp_path / "無い"
        monkeypatch.setenv("NOTES_REPORTS_DIR", str(missing))

        result = run("--apply")

        assert result.code == 1
        assert "見つかりません" in result.err
        assert not missing.exists()


class TestPreview:
    def test_下見は何も書かず作るファイルと作らない理由を表示する(self, reports, themes, authors, run, db_path):
        make_db(db_path, [book("地政学入門", author="曽村保信", tags=["地政学", "..."])])
        before = sorted(p.name for p in reports.iterdir())

        result = run()

        assert result.code == 0
        assert "  + 地政学.md" in result.out
        assert "  + 曽村保信.md" in result.out
        assert "作る 1 / 既にノートあり 0 / 作らない 1" in result.out
        assert "下見のみ。--apply を付けると 2 件を作る" in result.out
        assert "  ! ...: ファイル名にできる文字が無い" in result.err
        assert not themes.exists() and not authors.exists()
        assert sorted(p.name for p in reports.iterdir()) == before

    def test_下見で表示したファイルとapplyで作るファイルが同じ(self, reports, themes, authors, run, db_path):
        make_db(db_path, [
            book("言語の起源", author="ダニエル・Ｌ・エヴェレット, 松浦俊輔", tags=["言語学"]),
            book("何か", author="山田太郎 (著, 編集)", tags=["歴史/日本", "C#"], report=True),
        ])

        preview = run()
        run("--apply")

        shown = listed(preview.out)
        assert shown["themes"] == names_in(themes) == {"C.md", "言語学.md", "歴史日本.md"}
        assert shown["authors"] == names_in(authors)
        assert len(shown["authors"]) == 3


class TestThemeNotes:
    def test_本に付いているタグごとにテーマノートを作る(self, themes, run, db_path):
        make_db(db_path, [
            book("地政学入門", tags=["地政学", "歴史"]),
            book("世界史", tags=["歴史"]),
        ])

        result = run("--apply")

        assert result.code == 0
        assert names_in(themes) == {"地政学.md", "歴史.md"}
        assert meta_of(themes / "歴史.md")["type"] == "theme-note"
        assert "作った 2 / 作れなかった 0" in result.out

    def test_どの本にも付いていないタグのノートは作らない(self, themes, run, db_path):
        make_db(db_path, [book("地政学入門", tags=["地政学"])], unused_tags=["使っていない"])

        run("--apply")

        assert names_in(themes) == {"地政学.md"}

    def test_ファイル名とタグが一致するノートにはtagsを書かない(self, themes, run, db_path):
        make_db(db_path, [book("地政学入門", tags=["地政学"])])

        run("--apply")

        assert meta_of(themes / "地政学.md") == {"type": "theme-note"}
        assert read(themes / "地政学.md").startswith("---\ntype: theme-note\n---\n\n# 地政学\n")

    @pytest.mark.parametrize("tag, filename", [
        ("日本史/近代", "日本史近代.md"),
        ("C#", "C.md"),
        ("地政​学", "地政学.md"),
    ])
    def test_ファイル名に使えない文字や見えない文字を含むタグはtagsにタグ名を書く(
            self, themes, run, db_path, tag, filename):
        make_db(db_path, [book("本", tags=[tag])])

        result = run("--apply")

        assert names_in(themes) == {filename}
        assert meta_of(themes / filename)["tags"] == [tag]
        assert f"  + {filename}（tags: {tag}）" in result.out

    def test_全角や半角カナのタグはNFKCをかけずタグのままのファイル名にする(self, themes, run, db_path):
        make_db(db_path, [book("本", tags=["ＳＦ", "ｶﾞｲﾄﾞ"])])

        run("--apply")

        assert names_in(themes) == {"ＳＦ.md", "ｶﾞｲﾄﾞ.md"}
        assert "tags" not in meta_of(themes / "ＳＦ.md")
        assert "tags" not in meta_of(themes / "ｶﾞｲﾄﾞ.md")

    def test_作ったテーマノートはアプリが読むとそのタグの本を集める(self, themes, run, db_path):
        tags = ["地政学", "日本史/近代", "C#", "ＳＦ", "📚"]
        make_db(db_path, [book(f"{tag}の本", tags=[tag]) for tag in tags])

        run("--apply")

        # 次の回の scan_notes が読む集めるタグ（ファイル名か tags）が、どれもタグ1つとぴったり一致する
        collected = sorted(note.tags for note in theme_store.scan_notes(themes))
        assert collected == sorted((tag,) for tag in tags)

    def test_既存のテーマノートがファイル名かtagsで集めているタグは作らない(self, themes, run, db_path):
        make_db(db_path, [book("本1", tags=["日本史", "世界史", "地政学", "経済"])])
        write_note(themes, "歴史.md", "---\ntags: [日本史, 世界史]\n---\n")
        write_note(themes, "地政学.md", "# 地政学\n")
        before = snapshot(themes)

        result = run("--apply")

        assert result.code == 0
        assert names_in(themes) == {"歴史.md", "地政学.md", "経済.md"}
        after = snapshot(themes)
        assert all(after[name] == state for name, state in before.items())
        assert "作った 1 / 作れなかった 0 / 既にノートあり 3 / 作らない 0" in result.out

    @pytest.mark.parametrize("tag, reason", [
        ("#メモ", "ノートに書くと集めるタグが「メモ」になり、このタグと一致しない"),
        (" 歴史", "ノートに書くと集めるタグが「歴史」になり、このタグと一致しない"),
        ("テーマ一覧", "ファイル名がハブ（テーマ一覧.md）と同じになる"),
        ("...", "ファイル名にできる文字が無い"),
    ])
    def test_集められないタグやファイル名にできないタグは作らずに理由を出す(
            self, themes, run, db_path, tag, reason):
        make_db(db_path, [book("本", tags=[tag])])

        result = run("--apply")

        # 作らない理由が恒久的なものなので、終了コードは 0
        assert result.code == 0
        assert f"  ! {tag}: {reason}" in result.err
        assert not themes.exists()

    def test_同じファイル名になる2つのタグはタグと同じ名前のほうを作り他方は理由を出す(
            self, themes, run, db_path):
        # C# を先に登録しても、C.md は C のもの
        make_db(db_path, [book("本1", tags=["C#"]), book("本2", tags=["C"])])

        result = run("--apply")

        assert names_in(themes) == {"C.md"}
        assert "tags" not in meta_of(themes / "C.md")
        assert "  ! C#: C.md はこの回に「C」のノートとして作る" in result.err

    def test_同じ名前の既存ノートが別のタグを集めているときは作らずtagsに足すよう案内する(
            self, themes, run, db_path):
        make_db(db_path, [book("本", tags=["C", "C#"])])
        write_note(themes, "C.md", "# C\n")

        result = run("--apply")

        assert names_in(themes) == {"C.md"}
        assert "  ! C#: C.md が既にあり、このタグを集めていない（そのノートの frontmatter の tags に足すと集める）" \
            in result.err

    def test_テーマノートには最初から本の一覧と関連するテーマが入っている(self, themes, run, db_path):
        make_db(db_path, [
            book("地政学入門", author="曽村保信", tags=["地政学", "歴史"],
                 status=BookStatus.FINISHED, report=True),
            book("世界史", tags=["歴史"]),
        ])

        run("--apply")

        geopolitics = read(themes / "地政学.md")
        assert geopolitics.count(START) == 1 and geopolitics.count(END) == 1
        assert "1冊（レポートあり 1冊）" in geopolitics
        assert "- [地政学入門](../0001-地政学入門.md) — 曽村保信 · 読了 2026-09-20" in geopolitics
        # 同じ回に作る歴史のノートも「関連するテーマ」に出る
        assert "- [歴史](歴史.md) — 共通の本 1冊" in geopolitics
        history = read(themes / "歴史.md")
        assert "2冊（レポートあり 1冊）" in history
        assert "- 世界史 — 積読" in history
        assert "- [地政学](地政学.md) — 共通の本 1冊" in history

    @pytest.mark.parametrize("content, age, reason", [
        (b"", 60, "空のファイル"),
        ("---\ntags: [地政学, 日本史\n---\n\n# 歴史\n".encode(), 60, "frontmatter を解釈できない"),
        (b"---\ntags: [H\xff]\n---\n", 60, "読めない（UnicodeDecodeError）"),
        ("# 歴史\n".encode(), 0, "直近に更新された"),
    ])
    def test_編集中や壊れたテーマノートがあればテーマノートを作らず終了コード1になり著者ノートは作る(
            self, themes, authors, run, db_path, content, age, reason):
        # 歴史.md は複数のタグをまとめるノートを書いている途中かもしれない。集めるタグを読み違えて、
        # 同じタグのノートを重ねて作らない
        make_db(db_path, [book("地政学入門", author="曽村保信", tags=["地政学"])])
        write_note(themes, "歴史.md", content, age=age)

        result = run("--apply")

        assert result.code == 1
        assert f"  ! テーマノートを作らない: 歴史.md: {reason}" in result.err
        assert "待ち（このセクションは作らない）" in result.out
        assert names_in(themes) == {"歴史.md"}
        assert names_in(authors) == {"曽村保信.md"}


    @pytest.mark.parametrize("tag, reason", [
        # 読み戻すと内容が変わる。アプリが毎回書き直す
        ("a\rb", "一覧に CR の文字が入り、書いた内容が読み戻すと変わる"),
        # 読み戻すと CR で行が分かれ、END が増えてマーカーが壊れる。アプリは以後そのノートを更新しない
        ("-->\r<!-- notes:books:end -->\ry", "一覧を書くとマーカーを読み戻せない"),
    ])
    def test_CRを含むタグは作らずにエスケープした形で理由を出し他のノートは作る(
            self, themes, authors, run, db_path, tag, reason):
        make_db(db_path, [book("本", author="曽村保信", tags=[tag, "地政学"])])

        result = run("--apply")

        # 理由は恒久的なものなので終了コードは 0
        assert result.code == 0
        assert names_in(themes) == {"地政学.md"}
        assert f"  ! {tag.encode('unicode_escape').decode()}: {reason}" in result.err
        assert "\r" not in result.err

    def test_制御文字を含むタグは端末にそのまま出さずエスケープして表示する(self, themes, run, db_path):
        # ESC は端末の制御列になり、改行・CR は行を崩す
        make_db(db_path, [book("本", tags=["\x1b[31m赤", "\x1b\u2028"])])

        result = run("--apply")

        assert names_in(themes) == {"31m赤.md"}
        assert "\x1b" not in result.out and "\x1b" not in result.err
        assert "\u2028" not in result.err
        assert "  + 31m赤.md（tags: \\x1b[31m赤）" in result.out
        assert "  ! \\x1b\\u2028: ファイル名にできる文字が無い" in result.err

    def test_frontmatterが空のテーマノートがあれば待ち_直し方を案内する(self, themes, authors, run, db_path):
        # Obsidian のプロパティを全部消すとできる、閉じた空の frontmatter。1時間前に保存したノートでも待つ
        make_db(db_path, [book("地政学入門", author="曽村保信", tags=["地政学"])])
        write_note(themes, "歴史.md", "---\n---\n自分のメモ\n", age=3600)

        result = run("--apply")

        assert result.code == 1
        assert "  ! テーマノートを作らない: 歴史.md: frontmatter を解釈できない" in result.err
        assert "frontmatter ごと消す" in result.err
        assert names_in(themes) == {"歴史.md"}
        assert names_in(authors) == {"曽村保信.md"}


class TestAuthorNotes:
    def test_レポートの無い著者や積読の本の著者のノートも作る(self, authors, run, db_path):
        make_db(db_path, [
            book("お経の話", author="渡辺照宏", status=BookStatus.FINISHED, report=True),
            book("言語の起源", author="松浦俊輔", status=BookStatus.READING),
            book("積読の本", author="鈴木花子", status=BookStatus.UNREAD),
            book("読んだ本", author="田中一郎", status=BookStatus.FINISHED),
            book("著者欄が空の本", author=None),
        ])

        result = run("--apply")

        assert result.code == 0
        assert names_in(authors) == {"松浦俊輔.md", "渡辺照宏.md", "田中一郎.md", "鈴木花子.md"}
        # 積読の本だけの著者のノートは、「まだレポートの無い本」の節だけ
        text = read(authors / "鈴木花子.md")
        assert "- 積読の本 — 鈴木花子 · 積読" in text
        assert "### レポートのある本" not in text

    def test_共著者と訳者もそれぞれノートを作る(self, authors, run, db_path):
        make_db(db_path, [
            book("言語の起源", author="ダニエル・Ｌ・エヴェレット, 松浦俊輔"),
            book("マインドフルネスストレス低減法", author="J．カバットジン／著, 春木豊／訳"),
        ])

        run("--apply")

        assert names_in(authors) == {
            "ダニエル・L・エヴェレット.md", "松浦俊輔.md", "J.カバットジン.md", "春木豊.md"}

    def test_出版社の名前の著者ノートは作らない(self, authors, run, db_path):
        make_db(db_path, [
            book("決定版 図説 旧約・新約聖書", author="学研プラス", publisher="学研プラス"),
            book("野草・山菜・きのこ図鑑", author="茸本朗, HS", publisher="HS"),
        ])

        result = run("--apply")

        assert result.code == 0
        assert names_in(authors) == {"茸本朗.md"}
        assert "著者 1 人" in result.out

    def test_旧い規則の中黒入りのノートが集めている著者は作らない(self, authors, run, db_path):
        make_db(db_path, [book("ピダハン", author="ダニエル・Ｌ・エヴェレット")])
        write_note(authors, "ダニエル・L・エヴェレット.md",
                   "---\ntype: author-note\n---\n\n# ダニエル・L・エヴェレット\n")
        before = snapshot(authors)

        result = run("--apply")

        assert result.code == 0
        assert "既にノートあり 1" in result.out and "作った 0" in result.out
        assert snapshot(authors) == before

    @pytest.mark.parametrize("old_name, first, second, already", [
        # 旧い規則では1人の著者だった表記揺れ。0006 でも（カタカナ名の `・` は分けないので）キーが同じ1人
        ("ジャレド ダイアモンド", "ジャレド ダイアモンド", "ジャレド・ダイアモンド", 1),
        ("J.K.ローリング", "J.K.ローリング", "J・K・ローリング", 1),
    ])
    def test_旧い規則で同じ人だった表記揺れの著者は旧いノートが集めているので作らない(
            self, authors, run, db_path, old_name, first, second, already):
        make_db(db_path, [book("先の本", author=first), book("後の本", author=second)])
        write_note(authors, f"{old_name}.md", f"---\ntype: author-note\n---\n\n# {old_name}\n")
        before = snapshot(authors)

        preview = run()
        applied = run("--apply")

        assert preview.code == applied.code == 0
        assert f"作る 0 / 既にノートあり {already} / 作らない 0" in preview.out
        assert f"作った 0 / 作れなかった 0 / 既にノートあり {already} / 作らない 0" in applied.out
        assert snapshot(authors) == before

    def test_空白でつないだ旧いノートが集めている共著者は作らない(self, authors, run, db_path):
        # 旧い規則ではまとまり全体が1人。そのノートはまとまりのキーで2人の本を集める
        make_db(db_path, [book("二人の本", author="熊野純彦・大澤真幸")])
        write_note(authors, "熊野純彦 大澤真幸.md", "---\ntype: author-note\n---\n\n# 熊野純彦 大澤真幸\n")
        before = snapshot(authors)

        result = run("--apply")

        assert result.code == 0
        assert "既にノートあり 2" in result.out and "作った 0" in result.out
        assert snapshot(authors) == before

    def test_aliasesで集められている著者のノートは作らない(self, authors, run, db_path):
        make_db(db_path, [book("世界文化小史", author="Ｈ・Ｇ・ウェルズ")])
        write_note(authors, "Wells.md", "---\naliases: [H・G・ウェルズ]\n---\n\n# Wells\n")
        before = snapshot(authors)

        result = run("--apply")

        assert result.code == 0
        assert snapshot(authors) == before
        assert "既にノートあり 1" in result.out

    def test_ファイル名にすると名前が変わる著者はaliasesに元の名前を入れる(self, authors, run, db_path):
        make_db(db_path, [book("明治維新", author="山田*太郎")])

        result = run("--apply")

        assert names_in(authors) == {"山田太郎.md"}
        assert meta_of(authors / "山田太郎.md")["aliases"] == ["山田*太郎"]
        assert "  + 山田太郎.md（aliases: 山田*太郎）" in result.out

    def test_作った著者ノートはアプリが読むとその著者を集める(self, authors, run, db_path):
        make_db(db_path, [
            book("言語の起源", author="ダニエル・Ｌ・エヴェレット, 松浦俊輔"),
            book("明治維新", author="山田*太郎／著, 鈴木花子 訳"),
        ])

        run("--apply")

        books = create_notes._read_books(db_path)
        wanted = set(author_store.collect_authors(books))
        collected = set().union(*(note.keys for note in author_store.scan_notes(authors).notes))
        assert wanted <= collected
        assert len(names_in(authors)) == len(wanted)   # 著者1人につきノート1つ

    @pytest.mark.parametrize("names, files, reason", [
        (["★★★"], set(), "★★★: ファイル名にできる文字が無い"),
        (["著者一覧"], set(), "著者一覧: ファイル名がハブ（著者一覧.md）と同じになる"),
        (["山田*太郎", "山田太郎"], {"山田太郎.md"},
         "山田*太郎: ファイル名にすると他の著者か既存のノートの名前と見分けがつかない"),
    ])
    def test_作れない著者は作らずに理由を出す(self, authors, run, db_path, names, files, reason):
        make_db(db_path, [book(f"{name}の本", author=name) for name in names])

        result = run("--apply")

        assert result.code == 0
        assert f"  ! {reason}" in result.err
        assert names_in(authors) == files

    def test_編集中の著者ノートがあれば著者ノートを作らず終了コード1になりテーマノートは作る(
            self, themes, authors, run, db_path):
        make_db(db_path, [book("世界文化小史", author="Ｈ・Ｇ・ウェルズ", tags=["地政学"]),
                          book("お経の話", author="渡辺照宏")])
        write_note(authors, "ウェルズ.md", "# ウェルズ\n", age=0)   # Obsidian で保存したばかり

        result = run("--apply")

        assert result.code == 1
        assert "  ! 著者ノートを作らない: ウェルズ.md: 直近に更新された" in result.err
        assert names_in(authors) == {"ウェルズ.md"}
        assert names_in(themes) == {"地政学.md"}

    def test_著者ノートの関連するテーマに同じ回に作ったテーマノートが出る(self, themes, authors, run, db_path):
        make_db(db_path, [book("地政学入門", author="曽村保信", tags=["地政学"])])

        run("--apply")

        assert "- [地政学](../themes/地政学.md) — 共通の本 1冊" in read(authors / "曽村保信.md")


class TestPublisherNotes:
    def test_全部の出版社のノートをレポートの有無に関係なく作る(self, publishers, authors, run, db_path):
        make_db(db_path, [book("旧約聖書", publisher="学研プラス"),
                          book("野草図鑑", author="茸本朗", publisher="ハーベスト", report=True)])

        result = run("--apply")

        assert result.code == 0
        assert names_in(publishers) == {"学研プラス.md", "ハーベスト.md"}
        assert meta_of(publishers / "ハーベスト.md")["type"] == "publisher-note"
        assert "出版社 2 社" in result.out
        # 出版社の名前は著者のノートにならない
        assert names_in(authors) == {"茸本朗.md"}

    def test_下見は出版社ノートも何も書かず表示する(self, publishers, run, db_path):
        make_db(db_path, [book("野草図鑑", author="茸本朗・ハーベスト")])

        result = run()

        assert listed(result.out)["publishers"] == {"ハーベスト.md"}
        assert not publishers.exists()

    def test_既存の出版社ノートがaliasesで集めている出版社は作らない(self, publishers, run, db_path):
        make_db(db_path, [book("本1", publisher="学研プラス"), book("本2", publisher="株式会社学研プラス")])
        write_note(publishers, "学研プラス.md", "---\naliases: [株式会社学研プラス]\n---\n")
        before = snapshot(publishers)

        result = run("--apply")

        assert result.code == 0
        assert snapshot(publishers) == before
        assert "作った 0 / 作れなかった 0 / 既にノートあり 2 / 作らない 0" in result.out

    def test_編集中の出版社ノートがあれば出版社ノートを作らず終了コード1になり著者ノートは作る(
            self, publishers, authors, run, db_path):
        make_db(db_path, [book("野草図鑑", author="茸本朗", publisher="ハーベスト"),
                          book("旧約聖書", publisher="学研プラス")])
        write_note(publishers, "学研プラス.md", "# 学研プラス\n", age=0)   # Obsidian で保存したばかり

        result = run("--apply")

        assert result.code == 1
        assert "  ! 出版社ノートを作らない: 学研プラス.md: 直近に更新された" in result.err
        assert names_in(publishers) == {"学研プラス.md"}
        assert names_in(authors) == {"茸本朗.md"}


class TestExistingFilesAndRepeatedRuns:
    def test_既存のノートとハブは1バイトも変えず更新時刻も変えない(self, themes, authors, run, db_path):
        make_db(db_path, [
            book("地政学入門", author="曽村保信", tags=["地政学", "歴史"]),
            book("お経の話", author="渡辺照宏", tags=["歴史"]),
        ])
        stale = f"# 歴史\n\n自分のまとめ。\n\n{START}\n古い一覧\n{END}\n"
        write_note(themes, "歴史.md", stale)
        write_note(themes, THEME_HUB, f"# テーマ一覧\n\n{START}\n古い一覧\n{END}\n")
        write_note(authors, "渡辺照宏.md", f"# 渡辺照宏\n\n{START}\n古い一覧\n{END}\n")
        write_note(authors, AUTHOR_HUB, f"# 著者一覧\n\n{START}\n古い一覧\n{END}\n")
        before = {"themes": snapshot(themes), "authors": snapshot(authors)}

        result = run("--apply")

        assert result.code == 0
        assert names_in(themes) == {"地政学.md", "歴史.md"}
        assert names_in(authors) == {"曽村保信.md", "渡辺照宏.md"}
        for key, directory in (("themes", themes), ("authors", authors)):
            after = snapshot(directory)
            for name, state in before[key].items():
                assert after[name] == state, f"{key}/{name} が変わった"

    def test_ハブが無くてもハブは作らない(self, themes, authors, run, db_path):
        make_db(db_path, [book("地政学入門", author="曽村保信", tags=["地政学"])])

        run("--apply")

        assert not (themes / THEME_HUB).exists()
        assert not (authors / AUTHOR_HUB).exists()

    def test_作ったノートの一覧はアプリが次の回に作る一覧と同じなので書き直されない(
            self, themes, authors, run, db_path):
        make_db(db_path, [
            book("地政学入門", author="曽村保信", tags=["地政学", "歴史"], report=True),
            book("世界史", author="松浦俊輔, 渡辺照宏", tags=["歴史"]),
        ])
        run("--apply")
        before = {"themes": snapshot(themes), "authors": snapshot(authors)}
        engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(str(db_path)))

        with Session(engine) as db:
            written = theme_store.rebuild(db, quiet_seconds=0) + author_store.rebuild(db, quiet_seconds=0)
        engine.dispose()

        # 書かれるのは、ハブ（スクリプトが作らない）だけ
        assert sorted(p.name for p in written) == sorted([THEME_HUB, AUTHOR_HUB])
        for key, directory in (("themes", themes), ("authors", authors)):
            after = snapshot(directory)
            for name, state in before[key].items():
                assert after[name] == state, f"{key}/{name} が書き直された"

    def test_記号や改行を含むタグや書名や著者名でも作ったノートのマーカーは読め_アプリは書き直さない(
            self, themes, authors, run, db_path):
        # 作ったノートが、次の回にアプリが書き直し続けたり、マーカーが壊れて更新が止まったりしない
        make_db(db_path, [
            book("*強調*の本\n~~~", author="著者A\n```", tags=["a\nb", "x-->y", "<!-- z", "`~~~`", "C#"]),
            book("<!-- notes:books:end --> の本", author="<!-- notes:books:start -->", tags=["x-->y"]),
        ])
        assert run("--apply").code == 0
        created = [path for directory in (themes, authors) for path in directory.iterdir()]
        assert len(created) >= 5
        engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(str(db_path)))

        with Session(engine) as db:
            later = time.time() + 3600      # 作ったノートの静穏時間を過ぎた後
            theme_store.rebuild(db, now=later)      # 1回目はハブを作る
            author_store.rebuild(db, now=later)
            written = theme_store.rebuild(db, now=later) + author_store.rebuild(db, now=later)
        engine.dispose()

        assert all(theme_store._has_one_pair(read(path)) for path in created)
        assert written == []

    @pytest.mark.parametrize("store, planner, directory_name, filename", [
        (theme_store, "plan_new_notes", "themes", "地政学.md"),
        (author_store, "plan_new_notes", "authors", "曽村保信.md"),
    ])
    def test_計画のあとに同じ名前のファイルができていたら上書きせず終了コード1になる(
            self, reports, run, db_path, monkeypatch, store, planner, directory_name, filename):
        make_db(db_path, [book("地政学入門", author="曽村保信", tags=["地政学"])])
        original = getattr(store, planner)

        def plan_then_user_creates_the_note(*args, **kwargs):
            plan = original(*args, **kwargs)
            # 計画を立てたあと、ロックを取るまでの間に Obsidian で同じ名前のノートを作った
            write_note(reports / directory_name, filename, "ユーザーが書いた本文\n")
            return plan

        monkeypatch.setattr(store, planner, plan_then_user_creates_the_note)

        result = run("--apply")

        assert result.code == 1
        assert read(reports / directory_name / filename) == "ユーザーが書いた本文\n"
        assert f"  ! {filename}: 作れなかった" in result.err
        assert "作れなかった 1" in result.out

    def test_2回目は何も作らず終了コード0になる(self, themes, authors, run, db_path):
        make_db(db_path, [
            book("言語の起源", author="ダニエル・Ｌ・エヴェレット, 松浦俊輔", tags=["言語学"]),
            book("何か", author="山田太郎 (著, 編集)", tags=["歴史/日本", "C#"]),
        ])
        assert run("--apply").code == 0
        backdate(themes, authors)
        created = {"themes": snapshot(themes), "authors": snapshot(authors)}

        again = run()
        apply_again = run("--apply")

        assert again.code == 0 and apply_again.code == 0
        assert again.out.count("作る 0 / 既にノートあり") == 3   # テーマ・著者・出版社
        assert "作った 0 / 作れなかった 0" in apply_again.out
        assert {"themes": snapshot(themes), "authors": snapshot(authors)} == created

    def test_作った直後にもう一度流すと直近に更新されたノートがあるので待って終了コード1になる(
            self, themes, authors, run, db_path):
        make_db(db_path, [book("地政学入門", author="曽村保信", tags=["地政学"])])
        assert run("--apply").code == 0

        again = run("--apply")

        assert again.code == 1
        assert "テーマノートを作らない: 地政学.md: 直近に更新された" in again.err
        assert "20秒ほどおいてもう一度流す" in again.err
        assert "著者ノートを作らない: 曽村保信.md: 直近に更新された" in again.err
        assert again.out.count("待ち（このセクションは作らない）") == 2


class TestUnreadableFolders:
    """ノートのフォルダを読めない・作れないときは、トレースバックを出さずに理由を出して終了コード1にする。"""

    def test_テーマのフォルダを読めなければ理由を出し著者ノートは作って終了コード1になる(
            self, themes, authors, run, db_path):
        make_db(db_path, [book("地政学入門", author="曽村保信", tags=["地政学"])])
        themes.write_text("フォルダのはずが普通のファイル", encoding="utf-8")

        result = run("--apply")

        assert result.code == 1
        assert f"  ! {themes} を読めません: " in result.err
        assert themes.read_text(encoding="utf-8") == "フォルダのはずが普通のファイル"
        assert names_in(authors) == {"曽村保信.md"}

    def test_著者のフォルダを読めなければ理由を出しテーマノートは作って終了コード1になる(
            self, themes, authors, run, db_path):
        make_db(db_path, [book("地政学入門", author="曽村保信", tags=["地政学"])])
        authors.write_text("フォルダのはずが普通のファイル", encoding="utf-8")

        result = run("--apply")

        assert result.code == 1
        assert f"  ! {authors} を読めません: " in result.err
        assert authors.read_text(encoding="utf-8") == "フォルダのはずが普通のファイル"
        assert names_in(themes) == {"地政学.md"}

    def test_フォルダを作れなければ作れなかったと出し他方は作って終了コード1になる(
            self, themes, authors, run, db_path):
        make_db(db_path, [book("地政学入門", author="曽村保信", tags=["地政学"])])
        os.symlink("存在しない", themes)     # 行き先の無い symlink。mkdir は作れない

        result = run("--apply")

        assert result.code == 1
        assert f"  ! {themes} を作れません: " in result.err
        assert "  ! 地政学.md: 作れなかった" in result.err
        assert "作った 0 / 作れなかった 1 / 既にノートあり 0 / 作らない 0" in result.out
        assert names_in(authors) == {"曽村保信.md"}


class TestNonUtf8Names:
    def test_UTF8でない名前のノートがあっても下見と適用の結果が同じで落ちず一時ファイルも残さない(
            self, themes, authors, run, db_path):
        # 文字コードの違う zip の展開などで紛れる名前。UTF-8 で書けない文字が一覧のリンクに入ると、
        # 書くときに UnicodeEncodeError で落ちる
        make_db(db_path, [
            book("本1", author="曽村保信", tags=["T", "U"]),
            book("本2", author="渡辺照宏", tags=["V"]),
        ])
        themes.mkdir()
        bad = os.path.join(os.fsencode(themes), b"caf\xe9.md")
        try:
            with open(bad, "wb") as handle:
                handle.write("---\ntags: [T]\n---\n".encode())
        except OSError:
            pytest.skip("このファイルシステムは UTF-8 でない名前のファイルを作れない")
        old = time.time() - 60
        os.utime(bad, (old, old))

        preview = run()
        applied = run("--apply")

        assert preview.code == applied.code == 0
        assert listed(preview.out) == listed(applied.out) == {"themes": {"V.md"}, "authors": {"渡辺照宏.md"},
                                                       "publishers": set()}
        assert "Traceback" not in applied.err
        # T を集めるノートを「関連するテーマ」に出す U と曽村保信は、理由つきで作らない
        assert "  ! U: 一覧に UTF-8 にできない文字が入る" in applied.err
        assert "  ! 曽村保信: 一覧に UTF-8 にできない文字が入る" in applied.err
        assert names_in(themes) == {"V.md", os.fsdecode(b"caf\xe9.md")}   # 作ったのは V.md だけ
        assert not [name for name in os.listdir(os.fsencode(themes)) if name.endswith(b".tmp")]
