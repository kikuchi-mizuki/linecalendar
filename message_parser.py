import spacy
import re
from datetime import datetime, timedelta, timezone, date, time
import logging
import calendar
from typing import Optional, Dict, Any, Tuple, List
import dateparser
from dateparser.conf import Settings
import traceback
import pytz
import jaconv
from extractors.datetime_extractor import DateTimeExtractor
from extractors.title_extractor import TitleExtractor
from extractors.recurrence_extractor import RecurrenceExtractor
from extractors.person_extractor import PersonExtractor
from constants import (
    ADD_KEYWORDS, DELETE_KEYWORDS, UPDATE_KEYWORDS, READ_KEYWORDS,
    RELATIVE_DATES, WEEKDAYS, TIME_PATTERNS, DATE_PATTERNS
)

logger = logging.getLogger('app')

# DateTimeExtractorのインスタンスを作成
datetime_extractor = DateTimeExtractor()
# TitleExtractorのインスタンスを作成
title_extractor = TitleExtractor()
# RecurrenceExtractorのインスタンスを作成
recurrence_extractor = RecurrenceExtractor()

# spaCyモデルの読み込み
try:
    nlp = spacy.load("ja_core_news_sm")
except OSError:
    logger.info("Downloading spaCy model...")
    spacy.cli.download("ja_core_news_sm")
    nlp = spacy.load("ja_core_news_sm")

# dateparserの設定
settings = Settings()
settings.PREFER_DATES_FROM = 'future'
settings.TIMEZONE = 'Asia/Tokyo'
settings.RETURN_AS_TIMEZONE_AWARE = True
settings.RELATIVE_BASE = datetime.now()
settings.LANGUAGES = ['ja']
settings.PREFER_DAY_OF_MONTH = 'first'
settings.PREFER_MONTH_OF_YEAR = 'current'
settings.SKIP_TOKENS = ['の']
settings.RELATIVE_BASE = datetime(2025, 1, 1)  # 2025年を基準に設定

# 日本語の助詞とその役割のマッピングを拡充
PARTICLE_ROLES = {
    'の': ['possession', 'modification', 'topic', 'nominalization', 'apposition'],
    'と': ['with', 'and', 'comparison', 'quotation', 'conjunction'],
    'は': ['topic', 'contrast', 'emphasis', 'focus'],
    'を': ['object', 'target', 'passive', 'direction'],
    'に': ['target', 'time', 'location', 'purpose', 'cause', 'passive', 'agent'],
    'で': ['location', 'means', 'time_range', 'scope', 'cause', 'state', 'limit'],
    'から': ['start', 'source', 'reason', 'material', 'origin', 'basis'],
    'まで': ['end', 'destination', 'limit', 'extent', 'range'],
    'へ': ['direction', 'target', 'purpose', 'destination'],
    'が': ['subject', 'object', 'desire', 'ability', 'focus', 'emphasis'],
    'も': ['also', 'even', 'emphasis', 'addition', 'inclusion'],
    'や': ['and', 'example', 'listing', 'selection'],
    'か': ['question', 'choice', 'uncertainty', 'doubt'],
    'ね': ['confirmation', 'emphasis', 'agreement', 'appeal'],
    'よ': ['emphasis', 'attention', 'assertion', 'notification'],
    'な': ['emphasis', 'request', 'prohibition', 'emotion'],
    'わ': ['emphasis', 'feminine', 'realization', 'emotion'],
    'ぞ': ['emphasis', 'masculine', 'assertion', 'warning'],
    'ぜ': ['emphasis', 'masculine', 'invitation', 'encouragement'],
    'だ': ['assertion', 'declaration', 'state'],
    'です': ['polite_assertion', 'declaration', 'state'],
    'ます': ['polite_verb', 'declaration', 'state'],
    'けど': ['contrast', 'concession', 'background'],
    'から': ['reason', 'cause', 'basis', 'start'],
    'ので': ['reason', 'cause', 'basis'],
    'のに': ['contrast', 'expectation', 'purpose'],
    'ば': ['condition', 'hypothesis', 'assumption'],
    'たら': ['condition', 'hypothesis', 'assumption'],
    'なら': ['condition', 'hypothesis', 'assumption'],
    'て': ['connection', 'sequence', 'cause', 'state'],
    'で': ['connection', 'sequence', 'cause', 'state'],
}

# 日本語の日時表現を英語に変換するマッピング
JP_TO_EN_MAPPING = {
    '今日': 'today',
    '明日': 'tomorrow',
    '明後日': 'day after tomorrow',
    '昨日': 'yesterday',
    '一昨日': 'day before yesterday',
    '来週': 'next week',
    '先週': 'last week',
    '今週': 'this week',
    '再来週': 'week after next',
    '月曜': 'monday',
    '火曜': 'tuesday',
    '水曜': 'wednesday',
    '木曜': 'thursday',
    '金曜': 'friday',
    '土曜': 'saturday',
    '日曜': 'sunday',
    '月曜日': 'monday',
    '火曜日': 'tuesday',
    '水曜日': 'wednesday',
    '木曜日': 'thursday',
    '金曜日': 'friday',
    '土曜日': 'saturday',
    '日曜日': 'sunday',
    '今月': 'this month',
    '来月': 'next month',
    '先月': 'last month',
    '今年': 'this year',
    '来年': 'next year',
    '去年': 'last year',
    '一昨年': 'year before last',
}

# 予定追加のキーワード（より自然な表現に対応）
ADD_KEYWORDS = [
    '追加', '登録', '予定を入れる', '予定を入れて', '予定を追加', '予定を登録',
    'スケジュールを入れる', 'スケジュールを追加', 'スケジュールを登録',
    '会議を入れる', '会議を追加', '会議を登録', 'ミーティングを入れる',
    'ミーティングを追加', 'ミーティングを登録', 'アポイントを入れる',
    'アポイントを追加', 'アポイントを登録', '約束を入れる', '約束を追加',
    '約束を登録', '予定を設定', 'スケジュールを設定', '会議を設定',
    'ミーティングを設定', 'アポイントを設定', '約束を設定'
]

# 予定削除のキーワード（より自然な表現に対応）
DELETE_KEYWORDS = [
    '削除', '消す', '消して', '取り消し', '取り消して', 'キャンセル',
    'キャンセルして', '中止', '中止して', '予定を消す', '予定を消して',
    '予定を削除', '予定を削除して', '予定を取り消し', '予定を取り消して',
    '予定をキャンセル', '予定をキャンセルして', '予定を中止', '予定を中止して',
    'スケジュールを消す', 'スケジュールを消して', 'スケジュールを削除',
    'スケジュールを削除して', 'スケジュールを取り消し', 'スケジュールを取り消して',
    'スケジュールをキャンセル', 'スケジュールをキャンセルして', 'スケジュールを中止',
    'スケジュールを中止して'
]

# 予定変更のキーワード（より自然な表現に対応）
UPDATE_KEYWORDS = [
    '変更', '変更して', '修正', '修正して', '更新', '更新して', '編集',
    '編集して', '予定を変更', '予定を変更して', '予定を修正', '予定を修正して',
    '予定を更新', '予定を更新して', '予定を編集', '予定を編集して',
    'スケジュールを変更', 'スケジュールを変更して', 'スケジュールを修正',
    'スケジュールを修正して', 'スケジュールを更新', 'スケジュールを更新して',
    'スケジュールを編集', 'スケジュールを編集して', '時間を変更',
    '時間を変更して', '日時を変更', '日時を変更して', '場所を変更',
    '場所を変更して'
]

# 予定確認のキーワード（より自然な表現に対応）
READ_KEYWORDS = [
    '確認', '確認して', '見る', '見て', '表示', '表示して', '教えて',
    '教えてください', '予定を確認', '予定を確認して', '予定を見る',
    '予定を見て', '予定を表示', '予定を表示して', '予定を教えて',
    '予定を教えてください', 'スケジュールを確認', 'スケジュールを確認して',
    'スケジュールを見る', 'スケジュールを見て', 'スケジュールを表示',
    'スケジュールを表示して', 'スケジュールを教えて', 'スケジュールを教えてください',
    '今日の予定', '明日の予定', '今週の予定', '来週の予定', '今月の予定',
    '来月の予定', '予定一覧', 'スケジュール一覧',
    '空いている時間', '空き時間', 'あき時間', '空いてる時間', '空いてる', 'free time', 'free slot'
]

# 時間表現のパターンを拡充
TIME_PATTERNS = [
    # 既存のパターン
    r'(?P<hour>\d{1,2})時(?P<minute>\d{1,2})分?(?P<period>午前|午後|夜|夕方|深夜)?',
    r'(?P<hour>\d{1,2}):(?P<minute>\d{2})(?P<period>午前|午後|夜|夕方|深夜)?',
    # 新しいパターン
    r'(?P<hour>\d{1,2})時から(?P<minute>\d{1,2})分?(?P<period>午前|午後|夜|夕方|深夜)?',
    r'(?P<hour>\d{1,2}):(?P<minute>\d{2})から(?P<period>午前|午後|夜|夕方|深夜)?',
    r'(?P<hour>\d{1,2})時(?P<minute>\d{1,2})分から(?P<period>午前|午後|夜|夕方|深夜)?',
    r'(?P<hour>\d{1,2}):(?P<minute>\d{2})から(?P<end_hour>\d{1,2}):(?P<end_minute>\d{2})(?P<period>午前|午後|夜|夕方|深夜)?',
    r'(?P<hour>\d{1,2})時から(?P<end_hour>\d{1,2})時(?P<period>午前|午後|夜|夕方|深夜)?',
    r'(?P<hour>\d{1,2})時(?P<minute>\d{1,2})分から(?P<end_hour>\d{1,2})時(?P<end_minute>\d{1,2})分(?P<period>午前|午後|夜|夕方|深夜)?'
]

# 日付表現のパターンを拡充
DATE_PATTERNS = {
    'absolute_date': r'(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日',
    'relative_date': r'(?P<relative>今日|明日|明後日|昨日|一昨日|今週|来週|再来週|先週|今月|来月|先月|今年|来年|去年|一昨年)',
    'weekday': r'(?P<weekday>月|火|水|木|金|土|日)曜日?',
    'month_day': r'(?P<month>\d{1,2})月(?P<day>\d{1,2})日',
    'slash_date': r'(?P<month>\d{1,2})/(?P<day>\d{1,2})',
    # より自然な表現（追加）
    'relative_date_with_weekday': r'(?P<relative>今週|来週|再来週|先週)の(?P<weekday>月|火|水|木|金|土|日)曜日?',
    'relative_date_with_month': r'(?P<relative>今月|来月|先月)の(?P<day>\d{1,2})日',
    'relative_date_with_year': r'(?P<relative>今年|来年|去年|一昨年)の(?P<month>\d{1,2})月(?P<day>\d{1,2})日',
    'relative_date_with_weekday_and_time': r'(?P<relative>今週|来週|再来週|先週)の(?P<weekday>月|火|水|木|金|土|日)曜日?の(?P<hour>\d{1,2})時(?:(?P<minute>\d{1,2})分)?',
    'relative_date_with_month_and_time': r'(?P<relative>今月|来月|先月)の(?P<day>\d{1,2})日の(?P<hour>\d{1,2})時(?:(?P<minute>\d{1,2})分)?',
    'relative_date_with_year_and_time': r'(?P<relative>今年|来年|去年|一昨年)の(?P<month>\d{1,2})月(?P<day>\d{1,2})日の(?P<hour>\d{1,2})時(?:(?P<minute>\d{1,2})分)?',
}

# タイムゾーンの設定
JST = pytz.timezone('Asia/Tokyo')

logging.basicConfig(level=logging.DEBUG)

def normalize_text(text: str, keep_katakana: bool = False) -> str:
    """
    テキストを正規化する
    """
    # 半角カタカナ→全角カタカナ
    text = jaconv.h2z(text, kana=True)
    if not keep_katakana:
        # 全角カタカナ→ひらがな
        text = jaconv.kata2hira(text)
    # 全角数字・英字を半角に変換
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

def normalize_digits(text: str) -> str:
    """全角数字を半角数字に変換するユーティリティ関数"""
    return text.translate(str.maketrans('０１２３４５６７８９', '0123456789'))

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
        
        # 操作タイプが特定できない場合、内容から推論
        if not operation_type:
            # 日時やタイトルを抽出して推論
            datetime_info = extract_datetime_from_message(normalized_message)
            title = extract_title(normalized_message)
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
            
        elif operation_type == 'delete':
            title = extract_title(message)
            datetime_info = extract_datetime_from_message(normalized_message, operation_type)
            return {
                'success': True,
                'operation_type': 'delete',
                'title': title,
                'start_time': datetime_info.get('start_time') if datetime_info else None,
                'end_time': datetime_info.get('end_time') if datetime_info else None
            }
                
        elif operation_type == 'update':
            title = extract_title(message)
            lines = normalized_message.splitlines()
            if len(lines) >= 2:
                dt1 = extract_datetime_from_message(lines[0], 'update')
                dt2 = extract_datetime_from_message(lines[1], 'update')
                logger.debug(f"[parse_message][update] 1行目: {lines[0]} => {dt1}")
                logger.debug(f"[parse_message][update] 2行目: {lines[1]} => {dt2}")
                
                new_start_time = dt2.get('start_time')
                new_end_time = dt2.get('end_time')
                if 'duration' in dt2 and dt2['start_time']:
                    new_end_time = dt2['start_time'] + dt2['duration']
                
                if dt1.get('start_time') and new_start_time:
                    # 2行目にend_timeがあればそれを優先
                    if dt2.get('end_time'):
                        new_end_time = dt2.get('end_time')
                    elif dt1.get('end_time') and dt1.get('start_time'):
                        original_duration = dt1.get('end_time') - dt1.get('start_time')
                        new_end_time = new_start_time + original_duration
                    else:
                        new_end_time = new_start_time + timedelta(hours=1)
                    return {
                        'success': True,
                        'operation_type': 'update',
                        'title': title,
                        'start_time': dt1.get('start_time'),
                        'end_time': dt1.get('end_time'),
                        'new_start_time': new_start_time,
                        'new_end_time': new_end_time
                    }
            
            datetime_info = extract_datetime_from_message(normalized_message, operation_type)
            if datetime_info.get('new_start_time') and datetime_info.get('new_end_time'):
                return {
                    'success': True,
                    'operation_type': 'update',
                    'title': title,
                    'start_time': datetime_info.get('start_time'),
                    'end_time': datetime_info.get('end_time'),
                    'new_start_time': datetime_info.get('new_start_time'),
                    'new_end_time': datetime_info.get('new_end_time')
                }
            
            return {
                'success': True,
                'operation_type': 'update',
                'title': title,
                'start_time': datetime_info.get('start_time'),
                'end_time': datetime_info.get('end_time'),
                'new_start_time': datetime_info.get('new_start_time'),
                'new_end_time': datetime_info.get('new_end_time')
            }
                
        elif operation_type == 'read':
            datetime_info = extract_datetime_from_message(normalized_message, operation_type)
            return {
                'success': True,
                'operation_type': 'read',
                'start_time': datetime_info.get('start_time') if datetime_info else None,
                'end_time': datetime_info.get('end_time') if datetime_info else None
            }
            
        else:
            return {'success': False, 'error': '未対応の操作タイプです。'}
            
    except Exception as e:
        print(f"[parse_message][EXCEPTION] {e}")
        logger.error(f"メッセージ解析中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        return {'success': False, 'error': str(e)}

def extract_update_time(message: str, now: datetime) -> Tuple[Optional[datetime], Optional[datetime], bool]:
    """更新時の新しい時間を抽出する"""
    try:
        # 全角数字を半角に変換
        message = normalize_digits(message)
        
        # 時間のパターンを定義
        time_patterns = [
            r'(\d{1,2})時(?:(\d{1,2})分)?に変更',
            r'(\d{1,2}):(\d{2})に変更',
            r'(\d{1,2})時(?:(\d{1,2})分)?に',
            r'(\d{1,2}):(\d{2})に',
            r'(\d{1,2})時(?:(\d{1,2})分)?へ',
            r'(\d{1,2}):(\d{2})へ',
            # 追加パターン
            r'(\d{1,2})時(?:(\d{1,2})分)?からに変更',
            r'(\d{1,2}):(\d{2})からに変更',
            r'(\d{1,2})時(?:(\d{1,2})分)?から',
            r'(\d{1,2}):(\d{2})から',
            r'(\d{1,2})時[~〜\-](\d{1,2})時に変更',
            r'(\d{1,2}):(\d{2})[~〜\-](\d{1,2}):(\d{2})に変更',
            r'(\d{1,2})時[~〜\-](\d{1,2})時',
            r'(\d{1,2}):(\d{2})[~〜\-](\d{1,2}):(\d{2})',
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, message)
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2)) if match.group(2) else 0
                
                # 時間の範囲チェック
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    continue
                
                # 新しい時間を設定
                new_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                return new_time, new_time + timedelta(hours=1), True
            
        return None, None, False
    except Exception as e:
        logger.error(f"時間の抽出中にエラーが発生: {str(e)}")
        return None, None, False

def extract_operation_type(text: str) -> Optional[str]:
    """
    メッセージから操作タイプを抽出する
    """
    # テキストを正規化
    normalized_text = normalize_text(text)

    # 各操作タイプのキーワードをチェック
    for keyword in ADD_KEYWORDS:
        if keyword in normalized_text:
            return 'add'
    for keyword in DELETE_KEYWORDS:
        if keyword in normalized_text:
            return 'delete'
    for keyword in UPDATE_KEYWORDS:
        if keyword in normalized_text:
            return 'update'
    for keyword in READ_KEYWORDS:
        if keyword in normalized_text:
            return 'read'
    # 「今日の予定」「明日の予定」「今週の予定」などもread判定
    if re.search(r'(今日|明日|明後日|今週|来週|今月|来月|今度)[の ]*予定(を)?(教えて)?', normalized_text):
        return 'read'
    # 日付や時刻が含まれていて、かつタイトルっぽい行があれば「add」とみなす
    # 例: 「5/16 10:00 田中さんMTG」や「5月16日10時田中さんMTG」
    # 日付＋時刻＋タイトルのパターン
    date_time_title_pattern = r'(\d{1,2}[\/月]\d{1,2}[日\s]+\d{1,2}[:時][\d{2}]?\s*.+)'
    if re.search(date_time_title_pattern, normalized_text):
        return 'add'
    # 1行目に日付や時刻や/や:が含まれていて、2行目以降が存在する場合もaddとみなす
    lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
    if len(lines) >= 2:
        first_line = lines[0]
        # 1行目が日時っぽい && 2行目以降がタイトルっぽい場合はadd
        if re.search(r'(\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2}|\d{1,2}時|\d{1,2}:\d{2})', first_line):
            # 2行目以降に日本語文字列が含まれていればタイトルとみなす
            for title_line in lines[1:]:
                if re.search(r'[\u3040-\u30ff\u4e00-\u9fffA-Za-z]', title_line):
                    return 'add'
    # 既存の簡易判定も残す
    if re.search(r'(\d{1,2}月\d{1,2}日|\d{1,2}時)', normalized_text):
        lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
        if len(lines) >= 2:
            return 'add'
    return None

def extract_title(text: str, operation_type: str = None) -> Optional[str]:
    """
    メッセージからタイトルを抽出。delete/update時は抽出できなければ必ず「予定」を返す。
    """
    try:
        normalized_text = normalize_text(text, keep_katakana=True)
        # 削除・更新操作の場合の特別処理
        if operation_type in ('delete', 'update'):
            # 既存の抽出ロジック
            lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
            for line in lines:
                if any(kw in line for kw in DELETE_KEYWORDS + UPDATE_KEYWORDS):
                    continue
                if re.search(r'[\u3040-\u30ff\u4e00-\u9fffA-Za-z]', line):
                    return line
            # どの行にもタイトルらしきものがなければ「予定」
            return '予定'
        # 通常の抽出ロジック
        # ...（既存のまま）...
        # 1行メッセージの場合は先頭の時刻（範囲含む）部分を除去し残りをタイトルとする
        lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
        if len(lines) == 1:
            line = lines[0]
            # 日付＋時刻範囲パターン
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
            
            # 日付・時刻のみの行はタイトルなしとみなす
            if not line or re.fullmatch(r'[\d/:年月日時分\-〜~～\s　]+', line):
                return None
            return line
            
        return None
    except Exception as e:
        logger.error(f"タイトル抽出エラー: {str(e)}")
        return None

def extract_title(text: str, operation_type: str = None) -> Optional[str]:
    """
    メッセージからタイトルを抽出。delete/update時は抽出できなければ必ず「予定」を返す。
    """
    try:
        normalized_text = normalize_text(text, keep_katakana=True)
        # 削除・更新操作の場合の特別処理
        if operation_type in ('delete', 'update'):
            # 既存の抽出ロジック
            lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
            for line in lines:
                if any(kw in line for kw in DELETE_KEYWORDS + UPDATE_KEYWORDS):
                    continue
                if re.search(r'[\u3040-\u30ff\u4e00-\u9fffA-Za-z]', line):
                    return line
            # どの行にもタイトルらしきものがなければ「予定」
            return '予定'
        # 通常の抽出ロジック
        # ...（既存のまま）...
        # 1行メッセージの場合は先頭の時刻（範囲含む）部分を除去し残りをタイトルとする
        lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
        if len(lines) == 1:
            line = lines[0]
            # 日付＋時刻範囲パターン
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
            
            # 日付・時刻のみの行はタイトルなしとみなす
            if not line or re.fullmatch(r'[\d/:年月日時分\-〜~～\s　]+', line):
                return None
            return line
            
        return None
    except Exception as e:
        logger.error(f"タイトル抽出エラー: {str(e)}")
        return None

class MessageParser:
    def _parse_date(self, message: str) -> dict:
        try:
            result = extract_datetime_from_message(message)
            return {
                'start_date': result.get('start_time'),
                'end_date': result.get('end_time'),
                'is_range': result.get('is_time_range', False)
            }
        except Exception as e:
            logger.error(f"日付の解析中にエラーが発生: {str(e)}")
            return {
                'start_date': None,
                'end_date': None,
                'is_range': False
            }

    def _parse_time(self, message: str) -> dict:
        try:
            result = extract_datetime_from_message(message)
            return {
                'start_time': result.get('start_time'),
                'end_time': result.get('end_time'),
                'is_range': result.get('is_time_range', False)
            }
        except Exception as e:
            logger.error(f"時刻の解析中にエラーが発生: {str(e)}")
            return {
                'start_time': None,
                'end_time': None,
                'is_range': False
            }