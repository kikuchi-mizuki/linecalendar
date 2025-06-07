import sqlite3
import logging
logger = logging.getLogger('app')

def get_db_connection():
    """データベース接続を取得する"""
    try:
        conn = sqlite3.connect('instance/calendar.db')
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.error(f"データベース接続エラー: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise 