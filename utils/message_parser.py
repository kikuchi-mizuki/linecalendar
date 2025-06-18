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
        
        # 日付＋番号＋変更のパターン（例：6/19 2 変更）
        update_pattern = r'(\d{1,2})[\/月](\d{1,2})日?\s*(\d+)\s*(番)?\s*(変更|修正|更新|編集)'
        update_match = re.search(update_pattern, message)
        if update_match:
            logger.debug(f"[extract_datetime_from_message] update_pattern matched: {update_match.groups()} message={message}")
            month = int(update_match.group(1))
            day = int(update_match.group(2))
            update_index = int(update_match.group(3))
            year = now.year
            if (month < now.month) or (month == now.month and day < now.day):
                year += 1
            start_time = JST.localize(datetime(year, month, day, 0, 0, 0))
            end_time = JST.localize(datetime(year, month, day, 23, 59, 59, 999999))
            lines = message.splitlines()
            if len(lines) >= 2:
                new_time_info = extract_datetime_from_message(lines[1])
                logger.debug(f"[extract_datetime_from_message] new_time_info from 2nd line: {new_time_info} line={lines[1]}")
                if new_time_info.get('start_time') and new_time_info.get('end_time'):
                    return {
                        'start_time': start_time,
                        'end_time': end_time,
                        'new_start_time': new_time_info['start_time'],
                        'new_end_time': new_time_info['end_time'],
                        'update_index': update_index,
                        'is_time_range': True
                    }
            return {
                'start_time': start_time,
                'end_time': end_time,
                'update_index': update_index,
                'is_time_range': True
            }
        
        # 時間範囲のパターン（例：14:00〜15:00）
        time_range_pattern = r'(\d{1,2}):(\d{2})[〜~～-](\d{1,2}):(\d{2})'
        time_range_match = re.search(time_range_pattern, message)
        if time_range_match:
            logger.debug(f"[extract_datetime_from_message] time_range_pattern matched: {time_range_match.groups()} message={message}")
            start_hour = int(time_range_match.group(1))
            start_minute = int(time_range_match.group(2))
            end_hour = int(time_range_match.group(3))
            end_minute = int(time_range_match.group(4))
            date_match = re.search(r'(\d{1,2})[\/月](\d{1,2})日?', message)
            if date_match:
                month = int(date_match.group(1))
                day = int(date_match.group(2))
                year = now.year
                if (month < now.month) or (month == now.month and day < now.day):
                    year += 1
                start_time = JST.localize(datetime(year, month, day, start_hour, start_minute))
                end_time = JST.localize(datetime(year, month, day, end_hour, end_minute))
                return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True}
        
        # 「今日からn週間」
        m = re.search(r'今日から(\d+)週間', message)
        if m:
            logger.debug(f"[extract_datetime_from_message] 今日からn週間 matched: {m.groups()} message={message}")
            n = int(m.group(1))
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = (start_time + timedelta(days=7*n-1)).replace(hour=23, minute=59, second=59, microsecond=999999)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True}
        # 「今日から1週間」
        if re.search(r'今日から1週間', message):
            logger.debug(f"[extract_datetime_from_message] 今日から1週間 matched: message={message}")
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = (start_time + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True}
        # 「今週」
        if re.search(r'今週', message):
            logger.debug(f"[extract_datetime_from_message] 今週 matched: message={message}")
            start_time = now - timedelta(days=now.weekday())
            start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=999999)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True}
        # 「来週」
        if re.search(r'来週', message):
            logger.debug(f"[extract_datetime_from_message] 来週 matched: message={message}")
            start_time = now - timedelta(days=now.weekday()) + timedelta(days=7)
            start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=999999)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True}
        # 「6/18 1」や「6月18日1時」
        m = re.search(r'(\d{1,2})[\/月](\d{1,2})[日\s　]*(\d{1,2})時?', message)
        if m:
            logger.debug(f"[extract_datetime_from_message] 月日＋時刻パターン matched: {m.groups()} message={message}")
            month = int(m.group(1))
            day = int(m.group(2))
            hour = int(m.group(3))
            year = now.year
            if (month < now.month) or (month == now.month and day < now.day):
                year += 1
            start_time = JST.localize(datetime(year, month, day, hour, 0, 0))
            end_time = start_time + timedelta(hours=1)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': False}
        # --- 月日指定パターンを最優先で抽出 ---
        m = re.search(r'(\d{1,2})[\/月](\d{1,2})(?:日)?(?=\D|$)', message)
        if m:
            logger.debug(f"[extract_datetime_from_message] 月日パターン matched: {m.groups()} message={message}")
            month = int(m.group(1))
            day = int(m.group(2))
            year = now.year
            # タイムゾーンなしで一旦生成
            this_year_date_naive = datetime(year, month, day, 0, 0, 0)
            today_naive = now.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
            # 今日より前なら来年扱い、今日以降は今年扱い
            if this_year_date_naive < today_naive:
                year += 1
            start_time = JST.localize(datetime(year, month, day, 0, 0, 0))
            end_time = JST.localize(datetime(year, month, day, 23, 59, 59, 999999))
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True}
        # --- 日本語日付＋時刻範囲パターンを最優先で抽出 ---
        jp_date_time_range_match = re.search(r'(\d{1,2})月(\d{1,2})日[\s　]*(\d{1,2}):?(\d{2})[〜~～-](\d{1,2}):?(\d{2})', message)
        if jp_date_time_range_match:
            logger.debug(f"[extract_datetime_from_message] 日本語日付＋時刻範囲パターン matched: {jp_date_time_range_match.groups()} message={message}")
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
        logger.debug(f"[extract_datetime_from_message] no pattern matched: message={message}")
        return {'start_time': None, 'end_time': None, 'is_time_range': False}
    except Exception as e:
        logger.error(f"extract_datetime_from_message error: {str(e)}")
        return {'start_time': None, 'end_time': None, 'is_time_range': False} 