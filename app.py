import os
import logging
import hmac
import hashlib
import json
import secrets
import time
import uuid
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
from werkzeug.exceptions import Unauthorized

# --- Configuration --
load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")
PORTALS_AUTH_TOKEN = os.environ.get("PORTALS_AUTH_TOKEN")
GIFT_DEPOSIT_API_KEY = os.environ.get("GIFT_DEPOSIT_API_KEY")
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
        'rows': 8,
        'slots': [
            [600, 900], [350, 600], [200, 350], 'Ring', 'Bear', 'Ring', [200, 350], [350, 600], [600, 900]
        ]
    },
    '1000': {
        'bet_amount': 1000,
        'rows': 8,
        'slots': [
            # --- UPDATED RANGES FOR 1000 STARS ---
            [3000, 4000], [1500, 2000], [600, 1000], [400, 600], [200, 400], [400, 600], [600, 1000], [1500, 2000], [3000, 4000]
        ]
    },
    '4000': {
        'bet_amount': 4000,
        'rows': 8,
        'slots': [
            # --- UPDATED RANGES FOR 4000 STARS ---
            [7000, 20000], [4500, 7000], [3000, 4500], [1500, 3000], [1000, 1500], [1500, 3000], [3000, 4500], [4500, 7000], [7000, 20000]
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

board_cache = {}
CACHE_EXPIRATION_SECONDS = 300 # 5 minutes
withdrawal_tasks = []

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not DATABASE_URL:
    logger.error("DATABASE_URL is not set. Exiting.")
    exit()

engine = create_engine(DATABASE_URL, pool_recycle=300)
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
        
        # --- NEW PROBABILITY LOGIC FOR FREE TRY ---
        # 95% chance for a 'Bear', 5% for a 'Ring'
        won_gift_name = random.choices(['Bear', 'Ring'], weights=[95, 5], k=1)[0]
        
        # Get gift details from the EMOJI_GIFTS dictionary
        gift_data = EMOJI_GIFTS[won_gift_name]
        won_item_details = {
            "id": gift_data["id"],
            "name": won_gift_name,
            "value": gift_data["value"],
            "imageUrl": gift_data["imageUrl"]
        }
        
        # Add the won gift to the user's inventory
        new_gift_in_inventory = UserGiftInventory(
            user_id=user_id,
            gift_id=str(won_item_details.get('id')),
            gift_name=won_item_details.get('name'),
            value_at_win=float(won_item_details.get('value')),
            imageUrl=won_item_details.get('imageUrl')
        )
        db.add(new_gift_in_inventory)
        db.flush() # Get the new ID
        won_item_details["inventory_id"] = new_gift_in_inventory.id

        # Log this as a free drop (bet amount is 0)
        drop_log = PlinkoDrop(user_id=user_id, bet_amount=0, risk_level='free_try', multiplier_won=0, winnings=0)
        db.add(drop_log)
        db.commit()
        
        # The response structure now mimics the main game drop so the frontend can animate it
        return jsonify({
            "status": "success", 
            "message": f"Бесплатный бросок получен! Вы выиграли: {won_gift_name}!", 
            "new_claim_time": now.isoformat(),
            "game_result": {
                "status": "success",
                "new_balance": user.balance, # Balance is unchanged
                "final_slot_index": 4, # Animate to the middle slot
                "won_item": won_item_details
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
    seed = data.get('seed')

    if not seed:
        return jsonify({"error": "Missing board seed for drop"}), 400
    if bet_mode not in BET_MODES_CONFIG:
        return jsonify({"error": "Invalid bet mode"}), 400
    
    cached_entry = board_cache.get(seed)

    if not cached_entry or (dt.utcnow() - cached_entry['timestamp']) > timedelta(seconds=CACHE_EXPIRATION_SECONDS):
        logger.warning(f"STRICT CACHE MISS for seed: {seed}. Rejecting drop.")
        if seed in board_cache:
            del board_cache[seed]
        return jsonify({
            "error": "Ваша игровая сессия истекла. Пожалуйста, сделайте бросок еще раз."
        }), 400

    # The cached board is found and is valid. We use it.
    all_gifts_on_board = cached_entry['board']
    
    # --- FIX IS HERE: The problematic 'del board_cache[seed]' line has been REMOVED. ---
    # The cache entry will now persist for multiple drops until it expires naturally.

    config = BET_MODES_CONFIG[bet_mode]
    bet_amount = Decimal(str(config['bet_amount']))
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if not user or Decimal(str(user.balance)) < bet_amount:
            return jsonify({"error": "Insufficient balance"}), 400

        user.balance = float(Decimal(str(user.balance)) - bet_amount)
        
        # --- NEW PROBABILITY LOGIC ---
        # The user's requested probabilities (85, 18, 2) sum to 105.
        # We'll use them as weights to create a correct distribution.
        outcome_category = random.choices(
            ['lose', 'breakeven', 'win'], 
            weights=[85, 18, 2], 
            k=1
        )[0]

        # Generate the consistent board layout based on the seed
        all_gifts_on_board = generate_board_gifts(bet_mode, seed)
        
        # Filter gifts based on the determined outcome
        lose_gifts = [g for g in all_gifts_on_board if g['value'] < bet_amount]
        # Allow a small tolerance for breakeven, e.g., for values like 999.9 vs 1000
        breakeven_gifts = [g for g in all_gifts_on_board if abs(g['value'] - float(bet_amount)) < 1.0]
        win_gifts = [g for g in all_gifts_on_board if g['value'] > bet_amount]

        eligible_gifts = []
        if outcome_category == 'lose' and lose_gifts:
            eligible_gifts = lose_gifts
        elif outcome_category == 'breakeven' and breakeven_gifts:
            eligible_gifts = breakeven_gifts
        elif outcome_category == 'win' and win_gifts:
            eligible_gifts = win_gifts

        # Fallback mechanism in case a category has no eligible gifts on the board
        if not eligible_gifts:
            if outcome_category == 'win': # If win is chosen but no win gifts, fallback to the best possible
                eligible_gifts = [max(all_gifts_on_board, key=lambda g: g['value'])]
            elif outcome_category == 'breakeven': # Fallback to closest value to bet
                eligible_gifts = [min(all_gifts_on_board, key=lambda g: abs(g['value'] - float(bet_amount)))]
            else: # Fallback for 'lose'
                eligible_gifts = lose_gifts if lose_gifts else [min(all_gifts_on_board, key=lambda g: g['value'])]

        # Select the final winning item
        won_item_details = random.choice(eligible_gifts)

        # Find all possible indices for the winning item on the board to ensure animation is correct
        possible_indices = [i for i, gift in enumerate(all_gifts_on_board) if gift['id'] == won_item_details['id']]
        final_index = random.choice(possible_indices)
        # --- END OF NEW LOGIC ---

        # Add the won item to the user's inventory
        new_gift_in_inventory = UserGiftInventory(
            user_id=user_id, 
            gift_id=str(won_item_details.get('id', 'N/A')), 
            gift_name=won_item_details.get('name'), 
            value_at_win=float(won_item_details.get('value')), 
            imageUrl=won_item_details.get('imageUrl')
        )
        db.add(new_gift_in_inventory)
        db.flush() # Flush to get the new inventory ID
        won_item_details["inventory_id"] = new_gift_in_inventory.id
        
        # Log the drop
        drop_log = PlinkoDrop(user_id=user_id, bet_amount=float(bet_amount), risk_level=f"mode_{bet_mode}", multiplier_won=0, winnings=0)
        db.add(drop_log)
        db.commit()

        return jsonify({
            "status": "success", 
            "new_balance": user.balance, 
            "final_slot_index": final_index, 
            "won_item": won_item_details
        })

    except Exception as e:
        db.rollback()
        logger.error(f"Error during Plinko drop for user {user_id}: {e}", exc_info=True)
        return jsonify({"error": "An internal server error occurred"}), 500
    finally:
        db.close()

def generate_board_gifts(bet_mode, seed):
    """
    Generates the complete, symmetrical list of gift objects for a given bet mode and seed.
    This is the single source of truth for both displaying and awarding prizes.
    """
    config = BET_MODES_CONFIG[bet_mode]
    master_gift_list = build_master_gift_list()
    if not master_gift_list:
        raise ConnectionError("Could not retrieve gift market data.")

    # Use the provided seed to initialize the random number generator for deterministic results
    seeded_random = random.Random(seed)

    # Determine gifts for the first half of the board
    num_slots = len(config['slots'])
    mid_point_index = (num_slots // 2)
    first_half_gifts = []
    
    for i in range(mid_point_index + 1):
        slot_config = config['slots'][i]
        gift_object = None
        if isinstance(slot_config, list):
            min_val, max_val = slot_config
            # This simplified call is now correct
            gift_object = select_gift_for_range(min_val, max_val, master_gift_list, seeded_random)
        elif isinstance(slot_config, str) and slot_config in EMOJI_GIFTS:
            gift_data = EMOJI_GIFTS[slot_config]
            gift_object = {
                "id": gift_data["id"], "name": slot_config, 
                "value": gift_data["value"], "imageUrl": gift_data["imageUrl"]
            }
        first_half_gifts.append(gift_object)
    
    # Construct the full symmetrical list by mirroring the first half
    second_half_gifts = first_half_gifts[:-1][::-1]
    return first_half_gifts + second_half_gifts

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
    for gift_name, gift_data in EMOJI_GIFTS.items():
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

@app.route('/api/create_withdrawal_task', methods=['POST'])
def create_withdrawal_task():
    auth_data = validate_init_data(flask_request.headers.get('X-Telegram-Init-Data'), BOT_TOKEN)
    if not auth_data: return jsonify({"error": "Auth failed"}), 401
    
    user_id = auth_data['id']
    username = auth_data.get('username', f"id_{user_id}")
    data = flask_request.get_json()
    inventory_id = data.get('inventory_id')

    db = SessionLocal()
    try:
        item_to_withdraw = db.query(UserGiftInventory).filter(
            UserGiftInventory.id == inventory_id, 
            UserGiftInventory.user_id == user_id
        ).with_for_update().first() # Using the lock for race-condition safety

        if not item_to_withdraw:
            return jsonify({"status": "error", "message": "Item not found in your inventory."}), 404
        
        if item_to_withdraw.gift_name in EMOJI_GIFTS:
             return jsonify({"status": "error", "message": "Emoji gifts cannot be withdrawn."}), 400

        # --- THIS IS THE CRITICAL PART ---
        # Ensure the task dictionary includes the 'inventory_id'
        task = {
            "task_id": str(uuid.uuid4()),
            "telegram_id": user_id,
            "username": username,
            "gift_name": item_to_withdraw.gift_name,
            "gift_slug": item_to_withdraw.gift_name.lower().replace(" ", ""),
            "inventory_id": item_to_withdraw.id # THIS LINE IS MISSING IN YOUR DEPLOYED CODE
        }
        withdrawal_tasks.append(task)
        
        # We do NOT delete the item here. We wait for the userbot to confirm.
        db.commit()

        logger.info(f"Created withdrawal task for user {user_id}: Withdraw '{item_to_withdraw.gift_name}'")
        return jsonify({"status": "success", "message": "Withdrawal task created."})
    finally:
        db.close()

@app.route('/api/get_all_gift_prices', methods=['GET'])
def get_all_gift_prices():
    all_gifts = []
    
    # Add emoji gifts with fixed prices
    for name, data in EMOJI_GIFTS.items():
        all_gifts.append({
            "name": name,
            "value": data['value'],
            "imageUrl": data['imageUrl']
        })
        
    # Add collectible gifts with dynamic floor prices
    floor_prices = get_gift_floor_prices()
    for gift_id, data in REGULAR_GIFTS.items():
        normalized_name = data['name'].lower().replace("'", "")
        if normalized_name in floor_prices:
            all_gifts.append({
                "name": data['name'].replace("'", " ").title(),
                "value": floor_prices[normalized_name],
                "imageUrl": f"https://raw.githubusercontent.com/Vasiliy-katsyka/plinko/main/GiftImages/{data['filename']}"
            })

    # Sort by value, descending
    all_gifts.sort(key=lambda x: x['value'], reverse=True)
    return jsonify(all_gifts)

@app.route('/api/get_withdrawal_tasks', methods=['GET'])
def get_withdrawal_tasks():
    # Secure this endpoint for the userbot
    received_key = flask_request.headers.get('X-API-Key')
    if not GIFT_DEPOSIT_API_KEY or received_key != GIFT_DEPOSIT_API_KEY:
        raise Unauthorized("Invalid API Key")
    
    # Return current tasks and clear the list
    tasks_to_process = list(withdrawal_tasks)
    withdrawal_tasks.clear()
    
    return jsonify({"tasks": tasks_to_process})

@app.route('/api/public/deposit_gift', methods=['POST'])
def public_deposit_gift():
    """
    Public endpoint for the userbot to call.
    Receives a gift, finds its value from EITHER the emoji list OR the database,
    and adds it to a user's balance.
    """
    # 1. Secure the endpoint
    received_key = flask_request.headers.get('X-API-Key')
    if not GIFT_DEPOSIT_API_KEY or received_key != GIFT_DEPOSIT_API_KEY:
        logger.warning("Unauthorized attempt to access deposit_gift endpoint.")
        raise Unauthorized("Invalid API Key")

    # 2. Get data from the request
    data = flask_request.get_json()
    if not data or 'telegram_id' not in data or 'gift_name' not in data:
        return jsonify({"status": "error", "message": "Missing telegram_id or gift_name"}), 400

    telegram_id = data['telegram_id']
    gift_title = data['gift_name']
    
    db = SessionLocal()
    try:
        # 3. Find the user
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if not user:
            logger.warning(f"Gift deposit attempt for non-existent user: {telegram_id}")
            return jsonify({"status": "error", "message": f"User with ID {telegram_id} not found."}), 404

        # --- NEW UNIFIED PRICE LOOKUP LOGIC ---
        gift_value_in_stars = None

        # Step A: Check if it's a known, fixed-price emoji gift first.
        if gift_title in EMOJI_GIFTS:
            gift_value_in_stars = EMOJI_GIFTS[gift_title]['value']
            logging.info(f"Identified '{gift_title}' as an emoji gift with value {gift_value_in_stars}.")
        
        # Step B: If not an emoji gift, check the database for collectible gift prices.
        else:
            normalized_gift_name = gift_title.lower().replace(" ", "").replace("'", "")
            floor_prices = get_gift_floor_prices()
            if normalized_gift_name in floor_prices:
                gift_value_in_stars = floor_prices[normalized_gift_name]
                logging.info(f"Identified '{gift_title}' as a collectible gift with value {gift_value_in_stars}.")

        # Step C: If the gift was not found in EITHER location, reject it.
        if gift_value_in_stars is None:
            logger.error(f"Received unknown gift '{gift_title}' from user {telegram_id}. Not found in emoji list or DB.")
            return jsonify({"status": "error", "message": f"Gift '{gift_title}' is not recognized or has no price."}), 400
        # --- END OF NEW LOGIC ---

        # 5. Update user balance and log the deposit
        user.balance += gift_value_in_stars
        
        new_deposit = Deposit(
            user_id=user.telegram_id, 
            amount=gift_value_in_stars, 
            deposit_type='GIFT_TRANSFER', 
            status='completed'
        )
        db.add(new_deposit)
        db.commit()

        logger.info(f"Successfully processed gift '{gift_title}' for user {telegram_id}. Added {gift_value_in_stars} Stars. New balance: {user.balance}")

        # 6. Return success response
        return jsonify({
            "status": "success",
            "message": f"Successfully credited {gift_value_in_stars:.2f} Stars for the '{gift_title}' gift.",
            "new_balance": user.balance,
            "credited_amount": gift_value_in_stars
        })

    except Exception as e:
        db.rollback()
        logger.error(f"Error processing gift deposit for user {telegram_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An internal server error occurred."}), 500
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
    seed = data.get('seed', 'default_seed')

    if bet_mode not in BET_MODES_CONFIG:
        return jsonify({"error": "Invalid bet mode"}), 400
    
    try:
        # --- CHANGE IS HERE: Caching Logic ---
        all_gifts_on_board = generate_board_gifts(bet_mode, seed)
        board_cache[seed] = {
            'board': all_gifts_on_board,
            'timestamp': dt.utcnow()
        }
        # --- END CHANGE ---
        
        formatted_slots = []
        bet_amount = BET_MODES_CONFIG[bet_mode]['bet_amount']
        for gift in all_gifts_on_board:
            if gift:
                gift_value = gift.get('value', 0)
                formatted_slots.append({
                    "name": gift.get('name', 'Unknown'),
                    "imageUrl": gift.get('imageUrl', ''),
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

def select_gift_for_range(min_val, max_val, gift_list, seeded_random_gen):
    """
    Selects a gift for a price range using a seeded random generator for consistency.
    """
    eligible_gifts = [g for g in gift_list if min_val <= g.get('value', 0) <= max_val]
    
    if not eligible_gifts:
        # Fallback remains the same
        mid_point = (min_val + max_val) / 2
        return min(gift_list, key=lambda g: abs(g.get('value', 0) - mid_point))
        
    # Simply return the next random choice from the seeded generator
    return seeded_random_gen.choice(eligible_gifts)

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
