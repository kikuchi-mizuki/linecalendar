import os
import traceback
from utils.db import db_manager
from datetime import datetime, timedelta
from flask import session
from typing import List, Dict, Union
import time
import json
import logging
import pytz
from message_parser import parse_message
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    TemplateSendMessage, ButtonsTemplate, PostbackAction,
    CarouselTemplate, CarouselColumn, URIAction,
    FlexSendMessage, BubbleContainer, BoxComponent,
    TextComponent, ButtonComponent, MessageAction
)
from message_parser import MessageParser
from calendar_operations import CalendarOperations

logger = logging.getLogger('app')
JST = pytz.timezone('Asia/Tokyo')

async def reply_text(reply_token, texts: Union[str, list]):
    try:
        if not reply_token:
            logger.warning("reply_tokenがありません。返信できません。")
            return
        if not texts:
            logger.error("送信するテキストが空です")
            return
        if isinstance(texts, str):
            texts = [texts]
        from linebot.v3.messaging import TextMessage, ReplyMessageRequest
        from app import line_bot_api
        messages = []
        current_message = []
        current_length = 0
        for text in texts:
            if current_length + len(text) > 1900:
                messages.append("\n".join(current_message))
                current_message = [text]
                current_length = len(text)
            else:
                current_message.append(text)
                current_length += len(text)
        if current_message:
            messages.append("\n".join(current_message))
        for message in messages:
            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=reply_token,
                        messages=[TextMessage(text=message)]
                    )
                )
                logger.info(f"メッセージを送信しました: {message[:100]}...")
            except Exception as e:
                logger.error(f"メッセージの送信中にエラーが発生: {str(e)}")
                logger.error(traceback.format_exc())
    except Exception as e:
        logger.error(f"reply_textで予期せぬエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())

def get_auth_url(user_id: str) -> str:
    try:
        # db_manager.delete_google_credentials(user_id)
        session.clear()
        session['line_user_id'] = user_id
        session['auth_start_time'] = time.time()
        session['last_activity'] = time.time()
        session['auth_state'] = 'started'
        session.permanent = True
        session.modified = True
        code = generate_one_time_code()
        save_one_time_code(code, user_id)
        logger.info(f"ワンタイムコードを生成: user_id={user_id}, code={code}")
        return code
    except Exception as e:
        logger.error(f"ワンタイムコード生成中にエラー: {str(e)}")
        logger.error(traceback.format_exc())
        return ""

async def handle_message(user_id: str, message: str, reply_token: str):
    print(f"[handle_message] called: message={message}")
    try:
        print(f"[handle_message] before parse_message: message={message}")
        result = parse_message(message)
        print(f"[handle_message] after parse_message: result={result}")
        from services.calendar_service import get_calendar_manager
        calendar_manager = get_calendar_manager(user_id)
        operation_type = result.get('operation_type')
        action = result.get('action')
        logger.debug(f"[handle_parsed_message] 操作タイプ: {operation_type}")
        if operation_type == 'add':
            await handle_add_event(result, calendar_manager, user_id, reply_token)
        elif operation_type == 'read':
            today = datetime.now(JST).date()
            events = await calendar_manager.get_events(today)
            msg = format_event_list(events, today, today)
            await reply_text(reply_token, msg)
        elif operation_type == 'delete':
            await handle_delete_event(result, calendar_manager, user_id, reply_token)
        elif operation_type == 'update':
            await handle_update_event(result, calendar_manager, user_id, reply_token)
        elif (operation_type == 'confirm') or (action == 'confirm'):
            today = datetime.now(JST).date()
            events = await calendar_manager.get_events(today)
            msg = format_event_list(events, today, today)
            await reply_text(reply_token, msg)
            return
        else:
            await reply_text(reply_token, "未対応の操作です。\n予定の追加、確認、削除、更新のいずれかを指定してください。")
    except Exception as e:
        print(f"[handle_message][EXCEPTION] {e}")
        logger.error(f"メッセージ処理中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        await reply_text(reply_token, "エラーが発生しました。しばらく経ってから再度お試しください。")

def format_event_list(events: List[Dict], start_time: datetime = None, end_time: datetime = None) -> str:
    def border():
        return '━━━━━━━━━━'
    lines = []
    date_list = []
    if start_time and end_time:
        current = start_time
        while current <= end_time:
            date_list.append(current)
            current += timedelta(days=1)
    elif start_time:
        date_list.append(start_time)
    else:
        for event in events:
            start = event.get('start', {}).get('dateTime', event.get('start', {}).get('date'))
            if start:
                date = datetime.fromisoformat(start.replace('Z', '+00:00')).date()
                if date not in date_list:
                    date_list.append(date)
    for date in date_list:
        if isinstance(date, datetime):
            date_str = date.strftime('%Y/%m/%d (%a)')
            date_key = date.strftime('%Y/%m/%d (%a)')
        else:
            date_str = date.strftime('%Y/%m/%d (%a)')
            date_key = date.strftime('%Y/%m/%d (%a)')
        lines.append(f'📅 {date_str}')
        lines.append(border())
        day_events = []
        for event in events:
            start = event.get('start', {}).get('dateTime', event.get('start', {}).get('date'))
            if start:
                event_date = datetime.fromisoformat(start.replace('Z', '+00:00')).strftime('%Y/%m/%d (%a)')
                if event_date == date_key:
                    day_events.append(event)
        if day_events:
            for i, event in enumerate(day_events, 1):
                summary = event.get('summary', '（タイトルなし）')
                start = event.get('start', {}).get('dateTime', event.get('start', {}).get('date'))
                end = event.get('end', {}).get('dateTime', event.get('end', {}).get('date'))
                if start and end:
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                    lines.append(f"{i}. {summary}")
                    lines.append(f"⏰ {start_dt.strftime('%H:%M')}～{end_dt.strftime('%H:%M')}")
                    lines.append("")
                else:
                    lines.append(f"{i}. {summary}（終日）")
                    lines.append("")
        else:
            lines.append("予定はありません。")
            lines.append("")
        lines.append(border())
    return "\n".join(lines)

def get_user_credentials(user_id: str):
    try:
        # credentials_dict = db_manager.get_user_credentials(user_id)
        credentials = db_manager.get_user_credentials(user_id)
        logger.debug(f"[get_user_credentials] credentials: {credentials}")
        if not credentials:
            logger.warning(f"認証情報が見つかりません: user_id={user_id}")
            return None
        import google.oauth2.credentials
        from datetime import timezone
        SCOPES = ['https://www.googleapis.com/auth/calendar']
        credentials_obj = google.oauth2.credentials.Credentials(
            token=credentials.get('token'),
            refresh_token=credentials.get('refresh_token'),
            token_uri=credentials.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=credentials.get('client_id'),
            client_secret=credentials.get('client_secret'),
            scopes=credentials.get('scopes', SCOPES)
        )
        if credentials.get('expires_at'):
            credentials_obj.expiry = datetime.fromtimestamp(credentials['expires_at'], tz=timezone.utc)
            logger.info(f"credentials.expiry(set): {credentials_obj.expiry}, type={type(credentials_obj.expiry)}, tzinfo={credentials_obj.expiry.tzinfo}")
            if credentials_obj.expiry.tzinfo is None:
                credentials_obj.expiry = credentials_obj.expiry.replace(tzinfo=timezone.utc)
                logger.info(f"credentials.expiry(replaced): {credentials_obj.expiry}, type={type(credentials_obj.expiry)}, tzinfo={credentials_obj.expiry.tzinfo}")
            logger.info(f"credentials.expiry={credentials_obj.expiry}, now={datetime.now(timezone.utc)}")
        expiry = credentials_obj.expiry if hasattr(credentials_obj, 'expiry') else None
        if expiry and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if (expiry and (expiry - datetime.now(timezone.utc)).total_seconds() < 3600) or credentials_obj.expired:
            try:
                if not credentials_obj.refresh_token:
                    logger.error(f"リフレッシュトークンが存在しません: user_id={user_id}")
                    # db_manager.delete_google_credentials(user_id)
                    return None
                credentials_obj.refresh(__import__('google.auth.transport.requests').auth.transport.requests.Request())
                # db_manager.save_google_credentials(user_id, {
                #     'token': credentials_obj.token,
                #     'refresh_token': credentials_obj.refresh_token,
                #     'token_uri': credentials_obj.token_uri,
                #     'client_id': credentials_obj.client_id,
                #     'client_secret': credentials_obj.client_secret,
                #     'scopes': credentials_obj.scopes,
                #     'expires_at': credentials_obj.expiry.timestamp() if credentials_obj.expiry else None
                # })
                logger.info(f"認証トークンをリフレッシュしました: user_id={user_id}")
            except Exception as e:
                logger.error(f"トークンのリフレッシュに失敗: {str(e)}")
                # db_manager.delete_google_credentials(user_id)
                return None
        return credentials_obj
    except Exception as e:
        logger.error(f"認証情報の取得に失敗: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def generate_one_time_code(length=6):
    import random, string
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
    logger.debug(f"[one_time_code][generate] code={code}")
    return code

def save_one_time_code(code, user_id):
    try:
        from app import redis_client
        ONE_TIME_CODE_TTL = 600
        redis_client.setex(f"one_time_code:{code}", ONE_TIME_CODE_TTL, user_id)
        logger.debug(f"[one_time_code][redis][save] code={code}, user_id={user_id}")
    except Exception as e:
        logger.error(f"[one_time_code][redis][save][error] code={code}, user_id={user_id}, error={e}", exc_info=True)

async def handle_add_event(result, calendar_manager, user_id, reply_token):
    try:
        if not all(k in result for k in ['title', 'start_time', 'end_time']):
            await reply_text(reply_token, "予定の追加に必要な情報が不足しています。\nタイトル、開始時間、終了時間を指定してください。")
            return
        add_result = await calendar_manager.add_event(
            title=result['title'],
            start_time=result['start_time'],
            end_time=result['end_time'],
            location=result.get('location'),
            person=result.get('person'),
            description=result.get('description'),
            recurrence=result.get('recurrence')
        )
        if add_result['success']:
            day = result['start_time'].replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
            events = await calendar_manager.get_events(start_time=day, end_time=day_end)
            msg = f"✅ 予定を追加しました：\n{result['title']}\n{result['start_time'].strftime('%m月%d日 %H:%M')}～{result['end_time'].strftime('%H:%M')}\n\n" + format_event_list(events, day, day_end)
            await reply_text(reply_token, msg)
        else:
            if add_result.get('error') == 'duplicate':
                pending_event = {
                    'operation_type': 'add',
                    'title': result['title'],
                    'start_time': result['start_time'].isoformat(),
                    'end_time': result['end_time'].isoformat(),
                    'location': result.get('location'),
                    'person': result.get('person'),
                    'description': result.get('description'),
                    'recurrence': result.get('recurrence'),
                    'force_add': True
                }
                # db_manager.save_pending_event(user_id, pending_event)
            await reply_text(reply_token, f"予定の追加に失敗しました: {add_result.get('message', '不明なエラー')}")
    except Exception as e:
        logger.error(f"予定の追加中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        await reply_text(reply_token, "予定の追加中にエラーが発生しました。\nしばらく時間をおいて再度お試しください。")

async def handle_read_event(result, calendar_manager, user_id, reply_token):
    try:
        if not all(k in result for k in ['start_time', 'end_time']):
            await reply_text(reply_token, "予定の確認に必要な情報が不足しています。\n確認したい日付を指定してください。")
            return
        events = await calendar_manager.get_events(
            start_time=result['start_time'],
            end_time=result['end_time'],
            title=result.get('title')
        )
        formatted_events = []
        for event in events:
            start = event.get('start', {}).get('dateTime', event.get('start', {}).get('date'))
            end = event.get('end', {}).get('dateTime', event.get('end', {}).get('date'))
            if start and end:
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                event['start']['dateTime'] = start_dt.isoformat()
                event['end']['dateTime'] = end_dt.isoformat()
            formatted_events.append(event)
        message = format_event_list(formatted_events, result['start_time'], result['end_time'])
        # user_last_event_list[user_id] = {
        #     'events': formatted_events,
        #     'start_time': result['start_time'],
        #     'end_time': result['end_time']
        # }
        await reply_text(reply_token, message)
    except Exception as e:
        logger.error(f"予定の確認中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        await reply_text(reply_token, "予定の確認中にエラーが発生しました。\nしばらく時間をおいて再度お試しください。")

async def handle_delete_event(result, calendar_manager, user_id, reply_token):
    try:
        delete_result = None
        if 'index' in result:
            delete_result = await calendar_manager.delete_event_by_index(
                index=result['index'],
                start_time=result.get('start_time')
            )
        elif 'start_time' in result and 'end_time' in result:
            matched_events = await calendar_manager._find_events(
                result['start_time'], result['end_time'], result.get('title'))
            if not matched_events:
                await reply_text(reply_token, "指定された日時の予定が見つかりませんでした。")
                return
            if len(matched_events) == 1:
                event = matched_events[0]
                delete_result = await calendar_manager.delete_event(event['id'])
            else:
                msg = "複数の予定が見つかりました。削除したい予定を選んでください:\n" + format_event_list(matched_events)
                await reply_text(reply_token, msg)
                return
        elif 'event_id' in result:
            delete_result = await calendar_manager.delete_event(result['event_id'])
        else:
            await reply_text(reply_token, "削除する予定を特定できませんでした。\n予定の番号またはIDを指定してください。")
            return
        if delete_result and delete_result.get('success'):
            day = result.get('start_time', datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
            events = await calendar_manager.get_events(start_time=day, end_time=day_end)
            msg = delete_result.get('message', '予定を削除しました。')
            msg += f"\n\n{format_event_list(events, day, day_end)}"
            await reply_text(reply_token, msg)
        else:
            await reply_text(reply_token, f"予定の削除に失敗しました: {delete_result.get('message', '不明なエラー')}")
    except Exception as e:
        logger.error(f"予定の削除中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        await reply_text(reply_token, "予定の削除中にエラーが発生しました。\nしばらく時間をおいて再度お試しください。")

async def handle_update_event(result, calendar_manager, user_id, reply_token):
    try:
        if not all(k in result for k in ['start_time', 'end_time', 'new_start_time', 'new_end_time']):
            await reply_text(reply_token, "予定の更新に必要な情報が不足しています。\n更新する予定の時間と新しい時間を指定してください。")
            return
        update_result = await calendar_manager.update_event(
            start_time=result['start_time'],
            end_time=result['end_time'],
            new_start_time=result['new_start_time'],
            new_end_time=result['new_end_time'],
            title=result.get('title')
        )
        if update_result['success']:
            day = result['new_start_time'].replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
            events = await calendar_manager.get_events(start_time=day, end_time=day_end)
            msg = f"予定を更新しました！\n\n" + format_event_list(events, day, day_end)
            await reply_text(reply_token, msg)
        else:
            await reply_text(reply_token, f"予定の更新に失敗しました: {update_result.get('message', '不明なエラー')}")
    except Exception as e:
        logger.error(f"予定の更新中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        await reply_text(reply_token, "予定の更新中にエラーが発生しました。\nしばらく時間をおいて再度お試しください。")

class LineService:
    def __init__(self):
        self.line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
        self.handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
        self.message_parser = MessageParser()
        self.calendar_ops = CalendarOperations()

    def handle_message(self, event: MessageEvent) -> None:
        """
        メッセージイベントを処理
        """
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            logger.info(f"Received message from {user_id}: {message_text}")

            # メッセージを解析
            parsed_data = self.message_parser.parse_message(message_text)
            logger.info(f"Parsed message data: {parsed_data}")

            # 操作タイプに応じて処理
            operation = parsed_data.get('operation', 'unknown')
            
            if operation == 'create':
                self._handle_create_event(event, parsed_data)
            elif operation == 'read':
                self._handle_read_events(event, parsed_data)
            elif operation == 'update':
                self._handle_update_event(event, parsed_data)
            elif operation == 'delete':
                self._handle_delete_event(event, parsed_data)
            elif operation == 'list':
                self._handle_list_events(event, parsed_data)
            elif operation == 'search':
                self._handle_search_events(event, parsed_data)
            elif operation == 'remind':
                self._handle_remind_events(event, parsed_data)
            elif operation == 'help':
                self._handle_help(event)
            else:
                self._handle_unknown_operation(event)

        except Exception as e:
            logger.error(f"Error handling message: {str(e)}", exc_info=True)
            self._send_error_message(event)

    def _handle_create_event(self, event: MessageEvent, parsed_data: Dict) -> None:
        """
        イベント作成を処理
        """
        try:
            title = parsed_data.get('title')
            if not title:
                self._send_message(event, "予定のタイトルを教えてください。\n例：「会議」という予定を登録")
                return

            start_date = parsed_data['date'].get('start_date')
            end_date = parsed_data['date'].get('end_date')
            start_time = parsed_data['time'].get('start_time')
            end_time = parsed_data['time'].get('end_time')

            if not start_date:
                self._send_message(event, "予定の日付を教えてください。\n例：明日の会議を登録")
                return

            # 時刻が指定されていない場合は終日イベントとして扱う
            if not start_time:
                start_time = datetime.combine(start_date.date(), datetime.min.time())
                end_time = datetime.combine(end_date.date(), datetime.max.time())
            else:
                # 日付と時刻を組み合わせる
                start_time = datetime.combine(start_date.date(), start_time.time())
                end_time = datetime.combine(end_date.date(), end_time.time())

            # イベントを作成
            event_data = self.calendar_ops.create_event(
                title=title,
                start_time=start_time,
                end_time=end_time
            )

            # 確認メッセージを送信
            start_str, end_str = self.calendar_ops.format_event_time(event_data)
            message = f"予定を登録しました！\n\n{start_str}～{end_str}\n{title}"
            self._send_message(event, message)

        except Exception as e:
            logger.error(f"Error creating event: {str(e)}", exc_info=True)
            self._send_error_message(event)

    def _handle_read_events(self, event: MessageEvent, parsed_data: Dict) -> None:
        """
        イベント読み取りを処理
        """
        try:
            start_date = parsed_data['date'].get('start_date')
            end_date = parsed_data['date'].get('end_date')

            if not start_date:
                start_date = datetime.now()
                end_date = start_date

            # 時刻が指定されていない場合は終日として扱う
            start_time = datetime.combine(start_date.date(), datetime.min.time())
            end_time = datetime.combine(end_date.date(), datetime.max.time())

            # イベントを取得
            events = self.calendar_ops.get_events(start_time, end_time)
            
            # イベントリストを整形
            message = self.calendar_ops.format_event_list(events)
            self._send_message(event, message)

        except Exception as e:
            logger.error(f"Error reading events: {str(e)}", exc_info=True)
            self._send_error_message(event)

    def _handle_update_event(self, event: MessageEvent, parsed_data: Dict) -> None:
        """
        イベント更新を処理
        """
        try:
            title = parsed_data.get('title')
            if not title:
                self._send_message(event, "更新する予定のタイトルを教えてください。")
                return

            # 該当するイベントを検索
            start_date = parsed_data['date'].get('start_date', datetime.now())
            end_date = parsed_data['date'].get('end_date', start_date + timedelta(days=1))
            
            events = self.calendar_ops.get_events(start_date, end_date)
            matching_events = [e for e in events if e.get('summary') == title]

            if not matching_events:
                self._send_message(event, f"「{title}」という予定が見つかりませんでした。")
                return

            if len(matching_events) > 1:
                # 複数のイベントが見つかった場合は選択肢を表示
                self._show_event_selection(event, matching_events, 'update')
            else:
                # 単一のイベントが見つかった場合は更新フォームを表示
                self._show_update_form(event, matching_events[0])

        except Exception as e:
            logger.error(f"Error updating event: {str(e)}", exc_info=True)
            self._send_error_message(event)

    def _handle_delete_event(self, event: MessageEvent, parsed_data: Dict) -> None:
        """
        イベント削除を処理
        """
        try:
            title = parsed_data.get('title')
            if not title:
                self._send_message(event, "削除する予定のタイトルを教えてください。")
                return

            # 該当するイベントを検索
            start_date = parsed_data['date'].get('start_date', datetime.now())
            end_date = parsed_data['date'].get('end_date', start_date + timedelta(days=1))
            
            events = self.calendar_ops.get_events(start_date, end_date)
            matching_events = [e for e in events if e.get('summary') == title]

            if not matching_events:
                self._send_message(event, f"「{title}」という予定が見つかりませんでした。")
                return

            if len(matching_events) > 1:
                # 複数のイベントが見つかった場合は選択肢を表示
                self._show_event_selection(event, matching_events, 'delete')
            else:
                # 単一のイベントが見つかった場合は削除確認を表示
                self._show_delete_confirmation(event, matching_events[0])

        except Exception as e:
            logger.error(f"Error deleting event: {str(e)}", exc_info=True)
            self._send_error_message(event)

    def _handle_list_events(self, event: MessageEvent, parsed_data: Dict) -> None:
        """
        イベント一覧を処理
        """
        try:
            start_date = parsed_data['date'].get('start_date', datetime.now())
            end_date = parsed_data['date'].get('end_date', start_date + timedelta(days=7))

            # イベントを取得
            events = self.calendar_ops.get_events(start_date, end_date)
            
            if not events:
                self._send_message(event, "指定された期間の予定はありません。")
                return

            # イベントリストを整形
            message = self.calendar_ops.format_event_list(events)
            self._send_message(event, message)

        except Exception as e:
            logger.error(f"Error listing events: {str(e)}", exc_info=True)
            self._send_error_message(event)

    def _handle_search_events(self, event: MessageEvent, parsed_data: Dict) -> None:
        """
        イベント検索を処理
        """
        try:
            title = parsed_data.get('title')
            if not title:
                self._send_message(event, "検索する予定のタイトルを教えてください。")
                return

            # 過去1ヶ月から未来1ヶ月の期間で検索
            start_date = datetime.now() - timedelta(days=30)
            end_date = datetime.now() + timedelta(days=30)
            
            events = self.calendar_ops.get_events(start_date, end_date)
            matching_events = [e for e in events if title in e.get('summary', '')]

            if not matching_events:
                self._send_message(event, f"「{title}」を含む予定は見つかりませんでした。")
                return

            # イベントリストを整形
            message = self.calendar_ops.format_event_list(matching_events)
            self._send_message(event, message)

        except Exception as e:
            logger.error(f"Error searching events: {str(e)}", exc_info=True)
            self._send_error_message(event)

    def _handle_remind_events(self, event: MessageEvent, parsed_data: Dict) -> None:
        """
        イベントリマインダーを処理
        """
        try:
            # 現在時刻から24時間以内のイベントを取得
            start_time = datetime.now()
            end_time = start_time + timedelta(hours=24)
            
            events = self.calendar_ops.get_events(start_time, end_time)
            
            if not events:
                self._send_message(event, "今後24時間以内の予定はありません。")
                return

            # イベントリストを整形
            message = "【今後の予定】\n\n" + self.calendar_ops.format_event_list(events)
            self._send_message(event, message)

        except Exception as e:
            logger.error(f"Error handling reminders: {str(e)}", exc_info=True)
            self._send_error_message(event)

    def _handle_help(self, event: MessageEvent) -> None:
        """
        ヘルプメッセージを表示
        """
        help_message = """【使い方】

1. 予定の登録
「会議」という予定を明日の14時から登録
「打ち合わせ」を来週の月曜日に登録

2. 予定の確認
今日の予定を教えて
明日の予定を確認
来週の予定を見せて

3. 予定の変更
「会議」の時間を変更
「打ち合わせ」を編集

4. 予定の削除
「会議」を削除
「打ち合わせ」を取り消し

5. 予定の検索
「会議」を探す
「打ち合わせ」を検索

6. リマインダー
今後の予定を教えて
予定を通知して

※日付や時刻は以下のように指定できます：
・今日、明日、明後日
・来週、来月
・○月○日
・○曜日
・○時○分
・午前、午後、夜
"""
        self._send_message(event, help_message)

    def _handle_unknown_operation(self, event: MessageEvent) -> None:
        """
        不明な操作に対するメッセージを表示
        """
        message = "申し訳ありません。メッセージの内容が理解できませんでした。\n「使い方」と送信すると、使い方を確認できます。"
        self._send_message(event, message)

    def _show_event_selection(self, event: MessageEvent, events: List[Dict], action: str) -> None:
        """
        イベント選択用のカルーセルを表示
        """
        columns = []
        for evt in events:
            start_str, end_str = self.calendar_ops.format_event_time(evt)
            title = evt.get('summary', 'タイトルなし')
            
            column = CarouselColumn(
                title=title,
                text=f"{start_str}～{end_str}",
                actions=[
                    PostbackAction(
                        label="選択",
                        data=f"action={action}&event_id={evt['id']}"
                    )
                ]
            )
            columns.append(column)

        carousel = CarouselTemplate(columns=columns)
        template_message = TemplateSendMessage(
            alt_text="予定を選択してください",
            template=carousel
        )
        self.line_bot_api.reply_message(event.reply_token, template_message)

    def _show_update_form(self, event: MessageEvent, event_data: Dict) -> None:
        """
        イベント更新用のフォームを表示
        """
        start_str, end_str = self.calendar_ops.format_event_time(event_data)
        title = event_data.get('summary', 'タイトルなし')
        
        bubble = BubbleContainer(
            body=BoxComponent(
                layout="vertical",
                contents=[
                    TextComponent(text="予定を更新", weight="bold", size="xl"),
                    TextComponent(text=f"タイトル: {title}", margin="md"),
                    TextComponent(text=f"開始: {start_str}", margin="sm"),
                    TextComponent(text=f"終了: {end_str}", margin="sm")
                ]
            ),
            footer=BoxComponent(
                layout="vertical",
                contents=[
                    ButtonComponent(
                        style="primary",
                        color="#27AE60",
                        action=MessageAction(
                            label="タイトルを変更",
                            text=f"「{title}」のタイトルを変更"
                        )
                    ),
                    ButtonComponent(
                        style="primary",
                        color="#2980B9",
                        action=MessageAction(
                            label="日時を変更",
                            text=f"「{title}」の日時を変更"
                        )
                    )
                ]
            )
        )
        
        flex_message = FlexSendMessage(
            alt_text="予定の更新",
            contents=bubble
        )
        self.line_bot_api.reply_message(event.reply_token, flex_message)

    def _show_delete_confirmation(self, event: MessageEvent, event_data: Dict) -> None:
        """
        イベント削除の確認メッセージを表示
        """
        start_str, end_str = self.calendar_ops.format_event_time(event_data)
        title = event_data.get('summary', 'タイトルなし')
        
        message = f"以下の予定を削除しますか？\n\n{start_str}～{end_str}\n{title}"
        
        buttons_template = ButtonsTemplate(
            title="予定の削除",
            text=message,
            actions=[
                PostbackAction(
                    label="削除する",
                    data=f"action=confirm_delete&event_id={event_data['id']}"
                ),
                MessageAction(
                    label="キャンセル",
                    text="キャンセル"
                )
            ]
        )
        
        template_message = TemplateSendMessage(
            alt_text="予定の削除確認",
            template=buttons_template
        )
        self.line_bot_api.reply_message(event.reply_token, template_message)

    def _send_message(self, event: MessageEvent, message: str) -> None:
        """
        テキストメッセージを送信
        """
        try:
            self.line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=message)
            )
        except LineBotApiError as e:
            logger.error(f"Error sending message: {str(e)}", exc_info=True)
            raise

    def _send_error_message(self, event: MessageEvent) -> None:
        """
        エラーメッセージを送信
        """
        error_message = "申し訳ありません。エラーが発生しました。\nしばらく時間をおいて再度お試しください。"
        self._send_message(event, error_message) 