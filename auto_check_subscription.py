import sqlite3
import logging
from datetime import datetime, timezone
import stripe
import os
from dotenv import load_dotenv
import time
import schedule
from linebot.v3.messaging import PushMessageRequest, TextMessage
from app import line_bot_api

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('subscription_check.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 環境変数の読み込み
load_dotenv()
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

def get_db_connection():
    conn = sqlite3.connect('instance/calendar.db')
    conn.row_factory = sqlite3.Row
    return conn

def check_subscription_status(user_id):
    """ユーザーのサブスクリプション状態を確認"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ユーザーの現在の状態を取得
        cursor.execute('''
            SELECT subscription_status, stripe_customer_id, name
            FROM users 
            WHERE user_id = ?
        ''', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            logger.error(f"ユーザーが見つかりません: {user_id}")
            return False
            
        logger.info(f"ユーザー {user['name']} の状態確認: subscription_status={user['subscription_status']}, stripe_customer_id={user['stripe_customer_id']}")
        
        # Stripeの顧客情報を確認
        if user['stripe_customer_id']:
            try:
                customer = stripe.Customer.retrieve(user['stripe_customer_id'])
                subscriptions = stripe.Subscription.list(customer=user['stripe_customer_id'])
                
                # アクティブなサブスクリプションがあるか確認
                active_subscription = any(sub.status == 'active' for sub in subscriptions.data)
                
                if active_subscription and user['subscription_status'] != 'active':
                    # DBの状態を更新
                    cursor.execute('''
                        UPDATE users 
                        SET subscription_status = 'active',
                            subscription_start_date = CURRENT_TIMESTAMP
                        WHERE user_id = ?
                    ''', (user_id,))
                    conn.commit()
                    logger.info(f"サブスクリプション状態を更新しました: {user_id}")
                    
                    # ユーザーに通知
                    try:
                        line_bot_api.push_message(PushMessageRequest(
                            to=user_id,
                            messages=[TextMessage(text="サブスクリプションが有効になりました！")]
                        ))
                    except Exception as e:
                        logger.error(f"LINE通知の送信に失敗: {str(e)}")
                    
                    return True
                elif not active_subscription and user['subscription_status'] == 'active':
                    # サブスクリプションが無効になった場合
                    cursor.execute('''
                        UPDATE users 
                        SET subscription_status = 'inactive',
                            subscription_end_date = CURRENT_TIMESTAMP
                        WHERE user_id = ?
                    ''', (user_id,))
                    conn.commit()
                    logger.info(f"サブスクリプションが無効になりました: {user_id}")
                    
                    # ユーザーに通知
                    try:
                        line_bot_api.push_message(PushMessageRequest(
                            to=user_id,
                            messages=[TextMessage(text="サブスクリプションが無効になりました。更新が必要です。")]
                        ))
                    except Exception as e:
                        logger.error(f"LINE通知の送信に失敗: {str(e)}")
                    
            except stripe.error.StripeError as e:
                logger.error(f"Stripe APIエラー: {str(e)}")
                
        conn.close()
        return False
        
    except Exception as e:
        logger.error(f"エラーが発生しました: {str(e)}")
        return False

def check_all_users():
    """全ユーザーのサブスクリプション状態を確認"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 全ユーザーを取得
        cursor.execute('SELECT user_id FROM users')
        users = cursor.fetchall()
        
        for user in users:
            user_id = user['user_id']
            logger.info(f"ユーザー {user_id} の確認を開始")
            check_subscription_status(user_id)
            
        conn.close()
        logger.info("全てのユーザーの確認が完了しました")
        
    except Exception as e:
        logger.error(f"エラーが発生しました: {str(e)}")

def main():
    """メイン処理"""
    logger.info("サブスクリプションチェックを開始します")
    
    # 毎日午前0時に実行
    schedule.every().day.at("00:00").do(check_all_users)
    
    # 初回実行
    check_all_users()
    
    # スケジュール実行
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main() 