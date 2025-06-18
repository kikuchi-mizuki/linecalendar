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
    MessageEvent as LineEvent, TextMessage, TextSendMessage,
    TemplateSendMessage, ButtonsTemplate, PostbackAction,
    CarouselTemplate, CarouselColumn, URIAction,
    FlexSendMessage, BubbleContainer, BoxComponent,
    TextComponent, ButtonComponent, MessageAction
)
from message_parser import MessageParser
from calendar_operations import CalendarManager

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
        parser = MessageParser()
        result = parser.parse_message(message)
        print(f"[handle_message] after parse_message: result={result}")
        from services.calendar_service import get_calendar_manager
        calendar_manager = get_calendar_manager(user_id)
        operation = result.get('operation_type')
        logger.debug(f"[handle_parsed_message] 操作タイプ: {operation}")
        
        # 「いいえ」の処理を追加
        if message == "いいえ":
            pending_event = db_manager.get_pending_event(user_id)
            if pending_event:
                db_manager.clear_pending_event(user_id)
                await reply_text(reply_token, "予定の更新をキャンセルしました。")
                return
        
        if operation == 'add':
            await handle_add_event(result, calendar_manager, user_id, reply_token)
        elif operation == 'read':
            # 日付範囲の取得
            start_time = result.get('start_time')
            end_time = result.get('end_time')
            if not start_time:
                # 日付が指定されていない場合は今日の予定を表示
                today = datetime.now(JST).date()
                start_time = datetime.combine(today, datetime.min.time()).replace(tzinfo=JST)
                end_time = datetime.combine(today, datetime.max.time()).replace(tzinfo=JST)
            elif not end_time:
                # 終了日時が指定されていない場合は開始日時と同じ日を終了日時とする
                end_time = start_time.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            events = await calendar_manager.get_events(start_time, end_time)
            msg = format_event_list(events, start_time, end_time)
            await reply_text(reply_token, msg)
        elif operation == 'delete':
            await handle_delete_event(result, calendar_manager, user_id, reply_token)
        elif operation == 'update':
            await handle_update_event(result, calendar_manager, user_id, reply_token)
        elif operation == 'confirm':
            pending_event = db_manager.get_pending_event(user_id)
            if not pending_event:
                await reply_text(reply_token, "強制実行する保留中の操作が見つかりませんでした。")
                return

            op_type = pending_event.get('operation_type')
            # ISO文字列→datetime変換
            def parse_dt(dt):
                if dt is None:
                    return None
                if isinstance(dt, str):
                    try:
                        return datetime.fromisoformat(dt)
                    except Exception:
                        return None
                return dt

            if op_type == 'add':
                add_result = await calendar_manager.add_event(
                    title=pending_event.get('title'),
                    start_time=parse_dt(pending_event.get('start_time')),
                    end_time=parse_dt(pending_event.get('end_time')),
                    location=pending_event.get('location'),
                    person=pending_event.get('person'),
                    description=pending_event.get('description'),
                    recurrence=pending_event.get('recurrence'),
                    skip_overlap_check=True  # 強制追加
                )
                db_manager.clear_pending_event(user_id)
                if add_result['success']:
                    day = parse_dt(pending_event.get('start_time')).replace(hour=0, minute=0, second=0, microsecond=0)
                    day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
                    events = await calendar_manager.get_events(start_time=day, end_time=day_end)
                    msg = f"✅ 予定を追加しました：\n{pending_event.get('title')}\n{pending_event.get('start_time')}～{pending_event.get('end_time')}\n\n" + format_event_list(events, day, day_end)
                else:
                    msg = f"強制追加に失敗しました: {add_result.get('message', '不明なエラー')}"
                await reply_text(reply_token, msg)
                return

            elif op_type == 'update':
                update_result = await calendar_manager.update_event(
                    start_time=parse_dt(pending_event.get('start_time')),
                    end_time=parse_dt(pending_event.get('end_time')),
                    new_start_time=parse_dt(pending_event.get('new_start_time')),
                    new_end_time=parse_dt(pending_event.get('new_end_time')),
                    title=pending_event.get('title'),
                    skip_overlap_check=True  # 強制更新
                )
                db_manager.clear_pending_event(user_id)
                if update_result['success']:
                    day = parse_dt(pending_event.get('new_start_time')).replace(hour=0, minute=0, second=0, microsecond=0)
                    day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
                    events = await calendar_manager.get_events(start_time=day, end_time=day_end)
                    msg = "✅ 予定を更新しました。\n\n" + format_event_list(events, day, day_end)
                else:
                    msg = f"強制更新に失敗しました: {update_result.get('message', '不明なエラー')}"
                await reply_text(reply_token, msg)
                return

            else:
                await reply_text(reply_token, "未対応の保留中操作タイプです。")
                db_manager.clear_pending_event(user_id)
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
                db_manager.save_pending_event(user_id, pending_event)
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
        # 日付＋番号指定での削除
        if 'delete_index' in result and result.get('date'):
            delete_result = await calendar_manager.delete_event_by_index(
                index=result['delete_index'],
                start_time=result['date']
            )
            if delete_result.get('success'):
                # 削除後の予定一覧を表示
                day = result['date']
                day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
                events = await calendar_manager.get_events(start_time=day, end_time=day_end)
                msg = delete_result.get('message', '予定を削除しました。')
                msg += f"\n\n{format_event_list(events, day, day_end)}"
                await reply_text(reply_token, msg)
            else:
                await reply_text(reply_token, f"予定の削除に失敗しました: {delete_result.get('message', '不明なエラー')}")
            return
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
        # インデックス指定がある場合はupdate_event_by_indexを呼ぶ
        if 'update_index' in result and result.get('start_time') and result.get('new_start_time') and result.get('new_end_time'):
            update_result = await calendar_manager.update_event_by_index(
                index=result['update_index'],
                new_start_time=result['new_start_time'],
                new_end_time=result['new_end_time'],
                start_time=result.get('start_time')
            )
        else:
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
            msg = "✅ 予定を更新しました。\n\n" + format_event_list(events, day, day_end)
            await reply_text(reply_token, msg)
        else:
            # 予定更新時に重複が発生した場合はpending_eventを保存
            if update_result.get('error') == 'duplicate':
                pending_event = {
                    'operation_type': 'update',
                    'update_index': result.get('update_index'),
                    'start_time': result.get('start_time').isoformat() if result.get('start_time') else None,
                    'end_time': result.get('end_time').isoformat() if result.get('end_time') else None,
                    'new_start_time': result.get('new_start_time').isoformat() if result.get('new_start_time') else None,
                    'new_end_time': result.get('new_end_time').isoformat() if result.get('new_end_time') else None,
                    'title': result.get('title'),
                    'force_update': True
                }
                db_manager.save_pending_event(user_id, pending_event)
                await reply_text(reply_token, update_result.get('message', '重複しています。強制的に更新しますか？'))
                return
            await reply_text(reply_token, f"予定の更新に失敗しました: {update_result.get('message', '不明なエラー')}")
    except Exception as e:
        logger.error(f"予定の更新中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        await reply_text(reply_token, "予定の更新中にエラーが発生しました。\nしばらく時間をおいて再度お試しください。")

class LineService:
    def __init__(self, channel_access_token: str, calendar_manager: CalendarManager):
        self.line_bot_api = LineBotApi(channel_access_token)
        self.calendar_manager = calendar_manager
        self.parser = MessageParser()

    async def handle_message(self, event: LineEvent) -> None:
        """
        メッセージを処理
        - 非同期処理の実装
        - エラーハンドリングの強化
        """
        try:
            message = event.message.text
            user_id = event.source.user_id

            # メッセージの解析
            parsed = self.parser.parse_message(message)
            operation_type = parsed['operation_type']

            # 操作タイプに応じた処理
            if operation_type == 'add':
                await self._handle_add_event(event, parsed)
            elif operation_type == 'read':
                await self._handle_read_event(event, parsed)
            elif operation_type == 'delete':
                await self._handle_delete_event(event, parsed)
            elif operation_type == 'update':
                await self._handle_update_event(event, parsed)
            else:
                await self._reply_text(event, "申し訳ありません。メッセージを理解できませんでした。")

        except Exception as e:
            logger.error(f"メッセージ処理中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            await self._reply_text(event, "申し訳ありません。エラーが発生しました。")

    async def _handle_add_event(self, event: LineEvent, parsed: Dict) -> None:
        """イベントの追加処理"""
        try:
            if not parsed.get('title'):
                await self._reply_text(event, "予定のタイトルを入力してください。")
                return

            if not parsed.get('start_time'):
                await self._reply_text(event, "予定の開始時刻を入力してください。")
                return

            # イベントの追加
            result = self.calendar_manager.add_event(
                title=parsed['title'],
                start_time=parsed['start_time'],
                end_time=parsed['end_time'],
                description=parsed.get('description')
            )

            if result['success']:
                # 成功メッセージ
                event_time = parsed['start_time'].strftime('%Y年%m月%d日 %H:%M')
                await self._reply_text(event, f"予定を追加しました：\n{parsed['title']}\n{event_time}")
            else:
                if result.get('error') == 'overlap':
                    # 重複イベントの確認
                    overlapping_events = result['overlapping_events']
                    message = "以下の予定と重複しています：\n\n"
                    for i, ev in enumerate(overlapping_events, 1):
                        start = ev['start'].strftime('%H:%M')
                        end = ev['end'].strftime('%H:%M')
                        message += f"{i}. {ev['summary']} ({start}〜{end})\n"
                    message += "\n強制的に追加しますか？"
                    
                    # 確認ボタンの表示
                    await self._reply_confirm_buttons(event, message)
                else:
                    await self._reply_text(event, "予定の追加に失敗しました。")

        except Exception as e:
            logger.error(f"イベント追加処理中にエラーが発生: {str(e)}")
            await self._reply_text(event, "予定の追加中にエラーが発生しました。")

    async def _handle_read_event(self, event: LineEvent, parsed: Dict) -> None:
        """イベントの読み取り処理"""
        try:
            if not parsed.get('start_time'):
                await self._reply_text(event, "日付を指定してください。")
                return

            # イベントの取得
            events = self.calendar_manager.get_events(
                start_time=parsed['start_time'],
                end_time=parsed['end_time']
            )

            if not events:
                await self._reply_text(event, "指定された期間に予定はありません。")
                return

            # イベント一覧の表示
            message = "予定一覧：\n\n"
            for i, ev in enumerate(events, 1):
                start = ev['start'].strftime('%H:%M')
                end = ev['end'].strftime('%H:%M')
                message += f"{i}. {ev['summary']} ({start}〜{end})\n"
                if ev.get('description'):
                    message += f"   {ev['description']}\n"

            await self._reply_text(event, message)

        except Exception as e:
            logger.error(f"イベント読み取り処理中にエラーが発生: {str(e)}")
            await self._reply_text(event, "予定の取得中にエラーが発生しました。")

    async def _handle_delete_event(self, event: LineEvent, parsed: Dict) -> None:
        """イベントの削除処理"""
        try:
            if not parsed.get('title'):
                await self._reply_text(event, "削除する予定のタイトルを入力してください。")
                return

            # イベントの検索
            events = self.calendar_manager.get_events(
                start_time=parsed.get('start_time', datetime.now()),
                end_time=parsed.get('end_time', datetime.now() + timedelta(days=30))
            )

            matching_events = [ev for ev in events if parsed['title'] in ev['summary']]
            if not matching_events:
                await self._reply_text(event, "指定された予定が見つかりませんでした。")
                return

            if len(matching_events) == 1:
                # 単一のイベントを削除
                if self.calendar_manager.delete_event(matching_events[0]['id']):
                    await self._reply_text(event, "予定を削除しました。")
                else:
                    await self._reply_text(event, "予定の削除に失敗しました。")
            else:
                # 複数のイベントが見つかった場合
                message = "複数の予定が見つかりました。削除する予定を選択してください：\n\n"
                for i, ev in enumerate(matching_events, 1):
                    start = ev['start'].strftime('%Y年%m月%d日 %H:%M')
                    end = ev['end'].strftime('%H:%M')
                    message += f"{i}. {ev['summary']} ({start}〜{end})\n"

                await self._reply_text(event, message)

        except Exception as e:
            logger.error(f"イベント削除処理中にエラーが発生: {str(e)}")
            await self._reply_text(event, "予定の削除中にエラーが発生しました。")

    async def _handle_update_event(self, event: LineEvent, parsed: Dict) -> None:
        """イベントの更新処理"""
        try:
            if not parsed.get('title'):
                await self._reply_text(event, "更新する予定のタイトルを入力してください。")
                return

            # イベントの検索
            events = self.calendar_manager.get_events(
                start_time=parsed.get('start_time', datetime.now()),
                end_time=parsed.get('end_time', datetime.now() + timedelta(days=30))
            )

            matching_events = [ev for ev in events if parsed['title'] in ev['summary']]
            if not matching_events:
                await self._reply_text(event, "指定された予定が見つかりませんでした。")
                return

            if len(matching_events) == 1:
                # 単一のイベントを更新
                result = self.calendar_manager.update_event(
                    event_id=matching_events[0]['id'],
                    title=parsed.get('new_title'),
                    start_time=parsed.get('new_start_time'),
                    end_time=parsed.get('new_end_time'),
                    description=parsed.get('new_description')
                )

                if result['success']:
                    await self._reply_text(event, "予定を更新しました。")
                else:
                    if result.get('error') == 'overlap':
                        # 重複イベントの確認
                        overlapping_events = result['overlapping_events']
                        message = "以下の予定と重複しています：\n\n"
                        for i, ev in enumerate(overlapping_events, 1):
                            start = ev['start'].strftime('%H:%M')
                            end = ev['end'].strftime('%H:%M')
                            message += f"{i}. {ev['summary']} ({start}〜{end})\n"
                        message += "\n強制的に更新しますか？"
                        
                        # 確認ボタンの表示
                        await self._reply_confirm_buttons(event, message)
                    else:
                        await self._reply_text(event, "予定の更新に失敗しました。")
            else:
                # 複数のイベントが見つかった場合
                message = "複数の予定が見つかりました。更新する予定を選択してください：\n\n"
                for i, ev in enumerate(matching_events, 1):
                    start = ev['start'].strftime('%Y年%m月%d日 %H:%M')
                    end = ev['end'].strftime('%H:%M')
                    message += f"{i}. {ev['summary']} ({start}〜{end})\n"

                await self._reply_text(event, message)

        except Exception as e:
            logger.error(f"イベント更新処理中にエラーが発生: {str(e)}")
            await self._reply_text(event, "予定の更新中にエラーが発生しました。")

    async def _reply_text(self, event: LineEvent, text: str) -> None:
        """テキストメッセージの送信"""
        try:
            self.line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=text)
            )
        except Exception as e:
            logger.error(f"メッセージ送信中にエラーが発生: {str(e)}")

    async def _reply_confirm_buttons(self, event: LineEvent, text: str) -> None:
        """確認ボタンの表示"""
        try:
            buttons_template = ButtonsTemplate(
                title='確認',
                text=text,
                actions=[
                    MessageAction(label='はい', text='はい'),
                    MessageAction(label='いいえ', text='いいえ')
                ]
            )
            template_message = TemplateSendMessage(
                alt_text='確認',
                template=buttons_template
            )
            self.line_bot_api.reply_message(
                event.reply_token,
                template_message
            )
        except Exception as e:
            logger.error(f"確認ボタン表示中にエラーが発生: {str(e)}") 