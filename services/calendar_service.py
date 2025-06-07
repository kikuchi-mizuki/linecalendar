from utils.logger import logger
# db_managerが必要な場合は下記を有効化
# from utils.db import db_manager
from calendar_operations import CalendarManager
from services.line_service import get_user_credentials

def get_calendar_manager(user_id: str):
    try:
        credentials = get_user_credentials(user_id)
        if not credentials:
            logger.info(f"ユーザー {user_id} の認証情報が見つかりません。認証が必要です。")
            raise ValueError("Google認証情報が見つかりません")
        return CalendarManager(credentials)
    except Exception as e:
        logger.error(f"カレンダーマネージャーの初期化に失敗: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise
