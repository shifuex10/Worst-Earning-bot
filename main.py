import json
import os
import re
import sys
import time
import threading
import urllib.request
import urllib.error

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    print("[✗] BOT_TOKEN not set!")
    sys.exit(1)

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

# chat_id → {"email": str, "seen_ids": set}
user_data: dict = {}
user_lock = threading.Lock()

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
        print(f"[✗] HTTP {e.code}: {e.read().decode()}")
    except Exception as e:
        print(f"[✗] POST error: {e}")
    return None


def _get_url(url: str, timeout: int = 10) -> dict | list | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                    "accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read())
    except Exception as e:
        print(f"[✗] GET error: {e}")
        return None


# ═══════════════════════════════════════════════════════
#  TELEGRAM SEND
# ═══════════════════════════════════════════════════════

MAIN_KB = {
    "keyboard": [[{"text": "📬 Generate Mail"}]],
    "resize_keyboard": True,
    "one_time_keyboard": False,
    "input_field_placeholder": "Tap Generate Mail…",
}

def send(chat_id, text: str) -> None:
    payload = {
        "chat_id":      chat_id,
        "text":         text,
        "parse_mode":   "HTML",
        "reply_markup": MAIN_KB,
    }
    r = _post("sendMessage", payload)
    if r and not r.get("ok"):
        print(f"[✗] sendMessage: {r.get('description')}")


# ═══════════════════════════════════════════════════════
#  TEMP-MAIL API
# ═══════════════════════════════════════════════════════

def create_email() -> tuple[str | None, str | None]:
    url  = "https://api.internal.temp-mail.io/api/v3/email/new"
    body = json.dumps({"min_name_length": 10, "max_name_length": 10}).encode()
    hdrs = {"Content-Type": "application/json",
            "accept": "application/json", "User-Agent": "Mozilla/5.0"}
    req  = urllib.request.Request(url, data=body, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            r = json.loads(res.read())
            return r["email"], r["token"]
    except Exception as e:
        print("[✗] create_email:", e)
        return None, None


def get_inbox(email: str) -> list:
    url = f"https://api.internal.temp-mail.io/api/v3/email/{email}/messages"
    r   = _get_url(url)
    return r if isinstance(r, list) else []


# ═══════════════════════════════════════════════════════
#  OTP EXTRACTOR
# ═══════════════════════════════════════════════════════

OTP_RE = [
    r"(?:otp|code|pin|passcode|verification[\s_-]?code|confirm(?:ation)?[\s_-]?code"
    r"|security[\s_-]?code|auth(?:entication)?[\s_-]?code"
    r"|one[\s_-]?time[\s_-]?(?:password|code))"
    r"[\s:：\-–—]+([0-9]{4,8})",
    r"is\s+([0-9]{5,8})\b",
    r"\b([0-9]{6})\b",
    r"\b([0-9]{4,8})\b",
]

def extract_otp(text: str) -> str | None:
    if not text:
        return None
    lower = text.lower()
    for pat in OTP_RE:
        m = re.search(pat, lower)
        if m:
            return m.group(1)
    return None


# ═══════════════════════════════════════════════════════
#  INBOX WATCHER  (runs in background thread per user)
# ═══════════════════════════════════════════════════════

def watch_inbox(chat_id: int, email: str, seen_ids: set):
    """
    Polls inbox every 5 sec forever.
    Stops automatically when user generates a new email
    (user_data[chat_id]["email"] no longer matches this email).
    """
    print(f"[→] Watching inbox for {email}")
    while True:
        time.sleep(5)

        # Stop if user switched to a new email
        with user_lock:
            current = user_data.get(chat_id, {})
        if current.get("email") != email:
            print(f"[←] Stopped watching {email}")
            return

        try:
            messages = get_inbox(email)
        except Exception:
            continue

        for msg in messages:
            msg_id = msg.get("id") or msg.get("_id") or str(msg)
            if msg_id in seen_ids:
                continue
            seen_ids.add(msg_id)

            body    = msg.get("body_text", "") or ""
            subject = msg.get("subject", "")   or ""
            otp     = extract_otp(subject + "\n" + body)

            if otp:
                text = (
                    "🔰 <b>Your OTP Received</b>\n\n"
                    f"📧 Email: <code>{email}</code>\n"
                    f"🔑 OTP: <code>{otp}</code>"
                )
            else:
                text = (
                    "📨 <b>New Mail Received</b>\n\n"
                    f"📧 Email: <code>{email}</code>\n"
                    "⚠️ No OTP/code found in this email."
                )
            send(chat_id, text)


# ═══════════════════════════════════════════════════════
#  ACTIONS
# ═══════════════════════════════════════════════════════

def action_start(chat_id: int):
    send(chat_id,
         "👋 <b>Welcome to Temp Mail Bot!</b>\n\n"
         "🔒 Get a disposable inbox instantly.\n"
         "🔑 OTP codes are auto-extracted and sent to you.\n"
         "🔄 Generate new mail anytime — old mail is replaced.\n\n"
         "👇 Tap <b>📬 Generate Mail</b> to start!")


def action_generate(chat_id: int):
    send(chat_id, "⏳ Generating your email…")
    email, token = create_email()

    if not email:
        send(chat_id, "❌ Failed to generate email. Please try again.")
        return

    seen_ids: set = set()

    # Save immediately — old watcher thread will detect change and stop
    with user_lock:
        # Pre-load existing inbox so we don't re-notify old mails
        existing = get_inbox(email)
        for m in existing:
            seen_ids.add(m.get("id") or m.get("_id") or str(m))

        user_data[chat_id] = {"email": email, "token": token}

    send(chat_id,
         f"✅ <b>Email Generated!</b>\n\n"
         f"📧 <code>{email}</code>\n\n"
         "👆 Tap to copy. Watching for incoming mail…")

    # Start background watcher thread
    t = threading.Thread(target=watch_inbox,
                         args=(chat_id, email, seen_ids),
                         daemon=True)
    t.start()


# ═══════════════════════════════════════════════════════
#  MESSAGE HANDLER
# ═══════════════════════════════════════════════════════

def handle_message(message: dict):
    chat_id = message["chat"]["id"]
    text    = message.get("text", "").strip()

    if text == "/start":
        action_start(chat_id)
    elif text == "📬 Generate Mail":
        action_generate(chat_id)
    # ignore everything else silently


# ═══════════════════════════════════════════════════════
#  SKIP OLD UPDATES ON STARTUP
# ═══════════════════════════════════════════════════════

def skip_pending() -> int | None:
    try:
        url = API_URL + "getUpdates?offset=-1&timeout=0"
        with urllib.request.urlopen(url, timeout=10) as res:
            data = json.loads(res.read())
        results = data.get("result", [])
        if results:
            offset = results[-1]["update_id"] + 1
            print(f"[i] Skipped old updates. Starting from offset={offset}")
            return offset
    except Exception as e:
        print(f"[✗] skip_pending: {e}")
    return None


# ═══════════════════════════════════════════════════════
#  MAIN POLLING LOOP
# ═══════════════════════════════════════════════════════

def main():
    print("🤖 Bot is running…")
    last_id = skip_pending()

    while True:
        try:
            params = f"?offset={last_id}&timeout=30" if last_id else "?timeout=30"
            url    = API_URL + "getUpdates" + params
            data   = _get_url(url, timeout=35)

            if not data:
                continue

            for update in data.get("result", []):
                last_id = update["update_id"] + 1
                if "message" in update:
                    # Handle each message in its own thread → never blocks polling
                    threading.Thread(
                        target=handle_message,
                        args=(update["message"],),
                        daemon=True,
                    ).start()

        except Exception as e:
            print(f"[✗] Main loop error: {e}")
            time.sleep(3)


if __name__ == "__main__":
    main()
