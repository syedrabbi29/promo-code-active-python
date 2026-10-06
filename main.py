import os
import re
import asyncio
import threading
from flask import Flask
from telethon import TelegramClient, events
from telethon.sessions import StringSession

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
TARGET_CHANNEL = os.environ.get("TARGET_CHANNEL", "")

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

async def send_log(text):
    try:
        await client.send_message('me', text, parse_mode='html')
    except Exception as e:
        print(f"[!] Saved Messages Error: {e}")

@client.on(events.NewMessage(chats=TARGET_CHANNEL))
async def handle_post(event):
    msg = event.message
    raw_text = msg.raw_text or ""
    print(f"\n[⚡ NEW POST] ID: {msg.id}")

    action_done = False

    # ১. বাটন চেক করা
    if msg.buttons:
        print("[*] বাটনে ক্লিক করার চেষ্টা চলছে...")
        for row in msg.buttons:
            for btn in row:
                btn_name = btn.text
                btn_url = getattr(btn, 'url', None)

                # কেইস ক: লিংক বাটন
                if btn_url:
                    print(f"[+] লিংক বাটন: {btn_name} -> {btn_url}")
                    # t.me অথবা telegram.me লিংক
                    if ('t.me/' in btn_url or 'telegram.me/' in btn_url) and 'start=' in btn_url:
                        try:
                            domain = 'telegram.me/' if 'telegram.me/' in btn_url else 't.me/'
                            clean_part = btn_url.split(domain)[1]
                            bot_target = clean_part.split('?')[0]
                            start_code = clean_part.split('start=')[1].split('&')[0]

                            await client.send_message(bot_target, f"/start {start_code}")
                            await send_log(
                                f"✅ <b>বট ডিপ-লিংক অ্যাক্টিভ করা হয়েছে!</b>\n"
                                f"🤖 বট: @{bot_target}\n"
                                f"🔑 কোড: <code>{start_code}</code>"
                            )
                            action_done = True
                            break
                        except Exception as err:
                            await send_log(f"⚠️ বটে মেসেজ পাঠাতে ব্যর্থ: {err}")

                # কেইস খ: সাধারণ ইনলাইন বাটন (যার কোনো URL নেই)
                elif not btn_url:
                    try:
                        await btn.click()
                        await send_log(f"✅ <b>ইনলাইন বাটনে ক্লিক সম্পন্ন!</b>\n🔘 বাটন: <b>{btn_name}</b>")
                        action_done = True
                        break
                    except Exception as err:
                        await send_log(f"⚠️ বাটনে ক্লিক ব্যর্থ: {err}")

            if action_done:
                break

    # ২. যদি কোনো বাটন না পাওয়া যায় বা বাটনে কাজ না হয় (মেসেজের ভেতরের লিংক খোঁজা)
    if not action_done:
        # মেসেজ টেক্সটের ভেতরে কোনো t.me লিংক আছে কি না খোঁজা
        match = re.search(r'(?:https?://)?(?:t|telegram)\.me/([a-zA-Z0-9_]+)\?start=([a-zA-Z0-9_-]+)', raw_text)
        if match:
            bot_target = match.group(1)
            start_code = match.group(2)
            try:
                await client.send_message(bot_target, f"/start {start_code}")
                await send_log(
                    f"✅ <b>টেক্সট লিংক থেকে কোড অ্যাক্টিভ করা হয়েছে!</b>\n"
                    f"🤖 বট: @{bot_target}\n"
                    f"🔑 কোড: <code>{start_code}</code>"
                )
                action_done = True
            except Exception as err:
                await send_log(f"⚠️ টেক্সট লিংকের বটে মেসেজ পাঠাতে সমস্যা: {err}")

    # ৩. যদি বাটনে বা টেক্সটে কোনো অ্যাকশনই নেওয়া না যায়
    if not action_done:
        await send_log(
            f"ℹ️ <b>পোস্টে কোনো ক্লিকযোগ্য বাটন বা স্টার্ট-লিংক পাওয়া যায়নি!</b>\n"
            f"মেসেজ প্রিভিউ:\n<code>{raw_text[:200]}</code>"
        )

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
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(start_bot())
