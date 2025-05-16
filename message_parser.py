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

logger = logging.getLogger(__name__)

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
    "追加", "登録", "入れる", "予定にする", "作る", "お願い", "入れと", "入れて", 
    "スケジュールに入れる", "予定に入れる", "予定に追加", "予定に登録",
    "予定を入れる", "予定を作る", "予定を登録", "予定を設定",
    "予定を立てる", "予定を組む", "予定を決める", "予定を設定する",
    "予定を入れて", "予定を作って", "予定を登録して", "予定を設定して",
    "予定を入れてください", "予定を作ってください", "予定を登録してください",
    "予定を設定してください", "予定を入れておいて", "予定を作っておいて",
    "予定を登録しておいて", "予定を設定しておいて",
    "予定を入れてほしい", "予定を作ってほしい", "予定を登録してほしい",
    "予定を設定してほしい", "予定を入れてください", "予定を作ってください",
    "予定を登録してください", "予定を設定してください",
    # より自然な表現
    "入れて", "入れてください", "入れてほしい", "入れてお願い",
    "作って", "作ってください", "作ってほしい", "作ってお願い",
    "登録して", "登録してください", "登録してほしい", "登録してお願い",
    "設定して", "設定してください", "設定してほしい", "設定してお願い",
    "立てて", "立ててください", "立ててほしい", "立ててお願い",
    "組んで", "組んでください", "組んでほしい", "組んでお願い",
    "決めて", "決めてください", "決めてほしい", "決めてお願い",
    # 短い表現
    "追加", "登録", "入れる", "作る", "設定", "立てる", "組む", "決める",
    # より自然な短い表現
    "入れて", "作って", "登録して", "設定して", "立てて", "組んで", "決めて",
    # 追加の自然な表現
    "を追加", "を登録", "を入れて", "を作って",
    "追加して", "追加してください", "追加してほしい", "追加してお願い",
    "予定追加", "予定登録", "予定作成", "予定設定",
    "打ち合わせ追加", "打ち合わせ登録", "打ち合わせ設定",
    "会議追加", "会議登録", "会議設定",
    "ミーティング追加", "ミーティング登録", "ミーティング設定",
    # より自然な表現（追加）
    "予定を入れておいて", "予定を作っておいて", "予定を登録しておいて",
    "予定を設定しておいて", "予定を入れておいてください", "予定を作っておいてください",
    "予定を登録しておいてください", "予定を設定しておいてください",
    "予定を入れておいてほしい", "予定を作っておいてほしい", "予定を登録しておいてほしい",
    "予定を設定しておいてほしい", "予定を入れておいてお願い", "予定を作っておいてお願い",
    "予定を登録しておいてお願い", "予定を設定しておいてお願い",
    # より自然な短い表現（追加）
    "入れておいて", "作っておいて", "登録しておいて", "設定しておいて",
    "入れておいてください", "作っておいてください", "登録しておいてください", "設定しておいてください",
    "入れておいてほしい", "作っておいてほしい", "登録しておいてほしい", "設定しておいてほしい",
    "入れておいてお願い", "作っておいてお願い", "登録しておいてお願い", "設定しておいてお願い",
]

# 予定削除のキーワード（より自然な表現に対応）
DELETE_KEYWORDS = [
    "削除", "消す", "消して", "削除して", "削除してください", "消してください",
    "キャンセル", "キャンセルして", "キャンセルしてください",
    "きゃんせる", "きゃんせるして", "きゃんせるしてください",
    "ｷｬﾝｾﾙ", "ｷｬﾝｾﾙして", "ｷｬﾝｾﾙしてください",
    "予定削除", "予定キャンセル", "予定取り消し",
    "打ち合わせ削除", "打ち合わせキャンセル", "打ち合わせ取り消し",
    "会議削除", "会議キャンセル", "会議取り消し",
    "ミーティング削除", "ミーティングキャンセル", "ミーティング取り消し"
]

# 予定変更のキーワード（より自然な表現に対応）
UPDATE_KEYWORDS = [
    "変更", "リスケ", "ずらす", "後ろ倒し", "前倒し", "時間変更", "予定をずらす",
    "予定を後ろ倒し", "予定を前倒し", "予定をリスケジュール",
    "予定を変更", "予定を修正", "予定を調整", "予定を更新",
    "予定を移動", "予定をずらす", "予定を変更する", "予定を修正する",
    "予定を変更してください", "予定を修正してください", "予定を調整してください",
    "予定を更新してください", "予定を移動してください", "予定をずらしてください",
    "予定を変更して", "予定を修正して", "予定を調整して", "予定を更新して",
    "予定を移動して", "予定をずらして", "予定を変更して", "予定を修正して",
    "予定を変更してほしい", "予定を修正してほしい", "予定を調整してほしい",
    "予定を更新してほしい", "予定を移動してほしい", "予定をずらしてほしい",
    "予定を変更してお願い", "予定を修正してお願い", "予定を調整してお願い",
    "予定を更新してほしい", "予定を移動してほしい", "予定をずらしてほしい",
    "予定を変更してください", "予定を修正してください", "予定を調整してください",
    "予定を更新してください", "予定を移動してください", "予定をずらしてください"
]

# 予定確認のキーワード（より自然な表現に対応）
READ_KEYWORDS = [
    "予定を教えて", "予定を確認", "予定は？", "予定は?",
    "スケジュールを教えて", "スケジュールを確認",
    "何がある", "何が入ってる", "空いてる",
    "予定ある", "予定入ってる", "予定は何",
    "予定を見せて", "予定を表示", "予定一覧",
    "スケジュール一覧", "スケジュールを見せて",
    "予定を見る", "スケジュールを見る",
    "予定確認", "スケジュール確認",
    "予定は", "スケジュールは",
    "予定を", "スケジュールを",
    "予定", "スケジュール",
    # より自然な表現（追加）
    "予定を教えてください", "予定を確認してください", "予定を教えてほしい", "予定を確認してほしい",
    "予定を教えてお願い", "予定を確認してお願い", "予定を教えておいて", "予定を確認しておいて",
    "予定を教えておいてください", "予定を確認しておいてください", "予定を教えておいてほしい", "予定を確認しておいてほしい",
    "予定を教えておいてお願い", "予定を確認しておいてお願い", "予定を教えておいてください", "予定を確認しておいてください",
    "予定を教えておいてほしい", "予定を確認しておいてほしい", "予定を教えておいてお願い", "予定を確認しておいてお願い",
    # より自然な短い表現（追加）
    "教えて", "確認して", "教えてください", "確認してください",
    "教えてほしい", "確認してほしい", "教えてお願い", "確認してお願い",
    "教えておいて", "確認しておいて", "教えておいてください", "確認しておいてください",
    "教えておいてほしい", "確認しておいてほしい", "教えておいてお願い", "確認しておいてお願い",
]

# 時間表現のパターンを拡充
TIME_PATTERNS = {
    'basic_time': r'(?P<hour>\d{1,2})時(?:(?P<minute>\d{1,2})分)?',
    'am_pm_time': r'(?P<period>午前|午後|朝|夜|夕方|深夜)(?P<hour>\d{1,2})時(?:(?P<minute>\d{1,2})分)?',
    'colon_time': r'(?P<hour>\d{1,2}):(?P<minute>\d{2})',
    'relative_time': r'(?P<relative>今|この|次の|前の)(?P<unit>時間|時間帯|時間枠)',
    'duration': r'(?P<duration>\d{1,2})時間(?:(?P<minutes>\d{1,2})分)?',
    'time_range': r'(?P<start_hour>\d{1,2})時(?:(?P<start_minute>\d{1,2})分)?(?:から|〜)(?P<end_hour>\d{1,2})時(?:(?P<end_minute>\d{1,2})分)?',
    'time_range_colon': r'(?P<start_hour>\d{1,2}):(?P<start_minute>\d{2})(?:から|〜)(?P<end_hour>\d{1,2}):(?P<end_minute>\d{2})',
    'time_range_am_pm': r'(?P<start_period>午前|午後|朝|夜|夕方|深夜)(?P<start_hour>\d{1,2})時(?:(?P<start_minute>\d{1,2})分)?(?:から|〜)(?P<end_period>午前|午後|朝|夜|夕方|深夜)?(?P<end_hour>\d{1,2})時(?:(?P<end_minute>\d{1,2})分)?',
    # より自然な表現（追加）
    'time_range_with_duration': r'(?P<start_hour>\d{1,2})時(?:(?P<start_minute>\d{1,2})分)?から(?P<duration>\d{1,2})時間(?:(?P<minutes>\d{1,2})分)?',
    'time_range_with_duration_colon': r'(?P<start_hour>\d{1,2}):(?P<start_minute>\d{2})から(?P<duration>\d{1,2})時間(?:(?P<minutes>\d{1,2})分)?',
    'time_range_with_duration_am_pm': r'(?P<period>午前|午後|朝|夜|夕方|深夜)(?P<start_hour>\d{1,2})時(?:(?P<start_minute>\d{1,2})分)?から(?P<duration>\d{1,2})時間(?:(?P<minutes>\d{1,2})分)?',
    'time_range_with_duration_relative': r'(?P<relative>今|この|次の|前の)(?P<unit>時間|時間帯|時間枠)から(?P<duration>\d{1,2})時間(?:(?P<minutes>\d{1,2})分)?',
}

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
JST = timezone(timedelta(hours=9))

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
    """
    メッセージを解析して操作タイプと必要な情報を抽出する
    
    Args:
        message (str): 解析するメッセージ
        current_time (datetime, optional): 現在時刻
        
    Returns:
        Dict: 解析結果
    """
    try:
        # 現在時刻の設定
        if current_time is None:
            current_time = datetime.now(pytz.timezone('Asia/Tokyo'))
            
        # 操作タイプの抽出
        operation_type = extract_operation_type(message)
        if not operation_type:
            return {'success': False, 'error': '操作タイプが特定できません。'}
            
        # 操作タイプに応じた情報抽出
        if operation_type == 'confirm':
            # 確認応答の場合
            return {
                'success': True,
                'operation_type': 'confirm'
            }
            
        elif operation_type == 'add':
            # 予定追加の場合
            datetime_info = extract_datetime_from_message(message, operation_type)
            if not datetime_info:
                return {'success': False, 'error': '日時情報が特定できません。'}
            title = extract_title(message)
            location = extract_location(message)
            person = extract_person(message)
            recurrence = extract_recurrence(message)
            # durationがあればend_timeを上書き
            if 'duration' in datetime_info:
                end_time = datetime_info['start_time'] + datetime_info['duration']
            else:
                end_time = datetime_info['end_time']
            return {
                'success': True,
                'operation_type': 'add',
                'title': title,
                'start_time': datetime_info['start_time'],
                'end_time': end_time,
                'location': location,
                'person': person,
                'recurrence': recurrence
            }
            
        elif operation_type == 'delete':
            # 予定削除の場合
            title = extract_title(message)
            datetime_info = extract_datetime_from_message(message, operation_type)
            return {
                'success': True,
                'operation_type': 'delete',
                'title': title,
                'start_time': datetime_info.get('start_time') if datetime_info else None,
                'end_time': datetime_info.get('end_time') if datetime_info else None
            }
                
        elif operation_type == 'update':
            # 予定更新の場合
            title = extract_title(message)
            # 2つ以上の日時が含まれている場合は両方抽出
            date_matches = list(re.finditer(r'(\d{1,2})[\/月](\d{1,2})[日\s　]*(\d{1,2}):?(\d{2})?', message))
            if len(date_matches) >= 2:
                # 1つ目
                m1 = date_matches[0]
                month1 = int(m1.group(1))
                day1 = int(m1.group(2))
                hour1 = int(m1.group(3))
                minute1 = int(m1.group(4)) if m1.group(4) else 0
                year = current_time.year
                start_time = datetime(year, month1, day1, hour1, minute1, tzinfo=pytz.timezone('Asia/Tokyo'))
                end_time = start_time + timedelta(hours=1)
                # 2つ目
                m2 = date_matches[1]
                month2 = int(m2.group(1))
                day2 = int(m2.group(2))
                hour2 = int(m2.group(3))
                minute2 = int(m2.group(4)) if m2.group(4) else 0
                new_start_time = datetime(year, month2, day2, hour2, minute2, tzinfo=pytz.timezone('Asia/Tokyo'))
                new_end_time = new_start_time + timedelta(hours=1)
                return {
                    'success': True,
                    'operation_type': 'update',
                    'title': title,
                    'start_time': start_time,
                    'end_time': end_time,
                    'new_start_time': new_start_time,
                    'new_end_time': new_end_time
                }
            # 1行ずつ分割して2つの時刻がある場合（例: 1行目と2行目）
            lines = [line.strip() for line in message.splitlines() if line.strip()]
            if len(lines) >= 2:
                dt1 = extract_datetime_from_message(lines[0], 'update')
                dt2 = extract_datetime_from_message(lines[1], 'update')
                if dt1.get('start_time') and dt2.get('start_time'):
                    return {
                        'success': True,
                        'operation_type': 'update',
                        'title': title,
                        'start_time': dt1['start_time'],
                        'end_time': dt1['end_time'],
                        'new_start_time': dt2['start_time'],
                        'new_end_time': dt2['end_time']
                    }
            # それ以外は従来通り
            datetime_info = extract_datetime_from_message(message, operation_type)
            return {
                'success': True,
                'operation_type': 'update',
                'title': title,
                'start_time': datetime_info.get('start_time') if datetime_info else None,
                'end_time': datetime_info.get('end_time') if datetime_info else None
            }
                
        elif operation_type == 'read':
            # 予定確認の場合
            datetime_info = extract_datetime_from_message(message, operation_type)
            return {
                'success': True,
                'operation_type': 'read',
                'start_time': datetime_info.get('start_time') if datetime_info else None,
                'end_time': datetime_info.get('end_time') if datetime_info else None
            }
            
        else:
            return {'success': False, 'error': '未対応の操作タイプです。'}
            
    except Exception as e:
        logger.error(f"メッセージ解析中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        print(f'★parse_message except: {e}')
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
            r'(\d{1,2}):(\d{2})へ'
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

def extract_title(text: str) -> Optional[str]:
    """メッセージからタイトルを抽出する（複数行対応・不要行除外・カタカナ保持）"""
    try:
        # 末尾の「を△△で追加してください」「を△△と追加してください」などを除去
        text = re.sub(r'を[^\sを]+で(追加|削除|変更|確認|教えて|表示)(してください)?$', '', text)
        text = re.sub(r'を[^\sを]+と(追加|削除|変更|確認|教えて|表示)(してください)?$', '', text)
        text = re.sub(r'(を)?(追加|削除|変更|確認)?して(ください)?$', '', text)
        text = re.sub(r'(を)?(追加|削除|変更|確認|教えて|表示)(してください)?$', '', text)
        # まず「X月Y日Z時からタイトル」や「X時からタイトル」パターンを優先的に抽出
        match = re.search(r'(?:\d{1,2}月)?\d{1,2}日\d{1,2}時(?:\d{1,2})分から(.+)', text)
        if not match:
            match = re.search(r'\d{1,2}時(?:\d{1,2})分から(.+)', text)
        if match:
            title_candidate = match.group(1).strip()
            # 末尾の不要な語句を除去
            title_candidate = re.sub(r'[。\n].*$', '', title_candidate)
            if title_candidate:
                return title_candidate
        # カタカナはひらがなに変換しない
        normalized_message = normalize_text(text, keep_katakana=True)
        lines = [line.strip() for line in normalized_message.splitlines() if line.strip()]
        exclude_patterns = [
            r'\d+時間半?', r'\d+時間', r'\d+分', r'オンライン', r'おんらいん'
        ]
        location = extract_location(normalized_message)
        # --- ここから追加 ---
        # 1行メッセージで日付・時刻＋タイトルの場合、日付・時刻部分を除去
        if len(lines) == 1:
            line = lines[0]
            # 日付＋時刻パターン
            line = re.sub(r'^(\d{1,2})[\/月](\d{1,2})[日\s　]*(\d{1,2}):(\d{2})', '', line)
            line = re.sub(r'^(\d{1,2})[\/月](\d{1,2})[日\s　]*(\d{1,2})時(\d{1,2})分?', '', line)
            line = re.sub(r'^(\d{1,2})[\/月](\d{1,2})[日\s　]*(\d{1,2})時', '', line)
            line = re.sub(r'^(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2})', '', line)
            line = re.sub(r'^(\d{1,2})月(\d{1,2})日(\d{1,2})時(\d{1,2})分?', '', line)
            line = re.sub(r'^(\d{1,2})月(\d{1,2})日(\d{1,2})時', '', line)
            # 先頭の空白や記号を除去
            line = re.sub(r'^[\s　:：,、。]+', '', line)
            # 日付・時刻だけの場合はNone
            if not line or re.fullmatch(r'[\d/:年月日時分\s　]+', line):
                return None
            return line
        # --- ここまで追加 ---
        for i, line in enumerate(lines):
            if re.search(r'\d+月\d+日', line) or re.search(r'\d+時', line):
                continue
            if any(re.search(pat, line) for pat in exclude_patterns):
                continue
            if location and location in line:
                continue
            return line
        return None
    except Exception as e:
        logger.error(f"タイトル抽出エラー: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def remove_datetime_expressions(text: str) -> str:
    """日時表現を削除する"""
    # 年月日
    text = re.sub(r'\d{1,4}年', '', text)  # 年を削除
    text = re.sub(r'\d{1,2}月', '', text)  # 月を削除
    text = re.sub(r'\d{1,2}日', '', text)  # 日を削除
    
    # 時刻（分を含む場合と含まない場合の両方に対応）
    text = re.sub(r'\d{1,2}時(?:\d{1,2})分)?', '', text)  # 分を含む時刻と含まない時刻の両方に対応
    
    # 相対日付表現を削除
    text = re.sub(r'(今日|明日|明後日|昨日|一昨日|今週|来週|再来週|先週|今月|来月|先月|今年|来年|去年|一昨年)', '', text)
    
    # 時間関連の表現を削除
    text = re.sub(r'(?:から|まで|翌日)', '', text)
    
    return text

def extract_location(text: str) -> Optional[str]:
    """メッセージから場所を抽出する（明示的なパターンと「オンライン」対応）"""
    try:
        normalized_message = normalize_text(text)
        
        # 「オンライン」が含まれていれば場所として返す
        if 'オンライン' in text or 'おんらいん' in normalized_message:
            return 'オンライン'
            
        # 明示的なパターン
        location_patterns = [
            r'場所は(?P<location>[^。\n]+)',
            r'会場は(?P<location>[^。\n]+)',
            r'会議室(?P<location>[A-Za-z0-9]+)',  # 会議室A, 会議室B1 などのパターン
            r'会議室(?P<location>[一二三四五六七八九十]+)',  # 会議室一, 会議室二 などのパターン
            r'会議室(?P<location>[0-9]+)',  # 会議室1, 会議室2 などのパターン
            r'会議室(?P<location>[A-Za-z0-9]+)で',  # 会議室Aで, 会議室B1で などのパターン
            r'会議室(?P<location>[一二三四五六七八九十]+)で',  # 会議室一で, 会議室二で などのパターン
            r'会議室(?P<location>[0-9]+)で',  # 会議室1で, 会議室2で などのパターン
            r'(?:^|\n)(?P<location>(?:東京都|大阪府|京都府|北海道|.+?[都道府県])?(?:千代田区|中央区|港区|新宿区|渋谷区|.+?[市区町村])?.+?(?:丁目|番地)?)',  # 住所っぽい表現
            r'(?:^|\n)(?P<location>(?:京橋|新橋|銀座|渋谷|新宿|品川|東京|大阪|名古屋|福岡|札幌|仙台|広島|神戸)[^。\n]*)'  # 主要な地名
        ]
        
        for pattern in location_patterns:
            match = re.search(pattern, normalized_message)
            if match:
                location = match.group('location').strip()
                # 数字のみ、または1文字だけの場所は無効とする
                if location.isdigit() or len(location) == 1:
                    continue
                # 会議室の場合、会議室という文字を付加して返す
                if pattern.startswith('会議室'):
                    return f'会議室{location}'
                return location
                
        # 場所が見つからない場合はNoneを返す
        return None
        
    except Exception as e:
        logger.error(f"場所抽出エラー: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def extract_person(text: str) -> str:
    """メッセージから人物情報を抽出する"""
    # 参加者情報を抽出
    person_match = re.search(r'参加者(?:は|が)?([^。、]+)', text)
    if person_match:
        person = person_match.group(1).strip()
        # 不要な文字を削除（末尾のみ）
        patterns_to_remove = [
            r'[をにでへとがの]?追加して$',
            r'[をにでへとがの]?追加$',
            r'[をにでへとがの]?削除して$',
            r'[をにでへとがの]?削除$',
            r'[をにでへとがの]?キャンセルして$',
            r'[をにでへとがの]?キャンセル$',
            r'[をにでへとがの]?して$'
        ]
        
        for pattern in patterns_to_remove:
            person = re.sub(pattern, '', person)
        
        # 空白を削除
        person = person.strip()
        
        logger.debug(f"抽出された参加者: {person}")
        return person
    
    # 参加者情報が見つからない場合はNoneを返す
    return None

def extract_recurrence(text: str) -> Optional[str]:
    """メッセージから繰り返し情報を抽出する"""
    try:
        logger.debug(f"繰り返し情報を抽出: {text}")
        
        normalized_message = normalize_text(text)
        
        # 繰り返しを表すパターン
        recurrence_patterns = [
            r'毎週(?P<weekday>月|火|水|木|金|土|日)曜日?',
            r'毎月(?P<day>\d{1,2})日',
            r'毎日',
            r'毎週',
            r'毎月',
            r'毎年'
        ]
        
        for pattern in recurrence_patterns:
            match = re.search(pattern, normalized_message)
            if match:
                if 'weekday' in match.groupdict():
                    weekday = WEEKDAYS[match.group('weekday')]
                    return f'FREQ=WEEKLY;BYDAY={weekday}'
                elif 'day' in match.groupdict():
                    day = match.group('day')
                    return f'FREQ=MONTHLY;BYMONTHDAY={day}'
                elif pattern == '毎日':
                    return 'FREQ=DAILY'
                elif pattern == '毎週':
                    return 'FREQ=WEEKLY'
                elif pattern == '毎月':
                    return 'FREQ=MONTHLY'
                elif pattern == '毎年':
                    return 'FREQ=YEARLY'
        
        logger.debug("抽出された繰り返し情報: None")
        return None
    except Exception as e:
        logger.error(f"繰り返し情報抽出エラー: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def extract_relative_datetime(message: str, now: datetime) -> Optional[Dict]:
    """相対日付表現から日時情報を抽出する"""
    # まず「今日から1週間」「今日から2週間」を最優先で判定
    if '今日から1週間' in message:
        start_time = datetime.combine(now.date(), time(0, 0), tzinfo=JST)
        end_time = start_time + timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=999999)
        return {
            'success': True,
            'start_time': start_time,
            'end_time': end_time
        }
    elif '今日から2週間' in message:
        start_time = datetime.combine(now.date(), time(0, 0), tzinfo=JST)
        end_time = start_time + timedelta(days=13, hours=23, minutes=59, seconds=59, microseconds=999999)
        return {
            'success': True,
            'start_time': start_time,
            'end_time': end_time
        }
    
    # 以下、1日分の相対日付判定
    target_date = None
    if re.search(r'今日', message):
        target_date = now.date()
    elif re.search(r'明日', message):
        target_date = (now + timedelta(days=1)).date()
    elif re.search(r'明後日', message):
        target_date = (now + timedelta(days=2)).date()
    elif re.search(r'昨日', message):
        target_date = (now - timedelta(days=1)).date()
    elif re.search(r'一昨日', message):
        target_date = (now - timedelta(days=2)).date()
    elif re.search(r'今週', message):
        # 今週の月曜日を取得
        monday = now - timedelta(days=now.weekday())
        target_date = monday.date()
        end_date = (monday + timedelta(days=6)).date()
        start_time = datetime.combine(target_date, time(0, 0), tzinfo=JST)
        end_time = datetime.combine(end_date, time(23, 59, 59, 999999), tzinfo=JST)
        return {
            'success': True,
            'start_time': start_time,
            'end_time': end_time
        }
    elif re.search(r'来週', message):
        # 来週の月曜日を取得
        monday = now - timedelta(days=now.weekday()) + timedelta(days=7)
        target_date = monday.date()
        end_date = (monday + timedelta(days=6)).date()
        start_time = datetime.combine(target_date, time(0, 0), tzinfo=JST)
        end_time = datetime.combine(end_date, time(23, 59, 59, 999999), tzinfo=JST)
        return {
            'success': True,
            'start_time': start_time,
            'end_time': end_time
        }
    elif re.search(r'再来週', message):
        # 再来週の月曜日を取得
        monday = now - timedelta(days=now.weekday()) + timedelta(days=14)
        target_date = monday.date()
        end_date = (monday + timedelta(days=6)).date()
        start_time = datetime.combine(target_date, time(0, 0), tzinfo=JST)
        end_time = datetime.combine(end_date, time(23, 59, 59, 999999), tzinfo=JST)
        return {
            'success': True,
            'start_time': start_time,
            'end_time': end_time
        }
    elif re.search(r'先週', message):
        # 先週の月曜日を取得
        monday = now - timedelta(days=now.weekday()) - timedelta(days=7)
        target_date = monday.date()
        end_date = (monday + timedelta(days=6)).date()
        start_time = datetime.combine(target_date, time(0, 0), tzinfo=JST)
        end_time = datetime.combine(end_date, time(23, 59, 59, 999999), tzinfo=JST)
        return {
            'success': True,
            'start_time': start_time,
            'end_time': end_time
        }
    elif re.search(r'今月', message):
        # 今月の1日を取得
        target_date = now.replace(day=1).date()
        # 来月の1日を取得して1日引く
        if now.month == 12:
            end_date = now.replace(year=now.year + 1, month=1, day=1).date() - timedelta(days=1)
        else:
            end_date = now.replace(month=now.month + 1, day=1).date() - timedelta(days=1)
        start_time = datetime.combine(target_date, time(0, 0), tzinfo=JST)
        end_time = datetime.combine(end_date, time(23, 59, 59, 999999), tzinfo=JST)
        return {
            'success': True,
            'start_time': start_time,
            'end_time': end_time
        }
    elif re.search(r'来月', message):
        # 来月の1日を取得
        if now.month == 12:
            target_date = now.replace(year=now.year + 1, month=1, day=1).date()
            end_date = now.replace(year=now.year + 1, month=2, day=1).date() - timedelta(days=1)
        else:
            target_date = now.replace(month=now.month + 1, day=1).date()
            end_date = now.replace(month=now.month + 2, day=1).date() - timedelta(days=1)
        start_time = datetime.combine(target_date, time(0, 0), tzinfo=JST)
        end_time = datetime.combine(end_date, time(23, 59, 59, 999999), tzinfo=JST)
        return {
            'success': True,
            'start_time': start_time,
            'end_time': end_time
        }
    elif re.search(r'先月', message):
        # 先月の1日を取得
        if now.month == 1:
            target_date = now.replace(year=now.year - 1, month=12, day=1).date()
            end_date = now.replace(day=1).date() - timedelta(days=1)
        else:
            target_date = now.replace(month=now.month - 1, day=1).date()
            end_date = now.replace(day=1).date() - timedelta(days=1)
        start_time = datetime.combine(target_date, time(0, 0), tzinfo=JST)
        end_time = datetime.combine(end_date, time(23, 59, 59, 999999), tzinfo=JST)
        return {
            'success': True,
            'start_time': start_time,
            'end_time': end_time
        }
    elif re.search(r'今年', message):
        # 今年の1月1日を取得
        target_date = now.replace(month=1, day=1).date()
        end_date = now.replace(month=12, day=31).date()
        start_time = datetime.combine(target_date, time(0, 0), tzinfo=JST)
        end_time = datetime.combine(end_date, time(23, 59, 59, 999999), tzinfo=JST)
        return {
            'success': True,
            'start_time': start_time,
            'end_time': end_time
        }
    elif re.search(r'来年', message):
        # 来年の1月1日を取得
        target_date = now.replace(year=now.year + 1, month=1, day=1).date()
        end_date = now.replace(year=now.year + 1, month=12, day=31).date()
        start_time = datetime.combine(target_date, time(0, 0), tzinfo=JST)
        end_time = datetime.combine(end_date, time(23, 59, 59, 999999), tzinfo=JST)
        return {
            'success': True,
            'start_time': start_time,
            'end_time': end_time
        }
    elif re.search(r'去年', message):
        # 去年の1月1日を取得
        target_date = now.replace(year=now.year - 1, month=1, day=1).date()
        end_date = now.replace(year=now.year - 1, month=12, day=31).date()
        start_time = datetime.combine(target_date, time(0, 0), tzinfo=JST)
        end_time = datetime.combine(end_date, time(23, 59, 59, 999999), tzinfo=JST)
        return {
            'success': True,
            'start_time': start_time,
            'end_time': end_time
        }
    elif re.search(r'一昨年', message):
        # 一昨年の1月1日を取得
        target_date = now.replace(year=now.year - 2, month=1, day=1).date()
        end_date = now.replace(year=now.year - 2, month=12, day=31).date()
        start_time = datetime.combine(target_date, time(0, 0), tzinfo=JST)
        end_time = datetime.combine(end_date, time(23, 59, 59, 999999), tzinfo=JST)
        return {
            'success': True,
            'start_time': start_time,
            'end_time': end_time
        }
    
    if target_date:
        start_time = datetime.combine(target_date, time(0, 0), tzinfo=JST)
        end_time = datetime.combine(target_date, time(23, 59, 59, 999999), tzinfo=JST)
        return {
            'success': True,
            'start_time': start_time,
            'end_time': end_time
        }
    
    return None

def extract_datetime_from_message(message: str, operation_type: str = None) -> Dict:
    """
    メッセージから日時情報を抽出する
    """
    try:
        # 現在時刻を取得
        now = datetime.now(pytz.timezone('Asia/Tokyo'))
        
        # 相対日付表現の処理
        relative_datetime = extract_relative_datetime(message, now)
        if relative_datetime and relative_datetime.get('success'):
            return relative_datetime
        
        # 5/16 10:00形式の処理（最優先でreturn）
        lines = message.splitlines()
        for line in lines:
            # 5/16 10:00
            match = re.search(r'(\d{1,2})/(\d{1,2})[\s　]*(\d{1,2}):(\d{2})', line)
            if match:
                month = int(match.group(1))
                day = int(match.group(2))
                hour = int(match.group(3))
                minute = int(match.group(4))
                year = now.year
                if (month < now.month) or (month == now.month and day < now.day):
                    year += 1
                start_time = datetime(year, month, day, hour, minute, tzinfo=pytz.timezone('Asia/Tokyo'))
                end_time = start_time + timedelta(hours=1)
                return {'success': True, 'start_time': start_time, 'end_time': end_time}
            # 5/16 10時
            match2 = re.search(r'(\d{1,2})/(\d{1,2})[\s　]*(\d{1,2})時', line)
            if match2:
                month = int(match2.group(1))
                day = int(match2.group(2))
                hour = int(match2.group(3))
                year = now.year
                if (month < now.month) or (month == now.month and day < now.day):
                    year += 1
                start_time = datetime(year, month, day, hour, 0, tzinfo=pytz.timezone('Asia/Tokyo'))
                end_time = start_time + timedelta(hours=1)
                return {'success': True, 'start_time': start_time, 'end_time': end_time}
        # ここまででreturnされなければ、他の抽出ロジックへ
        # 日付＋時刻がなければextract_timeで最初の時刻だけを厳密に使う
        start_time, end_time, is_all_day = extract_time(message, now)
        if start_time and end_time:
            return {
                'success': True,
                'start_time': start_time,
                'end_time': end_time,
                'is_all_day': is_all_day
            }
        # デフォルト値として今日の予定を返す
        if operation_type == 'read':
            start_time = datetime.combine(now.date(), time(0, 0), tzinfo=pytz.timezone('Asia/Tokyo'))
            end_time = datetime.combine(now.date(), time(23, 59, 59), tzinfo=pytz.timezone('Asia/Tokyo'))
            return {
                'success': True,
                'start_time': start_time,
                'end_time': end_time,
                'is_all_day': True
            }
        return {'success': False, 'error': '日時情報が特定できません。'}
    except Exception as e:
        logger.error(f"日時抽出エラー: {str(e)}")
        logger.error(traceback.format_exc())
        return {'success': False, 'error': str(e)}

def extract_time(message: str, current_time: datetime) -> Tuple[Optional[datetime], Optional[datetime], bool]:
    logger.debug(f"extract_time: message={message}")
    jst = timezone(timedelta(hours=+9))
    current_time = current_time.astimezone(jst)

    # 空白・改行を除去した文字列で判定
    msg_no_space = message.replace('　', '').replace(' ', '').replace('\n', '').replace('\r', '')

    # 「今日から2週間」を最優先で判定
    if '今日から2週間' in msg_no_space:
        print("★今日から2週間分岐に入りました")
        start_time = datetime.combine(current_time.date(), time(0, 0), tzinfo=jst)
        end_time = start_time + timedelta(days=13, hours=23, minutes=59)
        print(f"★今日から2週間 return直前: {start_time} から {end_time}")
        logger.debug("extract_time: 今日から2週間にヒット")
        logger.debug(f"今日から2週間の時間情報: {start_time} から {end_time}")
        return start_time, end_time, True

    # 「今日から1週間」の判定
    if '今日から1週間' in msg_no_space:
        print("★今日から1週間分岐に入りました")
        start_time = datetime.combine(current_time.date(), time(0, 0), tzinfo=jst)
        end_time = start_time + timedelta(days=6, hours=23, minutes=59)
        print(f"★今日から1週間 return直前: {start_time} から {end_time}")
        logger.debug("extract_time: 今日から1週間にヒット")
        logger.debug(f"今日から1週間の時間情報: {start_time} から {end_time}")
        return start_time, end_time, True

    # 月単位の表現を最優先で処理
    if '今月' in message:
        year = current_time.year
        month = current_time.month
        start_time = datetime(year, month, 1, 0, 0, tzinfo=jst)
        # 翌月の1日を求めて月末を計算
        if month == 12:
            next_month = datetime(year + 1, 1, 1, 0, 0, tzinfo=jst)
        else:
            next_month = datetime(year, month + 1, 1, 0, 0, tzinfo=jst)
        end_time = next_month - timedelta(minutes=1)
        logger.debug(f"今月の時間情報: {start_time} から {end_time}")
        return start_time, end_time, True

    # 週の開始日（月曜日）を取得
    def get_week_start(date):
        return date - timedelta(days=date.weekday())

    # 週単位の表現
    if '今週' in message:
        week_start = get_week_start(current_time.date())
        week_end = week_start + timedelta(days=6)
        start_time = datetime.combine(week_start, time(0, 0), tzinfo=jst)
        end_time = datetime.combine(week_end, time(23, 59), tzinfo=jst)
        logger.debug(f"今週の時間情報: {start_time} から {end_time}")
        return start_time, end_time, True
    if '来週' in message:
        week_start = get_week_start(current_time.date()) + timedelta(days=7)
        week_end = week_start + timedelta(days=6)
        start_time = datetime.combine(week_start, time(0, 0), tzinfo=jst)
        end_time = datetime.combine(week_end, time(23, 59), tzinfo=jst)
        logger.debug(f"来週の時間情報: {start_time} から {end_time}")
        return start_time, end_time, True
    if '先週' in message:
        week_start = get_week_start(current_time.date()) - timedelta(days=7)
        week_end = week_start + timedelta(days=6)
        start_time = datetime.combine(week_start, time(0, 0), tzinfo=jst)
        end_time = datetime.combine(week_end, time(23, 59), tzinfo=jst)
        logger.debug(f"先週の時間情報: {start_time} から {end_time}")
        return start_time, end_time, True

    # X月Y日Z時半パターン
    match = re.search(r'(\d{1,2})月(\d{1,2})日(\d{1,2})時半', message)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        hour = int(match.group(3))
        year = current_time.year
        if (month < current_time.month) or (month == current_time.month and day < current_time.day):
            year += 1
        start_time = datetime(year, month, day, hour, 30, tzinfo=jst)
        # デフォルトは1時間
        end_time = start_time + timedelta(hours=1)
        # 時間の長さを抽出
        duration = extract_duration(message)
        if duration:
            end_time = start_time + duration
        logger.debug(f"X月Y日Z時半パターン: {start_time} から {end_time}")
        return start_time, end_time, False

    # X月Y日Z時パターン
    match = re.search(r'(\d{1,2})月(\d{1,2})日(\d{1,2})時', message)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        hour = int(match.group(3))
        year = current_time.year
        if (month < current_time.month) or (month == current_time.month and day < current_time.day):
            year += 1
        start_time = datetime(year, month, day, hour, 0, tzinfo=jst)
        # デフォルトは1時間
        end_time = start_time + timedelta(hours=1)
        # 時間の長さを抽出
        duration = extract_duration(message)
        if duration:
            end_time = start_time + duration
        logger.debug(f"X月Y日Z時パターン: {start_time} から {end_time}")
        return start_time, end_time, False

    # X月Y日Z時W分パターン
    match = re.search(r'(\d{1,2})月(\d{1,2})日(\d{1,2})時(\d{1,2})分', message)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        hour = int(match.group(3))
        minute = int(match.group(4))
        year = current_time.year
        if (month < current_time.month) or (month == current_time.month and day < current_time.day):
            year += 1
        start_time = datetime(year, month, day, hour, minute, tzinfo=jst)
        end_time = start_time + timedelta(hours=1)
        logger.debug(f"X月Y日Z時W分パターン: {start_time} から {end_time}")
        return start_time, end_time, False

    # X月Y日Z時〜W時パターン
    match = re.search(r'(\d{1,2})月(\d{1,2})日(\d{1,2})時[〜~](\d{1,2})時', message)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        start_hour = int(match.group(3))
        end_hour = int(match.group(4))
        year = current_time.year
        if (month < current_time.month) or (month == current_time.month and day < current_time.day):
            year += 1
        # 修正: 必ずminute=0で初期化
        start_time = datetime(year, month, day, start_hour, 0, tzinfo=jst)
        end_time = datetime(year, month, day, end_hour, 0, tzinfo=jst)
        logger.debug(f"X月Y日Z時〜W時パターン: {start_time} から {end_time}")
        return start_time, end_time, False

    # X月Y日Z:W〜A:Bパターン
    match = re.search(r'(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2})[〜~](\d{1,2}):(\d{2})', message)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        start_hour = int(match.group(3))
        start_minute = int(match.group(4))
        end_hour = int(match.group(5))
        end_minute = int(match.group(6))
        year = current_time.year
        if (month < current_time.month) or (month == current_time.month and day < current_time.day):
            year += 1
        start_time = datetime(year, month, day, start_hour, start_minute, tzinfo=jst)
        end_time = datetime(year, month, day, end_hour, end_minute, tzinfo=jst)
        logger.debug(f"X月Y日Z:W〜A:Bパターン: {start_time} から {end_time}")
        return start_time, end_time, False

    # X月Y日Z時からN時間/分パターン
    match = re.search(r'(\d{1,2})月(\d{1,2})日(\d{1,2})時から(\d{1,2})時間', message)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        hour = int(match.group(3))
        duration = int(match.group(4))
        year = current_time.year
        if (month < current_time.month) or (month == current_time.month and day < current_time.day):
            year += 1
        start_time = datetime(year, month, day, hour, 0, tzinfo=jst)
        end_time = start_time + timedelta(hours=duration)
        logger.debug(f"X月Y日Z時からN時間パターン: {start_time} から {end_time}")
        return start_time, end_time, False
    match = re.search(r'(\d{1,2})月(\d{1,2})日(\d{1,2})時から(\d{1,2})分', message)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        hour = int(match.group(3))
        duration = int(match.group(4))
        year = current_time.year
        if (month < current_time.month) or (month == current_time.month and day < current_time.day):
            year += 1
        start_time = datetime(year, month, day, hour, 0, tzinfo=jst)
        end_time = start_time + timedelta(minutes=duration)
        logger.debug(f"X月Y日Z時からN分パターン: {start_time} から {end_time}")
        return start_time, end_time, False

    # X月Y日N時間/分パターン（所要時間のみ、デフォルト9:00開始）
    match = re.search(r'(\d{1,2})月(\d{1,2})日.*?(\d{1,2})時間', message)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        duration = int(match.group(3))
        year = current_time.year
        if (month < current_time.month) or (month == current_time.month and day < current_time.day):
            year += 1
        start_time = datetime.combine(current_time.date(), time(9, 0, 0), tzinfo=jst)
        end_time = start_time + timedelta(hours=duration)
        logger.debug(f"X月Y日N時間パターン: {start_time} から {end_time}")
        return start_time, end_time, False
    match = re.search(r'(\d{1,2})月(\d{1,2})日.*?(\d{1,2})分', message)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        duration = int(match.group(3))
        year = current_time.year
        if (month < current_time.month) or (month == current_time.month and day < current_time.day):
            year += 1
        start_time = datetime.combine(current_time.date(), time(9, 0, 0), tzinfo=jst)
        end_time = start_time + timedelta(minutes=duration)
        logger.debug(f"X月Y日N分パターン: {start_time} から {end_time}")
        return start_time, end_time, False

    # X月Y日パターン（時刻なし）
    match = re.search(r'(\d{1,2})月(\d{1,2})日', message)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = current_time.year
        if (month < current_time.month) or (month == current_time.month and day < current_time.day):
            year += 1
        target_date = date(year, month, day)
        start_time = datetime.combine(target_date, time(0, 0, 0), tzinfo=jst)
        end_time = datetime.combine(target_date, time(23, 59, 0), tzinfo=jst)
        logger.debug(f"X月Y日パターン: {start_time} から {end_time}")
        return start_time, end_time, True

    # 既存の日付パターンの処理
    date_patterns = {
        r'今日': current_time.date(),
        r'明日': (current_time + timedelta(days=1)).date(),
        r'明後日': (current_time + timedelta(days=2)).date(),
        r'来週': (current_time + timedelta(days=7)).date(),
        r'来月': (current_time.replace(day=1) + timedelta(days=32)).replace(day=1).date()
    }
    target_date = None
    for pattern, date in date_patterns.items():
        if re.search(pattern, message):
            target_date = date
            break
    if not target_date:
        target_date = current_time.date()
    # 時刻の抽出
    time_match = re.search(r'(\d{1,2})時から', message)
    if time_match:
        start_hour = int(time_match.group(1))
        start_time = datetime.combine(target_date, time(start_hour, 0), tzinfo=jst)
        end_time = start_time + timedelta(hours=1)
        logger.debug(f"時刻を抽出: {start_hour}時から")
        return start_time, end_time, False
    duration_match = re.search(r'(\d{1,2})時から.*?(\d{1,2})時間', message)
    if duration_match:
        start_hour = int(duration_match.group(1))
        duration = int(duration_match.group(2))
        start_time = datetime.combine(target_date, time(start_hour, 0), tzinfo=jst)
        end_time = start_time + timedelta(hours=duration)
        logger.debug(f"時刻と時間を抽出: {start_hour}時から{duration}時間")
        return start_time, end_time, False
    start_time = datetime.combine(target_date, time(0, 0), tzinfo=jst)
    end_time = datetime.combine(target_date, time(23, 59), tzinfo=jst)
    logger.debug(f"日付のみの時間情報: {start_time} から {end_time}")
    return start_time, end_time, True

    # 5/16 10:00形式の抽出
    for line in lines:
        match = re.search(r'(\d{1,2})/(\d{1,2})[\s　]+(\d{1,2}):(\d{2})', line)
        if match and not start_time:
            month = int(match.group(1))
            day = int(match.group(2))
            hour = int(match.group(3))
            minute = int(match.group(4))
            now = datetime.now(JST)
            year = now.year
            if (month < now.month) or (month == now.month and day < now.day):
                year += 1
            start_time = datetime(year, month, day, hour, minute, tzinfo=JST)
            end_time = start_time + timedelta(hours=1)

def extract_duration(message: str) -> Optional[timedelta]:
    """
    メッセージから時間の長さを抽出する
    Args:
        message: 入力メッセージ
    Returns:
        Optional[timedelta]: 時間の長さ（見つからない場合はNone）
    """
    try:
        # 全角数字を半角に正規化
        message = normalize_digits(message)
        # 1時間半のパターン
        if '1時間半' in message or '１時間半' in message:
            return timedelta(minutes=90)
        # X時間半のパターン
        match = re.search(r'(\d+)時間半', message)
        if match:
            hours = int(match.group(1))
            return timedelta(minutes=hours * 60 + 30)
        # X.Y時間のパターン（小数点を含む時間）
        match = re.search(r'(\d+)\.(\d+)時間', message)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2)) * 6  # 0.5時間 = 30分
            return timedelta(hours=hours, minutes=minutes)
        # X時間Y分のパターン
        match = re.search(r'(\d+)時間(\d+)分', message)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            return timedelta(hours=hours, minutes=minutes)
        # X時間のパターン
        match = re.search(r'(\d+)時間', message)
        if match:
            hours = int(match.group(1))
            return timedelta(hours=hours)
        # X分に変更/X分だけ/X分間/X分パターン
        match = re.search(r'(\d{1,3})分(に変更|だけ|間|)', message)
        if match:
            minutes = int(match.group(1))
            return timedelta(minutes=minutes)
        # X分のパターン（単独）
        match = re.search(r'(\d{1,3})分', message)
        if match:
            minutes = int(match.group(1))
            return timedelta(minutes=minutes)
        return None
    except Exception as e:
        logger.error(f"時間の長さ抽出エラー: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def detect_operation_type(message: str, extracted: dict) -> str:
    """
    抽出済みの日時やタイトルから、操作タイプを補完的に推論する
    """
    for word in ADD_KEYWORDS:
        if word in message:
            return "add"
    for word in DELETE_KEYWORDS:
        if word in message:
            return "delete"
    for word in UPDATE_KEYWORDS:
        if word in message:
            return "update"
    for word in READ_KEYWORDS:
        if word in message:
            return "read"
    # ⬇️ キーワードがなければ、内容から推論（start_timeまたはtitleのどちらか一方でもあれば追加とみなす）
    if extracted.get("start_time") or extracted.get("title"):
        return "add"
    return None

# parse_messageの中のoperation_type判定部分を修正

def parse_message(message: str, current_time: datetime = None) -> Dict:
    """
    メッセージを解析して操作タイプと必要な情報を抽出する
    """
    try:
        if current_time is None:
            current_time = datetime.now(pytz.timezone('Asia/Tokyo'))
        operation_type = extract_operation_type(message)
        # まず従来の方法でoperation_typeを抽出
        # ここで特定できなければ、内容から推論
        if not operation_type:
            # 日時やタイトルを抽出して推論
            datetime_info = extract_datetime_from_message(message)
            title = extract_title(message)
            extracted = {}
            if datetime_info:
                extracted["start_time"] = datetime_info.get("start_time")
            if title:
                extracted["title"] = title
            operation_type = detect_operation_type(message, extracted)
            if not operation_type:
                return {'success': False, 'error': '操作タイプが特定できません。'}
        # 以下、従来のoperation_typeごとの処理はそのまま
        if operation_type == 'confirm':
            # 確認応答の場合
            return {
                'success': True,
                'operation_type': 'confirm'
            }
            
        elif operation_type == 'add':
            # 予定追加の場合
            datetime_info = extract_datetime_from_message(message, operation_type)
            if not datetime_info:
                return {'success': False, 'error': '日時情報が特定できません。'}
            title = extract_title(message)
            location = extract_location(message)
            person = extract_person(message)
            recurrence = extract_recurrence(message)
            # durationがあればend_timeを上書き
            if 'duration' in datetime_info:
                end_time = datetime_info['start_time'] + datetime_info['duration']
            else:
                end_time = datetime_info['end_time']
            return {
                'success': True,
                'operation_type': 'add',
                'title': title,
                'start_time': datetime_info['start_time'],
                'end_time': end_time,
                'location': location,
                'person': person,
                'recurrence': recurrence
            }
            
        elif operation_type == 'delete':
            # 予定削除の場合
            title = extract_title(message)
            datetime_info = extract_datetime_from_message(message, operation_type)
            return {
                'success': True,
                'operation_type': 'delete',
                'title': title,
                'start_time': datetime_info.get('start_time') if datetime_info else None,
                'end_time': datetime_info.get('end_time') if datetime_info else None
            }
                
        elif operation_type == 'update':
            # 予定更新の場合
            title = extract_title(message)
            # 2つ以上の日時が含まれている場合は両方抽出
            date_matches = list(re.finditer(r'(\d{1,2})[\/月](\d{1,2})[日\s　]*(\d{1,2}):?(\d{2})?', message))
            if len(date_matches) >= 2:
                # 1つ目
                m1 = date_matches[0]
                month1 = int(m1.group(1))
                day1 = int(m1.group(2))
                hour1 = int(m1.group(3))
                minute1 = int(m1.group(4)) if m1.group(4) else 0
                year = current_time.year
                start_time = datetime(year, month1, day1, hour1, minute1, tzinfo=pytz.timezone('Asia/Tokyo'))
                end_time = start_time + timedelta(hours=1)
                # 2つ目
                m2 = date_matches[1]
                month2 = int(m2.group(1))
                day2 = int(m2.group(2))
                hour2 = int(m2.group(3))
                minute2 = int(m2.group(4)) if m2.group(4) else 0
                new_start_time = datetime(year, month2, day2, hour2, minute2, tzinfo=pytz.timezone('Asia/Tokyo'))
                new_end_time = new_start_time + timedelta(hours=1)
                return {
                    'success': True,
                    'operation_type': 'update',
                    'title': title,
                    'start_time': start_time,
                    'end_time': end_time,
                    'new_start_time': new_start_time,
                    'new_end_time': new_end_time
                }
            # 1行ずつ分割して2つの時刻がある場合（例: 1行目と2行目）
            lines = [line.strip() for line in message.splitlines() if line.strip()]
            if len(lines) >= 2:
                dt1 = extract_datetime_from_message(lines[0], 'update')
                dt2 = extract_datetime_from_message(lines[1], 'update')
                if dt1.get('start_time') and dt2.get('start_time'):
                    return {
                        'success': True,
                        'operation_type': 'update',
                        'title': title,
                        'start_time': dt1['start_time'],
                        'end_time': dt1['end_time'],
                        'new_start_time': dt2['start_time'],
                        'new_end_time': dt2['end_time']
                    }
            # それ以外は従来通り
            datetime_info = extract_datetime_from_message(message, operation_type)
            return {
                'success': True,
                'operation_type': 'update',
                'title': title,
                'start_time': datetime_info.get('start_time') if datetime_info else None,
                'end_time': datetime_info.get('end_time') if datetime_info else None
            }
                
        elif operation_type == 'read':
            # 予定確認の場合
            datetime_info = extract_datetime_from_message(message, operation_type)
            return {
                'success': True,
                'operation_type': 'read',
                'start_time': datetime_info.get('start_time') if datetime_info else None,
                'end_time': datetime_info.get('end_time') if datetime_info else None
            }
            
        else:
            return {'success': False, 'error': '未対応の操作タイプです。'}
            
    except Exception as e:
        logger.error(f"メッセージ解析中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        print(f'★parse_message except: {e}')
        return {'success': False, 'error': str(e)}