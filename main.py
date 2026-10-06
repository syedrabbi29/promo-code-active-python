import os
import re
import asyncio
import threading
from flask import Flask
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, BotResponseTimeoutError
from telethon.sessions import StringSession

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
client.flood_sleep_threshold = 0

CODE_PATTERN = re.compile(r'Code:\s*([A-Za-z0-9_-]+)', re.IGNORECASE)
DEEP_LINK_PATTERN = re.compile(r'(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)\?(?:[^#\s]*&)?start=([^&#\s]+)')

processed_posts = set()
fired_payloads = set()


async def send_log(text):
    try:
        await client.send_message('me', text, parse_mode='html')
    except Exception as e:
        print(f"[!] Saved Messages Error: {e}")


def log(text):
    asyncio.create_task(send_log(text))


async def fire(bot, payload):
    key = (bot.lower(), payload)
    if key in fired_payloads:
        return True
    fired_payloads.add(key)

    cmd = f"/start {payload}"
    try:
        await client.send_message(bot, cmd)
    except FloodWaitError as err:
        fired_payloads.discard(key)
        log(f"⏳ ফ্লাড ওয়েট: {err.seconds} সেকেন্ড অপেক্ষা করতে বলেছে")
        return False
    except Exception as err:
        fired_payloads.discard(key)
        log(f"⚠️ বটে কমান্ড পাঠাতে এরর: {err}")
        return False

    log(
        f"⚡ <b>কমান্ড ফায়ার করা হয়েছে!</b>\n"
        f"🤖 বট: @{bot}\n"
        f"📋 কমান্ড: <code>{cmd}</code>"
    )
    return True


async def click_buttons(message):
    buttons = message.buttons
    if not buttons:
        return False

    for row in buttons:
        for btn in row:
            url = getattr(btn, 'url', None)

            if url:
                match = DEEP_LINK_PATTERN.search(url)
                if match:
                    if await fire(match.group(1), match.group(2)):
                        return True
                else:
                    log(f"🔗 <b>ওয়েব URL বাটন:</b> {btn.text}\n🌐 লিংক: {url}")
                continue

            if btn.data is None:
                continue

            try:
                await btn.click()
            except BotResponseTimeoutError:
                pass
            except FloodWaitError as err:
                log(f"⏳ ফ্লাড ওয়েট: {err.seconds} সেকেন্ড অপেক্ষা করতে বলেছে")
                return False
            except Exception as err:
                log(f"⚠️ বাটন ক্লিকে এরর: {err}")
                continue

            log(
                f"🎉 <b>বাটনে ক্লিক করা হয়েছে!</b>\n"
                f"🔘 বাটন: <b>{btn.text}</b>\n"
                f"📝 পোস্ট আইডি: <code>{message.id}</code>"
            )
            return True

    return False


async def process_buttons(message):
    if message.id in processed_posts:
        return
    processed_posts.add(message.id)
    if not await click_buttons(message):
        processed_posts.discard(message.id)


@client.on(events.NewMessage(chats=TARGET_CHANNEL))
async def handle_new_post(event):
    msg = event.message
    if msg.id in processed_posts:
        return

    match = CODE_PATTERN.search(msg.raw_text or "")
    if match:
        processed_posts.add(msg.id)
        if await fire(DEFAULT_BOT, f"promo_{match.group(1).strip()}"):
            return
        processed_posts.discard(msg.id)

    if msg.buttons:
        await process_buttons(msg)


@client.on(events.MessageEdited(chats=TARGET_CHANNEL))
async def handle_edited_post(event):
    msg = event.message
    if msg.id in processed_posts:
        return
    if msg.buttons:
        await process_buttons(msg)


async def warm_up():
    for target in (TARGET_CHANNEL, DEFAULT_BOT):
        try:
            await client.get_input_entity(target)
        except Exception as err:
            print(f"[!] Warm-up error ({target}): {err}")


async def main():
    print("[*] টেলিগ্রামে কানেক্ট হচ্ছে...")
    await client.start()
    me = await client.get_me()
    await warm_up()
    welcome_text = (
        f"🚀 <b>Ultra Hybrid Sniper চালু হয়েছে!</b>\n"
        f"👤 অ্যাকাউন্ট: <b>{me.first_name}</b>\n"
        f"🎯 মনিটর চ্যানেল: <code>{TARGET_CHANNEL}</code>\n"
        f"🤖 টার্গেট বট: <code>@{DEFAULT_BOT}</code>"
    )
    print(welcome_text)
    await send_log(welcome_text)
    await client.run_until_disconnected()


if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
