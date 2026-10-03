"""データベースへの接続を担当するファイル"""
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# backend フォルダに reading.db というファイルができる
DATABASE_URL = "sqlite:///./reading.db"

# SQLite を FastAPI で使うときのおまじない（複数スレッドからの利用を許可）
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False)


def configure_sqlite(target_engine) -> None:
    """SQLite の接続ごとに必要な設定を入れる。

    - journal_mode=WAL: 読み書きが同時に起きてもブロックしにくくなる。
      Step 5 で「次に読む本の提案」を裏側で書き込むときに効いてくる。
    - foreign_keys=ON: SQLite は外部キー制約が既定で無効。
      Step 4 の Note → Book の紐づけを効かせるために明示的に有効化する。

    テスト用に別のエンジンを作るときも同じ設定を使いたいので、関数にしてある。
    """

    @event.listens_for(target_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


configure_sqlite(engine)


class Base(DeclarativeBase):
    """すべてのテーブル定義の親クラス"""


def add_missing_columns(target_engine) -> list[str]:
    """モデルにあって DB に無い列を足す。足した列を「テーブル.列」で返す。

    create_all は**無いテーブル**しか作らないので、既存のテーブルに列を足しても
    DB には反映されない。実データが入っていて reading.db を作り直せないため、
    SQLite がその場でできる ADD COLUMN だけをここで行う。
    足せるのは null を許す列だけ（既存の行に入れる値が無いため）。
    列の型変更・削除が要るようになったら Alembic を入れる。
    """
    added = []
    with target_engine.begin() as conn:
        existing_tables = set(inspect(conn).get_table_names())
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all が作る
            have = {column["name"] for column in inspect(conn).get_columns(table.name)}
            for column in table.columns:
                if column.name in have:
                    continue
                if not column.nullable:
                    raise RuntimeError(
                        f"{table.name}.{column.name} は null を許さないので自動では足せません"
                    )
                ddl = column.type.compile(dialect=conn.dialect)
                conn.exec_driver_sql(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl}'
                )
                added.append(f"{table.name}.{column.name}")
    return added


def get_db():
    """リクエストごとにDBセッションを渡し、終わったら必ず閉じる"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
