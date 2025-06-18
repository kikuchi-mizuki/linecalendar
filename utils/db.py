import os
import sqlite3
import logging
from datetime import datetime
import json

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        # データベースファイルのパス設定
        self.db_path = 'calendar_bot.db'
        logger.info(f"Database path: {self.db_path}")
        
        # データベースの初期化
        self._initialize_database()

    def _initialize_database(self):
        """データベースの初期化を行う"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # usersテーブルの作成
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id TEXT PRIMARY KEY,
                        subscription_status TEXT DEFAULT 'inactive',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # google_credentialsテーブルの作成
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
                
                # pending_eventsテーブルの作成
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
                logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Database initialization error: {str(e)}")
            raise

    def get_db_connection(self):
        """データベース接続を取得する"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            logger.error(f"Database connection error: {str(e)}")
            raise

    def get_user_credentials(self, user_id):
        """ユーザーの認証情報を取得する"""
        if isinstance(user_id, bytes):
            user_id = user_id.decode()
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    SELECT token, refresh_token, token_uri, client_id, client_secret, scopes, expires_at
                    FROM google_credentials WHERE user_id = ?
                    ''',
                    (user_id,)
                )
                result = cursor.fetchone()
                if result:
                    scopes = result['scopes']
                    try:
                        scopes = json.loads(scopes)
                    except Exception:
                        pass
                    return {
                        'token': result['token'],
                        'refresh_token': result['refresh_token'],
                        'token_uri': result['token_uri'],
                        'client_id': result['client_id'],
                        'client_secret': result['client_secret'],
                        'scopes': scopes,
                        'expires_at': result['expires_at']
                    }
                return None
        except Exception as e:
            logger.error(f"Error getting user credentials: {str(e)}")
            return None

    def save_google_credentials(self, user_id, credentials):
        """Google認証情報を保存する"""
        if isinstance(user_id, bytes):
            user_id = user_id.decode()
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                scopes = credentials.get('scopes')
                if isinstance(scopes, list):
                    scopes = json.dumps(scopes)
                cursor.execute(
                    '''
                    INSERT OR REPLACE INTO google_credentials
                    (user_id, token, refresh_token, token_uri, client_id, client_secret, scopes, expires_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        user_id,
                        credentials.get('token'),
                        credentials.get('refresh_token'),
                        credentials.get('token_uri'),
                        credentials.get('client_id'),
                        credentials.get('client_secret'),
                        scopes,
                        credentials.get('expires_at'),
                        datetime.now()
                    )
                )
                conn.commit()
                logger.info(f"Google credentials saved for user: {user_id}")
        except Exception as e:
            logger.error(f"Error saving Google credentials: {str(e)}")
            raise

    def delete_google_credentials(self, user_id):
        """Google認証情報を削除する"""
        if isinstance(user_id, bytes):
            user_id = user_id.decode()
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'DELETE FROM google_credentials WHERE user_id = ?',
                    (user_id,)
                )
                conn.commit()
                logger.info(f"Google credentials deleted for user: {user_id}")
        except Exception as e:
            logger.error(f"Error deleting Google credentials: {str(e)}")
            raise

    def save_pending_event(self, user_id, event_info):
        """保留中のイベントを保存する"""
        try:
            logger.info(f"[save_pending_event] user_id={user_id}, event_info={event_info}")
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    INSERT OR REPLACE INTO pending_events (user_id, event_info, updated_at)
                    VALUES (?, ?, ?)
                    ''',
                    (user_id, json.dumps(event_info), datetime.now())
                )
                conn.commit()
                logger.info(f"Pending event saved for user: {user_id}")
        except Exception as e:
            logger.error(f"Error saving pending event: {str(e)}")
            raise

    def get_pending_event(self, user_id: str) -> dict:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT event_info FROM pending_events WHERE user_id = ?', (user_id,))
                result = cursor.fetchone()
                logger.info(f"[get_pending_event] user_id={user_id}, result={result}")
                if not result:
                    return None
                event_info = json.loads(result[0])
                logger.info(f"[get_pending_event] event_info={event_info}")
                return event_info
        except Exception as e:
            logger.error(f"保留中のイベントの取得に失敗: {str(e)}")
            return None

    def clear_pending_event(self, user_id):
        """保留中のイベントをクリアする"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'DELETE FROM pending_events WHERE user_id = ?',
                    (user_id,)
                )
                conn.commit()
                logger.info(f"Pending event cleared for user: {user_id}")
        except Exception as e:
            logger.error(f"Error clearing pending event: {str(e)}")
            raise

# グローバルなデータベースマネージャーインスタンス
db_manager = DatabaseManager()

def get_db_connection():
    db_path = 'calendar_bot.db'
    if not os.path.exists(db_path):
        DatabaseManager()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn 