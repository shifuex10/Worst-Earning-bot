import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    print("[✗] ERROR: BOT_TOKEN environment variable not set!")
    sys.exit(1)

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

# chat_id → {"email": str, "token": str}
user_data: dict = {}

print("[✓] BOT_TOKEN loaded.")

# ═══════════════════════════════════════════════════════
#  HTTP HELPERS
# ═══════════════════════════════════════════════════════

def _post(endpoint: str, payload: dict) -> dict | None:
    url  = API_URL + endpoint
    data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    req  = urllib.request.Request(url, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[✗] HTTP {e.code}: {e.reason} → {body}")
    except Exception as e:
        print(f"[✗] POST error: {e}")
    return None


def _get(endpoint: str, params: str = "") -> dict:
    url = API_URL + endpoint + params
    try:
        with urllib.request.urlopen(url, timeout=30) as res:
            return json.loads(res.read())
    except Exception as e:
        print(f"[✗] GET error: {e}")
        return {}


# ═══════════════════════════════════════════════════════
#  SEND HELPERS
# ═══════════════════════════════════════════════════════

def send_message(chat_id, text: str, reply_keyboard=None):
    payload = {
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "MarkdownV2",
    }
    if reply_keyboard is not None:
        payload["reply_markup"] = {
            "keyboard":          reply_keyboard,
            "resize_keyboard":   True,
            "one_time_keyboard": False,
        }

    result = _post("sendMessage", payload)
    if result and not result.get("ok"):
        print(f"[✗] sendMessage failed: {result.get('description')}")
    return result


# ═══════════════════════════════════════════════════════
#  REPLY KEYBOARD  (persistent bottom keyboard)
# ═══════════════════════════════════════════════════════

MAIN_KB = [
    [{"text": "📬 Generate Mail"}],
]


# ═══════════════════════════════════════════════════════
#  MARKDOWNV2 ESCAPE
# ═══════════════════════════════════════════════════════

_ESC = str.maketrans({c: f"\\{c}" for c in r"\_*[]()~`>#+-=|{}.!"})

def esc(text: str) -> str:
    return str(text).translate(_ESC)


# ═══════════════════════════════════════════════════════
#  TEMP-MAIL API
# ═══════════════════════════════════════════════════════

def create_email() -> tuple[str | None, str | None]:
    url  = "https://api.internal.temp-mail.io/api/v3/email/new"
    body = json.dumps({"min_name_length": 10, "max_name_length": 10}).encode()
    hdrs = {
        "Content-Type": "application/json",
        "accept":       "application/json",
        "User-Agent":   "Mozilla/5.0",
    }
    req = urllib.request.Request(url, data=body, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
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
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.loads(res.read())
    except Exception as e:
        print("[✗] get_inbox:", e)
        return []


# ═══════════════════════════════════════════════════════
#  OTP EXTRACTOR
# ═══════════════════════════════════════════════════════

def extract_otp(text: str) -> str | None:
    patterns = [
        r"(?:otp|code|verification\s*code|confirm\s*code|one[- ]?time)[^\d]{0,30}(\d{4,8})",
        r"(\d{4,8})\s*(?:is your|as your|—|:)\s*(?:otp|code|password|pin)",
        r"\b(\d{6})\b",
        r"\b(\d{4,8})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


# ═══════════════════════════════════════════════════════
#  INBOX POLLER
# ═══════════════════════════════════════════════════════

def poll_and_notify(chat_id, email: str, max_wait: int = 90, interval: int = 5):
    seen_ids: set = set()
    deadline = time.time() + max_wait

    existing = get_inbox(email)
    for m in existing:
        seen_ids.add(m.get("id") or m.get("_id") or str(m))

    while time.time() < deadline:
        current = user_data.get(chat_id, {})
        if current.get("email") != email:
            print(f"[i] Stopped polling {email} — user switched email.")
            return

        time.sleep(interval)
        messages = get_inbox(email)

        for msg in messages:
            msg_id = msg.get("id") or msg.get("_id") or str(msg)
            if msg_id in seen_ids:
                continue

            seen_ids.add(msg_id)

            if user_data.get(chat_id, {}).get("email") != email:
                return

            body    = msg.get("body_text") or msg.get("body_html") or ""
            subject = msg.get("subject", "")
            full    = f"{subject} {body}"

            otp = extract_otp(full)

            if otp:
                text = (
                    f"🔰 *Your OTP Received*\n\n"
                    f"📧 Email: `{esc(email)}`\n"
                    f"🔑 OTP: `{esc(otp)}`"
                )
            else:
                preview = esc(body[:200].strip()) if body else esc(subject)
                text = (
                    f"📨 *New Mail Received*\n\n"
                    f"📧 Email: `{esc(email)}`\n"
                    f"📌 Subject: {esc(subject)}\n\n"
                    f"{preview}"
                )

            send_message(chat_id, text, reply_keyboard=MAIN_KB)
            return

    print(f"[i] Polling timeout for {email}")


# ═══════════════════════════════════════════════════════
#  ACTION: GENERATE MAIL
# ═══════════════════════════════════════════════════════

def action_generate(chat_id):
    # Delete old email from memory — old mails won't be delivered anymore
    if chat_id in user_data:
        del user_data[chat_id]

    send_message(chat_id, "⏳ _Generating your email\\.\\.\\._", reply_keyboard=MAIN_KB)

    email, token = create_email()
    if not email:
        send_message(
            chat_id,
            "❌ Failed to generate email\\. Please try again\\.",
            reply_keyboard=MAIN_KB,
        )
        return

    user_data[chat_id] = {"email": email, "token": token}

    msg = (
        f"✅ *New Email Generated\\!*\n\n"
        f"📧 `{esc(email)}`\n\n"
        f"_Tap the address above to copy it\\._\n"
        f"⏳ _Waiting for mail \\(90 sec\\)\\.\\.\\._"
    )
    send_message(chat_id, msg, reply_keyboard=MAIN_KB)

    # Block-poll for incoming messages
    poll_and_notify(chat_id, email)


# ═══════════════════════════════════════════════════════
#  MESSAGE HANDLER
# ═══════════════════════════════════════════════════════

def handle_message(message: dict):
    chat_id = message["chat"]["id"]
    text    = message.get("text", "").strip()

    if text == "/start":
        welcome = (
            "👋 *Welcome to Temp Mail Bot\\!*\n\n"
            "📬 Get a disposable email instantly\\.\n"
            "🔑 OTP codes are auto\\-extracted \\& sent to you\\.\n"
            "🔄 Generate new mail anytime — old mail is deleted automatically\\.\n\n"
            "Press the button below to get started\\! 👇"
        )
        send_message(chat_id, welcome, reply_keyboard=MAIN_KB)

    elif text == "📬 Generate Mail":
        action_generate(chat_id)

    else:
        send_message(
            chat_id,
            "👇 Press *📬 Generate Mail* to get a temp email\\.",
            reply_keyboard=MAIN_KB,
        )


# ═══════════════════════════════════════════════════════
#  POLLING LOOP
# ═══════════════════════════════════════════════════════

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
                    handle_message(update["message"])
        except Exception as e:
            print(f"[✗] Main loop error: {e}")
            time.sleep(5)
        time.sleep(1)


if __name__ == "__main__":
    main()
