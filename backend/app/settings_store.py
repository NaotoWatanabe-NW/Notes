"""アプリ設定の読み書き。

設定は1行しか無いので、無ければ既定値で作ってから返す。
"""
from sqlalchemy.orm import Session

from .models import Settings

SETTINGS_ID = 1


def get_settings(db: Session) -> Settings:
    settings = db.get(Settings, SETTINGS_ID)
    if settings is None:
        settings = Settings(id=SETTINGS_ID)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings
