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
    "5983471780763796287": "santahat",
    "5936085638515261992": "signetring",
    "5933671725160989227": "preciouspeach",
    "5936013938331222567": "plushpepe",
    "5913442287462908725": "spicedwine",
    "5915502858152706668": "jellybunny",
    "5915521180483191380": "durov'scap",
    "5913517067138499193": "perfumebottle",
    "5882125812596999035": "eternalrose",
    "5882252952218894938": "berrybox",
    "5857140566201991735": "vintagecigar",
    "5846226946928673709": "magicpotion",
    "5845776576658015084": "kissedfrog",
    "5825801628657124140": "hexpot",
    "5825480571261813595": "evileye",
    "5841689550203650524": "sharptongue",
    "5841391256135008713": "trappedheart",
    "5839038009193792264": "skullflower",
    "5837059369300132790": "scaredcat",
    "5821261908354794038": "spyagaric",
    "5783075783622787539": "homemadecake",
    "5933531623327795414": "genielamp",
    "6028426950047957932": "lunarsnake",
    "6003643167683903930": "partysparkler",
    "5933590374185435592": "jesterhat",
    "5821384757304362229": "witchhat",
    "5915733223018594841": "hangingstar",
    "5915550639663874519": "lovecandle",
    "6001538689543439169": "cookieheart",
    "5782988952268964995": "deskcalendar",
    "6001473264306619020": "jinglebells",
    "5980789805615678057": "snowmittens",
    "5836780359634649414": "voodoodoll",
    "5841632504448025405": "madpumpkin",
    "5825895989088617224": "hypnolollipop",
    "5782984811920491178": "b-daycandle",
    "5935936766358847989": "bunnymuffin",
    "5933629604416717361": "astralshard",
    "5837063436634161765": "flyingbroom",
    "5841336413697606412": "crystalball",
    "5821205665758053411": "eternalcandle",
    "5936043693864651359": "swisswatch",
    "5983484377902875708": "gingercookie",
    "5879737836550226478": "minioscar",
    "5170594532177215681": "lolpop",
    "5843762284240831056": "iongem",
    "5936017773737018241": "starnotepad",
    "5868659926187901653": "lootbag",
    "5868348541058942091": "lovepotion",
    "5868220813026526561": "toybear",
    "5868503709637411929": "diamondring",
    "5167939598143193218": "sakuraflower",
    "5981026247860290310": "sleighbell",
    "5897593557492957738": "tophat",
    "5856973938650776169": "recordplayer",
    "5983259145522906006": "winterwreath",
    "5981132629905245483": "snowglobe",
    "5846192273657692751": "electricskull",
    "6023752243218481939": "tamagadget",
    "6003373314888696650": "candycane",
    "5933793770951673155": "nekohelmet",
    "6005659564635063386": "jack-in-the-box",
    "5773668482394620318": "easteregg",
    "5870661333703197240": "bondedring",
    "6023917088358269866": "petsnake",
    "6023679164349940429": "snakebox",
    "6003767644426076664": "xmasstocking",
    "6028283532500009446": "bigyear",
    "6003735372041814769": "holidaydrink",
    "5859442703032386168": "gemsignet",
    "5897581235231785485": "lightsword",
    "5870784783948186838": "restlessjar",
    "5870720080265871962": "nailbracelet",
    "5895328365971244193": "heroichelmet",
    "5895544372761461960": "bowtie",
    "5868455043362980631": "heartlocket",
    "5871002671934079382": "lushbouquet",
    "5933543975653737112": "whipcupcake",
    "5870862540036113469": "joyfulbundle",
    "5868561433997870501": "cupidcharm",
    "5868595669182186720": "valentinebox",
    "6014591077976114307": "snoopdogg",
    "6012607142387778152": "swagbag",
    "6012435906336654262": "snoopcigar",
    "6014675319464657779": "lowrider",
    "6014697240977737490": "westsidesign",
    "6042113507581755979": "stellarrocket",
    "6005880141270483700": "jollychimp",
    "5998981470310368313": "moonpendant",
    "5933937398953018107": "ionicdryer",
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
    if not auth_data:
        return jsonify({"error": "Authentication failed"}), 401

    user_id = auth_data['id']
    data = flask_request.get_json()
    if not data:
        return jsonify({"error": "Invalid request body"}), 400

    bet_mode = data.get('betMode') # e.g., '200', '1000', '4000'

    if bet_mode not in BET_MODES_CONFIG:
        return jsonify({"error": "Invalid bet mode"}), 400
    
    config = BET_MODES_CONFIG[bet_mode]
    bet_amount = Decimal(str(config['bet_amount']))
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if not user or Decimal(str(user.balance)) < bet_amount:
            return jsonify({"error": "Insufficient balance"}), 400

        user.balance = float(Decimal(str(user.balance)) - bet_amount)
        
        # Plinko simulation logic
        rows = config['rows']
        CENTER_BIAS = 0.2
        horizontal_offset = 0
        for _ in range(rows):
            direction = random.choice([-1, 1]) if horizontal_offset == 0 else random.choices([-1, 1], weights=[0.5 + CENTER_BIAS, 0.5 - CENTER_BIAS] if horizontal_offset > 0 else [0.5 - CENTER_BIAS, 0.5 + CENTER_BIAS], k=1)[0]
            horizontal_offset += direction

        center_index = len(config['slots']) // 2
        final_index = max(0, min(len(config['slots']) - 1, center_index + horizontal_offset))
        
        prize_config = config['slots'][final_index]
        winnings = Decimal('0')
        
        if isinstance(prize_config, list):
            # It's a range [min, max]
            winnings = Decimal(str(random.randint(prize_config[0], prize_config[1])))
        elif isinstance(prize_config, str):
            # It's an emoji gift name
            if prize_config in EMOJI_GIFTS:
                winnings = Decimal(str(EMOJI_GIFTS[prize_config]['value']))
        
        user.balance = float(Decimal(str(user.balance)) + winnings)
        
        multiplier_won = winnings / bet_amount if bet_amount > 0 else 0

        drop_log = PlinkoDrop(
            user_id=user_id, bet_amount=float(bet_amount), risk_level=f"mode_{bet_mode}",
            multiplier_won=float(multiplier_won), winnings=float(winnings)
        )
        db.add(drop_log)
        db.commit()

        return jsonify({
            "status": "success",
            "winnings": float(winnings),
            "new_balance": user.balance,
            "final_slot_index": final_index,
        })

    except Exception as e:
        db.rollback()
        logger.error(f"Error during Plinko drop for user {user_id}: {e}")
        return jsonify({"error": "An internal server error occurred"}), 500
    finally:
        db.close()

def get_gift_floor_prices():
    """
    Fetches gift floor prices from the Portals API, using a cache.
    Returns a dictionary of gift names to their floor price in Stars.
    """
    now = time.time()
    if now - gift_floor_cache["last_updated"] > CACHE_DURATION_SECONDS:
        logger.info("Cache expired. Fetching new gift floor prices from Portals API...")
        try:
            if not PORTALS_AUTH_TOKEN:
                raise ValueError("PORTALS_AUTH_TOKEN is not set.")
                
            # The API returns floors in TON (as strings)
            all_floors_ton = giftsFloors(authData=PORTALS_AUTH_TOKEN)
            
            if not all_floors_ton:
                 raise ConnectionError("Failed to retrieve data from Portals API.")

            # Convert to Stars and update cache
            floors_in_stars = {
                name: float(price) * TON_TO_STARS_RATE
                for name, price in all_floors_ton.items()
            }
            gift_floor_cache["data"] = floors_in_stars
            gift_floor_cache["last_updated"] = now
            logger.info("Successfully updated gift floor price cache.")
        except Exception as e:
            logger.error(f"Error updating gift floor cache: {e}")
            # Return the old data if the update fails to avoid breaking the app
            return gift_floor_cache["data"]
            
    return gift_floor_cache["data"]

def build_master_gift_list():
    """
    Combines regular gifts (with dynamic floor prices) and emoji gifts (with fixed values)
    into a single list of gift objects.
    """
    master_list = []
    floor_prices_stars = get_gift_floor_prices()

    # Add regular gifts
    for gift_id, gift_name in REGULAR_GIFTS.items():
        name_key = gift_name.lower()
        if name_key in floor_prices_stars:
            master_list.append({
                "id": gift_id,
                "name": gift_name,
                "value": floor_prices_stars[name_key],
                "imageUrl": f"https://cdn.changes.tg/gifts/originals/{gift_id}/Original.png"
            })

    # Add emoji gifts
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
        # Find the gift in the user's inventory to ensure they own it
        gift_to_convert = db.query(UserGiftInventory).filter(UserGiftInventory.id == inventory_id, UserGiftInventory.user_id == user_id).first()
        if not gift_to_convert:
            return jsonify({"error": "Gift not found in your inventory."}), 404

        user = db.query(User).filter(User.telegram_id == user_id).first()
        
        # Add the gift's value to the user's balance
        user.balance += gift_to_convert.value_at_win
        
        # Remove the gift from the inventory
        db.delete(gift_to_convert)
        db.commit()

        return jsonify({"status": "success", "message": "Gift converted to Stars!", "new_balance": user.balance})
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
    
    formatted_slots = []
    for slot_config in config['slots']:
        if isinstance(slot_config, list):
            avg_value = sum(slot_config) / 2
            formatted_slots.append({
                "type": "range", "display": f"{slot_config[0]}-{slot_config[1]}",
                "value": avg_value, "multiplier": avg_value / bet_amount if bet_amount > 0 else 0
            })
        elif isinstance(slot_config, str) and slot_config in EMOJI_GIFTS:
            gift_data = EMOJI_GIFTS[slot_config]
            gift_value = gift_data['value']
            formatted_slots.append({
                "type": "gift", "name": slot_config, "imageUrl": gift_data['imageUrl'],
                "value": gift_value, "multiplier": gift_value / bet_amount if bet_amount > 0 else 0
            })

    return jsonify({"slots": formatted_slots})

@app.route('/api/plinko_drop_batch', methods=['POST'])
def plinko_drop_batch():
    return jsonify({"error": "This feature is currently disabled."}), 403

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

if BOT_TOKEN:
    setup_telegram_webhook(app)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
