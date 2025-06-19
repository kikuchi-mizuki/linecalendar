from flask import Blueprint, request, abort, session
import json
import asyncio
from linebot.v3.webhooks import MessageEvent, FollowEvent, UnfollowEvent, JoinEvent, LeaveEvent, PostbackEvent, TextMessageContent
from utils.logger import logger
from services.calendar_service import get_calendar_manager
from services.line_service import reply_text, get_auth_url, handle_message, format_event_list, get_user_credentials
from message_parser import parse_message
import os
import traceback
from datetime import datetime, timedelta, timezone
from utils.db import get_db_connection, db_manager
import logging
import google_auth_oauthlib
from flask import url_for
from utils.formatters import format_free_time_calendar, format_simple_free_time
import pytz
# ↓循環import回避のため直接定義
CLIENT_SECRETS_FILE = "client_secret.json"

# GoogleカレンダーAPIのスコープ
SCOPES = ['https://www.googleapis.com/auth/calendar']

logger = logging.getLogger('app')

LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')

line_bp = Blueprint('line', __name__)

# --- LINEイベントハンドラ ---
@line_bp.route('/callback', methods=['POST'])
def callback():
    """LINE Messaging APIからのコールバックを処理する"""
    try:
        signature = request.headers['X-Line-Signature']
        body = request.get_data(as_text=True)
        logger.info(f"Webhook request received: {body}")

        try:
            events = json.loads(body)["events"]
            logger.info(f"Parsed events: {events}")
            for event in events:
                event_type = event.get("type")
                if event_type == "message" and event.get("message", {}).get("type") == "text":
                    asyncio.run(handle_message(MessageEvent.from_dict(event)))
                else:
                    logger.info(f"Unhandled event type: {event_type}")
            logger.info("Webhook request processed successfully")
            return 'OK'
        except InvalidSignatureError:
            logger.error("Invalid signature. Please check your channel access token/channel secret.")
            abort(400)
        except Exception as e:
            logger.error(f"Error in parsing events: {str(e)}")
            logger.error(traceback.format_exc())
            abort(500)
    except Exception as e:
        logger.error(f"Error in callback: {str(e)}")
        logger.error(traceback.format_exc())
        abort(500)

@line_bp.route('/oauth2callback', methods=['GET'])
def oauth2callback():
    try:
        state = session.get('state')
        logger.info(f"[oauth2callback] state={state}, session={dict(session)}")
        if not state:
            logger.error("[oauth2callback] セッション切れ")
            return 'Error: セッションが切れています。もう一度LINEから認証をやり直してください。', 400
        flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            scopes=SCOPES,
            state=state
        )
        flow.redirect_uri = url_for('line.oauth2callback', _external=True)
        authorization_response = request.url
        flow.fetch_token(authorization_response=authorization_response)
        credentials = flow.credentials
        user_id = session.get('line_user_id')
        if isinstance(user_id, bytes):
            user_id = user_id.decode()
        logger.info(f"[oauth2callback] user_id={user_id}, credentials={credentials}")
        if not user_id:
            logger.error("[oauth2callback] user_idがセッションに存在しません")
            return 'Error: No user ID in session', 400
        scopes = credentials.scopes
        if isinstance(scopes, list):
            import json
            scopes = json.dumps(scopes)
        db_manager.save_google_credentials(user_id, {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': scopes,
            'expires_at': credentials.expiry.timestamp() if credentials.expiry else None
        })
        logger.info(f"[oauth2callback] Google credentials saved for user: {user_id}")
        return '認証が完了しました。LINEに戻って予定の確認や追加ができるようになりました。'
    except Exception as e:
        logger.error(f"Error in oauth2callback: {str(e)}")
        logger.error(traceback.format_exc())
        return f"Error: {str(e)}", 500

async def handle_message(event):
    """メッセージイベントを処理する"""
    try:
        if not isinstance(event, MessageEvent):
            logger.warning(f"Invalid event type: {type(event)}")
            return

        if not isinstance(event.message, TextMessageContent):
            logger.warning(f"Invalid message type: {type(event.message)}")
            return

        user_id = event.source.user_id
        message_text = event.message.text
        reply_token = event.reply_token

        # 空き時間キーワードを必ず定義
        free_keywords = ['空いている時間', '空き時間', 'あき時間', '空いてる時間', '空いてる', 'free time', 'free slot']

        logger.info(f"Received message from {user_id}: {message_text}")

        # サブスクリプション確認
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT subscription_status FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        if not user or user['subscription_status'] != 'active':
            msg = (
                'この機能をご利用いただくには、月額プランへのご登録が必要です。\n'
                f'以下のURLからご登録ください：\n'
                f'{os.getenv("BASE_URL", "https://linecalendar-production.up.railway.app")}/payment/checkout?user_id={user_id}'
            )
            await reply_text(reply_token, msg)
            logger.info(f"[handle_message] サブスク未登録案内送信: user_id={user_id}")
            return

        # 空き時間キーワードに反応（キーワードが含まれる場合のみ空き時間分岐）
        if any(kw in message_text for kw in free_keywords):
            creds = get_user_credentials(user_id)
            if not creds:
                code = get_auth_url(user_id)
                login_url = f"{os.getenv('BASE_URL', 'https://linecalendar-production.up.railway.app')}/onetimelogin"
                msg1 = f"カレンダーを利用するにはGoogle認証が必要です。\nあなたのワンタイムコードは【{code}】です。"
                msg2 = f"下記URLから認証ページにアクセスし、ワンタイムコードを入力してください：\n{login_url}"
                await reply_text(reply_token, [msg1, msg2])
                logger.info(f"[handle_message] Google認証案内送信: user_id={user_id}, code={code}")
                return
            try:
                calendar_manager = get_calendar_manager(user_id)
                # 現在の日付をJSTで取得
                JST = pytz.timezone('Asia/Tokyo')
                today = datetime.now(JST)
                # デフォルトは今日のみ
                start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = start_date
                import re
                # 「今日からn週間」パターン
                week_match = re.search(r'今日から(\d+)週間', message_text)
                if week_match:
                    n_weeks = int(week_match.group(1))
                    end_date = start_date + timedelta(days=7*n_weeks-1)
                # 「明日からn週間」パターン
                elif re.search(r'明日から(\d+)週間', message_text):
                    tomorrow_match = re.search(r'明日から(\d+)週間', message_text)
                    n_weeks = int(tomorrow_match.group(1))
                    start_date = start_date + timedelta(days=1)
                    end_date = start_date + timedelta(days=7*n_weeks-1)
                # 「明後日からn週間」パターン
                elif re.search(r'明後日から(\d+)週間', message_text):
                    day_after_tomorrow_match = re.search(r'明後日から(\d+)週間', message_text)
                    n_weeks = int(day_after_tomorrow_match.group(1))
                    start_date = start_date + timedelta(days=2)
                    end_date = start_date + timedelta(days=7*n_weeks-1)
                # 「n週間の空き時間」パターン
                week2_match = re.search(r'(\d+)週間の空き時間', message_text)
                if week2_match:
                    n_weeks = int(week2_match.group(1))
                    end_date = start_date + timedelta(days=7*n_weeks-1)
                # 「今日から1週間」など
                elif '今日から1週間' in message_text:
                    end_date = start_date + timedelta(days=6)
                elif '今日から2週間' in message_text:
                    end_date = start_date + timedelta(days=13)
                # 「明日から1週間」など
                elif '明日から1週間' in message_text:
                    start_date = start_date + timedelta(days=1)
                    end_date = start_date + timedelta(days=6)
                elif '明日から2週間' in message_text:
                    start_date = start_date + timedelta(days=1)
                    end_date = start_date + timedelta(days=13)
                # 「明後日から1週間」など
                elif '明後日から1週間' in message_text:
                    start_date = start_date + timedelta(days=2)
                    end_date = start_date + timedelta(days=6)
                elif '明後日から2週間' in message_text:
                    start_date = start_date + timedelta(days=2)
                    end_date = start_date + timedelta(days=13)
                # 「M/Dの空き時間」パターン
                date_match = re.search(r'(\d{1,2})[\/月](\d{1,2})[日]?(の空き時間)?', message_text)
                if date_match:
                    month = int(date_match.group(1))
                    day = int(date_match.group(2))
                    year = today.year
                    # 年をまたぐ場合の考慮
                    if (month < today.month) or (month == today.month and day < today.day):
                        year += 1
                    start_date = today.replace(year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0)
                    end_date = start_date
                # 空き時間取得
                free_slots_by_day = await calendar_manager.get_free_time_slots_range(start_date, end_date)
                msg = format_simple_free_time(free_slots_by_day)
                await reply_text(reply_token, msg)
                logger.info(f"[handle_message] 空き時間案内送信: user_id={user_id}")
                return
            except Exception as e:
                logger.error(f"[handle_message] 空き時間取得エラー: {str(e)}")
                await reply_text(reply_token, "空き時間の取得中にエラーが発生しました。管理者にご連絡ください。")
                return

        # Google認証チェック
        try:
            creds = get_user_credentials(user_id)
            logger.info(f"[debug] get_user_credentials({user_id}) = {creds}")
            if not creds:
                code = get_auth_url(user_id)
                login_url = f"{os.getenv('BASE_URL', 'https://linecalendar-production.up.railway.app')}/onetimelogin"
                msg1 = f"カレンダーを利用するにはGoogle認証が必要です。\nあなたのワンタイムコードは【{code}】です。"
                msg2 = f"下記URLから認証ページにアクセスし、ワンタイムコードを入力してください：\n{login_url}"
                await reply_text(reply_token, [msg1, msg2])
                logger.info(f"[handle_message] Google認証案内送信: user_id={user_id}, code={code}")
                return
            calendar_manager = get_calendar_manager(user_id)
            if not calendar_manager:
                code = get_auth_url(user_id)
                login_url = f"{os.getenv('BASE_URL', 'https://linecalendar-production.up.railway.app')}/onetimelogin"
                msg1 = f"カレンダーを利用するにはGoogle認証が必要です。\nあなたのワンタイムコードは【{code}】です。"
                msg2 = f"下記URLから認証ページにアクセスし、ワンタイムコードを入力してください：\n{login_url}"
                await reply_text(reply_token, [msg1, msg2])
                logger.info(f"[handle_message] Google認証案内送信: user_id={user_id}, code={code}")
                return
        except ValueError as e:
            if "Google認証情報が見つかりません" in str(e):
                code = get_auth_url(user_id)
                login_url = f"{os.getenv('BASE_URL', 'https://linecalendar-production.up.railway.app')}/onetimelogin"
                msg1 = f"カレンダーを利用するにはGoogle認証が必要です。\nあなたのワンタイムコードは【{code}】です。"
                msg2 = f"下記URLから認証ページにアクセスし、ワンタイムコードを入力してください：\n{login_url}"
                await reply_text(reply_token, [msg1, msg2])
                logger.info(f"[handle_message] Google認証案内送信: user_id={user_id}, code={code}")
                return
            else:
                await reply_text(reply_token, "申し訳ありません。エラーが発生しました。\nしばらく時間をおいて再度お試しください。")
                logger.error(f"[handle_message] その他のValueError: {str(e)}")
                return

        # ここでservices.line_service.handle_messageを呼び出す
        from services.line_service import handle_message as service_handle_message
        await service_handle_message(user_id, message_text, reply_token)
        logger.info(f"[handle_message] end: user_id={user_id}")

    except Exception as e:
        logger.error(f"Error in handle_message: {str(e)}")
        logger.error(traceback.format_exc())
        try:
            if event.reply_token:
                # 例外時もGoogle認証案内を返す
                user_id = getattr(event.source, 'user_id', None)
                if user_id:
                    code = get_auth_url(user_id)
                    login_url = f"{os.getenv('BASE_URL', 'https://linecalendar-production.up.railway.app')}/onetimelogin"
                    msg1 = f"カレンダーを利用するにはGoogle認証が必要です。\nあなたのワンタイムコードは【{code}】です。"
                    msg2 = f"下記URLから認証ページにアクセスし、ワンタイムコードを入力してください：\n{login_url}"
                    await reply_text(event.reply_token, [msg1, msg2])
                    logger.info(f"[handle_message] 例外時Google認証案内送信: user_id={user_id}, code={code}")
                else:
                    await reply_text(event.reply_token, "Google認証が必要です。LINEで『連携』や『認証』と送信してください。")
                    logger.info(f"[handle_message] 例外時Google認証案内送信: user_id=None")
        except Exception as reply_error:
            logger.error(f"Error sending error message: {str(reply_error)}")
        return {'type': 'text', 'text': 'エラーが発生しました。'}

async def handle_follow(event):
    try:
        user_id = event.source.user_id
        logger.info(f"User followed: {user_id}")
        # フォロー時の処理を実装
    except Exception as e:
        logger.error(f"Error in handle_follow: {str(e)}")
        logger.error(traceback.format_exc())

async def handle_unfollow(event):
    try:
        user_id = event.source.user_id
        logger.info(f"User unfollowed: {user_id}")
        # アンフォロー時の処理を実装
    except Exception as e:
        logger.error(f"Error in handle_unfollow: {str(e)}")
        logger.error(traceback.format_exc())

async def handle_join(event):
    try:
        group_id = event.source.group_id
        logger.info(f"Bot joined group: {group_id}")
        # グループ参加時の処理を実装
    except Exception as e:
        logger.error(f"Error in handle_join: {str(e)}")
        logger.error(traceback.format_exc())

async def handle_leave(event):
    try:
        group_id = event.source.group_id
        logger.info(f"Bot left group: {group_id}")
        # グループ退出時の処理を実装
    except Exception as e:
        logger.error(f"Error in handle_leave: {str(e)}")
        logger.error(traceback.format_exc())

async def handle_postback(event):
    try:
        user_id = event.source.user_id
        data = event.postback.data
        logger.info(f"Postback received from {user_id}: {data}")
        # ポストバック時の処理を実装
    except Exception as e:
        logger.error(f"Error in handle_postback: {str(e)}")
        logger.error(traceback.format_exc())
