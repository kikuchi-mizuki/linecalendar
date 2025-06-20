import logging
# db_managerが必要な場合は下記を有効化
# from utils.db import db_manager
from calendar_operations import CalendarManager
from services.line_service import get_user_credentials
from datetime import datetime, time, timedelta
from googleapiclient.discovery import build
from pytz import timezone

logger = logging.getLogger('app')

def get_calendar_manager(user_id: str):
    credentials = get_user_credentials(user_id)
    if not credentials:
        logger.info(f"ユーザー {user_id} の認証情報が見つかりません。認証が必要です。")
        raise ValueError("Google認証情報が見つかりません")
    return CalendarManager(credentials)
