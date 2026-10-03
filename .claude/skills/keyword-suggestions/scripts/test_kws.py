"""kws.py のテスト（API を使わない部分）。

実行: .venv/bin/pytest .claude/skills/keyword-suggestions/scripts -q
本の照合そのもの（書名・著者・ISBN）は next-book-suggestions の test_nbs.py で見ている。
"""
import pytest

from kws import check_shape, match_books, merge_for_topic, need_for, normalize_keyword, order_rows


@pytest.mark.parametrize("raw, expected", [
    ("ＡＩ　倫理 ", "AI 倫理"),
    ("  ゲーム理論  ", "ゲーム理論"),
    ("CI/CD", "CI/CD"),
])
def test_normalize_keyword_folds_width_and_collapses_spaces_like_the_api(raw, expected):
    assert normalize_keyword(raw) == expected


def _shelf_book(book_id, title, **fields):
    return {"id": book_id, "title": title, "author": None, "category": None, "tags": [],
            "notes": []} | fields


SHELF = [
    _shelf_book(27, "一歩ずつ学ぶゲーム理論", tags=["数学"]),
    _shelf_book(28, "ゲーム理論の思考法", tags=["数学", "思考法"]),
    _shelf_book(79, "プログラマの数学", tags=["数学", "IT"]),
    _shelf_book(61, "サピエンス全史", tags=["歴史"]),
]


def test_match_books_finds_books_by_title_and_tag():
    assert match_books("ゲーム理論", SHELF) == [27, 28]
    assert set(match_books("数学", SHELF)) == {27, 28, 79}


def test_match_books_ranks_books_hitting_more_words_first():
    assert match_books("思考法 数学", SHELF)[0] == 28


def test_match_books_ignores_hiragana_katakana_and_case_differences():
    shelf = [_shelf_book(1, "Pythonではじめるデータ分析", tags=["IT"])]
    assert match_books("python", shelf) == [1]
    assert match_books("データぶんせき", [_shelf_book(2, "データブンセキ入門")]) == [2]


def test_match_books_looks_into_notes():
    shelf = [_shelf_book(5, "仏教", notes=[{"kind": "memo", "text": "縁起と空の関係", "memo": None}])]
    assert match_books("縁起", shelf) == [5]


def test_match_books_returns_nothing_for_unrelated_keyword():
    assert match_books("料理", SHELF) == []


SLOTS = {"same": 2, "adjacent": 2, "side": 2}


def test_need_for_asks_full_quota_when_keyword_is_new():
    assert need_for(SLOTS, []) == {"near": 4, "far": 2}


def test_need_for_counts_existing_by_distance():
    existing = [{"distance": "near"}] * 3 + [{"distance": "far"}] * 2
    assert need_for(SLOTS, existing) == {"near": 1, "far": 0}


def _cand(**fields):
    base = {"title": "ゲーム理論入門の入門", "slot": "same", "from_book_id": 28,
            "reason": "数式なしで全体をつかめます", "category": "学術"}
    return base | fields


def test_check_shape_accepts_well_formed_candidate():
    assert check_shape(_cand(), {28}) is None
    assert check_shape(_cand(from_book_id=None), {28}) is None


@pytest.mark.parametrize("fields, message", [
    ({"title": " "}, "書名が空"),
    ({"slot": "near"}, "slot が不正"),
    ({"reason": "あ" * 201}, "200字超"),
    ({"from_book_id": 999}, "本棚に無い"),
    ({"category": "教養"}, "category が不正"),
])
def test_check_shape_rejects_bad_candidate(fields, message):
    assert message in check_shape(_cand(**fields), {28})


def _row(isbn, slot):
    distance = "far" if slot == "side" else "near"
    return {"title": f"本{isbn}", "author": "著者", "isbn": isbn, "cover_url": None,
            "distance": distance, "reason": "理由", "from_book_id": None, "slot": slot,
            "genre": "academic", "publisher": None, "total": None}


QUOTA = {"near": 4, "far": 2}


def test_order_rows_puts_same_then_adjacent_then_side():
    rows = [_row("1", "side"), _row("2", "adjacent"), _row("3", "same")]
    assert [r["slot"] for r in order_rows(rows)] == ["same", "adjacent", "side"]


def test_merge_for_topic_keeps_existing_and_puts_near_books_first():
    existing = [_row("1", "same"), _row("2", "side")]
    payload, added = merge_for_topic(existing, [_row("3", "side"), _row("4", "adjacent")], QUOTA)

    assert added == 2
    assert [r["isbn"] for r in payload] == ["1", "4", "2", "3"]


def test_merge_for_topic_adds_nothing_when_same_rows_are_applied_twice():
    rows = [_row("1", "same"), _row("2", "adjacent"), _row("3", "side")]
    first, _ = merge_for_topic([], rows, QUOTA)

    second, added = merge_for_topic(first, rows, QUOTA)

    assert added == 0
    assert len(second) == 3


def test_merge_for_topic_does_not_exceed_quota_per_distance():
    existing = [_row("1", "side"), _row("2", "side")]
    payload, added = merge_for_topic(existing, [_row("3", "side"), _row("4", "same")], QUOTA)

    assert added == 1
    assert sorted(r["isbn"] for r in payload) == ["1", "2", "4"]


def test_merge_for_topic_sends_only_fields_the_api_accepts():
    # 区分（slot）は DB に無く、id / added_book_id はサーバーが持つ項目。送ると 422 になる
    existing = [{**_row("1", "same"), "id": 10, "added_book_id": None}]
    payload, _ = merge_for_topic(existing, [_row("2", "side")], QUOTA)

    expected = {"title", "author", "isbn", "cover_url", "distance", "reason", "from_book_id",
                "genre", "publisher", "total"}
    assert all(set(r) == expected for r in payload)
