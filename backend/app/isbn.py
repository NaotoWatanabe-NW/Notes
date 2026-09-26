"""ISBN の正規化。

入力欄には「978-4-274-22629-8」のようにハイフン付きで貼られることも、
古い本で10桁の ISBN-10 が書かれていることもある。
DB には常に「ハイフンなしの13桁」で入れたいので、ここで形を揃える。
Step 3 の ISBN 検索でも同じ関数を使う。
"""
import re

# ハイフンに見える文字はいくつかあるので、まとめて除去する
_SEPARATORS = re.compile(r"[\s\-‐‑‒–—−]")


# Kindle 版などの ASIN。B で始まる英数字10桁で、ISBN を持たない
_KINDLE_ASIN = re.compile(r"B[0-9A-Z]{9}")


class InvalidIsbnError(ValueError):
    """ISBN として受け付けられない文字列"""


def _isbn13_check_digit(first12: str) -> str:
    """ISBN-13 の末尾1桁を計算する（左から重み 1,3,1,3,... を掛けて足す）"""
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def _isbn10_is_valid(isbn10: str) -> bool:
    """ISBN-10 の検査（左から重み 10,9,...,1、末尾の X は 10 として扱う）"""
    total = 0
    for i, ch in enumerate(isbn10):
        if ch == "X" and i == 9:
            value = 10
        elif ch.isdigit():
            value = int(ch)
        else:
            return False
        total += value * (10 - i)
    return total % 11 == 0


def _isbn10_to_13(isbn10: str) -> str:
    """ISBN-10 を ISBN-13 に変換する。

    先頭に 978 を付け、元の末尾のチェックディジットは捨てて計算し直す。
    """
    body = "978" + isbn10[:9]
    return body + _isbn13_check_digit(body)


def normalize(raw: str | None) -> str | None:
    """ISBN を「ハイフンなしの13桁」に揃える。

    Amazon の ASIN も受け付ける。**紙の本の ASIN は ISBN-10 と同じ値**なので、
    そのまま10桁として扱えば通る。Kindle 版の ASIN（B から始まる）は ISBN を
    持たないので、そうと分かる形で断る。

    空文字や空白だけのときは None を返す。これをしないと、空文字が
    そのまま保存されて2冊目の空文字が UNIQUE 制約に引っかかってしまう。
    """
    if raw is None:
        return None

    cleaned = _SEPARATORS.sub("", raw).upper()
    if not cleaned:
        return None

    if _KINDLE_ASIN.fullmatch(cleaned):
        raise InvalidIsbnError(
            "Kindle版のASINには ISBN がないので調べられません。"
            "紙の本のASIN（数字10桁）か ISBN を入れてください"
        )

    if len(cleaned) == 10:
        if not _isbn10_is_valid(cleaned):
            raise InvalidIsbnError("ISBN-10 のチェックディジットが合いません")
        cleaned = _isbn10_to_13(cleaned)

    if len(cleaned) != 13 or not cleaned.isdigit():
        raise InvalidIsbnError("ISBN は10桁または13桁の数字で入力してください")

    if cleaned[12] != _isbn13_check_digit(cleaned[:12]):
        raise InvalidIsbnError("ISBN-13 のチェックディジットが合いません")

    return cleaned
