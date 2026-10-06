import os
import re
import asyncio
import threading
from flask import Flask
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# --- Environment Variables ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
TARGET_CHANNEL = os.environ.get("TARGET_CHANNEL", "klyx_news")
DEFAULT_BOT = os.environ.get("TARGET_BOT", "klyxx_bot")

app = Flask(__name__)

@app.route('/')
def home():
    return "Ultra Hybrid Sniper is Running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

processed_posts = set()
processed_codes = set()

async def send_log(text):
    try:
        await client.send_message('me', text, parse_mode='html')
    except Exception as e:
        print(f"[!] Saved Messages Error: {e}")

async def send_code_to_bot(code):
    if code in processed_codes:
        return
    processed_codes.add(code)

    cmd = f"/start promo_{code}"
    try:
        await client.send_message(DEFAULT_BOT, cmd)
        await send_log(
            f"⚡ <b>ইনস্ট্যান্ট কোড ফায়ার করা হয়েছে!</b>\n"
            f"🤖 বট: @{DEFAULT_BOT}\n"
            f"📋 কমান্ড: <code>{cmd}</code>\n"
            f"🔑 কোড: <code>{code}</code>"
        )
    except Exception as e:
        await send_log(f"⚠️ বটে কোড পাঠাতে এরর: {e}")

async def click_buttons(message):
    if not message.buttons:
        return False

    for row in message.buttons:
        for btn in row:
            btn_name = btn.text
            url = getattr(btn, 'url', None)

            if url:
                if ('t.me/' in url or 'telegram.me/' in url) and 'start=' in url:
                    try:
                        domain = 'telegram.me/' if 'telegram.me/' in url else 't.me/'
                        clean_part = url.split(domain)[1]
                        bot_target = clean_part.split('?')[0]
                        start_param = clean_part.split('start=')[1].split('&')[0]

                        # প্যারাম অলরেডি পাঠানো হয়ে থাকলে দ্বিতীয়বার পাঠাবে না
                        if start_param in processed_codes:
                            return True
                        processed_codes.add(start_param)

                        await client.send_message(bot_target, f"/start {start_param}")
                        await send_log(
                            f"✅ <b>বাটন ডিপ-লিংক অ্যাক্টিভ!</b>\n"
                            f"🤖 বট: @{bot_target}\n"
                            f"🔘 বাটন: <b>{btn_name}</b>\n"
                            f"🔑 প্যারাম: <code>{start_param}</code>"
                        )
                        return True
                    except Exception as err:
                        await send_log(f"⚠️️ বাটনের ডিপ-লিংকে সমস্যা: {err}")
                else:
                    await send_log(f"🔗 <b>ওয়েব URL বাটন:</b> {btn_name}\n🌐 লিংক: {url}")
                    return True
            else:
                try:
                    await btn.click()
                    await send_log(
                        f"🎉 <b>বাটনে সফলভাবে ক্লিক করা হয়েছে!</b>\n"
                        f"🔘 বাটন: <b>{btn_name}</b>\n"
                        f"📝 পোস্ট আইডি: <code>{message.id}</code>"
                    )
                    return True
                except Exception as err:
                    await send_log(f"⚠️ বাটন ক্লিকে এরর: {err}")
    return False

@client.on(events.NewMessage(chats=TARGET_CHANNEL))
async def handle_new_post(event):
    msg = event.message
    post_text = msg.raw_text or ""
    print(f"\n[⚡ NEW POST] ID: {msg.id}")

    # ১. টেক্সটে কোড থাকলে শুধু কোড পাঠাবে (একবারই)
    code_match = re.search(r'Code:\s*([A-Za-z0-9_-]+)', post_text, re.IGNORECASE)
    if code_match:
        promo_code = code_match.group(1).strip()
        processed_posts.add(msg.id)
        await send_code_to_bot(promo_code)
        return  # বাটন ক্লিক বাদ দিয়ে এখানেই শেষ করবে

    # ২. টেক্সটে কোড না থাকলে বাটন ক্লিক করবে (যেমন গিভঅ্যাওয়ে)
    if msg.buttons:
        processed_posts.add(msg.id)
        await click_buttons(msg)

@client.on(events.MessageEdited(chats=TARGET_CHANNEL))
async def handle_edited_post(event):
    msg = event.message
    if msg.id in processed_posts:
        return

    if msg.buttons:
        print(f"[*] মেসেজ এডিট হয়ে বাটন এসেছে (ID: {msg.id}), বাটন ক্লিক হচ্ছে...")
        if await click_buttons(msg):
            processed_posts.add(msg.id)

async def main():
    print("[*] টেলিগ্রামে কানেক্ট হচ্ছে...")
    await client.start()
    me = await client.get_me()
    welcome_text = (
        f"🚀 <b>Single-Shot Ultra Sniper চালু হয়েছে!</b>\n"
        f"👤 অ্যাকাউন্ট: <b>{me.first_name}</b>\n"
        f"🎯 মনিটর চ্যানেল: <code>{TARGET_CHANNEL}</code>\n"
        f"🤖 টার্গেট বট: <code>@{DEFAULT_BOT}</code>\n"
        f"⚡ <i>ডুপ্লিকেট রিকোয়েস্ট সম্পূর্ণ বন্ধ করা হয়েছে।</i>"
    )
    print(welcome_text)
    await send_log(welcome_text)
    await client.run_until_disconnected()

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
