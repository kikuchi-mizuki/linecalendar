"""
GPT補助機能モジュール

このモジュールは、OpenAI GPT APIを使用して日時抽出の精度を向上させる機能を提供します。
既存のルールベース抽出で対応できない場合のフォールバックとして使用します。
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any
import pytz
import traceback
import re

# 設定ファイルをインポート
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.gpt_config import GPTConfig

# ロガーの設定
logger = logging.getLogger(__name__)

# タイムゾーン設定
JST = pytz.timezone('Asia/Tokyo')

class GPTDateTimeAssistant:
    """GPTを使用した日時抽出補助クラス"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = None):
        """
        初期化
        
        Args:
            api_key: OpenAI APIキー（Noneの場合は設定ファイルから取得）
            model: 使用するGPTモデル名（Noneの場合は設定ファイルから取得）
        """
        self.api_key = api_key or GPTConfig.OPENAI_API_KEY
        self.model = model or GPTConfig.OPENAI_MODEL
        self.enabled = GPTConfig.GPT_ASSISTANT_ENABLED and bool(self.api_key)
        
        if not self.enabled:
            if not GPTConfig.GPT_ASSISTANT_ENABLED:
                logger.info("GPT補助機能が無効に設定されています。")
            elif not self.api_key:
                logger.warning("OpenAI APIキーが設定されていません。GPT補助機能は無効です。")
        else:
            logger.info(f"GPT補助機能が有効です。モデル: {self.model}")
    
    def extract_datetime_with_gpt(self, message: str, current_time: datetime = None) -> Optional[Dict]:
        """
        GPTを使用して日時情報を抽出する
        
        Args:
            message: 解析対象のメッセージ
            current_time: 現在時刻（Noneの場合は現在時刻を使用）
            
        Returns:
            抽出された日時情報の辞書、またはNone
        """
        if not self.enabled:
            return None
            
        try:
            current_time = current_time or datetime.now(JST)
            
            # GPTに送信するプロンプトを作成
            prompt = self._create_datetime_extraction_prompt(message, current_time)
            
            # GPT APIを呼び出し
            response = self._call_gpt_api(prompt)
            
            if response:
                # レスポンスをパース
                parsed_result = self._parse_gpt_response(response, current_time)
                if parsed_result:
                    # 確信度チェック
                    confidence = parsed_result.get('gpt_confidence', 0.0)
                    if confidence >= GPTConfig.GPT_CONFIDENCE_THRESHOLD:
                        logger.info(f"GPT補助で日時抽出成功 (確信度: {confidence:.2f}): {parsed_result}")
                        return parsed_result
                    else:
                        logger.warning(f"GPT補助の確信度が低すぎます (確信度: {confidence:.2f} < 閾値: {GPTConfig.GPT_CONFIDENCE_THRESHOLD})")
                        return None
            
            return None
            
        except Exception as e:
            logger.error(f"GPT補助での日時抽出中にエラーが発生: {str(e)}")
            if GPTConfig.GPT_DEBUG_MODE:
                logger.error(traceback.format_exc())
            return None
    
    def _create_datetime_extraction_prompt(self, message: str, current_time: datetime) -> str:
        """
        GPTに送信するプロンプトを作成する
        
        Args:
            message: 解析対象のメッセージ
            current_time: 現在時刻
            
        Returns:
            プロンプト文字列
        """
        current_date = current_time.strftime("%Y年%m月%d日")
        current_time_str = current_time.strftime("%H:%M")
        
        prompt = f"""
あなたは日本語のメッセージから日時情報を抽出する専門家です。

現在時刻: {current_date} {current_time_str} (JST)

以下のメッセージから日時情報を抽出し、JSON形式で返してください。

メッセージ: {message}

抽出すべき情報:
1. start_date: 開始日（YYYY-MM-DD形式、不明な場合はnull）
2. start_time: 開始時刻（HH:MM形式、不明な場合はnull）
3. end_date: 終了日（YYYY-MM-DD形式、不明な場合はnull）
4. end_time: 終了時刻（HH:MM形式、不明な場合はnull）
5. is_time_range: 時間範囲かどうか（true/false）
6. is_multiple_days: 複数日かどうか（true/false）
7. dates: 複数日の場合は日付リスト（YYYY-MM-DD形式の配列、単一日の場合はnull）
8. confidence: 抽出の確信度（0.0-1.0）

注意事項:
- 相対的な表現（「今日」「明日」「来週」など）は現在時刻を基準に解釈してください
- 時刻が不明な場合はnullを設定してください
- 複数日指定（「6/23と6/27」など）の場合はis_multiple_daysをtrueにし、datesに配列で設定してください
- 時間範囲（「14:00-16:00」など）の場合はis_time_rangeをtrueにしてください
- 確信度は慎重に評価してください（曖昧な場合は低めに設定）

JSON形式でのみ回答してください。説明文は含めないでください。
"""
        return prompt
    
    def _call_gpt_api(self, prompt: str) -> Optional[str]:
        """
        GPT APIを呼び出す
        
        Args:
            prompt: 送信するプロンプト
            
        Returns:
            GPTの応答文字列、またはNone
        """
        try:
            # OpenAI APIの呼び出し
            import openai
            
            # APIキーを設定
            openai.api_key = self.api_key
            
            # API呼び出し
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "あなたは日時抽出の専門家です。指定された形式でJSONを返してください。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=GPTConfig.GPT_TEMPERATURE,
                max_tokens=GPTConfig.GPT_MAX_TOKENS,
                timeout=GPTConfig.GPT_API_TIMEOUT
            )
            
            return response.choices[0].message.content.strip()
            
        except ImportError:
            logger.error("openaiライブラリがインストールされていません。pip install openai でインストールしてください。")
            return None
        except Exception as e:
            logger.error(f"GPT API呼び出し中にエラーが発生: {str(e)}")
            if GPTConfig.GPT_DEBUG_MODE:
                logger.error(traceback.format_exc())
            return None
    
    def _parse_gpt_response(self, response: str, current_time: datetime) -> Optional[Dict]:
        """
        GPTの応答をパースする
        
        Args:
            response: GPTの応答文字列
            current_time: 現在時刻
            
        Returns:
            パースされた日時情報の辞書、またはNone
        """
        try:
            # JSONを抽出（```json```で囲まれている場合がある）
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response
            
            # JSONをパース
            data = json.loads(json_str)
            
            # 結果を構築
            result = {}
            
            # 単一日の場合
            if not data.get('is_multiple_days', False):
                start_date = data.get('start_date')
                start_time = data.get('start_time')
                
                if start_date and start_time:
                    # 日付と時刻を結合
                    datetime_str = f"{start_date}T{start_time}:00+09:00"
                    start_datetime = datetime.fromisoformat(datetime_str)
                    result['start_time'] = start_datetime
                    
                    # 終了時刻の処理
                    end_date = data.get('end_date', start_date)
                    end_time = data.get('end_time')
                    
                    if end_time:
                        end_datetime_str = f"{end_date}T{end_time}:00+09:00"
                        end_datetime = datetime.fromisoformat(end_datetime_str)
                        result['end_time'] = end_datetime
                    else:
                        # 終了時刻が不明な場合は1時間後をデフォルト
                        result['end_time'] = start_datetime + timedelta(hours=1)
                    
                    result['is_time_range'] = data.get('is_time_range', False)
                    result['is_multiple_days'] = False
                    
            # 複数日の場合
            else:
                dates = data.get('dates', [])
                if dates:
                    date_objects = []
                    for date_str in dates:
                        date_obj = datetime.fromisoformat(f"{date_str}T00:00:00+09:00")
                        date_objects.append(date_obj)
                    
                    result['dates'] = date_objects
                    result['is_multiple_days'] = True
                    result['is_time_range'] = False
            
            # 確信度を追加
            result['gpt_confidence'] = data.get('confidence', 0.5)
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"GPT応答のJSONパースに失敗: {str(e)}")
            if GPTConfig.GPT_DEBUG_MODE:
                logger.error(f"応答内容: {response}")
            return None
        except Exception as e:
            logger.error(f"GPT応答のパース中にエラーが発生: {str(e)}")
            if GPTConfig.GPT_DEBUG_MODE:
                logger.error(traceback.format_exc())
            return None
    
    def should_use_gpt(self, message: str, rule_based_result: Dict) -> bool:
        """
        GPT補助を使用すべきかどうかを判定する
        
        Args:
            message: 解析対象のメッセージ
            rule_based_result: ルールベース抽出の結果
            
        Returns:
            GPT補助を使用すべきかどうか
        """
        if not self.enabled:
            return False
        
        # ルールベースで抽出できた場合はGPTは使用しない
        if rule_based_result.get('start_time') or rule_based_result.get('dates'):
            return False
        
        # 以下の場合はGPT補助を使用
        # 1. 日時らしき表現が含まれているが抽出できなかった場合
        datetime_patterns = [
            r'\d{1,2}[\/月]\d{1,2}',
            r'\d{1,2}時',
            r'\d{1,2}:\d{2}',
            r'今日|明日|明後日|来週|今週',
            r'午前|午後|朝|昼|夜|夕方'
        ]
        
        has_datetime_expression = any(re.search(pattern, message) for pattern in datetime_patterns)
        
        if has_datetime_expression:
            logger.info("日時表現が検出されたが抽出できなかったため、GPT補助を使用します")
            return True
        
        return False
    
    def get_status(self) -> Dict:
        """
        GPT補助機能の状態を取得する
        
        Returns:
            状態情報の辞書
        """
        return {
            'enabled': self.enabled,
            'configured': GPTConfig.is_configured(),
            'model': self.model,
            'api_key_set': bool(self.api_key),
            'config': GPTConfig.get_config_summary()
        }

# グローバルインスタンス
gpt_assistant = GPTDateTimeAssistant() 