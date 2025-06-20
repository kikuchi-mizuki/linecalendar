import logging
import sys
import os
import re
from logging.handlers import RotatingFileHandler

class SensitiveDataFilter(logging.Filter):
    """機密情報をマスクするフィルター"""
    def __init__(self):
        super().__init__()
        # マスク対象のパターン
        self.patterns = [
            (r'(token["\']?\s*[:=]\s*["\']?)([^"\']+)', r'\1[REDACTED]'),
            (r'(refresh_token["\']?\s*[:=]\s*["\']?)([^"\']+)', r'\1[REDACTED]'),
            (r'(client_secret["\']?\s*[:=]\s*["\']?)([^"\']+)', r'\1[REDACTED]'),
            (r'(client_id["\']?\s*[:=]\s*["\']?)([^"\']+)', r'\1[REDACTED]'),
            (r'(access_token["\']?\s*[:=]\s*["\']?)([^"\']+)', r'\1[REDACTED]'),
            (r'(Authorization["\']?\s*[:=]\s*["\']?)([^"\']+)', r'\1[REDACTED]'),
            (r'(password["\']?\s*[:=]\s*["\']?)([^"\']+)', r'\1[REDACTED]'),
            (r'(secret["\']?\s*[:=]\s*["\']?)([^"\']+)', r'\1[REDACTED]'),
            (r'(key["\']?\s*[:=]\s*["\']?)([^"\']+)', r'\1[REDACTED]'),
        ]

    def filter(self, record):
        if isinstance(record.msg, str):
            for pattern, replacement in self.patterns:
                record.msg = re.sub(pattern, replacement, record.msg)
        return True

# ログ設定
def setup_logging():
    """
    ログ設定を行う
    """
    try:
        # 環境に応じてログレベルを設定
        log_level = os.getenv('LOG_LEVEL', 'DEBUG')
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
            file_handler = RotatingFileHandler(
                'app.log',
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5
            )
            file_handler.setFormatter(logging.Formatter(log_format))
            handlers.append(file_handler)
        
        # 機密情報フィルターの追加
        sensitive_filter = SensitiveDataFilter()
        for handler in handlers:
            handler.addFilter(sensitive_filter)
        
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
        
        logger = logging.getLogger('app')
        logger.info(f"Logging configured with level: {log_level}")
        
        return logger
        
    except Exception as e:
        print(f"Error setting up logging: {str(e)}")
        raise

# グローバルなロガーインスタンス
# logger = setup_logging()  # この行を削除
