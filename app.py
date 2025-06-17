import os
import sys
import json
import time
import logging
import traceback
import asyncio
import nest_asyncio
import async_timeout
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Union, List, Dict, Optional
import pytz
from flask import Flask, request, jsonify, session, redirect, url_for, render_template, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_session import Session
from werkzeug.middleware.proxy_fix import ProxyFix
import redis
from dotenv import load_dotenv
import google_auth_oauthlib.flow
import google.oauth2.credentials
import google.auth.transport.requests
from google.auth.exceptions import RefreshError
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent, UnfollowEvent, JoinEvent, LeaveEvent, PostbackEvent
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage, PushMessageRequest, FlexMessage
from services.stripe_manager import StripeManager
from handlers.line_handler import line_bp, handle_message
from utils.db import get_db_connection, DatabaseManager
from services.calendar_service import get_calendar_manager
from utils.formatters import format_event_list
from utils.message_parser import extract_datetime_from_message
from urllib.parse import urlparse

logging.basicConfig(level=logging.DEBUG)

print("=== APP STARTED ===")

# 定数
JST = pytz.timezone('Asia/Tokyo')
MAX_RETRIES = 3
RETRY_DELAY = 2  # 秒
TIMEOUT_SECONDS = 30  # タイムアウトを30秒に延長
ONE_TIME_CODE_TTL = 600  # 10分

# 環境変数からclient_secret.jsonを書き出す
client_secret_json = os.getenv("GOOGLE_CLIENT_SECRET")
if client_secret_json:
    with open("client_secret.json", "w") as f:
        f.write(client_secret_json)

# 定数の定義
CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ['https://www.googleapis.com/auth/calendar']

# 環境変数の読み込み
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

# LINE Messaging APIの初期化（1回だけ）
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
if not LINE_CHANNEL_ACCESS_TOKEN:
    raise ValueError("LINE_CHANNEL_ACCESS_TOKEN is not set")
if not LINE_CHANNEL_SECRET:
    raise ValueError("LINE_CHANNEL_SECRET is not set")
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
line_bot_api = MessagingApi(ApiClient(configuration))

# データベースマネージャーの初期化
db_manager = DatabaseManager()

# Flask関連のインポート
from flask import Flask, request, jsonify, session, redirect, url_for, render_template, render_template_string, current_app
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_session import Session
from werkzeug.middleware.proxy_fix import ProxyFix
import redis
from datetime import datetime, timedelta
import asyncio
import nest_asyncio
from typing import Union, List, Dict, Optional
import traceback
import json
import time
import google.oauth2.credentials
import google.auth.transport.requests
from google.auth.exceptions import RefreshError
from services.stripe_manager import StripeManager
from handlers.line_handler import line_bp, handle_message
from utils.db import get_db_connection
from services.calendar_service import get_calendar_manager

# loggerのグローバル定義
logger = logging.getLogger('app')

# ログ設定
def setup_logging():
    """
    ログ設定を行う
    """
    try:
        # ログレベルを必ずDEBUGに固定
        log_level = 'DEBUG'
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
            handlers=handlers,
            stream=sys.stdout
        )
        
        # 特定のライブラリのログレベルを設定
        logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)
        logging.getLogger('urllib3').setLevel(logging.ERROR)
        logging.getLogger('linebot').setLevel(logging.ERROR)
        
        global logger
        logger = logging.getLogger('app')
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

# 予定確認時の一時保存用（ユーザーごと）
user_last_event_list = {}

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
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
line_bot_api = MessagingApi(ApiClient(configuration))

# タイムアウト設定
TIMEOUT_SECONDS = 30  # タイムアウトを30秒に延長

# 非同期処理の設定
nest_asyncio.apply()
loop = asyncio.get_event_loop()

async def send_reply_message(reply_token: str, text: str) -> None:
    """
    LINE Messaging APIを使用してテキストメッセージを送信する
    
    Args:
        reply_token (str): リプライトークン
        text (str): 送信するテキスト
    """
    try:
        if not reply_token:
            logger.warning("reply_tokenがありません。返信できません。")
            return

        if not text:
            logger.error("送信するテキストが空です")
            return

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)]
            )
        )
        logger.info(f"メッセージを送信しました: {text[:100]}...")
    except Exception as e:
        logger.error(f"メッセージの送信中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())

async def reply_text(reply_token: str, texts: Union[str, List[str]]) -> None:
    """
    LINE Messaging APIを使用してテキストメッセージを送信する
    
    Args:
        reply_token (str): リプライトークン
        texts (Union[str, List[str]]): 送信するテキスト（文字列または文字列のリスト）
    """
    try:
        if not reply_token:
            logger.warning("reply_tokenがありません。返信できません。")
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
        logger.debug(f"[get_user_credentials] credentials_dict: {credentials_dict}")
        if not credentials_dict:
            logger.warning(f"認証情報が見つかりません: user_id={user_id}")
            return None
            
        # 認証情報をCredentialsオブジェクトに変換
        scopes = credentials_dict.get('scopes', SCOPES)
        if isinstance(scopes, str):
            try:
                import json
                scopes = json.loads(scopes)
            except Exception:
                scopes = [scopes]
        credentials = google.oauth2.credentials.Credentials(
            token=credentials_dict.get('token'),
            refresh_token=credentials_dict.get('refresh_token'),
            token_uri=credentials_dict.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=credentials_dict.get('client_id'),
            client_secret=credentials_dict.get('client_secret'),
            scopes=scopes
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
    ワンタイムコードを生成し、保存して返す（認証URLは返さない）
    Args:
        user_id (str): ユーザーID
    Returns:
        str: ワンタイムコード
    """
    try:
        # 既存の認証情報を確認
        existing_creds = db_manager.get_user_credentials(user_id)
        if existing_creds:
            logger.info(f"[get_auth_url] 既存の認証情報が見つかりました: user_id={user_id}")
            return None

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

# === ensure_db_columnsの定義をsetup_appより前に移動 ===
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
                token TEXT NOT NULL,
                refresh_token TEXT,
                token_uri TEXT NOT NULL,
                client_id TEXT NOT NULL,
                client_secret TEXT NOT NULL,
                scopes TEXT NOT NULL,
                expires_at TIMESTAMP,
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
        # DBカラムの確認
        ensure_db_columns()
        # タイムゾーンの設定確認
        if not JST:
            logger.error("Failed to set timezone to Asia/Tokyo")
            raise ValueError("Failed to set timezone to Asia/Tokyo")
        if not os.path.exists("client_secret.json"):
            logger.error("client_secret.jsonが存在しません。GOOGLE_CLIENT_SECRETの環境変数を確認してください。")
        else:
            logger.info("client_secret.jsonの存在を確認しました。")
        # --- Stripe Webhook署名検証バイパス用（開発時のみtrueに）---
        if 'SKIP_STRIPE_SIGNATURE' not in os.environ:
            os.environ['SKIP_STRIPE_SIGNATURE'] = 'false'
        logger.info("Application setup completed successfully")
        # REDIS_URLの値を起動時に必ず出力
        print(f"[DEBUG] REDIS_URL={os.getenv('REDIS_URL')}")
        logger.info(f"[DEBUG] REDIS_URL={os.getenv('REDIS_URL')}")

        base_url = os.getenv('BASE_URL', '')
        if base_url:
            parsed_url = urlparse(base_url)
            domain = parsed_url.hostname
            if domain:
                app.config['SESSION_COOKIE_DOMAIN'] = domain if not domain.startswith('.') else domain
                logger.info(f"[SESSION_COOKIE_DOMAIN] Set to: {app.config['SESSION_COOKIE_DOMAIN']}")
    except Exception as e:
        logger.error(f"Application setup failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise

setup_app()
app.register_blueprint(line_bp)

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
            flow.redirect_uri = url_for('line.oauth2callback', _external=True)
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
            return render_template('onetimelogin.html', error=error)
    return render_template('onetimelogin.html', error=None)

stripe_manager = StripeManager()

@app.route('/payment/checkout', methods=['GET', 'POST'])
def create_checkout_session():
    try:
        logger.info(f"[決済リクエスト] method={request.method}, args={dict(request.args)}, data={request.get_json(silent=True)}")
        if request.method == 'POST':
            data = request.get_json()
            user_id = data.get('user_id')
            line_user_id = data.get('line_user_id')
        else:
            user_id = request.args.get('user_id')
            line_user_id = request.args.get('line_user_id', user_id)
        logger.info(f"[決済リクエスト] user_id={user_id}, line_user_id={line_user_id}")
        if not user_id or not line_user_id:
            return jsonify({'error': f'user_idまたはline_user_idが未指定です: user_id={user_id}, line_user_id={line_user_id}'}), 400
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
        logger.info(f"[LINEイベント] event={event}")
        user_id = getattr(event.source, 'user_id', None)
        logger.info(f"[LINEイベント] user_id={user_id}")
        message_text = event.message.text
        reply_token = event.reply_token
        # ユーザーのサブスクリプション状態を確認
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT subscription_status FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        if not user or user['subscription_status'] != 'active':
            base_url = os.getenv("BASE_URL")
            if not base_url:
                logger.error("BASE_URLが未設定です。環境変数を確認してください。")
                await reply_text(reply_token, "システムエラー：BASE_URLが未設定です。管理者にご連絡ください。")
                return
            payment_url = f'{base_url}/payment/checkout?user_id={user_id}&line_user_id={user_id}'
            logger.info(f"[決済案内] user_id={user_id}, url={payment_url}")
            msg = (
                'この機能をご利用いただくには、月額プランへのご登録が必要です。\n'
                f'以下のURLからご登録ください：\n'
                f'{payment_url}'
            )
            await reply_text(reply_token, msg)
            return
        # 既存のメッセージ処理ロジック
        await handle_message(event)
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

@app.route('/callback', methods=['POST'])
def callback():
    logger.info("app.py /callback called")
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

# Stripe webhook routeを他のrouteと一緒に配置
@app.route('/webhook/stripe', methods=['POST'])
def stripe_webhook():
    logger.info("=== Stripe Webhook受信 ===")
    try:
        payload = request.get_data(as_text=True)
        logger.info(f"Stripe Webhook payload: {payload}")
        sig_header = request.headers.get('Stripe-Signature')
        logger.info(f"Stripe Webhook sig_header: {sig_header}")
        
        if not sig_header:
            logger.error("Stripe-Signature header is missing")
            return jsonify({'error': 'Stripe-Signature header is missing'}), 400
            
        result = stripe_manager.handle_webhook(payload, sig_header, line_bot_api)
        logger.info(f"stripe_manager.handle_webhook result: {result}")
        if result:
            return jsonify({'status': 'success'})
        else:
            logger.error("Webhook handling failed (stripe_manager returned False)")
            return jsonify({'error': 'Webhook handling failed'}), 400
            
    except Exception as e:
        logger.error(f"Stripe webhook error: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 400

if __name__ == "__main__":
    try:
        # 開発用ローカル実行（本番ではgunicorn使用）
        port_str = os.getenv("PORT")
        port = int(port_str) if port_str and port_str.isdigit() else 3001
        logger.info(f"Starting server on port {port}")
        app.run(host="0.0.0.0", port=port, use_reloader=False)
    except Exception as e:
        logger.error(f"Failed to start application: {str(e)}")
        logger.error(traceback.format_exc())
        sys.exit(1)