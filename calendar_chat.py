from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone, time
import logging
import os
import warnings
import re
from dateutil import parser
from typing import List, Dict, Any, Optional, Tuple
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
import pytz
import traceback
import json
import tempfile

# 警告メッセージを抑制
warnings.filterwarnings('ignore', message='file_cache is only supported with oauth2client<4.0.0')

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_credentials():
    """環境変数から認証情報を取得し、一時ファイルとして保存する"""
    try:
        # 直接credentials.jsonを使用
        credentials_file = 'credentials.json'
        if not os.path.exists(credentials_file):
            raise ValueError("credentials.jsonファイルが見つかりません")
        return credentials_file
    except Exception as e:
        logger.error(f"認証情報の取得に失敗: {str(e)}")
        raise ValueError("認証情報の取得に失敗しました")

class CalendarChat:
    def __init__(self, line_user_id: str, calendar_id: str):
        """
        初期化（OAuth認証対応）
        Args:
            line_user_id (str): LINEユーザーID
            calendar_id (str): 操作対象のカレンダーID
        """
        self.line_user_id = line_user_id
        self.calendar_id = calendar_id
        self.service = None
        self.timezone = pytz.timezone('Asia/Tokyo')
        self.initialize_service()

    def initialize_service(self):
        """Google Calendar APIのサービスを初期化する（OAuth認証）"""
        try:
            with open('user_tokens.json', 'r') as f:
                tokens = json.load(f)
            user_token = tokens.get(self.line_user_id)
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
            self.service = build('calendar', 'v3', credentials=credentials)
            logger.info("Google Calendar APIサービスが正常に初期化されました（OAuth認証）")
        except Exception as e:
            logger.error(f"サービスの初期化に失敗: {str(e)}")
            logger.error("詳細なエラー情報:", exc_info=True)
            raise

    def get_events(self, time_min: datetime = None, time_max: datetime = None) -> list:
        """Get calendar events for the specified time range."""
        try:
            if time_min and isinstance(time_min, str):
                time_min = datetime.fromisoformat(time_min)
            if time_max and isinstance(time_max, str):
                time_max = datetime.fromisoformat(time_max)
            if not self.service:
                logger.error("Google Calendar APIサービスが初期化されていません")
                return []

            # タイムゾーンの設定
            if time_min and time_min.tzinfo is None:
                time_min = self.timezone.localize(time_min)
            if time_max and time_max.tzinfo is None:
                time_max = self.timezone.localize(time_max)

            # 予定を取得
            events_result = self.service.events().list(
                calendarId='mmms.dy.23@gmail.com',
                timeMin=time_min.isoformat() if time_min else None,
                timeMax=time_max.isoformat() if time_max else None,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            logger.info(f"予定を取得しました: {len(events_result.get('items', []))}件")
            return events_result.get('items', [])

        except Exception as e:
            logger.error(f"イベント取得中にエラーが発生: {str(e)}")
            logger.error("詳細なエラー情報:", exc_info=True)
            return []  # エラー時は空のリストを返す

    def format_events(self, events: list) -> str:
        """
        予定一覧を整形して返す（改善版）
        
        Args:
            events (list): 予定のリスト
            
        Returns:
            str: 整形された予定一覧
        """
        if not events:
            today = datetime.now(self.timezone)
            date_str = today.strftime('%Y年%m月%d日')
            return (
                f"📅 {date_str}の予定は特にありません。\n\n"
                f"新しい予定を追加する場合は、以下のような形式でメッセージを送ってください：\n"
                f"・「明日の15時に会議を追加して」\n"
                f"・「来週の月曜日、10時から12時まで打ち合わせを入れて」\n"
                f"・「今週の金曜日、14時からカフェで打ち合わせ」"
            )

        events_by_date = {}
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            # 型チェック追加
            if isinstance(start, str):
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            else:
                start_dt = start
            if isinstance(end, str):
                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
            else:
                end_dt = end
            start_dt = start_dt.astimezone(self.timezone)
            end_dt = end_dt.astimezone(self.timezone)
            date_key = start_dt.strftime('%Y/%m/%d')
            weekday = ['月', '火', '水', '木', '金', '土', '日'][start_dt.weekday()]
            time_str = f"{start_dt.strftime('%H:%M')}〜{end_dt.strftime('%H:%M')}"
            event_details = []
            event_details.append(f"📌 {event.get('summary', '予定なし')}")
            event_details.append(f"⏰ {time_str}")
            if event.get('location'):
                event_details.append(f"📍 {event['location']}")
            if event.get('description'):
                event_details.append(f"📝 {event['description']}")
            event_str = "\n".join(event_details)
            if date_key not in events_by_date:
                events_by_date[date_key] = {
                    'weekday': weekday,
                    'events': []
                }
            events_by_date[date_key]['events'].append(event_str)
        formatted_events = []
        formatted_events.append("📅 予定一覧")
        formatted_events.append("=" * 20)
        for date in sorted(events_by_date.keys()):
            date_info = events_by_date[date]
            formatted_events.append(f"\n■ {date}（{date_info['weekday']}）")
            formatted_events.extend([f"  {event}" for event in date_info['events']])
            formatted_events.append("-" * 20)
        free_slots = self.get_free_time_slots(
            datetime.now(self.timezone).replace(hour=0, minute=0, second=0, microsecond=0),
            30
        )
        if free_slots:
            formatted_events.append("\n⏰ 空き時間")
            formatted_events.append("=" * 20)
            formatted_events.extend([f"  {slot}" for slot in self.format_free_time_slots(free_slots)])
        else:
            formatted_events.append("\n⏰ 空き時間はありません")
        return "\n".join(formatted_events)

    def check_availability(self, start_time: datetime, end_time: datetime) -> List[Dict]:
        """
        指定された時間帯の予定の重複をチェックする（改善版）
        
        Args:
            start_time: 開始時間
            end_time: 終了時間
            
        Returns:
            List[Dict]: 重複する予定のリスト
        """
        try:
            start_time = start_time.astimezone(self.timezone)
            end_time = end_time.astimezone(self.timezone)
            logger.info(f"Checking availability from {start_time} to {end_time}")
            events_result = self.service.events().list(
                calendarId='mmms.dy.23@gmail.com',
                timeMin=start_time.isoformat(),
                timeMax=end_time.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            overlapping_events = []
            for event in events_result.get('items', []):
                event_start = event['start'].get('dateTime')
                event_end = event['end'].get('dateTime')
                if event_start and event_end:
                    # 型チェック追加
                    if isinstance(event_start, str):
                        event_start = datetime.fromisoformat(event_start.replace('Z', '+00:00'))
                    if isinstance(event_end, str):
                        event_end = datetime.fromisoformat(event_end.replace('Z', '+00:00'))
                    event_start = event_start.astimezone(self.timezone)
                    event_end = event_end.astimezone(self.timezone)
                    if (event_start < end_time and event_end > start_time and event_start != end_time and event_end != start_time):
                        overlapping_events.append({
                            'summary': event.get('summary', '予定なし'),
                            'start': event_start,
                            'end': event_end,
                            'location': event.get('location', ''),
                            'description': event.get('description', '')
                        })
            return overlapping_events
        except Exception as e:
            logger.error(f"Error checking availability: {str(e)}")
            raise

    def delete_event(self, start_time: datetime, end_time: datetime) -> bool:
        """
        指定された時間帯の予定を削除する
        
        Args:
            start_time (datetime): 予定の開始時刻
            end_time (datetime): 予定の終了時刻
            
        Returns:
            bool: 削除に成功したかどうか
        """
        try:
            # タイムゾーンの設定
            if start_time.tzinfo is None:
                start_time = self.timezone.localize(start_time)
            if end_time.tzinfo is None:
                end_time = self.timezone.localize(end_time)
            
            # 指定された時間帯の予定を検索
            events = self.get_events(time_min=start_time, time_max=end_time)
            
            if not events:
                logger.warning(f"指定された時間（{start_time.isoformat()}〜{end_time.isoformat()}）に予定が見つかりません")
                return False
            
            # 予定を削除
            for event in events:
                event_id = event['id']
                try:
                    self.service.events().delete(
                        calendarId='mmms.dy.23@gmail.com',
                        eventId=event_id
                    ).execute()
                    logger.info(f"予定を削除しました: {event.get('summary')} ({event.get('start')} - {event.get('end')})")
                except Exception as e:
                    logger.error(f"予定の削除中にエラーが発生: {str(e)}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"予定の削除中にエラーが発生: {str(e)}")
            return False

    def update_event(self, event_id: str, start_time: datetime, end_time: datetime, title: str = None, location: str = None) -> Dict[str, Any]:
        """
        予定を更新する
        
        Args:
            event_id (str): 更新する予定のID
            start_time (datetime): 開始時間
            end_time (datetime): 終了時間
            title (str, optional): 予定のタイトル
            location (str, optional): 場所
            
        Returns:
            Dict[str, Any]: 更新された予定の情報
        """
        try:
            # タイムゾーン情報を確実に設定
            if start_time.tzinfo is None:
                start_time = self.timezone.localize(start_time)
            if end_time.tzinfo is None:
                end_time = self.timezone.localize(end_time)
            
            # 予定の詳細を取得
            event = self.service.events().get(calendarId='mmms.dy.23@gmail.com', eventId=event_id).execute()
            
            # 更新する情報を設定
            event['start'] = {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Asia/Tokyo'
            }
            event['end'] = {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Asia/Tokyo'
            }
            
            if title:
                event['summary'] = title
            
            if location:
                event['location'] = location
            
            # 予定を更新
            updated_event = self.service.events().update(
                calendarId='mmms.dy.23@gmail.com',
                eventId=event_id,
                body=event
            ).execute()
            
            logger.info(f"予定を更新しました: {updated_event.get('summary')} ({start_time} - {end_time})")
            return updated_event
            
        except Exception as e:
            logger.error(f"予定の更新中にエラーが発生しました: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def create_event(self, summary: str, start_time: datetime, end_time: datetime,
                    location: Optional[str] = None, description: Optional[str] = None,
                    recurrence: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """
        予定を作成する
        
        Args:
            summary (str): 予定のタイトル
            start_time (datetime): 開始日時
            end_time (datetime): 終了日時
            location (Optional[str]): 場所
            description (Optional[str]): 説明
            recurrence (Optional[Dict[str, Any]]): 繰り返し情報
            
        Returns:
            Optional[str]: 作成された予定のID。失敗した場合はNone
        """
        try:
            # タイムゾーンを設定
            if start_time.tzinfo is None:
                start_time = self.timezone.localize(start_time)
            else:
                start_time = start_time.astimezone(self.timezone)
                
            if end_time.tzinfo is None:
                end_time = self.timezone.localize(end_time)
            else:
                end_time = end_time.astimezone(self.timezone)
            
            # 予定の詳細を構築
            event = {
                'summary': summary,
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'Asia/Tokyo',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'Asia/Tokyo',
                },
            }
            
            # オプションの情報を追加
            if location:
                event['location'] = location
            if description:
                event['description'] = description
            if recurrence:
                event['recurrence'] = [self._format_recurrence_rule(recurrence)]
            
            # 予定を作成
            created_event = self.service.events().insert(
                calendarId='mmms.dy.23@gmail.com',
                body=event
            ).execute()
            
            logger.info(f"Event created successfully: {created_event['id']}")
            return created_event['id']
            
        except Exception as e:
            logger.error(f"Failed to create event: {str(e)}")
            return None

    def list_events(self, time_min: Optional[datetime] = None,
                   time_max: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        予定の一覧を取得する
        
        Args:
            time_min (Optional[datetime]): 開始日時
            time_max (Optional[datetime]): 終了日時
            
        Returns:
            List[Dict[str, Any]]: 予定の一覧
        """
        try:
            # デフォルトの期間を設定
            if not time_min:
                time_min = datetime.now()
            if not time_max:
                time_max = time_min + timedelta(days=7)
            
            # タイムゾーンを設定
            time_min = self.timezone.localize(time_min)
            time_max = self.timezone.localize(time_max)
            
            # 予定を取得
            events_result = self.service.events().list(
                calendarId='mmms.dy.23@gmail.com',
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            logger.info(f"Retrieved {len(events)} events")
            return events
            
        except Exception as e:
            logger.error(f"Failed to list events: {str(e)}")
            return []

    def _format_recurrence_rule(self, recurrence: Dict[str, Any]) -> str:
        """
        繰り返し情報をiCalendar形式の文字列に変換する
        
        Args:
            recurrence (Dict[str, Any]): 繰り返し情報
                - freq: 頻度（daily, weekly, monthly, yearly）
                - interval: 間隔
                - count: 繰り返し回数
                - until: 終了日
                - byday: 曜日
                - bymonthday: 日付
            
        Returns:
            str: iCalendar形式の繰り返しルール
        """
        try:
            rule = f"RRULE:FREQ={recurrence['freq'].upper()}"
            
            if recurrence.get('interval'):
                rule += f";INTERVAL={recurrence['interval']}"
            
            if recurrence.get('count'):
                rule += f";COUNT={recurrence['count']}"
            
            if recurrence.get('until'):
                rule += f";UNTIL={recurrence['until'].strftime('%Y%m%dT%H%M%SZ')}"
            
            if recurrence.get('byday'):
                rule += f";BYDAY={recurrence['byday']}"
            
            if recurrence.get('bymonthday'):
                rule += f";BYMONTHDAY={recurrence['bymonthday']}"
            
            return rule
            
        except Exception as e:
            logger.error(f"Failed to format recurrence rule: {str(e)}")
            return ""

    def find_events_by_date_and_title(self, target_date: datetime, title_keyword: str = None) -> list:
        """
        指定された日付とタイトルのキーワードに一致する予定を検索する
        
        Args:
            target_date (datetime): 検索する日時
            title_keyword (str, optional): タイトルのキーワード
            
        Returns:
            list: 見つかった予定のリスト
        """
        try:
            # タイムゾーンを日本時間に設定
            jst = timezone(timedelta(hours=9))
            if target_date.tzinfo is None:
                target_date = target_date.replace(tzinfo=jst)
            
            # 指定された時刻の前後1時間を検索範囲とする
            search_start = target_date - timedelta(hours=1)
            search_end = target_date + timedelta(hours=1)
            
            logger.info(f"Searching for events between {search_start.isoformat()} and {search_end.isoformat()}")
            if title_keyword:
                logger.info(f"With title keyword: {title_keyword}")
            
            events_result = self.service.events().list(
                calendarId='mmms.dy.23@gmail.com',
                timeMin=search_start.isoformat(),
                timeMax=search_end.isoformat(),
                singleEvents=True,
                orderBy='startTime',
                timeZone='Asia/Tokyo'
            ).execute()
            
            events = events_result.get('items', [])
            matching_events = []
            
            for event in events:
                event_summary = event.get('summary', '').lower()
                # タイトルキーワードが指定されていない場合は、時間のみで検索
                if title_keyword is None or any(keyword.lower() in event_summary for keyword in title_keyword.split()):
                    # 開始・終了時刻をJSTに変換
                    start = event['start'].get('dateTime', event['start'].get('date'))
                    end = event['end'].get('dateTime', event['end'].get('date'))
                    
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00')).astimezone(jst)
                    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00')).astimezone(jst)
                    
                    # 指定された時刻に最も近い予定を対象とする
                    time_diff = abs((start_dt - target_date).total_seconds())
                    if time_diff <= 3600:  # 1時間以内
                        matching_events.append({
                            'id': event['id'],
                            'summary': event.get('summary', '予定なし'),
                            'start': start_dt,
                            'end': end_dt,
                            'original_event': event
                        })
            
            # 時間差でソート
            matching_events.sort(key=lambda x: abs((x['start'] - target_date).total_seconds()))
            return matching_events
            
        except Exception as e:
            logger.error(f"Error finding events: {str(e)}")
            logger.error("Full error details:", exc_info=True)
            return []

    def reschedule_event(self, target_date: datetime, title_keyword: str, new_start_time: datetime, new_duration: int = None) -> tuple[bool, str]:
        """
        指定された日付とタイトルの予定を新しい時間に変更する
        
        Args:
            target_date (datetime): 対象の予定の日付
            title_keyword (str): 予定のタイトルのキーワード
            new_start_time (datetime): 新しい開始時間
            new_duration (int, optional): 新しい予定の長さ（分）
            
        Returns:
            tuple[bool, str]: (成功したかどうか, メッセージ)
        """
        try:
            # タイムゾーンを日本時間に設定
            jst = timezone(timedelta(hours=9))
            if target_date.tzinfo is None:
                target_date = target_date.replace(tzinfo=jst)
            if new_start_time.tzinfo is None:
                new_start_time = new_start_time.replace(tzinfo=jst)
            
            # 対象の予定を検索
            events = self.find_events_by_date_and_title(target_date, title_keyword)
            
            if not events:
                return False, f"{target_date.strftime('%Y/%m/%d')}の「{title_keyword}」という予定は見つかりませんでした。"
     
            if len(events) > 1:
                # 複数の予定が見つかった場合は、時間を含めて表示
                events_info = "\n".join([
                    f"・{event['summary']} ({event['start'].strftime('%H:%M')}〜{event['end'].strftime('%H:%M')})"
                    for event in events
                ])
                return False, f"複数の予定が見つかりました。どの予定を変更するか、時間を指定してください：\n{events_info}"
            
            target_event = events[0]
            
            # 新しい終了時間を設定
            if new_duration is not None:
                new_end_time = new_start_time + timedelta(minutes=new_duration)
            else:
                # 元の予定の長さを維持
                original_duration = (target_event['end'] - target_event['start']).total_seconds() / 60
                new_end_time = new_start_time + timedelta(minutes=int(original_duration))
            
            # 予定の重複をチェック（自分自身は除外）
            events_result = self.service.events().list(
                calendarId='mmms.dy.23@gmail.com',
                timeMin=new_start_time.isoformat(),
                timeMax=new_end_time.isoformat(),
                singleEvents=True,
                orderBy='startTime',
                timeZone='Asia/Tokyo'
            ).execute()
            
            conflicts = []
            for event in events_result.get('items', []):
                # 自分自身の予定はスキップ
                if event['id'] == target_event['id']:
                    continue
                    
                event_start = event['start'].get('dateTime', event['start'].get('date'))
                event_end = event['end'].get('dateTime', event['end'].get('date'))
                
                # 日時をdatetimeオブジェクトに変換
                event_start_dt = datetime.fromisoformat(event_start.replace('Z', '+00:00'))
                event_end_dt = datetime.fromisoformat(event_end.replace('Z', '+00:00'))
                
                # JSTに変換
                event_start_dt = event_start_dt.astimezone(jst)
                event_end_dt = event_end_dt.astimezone(jst)
                
                conflicts.append({
                    'summary': event.get('summary', '予定なし'),
                    'start': event_start_dt.strftime('%H:%M'),
                    'end': event_end_dt.strftime('%H:%M')
                })
            
            if conflicts:
                conflict_info = "\n".join([
                    f"・{conflict['start']}〜{conflict['end']} {conflict['summary']}"
                    for conflict in conflicts
                ])
                return False, f"新しい時間に既に以下の予定が入っています：\n{conflict_info}"
            
            # 予定を更新
            event_body = target_event['original_event']
            event_body['start']['dateTime'] = new_start_time.isoformat()
            event_body['end']['dateTime'] = new_end_time.isoformat()
            
            updated_event = self.service.events().update(
                calendarId='mmms.dy.23@gmail.com',
                eventId=target_event['id'],
                body=event_body
            ).execute()
            
            # レスポンスメッセージを作成
            old_time = target_event['start'].strftime('%H:%M')
            new_time = new_start_time.strftime('%H:%M')
            new_end = new_end_time.strftime('%H:%M')
            duration_mins = int((new_end_time - new_start_time).total_seconds() / 60)
            
            return True, f"予定を変更しました：\n{target_event['summary']}\n{old_time} → {new_time}〜{new_end}（{duration_mins}分）"
         
        except Exception as e:
            logger.error(f"Error rescheduling event: {str(e)}")
            logger.error("Full error details:", exc_info=True)
            return False, "予定の変更中にエラーが発生しました。"

    def _format_event_time(self, event):
        """
        イベントの時間を文字列にフォーマットする
        
        Args:
            event (dict): イベントデータ
            
        Returns:
            str: フォーマットされた時間文字列
        """
        start_time = parser.parse(event['start'].get('dateTime'))
        end_time = parser.parse(event['end'].get('dateTime'))
        return f"{start_time.strftime('%H:%M')}〜{end_time.strftime('%H:%M')}"

    def update_event_duration(self, target_date, title_keyword, duration_minutes):
        """
        指定された日付とタイトルの予定の時間を更新する
        
        Args:
            target_date (datetime): 対象の日付
            title_keyword (str): 予定のタイトル（部分一致）
            duration_minutes (int): 新しい時間（分）
            
        Returns:
            tuple[bool, str]: (成功したかどうか, メッセージ)
        """
        try:
            # タイムゾーンの設定
            if target_date.tzinfo is None:
                target_date = self.timezone.localize(target_date)
            
            # 指定された日付の予定を取得
            start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)
            events = self.get_events(time_min=start_of_day, time_max=end_of_day)
            
            # タイトルでフィルタリング
            matching_events = []
            for event in events:
                if title_keyword in event.get('summary', ''):
                    matching_events.append(event)
            
            if not matching_events:
                return False, f"指定された日時（{target_date.strftime('%Y年%m月%d日 %H:%M')}）の予定が見つかりませんでした。"
            
            # 最も近い時間の予定を選択
            target_time = target_date.time()
            closest_event = min(matching_events, key=lambda e: abs(
                datetime.fromisoformat(e['start'].get('dateTime', e['start'].get('date')).replace('Z', '+00:00')).time() - target_time
            ))
            
            # イベントの開始時間を取得
            start_time = datetime.fromisoformat(closest_event['start'].get('dateTime', closest_event['start'].get('date')).replace('Z', '+00:00'))
            start_time = start_time.astimezone(self.timezone)
            
            # 新しい終了時間を計算
            end_time = start_time + timedelta(minutes=duration_minutes)
            
            # イベントを更新
            updated_event = self.update_event(
                event_id=closest_event['id'],
                start_time=start_time,
                end_time=end_time,
                title=closest_event.get('summary'),
                location=closest_event.get('location')
            )
            
            if updated_event:
                return True, f"予定を{duration_minutes}分に更新しました。\n開始: {start_time.strftime('%H:%M')}\n終了: {end_time.strftime('%H:%M')}"
            else:
                return False, "予定の更新に失敗しました。"
                
        except Exception as e:
            logger.error(f"予定の更新中にエラーが発生: {str(e)}")
            logger.error("詳細なエラー情報:", exc_info=True)
            return False, f"予定の更新中にエラーが発生しました: {str(e)}"

    def add_event(self, start_time: datetime, end_time: datetime, title: str = None, location: str = None) -> Dict[str, Any]:
        """
        予定を追加する（改善版）
        
        Args:
            start_time (datetime): 開始時刻
            end_time (datetime): 終了時刻
            title (str, optional): タイトル
            location (str, optional): 場所
            
        Returns:
            Dict[str, Any]: 追加された予定の情報
        """
        try:
            if isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time)
            if isinstance(end_time, str):
                end_time = datetime.fromisoformat(end_time)
            # タイムゾーンの設定
            if start_time.tzinfo is None:
                start_time = self.timezone.localize(start_time)
            else:
                start_time = start_time.astimezone(self.timezone)
                
            if end_time.tzinfo is None:
                end_time = self.timezone.localize(end_time)
            else:
                end_time = end_time.astimezone(self.timezone)

            # 重複する予定をチェック
            overlapping_events = self.check_overlapping_events(start_time, end_time)
            if overlapping_events:
                logger.info(f"{len(overlapping_events)}件の重複する予定が見つかりました")
                return {
                    'success': False,
                    'message': '⚠️ この時間帯に既に予定が存在します：\n' + format_overlapping_events(overlapping_events),
                    'overlapping_events': overlapping_events
                }

            # 新しい予定を追加
            event = {
                'summary': title if title else '予定',
                'location': location if location else '',
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'Asia/Tokyo',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'Asia/Tokyo',
                },
            }

            # 予定を追加
            created_event = self.service.events().insert(
                calendarId='mmms.dy.23@gmail.com',
                body=event
            ).execute()

            # 追加した予定の情報をログに記録
            logger.info(f"予定を追加しました: {created_event.get('summary', '予定なし')}")
            logger.info(f"開始時刻: {start_time.isoformat()}")
            logger.info(f"終了時刻: {end_time.isoformat()}")

            return {
                'success': True,
                'event': created_event
            }

        except Exception as e:
            logger.error(f"予定の追加中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'message': f'予定の追加に失敗しました: {str(e)}'
            }

    def get_free_time_slots(self, date: datetime, min_duration: int = 30) -> List[Dict]:
        """
        指定された日付の空き時間を取得する（改善版）
        
        Args:
            date (datetime): 対象日付
            min_duration (int): 最小空き時間（分）
            
        Returns:
            List[Dict]: 空き時間のリスト
        """
        try:
            # その日の予定を取得
            time_min = date.replace(hour=0, minute=0, second=0, microsecond=0)
            time_max = date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            events = self.get_events(time_min, time_max)
            
            # 予定を時系列順にソート
            sorted_events = sorted(events, key=lambda x: x['start'].get('dateTime', x['start'].get('date')))
            
            # 空き時間を計算
            free_slots = []
            current_time = time_min
            
            for event in sorted_events:
                event_start = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')).replace('Z', '+00:00'))
                event_start = event_start.astimezone(self.timezone)
                
                # 現在時刻と予定開始時刻の間に空き時間がある場合
                if (event_start - current_time).total_seconds() / 60 >= min_duration:
                    free_slots.append({
                        'start': current_time,
                        'end': event_start,
                        'duration': int((event_start - current_time).total_seconds() / 60)
                    })
                
                # 予定の終了時刻を次の開始時刻として設定
                event_end = datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')).replace('Z', '+00:00'))
                event_end = event_end.astimezone(self.timezone)
                current_time = event_end
            
            # 最後の予定から23:59までの空き時間を追加
            if (time_max - current_time).total_seconds() / 60 >= min_duration:
                free_slots.append({
                    'start': current_time,
                    'end': time_max,
                    'duration': int((time_max - current_time).total_seconds() / 60)
                })
            
            return free_slots
        
        except Exception as e:
            logger.error(f"空き時間の取得中にエラーが発生: {str(e)}")
            logger.error("詳細なエラー情報:", exc_info=True)
            return []

    def format_free_time_slots(self, free_slots: List[Dict]) -> str:
        """
        空き時間を整形して返す（改善版）
        
        Args:
            free_slots (List[Dict]): 空き時間のリスト
            
        Returns:
            str: 整形された空き時間情報
        """
        if not free_slots:
            return "空き時間はありません。"
        
        message = "🕒 空き時間\n\n"
        
        for slot in free_slots:
            start_time = slot['start'].strftime('%H:%M')
            end_time = slot['end'].strftime('%H:%M')
            duration = slot['duration']
            
            message += f"⏰ {start_time}〜{end_time}（{duration}分）\n"
        
        return message

    def format_calendar_response(self, events: list, start_time: datetime, end_time: datetime) -> str:
        """
        カレンダーのレスポンスを整形する
        
        Args:
            events (list): 予定のリスト
            start_time (datetime): 開始時刻
            end_time (datetime): 終了時刻
            
        Returns:
            str: 整形されたレスポンス
        """
        if not events:
            return (
                "📅 予定はありません。\n\n"
                "新しい予定を追加する場合は、以下のような形式でメッセージを送ってください：\n"
                "・「明日の15時に会議を追加して」\n"
                "・「来週の月曜日、10時から12時まで打ち合わせを入れて」\n"
                "・「今週の金曜日、14時からカフェで打ち合わせ」"
            )
        
        # 予定を日付ごとにグループ化
        events_by_date = {}
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            date = datetime.fromisoformat(start.replace('Z', '+00:00')).strftime('%Y年%m月%d日')
            if date not in events_by_date:
                events_by_date[date] = []
            events_by_date[date].append(event)
        
        # メッセージを構築
        message = "📅 予定一覧\n\n"
        
        for date in sorted(events_by_date.keys()):
            message += f"■ {date}\n"
            for event in events_by_date[date]:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                
                message += (
                    f"  📌 {event.get('summary', '予定なし')}\n"
                    f"  ⏰ {start_dt.strftime('%H:%M')}〜{end_dt.strftime('%H:%M')}\n"
                )
                if event.get('location'):
                    message += f"  📍 {event['location']}\n"
                if event.get('description'):
                    message += f"  👥 {event['description']}\n"
                message += "\n"
        
        # 空き時間情報を追加
        free_slots = self.get_free_time_slots(start_time)
        if free_slots:
            message += "\n空いている時間帯はこちらです👇\n"
            message += self.format_free_time_slots(free_slots)
        
        message += "\n予定の追加、変更、削除が必要な場合は、お気軽にお申し付けくださいね！"
        return message

    def check_overlapping_events(self, start_time: datetime, end_time: datetime) -> List[Dict]:
        """
        指定された時間帯に重複する予定があるかチェックする
        
        Args:
            start_time (datetime): 開始時刻
            end_time (datetime): 終了時刻
            
        Returns:
            List[Dict]: 重複する予定のリスト（id, summary, start, end, location, description）
        """
        try:
            if isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time)
            if isinstance(end_time, str):
                end_time = datetime.fromisoformat(end_time)
            # タイムゾーンの設定
            if start_time.tzinfo is None:
                start_time = self.timezone.localize(start_time)
            if end_time.tzinfo is None:
                end_time = self.timezone.localize(end_time)

            # 既存の予定を取得
            events = self.get_events(start_time, end_time)
            
            # 重複する予定を抽出
            overlapping_events = []
            for event in events:
                event_start = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')).replace('Z', '+00:00'))
                event_end = datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')).replace('Z', '+00:00'))
                
                # 日本時間に変換
                event_start = event_start.astimezone(self.timezone)
                event_end = event_end.astimezone(self.timezone)
                
                # 時間が重複しているかチェック
                if (event_start < end_time and event_end > start_time and event_start != end_time and event_end != start_time):
                    overlapping_events.append({
                        'id': event['id'],  # イベントIDを追加
                        'summary': event.get('summary', '予定なし'),
                        'start': event_start,
                        'end': event_end,
                        'location': event.get('location', ''),
                        'description': event.get('description', '')
                    })
            
            return overlapping_events
            
        except Exception as e:
            logger.error(f"予定の重複チェック中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return []
