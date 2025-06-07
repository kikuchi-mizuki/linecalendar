import re
from datetime import datetime, timedelta, time
import pytz
import logging
from typing import Dict

logger = logging.getLogger(__name__)
JST = pytz.timezone('Asia/Tokyo')

def extract_datetime_from_message(message: str, operation_type: str = None) -> Dict:
    """
    メッセージから日時情報を抽出する
    """
    try:
        now = datetime.now(JST)
        logger.debug(f"[now] サーバー現在日時: {now}")
        # --- 日本語日付＋時刻範囲パターンを最優先で抽出 ---
        jp_date_time_range_match = re.search(r'(\d{1,2})月(\d{1,2})日[\s　]*(\d{1,2}):?(\d{2})[〜~～-](\d{1,2}):?(\d{2})', message)
        if jp_date_time_range_match:
            month = int(jp_date_time_range_match.group(1))
            day = int(jp_date_time_range_match.group(2))
            start_hour = int(jp_date_time_range_match.group(3))
            start_minute = int(jp_date_time_range_match.group(4))
            end_hour = int(jp_date_time_range_match.group(5))
            end_minute = int(jp_date_time_range_match.group(6))
            year = now.year
            if (month < now.month) or (month == now.month and day < now.day):
                year += 1
            start_time = JST.localize(datetime(year, month, day, start_hour, start_minute))
            end_time = JST.localize(datetime(year, month, day, end_hour, end_minute))
            if end_time <= start_time:
                end_time += timedelta(days=1)
            result = {'start_time': start_time, 'end_time': end_time, 'is_time_range': True}
            logger.debug(f"[datetime_extraction][HIT] 日本語日付＋時刻範囲: {jp_date_time_range_match.groups()} 入力メッセージ: {message}, 抽出結果: start={start_time}, end={end_time}")
            return result
        # ...（省略：他のパターンも必要に応じて追加可能）...
        return {'start_time': None, 'end_time': None, 'is_time_range': False}
    except Exception as e:
        logger.error(f"extract_datetime_from_message error: {str(e)}")
        return {'start_time': None, 'end_time': None, 'is_time_range': False} 