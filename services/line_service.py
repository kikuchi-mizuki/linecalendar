import os
import traceback
from utils.logger import logger, db_manager
from datetime import datetime, timedelta
from flask import session
from typing import List, Dict, Union
import time
import json

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
        db_manager.delete_google_credentials(user_id)
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
        if operation_type == 'add':
            await handle_add_event(result, calendar_manager, user_id, reply_token)
        elif operation_type == 'read':
            await handle_read_event(result, calendar_manager, user_id, reply_token)
        elif operation_type == 'delete':
            await handle_delete_event(result, calendar_manager, user_id, reply_token)
        elif operation_type == 'update':
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
        credentials_dict = db_manager.get_user_credentials(user_id)
        logger.debug(f"[get_user_credentials] credentials_dict: {credentials_dict}")
        if not credentials_dict:
            logger.warning(f"認証情報が見つかりません: user_id={user_id}")
            return None
        import google.oauth2.credentials
        from datetime import timezone
        SCOPES = ['https://www.googleapis.com/auth/calendar']
        credentials = google.oauth2.credentials.Credentials(
            token=credentials_dict.get('token'),
            refresh_token=credentials_dict.get('refresh_token'),
            token_uri=credentials_dict.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=credentials_dict.get('client_id'),
            client_secret=credentials_dict.get('client_secret'),
            scopes=credentials_dict.get('scopes', SCOPES)
        )
        if credentials_dict.get('expires_at'):
            credentials.expiry = datetime.fromtimestamp(credentials_dict['expires_at'], tz=timezone.utc)
            logger.info(f"credentials.expiry(set): {credentials.expiry}, type={type(credentials.expiry)}, tzinfo={credentials.expiry.tzinfo}")
            if credentials.expiry.tzinfo is None:
                credentials.expiry = credentials.expiry.replace(tzinfo=timezone.utc)
                logger.info(f"credentials.expiry(replaced): {credentials.expiry}, type={type(credentials.expiry)}, tzinfo={credentials.expiry.tzinfo}")
            logger.info(f"credentials.expiry={credentials.expiry}, now={datetime.now(timezone.utc)}")
        expiry = credentials.expiry if hasattr(credentials, 'expiry') else None
        if expiry and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if (expiry and (expiry - datetime.now(timezone.utc)).total_seconds() < 3600) or credentials.expired:
            try:
                if not credentials.refresh_token:
                    logger.error(f"リフレッシュトークンが存在しません: user_id={user_id}")
                    db_manager.delete_google_credentials(user_id)
                    return None
                credentials.refresh(__import__('google.auth.transport.requests').auth.transport.requests.Request())
                db_manager.save_google_credentials(user_id, {
                    'token': credentials.token,
                    'refresh_token': credentials.refresh_token,
                    'token_uri': credentials.token_uri,
                    'client_id': credentials.client_id,
                    'client_secret': credentials.client_secret,
                    'scopes': credentials.scopes,
                    'expires_at': credentials.expiry.timestamp() if credentials.expiry else None
                })
                logger.info(f"認証トークンをリフレッシュしました: user_id={user_id}")
            except Exception as e:
                logger.error(f"トークンのリフレッシュに失敗: {str(e)}")
                db_manager.delete_google_credentials(user_id)
                return None
        return credentials
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