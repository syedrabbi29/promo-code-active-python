import os
import re
import time
import asyncio
import threading
from datetime import datetime, timedelta, timezone
from flask import Flask
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, BotResponseTimeoutError
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateStatusRequest
from telethon.tl.functions.help import GetConfigRequest

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")

ACCOUNTS = [
    (
        "Account-1",
        os.environ.get("SESSION_STRING", ""),
        API_ID,
        API_HASH,
    ),
    (
        "Account-2",
        os.environ.get("SESSION_STRING_2", ""),
        int(os.environ.get("API_ID_2") or API_ID),
        os.environ.get("API_HASH_2") or API_HASH,
    ),
]

TARGET_CHANNELS = [
    c.strip()
    for c in os.environ.get("TARGET_CHANNELS", "klyx_news,my_test_promo_channel").split(",")
    if c.strip()
]
DEFAULT_BOT = os.environ.get("TARGET_BOT", "klyxx_bot")

ONLINE_INTERVAL = float(os.environ.get("ONLINE_INTERVAL", 25))
LOCAL_TZ = timezone(timedelta(hours=float(os.environ.get("TZ_OFFSET_HOURS", 6))))

CODE_PATTERN = re.compile(r'Code:\s*([A-Za-z0-9_-]+)', re.IGNORECASE)
DEEP_LINK_PATTERN = re.compile(r'(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)\?(?:[^#\s]*&)?start=([^&#\s]+)')

app = Flask(__name__)

@app.route('/')
def home():
    return "Ultra-Responsive Dual-Account Sniper Running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


class SniperWorker:
    def __init__(self, name, session, api_id, api_hash):
        self.name = name
        self.client = TelegramClient(
            StringSession(session),
            api_id,
            api_hash,
            connection_retries=None,
            retry_delay=1,
            auto_reconnect=True
        )
        self.client.flood_sleep_threshold = 0
        self.processed_posts = set()
        self.fired_payloads = set()
        self.tasks = set()

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def send_log(self, text):
        try:
            await self.client.send_message('me', f"[{self.name}]\n{text}", parse_mode='html')
        except Exception as err:
            print(f"[!] {self.name} log error: {err}")

    def log(self, text):
        self.spawn(self.send_log(text))

    async def fire(self, bot, payload):
        key = (bot.lower(), payload)
        if key in self.fired_payloads:
            return f"Already sent <code>/start {payload}</code>"
        self.fired_payloads.add(key)

        cmd = f"/start {payload}"
        try:
            # ইনস্ট্যান্ট কমান্ড ফায়ার
            await self.client.send_message(bot, cmd)
        except FloodWaitError as err:
            self.fired_payloads.discard(key)
            self.log(f"⏳ Flood wait: {err.seconds}s")
            return None
        except Exception as err:
            self.fired_payloads.discard(key)
            self.log(f"⚠️ Bot fire error: {err}")
            return None

        return f"Sent <code>{cmd}</code> to @{bot}"

    async def click_buttons(self, message):
        buttons = message.buttons
        if not buttons:
            return None

        for row in buttons:
            for btn in row:
                url = getattr(btn, 'url', None)
                if url:
                    match = DEEP_LINK_PATTERN.search(url)
                    if match:
                        result = await self.fire(match.group(1), match.group(2))
                        if result:
                            return result
                    continue

                if btn.data is None:
                    continue

                try:
                    await btn.click()
                except BotResponseTimeoutError:
                    pass
                except FloodWaitError as err:
                    self.log(f"⏳ Flood wait: {err.seconds}s")
                    return None
                except Exception as err:
                    self.log(f"⚠️ Click error: {err}")
                    continue

                return f"Clicked button <b>{btn.text}</b>"

        return None

    async def process_msg(self, msg, source):
        key = (msg.chat_id, msg.id)
        if key in self.processed_posts:
            return
        self.processed_posts.add(key)

        seen_at = time.time()
        started = time.perf_counter()

        result = None
        match = CODE_PATTERN.search(msg.raw_text or "")
        if match:
            result = await self.fire(DEFAULT_BOT, f"promo_{match.group(1)}")
        
        if not result and msg.buttons:
            result = await self.click_buttons(msg)

        if not result:
            self.processed_posts.discard(key)
            return

        action_ms = (time.perf_counter() - started) * 1000
        event_time = msg.edit_date if source == "edit" and msg.edit_date else msg.date
        lag = seen_at - event_time.timestamp()
        label = "Edited" if source == "edit" else "Posted"
        
        # সফল হওয়ার পর ব্যাকগ্রাউন্ডে লগ পাঠানো
        self.log(
            f"✅ {result}\n"
            f"📡 Source: {source}\n"
            f"🕒 {label}: {event_time.astimezone(LOCAL_TZ):%H:%M:%S}\n"
            f"📥 Seen: {datetime.fromtimestamp(seen_at, LOCAL_TZ):%H:%M:%S} (+{lag:.1f}s)\n"
            f"⚡ Action took: {action_ms:.0f} ms\n"
            f"📝 Post ID: <code>{msg.id}</code>"
        )

    async def keep_online(self):
        """কানেকশন সক্রিয় ও হাই-প্রায়োরিটি রাখার লুপ"""
        while True:
            try:
                # টেলিগ্রামের মূল সার্ভারে পিং পাঠিয়ে অনলাইন স্ট্যাটাস রিনিউ করা
                await self.client(UpdateStatusRequest(offline=False))
                await self.client(GetConfigRequest())  # লাইভ কানেকশন সকেট ওয়ার্ম রাখা
            except FloodWaitError as err:
                await asyncio.sleep(err.seconds)
            except Exception as err:
                print(f"[!] {self.name} keep_online warn: {err}")
            await asyncio.sleep(ONLINE_INTERVAL)

    async def warm_up(self):
        for target in TARGET_CHANNELS + [DEFAULT_BOT]:
            try:
                await self.client.get_input_entity(target)
            except Exception as err:
                print(f"[!] {self.name} warm-up error ({target}): {err}")

    async def start(self):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            print(f"[-] {self.name}: Session invalid/expired!")
            await self.client.disconnect()
            return

        me = await self.client.get_me()
        await self.warm_up()

        # কানেকশন তৈরি হওয়ার পরই ইভেন্ট রেজিস্টার করা
        self.client.add_event_handler(lambda e: self.process_msg(e.message, "new"), events.NewMessage(chats=TARGET_CHANNELS))
        self.client.add_event_handler(lambda e: self.process_msg(e.message, "edit"), events.MessageEdited(chats=TARGET_CHANNELS))

        print(f"[+] {self.name} Connected & Armed: {me.first_name}")

        # ব্যাকগ্রাউন্ডে অনলাইন স্ট্যাটাস চালু
        self.spawn(self.keep_online())

        await self.send_log(
            f"🚀 <b>Sniper Active & Online!</b>\n"
            f"👤 User: <b>{me.first_name}</b>\n"
            f"🎯 Channels: <code>{', '.join(TARGET_CHANNELS)}</code>\n"
            f"🤖 Target: <code>@{DEFAULT_BOT}</code>"
        )
        await self.client.run_until_disconnected()


async def main():
    workers = [
        SniperWorker(name, session, api_id, api_hash).start()
        for name, session, api_id, api_hash in ACCOUNTS
        if session
    ]

    if not workers:
        print("[-] No valid sessions found!")
        return

    results = await asyncio.gather(*workers, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            print(f"[!] Worker exception: {result}")


if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
