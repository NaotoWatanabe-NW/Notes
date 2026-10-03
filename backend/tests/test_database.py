"""既存の DB に後から足した列を反映する処理（add_missing_columns）のテスト。

本番の reading.db は実データが入っていて作り直せないので、
列を足したときはこの処理で ALTER TABLE する。
"""
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app.database import Base, add_missing_columns, configure_sqlite


@pytest.fixture
def old_engine():
    """books.genre がまだ無かったころの DB（1冊入っている）"""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    configure_sqlite(engine)
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO books (title, status, page, created_at, updated_at) "
                          "VALUES ('既存の本', 'unread', 0, '2026-09-26', '2026-09-26')"))
        conn.execute(text("ALTER TABLE books DROP COLUMN genre"))
    yield engine
    engine.dispose()


def _columns(engine, table):
    return {column["name"] for column in inspect(engine).get_columns(table)}


def test_無い列を足して既存の行は残す(old_engine):
    added = add_missing_columns(old_engine)

    assert added == ["books.genre"]
    assert "genre" in _columns(old_engine, "books")
    with old_engine.connect() as conn:
        rows = conn.execute(text("SELECT title, genre FROM books")).all()
    assert rows == [("既存の本", None)]


def test_二度目は何もしない(old_engine):
    add_missing_columns(old_engine)
    assert add_missing_columns(old_engine) == []


def test_列がそろっているDBでは何もしない(db_engine):
    assert add_missing_columns(db_engine) == []


def test_nullを許さない列は足さずに止まる(old_engine):
    # 既存の行に入れる値が無いので、黙って足すと壊れる
    with old_engine.begin() as conn:
        conn.execute(text("ALTER TABLE books DROP COLUMN title"))
    with pytest.raises(RuntimeError, match="books.title"):
        add_missing_columns(old_engine)
