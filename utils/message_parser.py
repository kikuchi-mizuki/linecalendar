import re
from datetime import datetime, timedelta, time
import pytz
import logging
from typing import Dict, Optional
from message_parser import normalize_text

# ロガーの設定
logger = logging.getLogger("app")
logger.setLevel(logging.DEBUG)

# 既存のハンドラーがない場合のみ追加
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

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
        # --- 3個以上の複数日指定パターンを最優先で抽出（例：6/21と6/22と6/23の予定） ---
        multiple_dates_all_pattern = r'((?:\d{1,2}[\/月]\d{1,2}(?:日)?)(?:\s*と\s*\d{1,2}[\/月]\d{1,2}(?:日)?)+)'
        multiple_dates_all_match = re.search(multiple_dates_all_pattern, message)
        if multiple_dates_all_match:
            logger.debug(f"[DEBUG] 複数日(3個以上)パターン message={message} match={multiple_dates_all_match.group(1)}")
            date_strs = re.findall(r'(\d{1,2})[\/月](\d{1,2})(?:日)?', multiple_dates_all_match.group(1))
            now = datetime.now(JST)
            year = now.year
            date_objs = []
            for month_str, day_str in date_strs:
                month = int(month_str)
                day = int(day_str)
                this_year_date_naive = datetime(year, month, day, 0, 0, 0)
                today_naive = now.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
                # 今日より前なら翌年
                if this_year_date_naive < today_naive:
                    date_obj = JST.localize(datetime(year+1, month, day, 0, 0, 0))
                else:
                    date_obj = JST.localize(datetime(year, month, day, 0, 0, 0))
                date_objs.append(date_obj)
            # 最小日付と最大日付を範囲として返す
            start_time = min(date_objs)
            end_time = max(date_objs).replace(hour=23, minute=59, second=59, microsecond=999999)
            logger.debug(f"[DEBUG] 複数日(3個以上)パターン return: start_time={start_time}, end_time={end_time}")
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True}
        # --- 複数日指定パターン（2個） ---
        multiple_dates_pattern = r'(\d{1,2})[\/月](\d{1,2})(?:日)?\s*と\s*(\d{1,2})[\/月](\d{1,2})(?:日)?'
        multiple_dates_match = re.search(multiple_dates_pattern, message)
        if multiple_dates_match:
            logger.debug(f"[DEBUG] 複数日パターン message={message} groups={multiple_dates_match.groups()}")
            month1 = int(multiple_dates_match.group(1))
            day1 = int(multiple_dates_match.group(2))
            month2 = int(multiple_dates_match.group(3))
            day2 = int(multiple_dates_match.group(4))
            year = now.year
            
            # 最初の日付の年を決定
            this_year_date1_naive = datetime(year, month1, day1, 0, 0, 0)
            today_naive = now.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
            if this_year_date1_naive < today_naive:
                year += 1
            
            # 2番目の日付の年を決定（最初の日付より前なら翌年）
            this_year_date2_naive = datetime(year, month2, day2, 0, 0, 0)
            this_year_date1_naive = datetime(year, month1, day1, 0, 0, 0)
            if this_year_date2_naive < this_year_date1_naive:
                year += 1
            
            start_time = JST.localize(datetime(year, month1, day1, 0, 0, 0))
            end_time = JST.localize(datetime(year, month2, day2, 23, 59, 59, 999999))
            logger.debug(f"[DEBUG] 複数日パターン return: start_time={start_time}, end_time={end_time}")
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True}
        # --- 月日指定パターンを最優先で抽出 ---
        m = re.search(r'(\d{1,2})[\/月](\d{1,2})(?:日)?(?=\D|$)', message)
        if m:
            logger.debug(f"[DEBUG] 月日パターン message={message} groups={m.groups()}")
            month = int(m.group(1))
            day = int(m.group(2))
            year = now.year
            # タイムゾーンなしで一旦生成
            this_year_date_naive = datetime(year, month, day, 0, 0, 0)
            today_naive = now.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
            # 今日より前なら来年扱い、今日以降は今年扱い
            if this_year_date_naive < today_naive:
                year += 1
            logger.debug(f"[DEBUG] 月日パターン after year check: month={month}, day={day}, year={year}")
            start_time = JST.localize(datetime(year, month, day, 0, 0, 0))
            end_time = JST.localize(datetime(year, month, day, 23, 59, 59, 999999))
            logger.debug(f"[DEBUG] 月日パターン return: start_time={start_time}, end_time={end_time}")
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

def extract_title(text: str, operation_type: str = None) -> Optional[str]:
    """
    メッセージからタイトルを抽出。delete/update時は抽出できなければ必ず「予定」を返す。
    """
    try:
        normalized_text = normalize_text(text, keep_katakana=True)
        logger.debug(f"[extract_title] 正規化後のテキスト: {normalized_text}")
        
        # 時間属性ワードリスト
        time_keywords = ['終日', '午前', '午後', '朝', '夜', '昼', '夕方', '深夜']
        # 削除・更新操作の場合の特別処理
        if operation_type in ('delete', 'update'):
            lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
            for line in lines:
                if any(kw in line for kw in DELETE_KEYWORDS + UPDATE_KEYWORDS):
                    continue
                if re.search(r'[\u3040-\u30ff\u4e00-\u9fffA-Za-z]', line) and not any(kw == line for kw in time_keywords):
                    return line
            return '予定'
        
        # 通常の抽出ロジック
        lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
        logger.debug(f"[extract_title] 分割後の行: {lines}")
        
        # 複数行の場合は2行目以降を優先
        if len(lines) >= 2:
            for i, line in enumerate(lines[1:], 1):
                logger.debug(f"[extract_title] {i+1}行目を確認: {line}")
                # 日本語・英字が1文字でも含まれ、かつtime_keywordsと完全一致しない行をタイトルとする
                if re.search(r'[\u3040-\u30ff\u4e00-\u9fffA-Za-z]', line):
                    logger.debug(f"[extract_title] {i+1}行目に日本語・英字を検出: {line}")
                    if not any(kw == line for kw in time_keywords):
                        logger.debug(f"[extract_title] {i+1}行目をタイトルとして採用: {line}")
                        return line.strip()
                    else:
                        logger.debug(f"[extract_title] {i+1}行目は時間属性ワードと一致したためスキップ: {line}")
        
        # 1行目のみの場合、または2行目以降でタイトルが見つからなかった場合
        if len(lines) >= 1:
            line = lines[0]
            logger.debug(f"[extract_title] 1行目を処理: {line}")
            # 日付・時刻部分を除去
            line = re.sub(r'^(\d{1,2})[\/月](\d{1,2})[日\s　]*(\d{1,2}):?(\d{2})?[\-〜~～](\d{1,2}):?(\d{2})?', '', line)
            line = re.sub(r'^(\d{1,2})月(\d{1,2})日(\d{1,2})時[\-〜~～](\d{1,2})時', '', line)
            line = re.sub(r'^(\d{1,2}):?(\d{2})?[\-〜~～](\d{1,2}):?(\d{2})?', '', line)
            line = re.sub(r'^(\d{1,2})時[\-〜~～](\d{1,2})時', '', line)
            line = re.sub(r'^(\d{1,2})[\/月](\d{1,2})[日\s　]*(\d{1,2}):?(\d{2})?', '', line)
            line = re.sub(r'^(\d{1,2})月(\d{1,2})日(\d{1,2})時(\d{1,2})分?', '', line)
            line = re.sub(r'^(\d{1,2})月(\d{1,2})日(\d{1,2})時', '', line)
            line = re.sub(r'^(\d{1,2})[\/](\d{1,2})[\s　]*(\d{1,2}):?(\d{2})?', '', line)
            line = re.sub(r'^[\s　:：,、。]+', '', line)
            logger.debug(f"[extract_title] 1行目から日付・時刻を除去後: {line}")
            
            if not line or re.fullmatch(r'[\d/:年月日時分\-〜~～\s　]+', line):
                logger.debug("[extract_title] 1行目は日付・時刻のみ")
                return None
            if any(kw == line for kw in time_keywords):
                logger.debug(f"[extract_title] 1行目は時間属性ワード: {line}")
                return None
            # 1行目に日本語・英字が含まれていればそれを返す
            if re.search(r'[\u3040-\u30ff\u4e00-\u9fffA-Za-z]', line):
                logger.debug(f"[extract_title] 1行目をタイトルとして採用: {line}")
                return line.strip()
            
        logger.debug("[extract_title] タイトルが見つかりませんでした")
        return None
    except Exception as e:
        logger.error(f"タイトル抽出エラー: {str(e)}")
        print(f"[extract_title][EXCEPTION] {e}")
        return None 

def parse_message(message: str, current_time: datetime = None) -> Dict:
    print(f"[parse_message] called: message={message}")
    try:
        if current_time is None:
            current_time = datetime.now(pytz.timezone('Asia/Tokyo'))
        # メッセージを正規化
        normalized_message = normalize_text(message)
        logger.debug(f"正規化後のメッセージ: {normalized_message}")
        # まず従来の方法でoperation_typeを抽出
        operation_type = extract_operation_type(normalized_message)
        # confirm/cancelの場合はtitleをNoneで返す
        if operation_type in ['confirm', 'cancel']:
            return {
                'success': True,
                'operation_type': operation_type,
                'title': None,
                'date': None,
                'start_time': None,
                'end_time': None,
                'is_range': False
            }
        # 操作タイプが特定できない場合、内容から推論
        if not operation_type:
            # 日時やタイトルを抽出して推論
            datetime_info = extract_datetime_from_message(normalized_message)
            title = extract_title(normalized_message)
            logger.debug(f"[parse_message] タイトル抽出結果: {title}")
            extracted = {}
            if datetime_info:
                extracted["start_time"] = datetime_info.get("start_time")
            if title:
                extracted["title"] = title
            operation_type = detect_operation_type(normalized_message, extracted)
            # それでも特定できない場合は、メッセージの内容から推測
            if not operation_type:
                # 日付や時刻が含まれている、またはdatetime_info/titleがどちらかあれば追加とみなす
                if (datetime_info and datetime_info.get("start_time")) or title or re.search(r'\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2}|\d{1,2}時|\d{1,2}:\d{2}', normalized_message):
                    operation_type = "add"
                elif re.search(r'確認|教えて|見せて|表示|一覧', normalized_message):
                    operation_type = "read"
                else:
                    return {'success': False, 'error': '操作タイプを特定できませんでした。'}

        # 操作タイプごとの処理
        if operation_type == 'add':
            lines = normalized_message.splitlines()
            if len(lines) >= 2:
                datetime_info = extract_datetime_from_message(lines[0], operation_type)
            else:
                datetime_info = extract_datetime_from_message(normalized_message, operation_type)
            if not datetime_info or not datetime_info.get('start_time'):
                return {'success': False, 'error': '日時情報が特定できません。'}
            
            title = extract_title(message)
            logger.debug(f"[parse_message][add] タイトル抽出結果: {title}")
            if not title:
                return {'success': False, 'error': 'タイトルを特定できません。'}
            
            location = extract_location(normalized_message)
            person = extract_person(normalized_message)
            recurrence = extract_recurrence(normalized_message)
            
            # durationがあればend_timeを上書き
            if 'duration' in datetime_info:
                end_time = datetime_info['start_time'] + datetime_info['duration']
            else:
                end_time = datetime_info.get('end_time', datetime_info['start_time'] + timedelta(hours=1))
            
            result = {
                "success": True,
                "operation_type": operation_type,
                "title": title,
                "start_time": datetime_info['start_time'],
                "end_time": end_time,
                "location": location,
                "person": person,
                "recurrence": recurrence
            }
            logger.info(f"[parse_message result] {result}")
            print(f"[parse_message result] {result}")
            return result
        # ... existing code ...
    except Exception as e:
        logger.error(f"parse_message error: {str(e)}")
        return {'success': False, 'error': '処理中にエラーが発生しました。'} 