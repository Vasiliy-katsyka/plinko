# app.py
import os
import logging
import hmac
import hashlib
import json
import secrets
import asyncio
from urllib.parse import unquote, parse_qs
from datetime import datetime as dt, timezone, timedelta
from decimal import Decimal

from flask import Flask, jsonify, request as flask_request, abort as flask_abort
from flask_cors import CORS
from dotenv import load_dotenv
import telebot
from telebot import types
from sqlalchemy import create_engine, Column, BigInteger, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.sql import func
from sqlalchemy.exc import IntegrityError
from pytoniq import LiteBalancer

# --- Configuration ---
load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://plinko-rj2a.onrender.com")
DEPOSIT_WALLET_ADDRESS = os.environ.get("DEPOSIT_WALLET_ADDRESS")
# ВАЖНО: Укажите ваш Telegram ID в переменных окружения на Render.com
# Пример: ADMIN_USER_IDS = "12345678,87654321"
ADMIN_IDS_STR = os.environ.get("ADMIN_USER_IDS", "")
ADMIN_USER_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',') if admin_id.strip()]

# Конфигурация игры Plinko (теперь на бэкенде)
PLINKO_CONFIGS = {
    'low':    {'rows': 8, 'multipliers': [5, 2, 1.5, 1.1, 1, 1, 1.1, 1.5, 2, 5]},
    'medium': {'rows': 12, 'multipliers': [20, 5, 2, 1.2, 0.5, 0.4, 0.4, 0.5, 1.2, 2, 5, 20]},
    'high':   {'rows': 16, 'multipliers': [250, 25, 5, 1.5, 0.5, 0.2, 0.1, 0, 0.1, 0.2, 0.5, 1.5, 5, 25, 250]}
}

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Database Setup (SQLAlchemy) ---
if not DATABASE_URL:
    logger.error("DATABASE_URL is not set. Exiting.")
    exit()

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Database Models ---
class User(Base):
    __tablename__ = "plinko_users"
    telegram_id = Column(BigInteger, primary_key=True, index=True, autoincrement=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    balance = Column(Float, default=2000.0, nullable=False) # Стартовый баланс для новых пользователей
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class PlinkoDrop(Base):
    __tablename__ = "plinko_drops"
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("plinko_users.telegram_id"), nullable=False)
    bet_amount = Column(Float, nullable=False)
    risk_level = Column(String, nullable=False)
    multiplier_won = Column(Float, nullable=False)
    winnings = Column(Float, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

class Deposit(Base):
    __tablename__ = "plinko_deposits"
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("plinko_users.telegram_id"), nullable=False)
    amount = Column(Float, nullable=False)
    deposit_type = Column(String, nullable=False) # 'TON', 'STARS', 'GIFT'
    status = Column(String, default="pending", index=True)
    unique_comment = Column(String, nullable=True, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

Base.metadata.create_all(bind=engine)

# --- Flask App & Bot Initialization ---
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}}) # Настройте для продакшена
bot = telebot.TeleBot(BOT_TOKEN, threaded=False) if BOT_TOKEN else None

# --- Telegram Data Validation ---
def validate_init_data(init_data_str, bot_token):
    try:
        parsed_data = dict(parse_qs(init_data_str))
        hash_received = parsed_data.pop('hash')[0]
        data_check_string_parts = []
        for key in sorted(parsed_data.keys()):
            data_check_string_parts.append(f"{key}={parsed_data[key][0]}")
        data_check_string = "\n".join(data_check_string_parts)
        
        secret_key = hmac.new("WebAppData".encode(), bot_token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if calculated_hash == hash_received:
            user_data = json.loads(unquote(parsed_data['user'][0]))
            return user_data
        return None
    except Exception as e:
        logger.error(f"InitData validation error: {e}")
        return None

# --- Telegram Bot Handlers ---
if bot:
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        try:
            markup = types.InlineKeyboardMarkup()
            web_app_info = types.WebAppInfo(url=f"{RENDER_EXTERNAL_URL}")
            app_button = types.InlineKeyboardButton(text="🎮 Открыть Plinko", web_app=web_app_info)
            markup.add(app_button)
            bot.send_message(message.chat.id, "Добро пожаловать в Plinko! Нажмите кнопку ниже, чтобы начать игру.", reply_markup=markup)
        except Exception as e:
            logger.error(f"Error in /start handler: {e}")

    @bot.message_handler(commands=['add'])
    def add_balance_command(message):
        if message.from_user.id not in ADMIN_USER_IDS:
            bot.reply_to(message, "Эта команда доступна только администраторам.")
            return
        
        try:
            parts = message.text.split()
            if len(parts) != 3:
                bot.reply_to(message, "Неверный формат. Используйте: `/add @username сумма`", parse_mode="Markdown")
                return
            
            target_username = parts[1].replace('@', '').strip().lower()
            amount_to_add = float(parts[2])

            if amount_to_add <= 0:
                bot.reply_to(message, "Сумма должна быть положительной.")
                return

            db = SessionLocal()
            target_user = db.query(User).filter(func.lower(User.username) == target_username).first()

            if not target_user:
                bot.reply_to(message, f"Пользователь @{target_username} не найден.")
                return

            target_user.balance += amount_to_add
            new_deposit = Deposit(user_id=target_user.telegram_id, amount=amount_to_add, deposit_type='GIFT', status='completed')
            db.add(new_deposit)
            db.commit()

            bot.reply_to(message, f"✅ Успешно добавлено ${amount_to_add:.2f} пользователю @{target_username}. Новый баланс: ${target_user.balance:.2f}")
            bot.send_message(target_user.telegram_id, f"🎉 Администратор пополнил ваш баланс на ${amount_to_add:.2f}!")
        except ValueError:
            bot.reply_to(message, "Неверная сумма. Укажите число.")
        except Exception as e:
            logger.error(f"Error in /add command: {e}")
            bot.reply_to(message, "Произошла ошибка при выполнении команды.")
        finally:
            if 'db' in locals() and db.is_active:
                db.close()

    @bot.pre_checkout_query_handler(func=lambda query: True)
    def pre_checkout_process(pre_checkout_query: types.PreCheckoutQuery):
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

    @bot.message_handler(content_types=['successful_payment'])
    def successful_payment_process(message: types.Message):
        payment = message.successful_payment
        user_id = message.from_user.id
        stars_amount = payment.total_amount
        # Примерная конвертация, можно настроить
        balance_to_add = stars_amount / 10 

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if user:
                user.balance += balance_to_add
                new_deposit = Deposit(user_id=user_id, amount=balance_to_add, deposit_type='STARS', status='completed')
                db.add(new_deposit)
                db.commit()
                bot.send_message(user_id, f"✅ Оплата прошла успешно! Ваш баланс пополнен на ${balance_to_add:.2f}.")
            else:
                logger.error(f"User {user_id} not found after successful Stars payment.")
        except Exception as e:
            db.rollback()
            logger.error(f"DB error processing Stars payment for {user_id}: {e}")
        finally:
            db.close()

# --- API Routes ---
@app.route('/api/user_data', methods=['POST'])
def get_user_data():
    auth_data = validate_init_data(flask_request.headers.get('X-Telegram-Init-Data'), BOT_TOKEN)
    if not auth_data:
        return jsonify({"error": "Authentication failed"}), 401
    
    user_id = auth_data['id']
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if not user:
            user = User(
                telegram_id=user_id,
                username=auth_data.get('username'),
                first_name=auth_data.get('first_name')
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        
        return jsonify({
            "id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "balance": user.balance
        })
    finally:
        db.close()

@app.route('/api/plinko_drop', methods=['POST'])
def plinko_drop():
    auth_data = validate_init_data(flask_request.headers.get('X-Telegram-Init-Data'), BOT_TOKEN)
    if not auth_data:
        return jsonify({"error": "Authentication failed"}), 401

    user_id = auth_data['id']
    data = flask_request.get_json()
    bet_amount = Decimal(str(data.get('bet', 0)))
    risk = data.get('risk', 'medium')

    if risk not in PLINKO_CONFIGS:
        return jsonify({"error": "Invalid risk level"}), 400

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if not user or Decimal(str(user.balance)) < bet_amount:
            return jsonify({"error": "Insufficient balance"}), 400

        # --- Server-side game logic ---
        config = PLINKO_CONFIGS[risk]
        rows = config['rows']
        
        # Симуляция падения: N рядов = N выборов (влево -1, вправо +1)
        # Итоговая позиция - это сумма смещений
        final_pos_offset = sum(secrets.choice([-1, 1]) for _ in range(rows))
        
        # Преобразование смещения в индекс массива множителей
        center_index = len(config['multipliers']) // 2
        final_index = center_index + final_pos_offset
        final_index = max(0, min(len(config['multipliers']) - 1, final_index))
        
        multiplier = Decimal(str(config['multipliers'][final_index]))
        winnings = bet_amount * multiplier

        # Обновление баланса
        user.balance = float(Decimal(str(user.balance)) - bet_amount + winnings)

        # Логирование игры
        drop_log = PlinkoDrop(
            user_id=user_id, bet_amount=float(bet_amount), risk_level=risk,
            multiplier_won=float(multiplier), winnings=float(winnings)
        )
        db.add(drop_log)
        db.commit()

        return jsonify({
            "status": "success",
            "multiplier": float(multiplier),
            "winnings": float(winnings),
            "new_balance": user.balance,
            "final_slot_index": final_index # Отправляем индекс для подсветки на фронте
        })
    finally:
        db.close()

@app.route('/api/initiate_ton_deposit', methods=['POST'])
def initiate_ton_deposit():
    auth_data = validate_init_data(flask_request.headers.get('X-Telegram-Init-Data'), BOT_TOKEN)
    if not auth_data: return jsonify({"error": "Auth failed"}), 401

    user_id = auth_data['id']
    unique_comment = f"plnko_{secrets.token_hex(4)}"
    
    db = SessionLocal()
    try:
        new_deposit = Deposit(
            user_id=user_id, amount=0, deposit_type='TON', 
            status='pending', unique_comment=unique_comment,
            expires_at=dt.now(timezone.utc) + timedelta(minutes=30)
        )
        db.add(new_deposit)
        db.commit()
        return jsonify({
            "status": "success",
            "recipient_address": DEPOSIT_WALLET_ADDRESS,
            "comment": unique_comment
        })
    finally:
        db.close()

@app.route('/api/verify_ton_deposit', methods=['POST'])
def verify_ton_deposit():
    auth_data = validate_init_data(flask_request.headers.get('X-Telegram-Init-Data'), BOT_TOKEN)
    if not auth_data: return jsonify({"error": "Auth failed"}), 401

    user_id = auth_data['id']
    data = flask_request.get_json()
    comment = data.get('comment')
    
    db = SessionLocal()
    try:
        pdep = db.query(Deposit).filter(Deposit.user_id == user_id, Deposit.unique_comment == comment, Deposit.status == 'pending').first()
        if not pdep:
            return jsonify({"status": "not_found", "message": "Deposit request not found or already processed."})

        if pdep.expires_at < dt.now(timezone.utc):
            pdep.status = 'expired'
            db.commit()
            return jsonify({"status": "expired", "message": "Deposit request has expired."})
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        tx = loop.run_until_complete(check_blockchain_for_tx(comment))
        loop.close()

        if tx:
            amount_credited = Decimal(tx.in_msg.info.value_coins) / Decimal('1e9')
            user = db.query(User).filter(User.telegram_id == user_id).first()
            user.balance = float(Decimal(str(user.balance)) + amount_credited)
            pdep.status = 'completed'
            pdep.amount = float(amount_credited)
            db.commit()
            return jsonify({"status": "success", "message": f"Credited ${amount_credited:.4f}", "new_balance": user.balance})
        else:
            return jsonify({"status": "pending", "message": "Transaction not found yet. Please wait a moment and try again."})
    finally:
        db.close()

async def check_blockchain_for_tx(comment):
    provider = None
    try:
        provider = LiteBalancer.from_mainnet_config(trust_level=2)
        await provider.start_up()
        txs = await provider.get_transactions(DEPOSIT_WALLET_ADDRESS, count=50)
        for tx in txs:
            if tx.in_msg and tx.in_msg.body:
                try:
                    tx_comment = tx.in_msg.body.load_snake_string()
                    if tx_comment == comment:
                        return tx
                except:
                    continue
        return None
    finally:
        if provider: await provider.close_all()

@app.route('/api/create_stars_invoice', methods=['POST'])
def create_stars_invoice():
    auth_data = validate_init_data(flask_request.headers.get('X-Telegram-Init-Data'), BOT_TOKEN)
    if not auth_data: return jsonify({"error": "Auth failed"}), 401

    data = flask_request.get_json()
    stars_amount = int(data.get('amount', 0))

    if not (1 <= stars_amount <= 10000):
        return jsonify({"error": "Amount must be between 1 and 10000 Stars"}), 400

    invoice_link = bot.create_invoice_link(
        title=f"Покупка ${stars_amount / 10:.2f}",
        description=f"Пополнение баланса Plinko на {stars_amount} Stars.",
        payload=f"plinko-stars-deposit-{auth_data['id']}-{secrets.token_hex(4)}",
        provider_token="", # Для XTR токен не нужен, но поле обязательно
        currency="XTR",
        prices=[types.LabeledPrice(label=f"{stars_amount} Stars", amount=stars_amount)]
    )
    return jsonify({"status": "success", "invoice_link": invoice_link})

# --- Webhook Setup ---
def setup_telegram_webhook(flask_app):
    if not bot: return
    WEBHOOK_PATH = f'/{BOT_TOKEN}'
    FULL_WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"

    @flask_app.route(WEBHOOK_PATH, methods=['POST'])
    def webhook_handler():
        if flask_request.headers.get('content-type') == 'application/json':
            json_string = flask_request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            return '', 200
        flask_abort(403)
    
    try:
        bot.remove_webhook()
        bot.set_webhook(url=FULL_WEBHOOK_URL)
        logger.info(f"Webhook set to {FULL_WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")

if BOT_TOKEN:
    setup_telegram_webhook(app)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
