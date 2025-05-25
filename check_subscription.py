import sqlite3
import logging
from datetime import datetime, timezone
import stripe
import os
from dotenv import load_dotenv

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 環境変数の読み込み
load_dotenv()
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

def get_db_connection():
    conn = sqlite3.connect('calendar_bot.db')
    conn.row_factory = sqlite3.Row
    return conn

def check_subscription_status(user_id):
    """ユーザーのサブスクリプション状態を確認"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ユーザーの現在の状態を取得
        cursor.execute('''
            SELECT subscription_status, stripe_customer_id 
            FROM users 
            WHERE user_id = ?
        ''', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            logger.error(f"ユーザーが見つかりません: {user_id}")
            return False
            
        logger.info(f"現在の状態: subscription_status={user['subscription_status']}, stripe_customer_id={user['stripe_customer_id']}")
        
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
                    return True
                    
            except stripe.error.StripeError as e:
                logger.error(f"Stripe APIエラー: {str(e)}")
                
        conn.close()
        return False
        
    except Exception as e:
        logger.error(f"エラーが発生しました: {str(e)}")
        return False

def main():
    """メイン処理"""
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

if __name__ == "__main__":
    main() 