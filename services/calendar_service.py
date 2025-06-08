from utils.logger import logger
# db_managerが必要な場合は下記を有効化
# from utils.db import db_manager
from calendar_operations import CalendarManager
from services.line_service import get_user_credentials
from datetime import datetime, time, timedelta
from googleapiclient.discovery import build

def get_calendar_manager(user_id: str):
    try:
        credentials = get_user_credentials(user_id)
        if not credentials:
            logger.info(f"ユーザー {user_id} の認証情報が見つかりません。認証が必要です。")
            raise ValueError("Google認証情報が見つかりません")
        calendar_manager = CalendarManager()
        calendar_manager.set_credentials(credentials)
        return calendar_manager
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

    def _initialize_service(self):
        return build('calendar', 'v3', credentials=self.credentials)

    def get_free_time_slots(self, date, min_duration=timedelta(minutes=30)):
        """指定日の空き時間を取得する"""
        events = self.get_events(date)
        free_slots = []
        start_time = datetime.combine(date, time(9, 0))  # 9:00から開始
        end_time = datetime.combine(date, time(18, 0))   # 18:00で終了
        current_time = start_time
        for event in events:
            event_start = event['start']  # すでにdatetime型
            event_end = event['end']      # すでにdatetime型
            if event_start > current_time:
                free_slots.append((current_time, event_start))
            current_time = max(current_time, event_end)
        if current_time < end_time:
            free_slots.append((current_time, end_time))
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

    def get_events(self, date):
        """
        指定日の予定をGoogleカレンダーから取得する
        """
        start_of_day = datetime.combine(date, time(0, 0)).isoformat() + 'Z'
        end_of_day = datetime.combine(date, time(23, 59, 59)).isoformat() + 'Z'
        events_result = self.service.events().list(
            calendarId='primary',
            timeMin=start_of_day,
            timeMax=end_of_day,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        # 必要に応じてstart/endをdatetime型に変換
        for event in events:
            if 'dateTime' in event['start']:
                event['start'] = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00'))
            else:
                event['start'] = datetime.fromisoformat(event['start']['date'])
            if 'dateTime' in event['end']:
                event['end'] = datetime.fromisoformat(event['end']['dateTime'].replace('Z', '+00:00'))
            else:
                event['end'] = datetime.fromisoformat(event['end']['date'])
        return events
