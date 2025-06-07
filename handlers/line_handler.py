from flask import Blueprint, request, abort
import json
import asyncio
from linebot.v3.webhooks import MessageEvent, FollowEvent, UnfollowEvent, JoinEvent, LeaveEvent, PostbackEvent
from utils.logger import db_manager
from services.calendar_service import get_calendar_manager
from services.line_service import reply_text, get_auth_url, handle_parsed_message, format_event_list
from message_parser import parse_message
import os
import traceback
from datetime import datetime
from utils.db import get_db_connection
import logging
import google_auth_oauthlib
from flask import url_for
from app import CLIENT_SECRETS_FILE

logger = logging.getLogger('app')

LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')

line_bp = Blueprint('line', __name__)

# --- LINEイベントハンドラ ---
@line_bp.route('/callback', methods=['POST'])
def line_callback():
    try:
        body = request.get_data(as_text=True)
        signature = request.headers['X-Line-Signature']
        events = json.loads(body).get("events", [])
        for event in events:
            event_type = event.get("type")
            if event_type == "message" and event.get("message", {}).get("type") == "text":
                asyncio.run(handle_message(MessageEvent.from_dict(event)))
            elif event_type == "follow":
                asyncio.run(handle_follow(FollowEvent.from_dict(event)))
            elif event_type == "unfollow":
                asyncio.run(handle_unfollow(UnfollowEvent.from_dict(event)))
            elif event_type == "join":
                asyncio.run(handle_join(JoinEvent.from_dict(event)))
            elif event_type == "leave":
                asyncio.run(handle_leave(LeaveEvent.from_dict(event)))
            elif event_type == "postback":
                asyncio.run(handle_postback(PostbackEvent.from_dict(event)))
        return 'OK'
    except Exception as e:
        logger.error(f"Error in line_callback: {str(e)}")
        logger.error(traceback.format_exc())
        return 'Error', 500

@line_bp.route('/oauth2callback', methods=['GET'])
def oauth2callback():
    try:
        # Google認証のコールバック処理
        flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            scopes=SCOPES,
            state=session['state']
        )
        flow.redirect_uri = url_for('line.oauth2callback', _external=True)
        authorization_response = request.url
        flow.fetch_token(authorization_response=authorization_response)
        credentials = flow.credentials
        user_id = session.get('line_user_id')
        if not user_id:
            return 'Error: No user ID in session', 400
        db_manager.save_google_credentials(user_id, {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes,
            'expires_at': credentials.expiry.timestamp() if credentials.expiry else None
        })
        return '認証が完了しました。LINEに戻って予定の確認や追加ができるようになりました。'
    except Exception as e:
        logger.error(f"Error in oauth2callback: {str(e)}")
        logger.error(traceback.format_exc())
        return 'Error', 500

async def handle_message(event):
    try:
        user_id = event.source.user_id
        message = event.message.text.strip()
        reply_token = event.reply_token

        if not reply_token:
            logger.warning("reply_tokenがありません。返信できません。")
            return

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
            return

        # メッセージの解析
        result = parse_message(message)
        if not result:
            await reply_text(reply_token, "申し訳ありません。メッセージを理解できませんでした。\n予定の追加、確認、削除、更新のいずれかの操作を指定してください。")
            return

        # カレンダーマネージャーを取得
        try:
            calendar_manager = get_calendar_manager(user_id)
        except ValueError as e:
            if "Google認証情報が見つかりません" in str(e):
                code = get_auth_url(user_id)
                login_url = f"{os.getenv('BASE_URL', 'https://linecalendar-production.up.railway.app')}/onetimelogin"
                msg1 = f"はじめまして！LINEカレンダーをご利用いただきありがとうございます。\nカレンダーを利用するには、Googleアカウントとの連携が必要です。\n\nあなたのワンタイムコードは【{code}】です。"
                msg2 = f"下記のURLから認証ページにアクセスし、ワンタイムコードを入力してください：\n{login_url}\n\n※認証後は、LINEに戻って予定の確認や追加ができるようになります。"
                await reply_text(reply_token, [msg1, msg2])
            else:
                await reply_text(reply_token, "申し訳ありません。エラーが発生しました。\nしばらく時間をおいて再度お試しください。")
            return

        # メッセージの種類に応じて処理
        await handle_parsed_message(result, user_id, reply_token)

    except Exception as e:
        logger.error(f"Error in handle_message: {str(e)}")
        logger.error(traceback.format_exc())
        try:
            if event.reply_token:
                await reply_text(event.reply_token, "申し訳ありません。エラーが発生しました。\nしばらく時間をおいて再度お試しください。")
        except Exception as reply_error:
            logger.error(f"Error sending error message: {str(reply_error)}")

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
