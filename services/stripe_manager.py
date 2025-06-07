import stripe
from flask import current_app
from database import get_db_connection
import os
from linebot.v3.messaging import PushMessageRequest, TextMessage

class StripeManager:
    def __init__(self):
        self.stripe = stripe
        self.stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        self.price_id = os.getenv('STRIPE_PRICE_ID')  # 月額プランの価格ID

    def create_checkout_session(self, user_id, line_user_id):
        """チェックアウトセッションを作成"""
        try:
            if not user_id or not line_user_id:
                raise ValueError(f"user_idまたはline_user_idが未指定です: user_id={user_id}, line_user_id={line_user_id}")
            checkout_session = self.stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price': self.price_id,
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=f"{os.getenv('BASE_URL')}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{os.getenv('BASE_URL')}/payment/cancel",
                metadata={
                    'user_id': user_id,
                    'line_user_id': line_user_id
                }
            )
            return checkout_session
        except Exception as e:
            current_app.logger.error(f"Stripe checkout session creation failed: {str(e)}")
            raise

    def handle_webhook(self, payload, sig_header, line_bot_api=None):
        """StripeのWebhookを処理"""
        try:
            # usersテーブルがなければ自動作成
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    subscription_status TEXT DEFAULT 'inactive',
                    stripe_customer_id TEXT,
                    subscription_start_date TIMESTAMP,
                    subscription_end_date TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
            conn.close()

            # テスト用: 署名検証バイパス
            skip_signature = os.getenv('SKIP_STRIPE_SIGNATURE', 'false').lower() == 'true'
            event = None
            if skip_signature:
                current_app.logger.warning("[Stripe Webhook] SKIP_STRIPE_SIGNATURE=true: 署名検証をスキップします（開発用）")
                try:
                    import json
                    event = json.loads(payload)
                except Exception as e:
                    current_app.logger.error(f"[Stripe Webhook] JSONパースエラー: {str(e)}")
                    return False
            else:
                try:
                    event = self.stripe.Webhook.construct_event(
                        payload, sig_header, os.getenv('STRIPE_WEBHOOK_SECRET')
                    )
                except stripe.error.SignatureVerificationError as e:
                    current_app.logger.error(f"[Stripe Webhook] 署名検証エラー: {str(e)}")
                    return False
                except ValueError as e:
                    current_app.logger.error(f"[Stripe Webhook] ペイロードパースエラー: {str(e)}")
                    return False
                except Exception as e:
                    current_app.logger.error(f"[Stripe Webhook] その他のエラー: {str(e)}")
                    return False

            current_app.logger.info(f"[Stripe Webhook] event type: {event.get('type')}")
            current_app.logger.info(f"[Stripe Webhook] event data: {event.get('data')}")
            # イベントタイプに応じた処理
            if event.get('type') == 'checkout.session.completed':
                session = event['data']['object']
                current_app.logger.info(f"[Stripe Webhook] checkout.session.completed: customer={getattr(session, 'customer', None)}, metadata={getattr(session, 'metadata', None)}")
                self._handle_successful_payment(session, line_bot_api)
            elif event.get('type') == 'customer.subscription.created':
                subscription = event['data']['object']
                current_app.logger.info(f"[Stripe Webhook] customer.subscription.created: customer={getattr(subscription, 'customer', None)}")
                self._handle_subscription_created(subscription)
            elif event.get('type') == 'customer.subscription.deleted':
                subscription = event['data']['object']
                current_app.logger.info(f"[Stripe Webhook] customer.subscription.deleted: customer={getattr(subscription, 'customer', None)}")
                self._handle_subscription_cancelled(subscription)
            else:
                current_app.logger.info(f"[Stripe Webhook] 未対応のevent type: {event.get('type')}")
            return True
        except Exception as e:
            import traceback
            current_app.logger.error(f"Stripe webhook handling failed: {str(e)}\n{traceback.format_exc()}")
            return False

    def _handle_successful_payment(self, session, line_bot_api=None):
        """支払い成功時の処理"""
        try:
            # sessionはdict型で渡される
            line_user_id = session['metadata'].get('line_user_id') or session['metadata'].get('user_id')
            stripe_customer_id = session.get('customer')
            current_app.logger.info(f"[Stripe Payment] user_id={line_user_id}, customer_id={stripe_customer_id}")
            conn = get_db_connection()
            cursor = conn.cursor()
            # ユーザーがいなければ追加
            cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (line_user_id,))
            # ユーザーのサブスクリプション状態を更新
            cursor.execute('''
                UPDATE users 
                SET subscription_status = 'active',
                    stripe_customer_id = ?,
                    subscription_start_date = CURRENT_TIMESTAMP
                WHERE user_id = ?
            ''', (stripe_customer_id, line_user_id))
            conn.commit()
            conn.close()
            # LINEに決済完了通知をPush
            if line_user_id and line_bot_api:
                try:
                    line_bot_api.push_message(PushMessageRequest(
                        to=line_user_id,
                        messages=[TextMessage(text="決済が完了しました！ご利用ありがとうございます。")]
                    ))
                except Exception as e:
                    current_app.logger.error(f"LINE決済完了Pushに失敗: {str(e)}")
        except Exception as e:
            current_app.logger.error(f"Failed to update user subscription: {str(e)}")
            raise

    def _handle_subscription_created(self, subscription):
        """サブスクリプション作成時の処理"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # ユーザーのサブスクリプション状態を更新
            cursor.execute('''
                UPDATE users 
                SET subscription_status = 'active',
                    subscription_start_date = CURRENT_TIMESTAMP
                WHERE stripe_customer_id = ?
            ''', (subscription.customer,))
            
            conn.commit()
            conn.close()
        except Exception as e:
            current_app.logger.error(f"Failed to update subscription status: {str(e)}")
            raise

    def _handle_subscription_cancelled(self, subscription):
        """サブスクリプション解約時の処理"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # ユーザーのサブスクリプション状態を更新
            cursor.execute('''
                UPDATE users 
                SET subscription_status = 'inactive',
                    subscription_end_date = CURRENT_TIMESTAMP
                WHERE stripe_customer_id = ?
            ''', (subscription.customer,))
            
            conn.commit()
            conn.close()
        except Exception as e:
            current_app.logger.error(f"Failed to update cancelled subscription: {str(e)}")
            raise 