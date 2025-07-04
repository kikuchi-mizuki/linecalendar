"""
GPT補助機能の設定ファイル

このファイルは、GPT補助機能の設定を管理します。
"""

import os
from typing import Optional

class GPTConfig:
    """GPT補助機能の設定クラス"""
    
    # OpenAI API設定
    OPENAI_API_KEY: Optional[str] = os.getenv('OPENAI_API_KEY')
    OPENAI_MODEL: str = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
    
    # GPT補助機能の有効/無効
    GPT_ASSISTANT_ENABLED: bool = os.getenv('GPT_ASSISTANT_ENABLED', 'true').lower() == 'true'
    
    # 確信度の閾値（この値以上の場合のみGPT結果を使用）
    GPT_CONFIDENCE_THRESHOLD: float = float(os.getenv('GPT_CONFIDENCE_THRESHOLD', '0.7'))
    
    # API呼び出しのタイムアウト（秒）
    GPT_API_TIMEOUT: int = int(os.getenv('GPT_API_TIMEOUT', '10'))
    
    # 最大トークン数
    GPT_MAX_TOKENS: int = int(os.getenv('GPT_MAX_TOKENS', '500'))
    
    # 温度設定（0.0-1.0、低いほど一貫性が高い）
    GPT_TEMPERATURE: float = float(os.getenv('GPT_TEMPERATURE', '0.1'))
    
    # デバッグモード
    GPT_DEBUG_MODE: bool = os.getenv('GPT_DEBUG_MODE', 'false').lower() == 'true'
    
    @classmethod
    def is_configured(cls) -> bool:
        """GPT補助機能が正しく設定されているかチェック"""
        return bool(cls.OPENAI_API_KEY and cls.GPT_ASSISTANT_ENABLED)
    
    @classmethod
    def get_config_summary(cls) -> dict:
        """設定の概要を取得"""
        return {
            'enabled': cls.GPT_ASSISTANT_ENABLED,
            'configured': cls.is_configured(),
            'model': cls.OPENAI_MODEL,
            'confidence_threshold': cls.GPT_CONFIDENCE_THRESHOLD,
            'timeout': cls.GPT_API_TIMEOUT,
            'max_tokens': cls.GPT_MAX_TOKENS,
            'temperature': cls.GPT_TEMPERATURE,
            'debug_mode': cls.GPT_DEBUG_MODE
        } 