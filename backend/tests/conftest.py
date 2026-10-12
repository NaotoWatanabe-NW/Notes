"""テスト共通の準備。

本番の reading.db を触らないよう、テストごとにメモリ上の空のDBを用意し、
FastAPI の get_db をそちらに差し替える。
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import booklookup
from app.database import Base, configure_sqlite, get_db
from app.main import app


@pytest.fixture(autouse=True)
def _isolated_reports_dir(tmp_path, monkeypatch):
    """読書レポートの本文はファイルなので、テストごとに別のディレクトリへ向ける。

    本番の Notes/reports/ を汚さないため。読み書きは実ファイルで行う
    （I/O がこの機能の本体なのでモックしない）。
    """
    monkeypatch.setenv("NOTES_REPORTS_DIR", str(tmp_path / "reports"))
    # テーマノートの定期更新は lifespan で始まる。テストは lifespan を動かさないが、
    # 万一動いても本番の DB を読みに行かないよう止めておく
    monkeypatch.setenv("NOTES_THEMES_WATCH", "0")


@pytest.fixture(autouse=True)
def _clear_search_cache():
    """検索結果のキャッシュはテストをまたいで残さない"""
    booklookup.clear_cache()
    yield
    booklookup.clear_cache()


@pytest.fixture
def db_engine():
    # sqlite:// はメモリ上のDB。StaticPool を指定しないと接続ごとに別のDBに
    # なってしまい、テストで入れたデータが見えなくなる。
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    configure_sqlite(engine)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def client(db_engine):
    TestingSessionLocal = sessionmaker(bind=db_engine, autoflush=False)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # with を付けない = lifespan を動かさない。本番エンジンで create_all を
    # 走らせないため。
    yield TestClient(app)
    app.dependency_overrides.clear()
