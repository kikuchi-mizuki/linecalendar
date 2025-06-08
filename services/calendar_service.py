from utils.logger import logger
# db_managerが必要な場合は下記を有効化
# from utils.db import db_manager
from calendar_operations import CalendarManager
from services.line_service import get_user_credentials
from datetime import datetime, time, timedelta

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

class CalendarManager:
    def __init__(self):
        self.credentials = None
        self.service = None

    def set_credentials(self, credentials):
        self.credentials = credentials
        self.service = self._initialize_service()

    def get_free_time_slots(self, date, min_duration=timedelta(minutes=30)):
        """指定日の空き時間を取得する"""
        # 当日の予定を取得
        events = self.get_events(date)
        # 空き時間を計算
        free_slots = []
        start_time = datetime.combine(date, time(9, 0))  # 9:00から開始
        end_time = datetime.combine(date, time(18, 0))   # 18:00で終了
        current_time = start_time
        for event in events:
            event_start = event['start'].get('dateTime', event['start'].get('date'))
            event_end = event['end'].get('dateTime', event['end'].get('date'))
            if event_start > current_time:
                free_slots.append((current_time, event_start))
            current_time = event_end
        if current_time < end_time:
            free_slots.append((current_time, end_time))
        # 最小時間未満の空き時間を除外
        free_slots = [(start, end) for start, end in free_slots if (end - start) >= min_duration]
        return free_slots

    def format_free_time_slots(self, free_slots):
        """空き時間を整形して返す"""
        if not free_slots:
            return "空き時間はありません。"
        msg = "🕒 空き時間\n\n"
        for start, end in free_slots:
            duration = end - start
            hours = duration.seconds // 3600
            minutes = (duration.seconds % 3600) // 60
            duration_str = f"{hours}時間{minutes}分" if hours > 0 else f"{minutes}分"
            msg += f"⏰ {start.strftime('%H:%M')}〜{end.strftime('%H:%M')}（{duration_str}）\n"
        return msg
