import logging
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import datetime
import json

# ロギングの設定
logger = logging.getLogger(__name__)

# スコープの設定
SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_calendar_service(line_user_id):
    """Googleカレンダーのサービスを取得する（OAuth認証）"""
    try:
        with open('user_tokens.json', 'r') as f:
            tokens = json.load(f)
        user_token = tokens.get(line_user_id)
        if not user_token:
            raise Exception("Google連携が必要です")
        credentials = Credentials(
            token=user_token['token'],
            refresh_token=user_token['refresh_token'],
            token_uri=user_token['token_uri'],
            client_id=user_token['client_id'],
            client_secret=user_token['client_secret'],
            scopes=user_token['scopes']
        )
    service = build('calendar', 'v3', credentials=credentials)
    return service
    except Exception as e:
        logger.error(f"❌ サービス取得失敗: {str(e)}")
        raise e

def add_event(line_user_id, summary, start_time, end_time, description=None, calendar_id='primary'):
    """カレンダーにイベントを追加する（OAuth認証）"""
    try:
        logger.info("📅 カレンダー登録開始:")
        logger.info(f"  タイトル: {summary}")
        logger.info(f"  開始時間: {start_time}")
        logger.info(f"  終了時間: {end_time}")
        logger.info(f"  説明: {description if description else '(なし)'}")
        logger.info(f"  カレンダーID: {calendar_id}")
        
        service = get_calendar_service(line_user_id)
        
        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Asia/Tokyo',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Asia/Tokyo',
            },
        }
        
        result = service.events().insert(calendarId=calendar_id, body=event).execute()
        logger.info(f"✅ イベント追加成功: {result.get('htmlLink')}")
        return result
        
    except Exception as e:
        logger.error(f"❌ イベント追加失敗: {str(e)}")
        raise e

def parse_datetime(date_str, time_str):
    """日付と時間の文字列をdatetimeオブジェクトに変換する"""
    # 日付のパース（例: "2024/03/20"）
    year, month, day = map(int, date_str.split('/'))
    
    # 時間のパース（例: "14:30"）
    hour, minute = map(int, time_str.split(':'))
    
    return datetime.datetime(year, month, day, hour, minute) 