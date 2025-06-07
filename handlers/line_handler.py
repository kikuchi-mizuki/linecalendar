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

logger = logging.getLogger('app')

line_bp = Blueprint('line', __name__)

# --- LINEイベントハンドラ ---
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
                f'{os.getenv("BASE_URL", "https://linecalendar-production.up.railway.app")}/payment/checkout'
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

# --- /callbackエンドポイント ---
@line_bp.route('/callback', methods=['POST'])
def callback():
    try:
        signature = request.headers['X-Line-Signature']
        body = request.get_data(as_text=True)
        events = parser.parse(body, signature)
        
        for event in events:
            if isinstance(event, MessageEvent):
                asyncio.run(handle_message(event))
            elif isinstance(event, FollowEvent):
                asyncio.run(handle_follow(event))
            elif isinstance(event, UnfollowEvent):
                asyncio.run(handle_unfollow(event))
            elif isinstance(event, JoinEvent):
                asyncio.run(handle_join(event))
            elif isinstance(event, LeaveEvent):
                asyncio.run(handle_leave(event))
            elif isinstance(event, PostbackEvent):
                asyncio.run(handle_postback(event))
        
        return 'OK'
    except Exception as e:
        logger.error(f"Error in callback: {str(e)}")
        logger.error(traceback.format_exc())
        return 'Error', 500
