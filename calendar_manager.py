from typing import Dict, Optional
from datetime import datetime, timedelta
from dateutil.parser import parse
import traceback
from googleapiclient.discovery import build

class CalendarManager:
    def update_event(self, event_id: str, datetime_info: Dict[str, datetime]) -> Optional[Dict]:
        """
        指定されたイベントの時間を更新する
        
        Args:
            event_id (str): 更新するイベントのID
            datetime_info (Dict[str, datetime]): 更新する日時情報
            
        Returns:
            Optional[Dict]: 更新されたイベント情報
        """
        try:
            # イベントを取得
            event = self.service.events().get(calendarId='mmms.dy.23@gmail.com', eventId=event_id).execute()
            
            # 新しい開始時刻が指定されている場合
            if 'new_start_time' in datetime_info:
                new_start_time = datetime_info['new_start_time']
                duration = parse(event['end']['dateTime']) - parse(event['start']['dateTime'])
                new_end_time = new_start_time + duration
                
                event['start']['dateTime'] = new_start_time.isoformat()
                event['end']['dateTime'] = new_end_time.isoformat()
            
            # 新しい時間の長さが指定されている場合
            elif 'new_duration' in datetime_info:
                start_time = parse(event['start']['dateTime'])
                new_end_time = start_time + datetime_info['new_duration']
                event['end']['dateTime'] = new_end_time.isoformat()
            
            # イベントを更新
            updated_event = self.service.events().update(
                calendarId='mmms.dy.23@gmail.com',
                eventId=event_id,
                body=event
            ).execute()
            
            return updated_event
            
        except Exception as e:
            logger.error(f"イベントの更新中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    async def update_event_duration(self, index: int, duration: int) -> dict:
        """指定されたインデックスの予定の時間を更新する"""
        try:
            # 予定を取得
            events = await self.get_events()
            if not events:
                return {'success': False, 'error': '予定が見つかりません。'}
            
            # インデックスの範囲チェック
            if index < 1 or index > len(events):
                return {'success': False, 'error': f'予定の番号は1から{len(events)}の間で指定してください。'}
            
            # 更新対象の予定を取得
            event = events[index - 1]
            event_id = event['id']
            
            # 開始時間を取得
            start_time = datetime.fromisoformat(event['start'].get('dateTime'))
            
            # 新しい終了時間を計算
            end_time = start_time + timedelta(minutes=duration)
            
            # 予定を更新
            event['end']['dateTime'] = end_time.isoformat()
            event['end']['timeZone'] = 'Asia/Tokyo'
            
            # Google Calendar APIを使用して予定を更新
            service = build('calendar', 'v3', credentials=self.credentials)
            updated_event = service.events().update(
                calendarId='primary',
                eventId=event_id,
                body=event
            ).execute()
            
            return {'success': True, 'event': updated_event}
            
        except Exception as e:
            logger.error(f"予定の更新中にエラーが発生: {str(e)}")
            return {'success': False, 'error': str(e)} 