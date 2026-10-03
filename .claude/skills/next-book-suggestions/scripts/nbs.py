#!/usr/bin/env python3
"""「次に読む本」の候補を作るための道具（標準ライブラリだけで動く）。

  targets  候補が足りない本を数え、エージェントに渡すバッチと除外リストを書き出す
  verify   エージェントが出した候補を ISBN で照合し、流し込める形にする
  apply    照合済みの候補を PUT /api/books/{id}/suggestions で流し込む

リポジトリの直下で、API を起動した状態（./run.sh）で使う。
3つとも同じ作業ディレクトリ（--dir）を使う。
"""
import argparse
import json
import re
import sqlite3
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_API = "http://127.0.0.1:8765"
DEFAULT_DB = "backend/reading.db"
DISTANCES = ("near", "far")


# ---------------------------------------------------------------- HTTP

def _request(method: str, url: str, body=None, timeout: float = 30.0):
    """(ステータス, JSON) を返す。4xx/5xx も例外にせず返す"""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read()
            return res.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, raw.decode(errors="replace")


def _get(api: str, path: str, **params):
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    return _request("GET", f"{api}{path}{query}")


def _existing(api: str, book_id: int) -> list[dict]:
    """いま設定してある候補（「興味なし」にした本は API が外して返す）。

    GET は3冊ずつのページングなので、最後まで読む。
    """
    rows, page = [], 0
    while True:
        status, body = _get(api, f"/api/books/{book_id}/suggestions",
                            basis="note,rating,tag", distance="both", page=page)
        if status != 200:
            raise RuntimeError(f"#{book_id} の候補を読めませんでした（{status}）")
        rows.extend(body["suggestions"])
        if not body["has_more"]:
            return rows
        page += 1


# ---------------------------------------------------------------- 照合

# 書名の比較で無視する記号。副題の区切りもここで消える
_PUNCT = re.compile(
    r"[\s・:：;；,，、。.．!！?？「」『』\[\]［］【】〈〉<>《》\"'“”‘’"
    r"\-‐‑–—―─~〜～=＝/／+＋&＆#＃]"
)
# 「（講談社現代新書）」「[第三版]」「〔完全版〕」のような括弧書きは書名の一部ではないので落とす
_PAREN = re.compile(r"[（(][^（()）]*[)）]|[\[［][^\[\]［］]*[\]］]|〔[^〔〕]*〕")
# 副題の区切り。ここより前を本題とみなす。
# 空白1つは区切りにしない（「物語 ウィーンの歴史」と「物語 イギリスの歴史」が同じ本になる）
# 「=」は並列書名（「アースダイバー = Earth Diver」）の区切り
_SUBTITLE = re.compile(r"\s[:：―—\-–〜~=＝]\s?|[:：―—〜]|――|\s\s")
# 版・巻の表記。「仏教 第2版」「銃・病原菌・鉄 上巻」も同じ本として扱う
# （上下巻の本は上巻を候補にする約束なので、巻の違いは照合で問わない）
_EDITION_HEAD = re.compile(r"^(新版|増補改訂版|増補改訂|増補版|改訂版|新装版|決定版|完全版)")
_EDITION_TAIL = re.compile(
    r"(第?[\d一二三四五六七八九十]+版|新版|増補改訂版|増補版|改訂版|新装版|完全版|[上中下]巻?|第?\d+巻)$"
)


# 異体字。書誌とエージェントで書き方が割れる（柳澤/柳沢、下條/下条、日髙/日高）
_ITAIJI = str.maketrans({
    "澤": "沢", "條": "条", "髙": "高", "邊": "辺", "邉": "辺", "齋": "斉", "齊": "斉",
    "﨑": "崎", "嵜": "崎", "濱": "浜", "廣": "広", "國": "国", "櫻": "桜", "藝": "芸",
    "瀧": "滝", "德": "徳", "惠": "恵", "眞": "真", "龍": "竜",
})
# 末尾の巻番号（「100のモノが語る世界の歴史 1」）。「1984」のような数字だけの書名は残す
_VOLUME_NUMBER = re.compile(r"(?<=\D{4})\d{1,2}$")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower().translate(_ITAIJI)
    text = _PUNCT.sub("", _PAREN.sub("", text))
    text = _EDITION_TAIL.sub("", _EDITION_HEAD.sub("", text))
    return _VOLUME_NUMBER.sub("", text)


def _main_title(text: str) -> str:
    text = unicodedata.normalize("NFKC", _PAREN.sub("", text or "")).strip()
    return _norm(_SUBTITLE.split(text, maxsplit=1)[0])


def titles_match(given: str, found: str) -> bool:
    """同じ本の書名とみなせるか。

    副題の有無や括弧書き・版・巻の違いは許す。ただし「ハプスブルク家」と
    「ハプスブルク家の歴史」のような**別の本**を取り違えないよう、
    本題どうしが一致するか、一方がもう一方の全体と一致するときだけ認める。
    """
    g_full, f_full = _norm(given), _norm(found)
    g_main, f_main = _main_title(given), _main_title(found)
    if not g_main or not f_main:
        return False
    if g_main == f_main or g_full == f_full:
        return True
    return g_full in (f_full, f_main) or f_full in (g_full, g_main)


def prefix_match(given: str, found: str) -> bool:
    """一方の書名が、もう一方の書名の頭と一致するか（副題の有無の違い）"""
    g, f = _norm(given), _norm(found)
    shorter, longer = sorted((g, f), key=len)
    return len(shorter) >= 4 and longer.startswith(shorter)


def _segments(text: str) -> list[str]:
    """書名を副題の区切りで分けたもの（正規化済み・4文字以上だけ）"""
    text = unicodedata.normalize("NFKC", _PAREN.sub("", text or ""))
    return [s for s in (_norm(part) for part in _SUBTITLE.split(text)) if len(s) >= 4]


def titles_overlap(given: str, found: str) -> bool:
    """書名の一部が重なるか。titles_match より緩い。

    書誌はシリーズ名や副題の位置がエージェントと違うことがある
    （「イラスト図解 スマート工場のしくみ」と「スマート工場のしくみ : イラスト図解」、
    「脳は美をどう感じるか アートの脳科学」と「脳は美をどう感じるか」）。
    別の本も拾いうるので、ISBN が引けているときの補助にだけ使う。
    """
    if prefix_match(given, found):
        return True
    g_full, f_full = _norm(given), _norm(found)
    return any(s in g_full for s in _segments(found)) or any(s in f_full for s in _segments(given))


_ROLE = re.compile(r"(著|訳|編|監修|監訳|作|文|絵|本文|著者|編著|共著)$")
_JAPANESE = re.compile(r"[぀-ヿ㐀-鿿]")


def _people(text: str | None) -> list[str]:
    parts = re.split(r"[,，、/／;；&＆]", unicodedata.normalize("NFKC", text or "").translate(_ITAIJI))
    names = []
    for part in parts:
        name = _ROLE.sub("", re.sub(r"[\s・=＝.]", "", part.strip())).lower()
        if name:
            names.append(name)
    return names


def _family_names(text: str | None) -> list[str]:
    """カナ表記の外国人名の姓（「ジョン・カバットジン」→「カバットジン」）"""
    parts = re.split(r"[,，、/／;；&＆]", unicodedata.normalize("NFKC", text or ""))
    names = []
    for part in parts:
        pieces = [p for p in re.split(r"[・=＝\s]", part.strip()) if p]
        if len(pieces) >= 2 and len(pieces[-1]) >= 3:
            names.append(pieces[-1].lower())
    return names


def authors_match(given: str | None, found: str | None) -> bool:
    """著者が一致するか（区切りや「著」「訳」の有無、名の略し方には甘め）"""
    found_names = _people(found)
    if any(g in f or f in g for g in _people(given) for f in found_names):
        return True
    # 「ジョン・カバットジン」と「J．カバットジン」のように名の書き方だけ違う
    return any(family in f for family in _family_names(given) for f in found_names)


def authors_comparable(given: str | None, found: str | None) -> bool:
    """比べられる表記どうしか。

    翻訳書は書誌がローマ字（「Guy Deutscher, 椋田直子」）で、エージェントは
    カナ（「ガイ・ドイッチャー」）で書くので、そもそも突き合わせられない。
    """
    found_names = _people(found)
    if not given or not found_names:
        return False
    return bool(_JAPANESE.search(given)) == bool(_JAPANESE.search(found_names[0]))


# 並列書名（「アースダイバー = Earth Diver」の「= Earth Diver」）。次の副題の区切りか末尾まで
_PARALLEL_TITLE = re.compile(r"\s[=＝]\s[^:：]*?(?=\s[:：]|$)")


def clean_title(title: str, *authors: str | None) -> str:
    """画面に出す書名に整える。書誌の癖（英語の並列書名、頭に付いた著者名）を落とす"""
    text = _PARALLEL_TITLE.sub("", title).strip()
    for author in authors:
        first = re.split(r"[,，、/／]", author or "")[0].strip()
        first = _ROLE.sub("", first).strip()
        # 「デービッド・アトキンソン新・生産性立国論」→「新・生産性立国論」
        if len(first) >= 3 and text.startswith(first) and len(text) > len(first) + 2:
            text = text[len(first):].lstrip(" 　・:：")
    return text


def normalize_isbn(raw: str | None) -> str | None:
    """ハイフンを除き、ISBN-10 は 13桁に直す。形が不正なら None"""
    if not raw:
        return None
    digits = re.sub(r"[^0-9Xx]", "", unicodedata.normalize("NFKC", raw)).upper()
    if len(digits) == 10:
        core = "978" + digits[:9]
    elif len(digits) == 13 and digits.isdigit():
        core = digits[:12]
    else:
        return None
    check = (10 - sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core)) % 10) % 10
    isbn = core + str(check)
    if len(digits) == 13 and isbn != digits:
        return None  # チェックディジットが合わない＝写し間違いか作り話
    return isbn


# ---------------------------------------------------------------- targets

def _dismissed_isbns(db_path: Path) -> list[str]:
    """「興味なし」にした ISBN。一覧の API が無いので DB を読み取り専用で開く"""
    if not db_path.exists():
        print(f"! {db_path} が無いので「興味なし」は除外できません", file=sys.stderr)
        return []
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            return [row[0] for row in con.execute("SELECT isbn FROM dismissed_books")]
        finally:
            con.close()
    except sqlite3.Error as error:
        print(f"! 「興味なし」を読めませんでした（{error}）。除外せずに続けます", file=sys.stderr)
        return []


def cmd_targets(args) -> int:
    status, books = _get(args.api, "/api/books")
    if status != 200:
        print(f"! 本の一覧を取れませんでした（{status}）。./run.sh で API を起動してください", file=sys.stderr)
        return 1

    wanted = {int(x) for x in args.ids.split(",")} if args.ids else None
    quota = {"near": args.near, "far": args.far}
    targets = []
    for book in sorted(books, key=lambda b: b["id"]):
        if wanted is not None and book["id"] not in wanted:
            continue
        existing = [] if args.replace else _existing(args.api, book["id"])
        have = {d: sum(1 for s in existing if s["distance"] == d) for d in DISTANCES}
        need = {d: max(0, quota[d] - have[d]) for d in DISTANCES}
        if not any(need.values()):
            continue
        notes = []
        if book.get("note_count"):
            _, rows = _get(args.api, f"/api/books/{book['id']}/notes")
            notes = [{"kind": n["kind"], "text": n["text"], "memo": n.get("memo")} for n in rows or []]
        targets.append({
            "book_id": book["id"],
            "title": book["title"],
            "author": book.get("author"),
            "publisher": book.get("publisher"),
            "category": book.get("category"),
            "tags": [t["name"] if isinstance(t, dict) else t for t in book.get("tags") or []],
            "status": book["status"],
            "rating": book.get("rating"),
            "notes": notes,
            "need": need,
            # すでに候補にしてある本。同じ本を重ねて選ばないために渡す
            "existing": [{"title": s["title"], "isbn": s.get("isbn"), "distance": s["distance"]}
                         for s in existing],
        })
        if args.limit and len(targets) >= args.limit:
            break

    work = Path(args.dir)
    if any((work / "out").glob("*.json")):
        # バッチ名（b01…）は回ごとに振り直すので、前の回の出力と混ざってしまう
        print(f"! {work}/out/ に前の回の出力が残っています。apply 済みなら別の --dir で実行してください",
              file=sys.stderr)
        return 1
    batch_dir = work / "batches"
    batch_dir.mkdir(parents=True, exist_ok=True)
    for old in batch_dir.glob("*.json"):
        old.unlink()  # 前の回のバッチが混ざらないように

    (work / "targets.json").write_text(json.dumps({
        "mode": "replace" if args.replace else "fill",
        "quota": quota,
        "books": targets,
    }, ensure_ascii=False, indent=1))

    dismissed = _dismissed_isbns(Path(args.db))
    (work / "shelf.txt").write_text(
        "# 本棚にすでにある本（候補にしない）\n"
        + "\n".join(f"{b['title']} / {b.get('author') or '著者不明'}" for b in books) + "\n"
    )
    (work / "exclude.json").write_text(json.dumps({
        "shelf": [{"title": b["title"], "isbn": b.get("isbn")} for b in books],
        "dismissed_isbns": dismissed,
    }, ensure_ascii=False, indent=1))

    # エージェントへの指示書。バッチごとにパスを埋めたものを prompts/ に置く
    brief = (Path(__file__).resolve().parent.parent / "agent-brief.md").read_text()
    prompt_dir = work / "prompts"
    prompt_dir.mkdir(exist_ok=True)
    (work / "out").mkdir(exist_ok=True)
    for old in prompt_dir.glob("*.md"):
        old.unlink()

    size = max(1, args.batch_size)
    names = []
    for start in range(0, len(targets), size):
        name = f"b{start // size + 1:02d}"
        batch_path = (batch_dir / f"{name}.json").resolve()
        batch_path.write_text(json.dumps(targets[start : start + size], ensure_ascii=False, indent=1))
        (prompt_dir / f"{name}.md").write_text(
            brief.replace("{BATCH}", str(batch_path))
            .replace("{SHELF}", str((work / "shelf.txt").resolve()))
            .replace("{OUT}", str((work / "out" / f"{name}.json").resolve()))
        )
        names.append(name)

    total_need = sum(sum(t["need"].values()) for t in targets)
    print(f"対象 {len(targets)} 冊（候補あと {total_need} 冊ぶん）/ 本棚 {len(books)} 冊 / 興味なし {len(dismissed)} 件")
    print(f"モード: {'作り直し（replace）' if args.replace else '補充（fill）'}")
    print(f"バッチ {len(names)} 個 → {batch_dir}/ " + " ".join(names))
    print(f"指示書 → {prompt_dir.resolve()}/<バッチ名>.md（出力先 {(work / 'out').resolve()}/<バッチ名>.json）")
    return 0


# ---------------------------------------------------------------- verify

def _search(api: str, title: str, author: str | None) -> list[dict]:
    """書名＋著者で探す（遅い: 1回10秒以上かかることがある）"""
    query = f"{title} {author or ''}".strip()[:100]
    status, found = _request(
        "GET", f"{api}/api/search?{urllib.parse.urlencode({'q': query, 'limit': 5})}", timeout=60
    )
    return found if status == 200 and isinstance(found, list) else []


def _identify(api: str, cand: dict, use_search: bool, accept: frozenset):
    """候補が実在するか書誌で確かめる。(確かめ方, 書誌 or None, 一言) を返す。

    確かめ方: isbn / partial（書名が一部だけ重なる）/ search（書名検索で特定）/
    accepted（人が確かめて --accept した）/ mismatch（ISBN は別の書名を指す）/ unverified
    """
    title = cand["title"].strip()
    isbn = normalize_isbn(cand.get("isbn"))
    pointed = None  # ISBN が指している本（書名が合わなかったとき）
    if isbn:
        status, found = _get(api, f"/api/isbn/{isbn}")
        if status == 200:
            if titles_match(title, found["title"]):
                return "isbn", found, ""
            if isbn in accept:
                return "accepted", found, ""
            if titles_overlap(title, found["title"]):
                same = authors_match(cand.get("author"), found.get("author"))
                return ("isbn" if same else "partial"), found, ""
            pointed = found
    if use_search:
        for found in _search(api, title, cand.get("author")):
            if titles_match(title, found["title"]):
                return "search", found, ""

    tail = "。書名検索でも見つからない" if use_search else ""
    if pointed is not None:
        # 表記の違いだけ（「ファクトフルネス」と「FACTFULNESS」）か、別の本の ISBN かは人が見る
        return "mismatch", None, f"ISBN は「{pointed['title']} / {pointed.get('author')}」を指す{tail}"
    if cand.get("isbn") and not isbn:
        return "unverified", None, "ISBNの形が不正（桁数かチェックディジットが合わない）" + tail
    return "unverified", None, "ISBNで本が見つからない" + tail


def _check_shape(cand: dict) -> str | None:
    if not (cand.get("title") or "").strip():
        return "書名が空"
    if cand.get("distance") not in DISTANCES:
        return f"distance が不正: {cand.get('distance')}"
    if cand.get("basis") not in ("note", "rating", "tag"):
        return f"basis が不正: {cand.get('basis')}"
    reason = (cand.get("reason") or "").strip()
    if not reason or len(reason) > 200:
        return f"reason が空か200字超（{len(reason)}字）"
    return None


def verify_candidate(api: str, cand: dict, exclude: dict, use_search: bool = True,
                     accept: frozenset = frozenset()):
    """(状態, 流し込む形 or None, 一言) を返す。

    状態は ok / warn / invalid / mismatch / unverified / excluded
    """
    problem = _check_shape(cand)
    if problem:
        return "invalid", None, problem
    state, book, note = resolve_book(api, cand, exclude, use_search, accept)
    if book is None:
        return state, None, note
    row = {**book, "basis": cand["basis"], "distance": cand["distance"],
           "reason": cand["reason"].strip()}
    return state, row, note


def resolve_book(api: str, cand: dict, exclude: dict, use_search: bool = True,
                 accept: frozenset = frozenset()):
    """候補の本が実在し、本棚にも「興味なし」にも無いかを確かめる。

    (状態, {title, author, isbn, cover_url} or None, 一言) を返す。状態は
    ok / warn / mismatch / unverified / excluded。キーワードのおすすめ（keyword-suggestions）も使う
    """
    how, info, detail = _identify(api, cand, use_search, accept)
    if info is None:
        return how, None, detail

    if info["isbn"] in exclude["shelf_isbns"] or any(
        titles_match(info["title"], t) for t in exclude["shelf_titles"]
    ):
        return "excluded", None, "本棚にある"
    if info["isbn"] in exclude["dismissed"]:
        return "excluded", None, "興味なしにした本"

    given_author = (cand.get("author") or "").strip() or None
    comparable = authors_comparable(given_author, info.get("author"))
    same_author = authors_match(given_author, info.get("author"))
    # 書名・ISBN・表紙は照合した書誌を正とする。著者だけは、書誌がローマ字＋訳者
    # （画面で読みにくい）のときにエージェントのカナ表記を使う
    author = given_author if given_author and (same_author or not comparable) else info.get("author")

    book = {
        "title": clean_title(info["title"], info.get("author"), given_author),
        "author": author,
        "isbn": info["isbn"],
        "cover_url": info.get("cover_url"),
    }
    notes = []
    if how == "search" and info["isbn"] != normalize_isbn(cand.get("isbn")):
        notes.append(f"書名検索で特定（ISBN {cand.get('isbn')} → {info['isbn']}）")
    if how == "partial":
        notes.append(f"書名が一部だけ一致: 「{cand['title']}」/「{info['title']}」")
    if comparable and not same_author:
        notes.append(f"著者が違う: 「{given_author}」/「{info.get('author')}」")
    return ("warn" if notes else "ok"), book, "；".join(notes)


def load_exclude(path: Path) -> dict:
    """targets が書き出した exclude.json を、resolve_book に渡す形にする"""
    raw = json.loads(path.read_text())
    return {
        "shelf_isbns": {b["isbn"] for b in raw["shelf"] if b.get("isbn")},
        "shelf_titles": [b["title"] for b in raw["shelf"]],
        "dismissed": set(raw["dismissed_isbns"]),
    }


def cmd_verify(args) -> int:
    work = Path(args.dir)
    targets = {t["book_id"]: t for t in json.loads((work / "targets.json").read_text())["books"]}
    exclude = load_exclude(work / "exclude.json")

    accept = frozenset(filter(None, (normalize_isbn(x) for x in (args.accept or "").split(","))))

    inputs = [Path(p) for p in args.inputs] or sorted((work / "out").glob("*.json"))
    entries = []
    for path in inputs:
        entries.extend(json.loads(path.read_text()))

    verified: dict[str, list] = {}
    problems = []
    counts: dict[str, int] = {}
    for entry in entries:
        book_id = entry["book_id"]
        target = targets.get(book_id)
        if target is None:
            print(f"  [skip      ] #{book_id} は今回の対象ではない")
            continue
        seen = {s["isbn"] for s in target["existing"] if s.get("isbn")}
        left = dict(target["need"])
        rows = []
        for cand in entry.get("suggestions", []):
            state, row, note = verify_candidate(args.api, cand, exclude, not args.no_search, accept)
            if row and row["isbn"] in seen:
                state, row, note = "duplicate", None, "この本の候補にすでにある"
            elif row and left.get(row["distance"], 0) <= 0:
                state, row, note = "extra", None, f"{row['distance']} は頼んだ数を超えている"
            counts[state] = counts.get(state, 0) + 1
            if row:
                seen.add(row["isbn"])
                left[row["distance"]] -= 1
                rows.append(row)
            if state != "ok":
                problems.append({"book_id": book_id, "state": state, "title": cand.get("title"),
                                 "isbn": cand.get("isbn"), "note": note})
            print(f"  [{state:10}] #{book_id} {cand.get('title')}" + (f" — {note}" if note else ""))
        verified[str(book_id)] = rows

    (work / "verified.json").write_text(json.dumps(verified, ensure_ascii=False, indent=1))
    (work / "problems.json").write_text(json.dumps(problems, ensure_ascii=False, indent=1))

    print(f"\n結果: {counts}")
    print(f"流し込める形 → {work / 'verified.json'}（問題の一覧 → problems.json）")
    missing = [i for i in targets if str(i) not in verified]
    if missing:
        print(f"出力が無い本: {', '.join(f'#{i}' for i in missing)}")
    return 0


# ---------------------------------------------------------------- apply

_KEEP = ("title", "author", "isbn", "cover_url", "basis", "distance", "reason")


def merge_for_fill(existing: list[dict], rows: list[dict], quota: dict) -> tuple[list[dict], int]:
    """補充モードで PUT する全件と、そのうち新しく足した数を返す。

    同じ verified.json を2回 apply しても候補が倍にならないよう、既存と同じ ISBN は足さず、
    距離ごとの上限（quota）を超える分も足さない。
    """
    payload = [{k: s[k] for k in _KEEP} for s in existing]
    have_isbns = {s["isbn"] for s in payload if s.get("isbn")}
    count = {d: sum(1 for s in payload if s["distance"] == d) for d in DISTANCES}
    added = 0
    for row in rows:
        if row["isbn"] in have_isbns or count[row["distance"]] >= quota[row["distance"]]:
            continue
        payload.append(row)
        have_isbns.add(row["isbn"])
        count[row["distance"]] += 1
        added += 1
    # 近い本を先に並べる（ダイアログの既定「両方」で最初に見えるのは先頭3冊）
    payload.sort(key=lambda r: r["distance"] != "near")
    return payload, added


def cmd_apply(args) -> int:
    work = Path(args.dir)
    meta = json.loads((work / "targets.json").read_text())
    verified = json.loads((work / "verified.json").read_text())
    done = skipped = 0
    for book_id, rows in verified.items():
        if not rows:
            continue
        if meta["mode"] == "replace":
            payload = sorted(rows, key=lambda r: r["distance"] != "near")
            added = len(rows)
        else:
            existing = _existing(args.api, int(book_id))
            if any(s.get("added_book_id") for s in existing):
                # PUT は全件を作り直すので「✓ 積読に追加しました」の印が消えてしまう
                print(f"  [skip] #{book_id} 積読に追加済みの候補があるので補充しない")
                skipped += 1
                continue
            payload, added = merge_for_fill(existing, rows, meta["quota"])
            if added == 0:
                print(f"  [skip] #{book_id} 足すものが無い（登録済み）")
                skipped += 1
                continue
        if args.dry_run:
            print(f"  [dry ] #{book_id} {len(payload)} 冊: " + " / ".join(r["title"] for r in payload))
            continue
        status, body = _request("PUT", f"{args.api}/api/books/{book_id}/suggestions", payload)
        if status != 200:
            print(f"  [fail] #{book_id} {status}: {body}", file=sys.stderr)
            continue
        print(f"  [ok  ] #{book_id} {len(payload)} 冊（うち新規 {added}）")
        done += 1
    print(f"\n流し込み {done} 冊 / スキップ {skipped} 冊")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=DEFAULT_API)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("targets", help="候補が足りない本を数えてバッチにする")
    p.add_argument("--dir", required=True, help="作業ディレクトリ")
    p.add_argument("--ids", help="この本だけ（カンマ区切り）")
    p.add_argument("--replace", action="store_true", help="今の候補を捨てて作り直す（読了後にメモから選び直すとき）")
    p.add_argument("--near", type=int, default=2, help="1冊あたりの近い本の数")
    p.add_argument("--far", type=int, default=2, help="1冊あたりの少し離れた本の数")
    p.add_argument("--batch-size", type=int, default=4, help="エージェント1体に渡す冊数")
    p.add_argument("--limit", type=int, help="先頭から何冊まで")
    p.add_argument("--db", default=DEFAULT_DB, help="「興味なし」を読む DB")
    p.set_defaults(func=cmd_targets)

    p = sub.add_parser("verify", help="エージェントの出した候補を照合する")
    p.add_argument("--dir", required=True, help="作業ディレクトリ")
    p.add_argument("inputs", nargs="*", help="エージェントの出力（省略時は <dir>/out/*.json）")
    p.add_argument("--no-search", action="store_true", help="書名検索（遅い）での救済をしない")
    p.add_argument("--accept", help="mismatch を人が確かめて通す ISBN（カンマ区切り）")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("apply", help="照合済みの候補を流し込む")
    p.add_argument("--dir", required=True, help="作業ディレクトリ")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_apply)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
