import os
os.makedirs('instance', exist_ok=True)

import pytz
JST = pytz.timezone('Asia/Tokyo')

# 環境変数からclient_secret.jsonを書き出す
client_secret_json = os.getenv("GOOGLE_CLIENT_SECRET")
if client_secret_json:
    with open("client_secret.json", "w") as f:
        f.write(client_secret_json)

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

# LINE Messaging APIのハンドラーを初期化
from linebot.v3 import WebhookHandler
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
if not LINE_CHANNEL_SECRET:
    raise ValueError("LINE_CHANNEL_SECRET is not set")
line_handler = WebhookHandler(LINE_CHANNEL_SECRET)

# LINE Messaging APIクライアントの初期化
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
if not LINE_CHANNEL_ACCESS_TOKEN:
    raise ValueError("LINE_CHANNEL_ACCESS_TOKEN is not set")
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
line_bot_api = MessagingApi(ApiClient(configuration))

import logging
import sys

# ロガーの初期化
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# コンソールハンドラの設定
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)

# ファイルハンドラの設定（常に有効に変更）
from logging.handlers import RotatingFileHandler
file_handler = RotatingFileHandler(
    'app.log',
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5
)
file_handler.setLevel(logging.DEBUG)  # ここを追加
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

# app.loggerのログレベルもDEBUGに設定
try:
    app.logger.setLevel(logging.DEBUG)
    app.logger.addHandler(file_handler)
    app.logger.addHandler(console_handler)
except Exception as e:
    pass

# 特定のライブラリのログレベルを設定
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.ERROR)
logging.getLogger('linebot').setLevel(logging.ERROR)

from flask import Flask, request, abort, session, jsonify, render_template, redirect, url_for, current_app
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    MessagingApi, Configuration, ApiClient, ReplyMessageRequest,
    URIAction, TemplateMessage, ButtonsTemplate, PushMessageRequest,
    TextMessage, FlexMessage
)
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent, FollowEvent, UnfollowEvent,
    JoinEvent, LeaveEvent, PostbackEvent
)
from linebot.v3.messaging import TextMessage
from linebot import LineBotApi  # この行を追加
import os
import traceback
from datetime import datetime, timedelta, timezone
import pytz
import json
import asyncio
import argparse
from functools import wraps, partial
from message_parser import parse_message
from calendar_operations import CalendarManager
from database import DatabaseManager
from typing import List, Dict, Union, Optional
import warnings
import time
from tenacity import retry, stop_after_attempt, wait_exponential
import signal
from contextlib import contextmanager, asynccontextmanager
from werkzeug.middleware.proxy_fix import ProxyFix
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import google.oauth2.credentials
from google_auth_oauthlib.flow import Flow
import google_auth_oauthlib.flow
from googleapiclient import discovery
import requests
import nest_asyncio
import re
from collections import defaultdict
import redis
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException
import random
import string
from flask import render_template_string
from constants import WEEKDAYS
from stripe_manager import StripeManager
import sqlite3

# 警告の抑制
warnings.filterwarnings('ignore', category=DeprecationWarning)

# コマンドライン引数の設定（mainブロック内に移動）
# parser = argparse.ArgumentParser()
# parser.add_argument('--port', type=int, default=3001, help='ポート番号')
# args = parser.parse_args()

# ログ設定
def setup_logging():
    """
    ログ設定を行う
    """
    try:
        # 環境に応じてログレベルを設定
        log_level = os.getenv('LOG_LEVEL', 'INFO')
        numeric_level = getattr(logging, log_level.upper(), None)
        if not isinstance(numeric_level, int):
            raise ValueError(f'Invalid log level: {log_level}')

        # ログフォーマットの設定
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        
        # ログハンドラの設定
        handlers = []
        
        # コンソール出力
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(console_handler)
        
        # ファイル出力（本番環境の場合）
        if os.getenv('ENVIRONMENT') == 'production':
            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                'app.log',
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5
            )
            file_handler.setFormatter(logging.Formatter(log_format))
            handlers.append(file_handler)
        
        # ログ設定の適用
        logging.basicConfig(
            level=numeric_level,
            format=log_format,
            handlers=handlers
        )
        
        # 特定のライブラリのログレベルを設定
        logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)
        logging.getLogger('urllib3').setLevel(logging.ERROR)
        logging.getLogger('linebot').setLevel(logging.ERROR)
        
        global logger
        logger = logging.getLogger(__name__)
        logger.info(f"Logging configured with level: {log_level}")
        
        # Flaskのapp.loggerにも同じハンドラを追加
        if 'app' in globals():
            for handler in handlers:
                app.logger.addHandler(handler)
            app.logger.setLevel(numeric_level)
            app.logger.info("Flask app.logger configured.")
        
    except Exception as e:
        print(f"Error setting up logging: {str(e)}")
        raise

def validate_environment():
    """
    環境変数の検証を行う
    """
    required_vars = {
        'LINE_CHANNEL_ACCESS_TOKEN': str,
        'LINE_CHANNEL_SECRET': str,
        'FLASK_SECRET_KEY': str,
        'GOOGLE_CLIENT_SECRET': str
    }
    
    missing_vars = []
    invalid_vars = []
    
    for var_name, var_type in required_vars.items():
        value = os.getenv(var_name)
        if not value:
            missing_vars.append(var_name)
        elif not isinstance(value, var_type):
            invalid_vars.append(var_name)
    
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    if invalid_vars:
        raise ValueError(f"Invalid environment variables: {', '.join(invalid_vars)}")
    
    # オプションの環境変数の検証
    if os.getenv('ENVIRONMENT') not in [None, 'development', 'production']:
        raise ValueError("ENVIRONMENT must be either 'development' or 'production'")
    
    if os.getenv('PORT'):
        try:
            port = int(os.getenv('PORT'))
            if not (1024 <= port <= 65535):
                raise ValueError
        except ValueError:
            raise ValueError("PORT must be a number between 1024 and 65535")

# Flaskアプリケーションの初期化
app = Flask(__name__, static_folder='static', static_url_path='/static')
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config['PREFERRED_URL_SCHEME'] = 'https'
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-here')

# 静的ファイルの設定
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000  # 1年間のキャッシュ

# Flask-Limiterの設定
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    storage_options={"socket_connect_timeout": 30},
    default_limits=["500 per day", "100 per hour"]  # レート制限を緩和
)

# Redisの設定
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
if not REDIS_URL.endswith('/0'):
    REDIS_URL = REDIS_URL.split('/')[0] + '/0'  # DB番号を0に強制
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_REDIS'] = redis.from_url(REDIS_URL, db=0)
redis_client = app.config['SESSION_REDIS']  # ← ここで統一
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'line_calendar_'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)
app.config['SESSION_REFRESH_EACH_REQUEST'] = True

# セッションのセキュリティ設定
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_DOMAIN'] = '.linecalendar-production.up.railway.app'
app.config['SESSION_COOKIE_PATH'] = '/'

Session(app)

# Redis接続テストとセッション書き込みテスト
try:
    redis_client.ping()
    logger.info(f"[Redis接続テスト] Redisへの接続が成功しました: {REDIS_URL}")
except Exception as e:
    logger.error(f"[Redis接続テスト] Redisへの接続に失敗: {str(e)}")
    logger.error(traceback.format_exc())

def init_session():
    """
    セッションの初期化を行う
    """
    try:
        # Redisの接続確認
        redis_client.ping()
        logger.info("Redisへの接続が成功しました")
        
        # セッションのクリーンアップ
        session_prefix = app.config['SESSION_KEY_PREFIX']
        for key in redis_client.keys(f"{session_prefix}*"):
            redis_client.delete(key)
        
        logger.info("セッションの初期化が完了しました")
    except Exception as e:
        logger.error(f"セッションの初期化に失敗: {str(e)}")
        logger.error(traceback.format_exc())
        raise

# ngrokの設定
# NGROK_URL = "https://3656-113-32-186-176.ngrok-free.app"

# LINE Bot SDKの初期化
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
STRIPE_PRICE_ID = os.getenv('STRIPE_PRICE_ID')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# 環境変数の検証
if not LINE_CHANNEL_ACCESS_TOKEN:
    raise ValueError("LINE_CHANNEL_ACCESS_TOKEN is not set")
if not LINE_CHANNEL_SECRET:
    raise ValueError("LINE_CHANNEL_SECRET is not set")
if not STRIPE_SECRET_KEY:
    raise ValueError("STRIPE_SECRET_KEY is not set")
if not STRIPE_PRICE_ID:
    raise ValueError("STRIPE_PRICE_ID is not set")
if not STRIPE_WEBHOOK_SECRET:
    raise ValueError("STRIPE_WEBHOOK_SECRET is not set")

# LINE Messaging APIの初期化
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))

db_manager = DatabaseManager()

# CalendarManagerの初期化
def get_calendar_manager(user_id: str) -> CalendarManager:
    """
    ユーザーIDに基づいてカレンダーマネージャーを取得する
    
    Args:
        user_id (str): ユーザーID
        
    Returns:
        CalendarManager: カレンダーマネージャーのインスタンス
    """
    try:
        # ユーザーの認証情報を取得
        credentials = get_user_credentials(user_id)
        if not credentials:
            logger.error(f"ユーザー {user_id} の認証情報が見つかりません")
            raise ValueError("Google認証情報が見つかりません")
            
        # カレンダーマネージャーを初期化
        return CalendarManager(credentials)
    except Exception as e:
        logger.error(f"カレンダーマネージャーの初期化に失敗: {str(e)}")
        logger.error(traceback.format_exc())
        raise

# タイムアウト設定
TIMEOUT_SECONDS = 30  # タイムアウトを30秒に延長

# 非同期処理の設定
nest_asyncio.apply()
loop = asyncio.get_event_loop()

def handle_unauthenticated_user(user_id, reply_token):
    """
    未認証ユーザーへのガイダンスメッセージを送信する
    """
    try:
        code = generate_one_time_code()
        save_one_time_code(code, user_id)
        auth_url = f"https://linecalendar-production.up.railway.app/onetimelogin?code={code}"
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[
                    TextMessage(
                        text=f"Googleカレンダーの連携がまだのようです！\n以下のリンクから認証してください👇\n\n{auth_url}"
                    )
                ]
            )
        )
    except Exception as e:
        logger.error(f"[未認証ユーザー] エラー: {e}")
        raise

# handle_text_messageを非同期化
async def handle_text_message(event):
    """テキストメッセージを処理する関数"""
    try:
        user_id = event.source.user_id
        message_text = event.message.text
        reply_token = event.reply_token
        
        logger.info(f"[handle_text_message] メッセージ受信: user_id={user_id}, message={message_text}")
        
        # ユーザーの認証情報を取得
        credentials = get_user_credentials(user_id)
        logger.debug(f"[handle_text_message] credentials: {credentials}")
        
        if not credentials:
            logger.warning(f"[handle_text_message] 認証情報が見つかりません: user_id={user_id}")
            await handle_unauthenticated_user(user_id, reply_token)
            return
        
        # キャンセルパターンのチェック
        if message_text.lower() in ['キャンセル', 'cancel', 'やめる']:
            pending_event = get_pending_event(user_id)
            if pending_event:
                cancel_pending_event(user_id)
                reply_message = f"予定の{pending_event['action']}をキャンセルしました。"
                await send_reply_message(reply_token, reply_message)
                return
        
        # 確認応答の処理
        pending_event = get_pending_event(user_id)
        if pending_event and pending_event.get('waiting_confirmation'):
            if message_text.lower() in ['はい', 'yes', 'y']:
                await handle_message(event)
            else:
                cancel_pending_event(user_id)
                await send_reply_message(reply_token, "操作をキャンセルしました。")
            return
        
        # 通常のメッセージ処理
        await handle_message(event)
            
    except Exception as e:
        logger.error(f"[handle_text_message] エラー: {str(e)}", exc_info=True)
        try:
            await send_reply_message(reply_token, "申し訳ありません。エラーが発生しました。")
        except Exception as send_error:
            logger.error(f"[handle_text_message] エラーメッセージ送信失敗: {str(send_error)}", exc_info=True)

# --- 追加: pending_eventから予定追加を行う非同期関数 ---
async def add_event_from_pending(user_id, reply_token, pending_event):
    try:
        clear_pending_event(user_id)  # 最初に削除（ループ防止）
        calendar_manager = get_calendar_manager(user_id)
        add_result = await calendar_manager.add_event(
            title=pending_event['title'],
            start_time=pending_event['start_time'],
            end_time=pending_event['end_time'],
            location=pending_event.get('location'),
            person=pending_event.get('person'),
            description=pending_event.get('description'),
            recurrence=pending_event.get('recurrence'),
            skip_overlap_check=True
        )
        if add_result['success']:
            day = pending_event['start_time'].replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
            events = await calendar_manager.get_events(start_time=day, end_time=day_end)
            msg = f"✅ 予定を追加しました：\n{pending_event['title']}\n{pending_event['start_time'].strftime('%m月%d日 %H:%M')}～{pending_event['end_time'].strftime('%H:%M')}\n\n" + format_event_list(events, day, day_end)
            await reply_text(reply_token, msg)
        else:
            await reply_text(reply_token, f"予定の追加に失敗しました: {add_result.get('message', '不明なエラー')}")
    except Exception as e:
        logger.error(f"pending_eventから予定追加中にエラー: {str(e)}")
        logger.error(traceback.format_exc())
        await reply_text(reply_token, "予定の追加中にエラーが発生しました。\nしばらく時間をおいて再度お試しください。")

# グローバル変数
user_last_event_list = {}  # ユーザーごとの最後に表示した予定リスト
user_last_delete_candidates = {}  # ユーザーごとの直前の削除候補リスト

@contextmanager
def timeout(seconds):
    def signal_handler(signum, frame):
        raise TimeoutError(f"処理が{seconds}秒でタイムアウトしました")
    
    # SIGALRMハンドラーを設定する前に現在のハンドラーを保存
    original_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        # 元のハンドラーを復元
        signal.signal(signal.SIGALRM, original_handler)

# リトライ設定
MAX_RETRIES = 5
RETRY_DELAY = 2
RETRY_BACKOFF = 1.5

def retry_on_error(func):
    """
    エラー発生時にリトライするデコレータ
    """
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=RETRY_DELAY, exp_base=RETRY_BACKOFF),
        reraise=True,
        before_sleep=lambda retry_state: logger.warning(
            f"Retrying {func.__name__} after {retry_state.attempt_number} attempts"
        )
    )
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {str(e)}")
            logger.error(traceback.format_exc())
            raise
    return wrapper

def require_auth(f):
    """
    ユーザー認証を要求するデコレータ
    
    Args:
        f: デコレートする関数
        
    Returns:
        デコレートされた関数
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = request.args.get('user_id')
        if not user_id or not db_manager.is_authorized(user_id):
            logger.warning(f"未認証ユーザーからのアクセス: {user_id}")
            return "認証が必要です。", 401
        return f(*args, **kwargs)
    return decorated_function

def format_error_message(error: Exception, context: str = "") -> str:
    """
    エラーメッセージを整形する
    
    Args:
        error (Exception): エラーオブジェクト
        context (str): エラーのコンテキスト
        
    Returns:
        str: 整形されたエラーメッセージ
    """
    error_type = type(error).__name__
    error_message = str(error)
    
    if isinstance(error, InvalidSignatureError):
        return "署名の検証に失敗しました。不正なリクエストの可能性があります。"
    elif isinstance(error, ValueError):
        return f"入力値が不正です: {error_message}"
    elif isinstance(error, KeyError):
        return f"必要な情報が不足しています: {error_message}"
    elif "Token has been expired or revoked" in error_message:
        return "Googleカレンダーとの連携が切れているようです。\nもう一度認証を行ってください。\n認証方法は以下の通りです：\n1. 「認証」と送信\n2. 届いたURLをクリック\n3. Googleアカウントでログイン"
    elif "invalid_grant" in error_message:
        return "Googleカレンダーとの連携が切れているようです。\nもう一度認証を行ってください。\n認証方法は以下の通りです：\n1. 「認証」と送信\n2. 届いたURLをクリック\n3. Googleアカウントでログイン"
    else:
        return f"エラーが発生しました: {error_message}\n\n詳細: {context}"

def format_datetime(dt: datetime) -> str:
    """
    日時をフォーマットする
    
    Args:
        dt (datetime): フォーマットする日時
        
    Returns:
        str: フォーマットされた日時文字列
    """
    try:
        # 型チェック
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        
        # タイムゾーンの設定
        if dt.tzinfo is None:
            dt = JST.localize(dt)
        else:
            dt = dt.astimezone(JST)
        
        # 日時のフォーマット
        return dt.strftime('%Y年%m月%d日 %H:%M')
    except Exception as e:
        logger.error(f"日時のフォーマット中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        return ""

def format_response_message(operation_type: str, result: Dict) -> str:
    try:
        if not result.get('success', False):
            return result.get('message', 'うまくできなかったみたい。ごめんね。')
        
        if operation_type == 'add':
            event = result.get('event')
            if event:
                event_data = event.execute()
                return f"『{event_data.get('summary', '')}』を登録したよ！"
            return "予定を登録したよ！"
        
        elif operation_type == 'delete':
            deleted_count = result.get('deleted_count', 0)
            if deleted_count > 0:
                return f"{deleted_count}件の予定を消したよ！"
            else:
                return "ごめん、消せる予定がなかったよ。"
        
        elif operation_type == 'update':
            event = result.get('event')
            if event:
                return "予定を更新しました！"
            return "予定を更新したよ！"
        
        elif operation_type in ['read', 'check', 'list']:
            events = result.get('events', [])
            if not events:
                return "今日は予定ないよ！"
            return format_event_list(events)
        
        return "できたよ！"
    except Exception as e:
        logger.error(f"応答メッセージのフォーマット中にエラーが発生: {str(e)}")
        return "ごめん、エラーが出ちゃった。もう一度試してみてね。"

def format_event_details(event: dict) -> str:
    try:
        start_time = event.get('start', {}).get('dateTime')
        end_time = event.get('end', {}).get('dateTime')
        # 型チェック追加
        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        if isinstance(end_time, str):
            end_time = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        title = event.get('summary', '予定')
        location = event.get('location', '')
        description = event.get('description', '')
        message = f"🗓 {format_datetime(start_time)}〜\n"
        if location:
            message += f"📍 {location}\n"
        message += f"📌 {title}\n"
        if description:
            message += f"👥 {description}\n"
        return message
    except Exception as e:
        logger.error(f"イベント詳細のフォーマット中にエラーが発生: {str(e)}")
        return ""

def format_event_list(events, start_time=None, end_time=None):
    """イベントリストをテキストで整形して表示する（FlexMessageは返さない）"""
    if not events:
        return "今日は予定がありません。"
    lines = []
    for i, event in enumerate(events, 1):
        title = event.get('summary', '（タイトルなし）')
        start = event.get('start', {}).get('dateTime', event.get('start', {}).get('date', ''))
        end = event.get('end', {}).get('dateTime', event.get('end', {}).get('date', ''))
        if 'T' in start and 'T' in end:
            try:
                from datetime import datetime
                import pytz
                JST = pytz.timezone('Asia/Tokyo')
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00')).astimezone(JST)
                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00')).astimezone(JST)
                time_str = f"{start_dt.strftime('%H:%M')}～{end_dt.strftime('%H:%M')}"
            except Exception:
                time_str = "時刻不明"
        else:
            time_str = "終日"
        lines.append(f"{i}. {title}\n   🕘 {time_str}")
    return '\n'.join(lines)

def format_overlapping_events(events):
    """重複する予定を整形して表示する"""
    if not events:
        return "予定はありません。"
    
    # 日付ごとに予定をグループ化
    events_by_date = defaultdict(list)
    for event in events:
        start_time = event['start']
        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        date_key = start_time.strftime('%Y-%m-%d')
        events_by_date[date_key].append(event)
    
    # 日付ごとに予定を表示
    formatted_events = []
    for date in sorted(events_by_date.keys()):
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        weekday = WEEKDAYS[date_obj.weekday()]
        formatted_events.append(f"🗓 {date_obj.strftime('%Y/%m/%d')}（{weekday}）")
        formatted_events.append("━━━━━━━━━━━━")
        
        # その日の予定を時間順にソート
        day_events = sorted(events_by_date[date], 
                          key=lambda x: datetime.fromisoformat(x['start'].replace('Z', '+00:00')))
        
        for event in day_events:
            start = event['start']
            end = event['end']
            if isinstance(start, str):
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
            else:
                start_dt = start
                end_dt = end
            
            # 予定の詳細を整形
            event_details = []
            event_details.append(f"📌 {event.get('summary', '予定なし')}")
            event_details.append(f"⏰ {start_dt.strftime('%H:%M')}～{end_dt.strftime('%H:%M')}")
            
            if event.get('location'):
                event_details.append(f"📍 {event['location']}")
            if event.get('description'):
                event_details.append(f"📝 {event['description']}")
            
            formatted_events.append("\n".join(event_details))
            formatted_events.append("")
        
        formatted_events.append("━━━━━━━━━━━━")
    
    return "\n".join(formatted_events)

@app.route("/callback", methods=['POST'])
def callback():
    """
    LINE Messaging APIからのwebhookリクエストを処理する
    """
    try:
        # リクエストの署名を取得
        signature = request.headers.get('X-Line-Signature', '')
        if not signature:
            logger.error("X-Line-Signature header is missing")
            abort(400)

        # リクエストボディを取得
        body = request.get_data(as_text=True)
        logger.info(f"[callback] Request body: {body}")

        # LINEハンドラーの存在確認
        if line_handler is None:
            logger.error("[callback] LINE handler is not initialized")
            abort(500)

        # 署名の検証とイベントの処理
        try:
            line_handler.handle(body, signature)  # awaitを削除
            logger.info("[callback] Successfully handled webhook request")
        except InvalidSignatureError:
            logger.error("[callback] Invalid signature")
            abort(400)
        except Exception as e:
            logger.error(f"[callback] Error in line_handler.handle: {str(e)}")
            logger.error(traceback.format_exc())
            abort(500)

        return 'OK'

    except Exception as e:
        logger.error(f"[callback] Error in callback: {str(e)}")
        logger.error(traceback.format_exc())
        abort(500)

@line_handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        logger.info(f"[handle_message] メッセージを受信: {event.message.text}")
        logger.info(f"[handle_message] reply_token: {event.reply_token}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="✅ メッセージを受け取りました！")
        )
        logger.info("[handle_message] 応答メッセージを送信しました")
    except Exception as e:
        logger.error(f"[handle_message] エラーが発生しました: {str(e)}")
        logger.error(traceback.format_exc())
        try:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="申し訳ありません。エラーが発生しました。")
            )
        except Exception as reply_error:
            logger.error(f"[handle_message] エラー通知の送信に失敗: {str(reply_error)}")
            logger.error(traceback.format_exc())

@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    """StripeのWebhookを処理"""
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')

    try:
        stripe_manager = StripeManager()
        if stripe_manager.handle_webhook(payload, sig_header, line_bot_api):
            return jsonify({'status': 'success'}), 200
        else:
            return jsonify({'status': 'error'}), 400
    except Exception as e:
        current_app.logger.error(f"Webhook error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.before_request
def before_request():
    """
    リクエスト前の処理
    """
    try:
        # セッションの有効期限チェック
        if session.get('last_activity'):
            last_activity = datetime.fromtimestamp(session['last_activity'], tz=timezone.utc)
            if datetime.now(timezone.utc) - last_activity > timedelta(hours=2):
                session.clear()
                logger.info("セッションが期限切れのためクリアしました")
                return
        # セッションのアクティビティを更新
        session['last_activity'] = time.time()
        session.modified = True

        # 認証フローのセッション管理
        if request.endpoint in ['authorize', 'oauth2callback']:
            if request.endpoint == 'authorize':
                # authorizeエンドポイントでは新しいセッションを開始
                user_id = request.args.get('user_id')
                if user_id:
                    session.clear()
                    session['line_user_id'] = user_id
                    session['auth_start_time'] = time.time()
                    session['last_activity'] = time.time()
                    session['auth_state'] = 'started'
                    session.permanent = True
                    session.modified = True
                    logger.info(f"新しい認証セッションを開始: user_id={user_id}")
            elif request.endpoint == 'oauth2callback':
                # oauth2callbackエンドポイントではセッションの有効性をチェック
                if not session.get('auth_start_time'):
                    logger.error("認証セッションが開始されていません")
                    return '認証セッションが開始されていません。最初からやり直してください。', 400
                if not session.get('line_user_id'):
                    logger.error("ユーザーIDがセッションにありません")
                    return 'ユーザーIDが取得できませんでした。LINEからやり直してください。', 400
                if not session.get('state'):
                    logger.error("セッションにstateがありません")
                    return '認証セッションが不正です。最初からやり直してください。', 400
                if session.get('auth_state') != 'started':
                    logger.error("認証状態が不正です")
                    send_one_time_code(user_id)
                    return '認証状態が不正です。最初からやり直してください。', 400
                # 認証セッションの有効期限チェック
                auth_start_time = datetime.fromtimestamp(session['auth_start_time'], tz=timezone.utc)
                if datetime.now(timezone.utc) - auth_start_time > timedelta(minutes=30):
                    session.clear()
                    logger.info("認証セッションが期限切れ")
                    return '認証セッションが期限切れです。最初からやり直してください。', 400

        # HTTPアクセスをHTTPSにリダイレクト
        if not request.is_secure and request.headers.get('X-Forwarded-Proto', 'https') != 'https':
            url = request.url.replace("http://", "https://", 1)
            return redirect(url, code=301)

    except Exception as e:
        logger.error(f"Error in before_request: {str(e)}")
        logger.error(traceback.format_exc())
        abort(500)

@app.after_request
def after_request(response):
    """
    リクエスト後の処理
    """
    try:
        # セッションの更新
        if 'last_activity' in session:
            session['last_activity'] = time.time()
            session.permanent = True
            session.modified = True
        
        # セキュリティヘッダーの追加
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Content-Security-Policy'] = "default-src 'self'; frame-ancestors 'none'"
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        
        return response
    except Exception as e:
        logger.error(f"Error in after_request: {str(e)}")
        logger.error(traceback.format_exc())
        return response

@app.errorhandler(400)
def bad_request_error(error):
    """
    400 Bad Requestエラーハンドラー
    """
    logger.error(f"400 Bad Request Error: {str(error)}")
    logger.error(f"Request Headers: {dict(request.headers)}")
    logger.error(f"Request Data: {request.get_data()}")
    return jsonify({
        'error': 'Bad Request',
        'message': 'リクエストが不正です。',
        'details': str(error),
        'status_code': 400
    }), 400

@app.errorhandler(401)
def unauthorized_error(error):
    """
    401 Unauthorizedエラーハンドラー
    """
    logger.error(f"401 Unauthorized Error: {str(error)}")
    logger.error(f"Request Headers: {dict(request.headers)}")
    logger.error(f"Request Data: {request.get_data()}")
    return jsonify({
        'error': 'Unauthorized',
        'message': '認証が必要です。',
        'details': str(error),
        'status_code': 401
    }), 401

@app.errorhandler(403)
def forbidden_error(error):
    """
    403 Forbiddenエラーハンドラー
    """
    logger.error(f"403 Forbidden Error: {str(error)}")
    logger.error(f"Request Headers: {dict(request.headers)}")
    logger.error(f"Request Data: {request.get_data()}")
    return jsonify({
        'error': 'Forbidden',
        'message': 'アクセスが禁止されています。',
        'details': str(error),
        'status_code': 403
    }), 403

@app.errorhandler(404)
def not_found_error(error):
    logger.error(f"404 Not Found: {request.url}")
    return jsonify({
        "error": "Not Found",
        "message": "リクエストされたURLが見つかりませんでした。",
        "status_code": 404
    }), 404

@app.errorhandler(413)
def request_entity_too_large_error(error):
    """
    413 Request Entity Too Largeエラーハンドラー
    """
    logger.error(f"413 Request Entity Too Large Error: {str(error)}")
    logger.error(f"Request Headers: {dict(request.headers)}")
    logger.error(f"Request Data: {request.get_data()}")
    return jsonify({
        'error': 'Request Entity Too Large',
        'message': 'リクエストのサイズが大きすぎます。',
        'details': str(error),
        'status_code': 413
    }), 413

@app.errorhandler(429)
def too_many_requests_error(error):
    """
    429 Too Many Requestsエラーハンドラー
    """
    logger.error(f"429 Too Many Requests Error: {str(error)}")
    logger.error(f"Request Headers: {dict(request.headers)}")
    logger.error(f"Request Data: {request.get_data()}")
    return jsonify({
        'error': 'Too Many Requests',
        'message': 'リクエストが多すぎます。しばらく時間をおいて再度お試しください。',
        'details': str(error),
        'status_code': 429
    }), 429

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 Internal Server Error: {str(error)}")
    return jsonify({
        "error": "Internal Server Error",
        "message": "サーバーでエラーが発生しました。",
        "status_code": 500
    }), 500

@app.errorhandler(Exception)
def handle_exception(error):
    logger.error(f"Unhandled Exception: {str(error)}")
    logger.error(f"Request Headers: {dict(request.headers)}")
    logger.error(f"Request Data: {request.get_data()}")
    logger.error(f"Traceback: {traceback.format_exc()}")
    return jsonify({
        "error": "Internal Server Error",
        "message": "サーバーでエラーが発生しました。",
        "status_code": 500
    }), 500

# Google連携ボタンをLINEユーザーに送信する関数
def delete_all_one_time_codes_for_user(user_id):
    pattern = f"one_time_code:*"
    for key in redis_client.scan_iter(pattern):
        if redis_client.get(key) and redis_client.get(key).decode() == user_id:
            redis_client.delete(key)
            logger.debug(f"[one_time_code][redis][delete-old] key={key} for user_id={user_id}")

def log_all_one_time_codes():
    try:
        keys = list(redis_client.scan_iter('one_time_code:*'))
        logger.debug(f"[one_time_code][redis][all_keys] {keys}")
        for key in keys:
            val = redis_client.get(key)
            logger.debug(f"[one_time_code][redis][key] {key} => {val}")
    except Exception as e:
        logger.error(f"[one_time_code][redis][log_all] error: {e}")

# ワンタイムコード発行時

def send_one_time_code(user_id):
    delete_all_one_time_codes_for_user(user_id)
    code = generate_one_time_code()
    save_one_time_code(code, user_id)
    log_all_one_time_codes()  # 本番でもログは残す
    message = f"Googleカレンダー連携用ワンタイムコード: {code}\nhttps://linecalendar-production.up.railway.app/onetimelogin"
    try:
        line_bot_api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text=message)]
            )
        )
        logger.info(f"[send_one_time_code] push_message sent to {user_id} with code {code}")
    except Exception as e:
        logger.error(f"[send_one_time_code] LINE push_message error: {e}")
        logger.error(traceback.format_exc())

# ワンタイムコード削除時

def delete_all_one_time_codes_for_user(user_id):
    pattern = f"one_time_code:*"
    for key in redis_client.scan_iter(pattern):
        try:
            val = redis_client.get(key)
            if val and val.decode() == user_id:
                redis_client.delete(key)
                logger.debug(f"[one_time_code][redis][delete-old] key={key} for user_id={user_id}")
        except Exception as e:
            logger.error(f"[one_time_code][redis][delete-old][error] key={key}, error={e}")

# /authorizeでuser_idを受け取ってセッションに保存
@app.route('/authorize')
def authorize():
    print(f"[PRINT Cookie: /authorize] session={request.cookies.get('session')}")
    logger.info(f"[Cookie: /authorize] session={request.cookies.get('session')}")
    try:
        logger.info(f"[セッション内容: /authorize] {dict(session)}")
        user_id = request.args.get('user_id')
        if not user_id:
            logger.error("user_idが指定されていません")
            return 'ユーザーIDが指定されていません。', 400

        # セッションの初期化
        session.clear()
        session['line_user_id'] = user_id
        session['auth_start_time'] = time.time()
        session['last_activity'] = time.time()
        session.permanent = True

        # 既存の認証情報を削除
        db_manager.delete_google_credentials(user_id)

        flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            scopes=SCOPES
        )
        flow.redirect_uri = url_for('oauth2callback', _external=True)
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        session['state'] = state
        logger.info(f"認証フローを開始: user_id={user_id}, state={state}")
        return redirect(authorization_url)
    except Exception as e:
        logger.error(f"認証フローの開始に失敗: {str(e)}")
        logger.error(traceback.format_exc())
        return '認証の開始に失敗しました。もう一度お試しください。', 500

# /oauth2callbackでuser_idとトークンをuser_tokens.jsonに保存
@app.route('/oauth2callback')
@limiter.limit("5 per minute")
def oauth2callback():
    try:
        # ユーザーIDを最初に取得
        user_id = request.args.get('state')
        if not user_id:
            app.logger.error("[oauth2callback] stateパラメータが見つかりません")
            return "認証エラー: ユーザーIDが見つかりません", 400

        app.logger.info(f"[oauth2callback] ユーザーID: {user_id}")

        # スコープを明示的に指定
        flow = Flow.from_client_secrets_file(
            'client_secret.json',
            scopes=['https://www.googleapis.com/auth/calendar'],
            redirect_uri=url_for('oauth2callback', _external=True)
        )

        # トークンを取得
        flow.fetch_token(authorization_response=request.url)
        credentials = flow.credentials

        # 認証情報を保存
        credentials_dict = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes,
            'expires_at': credentials.expiry.timestamp() if credentials.expiry else None
        }

        # データベースに保存
        db_manager = DatabaseManager()
        db_manager.save_google_credentials(user_id, credentials_dict)
        app.logger.info(f"[oauth2callback] 認証情報を保存しました: {user_id}")

        # LINEに通知
        line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
        message = TextSendMessage(text="Googleカレンダーとの連携が完了しました！\n「予定を確認」と送信して、予定を確認できます。")
        line_bot_api.push_message(user_id, message)

        return "認証が完了しました。このページを閉じて、LINEに戻ってください。"

    except Exception as e:
        app.logger.error(f"[oauth2callback] エラー発生: {str(e)}")
        app.logger.error(traceback.format_exc())
        
        # エラー通知をLINEに送信
        try:
            if user_id:
                line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
                error_message = TextSendMessage(text="申し訳ありません。認証中にエラーが発生しました。\nもう一度お試しください。")
                line_bot_api.push_message(user_id, error_message)
        except Exception as line_error:
            app.logger.error(f"[oauth2callback] エラー通知のLINE Pushに失敗: {str(line_error)}")
        
        return "認証エラーが発生しました。LINEに戻って、もう一度お試しください。", 500

SCOPES = ['https://www.googleapis.com/auth/calendar']
CLIENT_SECRETS_FILE = "client_secret.json"

# LINE Messaging APIの設定
MAX_RETRIES = 3
RETRY_DELAY = 1  # 秒
TIMEOUT_SECONDS = 10

async def reply_text(reply_token: str, texts: Union[str, List[str]]) -> None:
    """
    LINE Messaging APIを使用してテキストメッセージを送信する
    
    Args:
        reply_token (str): リプライトークン
        texts (Union[str, List[str]]): 送信するテキスト（文字列または文字列のリスト）
    """
    try:
        if not reply_token:
            logger.error("reply_tokenが空です")
            return

        if not texts:
            logger.error("送信するテキストが空です")
            return

        # テキストが文字列の場合はリストに変換
        if isinstance(texts, str):
            texts = [texts]

        # メッセージの長さ制限（2000文字）を考慮して分割
        messages = []
        current_message = []
        current_length = 0

        for text in texts:
            if current_length + len(text) > 1900:  # 余裕を持って1900文字に制限
                messages.append("\n".join(current_message))
                current_message = [text]
                current_length = len(text)
            else:
                current_message.append(text)
                current_length += len(text)

        if current_message:
            messages.append("\n".join(current_message))

        # 各メッセージを送信
        for message in messages:
            try:
                line_bot_api.reply_message(
                    reply_token,
                    TextMessage(text=message)
                )
                logger.info(f"メッセージを送信しました: {message[:100]}...")
            except Exception as e:
                logger.error(f"メッセージの送信中にエラーが発生: {str(e)}")
                logger.error(traceback.format_exc())
                # エラーメッセージを送信
                try:
                    error_message = "申し訳ありません。メッセージの送信に失敗しました。しばらく時間をおいて再度お試しください。"
                    line_bot_api.reply_message(
                        reply_token,
                        TextMessage(text=error_message)
                    )
                except Exception as inner_e:
                    logger.error(f"エラーメッセージの送信にも失敗: {str(inner_e)}")

    except Exception as e:
        logger.error(f"reply_textで予期せぬエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())

async def push_message(user_id: str, texts: Union[str, List[str]]) -> None:
    """LINEへのプッシュメッセージを送信する（テキストのみ、リトライロジック付き）"""
    try:
        logger.debug(f"LINEへのプッシュメッセージを開始: {texts}")
        if isinstance(texts, str):
            texts = [texts]
        messages = [TextMessage(text=text) for text in texts]
        logger.debug(f"送信するメッセージ: {messages}")
        for attempt in range(MAX_RETRIES):
            try:
                async with async_timeout(TIMEOUT_SECONDS):
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: line_bot_api.push_message(
                            PushMessageRequest(
                                to=user_id,
                                messages=messages
                            )
                        )
                    )
                    logger.debug("LINEへのプッシュメッセージが完了")
                    return
            except Exception as e:
                logger.error(f"LINEへのプッシュメッセージ中にエラーが発生: {str(e)}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                raise
    except TimeoutError:
        logger.error(f"LINEへのプッシュメッセージがタイムアウトしました（{TIMEOUT_SECONDS}秒）")
        raise
    except Exception as e:
        logger.error(f"LINEへのプッシュメッセージ中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        raise

async def handle_update(user_id: str, message: str) -> str:
    """予定の更新を処理"""
    try:
        # メッセージから日時を抽出
        datetime_info = extract_datetime_from_message(message, 'update')
        if not datetime_info:
            return "予定の更新に必要な情報が見つかりませんでした。\n例: 5月10日1番の予定を12時に変更"

        # 番号指定による更新の場合
        if 'delete_index' in datetime_info:
            # 指定された日付の予定を取得
            events = await get_events_for_date(user_id, datetime_info['start_time'])
            if not events:
                return "指定された日付の予定が見つかりませんでした。"

            # インデックスが範囲内かチェック
            index = datetime_info['delete_index'] - 1  # 1-based to 0-based
            if index < 0 or index >= len(events):
                return f"指定された番号の予定が見つかりませんでした。1から{len(events)}までの番号を指定してください。"

            # 更新対象の予定を取得
            event = events[index]

            # 時間の長さ変更の場合
            if 'duration' in datetime_info:
                start_time = event['start']
                end_time = start_time + datetime_info['duration']
                await update_event(user_id, event['id'], start_time, end_time)
                return f"予定を{format_duration(datetime_info['duration'])}に変更しました！\n\n{format_event_list(events)}"

            # 時間変更の場合
            if 'new_hour' in datetime_info:
                new_hour = datetime_info['new_hour']
                start_time = event['start'].replace(hour=new_hour, minute=0)
                end_time = start_time + timedelta(hours=1)
                await update_event(user_id, event['id'], start_time, end_time)
                return f"予定を{new_hour}時に変更しました！\n\n{format_event_list(events)}"

        # 時間範囲による更新の場合
        if 'new_start_time' in datetime_info:
            # 元の時間範囲の予定を検索
            events = await get_events_for_date(user_id, datetime_info['start_time'])
            if not events:
                return "更新対象の予定が見つかりませんでした。"

            # 時間範囲が一致する予定を探す
            target_event = None
            for event in events:
                if (event['start'] == datetime_info['start_time'] and 
                    event['end'] == datetime_info['end_time']):
                    target_event = event
                    break

            if not target_event:
                return "更新対象の予定が見つかりませんでした。"

            # 予定を更新
            await update_event(
                user_id,
                target_event['id'],
                datetime_info['new_start_time'],
                datetime_info['new_end_time']
            )
            return "予定の時間を更新しました。"

        return "予定の更新に必要な情報が不足しています。"

    except Exception as e:
        logger.error(f"予定の更新中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        return "予定の更新中にエラーが発生しました。"

def format_duration(duration: timedelta) -> str:
    """時間の長さをフォーマットする"""
    total_seconds = int(duration.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    
    if hours > 0 and minutes > 0:
        return f"{hours}時間{minutes}分"
    elif hours > 0:
        return f"{hours}時間"
    else:
        return f"{minutes}分"

def check_event_overlap(start_time: datetime, end_time: datetime, events: List[Dict]) -> bool:
    """指定された時間帯に重複する予定があるかチェックする"""
    if start_time is None or end_time is None:
        logger.error("start_time or end_time is None")
        return False
        
    for event in events:
        try:
            # イベントの開始・終了時間を取得
            event_start_str = event.get('start', {}).get('dateTime')
            event_end_str = event.get('end', {}).get('dateTime')
            
            if not event_start_str or not event_end_str:
                logger.error(f"Invalid event time format: {event}")
                continue
                
            # 文字列をdatetimeに変換
            event_start = datetime.fromisoformat(event_start_str.replace('Z', '+00:00'))
            event_end = datetime.fromisoformat(event_end_str.replace('Z', '+00:00'))
            
            # 時間帯が重複しているかチェック
            if (start_time < event_end and end_time > event_start and start_time != event_end and end_time != event_start):
                return True
                
        except (KeyError, ValueError) as e:
            logger.error(f"Error parsing event time: {str(e)}, event: {event}")
            continue
            
    return False

async def update_event_by_index(calendar_id: str, index: int, new_start_time: datetime, new_end_time: datetime, new_title: str, new_description: str = None, skip_overlap_check: bool = False) -> dict:
    try:
        calendar_manager = get_calendar_manager(calendar_id)
        if not calendar_manager:
            logger.error(f"カレンダーマネージャーが見つかりません: {calendar_id}")
            return {'success': False, 'error': 'カレンダーマネージャーが見つかりません'}

        events = await calendar_manager.get_events()
        if not events:
            logger.error(f"予定が見つかりません: {calendar_id}")
            return {'success': False, 'error': '予定が見つかりません'}

        if index < 0 or index >= len(events):
            logger.error(f"無効なインデックスです: {index}")
            return {'success': False, 'error': '無効なインデックスです'}

        # 重複チェック（skip_overlap_checkがFalseの場合のみ）
        if not skip_overlap_check:
            other_events = [e for i, e in enumerate(events) if i != index]
            if check_event_overlap(new_start_time, new_end_time, other_events):
                pending_event = {
                    "calendar_id": calendar_id,
                    "start_time": new_start_time.isoformat(),
                    "end_time": new_end_time.isoformat(),
                    "title": new_title,
                    "description": new_description,
                    "operation_type": "update",
                    "delete_index": index
                }
                save_pending_event(calendar_id, pending_event)
                return {'success': False, 'error': '重複あり', 'pending': True}

        # 予定を更新
        event = events[index]
        event['start'] = {'dateTime': new_start_time.isoformat(), 'timeZone': 'Asia/Tokyo'}
        event['end'] = {'dateTime': new_end_time.isoformat(), 'timeZone': 'Asia/Tokyo'}
        if new_title:
            event['summary'] = new_title
        if new_description:
            event['description'] = new_description

        updated_event = await calendar_manager.update_event(event) if hasattr(calendar_manager.update_event, '__await__') else calendar_manager.update_event(event)
        logger.info(f"予定を更新しました: {event.get('summary', '')} ({new_start_time} - {new_end_time})")
        return {'success': True, 'event': event}

    except Exception as e:
        logger.error(f"予定の更新中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        return {'success': False, 'error': str(e)}

async def handle_yes_response(calendar_id: str) -> str:
    """
    「はい」の返答を処理する
    """
    try:
        # 保留中のイベントを取得
        pending_event = get_pending_event(calendar_id)
        if not pending_event:
            return "確認中の予定がありません。"

        # カレンダーマネージャーを取得
        calendar_manager = get_calendar_manager(calendar_id)
        if not calendar_manager:
            return "カレンダーへのアクセス権限がありません。認証が必要です。"

        # 操作タイプに応じて処理を分岐
        operation_type = pending_event.get('operation_type')
        logger.debug(f"[pending_event] on yes: {pending_event}")
        if operation_type == 'add':
            # 予定追加の処理
            result = await calendar_manager.add_event(
                title=pending_event['title'],
                start_time=pending_event['start_time'],
                end_time=pending_event['end_time'],
                description=pending_event.get('description'),
                location=pending_event.get('location'),
                recurrence=pending_event.get('recurrence')
            )
            clear_pending_event(calendar_id)
            return format_response_message('add', result)
        elif operation_type == 'update':
            # 予定更新の処理
            event_id = pending_event.get('event_id')
            if not event_id:
                return "更新対象の予定を特定できませんでした。もう一度お試しください。"
            new_start_time = pending_event.get('new_start_time')
            new_end_time = pending_event.get('new_end_time')
            if not new_start_time or not new_end_time:
                return "新しい時間情報が不足しています。もう一度やり直してください。"
            skip_overlap = pending_event.get('force_update') or pending_event.get('skip_overlap_check') or False
            logger.info(f"[handle_yes_response] skip_overlap={skip_overlap}, pending_event={pending_event}")
            result = await calendar_manager.update_event_by_id(
                event_id=event_id,
                new_start_time=new_start_time,
                new_end_time=new_end_time
            )
            clear_pending_event(calendar_id)
            if not result.get('success', False):
                logger.error(f"[update_event_by_id][error] {result}")
                return result.get('error', 'うまくできなかったみたい。ごめんね。')
            # 予定を更新した日の予定一覧も返す
            day = new_start_time.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
            events = await calendar_manager.get_events(start_time=day, end_time=day_end)
            msg = f"予定を更新しました！\n\n" + format_event_list(events, day, day_end)
            return msg
        else:
            return "操作タイプを特定できませんでした。もう一度お試しください。"

    except Exception as e:
        logger.error(f"Error in handle_yes_response: {str(e)}")
        logger.error(traceback.format_exc())
        return f"エラーが発生しました: {str(e)}\n\n詳細: 予定の処理中にエラーが発生しました。"

def get_user_credentials(user_id: str) -> Optional[google.oauth2.credentials.Credentials]:
    """
    ユーザーの認証情報を取得する
    
    Args:
        user_id (str): ユーザーID
        
    Returns:
        Optional[google.oauth2.credentials.Credentials]: 認証情報。存在しない場合はNone
    """
    try:
        # データベースから認証情報を取得
        credentials_dict = db_manager.get_user_credentials(user_id)
        if not credentials_dict:
            logger.warning(f"認証情報が見つかりません: user_id={user_id}")
            return None
            
        # 認証情報をCredentialsオブジェクトに変換
        credentials = google.oauth2.credentials.Credentials(
            token=credentials_dict.get('token'),
            refresh_token=credentials_dict.get('refresh_token'),
            token_uri=credentials_dict.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=credentials_dict.get('client_id'),
            client_secret=credentials_dict.get('client_secret'),
            scopes=credentials_dict.get('scopes', SCOPES)
        )
        
        # 有効期限の設定
        if credentials_dict.get('expires_at'):
            credentials.expiry = datetime.fromtimestamp(credentials_dict['expires_at'], tz=timezone.utc)
            logger.info(f"credentials.expiry(set): {credentials.expiry}, type={type(credentials.expiry)}, tzinfo={credentials.expiry.tzinfo}")
            if credentials.expiry.tzinfo is None:
                credentials.expiry = credentials.expiry.replace(tzinfo=timezone.utc)
                logger.info(f"credentials.expiry(replaced): {credentials.expiry}, type={type(credentials.expiry)}, tzinfo={credentials.expiry.tzinfo}")
            logger.info(f"credentials.expiry={credentials.expiry}, now={datetime.now(timezone.utc)}")
        # 比較用に一時変数expiryを使う
        expiry = credentials.expiry if hasattr(credentials, 'expiry') else None
        if expiry and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        # 1時間以内にトークンが切れるかどうかチェック
        if (expiry and (expiry - datetime.now(timezone.utc)).total_seconds() < 3600) or credentials.expired:
            try:
                # リフレッシュトークンが存在するか確認
                if not credentials.refresh_token:
                    logger.error(f"リフレッシュトークンが存在しません: user_id={user_id}")
                    db_manager.delete_google_credentials(user_id)
                    return None

                # トークンのリフレッシュを試行
                credentials.refresh(google.auth.transport.requests.Request())
                
                # リフレッシュした認証情報を保存
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
            except google.auth.exceptions.RefreshError as e:
                error_message = str(e)
                logger.error(f"トークンのリフレッシュに失敗: {error_message}")
                
                # エラーの種類に応じて処理を分岐
                if "invalid_grant" in error_message.lower():
                    logger.info(f"認証情報を削除して再認証を促します: user_id={user_id}")
                    db_manager.delete_google_credentials(user_id)
                    return None
                elif "invalid_client" in error_message.lower():
                    logger.error(f"クライアント認証情報が無効です: user_id={user_id}")
                    return None
                else:
                    logger.error(f"予期せぬリフレッシュエラー: {error_message}")
                    return None
            except Exception as e:
                logger.error(f"トークンのリフレッシュ中に予期せぬエラーが発生: {str(e)}")
                logger.error(traceback.format_exc())
                return None
            
        return credentials
        
    except Exception as e:
        logger.error(f"認証情報の取得に失敗: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def get_auth_url(user_id: str) -> str:
    """
    認証URLを生成する
    
    Args:
        user_id (str): ユーザーID
        
    Returns:
        str: 認証URL
    """
    try:
        # 既存の認証情報を削除
        db_manager.delete_google_credentials(user_id)
        
        # セッションの初期化
        session.clear()
        session['line_user_id'] = user_id
        session['auth_start_time'] = time.time()
        session['last_activity'] = time.time()
        session['auth_state'] = 'started'
        session.permanent = True
        
        # セッションの保存を確実に行う
        session.modified = True
        
        flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            scopes=SCOPES
        )
        flow.redirect_uri = url_for('oauth2callback', _external=True)
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        # セッションにstateを保存
        session['state'] = state
        session.modified = True
        
        logger.info(f"認証URLを生成: user_id={user_id}, state={state}")
        
        return authorization_url
    except Exception as e:
        logger.error(f"認証URLの生成中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        return ""

# アプリケーション起動時の設定
def setup_app():
    """
    アプリケーションの初期設定を行う
    """
    try:
        # 環境変数の検証
        validate_environment()
        
        # ログ設定
        setup_logging()
        
        # セッションの初期化
        init_session()
        
        # タイムゾーンの設定確認
        if not JST:
            logger.error("Failed to set timezone to Asia/Tokyo")
            raise ValueError("Failed to set timezone to Asia/Tokyo")
        
        if not os.path.exists("client_secret.json"):
            logger.error("client_secret.jsonが存在しません。GOOGLE_CLIENT_SECRETの環境変数を確認してください。")
        else:
            logger.info("client_secret.jsonの存在を確認しました。")
        
        logger.info("Application setup completed successfully")
        
    except Exception as e:
        logger.error(f"Application setup failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise

@app.route('/test_redis')
def test_redis():
    try:
        # セッション書き込みテスト
        with app.test_request_context():
            session['redis_test'] = 'ok'
            session.modified = True
            logger.info(f"[Redisセッションテスト] session['redis_test'] = {session.get('redis_test')}")
        return 'Redisセッションテスト: ' + str(session.get('redis_test'))
    except Exception as e:
        logger.error(f"[Redisセッションテスト] エラー: {str(e)}")
        return 'エラー: ' + str(e), 500

@app.route('/')
def index():
    return 'LINEカレンダーアプリのサーバーが正常に動作しています。'

@app.errorhandler(404)
def not_found_error(error):
    logger.error(f"404 Not Found: {request.url}")
    return jsonify({
        "error": "Not Found",
        "message": "リクエストされたURLが見つかりませんでした。",
        "status_code": 404
    }), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 Internal Server Error: {str(error)}")
    return jsonify({
        "error": "Internal Server Error",
        "message": "サーバーでエラーが発生しました。",
        "status_code": 500
    }), 500

@app.errorhandler(Exception)
def handle_exception(error):
    logger.error(f"Unhandled Exception: {str(error)}")
    logger.error(f"Request Headers: {dict(request.headers)}")
    logger.error(f"Request Data: {request.get_data()}")
    logger.error(f"Traceback: {traceback.format_exc()}")
    return jsonify({
        "error": "Internal Server Error",
        "message": "サーバーでエラーが発生しました。",
        "status_code": 500
    }), 500

# ワンタイムコードの保存用（Redisに変更）
# one_time_codes = {}
ONE_TIME_CODE_TTL = 600  # 10分

def generate_one_time_code(length=6):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
    logger.debug(f"[one_time_code][generate] code={code}")
    return code

def save_one_time_code(code, user_id):
    try:
        redis_client.setex(f"one_time_code:{code}", ONE_TIME_CODE_TTL, user_id)
        logger.debug(f"[one_time_code][redis][save] code={code}, user_id={user_id}")
        print(f"[one_time_code][redis][save] code={code}, user_id={user_id}")
        try:
            val = redis_client.get(f"one_time_code:{code}")
            logger.debug(f"[one_time_code][redis][check-val] code={code}, value={val}")
            print(f"[one_time_code][redis][check-val] code={code}, value={val}")
        except Exception as e:
            logger.error(f"[one_time_code][redis][check-val][error] code={code}, error={e}", exc_info=True)
            print(f"[one_time_code][redis][check-val][error] code={code}, error={e}")
        try:
            ttl = redis_client.ttl(f"one_time_code:{code}")
            logger.debug(f"[one_time_code][redis][check-ttl] code={code}, ttl={ttl}")
            print(f"[one_time_code][redis][check-ttl] code={code}, ttl={ttl}")
        except Exception as e:
            logger.error(f"[one_time_code][redis][check-ttl][error] code={code}, error={e}", exc_info=True)
            print(f"[one_time_code][redis][check-ttl][error] code={code}, error={e}")
    except Exception as e:
        logger.error(f"[one_time_code][redis][save][error] code={code}, user_id={user_id}, error={e}", exc_info=True)
        print(f"[one_time_code][redis][save][error] code={code}, user_id={user_id}, error={e}")

def get_one_time_code_user(code):
    user_id = redis_client.get(f"one_time_code:{code}")
    if user_id:
        return user_id.decode()
    return None

def delete_one_time_code(code):
    redis_client.delete(f"one_time_code:{code}")
    logger.debug(f"[one_time_code][redis][delete] code={code}")

# ワンタイムコード入力ページ
@app.route('/onetimelogin', methods=['GET', 'POST'])
def onetimelogin():
    if request.method == 'POST':
        code = request.form.get('code')
        logger.debug(f"[onetimelogin][input] code={code}")
        print(f"[onetimelogin][input] code={code}")
        # Redisから取得
        user_id = None
        try:
            user_id = redis_client.get(f"one_time_code:{code}")
            logger.debug(f"[onetimelogin][redis][get] code={code}, user_id={user_id}")
            print(f"[onetimelogin][redis][get] code={code}, user_id={user_id}")
        except Exception as e:
            logger.error(f"[onetimelogin][redis][get][error] code={code}, error={e}", exc_info=True)
            print(f"[onetimelogin][redis][get][error] code={code}, error={e}")
        # Redis内の全one_time_code:*キーと値を出力
        try:
            keys = list(redis_client.scan_iter('one_time_code:*'))
            logger.debug(f"[onetimelogin][redis][all_keys] {keys}")
            print(f"[onetimelogin][redis][all_keys] {keys}")
            for key in keys:
                val = redis_client.get(key)
                logger.debug(f"[onetimelogin][redis][key] {key} => {val}")
                print(f"[onetimelogin][redis][key] {key} => {val}")
        except Exception as e:
            logger.error(f"[onetimelogin][redis][log_all][error] {e}", exc_info=True)
            print(f"[onetimelogin][redis][log_all][error] {e}")
        if user_id:
            session.clear()
            session['line_user_id'] = user_id
            session['auth_start_time'] = time.time()
            session['last_activity'] = time.time()
            session['auth_state'] = 'started'
            session.permanent = True
            session.modified = True
            delete_one_time_code(code)
            logger.debug(f"[one_time_code][delete] code={code}")
            flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
                CLIENT_SECRETS_FILE,
                scopes=SCOPES
            )
            flow.redirect_uri = url_for('oauth2callback', _external=True)
            authorization_url, state = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                prompt='consent'
            )
            session['state'] = state
            return redirect(authorization_url)
        else:
            error = 'ワンタイムコードが無効か、期限切れです。LINEで新しいコードを取得してください。'
            logger.debug(f"[one_time_code][invalid] code={code}")
            return render_template_string(ONETIME_LOGIN_HTML, error=error)
    return render_template_string(ONETIME_LOGIN_HTML, error=None)

ONETIME_LOGIN_HTML = '''
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Google認証 - LINEカレンダー</title>
    <link rel="icon" type="image/x-icon" href="/static/favicon.ico">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
            color: #333;
        }
        .container {
            max-width: 600px;
            margin: 40px auto;
            padding: 20px;
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h2 {
            color: #06C755;
            margin-top: 0;
            text-align: center;
        }
        .error {
            color: #dc3545;
            background-color: #f8d7da;
            border: 1px solid #f5c6cb;
            padding: 10px;
            border-radius: 4px;
            margin-bottom: 20px;
        }
        form {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }
        label {
            font-weight: bold;
        }
        input[type="text"] {
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 16px;
        }
        button {
            background-color: #06C755;
            color: white;
            border: none;
            padding: 12px 20px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
            font-weight: bold;
            transition: background-color 0.2s;
        }
        button:hover {
            background-color: #05a548;
        }
        .instructions {
            background-color: #e9f7ef;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h2>Google認証用ワンタイムコード入力</h2>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        <div class="instructions">
            <p>LINEで受け取ったワンタイムコードを入力してください。</p>
            <p>※コードは一度きり使用可能です。期限切れの場合は、LINEで新しいコードを取得してください。</p>
        </div>
        <form method="post">
            <label for="code">ワンタイムコード:</label>
            <input type="text" id="code" name="code" required placeholder="例: ABC123">
            <button type="submit">認証を開始</button>
        </form>
    </div>
</body>
</html>
'''

stripe_manager = StripeManager()

@app.route('/payment/checkout', methods=['GET', 'POST'])
def create_checkout_session():
    try:
        if request.method == 'POST':
            data = request.get_json()
            user_id = data.get('user_id')
            line_user_id = data.get('line_user_id')
        else:
            user_id = request.args.get('user_id')
            line_user_id = request.args.get('line_user_id', user_id)
        session = stripe_manager.create_checkout_session(user_id, line_user_id)
        return redirect(session.url)
    except Exception as e:
        current_app.logger.error(f"Checkout session creation failed: {str(e)}")
        return jsonify({'error': str(e)}), 400

@app.route('/payment/success')
def payment_success():
    session_id = request.args.get('session_id')
    return render_template('payment_success.html', session_id=session_id)

@app.route('/payment/cancel')
def payment_cancel():
    return render_template('payment_cancel.html')

# LINE Messaging APIの処理を修正
async def handle_line_message(event):
    try:
        user_id = event.source.user_id
        message_text = event.message.text
        reply_token = event.reply_token
        # ユーザーのサブスクリプション状態を確認
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
        # 既存のメッセージ処理ロジック
        pass
    except Exception as e:
        logger.error(f"handle_line_message error: {str(e)}")
        return {'type': 'text', 'text': 'エラーが発生しました。'}

async def reply_flex(reply_token, flex_content):
    try:
        logger.info(f"[reply_flex] 送信直前のflex_content: {flex_content}")
        message = FlexMessage(alt_text=flex_content["altText"], contents=flex_content["contents"])
        async with async_timeout(TIMEOUT_SECONDS):
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[message]
                )
            )
        logger.info(f"[reply_flex] Flex Message送信成功: {flex_content}")
    except Exception as e:
        logger.error(f"[reply_flex] Flex Message送信エラー: {str(e)}")
        logger.error(traceback.format_exc())

def get_db_connection():
    """データベース接続を取得する"""
    try:
        conn = sqlite3.connect('instance/calendar.db')
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.error(f"データベース接続エラー: {str(e)}")
        logger.error(traceback.format_exc())
        raise

def ensure_db_columns():
    """必要なデータベースカラムが存在することを確認する"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # usersテーブルのカラムを確認
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                subscription_status TEXT DEFAULT 'inactive',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # google_credentialsテーブルのカラムを確認
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS google_credentials (
                user_id TEXT PRIMARY KEY,
                credentials TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        # pending_eventsテーブルのカラムを確認
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_events (
                user_id TEXT PRIMARY KEY,
                event_info TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        conn.commit()
        logger.info("データベースのカラム確認が完了しました")
    except Exception as e:
        logger.error(f"データベースのカラム確認中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        raise
    finally:
        if conn:
            conn.close()

@app.route('/test_redis_write')
def test_redis_write():
    try:
        # テスト用のデータを書き込む
        test_key = 'test_key'
        test_value = 'test_value'
        redis_client.setex(test_key, 60, test_value)  # 60秒のTTL
        
        # 書き込みの確認
        stored_value = redis_client.get(test_key)
        if stored_value and stored_value.decode() == test_value:
            logger.info(f"[Redis書き込みテスト] 成功: {test_key}={test_value}")
            return jsonify({
                'status': 'success',
                'message': 'Redis書き込みテスト成功',
                'data': {
                    'key': test_key,
                    'value': test_value,
                    'ttl': redis_client.ttl(test_key)
                }
            })
        else:
            logger.error(f"[Redis書き込みテスト] 失敗: 値の不一致")
            return jsonify({
                'status': 'error',
                'message': 'Redis書き込みテスト失敗: 値の不一致'
            }), 500
    except Exception as e:
        logger.error(f"[Redis書き込みテスト] エラー: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Redis書き込みテストエラー: {str(e)}'
        }), 500

@line_handler.add(FollowEvent)
def handle_follow(event):
    # フォローイベントの処理
    pass

@line_handler.add(UnfollowEvent)
def handle_unfollow(event):
    # アンフォローイベントの処理
    pass

@line_handler.add(JoinEvent)
def handle_join(event):
    # グループ参加イベントの処理
    pass

@line_handler.add(LeaveEvent)
def handle_leave(event):
    # グループ退出イベントの処理
    pass

@line_handler.add(PostbackEvent)
def handle_postback(event):
    # ポストバックイベントの処理
    pass

async def handle_parsed_message(result, user_id, reply_token):
    """
    解析されたメッセージを処理する
    
    Args:
        result: 解析結果
        user_id: ユーザーID
        reply_token: リプライトークン
    """
    try:
        # カレンダーマネージャーの初期化
        calendar_manager = get_calendar_manager(user_id)
        
        # 操作タイプに応じた処理
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

async def handle_add_event(result, calendar_manager, user_id, reply_token):
    """予定の追加を処理する"""
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
            await reply_text(reply_token, f"予定の追加に失敗しました: {add_result.get('message', '不明なエラー')}")
    except Exception as e:
        logger.error(f"予定の追加中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        await reply_text(reply_token, "予定の追加中にエラーが発生しました。\nしばらく時間をおいて再度お試しください。")

async def handle_read_event(result, calendar_manager, user_id, reply_token):
    """予定の確認を処理する"""
    try:
        if not all(k in result for k in ['start_time', 'end_time']):
            await reply_text(reply_token, "予定の確認に必要な情報が不足しています。\n確認したい日付を指定してください。")
            return

        events = await calendar_manager.get_events(
            start_time=result['start_time'],
            end_time=result['end_time'],
            title=result.get('title')
        )
        
        message = format_event_list(events, result['start_time'], result['end_time'])
        user_last_event_list[user_id] = {
            'events': events,
            'start_time': result['start_time'],
            'end_time': result['end_time']
        }
        await reply_text(reply_token, message)
    except Exception as e:
        logger.error(f"予定の確認中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        await reply_text(reply_token, "予定の確認中にエラーが発生しました。\nしばらく時間をおいて再度お試しください。")

async def handle_delete_event(result, calendar_manager, user_id, reply_token):
    """予定の削除を処理する"""
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
            if events:
                msg += f"\n\n残りの予定：\n" + format_event_list(events, day, day_end)
            else:
                msg += "\n\nこの日の予定は全て削除されました。"
            await reply_text(reply_token, msg)
        else:
            await reply_text(reply_token, f"予定の削除に失敗しました: {delete_result.get('message', '不明なエラー')}")
    except Exception as e:
        logger.error(f"予定の削除中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        await reply_text(reply_token, "予定の削除中にエラーが発生しました。\nしばらく時間をおいて再度お試しください。")

async def handle_update_event(result, calendar_manager, user_id, reply_token):
    """予定の更新を処理する"""
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

if __name__ == "__main__":
    try:
        # アプリケーションの初期設定
        setup_app()
        
        # ポート番号の設定
        port_str = os.getenv("PORT")
        port = int(port_str) if port_str and port_str.isdigit() else 3001
        
        logger.info(f"Starting server on port {port}")
        app.run(host="0.0.0.0", port=port, use_reloader=False)
        
    except Exception as e:
        logger.error(f"Failed to start application: {str(e)}")
        logger.error(traceback.format_exc())
        sys.exit(1) 

import os
print('STRIPE_WEBHOOK_SECRET:', os.getenv('STRIPE_WEBHOOK_SECRET'))

REDIS_URL = os.getenv("REDIS_URL")
print("REDIS_URL at startup:", REDIS_URL)
if not REDIS_URL or not REDIS_URL.startswith("redis://"):
    raise ValueError("REDIS_URL is missing or invalid.")