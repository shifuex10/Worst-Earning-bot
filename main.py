import json
import os
import sys
import urllib.request
import urllib.error
import time

# ─────────────────────────────────────────
#  CONFIG — Railway environment variable
# ─────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    print("[✗] ERROR: BOT_TOKEN environment variable is not set!")
    print("    → Railway dashboard → Variables → Add BOT_TOKEN")
    sys.exit(1)

API_URL   = f"https://api.telegram.org/bot{BOT_TOKEN}/"
user_data: dict = {}

print(f"[✓] BOT_TOKEN loaded from environment.")

# ═══════════════════════════════════════════════════════════
#  LOW-LEVEL HTTP HELPERS
# ═══════════════════════════════════════════════════════════

def _post(endpoint: str, payload: dict) -> dict | None:
    url     = API_URL + endpoint
    data    = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    req     = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[✗] HTTP {e.code}: {e.reason} → {body}")
    except Exception as e:
        print(f"[✗] Request error: {e}")
    return None


def _get(endpoint: str, params: str = "") -> dict:
    url = API_URL + endpoint + params
    try:
        with urllib.request.urlopen(url) as res:
            return json.loads(res.read())
    except Exception as e:
        print(f"[✗] GET error: {e}")
        return {}


# ═══════════════════════════════════════════════════════════
#  SEND HELPERS
# ═══════════════════════════════════════════════════════════

def send_message(
    chat_id,
    text: str,
    inline_buttons=None,
    reply_keyboard=None,
    remove_keyboard: bool = False,
):
    payload = {
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "MarkdownV2",
    }

    if inline_buttons:
        payload["reply_markup"] = {"inline_keyboard": inline_buttons}
    elif reply_keyboard:
        payload["reply_markup"] = {
            "keyboard":                reply_keyboard,
            "resize_keyboard":         True,
            "one_time_keyboard":       False,
            "input_field_placeholder": "Choose an option…",
        }
    elif remove_keyboard:
        payload["reply_markup"] = {"remove_keyboard": True}

    result = _post("sendMessage", payload)
    if result and not result.get("ok"):
        print(f"[✗] sendMessage failed: {result.get('description')}")


def answer_callback(callback_id: str, text: str = "", alert: bool = False):
    _post("answerCallbackQuery", {
        "callback_query_id": callback_id,
        "text":              text,
        "show_alert":        alert,
    })


# ═══════════════════════════════════════════════════════════
#  BUTTON FACTORIES  (API 9.4 colored InlineKeyboardButton)
# ═══════════════════════════════════════════════════════════

def _ib(text: str, cb: str, color: str = "default") -> dict:
    return {"text": text, "callback_data": cb, "color": color}


MAIN_INLINE_KB = [
    [_ib("📧  Generate Email", "generate",   color="primary")],
    [_ib("📬  Inbox",          "inbox",      color="default")],
    [_ib("🗑  Delete Email",   "delete",     color="destructive")],
    [_ib("📊  Statistics",     "statistics", color="default")],
]

MAIN_REPLY_KB = [
    [{"text": "📧 Generate", "color": "primary"},
     {"text": "📬 Inbox",    "color": "default"}],
    [{"text": "🗑 Delete",   "color": "destructive"},
     {"text": "📊 Stats",    "color": "default"}],
]

def email_action_kb() -> list:
    return [
        [_ib("📬  Check Inbox",  "inbox",    color="primary"),
         _ib("🔄  Regenerate",   "generate", color="default")],
        [_ib("🗑  Delete Email", "delete",   color="destructive")],
        [_ib("🏠  Back to Menu", "menu",     color="default")],
    ]


# ═══════════════════════════════════════════════════════════
#  TEMP-MAIL API
# ═══════════════════════════════════════════════════════════

def create_email() -> tuple[str | None, str | None]:
    url  = "https://api.internal.temp-mail.io/api/v3/email/new"
    body = json.dumps({"min_name_length": 10, "max_name_length": 10}).encode()
    hdrs = {"Content-Type": "application/json",
            "accept": "application/json", "User-Agent": "Mozilla/5.0"}
    req  = urllib.request.Request(url, data=body, headers=hdrs)
    try:
        with urllib.request.urlopen(req) as res:
            r = json.loads(res.read())
            return r["email"], r["token"]
    except Exception as e:
        print("[✗] create_email:", e)
        return None, None


def get_inbox(email: str) -> list:
    url  = f"https://api.internal.temp-mail.io/api/v3/email/{email}/messages"
    hdrs = {"accept": "application/json", "User-Agent": "Mozilla/5.0"}
    req  = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read())
    except Exception as e:
        print("[✗] get_inbox:", e)
        return []


# ═══════════════════════════════════════════════════════════
#  ESCAPE HELPER FOR MarkdownV2
# ═══════════════════════════════════════════════════════════

_ESC = str.maketrans({c: f"\\{c}" for c in r"\_*[]()~`>#+-=|{}.!"})

def esc(text: str) -> str:
    return str(text).translate(_ESC)


# ═══════════════════════════════════════════════════════════
#  UPDATE HANDLERS
# ═══════════════════════════════════════════════════════════

def handle_command(message: dict):
    chat_id = message["chat"]["id"]
    text    = message.get("text", "")

    reply_map = {
        "📧 Generate": "generate",
        "📬 Inbox":    "inbox",
        "🗑 Delete":   "delete",
        "📊 Stats":    "statistics",
    }
    if text in reply_map:
        _dispatch_action(chat_id, reply_map[text])
        return

    if text == "/start":
        welcome = (
            "👋 Welcome to *Temp Mail Bot*\\!\n\n"
            "🔒 _Your private, disposable inbox — right inside Telegram\\._\n\n"
            "Use the buttons below or the keyboard at the bottom\\."
        )
        send_message(chat_id, welcome,
                     inline_buttons=MAIN_INLINE_KB,
                     reply_keyboard=MAIN_REPLY_KB)

    elif text == "/help":
        help_text = (
            "📖 *Commands*\n\n"
            f"• /start — {esc('Show main menu')}\n"
            f"• /email — {esc('Generate a new temp email')}\n"
            f"• /inbox — {esc('Check your inbox')}\n"
            f"• /delete — {esc('Delete current email')}\n"
            f"• /stats — {esc('Show bot statistics')}\n"
        )
        send_message(chat_id, help_text)

    elif text == "/email":
        _dispatch_action(chat_id, "generate")
    elif text == "/inbox":
        _dispatch_action(chat_id, "inbox")
    elif text == "/delete":
        _dispatch_action(chat_id, "delete")
    elif text == "/stats":
        _dispatch_action(chat_id, "statistics")


def handle_callback(callback: dict):
    chat_id     = callback["message"]["chat"]["id"]
    action      = callback["data"]
    callback_id = callback["id"]

    answer_callback(callback_id)
    _dispatch_action(chat_id, action)


def _dispatch_action(chat_id, action: str):
    user = user_data.get(chat_id)

    if action == "menu":
        send_message(chat_id, "🏠 *Main Menu*", inline_buttons=MAIN_INLINE_KB)

    elif action == "generate":
        send_message(chat_id, "⏳ _Generating your email\\.\\.\\._")
        email, token = create_email()
        if email:
            user_data[chat_id] = {"email": email, "token": token}
            msg = (
                f"✅ *Email Generated\\!*\n\n"
                f"📧 `{esc(email)}`\n\n"
                f"_Tap the email to copy it\\._"
            )
            send_message(chat_id, msg, inline_buttons=email_action_kb())
        else:
            send_message(chat_id, "❌ Failed to generate email\\. Try again\\.")

    elif action == "inbox":
        if not user:
            send_message(chat_id,
                         "⚠️ No email yet\\! Tap *Generate Email* first\\.",
                         inline_buttons=[[_ib("📧 Generate", "generate", "primary")]])
            return
        send_message(chat_id, "📬 _Fetching inbox\\.\\.\\._")
        messages = get_inbox(user["email"])
        if messages:
            for i, msg in enumerate(messages, 1):
                sender  = esc(msg.get("from",      "Unknown"))
                subject = esc(msg.get("subject",   "No Subject"))
                body    = esc(msg.get("body_text", "[No Body]")[:800])
                mail_text = (
                    f"📨 *Message {i}*\n"
                    f"👤 From: {sender}\n"
                    f"📌 Subject: {subject}\n"
                    f"─────────────────\n"
                    f"{body}"
                )
                send_message(chat_id, mail_text)
        else:
            send_message(chat_id,
                         "📭 *Inbox is empty\\.* Waiting for messages\\.",
                         inline_buttons=[[_ib("🔄 Refresh", "inbox", "primary")]])

    elif action == "delete":
        if chat_id in user_data:
            old_email = esc(user_data[chat_id]["email"])
            del user_data[chat_id]
            send_message(chat_id,
                         f"🗑 *Email Deleted\\!*\n\n`{old_email}` has been removed\\.",
                         inline_buttons=[[_ib("📧 Generate New", "generate", "primary")]])
        else:
            send_message(chat_id, "⚠️ You don't have an active email to delete\\.")

    elif action == "statistics":
        total = len(user_data)
        bar   = "🟩" * min(total, 10) + "⬜" * max(0, 10 - total)
        stats_text = (
            f"📊 *Bot Statistics*\n\n"
            f"👥 Active emails: `{total}`\n"
            f"{bar}\n\n"
            f"_Each session stores one temp email\\._"
        )
        send_message(chat_id, stats_text,
                     inline_buttons=[[_ib("🔄 Refresh Stats", "statistics", "default")]])


# ═══════════════════════════════════════════════════════════
#  POLLING LOOP
# ═══════════════════════════════════════════════════════════

def get_updates(offset=None) -> dict:
    params = f"?offset={offset}&timeout=30" if offset else "?timeout=30"
    return _get("getUpdates", params)


def main():
    last_id = None
    print("🤖 Bot is running…")
    while True:
        try:
            updates = get_updates(last_id)
            for update in updates.get("result", []):
                last_id = update["update_id"] + 1
                if "message" in update:
                    handle_command(update["message"])
                elif "callback_query" in update:
                    handle_callback(update["callback_query"])
        except Exception as e:
            print(f"[✗] Main loop error: {e}")
            time.sleep(5)  # wait before retry on crash
        time.sleep(1)


if __name__ == "__main__":
    main()
