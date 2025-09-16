import os
import logging
import hmac
import hashlib
import json
import secrets
import time
import asyncio
from urllib.parse import unquote, parse_qs
from datetime import datetime as dt, timezone, timedelta
from decimal import Decimal
import random
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from flask import Flask, jsonify, request as flask_request, abort as flask_abort
from flask_cors import CORS
from dotenv import load_dotenv
import telebot
from telebot import types
from sqlalchemy import create_engine, Column, BigInteger, String, Float, ForeignKey, DateTime
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.sql import func
from sqlalchemy.exc import IntegrityError
from pytoniq import LiteBalancer
from portalsmp import giftsFloors

# --- Configuration ---
load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")
PORTALS_AUTH_TOKEN = os.environ.get("PORTALS_AUTH_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://plinko-4vm7.onrender.com")
DEPOSIT_WALLET_ADDRESS = os.environ.get("DEPOSIT_WALLET_ADDRESS")
ADMIN_IDS_STR = os.environ.get("ADMIN_USER_IDS", "")
REQUIRED_CHANNELS = ['@CompactTelegram', '@giftnewstoday', '@myzone196']
WEB_APP_URL = "https://vasiliy-katsyka.github.io/plinko"
ADMIN_USER_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',') if admin_id.strip()]
TON_TO_STARS_RATE = 250  # 1 TON = 250 Stars

PLINKO_CONFIGS = {
    'low': {
        'rows': 8,
        'multipliers': [4, 2, 1.2, 0.9, 0.7, 0.9, 1.2, 2, 4]
    },
    'medium': {
        'rows': 12,
        'multipliers': [18, 5, 2, 1.1, 0.8, 0.5, 0.3, 0.5, 0.8, 1.1, 2, 5, 18]
    },
    'high': {
        'rows': 16,
        'multipliers': [130, 25, 8, 2, 0.5, 0.2, 0.1, 0.1, 0, 0.1, 0.1, 0.2, 0.5, 2, 8, 25, 130]
    }
}

BET_MODES_CONFIG = {
    '200': {
        'bet_amount': 200,
        'rows': 8, # Number of peg rows for the simulation
        'slots': [
            [600, 900], [350, 600], [200, 350], 'Ring', 'Bear', 'Ring', [200, 350], [350, 600], [600, 900]
        ]
    },
    '1000': {
        'bet_amount': 1000,
        'rows': 8,
        'slots': [
            [3500, 4000], [2000, 3500], [1000, 2000], [500, 1000], 'Ring', [500, 1000], [1000, 2000], [2000, 3500], [3500, 4000]
        ]
    },
    '4000': {
        'bet_amount': 4000,
        'rows': 8,
        'slots': [
            [10000, 20000], [7000, 10000], [4000, 7000], [2000, 4000], [1000, 2000], [2000, 4000], [4000, 7000], [7000, 10000], [10000, 20000]
        ]
    }
}

REGULAR_GIFTS = {
    "5983471780763796287": {"name": "santahat", "filename": "santahat.png"},
    "5936085638515261992": {"name": "signetring", "filename": "signetring.png"},
    "5933671725160989227": {"name": "preciouspeach", "filename": "preciouspeach.png"},
    "5936013938331222567": {"name": "plushpepe", "filename": "plushpepe.png"},
    "5913442287462908725": {"name": "spicedwine", "filename": "spicedwine.png"},
    "5915502858152706668": {"name": "jellybunny", "filename": "jellybunny.png"},
    "5915521180483191380": {"name": "durov'scap", "filename": "durov'scap.png"},
    "5913517067138499193": {"name": "perfumebottle", "filename": "perfumebottle.png"},
    "5882125812596999035": {"name": "eternalrose", "filename": "eternalrose.png"},
    "5882252952218894938": {"name": "berrybox", "filename": "berrybox.png"},
    "5857140566201991735": {"name": "vintagecigar", "filename": "vintagecigar.png"},
    "5846226946928673709": {"name": "magicpotion", "filename": "magicpotion.png"},
    "5845776576658015084": {"name": "kissedfrog", "filename": "kissedfrog.png"},
    "5825801628657124140": {"name": "hexpot", "filename": "hexpot.png"},
    "5825480571261813595": {"name": "evileye", "filename": "evileye.png"},
    "5841689550203650524": {"name": "sharptongue", "filename": "sharptongue.png"},
    "5841391256135008713": {"name": "trappedheart", "filename": "trappedheart.png"},
    "5839038009193792264": {"name": "skullflower", "filename": "skullflower.png"},
    "5837059369300132790": {"name": "scaredcat", "filename": "scaredcat.png"},
    "5821261908354794038": {"name": "spyagaric", "filename": "spyagaric.png"},
    "5783075783622787539": {"name": "homemadecake", "filename": "homemadecake.png"},
    "5933531623327795414": {"name": "genielamp", "filename": "genielamp.png"},
    "6028426950047957932": {"name": "lunarsnake", "filename": "lunarsnake.png"},
    "6003643167683903930": {"name": "partysparkler", "filename": "partysparkler.png"},
    "5933590374185435592": {"name": "jesterhat", "filename": "jesterhat.png"},
    "5821384757304362229": {"name": "witchhat", "filename": "witchhat.png"},
    "5915733223018594841": {"name": "hangingstar", "filename": "hangingstar.png"},
    "5915550639663874519": {"name": "lovecandle", "filename": "lovecandle.png"},
    "6001538689543439169": {"name": "cookieheart", "filename": "cookieheart.png"},
    "5782988952268964995": {"name": "deskcalendar", "filename": "deskcalendar.png"},
    "6001473264306619020": {"name": "jinglebells", "filename": "jinglebells.png"},
    "5980789805615678057": {"name": "snowmittens", "filename": "snowmittens.png"},
    "5836780359634649414": {"name": "voodoodoll", "filename": "voodoodoll.png"},
    "5841632504448025405": {"name": "madpumpkin", "filename": "madpumpkin.png"},
    "5825895989088617224": {"name": "hypnolollipop", "filename": "Hynpo-Lollipop.png"},
    "5782984811920491178": {"name": "b-daycandle", "filename": "b-daycandle.png"},
    "5935936766358847989": {"name": "bunnymuffin", "filename": "bunnymuffin.png"},
    "5933629604416717361": {"name": "astralshard", "filename": "astralshard.png"},
    "5837063436634161765": {"name": "flyingbroom", "filename": "flyingbroom.png"},
    "5841336413697606412": {"name": "crystalball", "filename": "crystalball.png"},
    "5821205665758053411": {"name": "eternalcandle", "filename": "eternalcandle.png"},
    "5936043693864651359": {"name": "swisswatch", "filename": "swisswatch.png"},
    "5983484377902875708": {"name": "gingercookie", "filename": "gingercookie.png"},
    "5879737836550226478": {"name": "minioscar", "filename": "minioscar.png"},
    "5170594532177215681": {"name": "lolpop", "filename": "lolpop.png"},
    "5843762284240831056": {"name": "iongem", "filename": "iongem.png"},
    "5936017773737018241": {"name": "starnotepad", "filename": "starnotepad.png"},
    "5868659926187901653": {"name": "lootbag", "filename": "lootbag.png"},
    "5868348541058942091": {"name": "lovepotion", "filename": "lovepotion.png"},
    "5868220813026526561": {"name": "toybear", "filename": "toybear.png"},
    "5868503709637411929": {"name": "diamondring", "filename": "diamondring.png"},
    "5167939598143193218": {"name": "sakuraflower", "filename": "sakuraflower.png"},
    "5981026247860290310": {"name": "sleighbell", "filename": "sleighbell.png"},
    "5897593557492957738": {"name": "tophat", "filename": "tophat.png"},
    "5856973938650776169": {"name": "recordplayer", "filename": "recordplayer.png"},
    "5983259145522906006": {"name": "winterwreath", "filename": "winterwreath.png"},
    "5981132629905245483": {"name": "snowglobe", "filename": "snowglobe.png"},
    "5846192273657692751": {"name": "electricskull", "filename": "electricskull.png"},
    "6023752243218481939": {"name": "tamagadget", "filename": "tamagadget.png"},
    "6003373314888696650": {"name": "candycane", "filename": "candycane.png"},
    "5933793770951673155": {"name": "nekohelmet", "filename": "nekohelmet.png"},
    "6005659564635063386": {"name": "jack-in-the-box", "filename": "Jack-in-the-box.png"},
    "5773668482394620318": {"name": "easteregg", "filename": "easteregg.png"},
    "5870661333703197240": {"name": "bondedring", "filename": "bondedring.png"},
    "6023917088358269866": {"name": "petsnake", "filename": "petsnake.png"},
    "6023679164349940429": {"name": "snakebox", "filename": "snakebox.png"},
    "6003767644426076664": {"name": "xmasstocking", "filename": "xmasstocking.png"},
    "6028283532500009446": {"name": "bigyear", "filename": "bigyear.png"},
    "6003735372041814769": {"name": "holidaydrink", "filename": "holidaydrink.png"},
    "5859442703032386168": {"name": "gemsignet", "filename": "gemsignet.png"},
    "5897581235231785485": {"name": "lightsword", "filename": "lightsword.png"},
    "5870784783948186838": {"name": "restlessjar", "filename": "restlessjar.png"},
    "5870720080265871962": {"name": "nailbracelet", "filename": "nailbracelet.png"},
    "5895328365971244193": {"name": "heroichelmet", "filename": "heroichelmet.png"},
    "5895544372761461960": {"name": "bowtie", "filename": "bowtie.png"},
    "5868455043362980631": {"name": "heartlocket", "filename": "heartlocket.png"},
    "5871002671934079382": {"name": "lushbouquet", "filename": "lushbouquet.png"},
    "5933543975653737112": {"name": "whipcupcake", "filename": "whipcupcake.png"},
    "5870862540036113469": {"name": "joyfulbundle", "filename": "joyfulbundle.png"},
    "5868561433997870501": {"name": "cupidcharm", "filename": "cupidcharm.png"},
    "5868595669182186720": {"name": "valentinebox", "filename": "valentinebox.png"},
    "6014591077976114307": {"name": "snoopdogg", "filename": "snoopdogg.png"},
    "6012607142387778152": {"name": "swagbag", "filename": "swagbag.png"},
    "6012435906336654262": {"name": "snoopcigar", "filename": "snoopcigar.png"},
    "6014675319464657779": {"name": "lowrider", "filename": "lowrider.png"},
    "6014697240977737490": {"name": "westsidesign", "filename": "westsidesign.png"},
    "6042113507581755979": {"name": "stellarrocket", "filename": "stellarrocket.png"},
    "6005880141270483700": {"name": "jollychimp", "filename": "jollychimp.png"},
    "5998981470310368313": {"name": "moonpendant", "filename": "moonpendant.png"},
    "5933937398953018107": {"name": "ionicdryer", "filename": "ionicdryer.png"},
}

EMOJI_GIFTS = {
    "Heart": {"id": "5170145012310081615", "value": 15, "imageUrl": "https://github.com/Vasiliy-katsyka/gifthunter/blob/main/gifts_emoji_by_gifts_changes_bot_AgADYEwAAiHMUUk.png?raw=true"},
    "Bear": {"id": "5170233102089322756", "value": 15, "imageUrl": "https://github.com/Vasiliy-katsyka/gifthunter/blob/main/gifts_emoji_by_gifts_changes_bot_AgADomAAAvRzSEk.png?raw=true"},
    "Rose": {"id": "5168103777563050263", "value": 25, "imageUrl": "https://github.com/Vasiliy-katsyka/gifthunter/blob/main/gifts_emoji_by_gifts_changes_bot_AgADslsAAqCxSUk.png?raw=true"},
    "Rocket": {"id": "5170564780938756245", "value": 50, "imageUrl": "https://github.com/Vasiliy-katsyka/gifthunter/blob/main/gifts_emoji_by_gifts_changes_bot_AgAD9lAAAsBFUUk.png?raw=true"},
    "Bottle": {"id": "6028601630662853006", "value": 50, "imageUrl": "https://github.com/Vasiliy-katsyka/gifthunter/blob/main/gifts_emoji_by_gifts_changes_bot_AgADA2cAAm0PqUs.png?raw=true"},
    "Ring": {"id": "5170690322832818290", "value": 100, "imageUrl": "https://github.com/Vasiliy-katsyka/gifthunter/blob/main/IMG_20250901_162059_844.png?raw=true"}
}

gift_floor_cache = {
    "data": {},
    "last_updated": 0
}
CACHE_DURATION_SECONDS = 900  # 15 minutes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not DATABASE_URL:
    logger.error("DATABASE_URL is not set. Exiting.")
    exit()

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Database Models (balance, bet_amount, winnings are now in STARS) ---
class User(Base):
    __tablename__ = "plinko_users"
    telegram_id = Column(BigInteger, primary_key=True, index=True, autoincrement=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    balance = Column(Float, default=0.0, nullable=False) # Represents Stars
    last_free_drop_claim = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class PlinkoDrop(Base):
    __tablename__ = "plinko_drops"
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("plinko_users.telegram_id"), nullable=False)
    bet_amount = Column(Float, nullable=False) # Represents Stars
    risk_level = Column(String, nullable=False)
    multiplier_won = Column(Float, nullable=False)
    winnings = Column(Float, nullable=False) # Represents Stars
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

class Deposit(Base):
    __tablename__ = "plinko_deposits"
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("plinko_users.telegram_id"), nullable=False)
    amount = Column(Float, nullable=False) # Represents Stars credited
    deposit_type = Column(String, nullable=False) # 'TON', 'STARS', 'GIFT'
    status = Column(String, default="pending", index=True)
    unique_comment = Column(String, nullable=True, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

class UserGiftInventory(Base):
    __tablename__ = "plinko_user_gifts"
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("plinko_users.telegram_id"), nullable=False)
    gift_id = Column(String, nullable=False) # The gift's unique ID from TG
    gift_name = Column(String, nullable=False)
    value_at_win = Column(Float, nullable=False) # IMPORTANT: Store the Star value at the moment of winning
    imageUrl = Column(String, nullable=False)
    won_at = Column(DateTime(timezone=True), server_default=func.now())

class GiftFloorPrice(Base):
    __tablename__ = "plinko_gift_floor_prices"
    gift_name = Column(String, primary_key=True)  # The unique name, e.g., 'santahat'
    price_in_stars = Column(Float, nullable=False)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

Base.metadata.create_all(bind=engine)

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})
bot = telebot.TeleBot(BOT_TOKEN, threaded=False) if BOT_TOKEN else None

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

if bot:
    def check_subscription(user_id):
        """Checks if a user is subscribed to all required channels."""
        try:
            for channel in REQUIRED_CHANNELS:
                member = bot.get_chat_member(chat_id=channel, user_id=user_id)
                if member.status not in ['creator', 'administrator', 'member']:
                    return False
            return True
        except Exception as e:
            logger.error(f"Error checking subscription for user {user_id}: {e}")
            return False

    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        user_id = message.from_user.id
        if check_subscription(user_id):
            markup = types.InlineKeyboardMarkup()
            web_app_info = types.WebAppInfo(url=WEB_APP_URL)
            app_button = types.InlineKeyboardButton(text="🎮 Открыть Plinko", web_app=web_app_info)
            markup.add(app_button)
            bot.send_message(message.chat.id, "Добро пожаловать в Plinko! Нажмите кнопку ниже, чтобы начать игру.", reply_markup=markup)
        else:
            markup = types.InlineKeyboardMarkup(row_width=1)
            for i, channel in enumerate(REQUIRED_CHANNELS):
                markup.add(types.InlineKeyboardButton(text=f"Канал {i+1}", url=f"https://t.me/{channel[1:]}"))
            markup.add(types.InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub"))
            bot.send_message(message.chat.id, "Для доступа к боту, пожалуйста, подпишитесь на наши каналы:", reply_markup=markup)

    @bot.message_handler(commands=['add'])
    def add_balance_command(message):
        if message.from_user.id not in ADMIN_USER_IDS:
            bot.reply_to(message, "Эта команда доступна только администраторам.")
            return
        try:
            parts = message.text.split()
            if len(parts) != 3:
                bot.reply_to(message, "Неверный формат. Используйте: `/add @username сумма_в_Stars`", parse_mode="Markdown")
                return
            target_username = parts[1].replace('@', '').strip().lower()
            amount_to_add = float(parts[2]) # Amount is now in Stars
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
            
            bot.reply_to(message, f"✅ Успешно добавлено {amount_to_add:.2f} Stars пользователю @{target_username}. Новый баланс: {target_user.balance:.2f} Stars")
            bot.send_message(target_user.telegram_id, f"🎉 Администратор пополнил ваш баланс на {amount_to_add:.2f} Stars!")
        except Exception as e:
            logger.error(f"Error in /add command: {e}")
            bot.reply_to(message, "Произошла ошибка при выполнении команды.")
        finally:
            if 'db' in locals() and db.is_active:
                db.close()

    @bot.callback_query_handler(func=lambda call: call.data == "check_sub")
    def callback_check_subscription(call):
        user_id = call.from_user.id
        if check_subscription(user_id):
            bot.answer_callback_query(call.id, "Спасибо за подписку!")
            bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
            send_welcome(call.message)
        else:
            bot.answer_callback_query(call.id, "Вы еще не подписались на все каналы. Пожалуйста, проверьте снова.", show_alert=True)
    
    @bot.pre_checkout_query_handler(func=lambda query: True)
    def pre_checkout_process(pre_checkout_query: types.PreCheckoutQuery):
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

    @bot.message_handler(content_types=['successful_payment'])
    def successful_payment_process(message: types.Message):
        payment = message.successful_payment
        user_id = message.from_user.id
        stars_amount = payment.total_amount # This is the amount of stars paid
        
        balance_to_add = stars_amount
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.telegram_id == user_id).first()
            if user:
                user.balance += balance_to_add
                new_deposit = Deposit(user_id=user_id, amount=balance_to_add, deposit_type='STARS', status='completed')
                db.add(new_deposit)
                db.commit()
                bot.send_message(user_id, f"✅ Оплата прошла успешно! Ваш баланс пополнен на {balance_to_add} Stars.")
            else:
                logger.warning(f"User {user_id} not found after successful Stars payment.")
        except Exception as e:
            db.rollback()
            logger.error(f"DB error processing Stars payment for {user_id}: {e}")
        finally:
            db.close()

@app.route('/api/user_data', methods=['POST'])
def get_user_data():
    auth_data = validate_init_data(flask_request.headers.get('X-Telegram-Init-Data'), BOT_TOKEN)
    if not auth_data: return jsonify({"error": "Authentication failed"}), 401
    user_id = auth_data['id']
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if not user:
            user = User(telegram_id=user_id, username=auth_data.get('username'), first_name=auth_data.get('first_name'))
            db.add(user); db.commit(); db.refresh(user)
        last_claim_iso = user.last_free_drop_claim.isoformat() if user.last_free_drop_claim else None
        
        return jsonify({ 
            "id": user.telegram_id, 
            "username": user.username, 
            "first_name": user.first_name, 
            "balance": user.balance, # Balance is in Stars
            "last_free_drop_claim": last_claim_iso,
            "photo_url": auth_data.get('photo_url')
        })
    finally:
        db.close()

# 0.01 TON * 250 rate = 2.5 Stars
FREE_DROP_BET_AMOUNT = Decimal('2.5')

@app.route('/api/claim_free_drop', methods=['POST'])
def claim_free_drop():
    auth_data = validate_init_data(flask_request.headers.get('X-Telegram-Init-Data'), BOT_TOKEN)
    if not auth_data: return jsonify({"error": "Auth failed"}), 401
    user_id = auth_data['id']
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if not user: return jsonify({"error": "User not found"}), 404
        
        now = dt.now(timezone.utc)
        if user.last_free_drop_claim and (now - user.last_free_drop_claim) < timedelta(hours=24):
             return jsonify({"status": "error", "message": "Вы можете получить бесплатный бросок только раз в 24 часа."})

        user.last_free_drop_claim = now
        
        risk = 'medium'
        config = PLINKO_CONFIGS[risk]
        rows = config['rows']
        
        CENTER_BIAS = 0.2
        horizontal_offset = 0
        for _ in range(rows):
            if horizontal_offset > 0:
                direction = random.choices([-1, 1], weights=[0.5 + CENTER_BIAS, 0.5 - CENTER_BIAS], k=1)[0]
            elif horizontal_offset < 0:
                direction = random.choices([-1, 1], weights=[0.5 - CENTER_BIAS, 0.5 + CENTER_BIAS], k=1)[0]
            else:
                direction = random.choice([-1, 1])
            horizontal_offset += direction

        center_index = len(config['multipliers']) // 2
        final_index = max(0, min(len(config['multipliers']) - 1, center_index + horizontal_offset))
        
        multiplier = Decimal(str(config['multipliers'][final_index]))
        winnings = FREE_DROP_BET_AMOUNT * multiplier # Winnings are in Stars
        
        user.balance = float(Decimal(str(user.balance)) + winnings)
        
        drop_log = PlinkoDrop(user_id=user_id, bet_amount=float(FREE_DROP_BET_AMOUNT), risk_level=risk, multiplier_won=float(multiplier), winnings=float(winnings))
        db.add(drop_log)
        db.commit()
        
        return jsonify({
            "status": "success", 
            "message": "Бесплатный бросок получен!", 
            "new_claim_time": now.isoformat(),
            "game_result": {
                "multiplier": float(multiplier),
                "winnings": float(winnings), # Winnings in Stars
                "new_balance": user.balance, # Balance in Stars
                "final_slot_index": final_index
            }
        })
    finally:
        db.close()

@app.route('/api/plinko_drop', methods=['POST'])
def plinko_drop():
    auth_data = validate_init_data(flask_request.headers.get('X-Telegram-Init-Data'), BOT_TOKEN)
    if not auth_data: return jsonify({"error": "Authentication failed"}), 401

    user_id = auth_data['id']
    data = flask_request.get_json()
    bet_mode = data.get('betMode')

    if bet_mode not in BET_MODES_CONFIG:
        return jsonify({"error": "Invalid bet mode"}), 400
    
    config = BET_MODES_CONFIG[bet_mode]
    bet_amount = Decimal(str(config['bet_amount']))
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if not user or Decimal(str(user.balance)) < bet_amount:
            return jsonify({"error": "Insufficient balance"}), 400

        # 1. Subtract the bet amount. This is the ONLY balance change in this transaction.
        user.balance = float(Decimal(str(user.balance)) - bet_amount)
        
        # 2. CORRECTED & UNBIASED path simulation. This is the fix for the physics issue.
        #    A simple random choice on each row creates a natural bell curve distribution.
        rows = config['rows']
        horizontal_offset = 0
        for _ in range(rows):
            direction = random.choice([-1, 1]) # Purely random, fair path
            horizontal_offset += direction
            
        center_index = len(config['slots']) // 2
        final_index = max(0, min(len(config['slots']) - 1, center_index + horizontal_offset))
        
        # 3. Determine the prize and add it to inventory, NOT balance.
        prize_config = config['slots'][final_index]
        won_item_details = None
        
        # We need the full gift list to find the won item's details
        master_gift_list = build_master_gift_list()
        if not master_gift_list:
            raise ConnectionError("Could not retrieve gift market data.")

        if isinstance(prize_config, str) and prize_config in EMOJI_GIFTS:
            # Won a fixed-value emoji gift
            gift_data = EMOJI_GIFTS[prize_config]
            won_item_details = {
                "id": gift_data["id"],
                "name": prize_config,
                "value": gift_data["value"],
                "imageUrl": gift_data["imageUrl"]
            }
        elif isinstance(prize_config, list):
            # Won a dynamic gift from a price range
            won_gift_object = select_gift_for_range(prize_config[0], prize_config[1], master_gift_list)
            won_item_details = {
                "id": won_gift_object.get("id", "N/A"),
                "name": won_gift_object.get("name", "Unknown Gift"),
                "value": won_gift_object.get("value", 0),
                "imageUrl": won_gift_object.get("imageUrl", "")
            }
        
        # Create the inventory record for the user
        new_gift_in_inventory = UserGiftInventory(
            user_id=user_id,
            gift_id=str(won_item_details.get('id', 'N/A')),
            gift_name=won_item_details.get('name'),
            value_at_win=float(won_item_details.get('value')),
            imageUrl=won_item_details.get('imageUrl')
        )
        db.add(new_gift_in_inventory)

        # --- NEW CODE HERE ---
        # Flush the session to the database. This assigns the auto-incremented
        # primary key (the ID) to our 'new_gift_in_inventory' object.
        db.flush()

        # Now, add the newly created inventory ID to our response object.
        won_item_details["inventory_id"] = new_gift_in_inventory.id
        # --- END OF NEW CODE ---
        
        # Log the drop
        drop_log = PlinkoDrop(
            user_id=user_id, bet_amount=float(bet_amount), risk_level=f"mode_{bet_mode}",
            multiplier_won=0, winnings=0
        )
        db.add(drop_log)
        
        # Commit all changes together
        db.commit()

        return jsonify({
            "status": "success",
            "new_balance": user.balance,
            "final_slot_index": final_index,
            "won_item": won_item_details # This now contains the crucial 'inventory_id'
        })

    except Exception as e:
        db.rollback()
        logger.error(f"Error during Plinko drop for user {user_id}: {e}", exc_info=True)
        return jsonify({"error": "An internal server error occurred"}), 500
    finally:
        db.close()

def get_gift_floor_prices():
    """
    Retrieves all gift floor prices directly from the database.
    This is now the primary source of truth for game logic.
    """
    db = SessionLocal()
    try:
        prices = db.query(GiftFloorPrice).all()
        if not prices:
            logger.warning("GiftFloorPrice table is empty. Game logic may be affected.")
            return {}
        # Return data in the same format as before { 'gift_name': price }
        return {item.gift_name: item.price_in_stars for item in prices}
    finally:
        db.close()

def build_master_gift_list():
    """
    Combines regular gifts (with dynamic floor prices) and emoji gifts (with fixed values)
    into a single list of gift objects. Uses the new REGULAR_GIFTS structure for precise filenames.
    """
    master_list = []
    floor_prices_stars = get_gift_floor_prices()

    # Add regular gifts
    for gift_id, gift_data in REGULAR_GIFTS.items():
        internal_name = gift_data["name"]
        exact_filename = gift_data["filename"]
        
        name_key = internal_name.lower()
        if name_key in floor_prices_stars:
            master_list.append({
                "id": gift_id,
                "name": internal_name,
                "value": floor_prices_stars[name_key],
                # This now uses the correct folder and exact filename
                "imageUrl": f"https://raw.githubusercontent.com/Vasiliy-katsyka/plinko/main/GiftImages/{exact_filename}"
            })

    # Add emoji gifts (this part does not need to change)
    for gift_name, gift_data in EMO_GIFTS.items():
        master_list.append({
            "id": gift_data["id"],
            "name": gift_name,
            "value": gift_data["value"],
            "imageUrl": gift_data["imageUrl"]
        })
    
    return master_list

@app.route('/api/get_inventory', methods=['POST'])
def get_inventory():
    auth_data = validate_init_data(flask_request.headers.get('X-Telegram-Init-Data'), BOT_TOKEN)
    if not auth_data: return jsonify({"error": "Auth failed"}), 401
    user_id = auth_data['id']
    db = SessionLocal()
    try:
        inventory_items = db.query(UserGiftInventory).filter(UserGiftInventory.user_id == user_id).order_by(UserGiftInventory.won_at.desc()).all()
        # Convert SQLAlchemy objects to dictionaries
        inventory_list = [{
            "inventory_id": item.id,
            "name": item.gift_name,
            "value": item.value_at_win,
            "imageUrl": item.imageUrl
        } for item in inventory_items]
        return jsonify({"inventory": inventory_list})
    finally:
        db.close()


# POST endpoint to convert a gift to Stars
@app.route('/api/convert_gift', methods=['POST'])
def convert_gift():
    auth_data = validate_init_data(flask_request.headers.get('X-Telegram-Init-Data'), BOT_TOKEN)
    if not auth_data: return jsonify({"error": "Auth failed"}), 401
    user_id = auth_data['id']
    data = flask_request.get_json()
    inventory_id = data.get('inventory_id')

    db = SessionLocal()
    try:
        gift_to_convert = db.query(UserGiftInventory).filter(UserGiftInventory.id == inventory_id, UserGiftInventory.user_id == user_id).first()
        if not gift_to_convert:
            return jsonify({"error": "Gift not found in your inventory."}), 404

        user = db.query(User).filter(User.telegram_id == user_id).first()
        
        # --- CHANGE IS HERE ---
        # New: Calculate the conversion value with a 20% bonus
        conversion_value = gift_to_convert.value_at_win * 1.20
        
        # New: Add the boosted value to the user's balance
        user.balance += conversion_value
        
        db.delete(gift_to_convert)
        db.commit()

        # New: We can even notify the user of the bonus in the success message
        success_message = f"Gift converted! You received {conversion_value:.2f} Stars (including a 20% bonus)."
        return jsonify({"status": "success", "message": success_message, "new_balance": user.balance})
    except Exception as e:
        db.rollback()
        logger.error(f"Error converting gift: {e}")
        return jsonify({"error": "An error occurred."}), 500
    finally:
        db.close()

@app.route('/api/get_board_slots', methods=['POST'])
def get_board_slots():
    auth_data = validate_init_data(flask_request.headers.get('X-Telegram-Init-Data'), BOT_TOKEN)
    if not auth_data: return jsonify({"error": "Authentication failed"}), 401
    
    data = flask_request.get_json()
    bet_mode = data.get('betMode', '200')

    if bet_mode not in BET_MODES_CONFIG:
        return jsonify({"error": "Invalid bet mode"}), 400
    
    config = BET_MODES_CONFIG[bet_mode]
    bet_amount = config['bet_amount']
    
    try:
        # Build the master list of all gifts with their current floor prices
        master_gift_list = build_master_gift_list()
        if not master_gift_list:
            return jsonify({"error": "Could not load gift market data. Please try again."}), 503

        formatted_slots = []
        for slot_config in config['slots']:
            gift_to_display = None
            if isinstance(slot_config, list):
                # This is a price range, so find a suitable gift
                min_val, max_val = slot_config
                gift_to_display = select_gift_for_range(min_val, max_val, master_gift_list)
            
            elif isinstance(slot_config, str) and slot_config in EMOJI_GIFTS:
                # This is a specific emoji gift
                gift_data = EMOJI_GIFTS[slot_config]
                gift_to_display = {
                    "name": slot_config,
                    "imageUrl": gift_data['imageUrl'],
                    "value": gift_data['value']
                }

            if gift_to_display:
                gift_value = gift_to_display.get('value', 0)
                formatted_slots.append({
                    "name": gift_to_display.get('name', 'Unknown'),
                    "imageUrl": gift_to_display.get('imageUrl', ''),
                    "value": gift_value,
                    "multiplier": gift_value / bet_amount if bet_amount > 0 else 0
                })

        return jsonify({"slots": formatted_slots})
    except Exception as e:
        logger.error(f"Error in get_board_slots: {e}", exc_info=True)
        return jsonify({"error": "Server error while preparing game board."}), 500

@app.route('/api/plinko_drop_batch', methods=['POST'])
def plinko_drop_batch():
    return jsonify({"error": "This feature is currently disabled."}), 403

def select_gift_for_range(min_val, max_val, gift_list):
    """Selects a gift from the list that fits within the price range."""
    eligible_gifts = [g for g in gift_list if min_val <= g.get('value', 0) <= max_val]
    
    if eligible_gifts:
        # --- CHANGE IS HERE ---
        # Instead of random.choice, sort by name to make the selection deterministic.
        # This ensures get_board_slots and plinko_drop pick the same gift.
        return sorted(eligible_gifts, key=lambda g: g['name'])[0]
    else:
        # Fallback remains the same
        mid_point = (min_val + max_val) / 2
        return min(gift_list, key=lambda g: abs(g.get('value', 0) - mid_point))

@app.route('/api/initiate_ton_deposit', methods=['POST'])
def initiate_ton_deposit():
    auth_data = validate_init_data(flask_request.headers.get('X-Telegram-Init-Data'), BOT_TOKEN)
    if not auth_data: return jsonify({"error": "Auth failed"}), 401
    user_id = auth_data['id']
    unique_comment = f"plnko_{secrets.token_hex(4)}"
    db = SessionLocal()
    try:
        new_deposit = Deposit(user_id=user_id, amount=0, deposit_type='TON', status='pending', unique_comment=unique_comment, expires_at=dt.now(timezone.utc) + timedelta(minutes=30))
        db.add(new_deposit); db.commit()
        return jsonify({ "status": "success", "recipient_address": DEPOSIT_WALLET_ADDRESS, "comment": unique_comment })
    finally:
        db.close()

def update_floor_prices_in_db():
    """
    Fetches latest floor prices from the Portals API and updates the database.
    This function is intended to be run by a scheduler.
    """
    logger.info("Scheduler starting job: update_floor_prices_in_db")
    db = SessionLocal()
    try:
        if not PORTALS_AUTH_TOKEN:
            logger.warning("PORTALS_AUTH_TOKEN not set. Skipping floor price update.")
            return

        all_floors_ton = giftsFloors(authData=PORTALS_AUTH_TOKEN)
        if not all_floors_ton:
            logger.error("Failed to retrieve data from Portals API during scheduled update.")
            return

        floors_in_stars = {
            name: float(price) * TON_TO_STARS_RATE
            for name, price in all_floors_ton.items()
        }

        # "Upsert" logic: Update existing records or insert new ones
        for name, price in floors_in_stars.items():
            record = db.query(GiftFloorPrice).filter_by(gift_name=name).first()
            if record:
                record.price_in_stars = price  # Update
            else:
                db.add(GiftFloorPrice(gift_name=name, price_in_stars=price))  # Insert
        
        db.commit()
        logger.info(f"Successfully updated/inserted {len(floors_in_stars)} gift floor prices in the database.")

    except Exception as e:
        logger.error(f"An error occurred during scheduled floor price update: {e}", exc_info=True)
        db.rollback()
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
        if not pdep: return jsonify({"status": "not_found", "message": "Deposit request not found or already processed."})
        if pdep.expires_at < dt.now(timezone.utc):
            pdep.status = 'expired'; db.commit(); return jsonify({"status": "expired", "message": "Deposit request has expired."})
        
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        tx = loop.run_until_complete(check_blockchain_for_tx(comment)); loop.close()
        
        if tx:
            amount_in_ton = Decimal(tx.in_msg.info.value_coins) / Decimal('1e9')
            stars_credited = amount_in_ton * Decimal(str(TON_TO_STARS_RATE))

            user = db.query(User).filter(User.telegram_id == user_id).first()
            user.balance = float(Decimal(str(user.balance)) + stars_credited)
            
            pdep.status = 'completed'
            pdep.amount = float(stars_credited) # Store credited Stars amount
            db.commit()
            
            message_to_user = f"Успешно зачислено {float(stars_credited):.2f} Stars (из {float(amount_in_ton):.4f} TON)!"
            return jsonify({"status": "success", "message": message_to_user, "new_balance": user.balance})
        else:
            return jsonify({"status": "pending", "message": "Транзакция пока не найдена. Подождите немного и попробуйте снова."})

    except Exception as e:
        logger.error(f"Error during deposit verification: {e}")
        if db.is_active: db.rollback()
        return jsonify({"status": "error", "message": "Произошла непредвиденная ошибка во время проверки."}), 500
    finally:
        if db.is_active: db.close()

async def check_blockchain_for_tx(comment):
    provider = None
    try:
        provider = LiteBalancer.from_mainnet_config(trust_level=2)
        await provider.start_up()
        txs = await provider.get_transactions(DEPOSIT_WALLET_ADDRESS, count=200)
        for tx in txs:
            if tx.in_msg and tx.in_msg.body:
                try:
                    tx_comment_body = tx.in_msg.body.to_boc().decode('utf-8', 'ignore')
                    if comment in tx_comment_body: return tx
                    cmt_slice = tx.in_msg.body.begin_parse()
                    if cmt_slice.remaining_bits >= 32 and cmt_slice.load_uint(32) == 0:
                        if cmt_slice.load_snake_string() == comment: return tx
                except: continue
        return None
    finally:
        if provider: await provider.close_all()

@app.route('/api/create_stars_invoice', methods=['POST'])
def create_stars_invoice():
    auth_data = validate_init_data(flask_request.headers.get('X-Telegram-Init-Data'), BOT_TOKEN)
    if not auth_data: return jsonify({"error": "Auth failed"}), 401
    data = flask_request.get_json()
    stars_amount = int(data.get('amount', 0))
    if not (1 <= stars_amount <= 10000): return jsonify({"error": "Amount must be between 1 and 10000 Stars"}), 400
    
    invoice_link = bot.create_invoice_link(
        title=f"Покупка {stars_amount} Stars",
        description=f"Пополнение баланса Plinko на {stars_amount} Stars.",
        payload=f"plinko-stars-deposit-{auth_data['id']}-{secrets.token_hex(4)}",
        provider_token="",
        currency="XTR",
        prices=[types.LabeledPrice(label=f"{stars_amount} Stars", amount=stars_amount)]
    )
    return jsonify({"status": "success", "invoice_link": invoice_link})

def initial_populate_prices():
    """Checks if the price table is empty and populates it on app startup."""
    with SessionLocal() as db:
        try:
            count = db.query(func.count(GiftFloorPrice.gift_name)).scalar()
            if count == 0:
                logger.info("GiftFloorPrice table is empty. Running initial population.")
                # This direct call ensures the app has data to work with immediately.
                update_floor_prices_in_db()
            else:
                logger.info(f"GiftFloorPrice table contains {count} records. Skipping initial population.")
        except Exception as e:
            # This can happen if the database/table doesn't exist yet.
            logger.error(f"Error during initial price population check (might be normal on first run): {e}")

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
        bot.remove_webhook(); bot.set_webhook(url=FULL_WEBHOOK_URL)
        logger.info(f"Webhook set to {FULL_WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")

scheduler = BackgroundScheduler(timezone=pytz.timezone('Europe/Moscow')) 
scheduler.add_job(
    func=update_floor_prices_in_db,
    trigger=CronTrigger(hour=23, minute=8), # Runs daily at 23:00 (11 PM)
    id='update_floor_prices_job',
    name='Update gift floor prices from Portals API',
    replace_existing=True
)
scheduler.start()
logger.info("APScheduler started. Price update job is scheduled for 23:00 UTC+3.")

initial_populate_prices()

if BOT_TOKEN:
    setup_telegram_webhook(app)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
