"""ISBN 正規化のテスト"""
import pytest

from app.isbn import InvalidIsbnError, normalize


def test_ハイフン付きのISBN13からハイフンを取り除く():
    assert normalize("978-4-274-22629-8") == "9784274226298"


def test_前後の空白を取り除く():
    assert normalize("  9784274226298 ") == "9784274226298"


def test_ISBN10を13桁に変換する():
    # 『達人プログラマー』旧版の ISBN-10 → 978 を付けて再計算した ISBN-13
    assert normalize("4274226298") == "9784274226298"


def test_末尾がXのISBN10も13桁に変換できる():
    assert normalize("020161622X") == "9780201616224"


def test_空文字はNoneになる():
    # 空文字のまま保存すると、2冊目の空文字が UNIQUE 制約に引っかかる
    assert normalize("") is None


def test_空白だけの文字列はNoneになる():
    assert normalize("   ") is None


def test_Noneはそのまま返る():
    assert normalize(None) is None


def test_チェックディジットが合わないISBN13は拒否される():
    with pytest.raises(InvalidIsbnError):
        normalize("9784274226299")


def test_チェックディジットが合わないISBN10は拒否される():
    with pytest.raises(InvalidIsbnError):
        normalize("4274226299")


def test_桁数が足りない文字列は拒否される():
    with pytest.raises(InvalidIsbnError):
        normalize("12345")


def test_数字以外を含む文字列は拒否される():
    with pytest.raises(InvalidIsbnError):
        normalize("97842742262AB")


# --- Amazon の ASIN ---

def test_紙の本のASINはISBN10として扱える():
    # 紙の本の ASIN は ISBN-10 と同じ値なので、そのまま通る
    assert normalize("4274226298") == "9784274226298"


def test_KindleのASINは理由を添えて拒否する():
    # 「チェックディジットが合いません」だと、何が悪いのか伝わらない
    with pytest.raises(InvalidIsbnError) as error:
        normalize("B08XYZ1234")
    assert "Kindle" in str(error.value)


def test_KindleのASINは小文字でも拒否する():
    with pytest.raises(InvalidIsbnError) as error:
        normalize("b08xyz1234")
    assert "Kindle" in str(error.value)


def test_Bで始まっても13桁ならISBNとして扱おうとする():
    # B から始まる10桁だけを ASIN とみなす
    with pytest.raises(InvalidIsbnError) as error:
        normalize("B123456789012")
    assert "Kindle" not in str(error.value)
