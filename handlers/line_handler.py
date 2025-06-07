from flask import Blueprint, request, abort
import json
import asyncio
from linebot.v3.webhooks import MessageEvent, FollowEvent, UnfollowEvent, JoinEvent, LeaveEvent, PostbackEvent
from app import logger, db_manager, get_calendar_manager, reply_text, get_auth_url, parse_message, get_db_connection, handle_parsed_message, format_event_list
import os
import traceback
from datetime import datetime

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
                f'{os.getenv("BASE_URL")}/payment/checkout?user_id={user_id}'
            )
            await reply_text(reply_token, msg)
            return

        # 「はい」返答時のpendingイベント強制追加対応
        if message in ["はい", "はい。", "追加して", "追加", "OK", "ok", "Yes", "yes"]:
            pending_event = db_manager.get_pending_event(user_id)
            if pending_event and pending_event.get('operation_type') == 'add':
                # 予定追加を強制実行
                calendar_manager = get_calendar_manager(user_id)
                add_result = await calendar_manager.add_event(
                    title=pending_event['title'],
                    start_time=datetime.fromisoformat(pending_event['start_time']),
                    end_time=datetime.fromisoformat(pending_event['end_time']),
                    location=pending_event.get('location'),
                    person=pending_event.get('person'),
                    description=pending_event.get('description'),
                    recurrence=pending_event.get('recurrence'),
                    skip_overlap_check=True
                )
                db_manager.clear_pending_event(user_id)
                if add_result['success']:
                    day = datetime.fromisoformat(pending_event['start_time']).replace(hour=0, minute=0, second=0, microsecond=0)
                    day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
                    events = await calendar_manager.get_events(start_time=day, end_time=day_end)
                    msg = f"✅ 予定を追加しました：\n{pending_event['title']}\n{day.strftime('%m月%d日 %H:%M')}～{datetime.fromisoformat(pending_event['end_time']).strftime('%H:%M')}\n\n" + format_event_list(events, day, day_end)
                    await reply_text(reply_token, msg)
                else:
                    await reply_text(reply_token, f"予定の追加に失敗しました: {add_result.get('message', '不明なエラー')}")
                return

        # 「いいえ」や「キャンセル」返答時のpendingイベント削除対応
        if message in ["いいえ", "いいえ。", "キャンセル", "やめる", "中止", "no", "No"]:
            pending_event = db_manager.get_pending_event(user_id)
            if pending_event and pending_event.get('operation_type') == 'add':
                db_manager.clear_pending_event(user_id)
                await reply_text(reply_token, "予定の追加をキャンセルしました。")
                return

        # 通常のメッセージ解析
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
            logger.error(f"エラーメッセージの送信にも失敗: {str(reply_error)}")
            logger.error(traceback.format_exc())

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
        logger.info(f"Webhook request received: {body}")
        try:
            events = json.loads(body)["events"]
            logger.info(f"Parsed events: {events}")
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
                else:
                    logger.info(f"Unhandled event type: {event_type}")
            logger.info("Webhook request processed successfully")
            return 'OK'
        except Exception as e:
            logger.error(f"Error in parsing events: {str(e)}")
            logger.error(e, exc_info=True)
            abort(500)
    except Exception as e:
        logger.error(f"Error in callback: {str(e)}")
        logger.error(e, exc_info=True)
        abort(500)
