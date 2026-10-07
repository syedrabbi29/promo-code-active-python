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

CODE_PATTERN = re.compile(r'Code:\s*([A-Za-z0-9_-]+)', re.IGNORECASE)
DEEP_LINK_PATTERN = re.compile(r'(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)\?(?:[^#\s]*&)?start=([^&#\s]+)')

app = Flask(__name__)


@app.route('/')
def home():
    return "Dual-Account Hybrid Sniper is Running 24/7!"


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
        )
        self.client.flood_sleep_threshold = 0
        self.processed_posts = set()
        self.fired_payloads = set()
        self.tasks = set()
        self.client.add_event_handler(self.on_post, events.NewMessage(chats=TARGET_CHANNELS))
        self.client.add_event_handler(self.on_post, events.MessageEdited(chats=TARGET_CHANNELS))

    async def send_log(self, text):
        try:
            await self.client.send_message('me', f"[{self.name}]\n{text}", parse_mode='html')
        except Exception as err:
            print(f"[!] {self.name} log error: {err}")

    def log(self, text):
        task = asyncio.create_task(self.send_log(text))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def fire(self, bot, payload):
        key = (bot.lower(), payload)
        if key in self.fired_payloads:
            return True
        self.fired_payloads.add(key)

        cmd = f"/start {payload}"
        try:
            await self.client.send_message(bot, cmd)
        except FloodWaitError as err:
            self.fired_payloads.discard(key)
            self.log(f"⏳ Flood wait: Telegram asked to wait {err.seconds}s")
            return False
        except Exception as err:
            self.fired_payloads.discard(key)
            self.log(f"⚠️ Failed to send command to bot: {err}")
            return False

        self.log(
            f"⚡ <b>Command fired!</b>\n"
            f"🤖 Bot: @{bot}\n"
            f"📋 Command: <code>{cmd}</code>"
        )
        return True

    async def click_buttons(self, message):
        buttons = message.buttons
        if not buttons:
            return False

        for row in buttons:
            for btn in row:
                url = getattr(btn, 'url', None)
                if url:
                    match = DEEP_LINK_PATTERN.search(url)
                    if match and await self.fire(match.group(1), match.group(2)):
                        return True
                    continue

                if btn.data is None:
                    continue

                try:
                    await btn.click()
                except BotResponseTimeoutError:
                    pass
                except FloodWaitError as err:
                    self.log(f"⏳ Flood wait: Telegram asked to wait {err.seconds}s")
                    return False
                except Exception as err:
                    self.log(f"⚠️ Button click error: {err}")
                    continue

                self.log(
                    f"🎉 <b>Button clicked!</b>\n"
                    f"🔘 Button: <b>{btn.text}</b>\n"
                    f"📝 Post ID: <code>{message.id}</code>"
                )
                return True

        return False

    async def process_msg(self, msg):
        key = (msg.chat_id, msg.id)
        if key in self.processed_posts:
            return
        self.processed_posts.add(key)

        match = CODE_PATTERN.search(msg.raw_text or "")
        if match and await self.fire(DEFAULT_BOT, f"promo_{match.group(1)}"):
            return

        if msg.buttons and await self.click_buttons(msg):
            return

        self.processed_posts.discard(key)

    async def on_post(self, event):
        await self.process_msg(event.message)

    async def warm_up(self):
        for target in TARGET_CHANNELS + [DEFAULT_BOT]:
            try:
                await self.client.get_input_entity(target)
            except Exception as err:
                print(f"[!] {self.name} warm-up error ({target}): {err}")

    async def start(self):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            print(f"[-] {self.name}: session is invalid or expired, skipping this account")
            await self.client.disconnect()
            return

        me = await self.client.get_me()
        await self.warm_up()
        print(f"[+] {self.name} connected as {me.first_name}")
        await self.send_log(
            f"🚀 <b>Sniper active!</b>\n"
            f"👤 User: <b>{me.first_name}</b>\n"
            f"🎯 Channels: <code>{', '.join(TARGET_CHANNELS)}</code>\n"
            f"🤖 Target bot: <code>@{DEFAULT_BOT}</code>"
        )
        await self.client.run_until_disconnected()


async def main():
    workers = [
        SniperWorker(name, session, api_id, api_hash).start()
        for name, session, api_id, api_hash in ACCOUNTS
        if session
    ]

    if not workers:
        print("[-] No session string found. Check your environment variables.")
        return

    results = await asyncio.gather(*workers, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            print(f"[!] Worker stopped with error: {result}")


if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
