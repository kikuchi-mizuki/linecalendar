from datetime import datetime, timedelta, timezone
import logging
import pytz
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import os
import json
import asyncio
from functools import lru_cache
from typing import Dict, List, Optional, Tuple, Union, Any
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import signal
from contextlib import contextmanager
from tenacity import retry, stop_after_attempt, wait_exponential
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
import google.oauth2.credentials
from google.auth import credentials
from google.auth import exceptions
from google.auth import transport
from message_parser import normalize_text
from constants import WEEKDAYS

# ログ設定
logger = logging.getLogger(__name__)

# タイムアウト設定（秒）
CALENDAR_TIMEOUT_SECONDS = 30

@contextmanager
def calendar_timeout(seconds):
    def signal_handler(signum, frame):
        raise TimeoutError(f"カレンダー操作が{seconds}秒でタイムアウトしました")
    
    original_handler = signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, original_handler)

class CalendarManager:
    """
    Google Calendar APIを使用してカレンダー操作を行うクラス（OAuth認証対応）
    """
    def __init__(self, credentials):
        """
        カレンダーマネージャーの初期化
        
        Args:
            credentials (google.oauth2.credentials.Credentials): Google認証情報
        """
        try:
            # 認証情報を設定
            self.credentials = credentials
            
            # Google Calendar APIサービスの初期化
            self.service = build(
                'calendar', 'v3', credentials=self.credentials
            )
            logger.info("Google Calendar APIサービスを初期化しました（OAuth認証）")
            
            # カレンダーIDの取得
            self.calendar_id = self._get_calendar_id()
            
            # タイムゾーンの設定
            self.timezone = pytz.timezone('Asia/Tokyo')
            
        except Exception as e:
            logger.error(f"カレンダーマネージャーの初期化中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def _get_calendar_id(self):
        """
        プライマリーカレンダーのIDを取得する
        
        Returns:
            str: カレンダーID
        """
        try:
            logger.info("カレンダーIDの取得を開始します")
            calendar_list = self.service.calendarList().list().execute()
            calendars = calendar_list.get('items', [])
            
            logger.info(f"利用可能なカレンダー数: {len(calendars)}")
            
            # プライマリーカレンダーを探す
            for calendar in calendars:
                logger.info(f"カレンダー詳細: ID={calendar['id']}, タイトル={calendar['summary']}, プライマリー={calendar.get('primary', False)}, アクセス権限={calendar['accessRole']}")
                if calendar.get('primary', False):
                    logger.info(f"プライマリーカレンダーを使用: {calendar['id']}")
                    return calendar['id']
            
            # プライマリーカレンダーが見つからない場合は最初のカレンダーを使用
            if calendars:
                logger.info(f"プライマリーカレンダーが見つからないため、最初のカレンダーを使用: {calendars[0]['id']}")
                return calendars[0]['id']
            
            raise Exception("利用可能なカレンダーが見つかりません")
            
        except Exception as e:
            logger.error(f"カレンダーIDの取得中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1))
    async def get_events(
        self,
        start_time: datetime,
        end_time: datetime,
        title: Optional[str] = None,
        ignore_event_id: str = None
    ) -> List[Dict]:
        """
        指定された期間のイベントを取得
        Args:
            start_time (datetime): 開始時間
            end_time (datetime): 終了時間
            title (Optional[str]): イベントのタイトル
            ignore_event_id (Optional[str]): 除外するイベントID
        Returns:
            List[Dict]: イベントのリスト
        """
        # Noneチェックを追加
        if start_time is None or end_time is None:
            logger.error("start_timeまたはend_timeがNoneです")
            return []

        # タイムゾーンの設定
            if start_time.tzinfo is None:
                start_time = self.timezone.localize(start_time)
            else:
                start_time = start_time.astimezone(self.timezone)
            if end_time.tzinfo is None:
                end_time = self.timezone.localize(end_time)
            else:
                end_time = end_time.astimezone(self.timezone)
            
        # デバッグ: 取得前の時刻をJSTで出力
            logger.info(f"予定を取得: {start_time.isoformat()} から {end_time.isoformat()}")
            
        try:
            # タイトルが指定されている場合は正規化
            norm_title = None
            if title:
                norm_title = normalize_text(title, keep_katakana=True)
                logger.debug(f"検索タイトル(正規化後): {norm_title}")
            
            # APIからイベントを取得
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=start_time.isoformat(),
                timeMax=end_time.isoformat(),
                singleEvents=True,
                orderBy='startTime',
                timeZone='Asia/Tokyo'
            ).execute()
            
            events = events_result.get('items', [])
            logger.info(f"取得した予定の数: {len(events)}")
            
            # デバッグ: 取得したイベントの一覧を出力
            for event in events:
                event_title = event.get('summary', '')
                event_start = event.get('start', {}).get('dateTime', '')
                logger.debug(f"取得したイベント: タイトル={event_title}, 開始時刻={event_start}")
            
            # タイトルでフィルタリング（カタカナ保持の正規化で部分一致）
            if norm_title:
                filtered_events = []
                for event in events:
                    event_title = event.get('summary', '')
                    # タイトルをそのまま比較
                    if norm_title in event_title:
                        filtered_events.append(event)
                        logger.debug(f"タイトル一致: 検索={norm_title}, イベント={event_title}")
                events = filtered_events
                logger.info(f"タイトルフィルタリング後の予定数: {len(events)}")
            
            # ignore_event_idでフィルタリング
            if ignore_event_id:
                events = [event for event in events if event.get('id') != ignore_event_id]

            # 予定を時系列順にソート
            events.sort(key=lambda x: x.get('start', {}).get('dateTime', ''))
            
            return events
            
        except Exception as e:
            logger.error(f"イベント取得中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return []

    async def add_event(
        self,
        title: str,
        start_time: datetime,
        end_time: datetime,
        location: str = None,
        person: str = None,
        description: str = None,
        recurrence: str = None,
        skip_overlap_check: bool = False
    ) -> Dict:
        """予定を追加する"""
        try:
            # デバッグ: 追加前の時刻をJSTで出力
            print(f"[DEBUG][add_event] 追加前: start_time={start_time} end_time={end_time}")
            logger.info(f"[DEBUG][add_event] 追加前: start_time={start_time} end_time={end_time}")
            # 秒・マイクロ秒を必ず0に丸める
            start_time = start_time.replace(second=0, microsecond=0)
            end_time = end_time.replace(second=0, microsecond=0)
            # タイムゾーンの設定
            if start_time.tzinfo is None:
                start_time = self.timezone.localize(start_time)
            else:
                start_time = start_time.astimezone(self.timezone)
            if end_time.tzinfo is None:
                end_time = self.timezone.localize(end_time)
            else:
                end_time = end_time.astimezone(self.timezone)
            # デバッグ: 追加直前の時刻をJSTで出力
            print(f"[DEBUG][add_event] GoogleAPI渡す直前: start_time={start_time} end_time={end_time}")
            logger.info(f"[DEBUG][add_event] GoogleAPI渡す直前: start_time={start_time} end_time={end_time}")
            
            # 重複チェック（スキップ可能）
            if not skip_overlap_check:
                # その日の全予定を取得
                day_start = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
                day_end = start_time.replace(hour=23, minute=59, second=59, microsecond=999999)
                all_events = await self.get_events(day_start, day_end)
                duplicate_details = []
                for event in all_events:
                    start_info = event.get('start')
                    end_info = event.get('end')
                    if not isinstance(start_info, dict) or not isinstance(end_info, dict):
                        continue
                    start_val = start_info.get('dateTime', start_info.get('date'))
                    end_val = end_info.get('dateTime', end_info.get('date'))
                    if not isinstance(start_val, str) or not isinstance(end_val, str):
                        continue
                    try:
                        event_start = datetime.fromisoformat(start_val.replace('Z', '+00:00')).astimezone(self.timezone)
                        event_end = datetime.fromisoformat(end_val.replace('Z', '+00:00')).astimezone(self.timezone)
                    except Exception:
                        continue
                    # 本当に重複しているか判定
                    if (start_time < event_end and end_time > event_start):
                        duplicate_details.append({
                            'title': event.get('summary', '予定'),
                            'start': event_start.strftime('%H:%M'),
                            'end': event_end.strftime('%H:%M')
                        })
                if duplicate_details:
                    warning_message = "⚠️ この時間帯に既に予定が存在します：\n"
                    for detail in duplicate_details:
                        warning_message += f"- {detail['title']} ({detail['start']}～{detail['end']})\n"
                    warning_message += "\nそれでも追加しますか？"
                    return {
                        'success': False,
                        'error': 'duplicate',
                        'message': warning_message,
                        'duplicate_events': duplicate_details
                    }
            # 予定の作成
            event = {
                'summary': title,  # タイトルをそのまま使用
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'Asia/Tokyo',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'Asia/Tokyo',
                }
            }
            if location:
                event['location'] = location
            if description:
                event['description'] = description
            elif person:
                event['description'] = f"参加者: {person}"
            if recurrence:
                event['recurrence'] = [recurrence]
            # 予定の追加
            event = self.service.events().insert(calendarId=self.calendar_id, body=event).execute()
            logger.info(f"予定を追加しました: {event['id']}")
            return {
                'success': True,
                'event_id': event['id'],
                'message': f"予定「{title}」を追加しました。"
            }
        except Exception as e:
            logger.info(f"予定の追加に失敗: {str(e)} start_time={start_time}, end_time={end_time}")
            import traceback
            logger.info(traceback.format_exc())
            logger.error(f"予定の追加に失敗: {str(e)}")
            return {
                'success': False,
                'error': 'exception',
                'message': f'Google APIエラー: {str(e)}'
            }

    async def delete_event(self, event_id: str) -> Dict:
        """
        指定されたIDの予定を削除する
        
        Args:
            event_id (str): 削除する予定のID
            
        Returns:
            Dict: 削除結果
        """
        try:
            self.service.events().delete(
                calendarId=self.calendar_id,
                eventId=event_id
            ).execute()
            logger.info(f"予定を削除しました: {event_id}")
            return {
                'success': True,
                'message': '予定を削除しました'
            }
        except Exception as e:
            logger.error(f"予定の削除中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': str(e),
                'message': '予定の削除に失敗しました'
            }

    async def update_event(
        self,
        start_time: datetime,
        end_time: datetime,
        new_start_time: datetime,
        new_end_time: datetime,
        title: Optional[str] = None,
        skip_overlap_check: bool = False
    ) -> Dict:
        """予定を更新する"""
        try:
            logger.info("予定更新処理を開始")
            
            # タイムゾーンの設定
            if start_time.tzinfo is None:
                start_time = self.timezone.localize(start_time)
            else:
                start_time = start_time.astimezone(self.timezone)
            if end_time.tzinfo is None:
                end_time = self.timezone.localize(end_time)
            else:
                end_time = end_time.astimezone(self.timezone)
            if new_start_time.tzinfo is None:
                new_start_time = self.timezone.localize(new_start_time)
            else:
                new_start_time = new_start_time.astimezone(self.timezone)
            if new_end_time.tzinfo is None:
                new_end_time = self.timezone.localize(new_end_time)
            else:
                new_end_time = new_end_time.astimezone(self.timezone)
            
            # 更新対象の予定を検索
            events = await self._find_events(start_time, end_time, title)
            if not events:
                logger.warning("更新対象の予定が見つかりませんでした")
                return {'success': False, 'error': '予定が見つかりませんでした'}
                
            # 重複チェック（スキップ可能）
            if not skip_overlap_check:
                overlapping_events = await self._check_overlapping_events(new_start_time, new_end_time, exclude_event_id=events[0]['id'])
                if overlapping_events:
                    logger.warning(f"更新後の時間帯に重複する予定があります: {len(overlapping_events)}件")
                    warning_message = "⚠️ 更新後の時間帯に既に予定が存在します：\n"
                    for detail in overlapping_events:
                        warning_message += f"- {detail['summary']} ({detail['start']}～{detail['end']})\n"
                    warning_message += "\nそれでも更新しますか？"
                    return {
                        'success': False,
                        'error': 'duplicate',
                        'message': warning_message,
                        'duplicate_events': overlapping_events
                    }
            
            # 予定を更新
            event = events[0]  # 最初の予定を更新
            event['start'] = {
                'dateTime': new_start_time.isoformat(),
                'timeZone': 'Asia/Tokyo'
            }
            event['end'] = {
                'dateTime': new_end_time.isoformat(),
                'timeZone': 'Asia/Tokyo'
            }
            
            updated_event = self.service.events().update(
                calendarId=self.calendar_id,
                eventId=event['id'],
                body=event
            ).execute()
            
            logger.info(f"予定を更新しました: {updated_event['id']}")
            return {
                'success': True,
                'event': updated_event,
                'message': '予定を更新しました'
            }
            
        except Exception as e:
            logger.error(f"予定の更新に失敗: {str(e)}")
            logger.error(traceback.format_exc())
            print(f'★update_event except: {e}')
            print(traceback.format_exc())
            return {
                'success': False,
                'error': str(e),
                'message': '予定の更新に失敗しました'
            }

    async def update_event_by_index(
        self,
        index: int,
        new_start_time: datetime,
        new_end_time: datetime,
        start_time: Optional[datetime] = None,
        skip_overlap_check: bool = False
    ) -> Dict:
        """
        インデックスを指定して予定を更新する
        
        Args:
            index (int): 更新する予定のインデックス（1から始まる）
            new_start_time (datetime): 新しい開始時間
            new_end_time (datetime): 新しい終了時間
            start_time (Optional[datetime]): 検索開始時間（指定がない場合はnew_start_timeの日付の0時0分）
            skip_overlap_check (bool): Trueなら重複チェックをスキップ
        Returns:
            Dict: 更新結果
        """
        try:
            # タイムゾーンの設定
            if new_start_time.tzinfo is None:
                new_start_time = self.timezone.localize(new_start_time)
            else:
                new_start_time = new_start_time.astimezone(self.timezone)
            if new_end_time.tzinfo is None:
                new_end_time = self.timezone.localize(new_end_time)
            else:
                new_end_time = new_end_time.astimezone(self.timezone)

            # 日付の範囲を設定
            if start_time is None:
                start_time = new_start_time.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                if start_time.tzinfo is None:
                    start_time = self.timezone.localize(start_time)
                else:
                    start_time = start_time.astimezone(self.timezone)
            end_time = start_time.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            # 予定を取得
            events = await self.get_events(start_time, end_time)
            logger.debug(f"[update_event_by_index] 取得イベント一覧:")
            for idx, ev in enumerate(events):
                ev_start = ev['start'].get('dateTime', ev['start'].get('date'))
                logger.debug(f"  idx={idx+1} id={ev.get('id')} title={ev.get('summary')} start={ev_start}")
            if not events:
                return {'success': False, 'error': '予定が見つかりませんでした'}
            
            # インデックスの範囲チェック
            if index < 1 or index > len(events):
                logger.error(f"[update_event_by_index] event_indexが不正: {index}")
                return {'success': False, 'error': f'指定されたインデックス（{index}）は範囲外です'}
            
            # 更新対象の予定を取得
            event = events[index - 1]
            event_id = event['id']
            logger.debug(f"[update_event_by_index] 除外するevent_id={event_id}")
            
            # 重複チェック（skip_overlap_checkがFalseのときのみ）
            if not skip_overlap_check:
                logger.info(f"[update_event_by_index] skip_overlap_check is False, doing overlap check")
                overlapping_events = await self._check_overlapping_events(new_start_time, new_end_time, exclude_event_id=event_id)
                if overlapping_events:
                    return {
                        'success': False,
                        'error': '更新後の時間帯に重複する予定があります',
                        'overlapping_events': overlapping_events
                    }
            else:
                logger.info(f"[update_event_by_index] skip_overlap_check is True, skipping overlap check")
            
            # 予定を更新
            try:
                event['start'] = {
                    'dateTime': new_start_time.isoformat(),
                    'timeZone': 'Asia/Tokyo'
                }
                event['end'] = {
                    'dateTime': new_end_time.isoformat(),
                    'timeZone': 'Asia/Tokyo'
                }
                updated_event = self.service.events().update(
                    calendarId=self.calendar_id,
                    eventId=event_id,
                    body=event
                ).execute()
            except Exception as e:
                logger.error(f"Google Calendar API更新時にエラー: {str(e)}")
                logger.error(traceback.format_exc())
                return {'success': False, 'error': f'Google APIエラー: {str(e)}'}
            
            return {
                'success': True,
                'event': updated_event,
                'message': '予定を更新しました'
            }
            
        except Exception as e:
            logger.error(f"インデックスによる予定の更新に失敗: {str(e)}")
            logger.error(traceback.format_exc())
            return {'success': False, 'error': f'予定の更新に失敗しました: {str(e)}'}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1))
    async def _check_overlapping_events(
        self,
        start_time: datetime,
        end_time: datetime,
        title: Optional[str] = None,
        exclude_event_id: Optional[str] = None
    ) -> List[Dict]:
        """
        重複するイベントをチェック
        
        Args:
            start_time (datetime): 開始時間
            end_time (datetime): 終了時間
            title (Optional[str]): イベントのタイトル
            exclude_event_id (Optional[str]): 除外するイベントID
            
        Returns:
            List[Dict]: 重複するイベントのリスト
        """
        try:
            # タイムゾーンの設定
            if start_time.tzinfo is None:
                start_time = self.timezone.localize(start_time)
            else:
                start_time = start_time.astimezone(self.timezone)
            if end_time.tzinfo is None:
                end_time = self.timezone.localize(end_time)
            else:
                end_time = end_time.astimezone(self.timezone)

            events = await self.get_events(start_time, end_time)
            overlapping_events = []
            
            for event in events:
                event_start = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00')).astimezone(self.timezone)
                event_end = datetime.fromisoformat(event['end']['dateTime'].replace('Z', '+00:00')).astimezone(self.timezone)
                # タイトルが指定されている場合は、部分一致も許容
                if title and title not in event.get('summary', ''):
                    continue
                # 自分自身のイベントIDは除外
                if exclude_event_id and event.get('id') == exclude_event_id:
                    continue
                # 時間帯が重なっていれば重複とみなす
                if (event_start < end_time and event_end > start_time and event_start != end_time and event_end != start_time):
                    overlapping_events.append({
                        'id': event['id'],
                        'summary': event.get('summary', '予定なし'),
                        'start': event_start.strftime('%Y-%m-%d %H:%M'),
                        'end': event_end.strftime('%Y-%m-%d %H:%M'),
                        'location': event.get('location', ''),
                        'description': event.get('description', '')
                    })
                    
            logger.info(f"重複チェック結果: {len(overlapping_events)}件の重複予定を検出")
            return overlapping_events
            
        except Exception as e:
            logger.error(f"重複チェック中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return []
            
    async def _find_events(
        self,
        start_time: datetime,
        end_time: datetime,
        title: Optional[str] = None,
        ignore_event_id: str = None
    ) -> List[Dict]:
        """
        指定された条件に一致するイベントを検索
        """
        try:
            search_start = start_time - timedelta(minutes=30)
            search_end = end_time + timedelta(minutes=30)
            events = await self.get_events(
                start_time=search_start,
                end_time=search_end,
                title=title,
                ignore_event_id=ignore_event_id
            )
            if not events:
                logger.info(f"指定された期間にイベントが見つかりません: {start_time} - {end_time}")
                return []
            matching_events = []
            for event in events:
                event_start = self._parse_event_time(event['start'])
                event_end = self._parse_event_time(event['end'])
                # 完全一致のみを最優先
                if event_start == start_time and event_end == end_time:
                    matching_events.insert(0, event)
                # 開始時刻が一致するものだけ
                elif event_start == start_time:
                    matching_events.append(event)
            if title:
                matching_events = [
                    event for event in matching_events
                    if title.lower() in event.get('summary', '').lower()
                ]
            logger.info(f"検索結果: {len(matching_events)}件のイベントが見つかりました")
            return matching_events
        except Exception as e:
            logger.error(f"イベントの検索中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return []

    async def get_free_time(self, start_time: datetime, end_time: datetime,
                     duration: timedelta) -> List[Tuple[datetime, datetime]]:
        """
        指定された時間帯の空き時間を取得する
        
        Args:
            start_time (datetime): 開始時刻
            end_time (datetime): 終了時刻
            duration (timedelta): 必要な時間
            
        Returns:
            List[Tuple[datetime, datetime]]: 空き時間のリスト
        """
        try:
            # タイムゾーンの設定
            if start_time.tzinfo is None:
                start_time = self.timezone.localize(start_time)
            if end_time.tzinfo is None:
                end_time = self.timezone.localize(end_time)
                
            # イベントの取得
            events = await self.get_events(start_time, end_time)
            
            # 空き時間の計算
            free_times = []
            current_time = start_time
            
            for event in events:
                event_start = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00')).astimezone(self.timezone)
                event_end = datetime.fromisoformat(event['end']['dateTime'].replace('Z', '+00:00')).astimezone(self.timezone)
                
                # イベントの開始時刻までに空き時間がある場合
                if event_start - current_time >= duration:
                    free_times.append((current_time, event_start))
                    
                current_time = event_end
                
            # 最後のイベントから終了時刻までに空き時間がある場合
            if end_time - current_time >= duration:
                free_times.append((current_time, end_time))
                
            return free_times
            
        except Exception as e:
            logger.error(f"空き時間の取得中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return []

    async def check_overlap(self, start_time: datetime, end_time: datetime) -> Dict:
        """
        指定した時間帯に重複する予定があるかチェックする
        
        Args:
            start_time (datetime): 開始時間
            end_time (datetime): 終了時間
            
        Returns:
            Dict: {'has_overlap': bool, 'events': list}
        """
        try:
            # タイムゾーンの設定
            if start_time.tzinfo is None:
                start_time = self.timezone.localize(start_time)
            else:
                start_time = start_time.astimezone(self.timezone)
            if end_time.tzinfo is None:
                end_time = self.timezone.localize(end_time)
            else:
                end_time = end_time.astimezone(self.timezone)

            events = await self.get_events(start_time, end_time)
            has_overlap = len(events) > 0
            overlap_events = []
            for event in events:
                start_dt = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')).replace('Z', '+00:00')).astimezone(self.timezone)
                end_dt = datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')).replace('Z', '+00:00')).astimezone(self.timezone)
                overlap_events.append({
                    'start': start_dt.isoformat(),
                    'end': end_dt.isoformat(),
                    'summary': event.get('summary', ''),
                    'location': event.get('location', '')
                })
            return {'has_overlap': has_overlap, 'events': overlap_events}
        except Exception as e:
            logger.error(f"重複予定チェック中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return {'has_overlap': False, 'events': []}

    async def update_event_duration(self, index: int, duration: timedelta, start_time: Optional[datetime] = None) -> Dict:
        """
        指定されたインデックスの予定の時間を更新する
        
        Args:
            index (int): 変更したい予定の番号（1始まり）
            duration (timedelta): 新しい所要時間
            start_time (Optional[datetime]): その日の0時（指定がなければ今日）
            
        Returns:
            Dict: 成功/失敗とイベント情報またはエラーメッセージ
        """
        try:
            # 指定がなければ今日、指定があればその日
            if start_time is None:
                now = datetime.now(self.timezone)
                start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                if start_time.tzinfo is None:
                    start_time = self.timezone.localize(start_time)
                else:
                    start_time = start_time.astimezone(self.timezone)
            end_time = start_time + timedelta(days=1)
            events = await self.get_events(start_time, end_time)
            if not events:
                return {'success': False, 'error': '予定が見つかりません。'}
            if index < 1 or index > len(events):
                return {'success': False, 'error': f'予定の番号は1から{len(events)}の間で指定してください。'}
            event = events[index - 1]
            event_id = event['id']
            start_dt_str = event['start'].get('dateTime', event['start'].get('date'))
            start_time_dt = datetime.fromisoformat(start_dt_str.replace('Z', '+00:00')).astimezone(self.timezone)
            end_time_dt = start_time_dt + duration
            event['end']['dateTime'] = end_time_dt.isoformat()
            event['end']['timeZone'] = 'Asia/Tokyo'
            updated_event = self.service.events().update(
                calendarId=self.calendar_id,
                eventId=event_id,
                body=event
            ).execute()
            return {
                'success': True,
                'event': updated_event,
                'message': '予定の時間を更新しました'
            }
        except Exception as e:
            logger.error(f"予定の更新中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': str(e),
                'message': '予定の更新に失敗しました'
            }

    async def delete_event_by_index(self, index: int, start_time: Optional[datetime] = None) -> Dict:
        """
        指定した日付の予定リストからインデックス指定で予定を削除する
        
        Args:
            index (int): 削除したい予定の番号（1始まり）
            start_time (Optional[datetime]): その日の0時（指定がなければ今日）
            
        Returns:
            Dict: 成功/失敗とメッセージ
        """
        try:
            # 指定がなければ今日、指定があればその日
            if start_time is None:
                now = datetime.now(self.timezone)
                start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                # 指定された日付の0時0分0秒に設定
                start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # その日の23:59:59までを検索範囲とする
            end_time = start_time.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            # 予定を取得
            events = await self.get_events(start_time, end_time)
            if not events:
                return {'success': False, 'error': '予定が見つかりません。'}
            
            # インデックスの範囲チェック
            if index < 1 or index > len(events):
                return {'success': False, 'error': f'予定の番号は1から{len(events)}の間で指定してください。'}
            
            # 予定を削除
            event = events[index - 1]
            event_id = event['id']
            self.service.events().delete(
                calendarId=self.calendar_id,
                eventId=event_id
            ).execute()
            
            return {'success': True, 'message': f'予定「{event.get("summary", "")}」を削除しました。'}
            
        except Exception as e:
            logger.error(f"予定の削除中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return {'success': False, 'error': str(e)}

    async def update_event_by_id(self, event_id: str, new_start_time: datetime, new_end_time: datetime) -> Dict:
        """event_idで直接予定を更新する"""
        try:
            # タイムゾーンの設定
            if new_start_time.tzinfo is None:
                new_start_time = self.timezone.localize(new_start_time)
            else:
                new_start_time = new_start_time.astimezone(self.timezone)
            if new_end_time.tzinfo is None:
                new_end_time = self.timezone.localize(new_end_time)
            else:
                new_end_time = new_end_time.astimezone(self.timezone)

            # 予定を取得
            event = self.service.events().get(calendarId=self.calendar_id, eventId=event_id).execute()
            logger.debug(f"[update_event_by_id] 取得したevent: {event}")

            # 重複チェック（自分自身のイベントは除外）
            events = await self.get_events(
                start_time=new_start_time,
                end_time=new_end_time
            )
            for e in events:
                if str(e.get('id', '')).strip() == str(event_id).strip():
                    continue  # 自分自身は除外
                e_start = datetime.fromisoformat(e['start']['dateTime'].replace('Z', '+00:00')).astimezone(self.timezone)
                e_end = datetime.fromisoformat(e['end']['dateTime'].replace('Z', '+00:00')).astimezone(self.timezone)
                if (new_start_time < e_end and new_end_time > e_start):
                    logger.warning(f"[update_event_by_id] 重複イベント: {e}")
                    return {'success': False, 'error': 'duplicate', 'message': '更新後の時間帯に既に予定があります。'}

            # 予定を更新
            event['start'] = {'dateTime': new_start_time.isoformat(), 'timeZone': 'Asia/Tokyo'}
            event['end'] = {'dateTime': new_end_time.isoformat(), 'timeZone': 'Asia/Tokyo'}
            logger.debug(f"[update_event_by_id] 更新前のevent: {event}")

            updated_event = self.service.events().update(
                calendarId=self.calendar_id,
                eventId=event_id,
                body=event
            ).execute()
            logger.debug(f"[update_event_by_id] 更新後のevent: {updated_event}")

            return {
                'success': True,
                'event': updated_event
            }

        except Exception as e:
            logger.error(f"予定更新中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': str(e)
            } 

    def _parse_event_time(self, time_dict):
        """
        Google Calendar APIのevent['start']やevent['end']のdictからdatetimeを返す
        """
        if 'dateTime' in time_dict:
            return datetime.fromisoformat(time_dict['dateTime'].replace('Z', '+00:00'))
        elif 'date' in time_dict:
            # 終日イベント
            return datetime.fromisoformat(time_dict['date'])
        else:
            return None 