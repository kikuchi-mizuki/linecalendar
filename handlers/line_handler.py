from flask import Blueprint, request, abort, session
import json
import asyncio
from linebot.v3.webhooks import MessageEvent, FollowEvent, UnfollowEvent, JoinEvent, LeaveEvent, PostbackEvent, TextMessageContent
from utils.logger import logger
from services.calendar_service import get_calendar_manager
from services.line_service import reply_text, get_auth_url, handle_parsed_message, format_event_list, get_user_credentials
from message_parser import parse_message
import os
import traceback
from datetime import datetime
from utils.db import get_db_connection, db_manager
import logging
import google_auth_oauthlib
from flask import url_for
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

        logger.info(f"Received message from {user_id}: {message_text}")

        # メッセージの解析
        result = None
        if "今日の予定" in message_text:
            result = {"type": "today_schedule"}
        elif "予定を追加" in message_text or "予定追加" in message_text:
            result = {"type": "add_schedule"}
        elif "予定を削除" in message_text or "予定削除" in message_text:
            result = {"type": "delete_schedule"}
        elif "予定を更新" in message_text or "予定更新" in message_text:
            result = {"type": "update_schedule"}
        elif "連携" in message_text or "認証" in message_text:
            result = {"type": "auth"}

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

        # 空き時間キーワードに反応
        free_keywords = ['空いている時間', '空き時間', 'あき時間', '空いてる時間', '空いてる', 'free time', 'free slot']
        if any(kw in message_text for kw in free_keywords):
            # Google認証チェック
            creds = get_user_credentials(user_id)
            if not creds:
                code = get_auth_url(user_id)
                login_url = f"{os.getenv('BASE_URL', 'https://linecalendar-production.up.railway.app')}/onetimelogin"
                msg1 = f"カレンダーを利用するにはGoogle認証が必要です。\nあなたのワンタイムコードは【{code}】です。"
                msg2 = f"下記URLから認証ページにアクセスし、ワンタイムコードを入力してください：\n{login_url}"
                await reply_text(reply_token, [msg1, msg2])
                logger.info(f"[handle_message] Google認証案内送信: user_id={user_id}, code={code}")
                return
            # 認証済みなら空き時間取得
            try:
                calendar_manager = get_calendar_manager(user_id)
                today = datetime.now().astimezone()
                free_slots = calendar_manager.get_free_time_slots(today)
                msg = calendar_manager.format_free_time_slots(free_slots)
                await reply_text(reply_token, msg)
                logger.info(f"[handle_message] 空き時間案内送信: user_id={user_id}")
                return
            except Exception as e:
                logger.error(f"[handle_message] 空き時間取得エラー: {str(e)}")
                await reply_text(reply_token, "空き時間の取得中にエラーが発生しました。管理者にご連絡ください。")
                return
        if not result:
            await reply_text(reply_token, "申し訳ありません。メッセージを理解できませんでした。\n予定の追加、確認、削除、更新のいずれかの操作を指定してください。")
            logger.info(f"[handle_message] メッセージ解析失敗: user_id={user_id}")
            return

        # Google認証チェック
        try:
            creds = get_user_credentials(user_id)
            logger.info(f"[debug] get_user_credentials({user_id}) = {creds}")
            
            if not creds:
                code = get_auth_url(user_id)
                if code is None:
                    # 既存の認証情報がある場合は、それを再利用
                    logger.info(f"[handle_message] 既存の認証情報を再利用: user_id={user_id}")
                    await handle_parsed_message(result, user_id, reply_token)
                    return
                    
                login_url = f"{os.getenv('BASE_URL', 'https://linecalendar-production.up.railway.app')}/onetimelogin"
                msg1 = f"カレンダーを利用するにはGoogle認証が必要です。\nあなたのワンタイムコードは【{code}】です。"
                msg2 = f"下記URLから認証ページにアクセスし、ワンタイムコードを入力してください：\n{login_url}"
                await reply_text(reply_token, [msg1, msg2])
                logger.info(f"[handle_message] Google認証案内送信: user_id={user_id}, code={code}")
                return
                
            calendar_manager = get_calendar_manager(user_id)
            if not calendar_manager:
                code = get_auth_url(user_id)
                if code is None:
                    # 既存の認証情報がある場合は、それを再利用
                    logger.info(f"[handle_message] 既存の認証情報を再利用: user_id={user_id}")
                    await handle_parsed_message(result, user_id, reply_token)
                    return
                    
                login_url = f"{os.getenv('BASE_URL', 'https://linecalendar-production.up.railway.app')}/onetimelogin"
                msg1 = f"カレンダーを利用するにはGoogle認証が必要です。\nあなたのワンタイムコードは【{code}】です。"
                msg2 = f"下記URLから認証ページにアクセスし、ワンタイムコードを入力してください：\n{login_url}"
                await reply_text(reply_token, [msg1, msg2])
                logger.info(f"[handle_message] Google認証案内送信: user_id={user_id}, code={code}")
                return
        except ValueError as e:
            if "Google認証情報が見つかりません" in str(e):
                code = get_auth_url(user_id)
                if code is None:
                    # 既存の認証情報がある場合は、それを再利用
                    logger.info(f"[handle_message] 既存の認証情報を再利用: user_id={user_id}")
                    await handle_parsed_message(result, user_id, reply_token)
                    return
                    
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

        # メッセージの種類に応じて処理
        await handle_parsed_message(result, user_id, reply_token)
        logger.info(f"[handle_message] end: user_id={user_id}")

    except Exception as e:
        logger.error(f"Error in handle_message: {str(e)}")
        logger.error(traceback.format_exc())
        try:
            if event.reply_token:
                await reply_text(event.reply_token, "Google認証が必要です。LINEで「連携」や「認証」と送信してください。")
                logger.info(f"[handle_message] 例外時Google認証案内送信: user_id={getattr(event.source, 'user_id', None)}")
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
