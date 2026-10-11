import os
import re
import time
import asyncio
import threading
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from flask import Flask
from telethon import TelegramClient, events, utils
from telethon.errors import FloodWaitError, BotResponseTimeoutError
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateStatusRequest
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
MAX_ACCOUNTS = 10

TARGET_CHANNELS = [
    c.strip()
    for c in os.environ.get("TARGET_CHANNELS", "klyx_news").split(",")
    if c.strip()
]
DEFAULT_BOT = os.environ.get("TARGET_BOT", "klyxx_bot")
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", 0.8))
ONLINE_INTERVAL = float(os.environ.get("ONLINE_INTERVAL", 25))
FIRE_STAGGER = float(os.environ.get("FIRE_STAGGER_MS", 0)) / 1000
LOCAL_TZ = timezone(timedelta(hours=float(os.environ.get("TZ_OFFSET_HOURS", 6))))

CODE_PATTERN = re.compile(r'Code:\s*([A-Za-z0-9_-]+)', re.IGNORECASE)
DEEP_LINK_PATTERN = re.compile(r'(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)\?(?:[^#\s]*&)?start=([^&#\s]+)')

Plan = namedtuple("Plan", "kind bot payload chat_id msg_id data label")

app = Flask(__name__)


@app.route('/')
def home():
    return "Ultra-Fast Shared-Dispatch Sniper Running!"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def load_accounts():
    accounts = []
    for index in range(1, MAX_ACCOUNTS + 1):
        suffix = "" if index == 1 else f"_{index}"
        session = os.environ.get(f"SESSION_STRING{suffix}", "")
        if not session:
            continue
        api_id = int(os.environ.get(f"API_ID{suffix}") or API_ID)
        api_hash = os.environ.get(f"API_HASH{suffix}") or API_HASH
        accounts.append((f"Account-{index}", session, api_id, api_hash))
    return accounts


def build_plan(msg):
    match = CODE_PATTERN.search(msg.raw_text or "")
    if match:
        return Plan("command", DEFAULT_BOT, f"promo_{match.group(1)}", msg.chat_id, msg.id, None, None)

    buttons = msg.buttons
    if not buttons:
        return None

    for row in buttons:
        for btn in row:
            url = getattr(btn, 'url', None)
            if url:
                link = DEEP_LINK_PATTERN.search(url)
                if link:
                    return Plan("command", link.group(1), link.group(2), msg.chat_id, msg.id, None, btn.text)
                continue
            if btn.data is not None:
                return Plan("callback", None, None, msg.chat_id, msg.id, btn.data, btn.text)

    return None


class Hub:
    def __init__(self):
        self.workers = []
        self.claimed = set()

    def register(self, worker):
        self.workers.append(worker)

    async def run_worker(self, index, worker, plan, info):
        if index and FIRE_STAGGER > 0:
            await asyncio.sleep(index * FIRE_STAGGER)
        return await worker.execute(plan, info)

    async def handle(self, detector, msg, source):
        key = (msg.chat_id, msg.id)
        if key in self.claimed:
            return

        plan = build_plan(msg)
        if plan is None:
            return
        self.claimed.add(key)

        is_edit = source.endswith("edit")
        info = {
            "detector": detector.name,
            "source": source,
            "perf": time.perf_counter(),
            "seen_at": time.time(),
            "label": "Edited" if is_edit else "Posted",
            "event_time": msg.edit_date if is_edit and msg.edit_date else msg.date,
            "msg_id": msg.id,
        }

        results = await asyncio.gather(
            *(self.run_worker(i, w, plan, info) for i, w in enumerate(self.workers))
        )
        if not any(results):
            self.claimed.discard(key)


HUB = Hub()


class SniperWorker:
    def __init__(self, name, session, api_id, api_hash, poll_offset):
        self.name = name
        self.poll_offset = poll_offset
        self.client = TelegramClient(
            StringSession(session),
            api_id,
            api_hash,
            connection_retries=None,
            retry_delay=1,
            auto_reconnect=True,
        )
        self.client.flood_sleep_threshold = 0
        self.fired_payloads = set()
        self.tasks = set()
        self.channel_entities = {}
        self.entities_by_chat = {}

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

    async def click_callback(self, plan):
        peer = self.entities_by_chat.get(plan.chat_id)
        if peer is None:
            self.log(f"⚠️ No channel entity available for chat {plan.chat_id}")
            return None

        try:
            await self.client(
                GetBotCallbackAnswerRequest(peer=peer, msg_id=plan.msg_id, data=plan.data)
            )
        except BotResponseTimeoutError:
            pass
        except FloodWaitError as err:
            self.log(f"⏳ Flood wait: {err.seconds}s")
            return None
        except Exception as err:
            self.log(f"⚠️ Button click error ({plan.label}): {err}")
            return None

        return f"Clicked button <b>{plan.label}</b>"

    async def execute(self, plan, info):
        try:
            if plan.kind == "command":
                result = await self.fire(plan.bot, plan.payload)
            else:
                result = await self.click_callback(plan)
        except Exception as err:
            self.log(f"⚠️ Execution error: {err}")
            return False

        if not result:
            return False

        action_ms = (time.perf_counter() - info["perf"]) * 1000
        lag = info["seen_at"] - info["event_time"].timestamp()
        self.log(
            f"✅ {result}\n"
            f"🔎 Detected by: {info['detector']} ({info['source']})\n"
            f"🕒 {info['label']}: {info['event_time'].astimezone(LOCAL_TZ):%H:%M:%S}\n"
            f"📥 Seen: {datetime.fromtimestamp(info['seen_at'], LOCAL_TZ):%H:%M:%S} (up to +{lag:.1f}s)\n"
            f"⚡ Detection to action: {action_ms:.0f} ms\n"
            f"📝 Post ID: <code>{info['msg_id']}</code>"
        )
        return True

    async def on_new(self, event):
        await HUB.handle(self, event.message, "push_new")

    async def on_edit(self, event):
        await HUB.handle(self, event.message, "push_edit")

    async def keep_online(self):
        while True:
            try:
                await self.client(UpdateStatusRequest(offline=False))
            except FloodWaitError as err:
                await asyncio.sleep(err.seconds)
            except Exception as err:
                print(f"[!] {self.name} keep_online warn: {err}")
            await asyncio.sleep(ONLINE_INTERVAL)

    async def fast_channel_tracker(self, channel):
        entity = self.channel_entities.get(channel)
        if not entity:
            return

        last_id = 0
        while last_id == 0:
            try:
                msgs = await self.client.get_messages(entity, limit=1)
                if not msgs:
                    break
                last_id = msgs[0].id
            except FloodWaitError as err:
                print(f"[!] {self.name} tracker init flood wait: {err.seconds}s")
                await asyncio.sleep(err.seconds + 1)
            except Exception as err:
                print(f"[!] {self.name} tracker init error ({channel}): {err}")
                await asyncio.sleep(2)

        await asyncio.sleep(self.poll_offset)

        while True:
            await asyncio.sleep(POLL_INTERVAL)
            try:
                msgs = await self.client.get_messages(entity, limit=1)
                if not msgs:
                    continue

                latest_msg = msgs[0]
                if latest_msg.id > last_id:
                    last_id = latest_msg.id
                    self.spawn(HUB.handle(self, latest_msg, "fast_tracker"))

            except FloodWaitError as err:
                await asyncio.sleep(err.seconds + 1)
                continue
            except Exception as err:
                print(f"[!] {self.name} tracker error ({channel}): {err}")
                await asyncio.sleep(2)
                continue

    async def warm_up(self):
        for target in TARGET_CHANNELS:
            try:
                entity = await self.client.get_input_entity(target)
                self.channel_entities[target] = entity
                self.entities_by_chat[utils.get_peer_id(entity)] = entity
            except Exception as err:
                print(f"[!] {self.name} entity error ({target}): {err}")

        try:
            await self.client.get_input_entity(DEFAULT_BOT)
        except Exception as err:
            print(f"[!] {self.name} entity error ({DEFAULT_BOT}): {err}")

    async def start(self):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            print(f"[-] {self.name}: session invalid, skipping this account")
            await self.client.disconnect()
            return

        me = await self.client.get_me()
        await self.warm_up()

        self.client.add_event_handler(self.on_new, events.NewMessage(chats=TARGET_CHANNELS))
        self.client.add_event_handler(self.on_edit, events.MessageEdited(chats=TARGET_CHANNELS))

        HUB.register(self)

        for channel in TARGET_CHANNELS:
            self.spawn(self.fast_channel_tracker(channel))

        self.spawn(self.keep_online())

        dc_id = self.client.session.dc_id
        print(f"[+] {self.name} armed and ready: {me.first_name} (home DC {dc_id})")

        await self.send_log(
            f"⚡ <b>Shared-Dispatch Sniper Armed!</b>\n"
            f"👤 User: <b>{me.first_name}</b>\n"
            f"🌍 Home DC: <b>{dc_id}</b>\n"
            f"🎯 Channels: <code>{', '.join(TARGET_CHANNELS)}</code>\n"
            f"🔄 Tracker interval: {POLL_INTERVAL}s (offset {self.poll_offset:.2f}s)\n"
            f"🟢 Keep-Online interval: {ONLINE_INTERVAL}s\n"
            f"⏱ Fire stagger: {FIRE_STAGGER * 1000:.0f} ms per account"
        )
        await self.client.run_until_disconnected()


async def main():
    accounts = load_accounts()
    if not accounts:
        print("[-] No valid sessions found!")
        return

    count = len(accounts)
    workers = [
        SniperWorker(name, session, api_id, api_hash, POLL_INTERVAL * index / count).start()
        for index, (name, session, api_id, api_hash) in enumerate(accounts)
    ]

    results = await asyncio.gather(*workers, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            print(f"[!] Worker exception: {result}")


if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
