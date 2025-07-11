import re
from datetime import datetime, timedelta, time
import pytz
import logging
from typing import Dict, Optional, List
import jaconv
import traceback

# GPT補助機能をインポート
from .gpt_assistant import gpt_assistant

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

def normalize_text(text: str, keep_katakana: bool = False) -> str:
    """
    テキストを正規化する
    """
    if not keep_katakana:
        # 半角カタカナ→全角カタカナ
        text = jaconv.h2z(text, kana=True)
        # 全角カタカナ→ひらがな
        text = jaconv.kata2hira(text)
    else:
        # カタカナはそのまま、英数字のみ半角化
        text = jaconv.z2h(text, ascii=True, digit=True)
    # 全角スペースを半角に変換
    text = text.replace('　', ' ')
    # 半角カタカナの「キャンセル」をひらがなに変換（複数のパターンに対応）
    text = text.replace('ｷｬﾝｾﾙ', 'きゃんせる')
    text = text.replace('ｷｬﾝｾﾙして', 'きゃんせるして')
    text = text.replace('ｷｬﾝｾﾙしてください', 'きゃんせるしてください')
    # 相対日付表現の正規化
    text = text.replace('あした', '明日')
    text = text.replace('あす', '明日')
    text = text.replace('みょうにち', '明日')
    text = text.replace('あさって', '明後日')
    text = text.replace('みょうごにち', '明後日')
    text = text.replace('きのう', '昨日')
    text = text.replace('さくじつ', '昨日')
    text = text.replace('おととい', '一昨日')
    text = text.replace('いっさくじつ', '一昨日')
    text = text.replace('こんしゅう', '今週')
    text = text.replace('らいしゅう', '来週')
    text = text.replace('さらいしゅう', '再来週')
    text = text.replace('こんげつ', '今月')
    text = text.replace('らいげつ', '来月')
    text = text.replace('さらいげつ', '再来月')
    # 助詞付きの表現も正規化
    text = text.replace('あしたの', '明日の')
    text = text.replace('あすの', '明日の')
    text = text.replace('みょうにちの', '明日の')
    text = text.replace('あさっての', '明後日の')
    text = text.replace('みょうごにちの', '明後日の')
    text = text.replace('きのうの', '昨日の')
    text = text.replace('さくじつの', '昨日の')
    text = text.replace('おとといの', '一昨日の')
    text = text.replace('いっさくじつの', '一昨日の')
    text = text.replace('こんしゅうの', '今週の')
    text = text.replace('らいしゅうの', '来週の')
    text = text.replace('さらいしゅうの', '再来週の')
    text = text.replace('こんげつの', '今月の')
    text = text.replace('らいげつの', '来月の')
    text = text.replace('さらいげつの', '再来月の')
    # 全角数字を半角数字に変換（追加）
    text = text.replace('０', '0')
    text = text.replace('１', '1')
    text = text.replace('２', '2')
    text = text.replace('３', '3')
    text = text.replace('４', '4')
    text = text.replace('５', '5')
    text = text.replace('６', '6')
    text = text.replace('７', '7')
    text = text.replace('８', '8')
    text = text.replace('９', '9')
    # 全角数字の「一」を半角数字に変換（追加）
    text = text.replace('一', '1')
    text = text.replace('二', '2')
    text = text.replace('三', '3')
    text = text.replace('四', '4')
    text = text.replace('五', '5')
    text = text.replace('六', '6')
    text = text.replace('七', '7')
    text = text.replace('八', '8')
    text = text.replace('九', '9')
    text = text.replace('十', '10')
    return text

def extract_datetime_from_message(message: str, operation_type: str = None) -> Dict:
    """
    メッセージから日時情報を抽出する（ハイブリッド方式）
    まずルールベース抽出を試行し、失敗した場合はGPT補助機能を使用
    """
    try:
        logger.debug(f"[DEBUG][extract_datetime_from_message] message={message}, operation_type={operation_type}")
        now = datetime.now(JST)
        logger.debug(f"[now] サーバー現在日時: {now}")
        
        # 複数行の時間範囲指定パターンを最優先で抽出
        # 例: "空き時間教えて\n\n7/4 8:00〜9:00\n7/5 12:00〜14:00"
        # ただし、予定追加時（operation_type='add'）の場合は、単一時間範囲を複数時間範囲として扱わない
        multi_time_ranges = extract_multiple_time_ranges(message)
        logger.debug(f"[DEBUG][extract_datetime_from_message] multi_time_ranges={multi_time_ranges}")
        if multi_time_ranges and operation_type != 'add':
            logger.debug(f"[extract_datetime_from_message] 複数時間範囲パターン matched: {multi_time_ranges}")
            return {
                'time_ranges': multi_time_ranges,
                'is_multiple_ranges': True,
                'extraction_method': 'rule_based'
            }
        
        # 予定追加時で単一時間範囲が検出された場合、通常の形式に変換
        if multi_time_ranges and operation_type == 'add' and len(multi_time_ranges) == 1:
            time_range = multi_time_ranges[0]
            date_obj = time_range['date']
            start_time_obj = time_range['start_time']
            end_time_obj = time_range['end_time']
            
            # datetimeに変換
            start_time = date_obj.replace(
                hour=start_time_obj.hour,
                minute=start_time_obj.minute,
                second=0,
                microsecond=0
            )
            end_time = date_obj.replace(
                hour=end_time_obj.hour,
                minute=end_time_obj.minute,
                second=0,
                microsecond=0
            )
            
            logger.debug(f"[extract_datetime_from_message] 予定追加用に変換: start_time={start_time}, end_time={end_time}")
            return {
                'start_time': start_time,
                'end_time': end_time,
                'is_time_range': True,
                'extraction_method': 'rule_based'
            }
        
        # まずルールベース抽出を試行
        rule_based_result = _extract_datetime_rule_based(message, now, operation_type)
        
        # ルールベースで抽出できた場合はその結果を返す
        if rule_based_result.get('start_time') or rule_based_result.get('dates'):
            logger.debug(f"[extract_datetime_from_message] ルールベース抽出成功: {rule_based_result}")
            return rule_based_result
        
        # ルールベースで抽出できなかった場合、GPT補助を使用すべきかチェック
        if gpt_assistant.should_use_gpt(message, rule_based_result):
            logger.info(f"[extract_datetime_from_message] GPT補助を使用して日時抽出を試行: {message}")
            gpt_result = gpt_assistant.extract_datetime_with_gpt(message, now)
            
            if gpt_result:
                # GPT補助で抽出できた場合、結果をマージ
                result = {**rule_based_result, **gpt_result}
                result['extraction_method'] = 'hybrid_gpt'
                logger.info(f"[extract_datetime_from_message] GPT補助抽出成功: {result}")
                return result
        
        # どちらでも抽出できなかった場合
        logger.debug(f"[extract_datetime_from_message] 日時抽出失敗: message={message}")
        return {'start_time': None, 'end_time': None, 'is_time_range': False, 'extraction_method': 'none'}
        
    except Exception as e:
        logger.error(f"extract_datetime_from_message error: {str(e)}")
        return {'start_time': None, 'end_time': None, 'is_time_range': False, 'extraction_method': 'error'}

def extract_multiple_time_ranges(message: str) -> List[Dict]:
    """
    メッセージから複数の時間範囲を抽出する
    
    Args:
        message: 解析対象のメッセージ
        
    Returns:
        時間範囲のリスト [{'date': datetime, 'start_time': time, 'end_time': time}, ...]
    """
    try:
        # 行に分割
        lines = [line.strip() for line in message.splitlines() if line.strip()]
        
        time_ranges = []
        now = datetime.now(JST)
        
        for line in lines:
            # 日付と時間範囲のパターンを検索
            # 例: "7/4 8:00〜9:00", "7月4日 14:00-16:00"
            patterns = [
                r'(\d{1,2})[\/月](\d{1,2})日?\s+(\d{1,2}):(\d{2})[〜~～-](\d{1,2}):(\d{2})',
                r'(\d{1,2})[\/月](\d{1,2})日?\s+(\d{1,2})時(\d{2})分?[〜~～-](\d{1,2})時(\d{2})分?',
                r'(\d{1,2})[\/月](\d{1,2})日?\s+(\d{1,2})時[〜~～-](\d{1,2})時',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, line)
                if match:
                    groups = match.groups()
                    
                    if len(groups) == 6:  # "7/4 8:00〜9:00" パターン
                        month = int(groups[0])
                        day = int(groups[1])
                        start_hour = int(groups[2])
                        start_minute = int(groups[3])
                        end_hour = int(groups[4])
                        end_minute = int(groups[5])
                    elif len(groups) == 6:  # "7/4 8時30分〜9時30分" パターン
                        month = int(groups[0])
                        day = int(groups[1])
                        start_hour = int(groups[2])
                        start_minute = int(groups[3])
                        end_hour = int(groups[4])
                        end_minute = int(groups[5])
                    elif len(groups) == 4:  # "7/4 8時〜9時" パターン
                        month = int(groups[0])
                        day = int(groups[1])
                        start_hour = int(groups[2])
                        start_minute = 0
                        end_hour = int(groups[3])
                        end_minute = 0
                    else:
                        continue
                    
                    # 年を決定
                    year = now.year
                    if (month < now.month) or (month == now.month and day < now.day):
                        year += 1
                    
                    # 日付と時刻を構築
                    date_obj = JST.localize(datetime(year, month, day))
                    start_time = time(start_hour, start_minute)
                    end_time = time(end_hour, end_minute)
                    
                    time_ranges.append({
                        'date': date_obj,
                        'start_time': start_time,
                        'end_time': end_time
                    })
                    
                    logger.debug(f"[extract_multiple_time_ranges] 抽出: {date_obj.date()} {start_time}〜{end_time}")
                    break
        
        return time_ranges
        
    except Exception as e:
        logger.error(f"extract_multiple_time_ranges error: {str(e)}")
        return []

def _extract_datetime_rule_based(message: str, now: datetime, operation_type: str = None) -> Dict:
    """
    ルールベースでの日時抽出（既存のロジック）
    """
    try:
        # 日付＋番号＋変更のパターン（例：6/19 2 変更）
        update_pattern = r'(\d{1,2})[\/月](\d{1,2})日?\s*(\d+)\s*(番)?\s*(変更|修正|更新|編集)'
        update_match = re.search(update_pattern, message)
        if update_match:
            logger.debug(f"[_extract_datetime_rule_based] update_pattern matched: {update_match.groups()} message={message}")
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
                new_time_info = _extract_datetime_rule_based(lines[1], now)
                logger.debug(f"[_extract_datetime_rule_based] new_time_info from 2nd line: {new_time_info} line={lines[1]}")
                if new_time_info.get('start_time') and new_time_info.get('end_time'):
                    return {
                        'start_time': start_time,
                        'end_time': end_time,
                        'new_start_time': new_time_info['start_time'],
                        'new_end_time': new_time_info['end_time'],
                        'update_index': update_index,
                        'is_time_range': True,
                        'extraction_method': 'rule_based'
                    }
            return {
                'start_time': start_time,
                'end_time': end_time,
                'update_index': update_index,
                'is_time_range': True,
                'extraction_method': 'rule_based'
            }
        
        # 時間範囲のパターン（例：14:00〜15:00）
        time_range_pattern = r'(\d{1,2}):(\d{2})[〜~～-](\d{1,2}):(\d{2})'
        time_range_match = re.search(time_range_pattern, message)
        if time_range_match:
            logger.debug(f"[_extract_datetime_rule_based] time_range_pattern matched: {time_range_match.groups()} message={message}")
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
                return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True, 'extraction_method': 'rule_based'}
        
        # 「今日からn週間」
        m = re.search(r'今日から(\d+)週間', message)
        if m:
            logger.debug(f"[_extract_datetime_rule_based] 今日からn週間 matched: {m.groups()} message={message}")
            n = int(m.group(1))
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = (start_time + timedelta(days=7*n-1)).replace(hour=23, minute=59, second=59, microsecond=999999)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True, 'extraction_method': 'rule_based'}
        # 「今日から1週間」
        if re.search(r'今日から1週間', message):
            logger.debug(f"[_extract_datetime_rule_based] 今日から1週間 matched: message={message}")
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = (start_time + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True, 'extraction_method': 'rule_based'}
        # 「今週」
        if re.search(r'今週', message):
            logger.debug(f"[_extract_datetime_rule_based] 今週 matched: message={message}")
            start_time = now - timedelta(days=now.weekday())
            start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=999999)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True, 'extraction_method': 'rule_based'}
        # 「来週」
        if re.search(r'来週', message):
            logger.debug(f"[_extract_datetime_rule_based] 来週 matched: message={message}")
            start_time = now - timedelta(days=now.weekday()) + timedelta(days=7)
            start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=999999)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True, 'extraction_method': 'rule_based'}
        
        # --- 相対日付表現パターンを追加 ---
        # 「一昨日」（「昨日」より先に配置）
        if re.search(r'一昨日', message):
            logger.debug(f"[_extract_datetime_rule_based] 一昨日 matched: message={message}")
            day_before_yesterday = now - timedelta(days=2)
            start_time = day_before_yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = day_before_yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True, 'extraction_method': 'rule_based'}
        
        # 「昨日」
        if re.search(r'昨日', message):
            logger.debug(f"[_extract_datetime_rule_based] 昨日 matched: message={message}")
            yesterday = now - timedelta(days=1)
            start_time = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True, 'extraction_method': 'rule_based'}
        
        # 「明日」
        if re.search(r'明日', message):
            logger.debug(f"[_extract_datetime_rule_based] 明日 matched: message={message}")
            tomorrow = now + timedelta(days=1)
            start_time = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = tomorrow.replace(hour=23, minute=59, second=59, microsecond=999999)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True, 'extraction_method': 'rule_based'}
        
        # 「明後日」
        if re.search(r'明後日', message):
            logger.debug(f"[_extract_datetime_rule_based] 明後日 matched: message={message}")
            day_after_tomorrow = now + timedelta(days=2)
            start_time = day_after_tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = day_after_tomorrow.replace(hour=23, minute=59, second=59, microsecond=999999)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True, 'extraction_method': 'rule_based'}
        
        # 「今日」
        if re.search(r'今日', message):
            logger.debug(f"[_extract_datetime_rule_based] 今日 matched: message={message}")
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = now.replace(hour=23, minute=59, second=59, microsecond=999999)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True, 'extraction_method': 'rule_based'}
        
        # 「今日から1週間」
        if re.search(r'今日から1週間', message):
            logger.debug(f"[_extract_datetime_rule_based] 今日から1週間 matched: message={message}")
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = (start_time + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True, 'extraction_method': 'rule_based'}
        
        # 「今週」
        if re.search(r'今週', message):
            logger.debug(f"[_extract_datetime_rule_based] 今週 matched: message={message}")
            start_time = now - timedelta(days=now.weekday())
            start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=999999)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True, 'extraction_method': 'rule_based'}
        
        # 「来週」
        if re.search(r'来週', message):
            logger.debug(f"[_extract_datetime_rule_based] 来週 matched: message={message}")
            start_time = now - timedelta(days=now.weekday()) + timedelta(days=7)
            start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=999999)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True, 'extraction_method': 'rule_based'}
        
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
                this_year_date_naive = datetime(year, month, day)
                today_naive = now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
                # 今日より前なら翌年
                if this_year_date_naive < today_naive:
                    date_obj = JST.localize(datetime(year+1, month, day))
                else:
                    date_obj = JST.localize(datetime(year, month, day))
                date_objs.append(date_obj)
            logger.debug(f"[DEBUG] 複数日(3個以上)パターン return: dates={date_objs}")
            return {'dates': date_objs, 'is_time_range': False, 'is_multiple_days': True, 'extraction_method': 'rule_based'}
        # --- 複数日指定パターン（2個） ---
        multiple_dates_pattern = r'(\d{1,2})[\/月](\d{1,2})(?:日)?\s*と\s*(\d{1,2})[\/月](\d{1,2})(?:日)?'
        multiple_dates_match = re.search(multiple_dates_pattern, message)
        if multiple_dates_match:
            logger.debug(f"[DEBUG] 複数日パターン message={message} groups={multiple_dates_match.groups()}")
            month1 = int(multiple_dates_match.group(1))
            day1 = int(multiple_dates_match.group(2))
            month2 = int(multiple_dates_match.group(3))
            day2 = int(multiple_dates_match.group(4))
            now = datetime.now(JST)
            year = now.year
            today_naive = now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)

            this_year_date1_naive = datetime(year, month1, day1)
            year1 = year + 1 if this_year_date1_naive < today_naive else year
            date1 = JST.localize(datetime(year1, month1, day1))

            this_year_date2_naive = datetime(year, month2, day2)
            year2 = year + 1 if this_year_date2_naive < today_naive else year
            date2 = JST.localize(datetime(year2, month2, day2))
            
            logger.debug(f"[DEBUG] 複数日パターン return: dates={[date1, date2]}")
            return {'dates': [date1, date2], 'is_time_range': False, 'is_multiple_days': True, 'extraction_method': 'rule_based'}
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
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': True, 'extraction_method': 'rule_based'}
        # 「6/18 1」や「6月18日1時」
        m = re.search(r'(\d{1,2})[\/月](\d{1,2})[日\s　]*(\d{1,2})時?', message)
        if m:
            logger.debug(f"[_extract_datetime_rule_based] 月日＋時刻パターン matched: {m.groups()} message={message}")
            month = int(m.group(1))
            day = int(m.group(2))
            hour = int(m.group(3))
            year = now.year
            if (month < now.month) or (month == now.month and day < now.day):
                year += 1
            start_time = JST.localize(datetime(year, month, day, hour, 0, 0))
            end_time = start_time + timedelta(hours=1)
            return {'start_time': start_time, 'end_time': end_time, 'is_time_range': False, 'extraction_method': 'rule_based'}
        # --- 日本語日付＋時刻範囲パターンを最優先で抽出 ---
        jp_date_time_range_match = re.search(r'(\d{1,2})月(\d{1,2})日[\s　]*(\d{1,2}):?(\d{2})[〜~～-](\d{1,2}):?(\d{2})', message)
        if jp_date_time_range_match:
            logger.debug(f"[_extract_datetime_rule_based] 日本語日付＋時刻範囲パターン matched: {jp_date_time_range_match.groups()} message={message}")
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
            result = {'start_time': start_time, 'end_time': end_time, 'is_time_range': True, 'extraction_method': 'rule_based'}
            logger.debug(f"[datetime_extraction][HIT] 日本語日付＋時刻範囲: {jp_date_time_range_match.groups()} 入力メッセージ: {message}, 抽出結果: start={start_time}, end={end_time}")
            return result
        logger.debug(f"[_extract_datetime_rule_based] no pattern matched: message={message}")
        return {'start_time': None, 'end_time': None, 'is_time_range': False, 'extraction_method': 'rule_based'}
    except Exception as e:
        logger.error(f"_extract_datetime_rule_based error: {str(e)}")
        return {'start_time': None, 'end_time': None, 'is_time_range': False, 'extraction_method': 'rule_based_error'}

def extract_title(message: str, operation_type: str = None) -> Optional[str]:
    """
    メッセージからタイトルを抽出する
    """
    print(f"[extract_title] 開始: message='{message}', operation_type={operation_type}")
    logger.debug(f"[extract_title] 開始: message='{message}', operation_type={operation_type}")

    if operation_type == 'read':
        return None
    
    try:
        # メッセージを正規化（カタカナを保持）
        normalized_message = normalize_text(message, keep_katakana=True)
        print(f"[extract_title] 正規化後: '{normalized_message}'")
        logger.debug(f"[extract_title] 正規化後: '{normalized_message}'")
        
        # 行に分割
        lines = [line.strip() for line in normalized_message.splitlines() if line.strip()]
        print(f"[extract_title] 行数: {len(lines)}, 各行: {lines}")
        logger.debug(f"[extract_title] 行数: {len(lines)}, 各行: {lines}")
        
        # タイトル抽出のロジック
        title = None
        
        # 2行目以降からタイトルを探す
        for i, line in enumerate(lines[1:], 1):
            print(f"[extract_title] 行{i}をチェック: '{line}'")
            logger.debug(f"[extract_title] 行{i}をチェック: '{line}'")
            
            # 日時パターンを除外
            if re.search(r'\d{1,2}[\/月]\d{1,2}|時|分|:\d{2}', line):
                print(f"[extract_title] 行{i}は日時パターンのためスキップ")
                logger.debug(f"[extract_title] 行{i}は日時パターンのためスキップ")
                continue
            
            # 空でない行をタイトルとして使用
            if line.strip():
                title = line.strip()
                print(f"[extract_title] タイトルとして抽出: '{title}'")
                logger.debug(f"[extract_title] タイトルとして抽出: '{title}'")
                break
        
        # タイトルが見つからない場合、1行目からも探す
        if not title and lines:
            first_line = lines[0]
            print(f"[extract_title] 1行目をチェック: '{first_line}'")
            logger.debug(f"[extract_title] 1行目をチェック: '{first_line}'")
            
            # 日時部分を除去してタイトルを抽出
            # 日時パターンを削除
            title_line = re.sub(r'\d{1,2}[\/月]\d{1,2}日?[\s　]*\d{1,2}:\d{2}[〜~～-]\d{1,2}:\d{2}', '', first_line)
            title_line = re.sub(r'\d{1,2}[\/月]\d{1,2}日?', '', title_line)
            title_line = title_line.strip()
            
            if title_line:
                title = title_line
                print(f"[extract_title] 1行目からタイトル抽出: '{title}'")
                logger.debug(f"[extract_title] 1行目からタイトル抽出: '{title}'")
        
        print(f"[extract_title] 最終結果: '{title}'")
        logger.debug(f"[extract_title] 最終結果: '{title}'")
        
        return title
        
    except Exception as e:
        print(f"[extract_title] エラー: {str(e)}")
        logger.error(f"[extract_title] エラー: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def extract_operation_type(message: str) -> Optional[str]:
    """
    メッセージから操作タイプを抽出する
    """
    normalized = normalize_text(message)
    
    # キャンセル系
    if re.search(r'きゃんせる|キャンセル|削除|消去|取り消し', normalized):
        return 'cancel'
    
    # 確認系
    if re.search(r'確認|教えて|見せて|表示|一覧|予定', normalized):
        return 'read'
    
    # 追加系（日時が含まれている場合）
    if re.search(r'\d{1,2}[\/月]\d{1,2}|\d{1,2}時|\d{1,2}:\d{2}', normalized):
        return 'add'
    
    return None

def detect_operation_type(message: str, extracted: Dict) -> Optional[str]:
    """
    抽出された情報から操作タイプを推測する
    """
    if extracted.get('start_time'):
        return 'add'
    elif extracted.get('title'):
        return 'add'
    return None

def extract_location(message: str) -> Optional[str]:
    """
    メッセージから場所を抽出する
    """
    # 場所抽出のロジックを実装
    return None

def extract_person(message: str) -> Optional[str]:
    """
    メッセージから人物を抽出する
    """
    # 人物抽出のロジックを実装
    return None

def extract_recurrence(message: str) -> Optional[str]:
    """
    メッセージから繰り返し情報を抽出する
    """
    # 繰り返し抽出のロジックを実装
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
            datetime_info = extract_datetime_from_message(normalized_message, operation_type)
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
            datetime_info = extract_datetime_from_message(normalized_message, operation_type)
            print(f"[DEBUG][parse_message] datetime_info: {datetime_info}")
            logger.debug(f"[DEBUG][parse_message] datetime_info: {datetime_info}")
            if not datetime_info or not datetime_info.get('start_time'):
                return {'success': False, 'error': '日時情報が特定できません。'}
            
            title = extract_title(message)
            logger.debug(f"[parse_message][add] タイトル抽出結果: {title}")
            logger.debug(f"[parse_message][add] タイトル抽出前のメッセージ: {message}")
            if not title:
                logger.debug(f"[parse_message][add] タイトルが抽出できませんでした")
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
        
        elif operation_type == 'read':
            # 日時範囲を抽出
            datetime_info = extract_datetime_from_message(normalized_message, operation_type)
            if datetime_info and datetime_info.get('start_time'):
                return {
                    'success': True,
                    'operation_type': operation_type,
                    'start_time': datetime_info['start_time'],
                    'end_time': datetime_info['end_time'],
                    'is_range': datetime_info.get('is_time_range', False)
                }
            else:
                # 日時が指定されていない場合は今日の予定を表示
                today = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
                tomorrow = today + timedelta(days=1)
                return {
                    'success': True,
                    'operation_type': operation_type,
                    'start_time': today,
                    'end_time': tomorrow,
                    'is_range': True
                }
        
        elif operation_type == 'cancel':
            # キャンセル処理
            datetime_info = extract_datetime_from_message(normalized_message, operation_type)
            if datetime_info and datetime_info.get('start_time'):
                return {
                    'success': True,
                    'operation_type': operation_type,
                    'start_time': datetime_info['start_time'],
                    'end_time': datetime_info['end_time'],
                    'is_range': datetime_info.get('is_time_range', False)
                }
            else:
                return {'success': False, 'error': 'キャンセルする予定の日時が特定できません。'}
        
        else:
            return {'success': False, 'error': f'未対応の操作タイプ: {operation_type}'}
            
    except Exception as e:
        logger.error(f"parse_message error: {str(e)}")
        logger.error(traceback.format_exc())
        return {'success': False, 'error': '処理中にエラーが発生しました。'} 