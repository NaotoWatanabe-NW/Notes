"""DBのテーブル定義（データベース側の形）"""
import enum
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    Enum,
    ForeignKey,
    LargeBinary,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .timeutil import now_jst


# 本とタグの結び付き。タグ自体に属性は無いので、関連テーブルだけ用意する
book_tags = Table(
    "book_tags",
    Base.metadata,
    Column("book_id", ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class BookStatus(str, enum.Enum):
    UNREAD = "unread"      # 積読
    READING = "reading"    # 読書中
    FINISHED = "finished"  # 読了


class Genre(str, enum.Enum):
    """本のカテゴリ（本棚の絞り込み用の大きな分類）。

    細かい分野はタグで持つ。`Book.category`（国会図書館の件名）とは別物。
    """
    NOVEL = "novel"        # 小説
    BUSINESS = "business"  # ビジネス・実用
    ESSAY = "essay"        # エッセイ
    ACADEMIC = "academic"  # 学術
    MAGAZINE = "magazine"  # 雑誌
    OTHER = "other"        # その他


class Recommend(str, enum.Enum):
    """読み終えた本を人にすすめたいか（デザインの「おすすめ度」）"""
    STRONG = "strong"  # 人にすすめたい
    SOME = "some"      # 人を選ぶ
    SELF = "self"      # 自分用


class Basis(str, enum.Enum):
    """なぜこの本を薦めたか（デザイン #5a の根拠トグル）"""
    NOTE = "note"      # 引用・メモから
    RATING = "rating"  # 評価から
    TAG = "tag"        # 分野から


class Distance(str, enum.Enum):
    """読んできた本との距離"""
    NEAR = "near"  # 近い本
    FAR = "far"    # 少し離れた本


class NoteKind(str, enum.Enum):
    QUOTE = "quote"  # 本文からの引用
    MEMO = "memo"    # 自分の考え


def _values_enum(enum_class, name: str) -> Enum:
    """enum の「名前」ではなく「値」をDBに保存させる。

    既定のままだと DB に 'READING'、APIに 'reading' が出て見比べたときに
    食い違うため。
    """
    return Enum(
        enum_class,
        values_callable=lambda cls: [member.value for member in cls],
        native_enum=False,
        name=name,
    )


class Book(Base):
    __tablename__ = "books"
    __table_args__ = (
        # DB側でも評価は1〜5しか入らないようにする
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_rating_range"),
        # 読んだページ・総ページは負にならない
        CheckConstraint("page >= 0", name="ck_page_positive"),
        CheckConstraint("total IS NULL OR total > 0", name="ck_total_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    isbn: Mapped[str | None] = mapped_column(String(13), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str | None] = mapped_column(String(255))
    publisher: Mapped[str | None] = mapped_column(String(255))
    # 「よく読む分野」の集計に使う。ISBN検索のときに国会図書館の件名から入れる
    category: Mapped[str | None] = mapped_column(String(120))
    # カテゴリ。列は後から足したので null を許すが、入れるときは必ず値を入れる（既定はその他）
    genre: Mapped[Genre | None] = mapped_column(
        _values_enum(Genre, "genre"), default=Genre.OTHER
    )
    cover_url: Mapped[str | None] = mapped_column(String(500))

    status: Mapped[BookStatus] = mapped_column(
        _values_enum(BookStatus, "book_status"), default=BookStatus.UNREAD
    )
    rating: Mapped[int | None]
    recommend: Mapped[Recommend | None] = mapped_column(
        _values_enum(Recommend, "recommend")
    )

    # 進捗。page は読んだところまで、total は本の総ページ数
    page: Mapped[int] = mapped_column(default=0)
    total: Mapped[int | None] = mapped_column(default=None)

    started_on: Mapped[date | None]
    finished_on: Mapped[date | None]

    # 読書レポートの本文（Markdown）は **ファイルが正**（2026-10-11 に移管）。
    # app/report_store.py が reports/<book_id>-<タイトル>.md を読み書きする。
    # 移管前に本文を入れていた report_md 列は、凍結コピーとして残したあと
    # scripts/drop_unused_columns.py で DB から消す（docs/design/0004-drop-unused-columns.md）。
    # 消す前の DB に列が残っていても、ここでマップしないのでアプリは読み書きしない。
    # 理由と境界: Storage/_vault/document-storage-policy.md

    # 時刻は SQLite の CURRENT_TIMESTAMP（UTC）ではなく Python 側の JST を使う。
    # そうしないと finished_on（JST）と9時間ずれる。
    created_at: Mapped[datetime] = mapped_column(default=now_jst)
    updated_at: Mapped[datetime] = mapped_column(default=now_jst, onupdate=now_jst)

    # 本を削除したら、その本のノートも一緒に消す。
    # delete-orphan は「本との繋がりが切れたノートも消す」という意味。
    notes: Mapped[list["Note"]] = relationship(
        back_populates="book",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    # 読み終えた記録。再読するたびに1行増える
    readings: Mapped[list["Reading"]] = relationship(
        back_populates="book",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Reading.finished_on.desc(), Reading.id.desc()",
    )
    tags: Mapped[list["Tag"]] = relationship(
        secondary=book_tags,
        back_populates="books",
        order_by="Tag.name",
    )
    # この本を読み終えたときに出す「次に読む本」
    suggestions: Mapped[list["Suggestion"]] = relationship(
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Suggestion.position, Suggestion.id",
        foreign_keys="Suggestion.book_id",
    )

    @property
    def read_count(self) -> int:
        """読み終えた回数"""
        return len(self.readings)

    @property
    def progress(self) -> int | None:
        """読んだ割合（％）。総ページが分からない本は None"""
        if not self.total:
            return None
        return min(100, round(self.page * 100 / self.total))


class Note(Base):
    """1冊の本に対する引用・メモ。1冊に何件でも書ける"""
    __tablename__ = "notes"
    __table_args__ = (CheckConstraint("page IS NULL OR page > 0", name="ck_note_page"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # ondelete="CASCADE" は DB 側の設定。SQLite では PRAGMA foreign_keys=ON が
    # 有効でないと効かないので、database.py で有効にしている
    book_id: Mapped[int] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[NoteKind] = mapped_column(_values_enum(NoteKind, "note_kind"))
    page: Mapped[int | None]
    # 引用なら本文からの抜き書き、メモなら自分の考え
    text: Mapped[str] = mapped_column(Text)
    # 引用に添える自分のひとこと（引用のときだけ使う）
    memo: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now_jst)
    updated_at: Mapped[datetime] = mapped_column(default=now_jst, onupdate=now_jst)

    book: Mapped[Book] = relationship(back_populates="notes")


class BookCover(Base):
    """自分で入れた表紙の画像。

    国会図書館に書影が無い本（洋書や文庫の分冊など）もあるので、
    手で入れられるようにしてある。
    ファイルではなく**DBに入れる**のは、バックアップが reading.db 1つで
    済むという最初の方針を守るため。保存前に縮めるので大きくならない。
    """
    __tablename__ = "book_covers"

    book_id: Mapped[int] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[bytes] = mapped_column(LargeBinary)
    content_type: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(default=now_jst, onupdate=now_jst)


class Reading(Base):
    """1回ぶんの「読み終えた」記録。再読すると増えていく"""
    __tablename__ = "readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), index=True
    )
    finished_on: Mapped[date]
    created_at: Mapped[datetime] = mapped_column(default=now_jst)

    book: Mapped[Book] = relationship(back_populates="readings")


class Suggestion(Base):
    """「次に読む本」の候補。

    その場で計算せず、**あらかじめ本ごとに設定しておいたもの**を出す。
    外部APIを叩かないので速く、理由も人の言葉で書ける。
    """
    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # どの本を読み終えたときに出すか
    book_id: Mapped[int] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str | None] = mapped_column(String(255))
    isbn: Mapped[str | None] = mapped_column(String(13))
    cover_url: Mapped[str | None] = mapped_column(String(500))
    basis: Mapped[Basis] = mapped_column(_values_enum(Basis, "basis"))
    distance: Mapped[Distance] = mapped_column(_values_enum(Distance, "distance"))
    # 理由は一言で（デザインの指定）
    reason: Mapped[str] = mapped_column(Text)
    # おすすめ一覧（デザイン J）で使う。カテゴリで絞り込み、詳細に出版社・ページ数を出す
    genre: Mapped[Genre | None] = mapped_column(_values_enum(Genre, "genre"))
    publisher: Mapped[str | None] = mapped_column(String(255))
    total: Mapped[int | None]
    # 画面に出す順番
    position: Mapped[int] = mapped_column(default=0)
    # 積読に追加したら、その本の id を控える（開き直しても分かるように）
    added_book_id: Mapped[int | None] = mapped_column(
        ForeignKey("books.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(default=now_jst)


class Tag(Base):
    """本に付ける分類。名前は重複させない"""
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("name", name="uq_tag_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40))

    books: Mapped[list[Book]] = relationship(secondary=book_tags, back_populates="tags")


class DismissedBook(Base):
    """「興味なし」にした本。以後のおすすめから外す。

    おすすめの候補はまだ本棚に無い本なので、本のidではなく ISBN で覚える。
    """
    __tablename__ = "dismissed_books"
    __table_args__ = (UniqueConstraint("isbn", name="uq_dismissed_isbn"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    isbn: Mapped[str] = mapped_column(String(13))
    created_at: Mapped[datetime] = mapped_column(default=now_jst)


class Topic(Base):
    """キーワードごとのおすすめのまとまり（「ゲーム理論」「統計」など）。

    「次に読む本」（Suggestion）が本棚の1冊に紐づくのに対し、こちらは
    **キーワードに紐づく**。本棚の本は選書の手がかりにするだけ。
    """
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("keyword", name="uq_topic_keyword"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    keyword: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(default=now_jst)
    updated_at: Mapped[datetime] = mapped_column(default=now_jst, onupdate=now_jst)

    suggestions: Mapped[list["TopicSuggestion"]] = relationship(
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TopicSuggestion.position, TopicSuggestion.id",
    )


class TopicSuggestion(Base):
    """キーワードのおすすめ1冊。中身は Suggestion とほぼ同じ"""
    __tablename__ = "topic_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str | None] = mapped_column(String(255))
    isbn: Mapped[str | None] = mapped_column(String(13))
    cover_url: Mapped[str | None] = mapped_column(String(500))
    distance: Mapped[Distance] = mapped_column(_values_enum(Distance, "distance"))
    reason: Mapped[str] = mapped_column(Text)
    # おすすめ一覧（デザイン J）で使う。Suggestion と同じ
    genre: Mapped[Genre | None] = mapped_column(_values_enum(Genre, "genre"))
    publisher: Mapped[str | None] = mapped_column(String(255))
    total: Mapped[int | None]
    # 手がかりにした本棚の本（「『〇〇』より一段深く」の〇〇）。無ければ null
    from_book_id: Mapped[int | None] = mapped_column(
        ForeignKey("books.id", ondelete="SET NULL")
    )
    position: Mapped[int] = mapped_column(default=0)
    # 積読に追加したら、その本の id を控える
    added_book_id: Mapped[int | None] = mapped_column(
        ForeignKey("books.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(default=now_jst)


class BookSort(str, enum.Enum):
    """本棚の並び順（設定画面で選ぶ）"""
    RECENT = "recent"      # 追加順
    TITLE = "title"        # 書名
    PROGRESS = "progress"  # 進捗


class QuoteStyle(str, enum.Enum):
    ITALIC = "italic"
    PLAIN = "plain"


class Settings(Base):
    """アプリ全体の設定。1行だけ使う（id は常に 1）"""
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    yearly_goal: Mapped[int] = mapped_column(default=50)
    sort: Mapped[BookSort] = mapped_column(
        _values_enum(BookSort, "book_sort"), default=BookSort.RECENT
    )
    quote_style: Mapped[QuoteStyle] = mapped_column(
        _values_enum(QuoteStyle, "quote_style"), default=QuoteStyle.ITALIC
    )
    updated_at: Mapped[datetime] = mapped_column(default=now_jst, onupdate=now_jst)
