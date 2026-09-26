"""時刻の扱いを1箇所にまとめる。

このアプリは日本国内からしか使わない個人用なので、日時はすべて JST で揃える。
DB には naive（タイムゾーン情報なし）で入れるため、SQLite を直接覗いても
そのまま日本時間として読める。
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def now_jst() -> datetime:
    """現在時刻（JST、タイムゾーン情報は落とす）"""
    return datetime.now(JST).replace(tzinfo=None)


def today_jst() -> date:
    """今日の日付（JST）"""
    return datetime.now(JST).date()
