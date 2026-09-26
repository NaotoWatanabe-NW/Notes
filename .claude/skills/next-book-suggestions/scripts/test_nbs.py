"""nbs.py の照合ロジックのテスト。

実行: .venv/bin/pytest .claude/skills/next-book-suggestions/scripts -q
"""
import pytest

from nbs import authors_comparable, authors_match, normalize_isbn, prefix_match, titles_match


@pytest.mark.parametrize("given, found", [
    ("ハプスブルク帝国 (講談社現代新書)", "ハプスブルク帝国"),
    ("物語 ウィーンの歴史", "物語ウィーンの歴史 : 音楽の都の八〇〇年"),
    ("ピダハン", "ピダハン : 「言語本能」を超える文化と世界観"),
    ("仏教", "仏教 第2版"),
    ("銃・病原菌・鉄", "銃・病原菌・鉄. 上巻"),
    ("思考の整理学", "新版　思考の整理学"),
    ("神道はなぜ教えがないのか", "[増補版]神道はなぜ教えがないのか"),
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


def test_authors_match_ignores_role_suffix_and_separators():
    assert authors_match("川畑秀明", "川畑秀明／著")
    assert authors_match("岩崎周一", "岩崎周一")


def test_authors_match_is_false_for_different_people():
    assert not authors_match("江村洋", "岩崎周一")


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
