import os
import sqlite3
import logging
import random
import string
import pyotp
import openpyxl
from datetime import datetime
from io import BytesIO
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, ConversationHandler
)

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
CHANNEL_ID = "@worst_bux_bot"
CHANNEL_LINK = "https://t.me/worst_bux_bot"
PROXY_LINK = "https://t.me/will_be_eran_shop_bot?start=ref_8907284640"

SUPERADMIN_ID = 8452827743
ADMIN_1 = int(os.environ.get("ADMIN_1", "0"))
ADMIN_2 = int(os.environ.get("ADMIN_2", "0"))

def get_all_admins():
    admins = {SUPERADMIN_ID}
    if ADMIN_1: admins.add(ADMIN_1)
    if ADMIN_2: admins.add(ADMIN_2)
    return admins

BOT_ENABLED = True
USDT_RATE = 122
FEE_USDT = 0.0250
MIN_WITHDRAW_TK = 20

# ─────────────────────────────────────────
# CONVERSATION STATES
# ─────────────────────────────────────────
(
    TASK_SELECT,
    TT_WAIT_2FA, TT_WAIT_EMAIL, TT_WAIT_REGISTERED,
    INSTA_WAIT_2FA, INSTA_WAIT_EMAIL,
    WITHDRAW_ADDR, WITHDRAW_AMOUNT,
    LANG_SELECT,
) = range(9)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# DB INIT
# ─────────────────────────────────────────
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

cur.executescript("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    balance REAL DEFAULT 0.0,
    language TEXT DEFAULT 'bn',
    joined INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tiktok_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    password TEXT,
    twofa_key TEXT,
    email TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS insta_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    password TEXT,
    twofa_key TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    address TEXT,
    amount_tk REAL,
    amount_usdt REAL,
    status TEXT DEFAULT 'pending',
    created_at TEXT
);

INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('tt_password', 'demon@15');
INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('insta_password', 'Rokon@15');
""")
conn.commit()

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def get_setting(key):
    cur.execute("SELECT value FROM bot_settings WHERE key=?", (key,))
    row = cur.fetchone()
    return row[0] if row else ""

def set_setting(key, value):
    cur.execute("INSERT OR REPLACE INTO bot_settings (key,value) VALUES (?,?)", (key, value))
    conn.commit()

def ensure_user(user):
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?,?,?)",
        (user.id, user.username or "", user.full_name or "")
    )
    conn.commit()

def get_balance(user_id):
    cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0.0

def add_balance(user_id, amount):
    cur.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, user_id))
    conn.commit()

def get_lang(user_id):
    cur.execute("SELECT language FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else "bn"

def txt(user_id, bn, en):
    return bn if get_lang(user_id) == "bn" else en

def gen_totp(secret):
    try:
        secret = secret.strip().upper().replace(" ", "")
        totp = pyotp.TOTP(secret)
        return totp.now()
    except Exception as e:
        logger.error(f"TOTP error: {e}")
        return "ERROR"

def gen_username():
    """Auto-generate an uncommon username with numbers in the middle."""
    parts = [
        "wolf", "nova", "zylo", "kori", "raxo", "mint", "luna", "drip",
        "vexo", "juno", "riko", "zephy", "orbi", "flux", "kylo", "nyra",
        "quix", "brix", "dazo", "vibr", "ghost", "pyro", "aero", "onyx",
    ]
    tails = [
        "vibe", "wave", "core", "byte", "lite", "zone", "kid", "fox",
        "boss", "hub", "lab", "pix", "sky", "dew", "ink", "run",
    ]
    head = random.choice(parts)
    tail = random.choice(tails)
    mid = "".join(random.choices(string.digits, k=random.choice([2, 3])))
    return f"{head}{mid}{tail}"

# ─────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────
def _kb(key, style=None):
    """Build a KeyboardButton, with style only if supported."""
    try:
        return KeyboardButton(key, style=style)
    except TypeError:
        return KeyboardButton(key)

def _ikb(text, style=None, **kwargs):
    """Build an InlineKeyboardButton, with style only if supported."""
    try:
        return InlineKeyboardButton(text, style=style, **kwargs)
    except TypeError:
        return InlineKeyboardButton(text, **kwargs)

def join_keyboard():
    return InlineKeyboardMarkup([
        [_ikb("💼 Official Channel", url=CHANNEL_LINK, style="primary")],
        [_ikb("✅ জয়েন করেছি", callback_data="check_join", style="success")],
    ])

def home_keyboard():
    return ReplyKeyboardMarkup([
        [_kb("💰 Balance", "success"), _kb("📋 Tasks", "primary")],
        [_kb("📥 Withdraw", "danger"), _kb("👤 Profile", "primary")],
        [_kb("🌎 Language", "primary")],
        [_kb("Support 🆘", "danger"), _kb("ProxyBOT 🪀", "success")],
    ], resize_keyboard=True)

def task_keyboard():
    return ReplyKeyboardMarkup([
        [_kb("TikTok 2Fa ( 3tk - 64 Minutes ⏰ )", "primary")],
        [_kb("Insta 2Fa ( 4tk - 64 Minutes ⏰ )", "success")],
        [_kb("Cancel ❌", "danger")],
    ], resize_keyboard=True)

def twofa_set_keyboard():
    return ReplyKeyboardMarkup([
        [_kb("2FA Set 📐", "success")],
        [_kb("Cancel ❌", "danger")],
    ], resize_keyboard=True)

def registered_keyboard():
    return ReplyKeyboardMarkup([
        [_kb("Account Registered ✅", "success")],
        [_kb("Cancel ❌", "danger")],
    ], resize_keyboard=True)

def lang_keyboard():
    return ReplyKeyboardMarkup([
        [_kb("Bangla 🇧🇩", "success"), _kb("🇺🇸 English", "primary")],
    ], resize_keyboard=True)

def review_keyboard(idx, acc_type):
    return InlineKeyboardMarkup([
        [
            _ikb("Rejected ❌", callback_data=f"rej_{acc_type}_{idx}", style="danger"),
            _ikb("Approve ✅", callback_data=f"app_{acc_type}_{idx}", style="success"),
        ],
        [
            _ikb("◀️ Previous", callback_data=f"prev_{acc_type}_{idx}", style="primary"),
            _ikb("Next 🔥", callback_data=f"next_{acc_type}_{idx}", style="primary"),
        ],
    ])

# ─────────────────────────────────────────
# UTILS
# ─────────────────────────────────────────
async def check_membership(bot, user_id):
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning(f"Membership check failed: {e}")
        return False

async def notify_admins(bot, message):
    for admin_id in get_all_admins():
        try:
            await bot.send_message(admin_id, message)
        except Exception:
            pass

def is_admin(user_id):
    return user_id in get_all_admins()

# ─────────────────────────────────────────
# /start
# ─────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    uname = f"@{user.username}" if user.username else str(user.id)
    full_name = user.full_name or "Unknown"
    await notify_admins(
        ctx.bot,
        f"🔔 User Started The Bot\n👤 {full_name}\n🆔 {uname}"
    )

    if not BOT_ENABLED:
        await update.message.reply_text("🔴 বট এখন বন্ধ আছে। পরে চেষ্টা করুন।")
        return ConversationHandler.END

    cur.execute("SELECT joined FROM users WHERE user_id=?", (user.id,))
    row = cur.fetchone()
    already_joined = row and row[0] == 1

    if already_joined:
        await update.message.reply_text(
            txt(user.id,
                "📝 কাজ করতে নিচের বাটনে ক্লিক করুন",
                "📝 Click the button below to start working"),
            reply_markup=home_keyboard()
        )
    else:
        await update.message.reply_text(
            "⚠️ বট ব্যবহার করতে হলে অবশ্যই আমাদের চ্যানেলে জয়েন থাকতে হবে!\n\n"
            "দয়া করে নিচের চ্যানেলে জয়েন করে \"✅ জয়েন করেছি\" বাটনে ক্লিক করুন।",
            reply_markup=join_keyboard()
        )
    return ConversationHandler.END

# ─────────────────────────────────────────
# CALLBACK: check join
# ─────────────────────────────────────────
async def check_join_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    uid = user.id

    if not BOT_ENABLED:
        await query.edit_message_text("🔴 বট এখন বন্ধ আছে।")
        return

    joined = await check_membership(ctx.bot, uid)
    if joined:
        cur.execute("UPDATE users SET joined=1 WHERE user_id=?", (uid,))
        conn.commit()
        await query.edit_message_text("✅ যাচাই সম্পন্ন! স্বাগতম! 🎉")
        await ctx.bot.send_message(
            uid,
            txt(uid,
                "📝 কাজ করতে নিচের বাটনে ক্লিক করুন",
                "📝 Click below to start working"),
            reply_markup=home_keyboard()
        )
    else:
        await query.answer(
            "❌ আপনি এখনও চ্যানেলে জয়েন করেননি! আগে জয়েন করুন।",
            show_alert=True
        )

# ─────────────────────────────────────────
# HOME MESSAGE HANDLER
# ─────────────────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not BOT_ENABLED:
        await update.message.reply_text("🔴 বট বন্ধ আছে।")
        return ConversationHandler.END

    uid = update.effective_user.id
    text = update.message.text

    cur.execute("SELECT joined FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()
    if not row or row[0] == 0:
        await update.message.reply_text(
            "⚠️ প্রথমে চ্যানেলে জয়েন করুন।",
            reply_markup=join_keyboard()
        )
        return ConversationHandler.END

    # ── BALANCE ──
    if text == "💰 Balance":
        bal = get_balance(uid)
        await update.message.reply_text(f"💰 {bal:.4f}tk")
        return ConversationHandler.END

    # ── TASKS ──
    elif text == "📋 Tasks":
        await update.message.reply_text(
            txt(uid, "📋 একটি কাজ বেছে নিন:", "📋 Choose a task:"),
            reply_markup=task_keyboard()
        )
        return TASK_SELECT

    # ── WITHDRAW ──
    elif text == "📥 Withdraw":
        bal = get_balance(uid)
        if bal < MIN_WITHDRAW_TK:
            await update.message.reply_text(
                txt(uid,
                    f"❌ উইথড্র করতে কমপক্ষে {MIN_WITHDRAW_TK}tk লাগবে।\n💰 আপনার ব্যালেন্স: {bal:.4f}tk",
                    f"❌ Minimum {MIN_WITHDRAW_TK}tk required.\n💰 Your balance: {bal:.4f}tk")
            )
            return ConversationHandler.END
        await update.message.reply_text(
            'Sir, Please Enter Your "USDT-BEP20" Address ✍️',
            reply_markup=ReplyKeyboardRemove()
        )
        return WITHDRAW_ADDR

    # ── PROFILE ──
    elif text == "👤 Profile":
        user = update.effective_user
        uname = f"@{user.username}" if user.username else "N/A"
        await update.message.reply_text(
            f"👤 *প্রোফাইল*\n\n"
            f"📛 নাম: {user.full_name}\n"
            f"🆔 Username: {uname}\n"
            f"🔢 Chat ID: `{user.id}`",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # ── LANGUAGE ──
    elif text == "🌎 Language":
        await update.message.reply_text(
            "🌎 ভাষা বেছে নিন / Choose language:",
            reply_markup=lang_keyboard()
        )
        return LANG_SELECT

    # ── SUPPORT ──
    elif text == "Support 🆘":
        await update.message.reply_text(
            f"🆘 সাপোর্টের জন্য আমাদের চ্যানেলে যোগাযোগ করুন:\n{CHANNEL_LINK}"
        )
        return ConversationHandler.END

    # ── PROXY ──
    elif text == "ProxyBOT 🪀":
        await update.message.reply_text(f"🪀 ProxyBOT:\n{PROXY_LINK}")
        return ConversationHandler.END

    return ConversationHandler.END

# ─────────────────────────────────────────
# TASK FLOW
# ─────────────────────────────────────────
async def task_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if text == "Cancel ❌":
        await update.message.reply_text(
            txt(uid, "🏠 হোমে ফিরে এসেছেন।", "🏠 Returned home."),
            reply_markup=home_keyboard()
        )
        return ConversationHandler.END

    elif "TikTok" in text:
        tt_user = gen_username()
        tt_pass = get_setting("tt_password")
        ctx.user_data["task"] = "tiktok"
        ctx.user_data["tt_username"] = tt_user
        await update.message.reply_text(
            f"`👤 Username: {tt_user}`\n`🔑 Password: {tt_pass}`\n\n"
            "🧾 উপরের ইউজারনেম এবং পাসওয়ার্ড দিয়ে অ্যাকাউন্ট খুলুন।\n"
            "তারপর 2FA চালু করুন এবং নিচে 2FA Set বাটনে ক্লিক করুন 👋",
            parse_mode="Markdown",
            reply_markup=twofa_set_keyboard()
        )
        return TT_WAIT_2FA

    elif "Insta" in text:
        insta_user = gen_username()
        insta_pass = get_setting("insta_password")
        ctx.user_data["task"] = "insta"
        ctx.user_data["insta_username"] = insta_user
        await update.message.reply_text(
            f"`👤 Username: {insta_user}`\n`🔑 Password: {insta_pass}`\n\n"
            "🧾 উপরের ইউজারনেম এবং পাসওয়ার্ড দিয়ে অ্যাকাউন্ট খুলুন।\n"
            "তারপর 2FA চালু করুন এবং নিচে 2FA Set বাটনে ক্লিক করুন 👋",
            parse_mode="Markdown",
            reply_markup=twofa_set_keyboard()
        )
        return INSTA_WAIT_2FA

    await update.message.reply_text("⚠️ একটি অপশন বেছে নিন।", reply_markup=task_keyboard())
    return TASK_SELECT

# ── TikTok: wait for 2FA button click, then secret key ──
async def tt_wait_2fa(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if text == "Cancel ❌":
        await update.message.reply_text("🏠", reply_markup=home_keyboard())
        return ConversationHandler.END

    if text == "2FA Set 📐":
        await update.message.reply_text(
            "🔑 এখন আপনার TikTok অ্যাকাউন্টের 2FA Secret Key পাঠান:\n\n"
            "_(2FA চালু করার সময় যে QR code বা text key পাবেন সেটা)_",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return TT_WAIT_2FA

    # user sent the 2FA secret key
    secret = text.strip().replace(" ", "")
    code = gen_totp(secret)
    ctx.user_data["tt_2fa_key"] = secret

    if code == "ERROR":
        await update.message.reply_text(
            "❌ 2FA Key সঠিক নয়! আবার চেষ্টা করুন।\n"
            "_(সঠিক Base32 secret key দিন)_",
            parse_mode="Markdown"
        )
        return TT_WAIT_2FA

    await update.message.reply_text(
        f"✅ আপনার 2FA কোড: `{code}`\n\n"
        "এই কোডটি TikTok এ দিয়ে 2FA confirm করুন।\n\n"
        "🔔 এরপর যেই ইমেল দিয়ে একাউন্ট করেছেন ওই ইমেল টা দিন ❗",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return TT_WAIT_EMAIL

async def tt_wait_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if text == "Cancel ❌":
        await update.message.reply_text("🏠", reply_markup=home_keyboard())
        return ConversationHandler.END

    ctx.user_data["tt_email"] = text

    await update.message.reply_text(
        "🔔 অ্যাকাউন্ট খোলা শেষ হলে নিচের বাটনে চাপ দিন:",
        reply_markup=registered_keyboard()
    )
    return TT_WAIT_REGISTERED

async def tt_wait_registered(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if text == "Cancel ❌":
        ctx.user_data.clear()
        await update.message.reply_text("🏠", reply_markup=home_keyboard())
        return ConversationHandler.END

    if text == "Account Registered ✅":
        tt_user = ctx.user_data.get("tt_username", gen_username())
        tt_pass = get_setting("tt_password")
        twofa = ctx.user_data.get("tt_2fa_key", "")
        email = ctx.user_data.get("tt_email", "")

        cur.execute(
            "INSERT INTO tiktok_accounts (user_id, username, password, twofa_key, email, status, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (uid, tt_user, tt_pass, twofa, email, "pending", datetime.now().isoformat())
        )
        conn.commit()

        await update.message.reply_text(
            txt(uid,
                "✅ সাবমিট হয়েছে! রিভিউ পেন্ডিং। অ্যাপ্রুভ হলে টাকা যোগ হবে।",
                "✅ Submitted! Review pending. Balance will be added after approval."),
            reply_markup=home_keyboard()
        )
        ctx.user_data.clear()
        return ConversationHandler.END

    return TT_WAIT_REGISTERED

# ── Instagram: wait for 2FA button click, then secret key ──
async def insta_wait_2fa(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if text == "Cancel ❌":
        await update.message.reply_text("🏠", reply_markup=home_keyboard())
        return ConversationHandler.END

    if text == "2FA Set 📐":
        await update.message.reply_text(
            "🔑 এখন আপনার Instagram অ্যাকাউন্টের 2FA Secret Key পাঠান:\n\n"
            "_(2FA চালু করার সময় যে QR code বা text key পাবেন সেটা)_",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return INSTA_WAIT_2FA

    secret = text.strip().replace(" ", "")
    code = gen_totp(secret)
    ctx.user_data["insta_2fa_key"] = secret

    if code == "ERROR":
        await update.message.reply_text(
            "❌ 2FA Key সঠিক নয়! আবার চেষ্টা করুন।",
        )
        return INSTA_WAIT_2FA

    await update.message.reply_text(
        f"✅ আপনার 2FA কোড: `{code}`\n\n"
        "এই কোডটি Instagram এ দিয়ে 2FA confirm করুন।",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )

    # Save to DB
    insta_user = ctx.user_data.get("insta_username", gen_username())
    insta_pass = get_setting("insta_password")
    cur.execute(
        "INSERT INTO insta_accounts (user_id, username, password, twofa_key, status, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (uid, insta_user, insta_pass, secret, "pending", datetime.now().isoformat())
    )
    conn.commit()

    await update.message.reply_text(
        "🔔 অ্যাকাউন্ট খোলা শেষ হলে নিচের বাটনে চাপ দিন:",
        reply_markup=registered_keyboard()
    )
    return INSTA_WAIT_EMAIL

async def insta_wait_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if text == "Cancel ❌":
        ctx.user_data.clear()
        await update.message.reply_text("🏠", reply_markup=home_keyboard())
        return ConversationHandler.END

    if text == "Account Registered ✅":
        await update.message.reply_text(
            txt(uid,
                "✅ সাবমিট হয়েছে! রিভিউ পেন্ডিং। অ্যাপ্রুভ হলে টাকা যোগ হবে।",
                "✅ Submitted! Review pending. Balance will be added after approval."),
            reply_markup=home_keyboard()
        )
        ctx.user_data.clear()
        return ConversationHandler.END

    return INSTA_WAIT_EMAIL

# ─────────────────────────────────────────
# WITHDRAW FLOW
# ─────────────────────────────────────────
async def withdraw_addr(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    addr = update.message.text.strip()

    if addr == "Cancel ❌":
        await update.message.reply_text("🏠", reply_markup=home_keyboard())
        return ConversationHandler.END

    ctx.user_data["withdraw_addr"] = addr
    bal = get_balance(uid)
    bal_usdt = bal / USDT_RATE

    await update.message.reply_text(
        f"💰 আপনার ব্যালেন্স: *{bal:.4f}tk* ({bal_usdt:.6f} USDT)\n"
        f"📌 ফি: {FEE_USDT} USDT কাটা হবে\n"
        f"💱 1 USDT = {USDT_RATE}tk\n\n"
        f"কত টাকা উইথড্র করতে চান?\n_(সর্বনিম্ন {MIN_WITHDRAW_TK}tk)_",
        parse_mode="Markdown"
    )
    return WITHDRAW_AMOUNT

async def withdraw_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if text == "Cancel ❌":
        await update.message.reply_text("🏠", reply_markup=home_keyboard())
        return ConversationHandler.END

    try:
        amount_tk = float(text)
    except ValueError:
        await update.message.reply_text("❌ সংখ্যা দিন! যেমন: 50")
        return WITHDRAW_AMOUNT

    bal = get_balance(uid)
    if amount_tk < MIN_WITHDRAW_TK:
        await update.message.reply_text(f"❌ সর্বনিম্ন {MIN_WITHDRAW_TK}tk!")
        return WITHDRAW_AMOUNT
    if amount_tk > bal:
        await update.message.reply_text(f"❌ অপর্যাপ্ত ব্যালেন্স! আপনার: {bal:.4f}tk")
        return WITHDRAW_AMOUNT

    amount_usdt = (amount_tk / USDT_RATE) - FEE_USDT
    if amount_usdt <= 0:
        await update.message.reply_text("❌ ফি বাদে পরিমাণ শূন্য হয়ে যাচ্ছে!")
        return WITHDRAW_AMOUNT

    addr = ctx.user_data.get("withdraw_addr", "")
    cur.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount_tk, uid))
    cur.execute(
        "INSERT INTO withdrawals (user_id, address, amount_tk, amount_usdt, status, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (uid, addr, amount_tk, amount_usdt, "pending", datetime.now().isoformat())
    )
    conn.commit()

    user = update.effective_user
    uname = f"@{user.username}" if user.username else str(uid)
    await notify_admins(
        ctx.bot,
        f"💸 নতুন Withdraw Request!\n"
        f"👤 {user.full_name} ({uname})\n"
        f"💰 {amount_tk}tk → {amount_usdt:.6f} USDT\n"
        f"📍 Address: `{addr}`"
    )

    await update.message.reply_text(
        txt(uid,
            "✅ আপনার Withdraw টি ১-৬ ঘন্টার মধ্যে আপনার Wallet এ পাঠিয়ে দেওয়া হবে, ধন্যবাদ 💝",
            "✅ Your withdrawal will be processed within 1-6 hours. Thank you 💝"),
        reply_markup=home_keyboard()
    )
    ctx.user_data.clear()
    return ConversationHandler.END

# ─────────────────────────────────────────
# LANGUAGE FLOW
# ─────────────────────────────────────────
async def lang_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if "Bangla" in text or "🇧🇩" in text:
        cur.execute("UPDATE users SET language='bn' WHERE user_id=?", (uid,))
        conn.commit()
        await update.message.reply_text("✅ বাংলা সেট হয়েছে!", reply_markup=home_keyboard())
        return ConversationHandler.END
    elif "English" in text or "🇺🇸" in text:
        cur.execute("UPDATE users SET language='en' WHERE user_id=?", (uid,))
        conn.commit()
        await update.message.reply_text("✅ English set!", reply_markup=home_keyboard())
        return ConversationHandler.END

    await update.message.reply_text("⚠️ আবার বেছে নিন।", reply_markup=lang_keyboard())
    return LANG_SELECT

# ─────────────────────────────────────────
# ADMIN DECORATORS
# ─────────────────────────────────────────
def admin_only(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Access denied.")
            return
        return await func(update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper

def superadmin_only(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != SUPERADMIN_ID:
            await update.message.reply_text("❌ Access denied.")
            return
        return await func(update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper

# ─────────────────────────────────────────
# ADMIN COMMANDS
# ─────────────────────────────────────────
@admin_only
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE joined=1")
    verified = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM tiktok_accounts")
    tt_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM tiktok_accounts WHERE status='approved'")
    tt_approved = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM tiktok_accounts WHERE status='pending'")
    tt_pending = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM insta_accounts")
    insta_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM insta_accounts WHERE status='approved'")
    insta_approved = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM insta_accounts WHERE status='pending'")
    insta_pending = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
    pending_wd = cur.fetchone()[0]
    cur.execute("SELECT SUM(balance) FROM users")
    total_balance = cur.fetchone()[0] or 0

    await update.message.reply_text(
        f"📊 *Bot Statistics*\n\n"
        f"👥 Total Users: {total_users}\n"
        f"✅ Verified: {verified}\n\n"
        f"🎵 TikTok: {tt_total} total | ✅ {tt_approved} | ⏳ {tt_pending} pending\n"
        f"📸 Instagram: {insta_total} total | ✅ {insta_approved} | ⏳ {insta_pending} pending\n\n"
        f"💸 Pending Withdrawals: {pending_wd}\n"
        f"💰 Total User Balance: {total_balance:.4f}tk",
        parse_mode="Markdown"
    )

@admin_only
async def cmd_pass_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "🔑 *Password পরিবর্তন:*\n\n"
            "`/pass <password>` লিখুন — এটাই TikTok এবং Instagram দুই টাস্কের password হবে।",
            parse_mode="Markdown"
        )
        return

    val = " ".join(args)
    set_setting("tt_password", val)
    set_setting("insta_password", val)
    await update.message.reply_text(
        f"✅ Password আপডেট হয়েছে (TikTok + Instagram):\n`{val}`",
        parse_mode="Markdown"
    )

@admin_only
async def cmd_reviewtt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cur.execute(
        "SELECT id, username, user_id FROM tiktok_accounts WHERE status='pending' ORDER BY id"
    )
    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("📭 কোনো pending TikTok account নেই।")
        return

    ctx.user_data["tt_review"] = rows
    ctx.user_data["tt_review_idx"] = 0
    idx = 0
    acc_id, username, owner_uid = rows[idx]

    await update.message.reply_text(
        f"🎵 *TikTok Review* [{idx+1}/{len(rows)}]\n\n`{username}`",
        parse_mode="Markdown",
        reply_markup=review_keyboard(idx, "tt")
    )

@admin_only
async def cmd_reviewinsta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cur.execute(
        "SELECT id, username, user_id FROM insta_accounts WHERE status='pending' ORDER BY id"
    )
    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("📭 কোনো pending Instagram account নেই।")
        return

    ctx.user_data["insta_review"] = rows
    ctx.user_data["insta_review_idx"] = 0
    idx = 0
    acc_id, username, owner_uid = rows[idx]

    await update.message.reply_text(
        f"📸 *Instagram Review* [{idx+1}/{len(rows)}]\n\n`{username}`",
        parse_mode="Markdown",
        reply_markup=review_keyboard(idx, "insta")
    )

async def review_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    data = query.data  # e.g. rej_tt_0
    parts = data.split("_")
    action = parts[0]
    acc_type = parts[1]
    idx = int(parts[2])

    review_key = f"{acc_type}_review"
    rows = ctx.user_data.get(review_key, [])

    if not rows:
        await query.edit_message_text("⚠️ Session শেষ। কমান্ড আবার দিন।")
        return

    if idx >= len(rows):
        idx = len(rows) - 1

    acc_id, username, owner_uid = rows[idx]
    table = "tiktok_accounts" if acc_type == "tt" else "insta_accounts"
    label = "🎵 TikTok" if acc_type == "tt" else "📸 Instagram"
    reward = 3 if acc_type == "tt" else 4

    if action == "app":
        cur.execute(f"UPDATE {table} SET status='approved' WHERE id=?", (acc_id,))
        conn.commit()
        add_balance(owner_uid, reward)
        try:
            await ctx.bot.send_message(
                owner_uid,
                f"✅ আপনার {label} টাস্ক অ্যাপ্রুভ হয়েছে!\n"
                f"👤 Account: `{username}`\n"
                f"💰 +{reward}tk আপনার ব্যালেন্সে যোগ হয়েছে!",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        rows.pop(idx)
        ctx.user_data[review_key] = rows

    elif action == "rej":
        cur.execute(f"UPDATE {table} SET status='rejected' WHERE id=?", (acc_id,))
        conn.commit()
        try:
            await ctx.bot.send_message(
                owner_uid,
                f"❌ আপনার {label} টাস্ক রিজেক্ট হয়েছে।\n"
                f"👤 Account: `{username}`",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        rows.pop(idx)
        ctx.user_data[review_key] = rows

    elif action == "next":
        idx = min(idx + 1, len(rows) - 1)

    elif action == "prev":
        idx = max(idx - 1, 0)

    rows = ctx.user_data.get(review_key, [])
    if not rows:
        await query.edit_message_text(f"✅ সব {label} রিভিউ শেষ!")
        return

    if idx >= len(rows):
        idx = len(rows) - 1

    acc_id, username, owner_uid = rows[idx]
    await query.edit_message_text(
        f"{label} *Review* [{idx+1}/{len(rows)}]\n\n`{username}`",
        parse_mode="Markdown",
        reply_markup=review_keyboard(idx, acc_type)
    )

@admin_only
async def cmd_xltiktok(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cur.execute(
        "SELECT username, password, twofa_key, email FROM tiktok_accounts ORDER BY id"
    )
    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("📭 কোনো TikTok account নেই।")
        return

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TikTok Accounts"
    ws.append(["Username", "Password", "2FA Key", "Email"])
    for row in rows:
        ws.append(list(row))

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    await update.message.reply_document(
        document=buf,
        filename=f"tiktok_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        caption=f"🎵 TikTok Accounts — {len(rows)} টি"
    )

@admin_only
async def cmd_xlinsta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cur.execute(
        "SELECT username, password, twofa_key FROM insta_accounts ORDER BY id"
    )
    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("📭 কোনো Instagram account নেই।")
        return

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Instagram Accounts"
    ws.append(["Username", "Password", "2FA Key"])
    for row in rows:
        ws.append(list(row))

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    await update.message.reply_document(
        document=buf,
        filename=f"insta_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        caption=f"📸 Instagram Accounts — {len(rows)} টি"
    )

@admin_only
async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cur.execute("DELETE FROM tiktok_accounts")
    cur.execute("DELETE FROM insta_accounts")
    cur.execute("DELETE FROM withdrawals WHERE status='pending'")
    conn.commit()
    await update.message.reply_text(
        "✅ সব account এবং pending withdrawals clear হয়েছে।\n"
        "💰 User balance অক্ষত আছে।"
    )

@superadmin_only
async def cmd_toggle_bot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global BOT_ENABLED
    BOT_ENABLED = not BOT_ENABLED
    status = "✅ চালু" if BOT_ENABLED else "🔴 বন্ধ"
    await update.message.reply_text(f"🤖 Bot এখন {status}!")

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & filters.Regex(
                    "^(💰 Balance|📋 Tasks|📥 Withdraw|👤 Profile|🌎 Language|Support 🆘|ProxyBOT 🪀)$"
                ),
                handle_message
            ),
        ],
        states={
            TASK_SELECT:       [MessageHandler(filters.TEXT & ~filters.COMMAND, task_select)],
            TT_WAIT_2FA:       [MessageHandler(filters.TEXT & ~filters.COMMAND, tt_wait_2fa)],
            TT_WAIT_EMAIL:     [MessageHandler(filters.TEXT & ~filters.COMMAND, tt_wait_email)],
            TT_WAIT_REGISTERED:[MessageHandler(filters.TEXT & ~filters.COMMAND, tt_wait_registered)],
            INSTA_WAIT_2FA:    [MessageHandler(filters.TEXT & ~filters.COMMAND, insta_wait_2fa)],
            INSTA_WAIT_EMAIL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, insta_wait_email)],
            WITHDRAW_ADDR:     [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_addr)],
            WITHDRAW_AMOUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount)],
            LANG_SELECT:       [MessageHandler(filters.TEXT & ~filters.COMMAND, lang_select)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
        name="main_conv",
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(review_callback, pattern="^(rej|app|prev|next)_(tt|insta)_\\d+$"))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("pass", cmd_pass_handler))
    app.add_handler(CommandHandler("reviewtt", cmd_reviewtt))
    app.add_handler(CommandHandler("reviewinsta", cmd_reviewinsta))
    app.add_handler(CommandHandler("xltiktok", cmd_xltiktok))
    app.add_handler(CommandHandler("xlinsta", cmd_xlinsta))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("534757", cmd_toggle_bot))

    # Catch-all for unmatched home buttons outside conversation
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 Bot polling started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
