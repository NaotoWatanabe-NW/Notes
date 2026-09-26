"""アプリ設定のAPI（読書目標・並び順・引用の書体）"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import SettingsRead, SettingsUpdate
from ..settings_store import get_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsRead)
def read_settings(db: Session = Depends(get_db)):
    return get_settings(db)


@router.patch("", response_model=SettingsRead)
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    """送った項目だけ更新する"""
    settings = get_settings(db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(settings, key, value)
    db.commit()
    db.refresh(settings)
    return settings
