import os
import sqlite3
import logging
from datetime import datetime
import json

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        # データベースディレクトリの設定
        self.db_dir = os.getenv('DATABASE_DIR', 'instance')
        os.makedirs(self.db_dir, exist_ok=True)
        
        # データベースファイルのパス設定
        self.db_path = os.path.join(self.db_dir, 'calendar.db')
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
                        credentials TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT credentials FROM google_credentials WHERE user_id = ?',
                    (user_id,)
                )
                result = cursor.fetchone()
                if result:
                    return json.loads(result['credentials'])
                return None
        except Exception as e:
            logger.error(f"Error getting user credentials: {str(e)}")
            return None

    def save_google_credentials(self, user_id, credentials):
        """Google認証情報を保存する"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    INSERT OR REPLACE INTO google_credentials (user_id, credentials, updated_at)
                    VALUES (?, ?, ?)
                    ''',
                    (user_id, json.dumps(credentials), datetime.now())
                )
                conn.commit()
                logger.info(f"Google credentials saved for user: {user_id}")
        except Exception as e:
            logger.error(f"Error saving Google credentials: {str(e)}")
            raise

    def delete_google_credentials(self, user_id):
        """Google認証情報を削除する"""
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

    def get_pending_event(self, user_id):
        """保留中のイベントを取得する"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT event_info FROM pending_events WHERE user_id = ?',
                    (user_id,)
                )
                result = cursor.fetchone()
                if result:
                    return json.loads(result['event_info'])
                return None
        except Exception as e:
            logger.error(f"Error getting pending event: {str(e)}")
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
    """データベース接続を取得する（互換性のために残す）"""
    return db_manager.get_db_connection() 