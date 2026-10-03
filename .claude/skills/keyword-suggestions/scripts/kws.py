#!/usr/bin/env python3
"""キーワードのおすすめを作るための道具（標準ライブラリだけで動く）。

  targets  キーワードごとに、手がかりになる本棚の本と頼む数を書き出す
  verify   エージェントが出した候補を ISBN で照合し、流し込める形にする
  apply    照合済みの候補を PUT /api/topics で流し込む

本の照合（書名・著者・ISBN・本棚との重複）は next-book-suggestions の nbs.py をそのまま使う。
リポジトリの直下で、API を起動した状態で使う。3つとも同じ作業ディレクトリ（--dir）を使う。
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "next-book-suggestions" / "scripts"))
import nbs  # noqa: E402

# 区分。DB には距離（near/far）しか無いので、same と adjacent は near、side は far として入れる
SLOTS = ("same", "adjacent", "side")
SLOT_DISTANCE = {"same": "near", "adjacent": "near", "side": "far"}
SLOT_LABELS = {"same": "同じテーマ", "adjacent": "近いテーマ", "side": "少し離れた"}
GENRES = ("study", "novel", "essay", "selfhelp")
# PUT する項目。区分（slot）は DB に無いので落とす
_KEEP = ("title", "author", "isbn", "cover_url", "distance", "reason", "from_book_id",
         "genre", "publisher", "total")


def normalize_keyword(text: str) -> str:
    """API と同じそろえ方（全角/半角、前後と連続する空白）。既存のキーワードを探すときに使う"""
    return " ".join(unicodedata.normalize("NFKC", text or "").split())


def _fold(text: str) -> str:
    """表記のゆれをそろえる（全角/半角・大文字/小文字・ひらがな/カタカナ）"""
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[ぁ-ゖ]", lambda m: chr(ord(m.group()) + 0x60), text)


def match_books(keyword: str, shelf: list[dict]) -> list[int]:
    """キーワードの語を、書名・著者・分野・タグ・メモのどこかに含む本の id。

    当たった語が多い本から並べる。文字列が一致するかを見るだけなので、取りこぼしも誤りもある。
    エージェントに渡す出発点で、手がかりの本を選び直すのはエージェント。
    """
    terms = _fold(keyword).split()
    scored = []
    for book in shelf:
        fields = [book["title"], book.get("author"), book.get("category"), *book.get("tags", [])]
        for note in book.get("notes", []):
            fields += [note.get("text"), note.get("memo")]
        text = _fold("\n".join(f for f in fields if f))
        hits = sum(1 for term in terms if term in text)
        if hits:
            scored.append((-hits, book["id"]))
    return [book_id for _, book_id in sorted(scored)]


def distance_quota(slots: dict) -> dict:
    return {"near": slots["same"] + slots["adjacent"], "far": slots["side"]}


def need_for(slots: dict, existing: list[dict]) -> dict:
    """距離ごとに、あと何冊要るか。既存の候補には区分が無いので距離で数える"""
    quota = distance_quota(slots)
    return {d: max(0, quota[d] - sum(1 for s in existing if s["distance"] == d))
            for d in nbs.DISTANCES}


def check_shape(cand: dict, shelf_ids: set[int]) -> str | None:
    if not (cand.get("title") or "").strip():
        return "書名が空"
    if cand.get("slot") not in SLOTS:
        return f"slot が不正: {cand.get('slot')}"
    reason = (cand.get("reason") or "").strip()
    if not reason or len(reason) > 200:
        return f"reason が空か200字超（{len(reason)}字）"
    from_id = cand.get("from_book_id")
    if from_id is not None and from_id not in shelf_ids:
        return f"from_book_id {from_id} は本棚に無い"
    if cand.get("category") not in nbs.GENRE_BY_LABEL:
        return f"category が不正: {cand.get('category')}"
    return None


def order_rows(rows: list[dict]) -> list[dict]:
    """同じテーマ → 近いテーマ → 少し離れた の順"""
    return sorted(rows, key=lambda r: SLOTS.index(r["slot"]))


def merge_for_topic(existing: list[dict], rows: list[dict], quota: dict) -> tuple[list[dict], int]:
    """補充モードで PUT する全件と、そのうち新しく足した数を返す。

    同じ verified.json を2回 apply しても候補が倍にならないよう、既存と同じ ISBN は足さず、
    距離ごとの上限（quota）を超える分も足さない。近い本を先に並べる。
    """
    payload = [{k: s.get(k) for k in _KEEP} for s in existing]
    have_isbns = {s["isbn"] for s in payload if s.get("isbn")}
    count = {d: sum(1 for s in payload if s["distance"] == d) for d in nbs.DISTANCES}
    added = 0
    for row in order_rows(rows):
        if row["isbn"] in have_isbns or count[row["distance"]] >= quota[row["distance"]]:
            continue
        payload.append({k: row.get(k) for k in _KEEP})
        have_isbns.add(row["isbn"])
        count[row["distance"]] += 1
        added += 1
    payload.sort(key=lambda r: r["distance"] != "near")
    return payload, added


# ---------------------------------------------------------------- API

def _topic_ids(api: str) -> dict[str, int]:
    status, topics = nbs._get(api, "/api/topics")
    if status != 200:
        raise RuntimeError(f"キーワードの一覧を読めませんでした（{status}）")
    return {t["keyword"]: t["id"] for t in topics}


def _existing(api: str, keyword: str) -> list[dict]:
    """そのキーワードにいま設定してある候補（「興味なし」は API が外して返す）"""
    topic_id = _topic_ids(api).get(keyword)
    if topic_id is None:
        return []
    status, topic = nbs._get(api, f"/api/topics/{topic_id}")
    if status != 200:
        raise RuntimeError(f"「{keyword}」の候補を読めませんでした（{status}）")
    return topic["suggestions"]


# ---------------------------------------------------------------- targets

def _shelf(api: str, books: list[dict]) -> list[dict]:
    """エージェントに渡す本棚。手がかりの本を選ぶのにも、本棚にある本を避けるのにも使う"""
    shelf = []
    for book in sorted(books, key=lambda b: b["id"]):
        notes = []
        if book.get("note_count"):
            _, rows = nbs._get(api, f"/api/books/{book['id']}/notes")
            notes = [{"kind": n["kind"], "text": n["text"], "memo": n.get("memo")} for n in rows or []]
        shelf.append({
            "id": book["id"],
            "title": book["title"],
            "author": book.get("author"),
            "category": book.get("category"),
            "tags": [t["name"] if isinstance(t, dict) else t for t in book.get("tags") or []],
            "status": book["status"],
            "rating": book.get("rating"),
            "notes": notes,
        })
    return shelf


def cmd_targets(args) -> int:
    status, books = nbs._get(args.api, "/api/books")
    if status != 200:
        print(f"! 本の一覧を取れませんでした（{status}）。API が動いているか確かめてください", file=sys.stderr)
        return 1

    keywords = []
    for raw in args.keyword:
        keyword = normalize_keyword(raw)
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    if not keywords:
        print("! キーワードが空です", file=sys.stderr)
        return 1
    extra = [int(x) for x in args.books.split(",")] if args.books else []
    if extra and len(keywords) > 1:
        print("! --books はキーワードが1つのときだけ使えます", file=sys.stderr)
        return 1
    unknown = sorted(set(extra) - {b["id"] for b in books})
    if unknown:
        print(f"! 本棚に無い本の id: {unknown}", file=sys.stderr)
        return 1

    work = Path(args.dir)
    if any((work / "out").glob("*.json")):
        # バッチ名（k01…）は回ごとに振り直すので、前の回の出力と混ざってしまう
        print(f"! {work}/out/ に前の回の出力が残っています。apply 済みなら別の --dir で実行してください",
              file=sys.stderr)
        return 1

    shelf = _shelf(args.api, books)
    slots = {"same": args.same, "adjacent": args.adjacent, "side": args.side}
    targets = []
    for keyword in keywords:
        existing = [] if args.replace else _existing(args.api, keyword)
        if any(s.get("added_book_id") for s in existing):
            # PUT は全件を作り直すので「積読に追加済み」の印が消えてしまう
            print(f"  [skip] 「{keyword}」積読に追加済みの候補があるので補充しない（--replace で作り直すと印は消える）")
            continue
        need = need_for(slots, existing)
        if not any(need.values()):
            print(f"  [skip] 「{keyword}」候補は足りている（作り直すなら --replace）")
            continue
        related = extra + [i for i in match_books(keyword, shelf) if i not in extra]
        targets.append({
            "name": f"k{len(targets) + 1:02d}",
            "keyword": keyword,
            "genre": args.genre,
            "related": related,
            "slots": slots,
            "need": need,
            # すでに設定してある候補。同じ本を重ねて選ばないために渡す
            "existing": [{"title": s["title"], "isbn": s.get("isbn"), "distance": s["distance"],
                          "reason": s["reason"]} for s in existing],
        })

    if not targets:
        print("対象のキーワードがありません")
        return 0

    batch_dir, prompt_dir = work / "batches", work / "prompts"
    for folder in (batch_dir, prompt_dir, work / "out"):
        folder.mkdir(parents=True, exist_ok=True)
    for old in [*batch_dir.glob("*.json"), *prompt_dir.glob("*.md")]:
        old.unlink()  # 前の回のバッチが混ざらないように

    (work / "targets.json").write_text(json.dumps({
        "mode": "replace" if args.replace else "fill",
        "slots": slots,
        "topics": targets,
    }, ensure_ascii=False, indent=1))
    shelf_path = (work / "shelf.json").resolve()
    # 1冊1行。エージェントの Read は既定で2000行までなので、字下げすると本が増えたとき切れる
    shelf_path.write_text("[\n" + ",\n".join(json.dumps(b, ensure_ascii=False) for b in shelf) + "\n]\n")
    dismissed = nbs._dismissed_isbns(Path(args.db))
    (work / "exclude.json").write_text(json.dumps({
        "shelf": [{"title": b["title"], "isbn": b.get("isbn")} for b in books],
        "dismissed_isbns": dismissed,
    }, ensure_ascii=False, indent=1))

    brief = (Path(__file__).resolve().parent.parent / "agent-brief.md").read_text()
    titles = {b["id"]: b["title"] for b in shelf}
    for target in targets:
        name = target["name"]
        batch_path = (batch_dir / f"{name}.json").resolve()
        batch_path.write_text(json.dumps(target, ensure_ascii=False, indent=1))
        (prompt_dir / f"{name}.md").write_text(
            brief.replace("{BATCH}", str(batch_path))
            .replace("{SHELF}", str(shelf_path))
            .replace("{OUT}", str((work / "out" / f"{name}.json").resolve()))
        )
        hint = "、".join(f"『{titles[i]}』" for i in target["related"][:5]) or "なし"
        more = f" ほか{len(target['related']) - 5}冊" if len(target["related"]) > 5 else ""
        print(f"  {name} 「{target['keyword']}」 あと near {target['need']['near']}・far {target['need']['far']}"
              f" / 文字列で当たった本: {hint}{more}")

    print(f"\nキーワード {len(targets)} 個 / 本棚 {len(books)} 冊 / 興味なし {len(dismissed)} 件")
    print(f"モード: {'作り直し（replace）' if args.replace else '補充（fill）'}")
    print(f"指示書 → {prompt_dir.resolve()}/<名前>.md（出力先 {(work / 'out').resolve()}/<名前>.json）")
    return 0


# ---------------------------------------------------------------- verify

def cmd_verify(args) -> int:
    work = Path(args.dir)
    meta = json.loads((work / "targets.json").read_text())
    targets = {t["keyword"]: t for t in meta["topics"]}
    exclude = nbs.load_exclude(work / "exclude.json")
    titles = {b["id"]: b["title"] for b in json.loads((work / "shelf.json").read_text())}
    accept = frozenset(filter(None, (nbs.normalize_isbn(x) for x in (args.accept or "").split(","))))

    inputs = [Path(p) for p in args.inputs] or sorted((work / "out").glob("*.json"))
    verified: dict[str, dict] = {}
    problems = []
    counts: dict[str, int] = {}
    for path in inputs:
        entry = json.loads(path.read_text())
        if not isinstance(entry, dict):
            # next-book-suggestions の形（本ごとの配列）で書いてくることがある
            print(f"  [skip      ] {path.name}: JSON オブジェクト1つの形になっていない")
            continue
        keyword = normalize_keyword(entry.get("keyword", ""))
        target = targets.get(keyword)
        if target is None:
            print(f"  [skip      ] {path.name}: 「{keyword}」は今回の対象ではない")
            continue
        genre = target["genre"] or entry.get("genre")
        related = "、".join(f"『{titles.get(i, f'#{i}')}』" for i in entry.get("related_books") or []) or "なし"
        print(f"\n■ 「{keyword}」 ジャンル {genre}" + ("（仮ルール）" if genre != "study" else "")
              + f" / 手がかりの本: {related}")
        if genre not in GENRES:
            print(f"  ! ジャンルが不明: {genre}")

        seen = {s["isbn"] for s in target["existing"] if s.get("isbn")}
        left = dict(target["need"])
        rows = []
        for cand in entry.get("suggestions", []):
            problem = check_shape(cand, set(titles))
            if problem:
                state, row, note = "invalid", None, problem
            else:
                state, book, note = nbs.resolve_book(args.api, cand, exclude, not args.no_search, accept)
                row = None if book is None else {
                    **book,
                    "distance": SLOT_DISTANCE[cand["slot"]],
                    "reason": cand["reason"].strip(),
                    "from_book_id": cand.get("from_book_id"),
                    "genre": nbs.GENRE_BY_LABEL[cand["category"]],
                    "slot": cand["slot"],
                }
            if row and row["isbn"] in seen:
                state, row, note = "duplicate", None, "このキーワードの候補にすでにある"
            elif row and left[row["distance"]] <= 0:
                state, row, note = "extra", None, f"{SLOT_DISTANCE[cand['slot']]} は頼んだ数を超えている"
            counts[state] = counts.get(state, 0) + 1
            if row:
                seen.add(row["isbn"])
                left[row["distance"]] -= 1
                rows.append(row)
            if state != "ok":
                problems.append({"keyword": keyword, "state": state, "title": cand.get("title"),
                                 "isbn": cand.get("isbn"), "note": note})
            label = SLOT_LABELS.get(cand.get("slot"), "?")
            print(f"  [{state:10}] {label}: {cand.get('title')}" + (f" — {note}" if note else ""))
        verified[keyword] = {"genre": genre, "rows": rows}
        if any(left.values()):
            print(f"  → 足りない: near {left['near']}・far {left['far']}")

    (work / "verified.json").write_text(json.dumps(verified, ensure_ascii=False, indent=1))
    (work / "problems.json").write_text(json.dumps(problems, ensure_ascii=False, indent=1))

    print(f"\n結果: {counts}")
    print(f"流し込める形 → {work / 'verified.json'}（問題の一覧 → problems.json）")
    missing = [k for k in targets if k not in verified]
    if missing:
        print(f"出力が無いキーワード: {'、'.join(missing)}")
    return 0


# ---------------------------------------------------------------- apply

def cmd_apply(args) -> int:
    work = Path(args.dir)
    meta = json.loads((work / "targets.json").read_text())
    verified = json.loads((work / "verified.json").read_text())
    quota = distance_quota(meta["slots"])
    done = skipped = 0
    for keyword, entry in verified.items():
        rows = entry["rows"]
        if not rows:
            continue
        if meta["mode"] == "replace":
            payload = [{k: r.get(k) for k in _KEEP} for r in order_rows(rows)]
            added = len(payload)
        else:
            existing = _existing(args.api, keyword)
            if any(s.get("added_book_id") for s in existing):
                print(f"  [skip] 「{keyword}」積読に追加済みの候補があるので補充しない")
                skipped += 1
                continue
            payload, added = merge_for_topic(existing, rows, quota)
            if added == 0:
                print(f"  [skip] 「{keyword}」足すものが無い（登録済み）")
                skipped += 1
                continue
        if args.dry_run:
            print(f"  [dry ] 「{keyword}」{len(payload)} 冊: " + " / ".join(r["title"] for r in payload))
            continue
        status, body = nbs._request("PUT", f"{args.api}/api/topics",
                                    {"keyword": keyword, "suggestions": payload})
        if status != 200:
            print(f"  [fail] 「{keyword}」{status}: {body}", file=sys.stderr)
            continue
        print(f"  [ok  ] 「{keyword}」(topic #{body['id']}) {len(payload)} 冊（うち新規 {added}）")
        done += 1
    print(f"\n流し込み {done} 件 / スキップ {skipped} 件")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=nbs.DEFAULT_API)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("targets", help="キーワードごとに頼む数と手がかりの本を書き出す")
    p.add_argument("--dir", required=True, help="作業ディレクトリ")
    p.add_argument("--keyword", action="append", required=True, help="キーワード（複数なら繰り返す）")
    p.add_argument("--books", help="手がかりにする本棚の本の id（カンマ区切り。キーワード1つのときだけ）")
    p.add_argument("--genre", choices=GENRES, help="ジャンルを決め打ちする（省略時はエージェントが判断）")
    p.add_argument("--same", type=int, default=2, help="同じテーマの本の数（near）")
    p.add_argument("--adjacent", type=int, default=2, help="近いテーマの本の数（near）")
    p.add_argument("--side", type=int, default=2, help="少し離れた本の数（far）")
    p.add_argument("--replace", action="store_true", help="今の候補を捨てて作り直す")
    p.add_argument("--db", default=nbs.DEFAULT_DB, help="「興味なし」を読む DB")
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
