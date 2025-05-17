import sqlite3
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
import json

# ログ設定
logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    データベース操作を管理するクラス
    """
    def __init__(self, db_path: str = 'calendar_bot.db'):
        """
        データベースマネージャーの初期化
        
        Args:
            db_path (str): データベースファイルのパス
        """
        self.db_path = db_path
        self._initialize_database()
        
    def _initialize_database(self):
        """
        データベースの初期化
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # ユーザーテーブルの作成
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id TEXT PRIMARY KEY,
                        name TEXT,
                        email TEXT,
                        is_authorized INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # イベント履歴テーブルの作成
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS event_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT,
                        operation_type TEXT,
                        event_id TEXT,
                        event_title TEXT,
                        start_time TIMESTAMP,
                        end_time TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                ''')
                
                # Google認証情報テーブルの作成
                cursor.execute('''
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
                ''')
                
                # pending_eventsテーブルの作成
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS pending_events (
                        user_id TEXT PRIMARY KEY,
                        operation_type TEXT,
                        delete_index INTEGER,
                        title TEXT,
                        start_time TEXT,
                        end_time TEXT,
                        new_start_time TEXT,
                        new_end_time TEXT,
                        location TEXT,
                        description TEXT,
                        recurrence TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # 既存テーブルにカラムがなければ追加
                for col, typ in [
                    ("operation_type", "TEXT"),
                    ("delete_index", "INTEGER"),
                    ("new_start_time", "TEXT"),
                    ("new_end_time", "TEXT")
                ]:
                    try:
                        cursor.execute(f'ALTER TABLE pending_events ADD COLUMN {col} {typ}')
                    except Exception:
                        pass
                
                conn.commit()
                logger.info("データベースを初期化しました。")
                
        except Exception as e:
            logger.error(f"データベースの初期化に失敗: {str(e)}")
            raise
            
    def add_user(self, user_id: str, name: Optional[str] = None, email: Optional[str] = None) -> bool:
        """
        ユーザーを追加
        
        Args:
            user_id (str): ユーザーID
            name (Optional[str]): ユーザー名
            email (Optional[str]): メールアドレス
            
        Returns:
            bool: 成功した場合はTrue
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR IGNORE INTO users (user_id, name, email)
                    VALUES (?, ?, ?)
                ''', (user_id, name, email))
                conn.commit()
                logger.info(f"ユーザーを追加しました: {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"ユーザーの追加に失敗: {str(e)}")
            return False
            
    def authorize_user(self, user_id: str) -> bool:
        """
        ユーザーを認証
        
        Args:
            user_id (str): ユーザーID
            
        Returns:
            bool: 成功した場合はTrue
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users
                    SET is_authorized = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                ''', (user_id,))
                conn.commit()
                logger.info(f"ユーザーを認証しました: {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"ユーザーの認証に失敗: {str(e)}")
            return False
            
    def is_authorized(self, user_id: str) -> bool:
        """
        ユーザーが認証済みかどうかを確認
        
        Args:
            user_id (str): ユーザーID
            
        Returns:
            bool: 認証済みの場合はTrue
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT is_authorized
                    FROM users
                    WHERE user_id = ?
                ''', (user_id,))
                result = cursor.fetchone()
                return bool(result[0]) if result else False
                
        except Exception as e:
            logger.error(f"ユーザーの認証状態の確認に失敗: {str(e)}")
            return False
            
    def add_event_history(
        self,
        user_id: str,
        operation_type: str,
        event_id: str,
        event_title: str,
        start_time: datetime,
        end_time: datetime
    ) -> bool:
        """
        イベント履歴を追加
        
        Args:
            user_id (str): ユーザーID
            operation_type (str): 操作タイプ
            event_id (str): イベントID
            event_title (str): イベントのタイトル
            start_time (datetime): 開始時間
            end_time (datetime): 終了時間
            
        Returns:
            bool: 成功した場合はTrue
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO event_history (
                        user_id, operation_type, event_id,
                        event_title, start_time, end_time
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    user_id, operation_type, event_id,
                    event_title, start_time.isoformat(), end_time.isoformat()
                ))
                conn.commit()
                logger.info(f"イベント履歴を追加しました: {event_id}")
                return True
                
        except Exception as e:
            logger.error(f"イベント履歴の追加に失敗: {str(e)}")
            return False
            
    def get_event_history(
        self,
        user_id: str,
        limit: int = 10,
        offset: int = 0
    ) -> List[Dict]:
        """
        イベント履歴を取得
        
        Args:
            user_id (str): ユーザーID
            limit (int): 取得件数
            offset (int): 開始位置
            
        Returns:
            List[Dict]: イベント履歴のリスト
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT
                        operation_type, event_id, event_title,
                        start_time, end_time, created_at
                    FROM event_history
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                ''', (user_id, limit, offset))
                
                history = []
                for row in cursor.fetchall():
                    def to_aware(dt):
                        if dt is None:
                            return None
                        if dt.tzinfo is None:
                            return dt.replace(tzinfo=timezone.utc)
                        return dt
                    history.append({
                        'operation_type': row[0],
                        'event_id': row[1],
                        'event_title': row[2],
                        'start_time': to_aware(datetime.fromisoformat(row[3])),
                        'end_time': to_aware(datetime.fromisoformat(row[4])),
                        'created_at': to_aware(datetime.fromisoformat(row[5]))
                    })
                    
                return history
                
        except Exception as e:
            logger.error(f"イベント履歴の取得に失敗: {str(e)}")
            return []
            
    def get_user_statistics(self, user_id: str) -> Dict:
        """
        ユーザーの統計情報を取得
        
        Args:
            user_id (str): ユーザーID
            
        Returns:
            Dict: 統計情報
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 操作タイプごとの件数を取得
                cursor.execute('''
                    SELECT operation_type, COUNT(*)
                    FROM event_history
                    WHERE user_id = ?
                    GROUP BY operation_type
                ''', (user_id,))
                
                operation_counts = dict(cursor.fetchall())
                
                # 最近の操作を取得
                cursor.execute('''
                    SELECT operation_type, created_at
                    FROM event_history
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                ''', (user_id,))
                
                last_operation = cursor.fetchone()
                
                return {
                    'operation_counts': operation_counts,
                    'last_operation': {
                        'type': last_operation[0] if last_operation else None,
                        'time': datetime.fromisoformat(last_operation[1]) if last_operation else None
                    }
                }
                
        except Exception as e:
            logger.error(f"ユーザー統計情報の取得に失敗: {str(e)}")
            return {
                'operation_counts': {},
                'last_operation': None
            } 

    def save_google_credentials(self, user_id: str, credentials: dict):
        """Google認証情報を保存"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
                refresh_token = credentials.get('refresh_token')
                if not refresh_token:
                    cursor.execute('SELECT refresh_token FROM google_credentials WHERE user_id = ?', (user_id,))
                    row = cursor.fetchone()
                    if row and row[0]:
                        refresh_token = row[0]
                logger.info(f"[save_google_credentials] user_id={user_id}, token={credentials.get('token')}, refresh_token={refresh_token}, expires_at={credentials.get('expires_at')}")
                # expires_atを必ずUTCタイムゾーン付きで保存
                expires_at = credentials.get('expires_at')
                expires_at_str = None
                if expires_at:
                    if isinstance(expires_at, (int, float)):
                        dt = datetime.fromtimestamp(expires_at, tz=timezone.utc)
                    elif isinstance(expires_at, datetime):
                        dt = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
                    else:
                        dt = datetime.fromisoformat(str(expires_at))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                    expires_at_str = dt.isoformat()
                cursor.execute('''
                    INSERT OR REPLACE INTO google_credentials 
                    (user_id, token, refresh_token, token_uri, client_id, client_secret, scopes, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_id,
                    credentials['token'],
                    refresh_token,
                    credentials['token_uri'],
                    credentials['client_id'],
                    credentials['client_secret'],
                    json.dumps(credentials['scopes']),
                    expires_at_str
                ))
                conn.commit()
                logger.info(f"Google認証情報を保存しました: {user_id}")
        except Exception as e:
            logger.error(f"[save_google_credentials] Google認証情報の保存に失敗: user_id={user_id}, error={str(e)}")
            raise

    def get_google_credentials(self, user_id: str) -> dict:
        """Google認証情報を取得"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT token, refresh_token, token_uri, client_id, client_secret, scopes, expires_at
                    FROM google_credentials
                    WHERE user_id = ?
                ''', (user_id,))
                row = cursor.fetchone()
                logger.info(f"[get_google_credentials] user_id={user_id}, row={row}")
                if row:
                    expires_at = None
                    if row[6]:
                        dt = datetime.fromisoformat(row[6])
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        expires_at = dt.timestamp()
                    result = {
                        'token': row[0],
                        'refresh_token': row[1],
                        'token_uri': row[2],
                        'client_id': row[3],
                        'client_secret': row[4],
                        'scopes': json.loads(row[5]),
                        'expires_at': expires_at
                    }
                    logger.info(f"[get_google_credentials] result for user_id={user_id}: {result}")
                    return result
                logger.warning(f"[get_google_credentials] 認証情報が見つかりません: user_id={user_id}")
                return None
        except Exception as e:
            logger.error(f"[get_google_credentials] Google認証情報の取得に失敗: user_id={user_id}, error={str(e)}")
            return None

    def delete_google_credentials(self, user_id: str):
        """Google認証情報を削除"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM google_credentials WHERE user_id = ?', (user_id,))
                conn.commit()
                logger.info(f"Google認証情報を削除しました: {user_id}")
        except Exception as e:
            logger.error(f"Google認証情報の削除に失敗: {str(e)}")
            raise 

    def save_pending_event(self, user_id: str, event_info: dict) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # 各フィールドがdatetimeの場合のみisoformat()を呼ぶ
                start_time = event_info.get('start_time')
                if isinstance(start_time, datetime):
                    start_time = start_time.isoformat()
                end_time = event_info.get('end_time')
                if isinstance(end_time, datetime):
                    end_time = end_time.isoformat()
                new_start_time = event_info.get('new_start_time')
                if isinstance(new_start_time, datetime):
                    new_start_time = new_start_time.isoformat()
                new_end_time = event_info.get('new_end_time')
                if isinstance(new_end_time, datetime):
                    new_end_time = new_end_time.isoformat()
                # 以下は既存のコード
                cursor.execute('''
                    INSERT OR REPLACE INTO pending_events (
                        user_id, operation_type, delete_index,
                        title, start_time, end_time,
                        new_start_time, new_end_time,
                        location, description, recurrence
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_id,
                    event_info.get('operation_type'),
                    event_info.get('delete_index'),
                    event_info.get('title'),
                    start_time,
                    end_time,
                    new_start_time,
                    new_end_time,
                    event_info.get('location'),
                    event_info.get('description'),
                    event_info.get('recurrence')
                ))
                conn.commit()
                logger.info(f"保留中のイベントを保存しました: {user_id}")
        except Exception as e:
            logger.error(f"保留中のイベントの保存に失敗: {str(e)}")
            raise

    def get_pending_event(self, user_id: str) -> dict:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT operation_type, delete_index,
                           title, start_time, end_time,
                           new_start_time, new_end_time,
                           location, description, recurrence
                    FROM pending_events
                    WHERE user_id = ?
                ''', (user_id,))
                result = cursor.fetchone()
                if not result:
                    return None
                # 各フィールドがdatetime形式の場合のみto_awareで変換
                def to_aware(dt_str):
                    if not dt_str:
                        return None
                    try:
                        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        return dt
                    except ValueError:
                        return dt_str
                return {
                    'operation_type': result[0],
                    'delete_index': result[1],
                    'title': result[2],
                    'start_time': to_aware(result[3]),
                    'end_time': to_aware(result[4]),
                    'new_start_time': to_aware(result[5]),
                    'new_end_time': to_aware(result[6]),
                    'location': result[7],
                    'description': result[8],
                    'recurrence': result[9]
                }
        except Exception as e:
            logger.error(f"保留中のイベントの取得に失敗: {str(e)}")
            return None

    def clear_pending_event(self, user_id: str) -> None:
        logger.debug(f"[pending_event] clear_pending_event: user_id={user_id}")
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM pending_events WHERE user_id = ?', (user_id,))
            conn.commit() 