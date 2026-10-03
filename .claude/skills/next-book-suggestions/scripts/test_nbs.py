"""nbs.py の照合ロジックのテスト。

実行: .venv/bin/pytest .claude/skills/next-book-suggestions/scripts -q
"""
import pytest

from nbs import (
    authors_comparable,
    authors_match,
    clean_title,
    merge_for_fill,
    normalize_isbn,
    prefix_match,
    titles_match,
    titles_overlap,
)


@pytest.mark.parametrize("given, found", [
    ("ハプスブルク帝国 (講談社現代新書)", "ハプスブルク帝国"),
    ("物語 ウィーンの歴史", "物語ウィーンの歴史 : 音楽の都の八〇〇年"),
    ("ピダハン", "ピダハン : 「言語本能」を超える文化と世界観"),
    ("仏教", "仏教 第2版"),
    ("銃・病原菌・鉄", "銃・病原菌・鉄. 上巻"),
    ("思考の整理学", "新版　思考の整理学"),
    ("神道はなぜ教えがないのか", "[増補版]神道はなぜ教えがないのか"),
    ("影響力の武器[第三版]", "影響力の武器 : なぜ、人は動かされるのか"),
    ("マネー・ボール〔完全版〕", "マネー・ボール"),
])
def test_titles_match_accepts_same_book_with_label_subtitle_or_edition_differences(given, found):
    assert titles_match(given, found)


@pytest.mark.parametrize("given, found", [
    ("ハプスブルク家", "ハプスブルク家の歴史"),
    ("構造", "レヴィ=ストロース : 構造"),
    ("物語 イギリスの歴史", "物語 ウィーンの歴史"),
    ("存在しない本のタイトル", "利己的な遺伝子"),
])
def test_titles_match_rejects_different_books_that_share_words(given, found):
    assert not titles_match(given, found)


def test_prefix_match_accepts_title_whose_subtitle_is_missing_in_bibliography():
    # openBD は副題を持たないことがある
    assert prefix_match("脳は美をどう感じるか アートの脳科学", "脳は美をどう感じるか")


def test_prefix_match_rejects_prefixes_too_short_to_identify_a_book():
    assert not prefix_match("数学ガール", "数学")


@pytest.mark.parametrize("given, found", [
    # シリーズ名の位置が書誌と違う
    ("イラスト図解 スマート工場のしくみ : IoT、AI、RPAで変わるモノづくり",
     "スマート工場のしくみ : イラスト図解 : IoT、AI、RPAで変わるモノづくり"),
    ("図解入門 よくわかる最新シーケンス制御と回路図の基本",
     "よくわかる最新シーケンス制御と回路図の基本 : 制御回路の作成手法と手順を初歩から学ぶ!"),
    # 書誌の本題にローマ字が付いていても、副題が重なれば拾う
    ("クリスパー 究極の遺伝子編集技術の発見", "クリスパーCRISPR : 究極の遺伝子編集技術の発見"),
])
def test_titles_overlap_accepts_same_book_with_series_label_moved_or_romanized(given, found):
    assert titles_overlap(given, found)


@pytest.mark.parametrize("given, found", [
    # 同じ著者の別の本の ISBN を書いてきた実例
    ("オウム真理教の精神史", "現代オカルトの根源"),
    # カナとローマ字だけの違いは文字列では判定できない（人が見て --accept する）
    ("ファクトフルネス", "FACTFULNESS : 10の思い込みを乗り越え、データを基に世界を正しく見る習慣"),
])
def test_titles_overlap_rejects_titles_with_no_shared_part(given, found):
    assert not titles_overlap(given, found)


def test_authors_match_ignores_role_suffix_and_separators():
    assert authors_match("川畑秀明", "川畑秀明／著")
    assert authors_match("岩崎周一", "岩崎周一")


def test_authors_match_accepts_abbreviated_given_name_in_katakana():
    assert authors_match("ジョン・カバットジン", "J．カバットジン／著, 春木豊／訳")


def test_authors_match_is_false_for_different_people():
    assert not authors_match("江村洋", "岩崎周一")
    assert not authors_match("ジョン・スミス", "J．カバットジン／著")


def test_authors_comparable_is_false_between_katakana_and_roman_names():
    assert not authors_comparable("ガイ・ドイッチャー", "Guy Deutscher, 椋田直子")


def test_authors_comparable_is_true_when_both_are_japanese():
    assert authors_comparable("江村洋", "岩崎周一")


@pytest.mark.parametrize("raw, expected", [
    ("978-4-06-288442-6", "9784062884426"),
    ("4-06-288442-X", "9784062884426"),
    ("９７８４０６２８８４４２６", "9784062884426"),
])
def test_normalize_isbn_converts_hyphenated_isbn10_and_fullwidth_to_isbn13(raw, expected):
    assert normalize_isbn(raw) == expected


@pytest.mark.parametrize("raw", ["9784062884427", "12345", "", None])
def test_normalize_isbn_returns_none_for_bad_check_digit_or_wrong_length(raw):
    assert normalize_isbn(raw) is None


def _row(isbn: str, distance: str) -> dict:
    return {"title": f"本{isbn}", "author": "著者", "isbn": isbn, "cover_url": None,
            "basis": "tag", "distance": distance, "reason": "理由"}


QUOTA = {"near": 2, "far": 2}


def test_merge_for_fill_keeps_existing_and_adds_missing_far_with_near_first():
    existing = [_row("1", "near"), _row("2", "far"), _row("3", "near")]
    payload, added = merge_for_fill(existing, [_row("4", "far")], QUOTA)

    assert added == 1
    assert [r["isbn"] for r in payload] == ["1", "3", "2", "4"]


def test_merge_for_fill_adds_nothing_when_same_rows_are_applied_twice():
    rows = [_row("1", "near"), _row("2", "near"), _row("3", "far"), _row("4", "far")]
    first, _ = merge_for_fill([], rows, QUOTA)

    second, added = merge_for_fill(first, rows, QUOTA)

    assert added == 0
    assert len(second) == 4


def test_merge_for_fill_does_not_exceed_quota_per_distance():
    existing = [_row("1", "near"), _row("2", "near")]
    payload, added = merge_for_fill(existing, [_row("5", "near"), _row("6", "far")], QUOTA)

    assert added == 1
    assert sorted(r["isbn"] for r in payload) == ["1", "2", "6"]


def test_merge_for_fill_drops_server_only_fields_from_existing():
    existing = [{**_row("1", "near"), "id": 10, "added_book_id": None}]
    payload, _ = merge_for_fill(existing, [], QUOTA)

    assert set(payload[0]) == {"title", "author", "isbn", "cover_url", "basis", "distance", "reason"}


@pytest.mark.parametrize("given, found", [
    ("柳澤英子", "柳沢英子"),
    ("下條信輔", "下条信輔"),
    ("日高敏隆", "日髙敏隆／著"),
    ("村上龍", "村上竜"),
])
def test_authors_match_treats_itaiji_variants_as_same_person(given, found):
    assert authors_match(given, found)


def test_titles_overlap_ignores_trailing_volume_number_in_bibliography():
    assert titles_overlap("100のモノが語る世界の歴史 文明の誕生", "１００のモノが語る世界の歴史１")


def test_titles_match_keeps_title_that_is_only_a_number():
    assert not titles_match("1984", "1Q84")
    assert titles_match("1984", "1984")


def test_titles_match_ignores_edition_prefix_without_han_and_parallel_title():
    assert titles_match("増補改訂 アースダイバー", "アースダイバー = Earth Diver")


@pytest.mark.parametrize("title, author, expected", [
    ("アースダイバー = Earth Diver", "中沢新一", "アースダイバー"),
    ("需要予測の基本 = The Basics of Demand Forecasting & Planning : この1冊ですべてわかる",
     "山口雄大", "需要予測の基本 : この1冊ですべてわかる"),
    ("デービッド・アトキンソン新・生産性立国論 : 人口減少で「経済の常識」が根本から変わった",
     "デービッド・アトキンソン", "新・生産性立国論 : 人口減少で「経済の常識」が根本から変わった"),
    ("ハプスブルク帝国", "岩崎周一", "ハプスブルク帝国"),
])
def test_clean_title_drops_parallel_title_and_leading_author_name(title, author, expected):
    assert clean_title(title, author) == expected


def test_clean_title_keeps_title_that_merely_equals_author_name():
    # 書名が著者名そのもの（評伝など）は削らない
    assert clean_title("孔子", "孔子") == "孔子"
