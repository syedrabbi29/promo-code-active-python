import os
import asyncio
import threading
from flask import Flask
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# --- Environment Variables থেকে ডাটা লোড ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
TARGET_CHANNEL = os.environ.get("TARGET_CHANNEL", "")

# --- Render ওয়েব সার্ভিস সচল রাখতে Flask ব্যাকগ্রাউন্ড সার্ভার ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# --- Telethon ক্লায়েন্ট ---
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

async def send_log(text):
    """Saved Messages-এ তাৎক্ষণিক নোটিফিকেশন পাঠানো"""
    try:
        await client.send_message('me', text, parse_mode='html')
    except Exception as e:
        print(f"[!] Saved Messages Error: {e}")

@client.on(events.NewMessage(chats=TARGET_CHANNEL))
async def handle_post(event):
    msg = event.message
    post_snippet = (msg.raw_text or "মিডিয়া বা টেক্সট ছাড়া পোস্ট")[:120]
    
    print(f"\n[⚡ NEW POST] ID: {msg.id}")
    await send_log(f"⚡ <b>নতুন পোস্ট পাওয়া গেছে!</b>\n\n📝 <i>{post_snippet}...</i>")

    # যদি পোস্টের সাথে বাটন থাকে
    if msg.buttons:
        action_taken = False
        for row in msg.buttons:
            for btn in row:
                btn_name = btn.text
                btn_url = getattr(btn, 'url', None)

                # কেইস ১: লিংক বাটন (বট ডিপ-লিংক)
                if btn_url and 't.me/' in btn_url and 'start=' in btn_url:
                    try:
                        clean_url = btn_url.split('t.me/')[1]
                        bot_target = clean_url.split('?')[0]
                        start_code = clean_url.split('start=')[1].split('&')[0]
                        
                        await client.send_message(bot_target, f"/start {start_code}")
                        await send_log(
                            f"✅ <b>বট ডিপ-লিংক অ্যাক্টিভ করা হয়েছে!</b>\n"
                            f"🤖 বট: @{bot_target}\n"
                            f"🔑 প্যারাম: <code>{start_code}</code>"
                        )
                        action_taken = True
                    except Exception as err:
                        await send_log(f"⚠️ ডিপ-লিংক পাঠাতে সমস্যা: {err}")

                # কেইস ২: ইনলাইন কলব্যাক বাটন (সরাসরি ক্লিক)
                elif not btn_url:
                    try:
                        await btn.click()
                        await send_log(f"✅ <b>বাটনে ক্লিক সম্পন্ন!</b>\n🔘 বাটন: <b>{btn_name}</b>")
                        action_taken = True
                    except Exception as err:
                        await send_log(f"⚠️ বাটন ক্লিকে ব্যর্থ: {err}")

                if action_taken:
                    break
            if action_taken:
                break

async def start_bot():
    print("[*] Telegram Client চালু হচ্ছে...")
    await client.start()
    
    me = await client.get_me()
    welcome_msg = (
        f"🚀 <b>Promo Bot সফলভাবে লাইভ হয়েছে!</b>\n"
        f"👤 অ্যাকাউন্ট: <b>{me.first_name}</b>\n"
        f"🎯 মনিটর চ্যানেল: <code>{TARGET_CHANNEL}</code>"
    )
    print(welcome_msg)
    await send_log(welcome_msg)
    
    await client.run_until_disconnected()

if __name__ == '__main__':
    # Flask সার্ভার ব্যাকগ্রাউন্ড থ্রেডে রান রাখা
    threading.Thread(target=run_flask, daemon=True).start()
    # মূল লুপে টেলিগ্রাম লিসেনার চালানো
    asyncio.run(start_bot())
