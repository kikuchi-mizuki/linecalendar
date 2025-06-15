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

async def handle_parsed_message(result, user_id, reply_token):
    try:
        from services.calendar_service import get_calendar_manager
        calendar_manager = get_calendar_manager(user_id)
        operation_type = result.get('operation_type')
        logger.debug(f"[handle_parsed_message] 操作タイプ: {operation_type}")
        if operation_type == 'add_schedule':
            await handle_add_event(result, calendar_manager, user_id, reply_token)
        elif operation_type == 'today_schedule':
            # 今日の予定を取得
            today = datetime.now(JST).date()
            events = calendar_manager.get_events(today)
            msg = format_event_list(events, today, today)
            await reply_text(reply_token, msg)
        elif operation_type == 'delete_schedule':
            await handle_delete_event(result, calendar_manager, user_id, reply_token)
        elif operation_type == 'update_schedule':
            await handle_update_event(result, calendar_manager, user_id, reply_token)
        else:
            await reply_text(reply_token, "未対応の操作です。\n予定の追加、確認、削除、更新のいずれかを指定してください。")
    except Exception as e:
        logger.error(f"メッセージ処理中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        await reply_text(reply_token, "申し訳ありません。エラーが発生しました。\nしばらく時間をおいて再度お試しください。")

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