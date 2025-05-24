import stripe
from flask import current_app
from database import get_db_connection
import os

class StripeManager:
    def __init__(self):
        self.stripe = stripe
        self.stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        self.price_id = os.getenv('STRIPE_PRICE_ID')  # 月額プランの価格ID

    def create_checkout_session(self, user_id, line_user_id):
        """チェックアウトセッションを作成"""
        try:
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

    def handle_webhook(self, payload, sig_header):
        """StripeのWebhookを処理"""
        try:
            event = self.stripe.Webhook.construct_event(
                payload, sig_header, os.getenv('STRIPE_WEBHOOK_SECRET')
            )
            
            if event['type'] == 'checkout.session.completed':
                session = event['data']['object']
                self._handle_successful_payment(session)
            elif event['type'] == 'customer.subscription.deleted':
                subscription = event['data']['object']
                self._handle_subscription_cancelled(subscription)
            
            return True
        except Exception as e:
            current_app.logger.error(f"Stripe webhook handling failed: {str(e)}")
            return False

    def _handle_successful_payment(self, session):
        """支払い成功時の処理"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # ユーザーのサブスクリプション状態を更新
            cursor.execute('''
                UPDATE users 
                SET subscription_status = 'active',
                    stripe_customer_id = ?,
                    subscription_start_date = CURRENT_TIMESTAMP
                WHERE user_id = ?
            ''', (session.customer, session.metadata.line_user_id))
            
            conn.commit()
            conn.close()
        except Exception as e:
            current_app.logger.error(f"Failed to update user subscription: {str(e)}")
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