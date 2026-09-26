"""APIでやり取りするデータの形（入力チェックもここで行う）"""
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from . import isbn as isbn_util
from .models import Basis, BookSort, BookStatus, Distance, NoteKind, QuoteStyle, Recommend

# タグ名は前後の空白を落として扱う。空白だけのタグは作らせない
TagName = Annotated[str, Field(min_length=1, max_length=40)]

# BeforeValidator は「型チェックより先」に走る。ここでハイフンを落として13桁に
# 揃えてしまうので、「978-4-274-22629-8」のような入力も通るようになる。
Isbn = Annotated[str | None, BeforeValidator(isbn_util.normalize)]


def _reject_explicit_null(value, label: str):
    """PATCH で null を明示的に送られたときに 422 で弾く。

    項目を送らなければ「変更しない」、null を送れば「空にする」が基本だが、
    DB 側で NOT NULL の項目は空にできない。ここで弾かないと保存時に
    IntegrityError になり、原因の分かりにくいエラーがユーザーに返ってしまう。
    """
    if value is None:
        raise ValueError(f"{label}は空にできません")
    return value


# ---------------------------------------------------------------- 本

class BookBase(BaseModel):
    isbn: Isbn = None
    title: str = Field(min_length=1, max_length=255)
    author: str | None = Field(default=None, max_length=255)
    publisher: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=120)
    cover_url: str | None = Field(default=None, max_length=500)
    status: BookStatus = BookStatus.UNREAD
    rating: int | None = Field(default=None, ge=1, le=5)
    recommend: Recommend | None = None
    page: int = Field(default=0, ge=0)
    total: int | None = Field(default=None, gt=0)
    started_on: date | None = None
    finished_on: date | None = None
    tags: list[TagName] = Field(default_factory=list, max_length=20)


class BookCreate(BookBase):
    """登録するときに受け取る形"""
    # 知らない項目が来たら弾く。黙って無視すると、項目名を打ち間違えたときに
    # 「200が返るのに保存されない」という分かりにくい不具合になる。
    model_config = ConfigDict(extra="forbid")


class BookUpdate(BaseModel):
    """更新するときに受け取る形。すべて任意で、送った項目だけ更新する"""
    model_config = ConfigDict(extra="forbid")

    isbn: Isbn = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    author: str | None = Field(default=None, max_length=255)
    publisher: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=120)
    cover_url: str | None = Field(default=None, max_length=500)
    status: BookStatus | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    recommend: Recommend | None = None
    page: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, gt=0)
    started_on: date | None = None
    finished_on: date | None = None
    report_md: str | None = None
    tags: list[TagName] | None = Field(default=None, max_length=20)

    @field_validator("title")
    @classmethod
    def _title_not_null(cls, value):
        return _reject_explicit_null(value, "タイトル")

    @field_validator("status")
    @classmethod
    def _status_not_null(cls, value):
        return _reject_explicit_null(value, "状態")

    @field_validator("page")
    @classmethod
    def _page_not_null(cls, value):
        return _reject_explicit_null(value, "読んだページ")


class Reading(BaseModel):
    """1回ぶんの「読み終えた」記録"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    finished_on: date


class BookRead(BookBase):
    """返すときの形。DBが付けたidや、画面で使う集計値も含める"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    # 読んだ割合（％）。総ページが未設定の本は null
    progress: int | None = None
    # この本に紐づく引用・メモの件数（一覧のメタ表示に使う）
    note_count: int = 0
    # 読み終えた回数。再読するたびに増える
    read_count: int = 0
    # レポートを書いたかどうかだけを一覧に返す。本文は詳細で取る
    has_report: bool = False
    created_at: datetime
    updated_at: datetime

    @field_validator("tags", mode="before")
    @classmethod
    def _tags_to_names(cls, value):
        """DBのTagオブジェクトの一覧を、名前の一覧に均す"""
        if isinstance(value, list):
            return [t.name if hasattr(t, "name") else t for t in value]
        return value


class BookDetail(BookRead):
    """本の詳細。レポート本文と読了の履歴まで含める"""
    report_md: str | None = None
    readings: list[Reading] = Field(default_factory=list)


# ---------------------------------------------------------------- ノート

class NoteBase(BaseModel):
    kind: NoteKind
    page: int | None = Field(default=None, gt=0)
    # 引用なら抜き書き、メモなら自分の考え
    text: str = Field(min_length=1)
    # 引用に添える自分のひとこと
    memo: str | None = None


class NoteCreate(NoteBase):
    model_config = ConfigDict(extra="forbid")


class NoteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: NoteKind | None = None
    page: int | None = Field(default=None, gt=0)
    text: str | None = Field(default=None, min_length=1)
    memo: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind_not_null(cls, value):
        return _reject_explicit_null(value, "種別")

    @field_validator("text")
    @classmethod
    def _text_not_null(cls, value):
        return _reject_explicit_null(value, "本文")


class NoteBook(BaseModel):
    """ノート一覧に添える、出典の本の情報"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    author: str | None = None
    cover_url: str | None = None


class NoteRead(NoteBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    book_id: int
    created_at: datetime
    updated_at: datetime


class NoteWithBook(NoteRead):
    """「メモ・引用」ビュー用。どの本のノートかが分かる形"""
    book: NoteBook


# ---------------------------------------------------------------- 設定

class SettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    yearly_goal: int
    sort: BookSort
    quote_style: QuoteStyle


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    yearly_goal: int | None = Field(default=None, ge=1, le=1000)
    sort: BookSort | None = None
    quote_style: QuoteStyle | None = None


# ---------------------------------------------------------------- 振り返り

class ReviewPeriod(BaseModel):
    """振り返りの期間リスト1行ぶん"""
    period: str   # "2026" や "2026-09"
    label: str    # 画面に出す名前
    sub: str      # 「今月」「1月〜9月」などの補足
    count: int    # その期間に読み終えた冊数


class ReviewBar(BaseModel):
    """棒グラフ1本ぶん"""
    label: str
    value: int
    current: bool = False


class ReviewBook(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    author: str | None = None
    cover_url: str | None = None


class ReviewQuote(BaseModel):
    """「いちばん残した言葉」"""
    text: str
    book_title: str
    page: int | None = None


class Review(BaseModel):
    """ある期間の読書のまとめ"""
    label: str
    finished_count: int
    yearly_goal: int | None = None
    remaining_to_goal: int | None = None
    pages: int
    note_count: int
    top_category: str | None = None
    bars: list[ReviewBar]
    books: list[ReviewBook]
    top_quote: ReviewQuote | None = None


# ---------------------------------------------------------------- タグ

class TagCount(BaseModel):
    """タグと、それが付いている本の冊数"""
    name: str
    count: int


# ---------------------------------------------------------------- おすすめ

class SuggestionBase(BaseModel):
    """「次に読む本」の候補1冊ぶん"""
    title: str = Field(min_length=1, max_length=255)
    author: str | None = Field(default=None, max_length=255)
    isbn: Isbn = None
    cover_url: str | None = Field(default=None, max_length=500)
    # なぜこの本を出したか（引用・メモ / 評価 / 分野）
    basis: Basis
    # 読んできた本との距離（近い / 少し離れた）
    distance: Distance
    # 理由は一言で
    reason: str = Field(min_length=1, max_length=200)


class SuggestionWrite(SuggestionBase):
    """設定するときに受け取る形"""
    model_config = ConfigDict(extra="forbid")


class Suggestion(SuggestionBase):
    """返すときの形"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    # 積読に追加済みなら、その本の id
    added_book_id: int | None = None


class SuggestionSet(BaseModel):
    """おすすめ画面に渡すひとまとまり"""
    book_id: int
    book_title: str
    # 読み終えるまでにかかった日数（分かるときだけ）
    days: int | None = None
    note_count: int
    # そもそも候補を設定してあるか。false なら「まだ検索していません」を出す
    configured: bool
    suggestions: list[Suggestion]
    # 画面の下に出す、根拠の要約
    summary: str
    # まだ次のページがあるか（「出し直す」で次の3冊を出せるか）
    has_more: bool = False
