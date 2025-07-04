#!/usr/bin/env python3
"""
GPT補助機能のハイブリッド方式テストスクリプト

このスクリプトは、既存のルールベース抽出とGPT補助機能の組み合わせをテストします。
"""

import os
import sys
from datetime import datetime
import pytz

# プロジェクトのルートディレクトリをパスに追加
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.message_parser import extract_datetime_from_message
from utils.gpt_assistant import gpt_assistant

def test_hybrid_datetime_extraction():
    """ハイブリッド方式の日時抽出をテストする"""
    
    print("=== GPT補助機能ハイブリッド方式テスト ===\n")
    
    # GPT補助機能の状態を確認
    status = gpt_assistant.get_status()
    print(f"GPT補助機能状態: {status}\n")
    
    # テストケース
    test_cases = [
        # ルールベースで抽出できるケース
        {
            'message': '6/23 14:00 会議',
            'description': 'ルールベースで抽出できる標準的なケース'
        },
        {
            'message': '6/23と6/27の予定を教えて',
            'description': '複数日指定（ルールベース対応）'
        },
        {
            'message': '今日の予定',
            'description': '相対日付（ルールベース対応）'
        },
        
        # GPT補助が必要なケース
        {
            'message': '来週の水曜日の午後3時から会議',
            'description': '複雑な相対日付と時刻（GPT補助が必要）'
        },
        {
            'message': '3日後の夕方6時頃に打ち合わせ',
            'description': '曖昧な時刻表現（GPT補助が必要）'
        },
        {
            'message': '今度の土曜日の朝9時から12時まで',
            'description': '時間範囲指定（GPT補助が必要）'
        },
        {
            'message': '来月の第1金曜日の夜7時から',
            'description': '複雑な日付指定（GPT補助が必要）'
        },
        
        # 抽出できないケース
        {
            'message': 'こんにちは',
            'description': '日時情報なし'
        },
        {
            'message': '予定を確認したい',
            'description': '日時情報なし'
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"テストケース {i}: {test_case['description']}")
        print(f"メッセージ: {test_case['message']}")
        
        # 日時抽出を実行
        result = extract_datetime_from_message(test_case['message'])
        
        print(f"抽出結果:")
        print(f"  - 抽出方法: {result.get('extraction_method', 'unknown')}")
        
        if result.get('start_time'):
            print(f"  - 開始時刻: {result['start_time']}")
        if result.get('end_time'):
            print(f"  - 終了時刻: {result['end_time']}")
        if result.get('dates'):
            print(f"  - 複数日: {[d.strftime('%Y-%m-%d') for d in result['dates']]}")
        if result.get('is_multiple_days'):
            print(f"  - 複数日フラグ: {result['is_multiple_days']}")
        if result.get('is_time_range'):
            print(f"  - 時間範囲フラグ: {result['is_time_range']}")
        if result.get('gpt_confidence'):
            print(f"  - GPT確信度: {result['gpt_confidence']:.2f}")
        
        print()

def test_gpt_only():
    """GPT補助機能のみをテストする"""
    
    print("=== GPT補助機能単体テスト ===\n")
    
    # GPT補助機能の状態を確認
    if not gpt_assistant.enabled:
        print("GPT補助機能が無効です。テストをスキップします。")
        return
    
    test_cases = [
        '来週の水曜日の午後3時から会議',
        '3日後の夕方6時頃に打ち合わせ',
        '今度の土曜日の朝9時から12時まで',
        '来月の第1金曜日の夜7時から',
        '明日の朝8時半から10時までミーティング',
        '今週末の土曜日と日曜日の両方でイベント'
    ]
    
    for i, message in enumerate(test_cases, 1):
        print(f"GPTテスト {i}: {message}")
        
        # GPT補助で抽出
        result = gpt_assistant.extract_datetime_with_gpt(message)
        
        if result:
            print(f"  成功: {result}")
        else:
            print(f"  失敗: 抽出できませんでした")
        print()

def main():
    """メイン関数"""
    
    # 環境変数の設定確認
    if not os.getenv('OPENAI_API_KEY'):
        print("警告: OPENAI_API_KEYが設定されていません。")
        print("GPT補助機能は無効になりますが、ルールベース抽出は動作します。\n")
    
    # ハイブリッド方式のテスト
    test_hybrid_datetime_extraction()
    
    # GPT補助機能単体のテスト
    test_gpt_only()
    
    print("=== テスト完了 ===")

if __name__ == "__main__":
    main() 