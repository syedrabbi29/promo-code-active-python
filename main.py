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


def clean_name(value):
    value = value.strip()
    value = re.sub(r'^(https?://)?(t\.me|telegram\.me)/', '', value)
    return value.split('?')[0].lstrip('@').strip('/')


def parse_names(env_name, default):
    names = []
    for item in os.environ.get(env_name, default).split(','):
        name = clean_name(item)
        if name and name.lower() not in [n.lower() for n in names]:
            names.append(name)
    return names


TARGET_CHANNELS = parse_names("TARGET_CHANNELS", "klyx_news")
DEFAULT_BOT = clean_name(os.environ.get("TARGET_BOT", "klyxx_bot"))

GIVEAWAY_CHANNELS = parse_names("GIVEAWAY_CHANNELS", "smartupdate011,lolololo0172")
GIVEAWAY_BOTS = parse_names("GIVEAWAY_BOTS", "MoneyPlugGiveawayBot")
GIVEAWAY_CHANNELS_LOWER = {c.lower() for c in GIVEAWAY_CHANNELS}
GIVEAWAY_BOTS_LOWER = {b.lower() for b in GIVEAWAY_BOTS}
GIVEAWAY_CHAT_IDS = set()

WATCH_CHANNELS = TARGET_CHANNELS + [
    c for c in GIVEAWAY_CHANNELS if c.lower() not in {t.lower() for t in TARGET_CHANNELS}
]

POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", 0.8))
POLLERS_PER_CHANNEL = int(os.environ.get("POLLERS_PER_CHANNEL", 0))
ONLINE_INTERVAL = float(os.environ.get("ONLINE_INTERVAL", 25))
FIRE_STAGGER = float(os.environ.get("FIRE_STAGGER_MS", 0)) / 1000
WALLET_COOLDOWN = float(os.environ.get("WALLET_COOLDOWN", 8))
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
        wallet = os.environ.get(f"GRAM_ADDRESS{suffix}", "").strip()
        accounts.append((f"Account-{index}", session, api_id, api_hash, wallet))
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


def build_giveaway_plan(msg):
    buttons = msg.buttons
    if not buttons:
        return None

    for row in buttons:
        for btn in row:
            url = getattr(btn, 'url', None)
            if not url:
                continue
            link = DEEP_LINK_PATTERN.search(url)
            if link and link.group(1).lower() in GIVEAWAY_BOTS_LOWER:
                return Plan("giveaway", link.group(1), link.group(2), msg.chat_id, msg.id, None, btn.text)

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

        if msg.chat_id in GIVEAWAY_CHAT_IDS:
            plan = build_giveaway_plan(msg)
        else:
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
    def __init__(self, name, session, api_id, api_hash, wallet, index, count):
        self.name = name
        self.wallet = wallet
        self.index = index
        self.count = count
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
        self.wallet_prompts = set()
        self.last_wallet_sent = {}
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

    async def fire(self, bot, payload, unique=None):
        key = (bot.lower(), payload, unique)
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
            if plan.kind == "callback":
                result = await self.click_callback(plan)
            else:
                unique = plan.msg_id if plan.kind == "giveaway" else None
                result = await self.fire(plan.bot, plan.payload, unique)
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

    async def on_bot_message(self, event):
        text = (event.raw_text or "").lower()

        if "sorry" in text and "slots" in text:
            self.log("😞 All giveaway slots were already reserved")
            return

        if "wallet address" in text and "send your" in text:
            await self.send_wallet(event)

    async def send_wallet(self, event):
        if not self.wallet:
            self.log("⚠️ Giveaway asked for a wallet address but no GRAM_ADDRESS is set for this account")
            return

        prompt_key = (event.chat_id, event.id)
        if prompt_key in self.wallet_prompts:
            return
        self.wallet_prompts.add(prompt_key)

        if time.time() - self.last_wallet_sent.get(event.chat_id, 0) < WALLET_COOLDOWN:
            return

        try:
            await event.respond(self.wallet)
        except FloodWaitError as err:
            self.log(f"⏳ Flood wait while sending wallet: {err.seconds}s")
            return
        except Exception as err:
            self.log(f"⚠️ Failed to send wallet address: {err}")
            return

        self.last_wallet_sent[event.chat_id] = time.time()
        self.log("💳 <b>Wallet address sent to the giveaway bot</b>")

    async def keep_online(self):
        while True:
            try:
                await self.client(UpdateStatusRequest(offline=False))
            except FloodWaitError as err:
                await asyncio.sleep(err.seconds)
            except Exception as err:
                print(f"[!] {self.name} keep_online warn: {err}")
            await asyncio.sleep(ONLINE_INTERVAL)

    def poll_offset_for(self, channel_index):
        pollers = POLLERS_PER_CHANNEL if 0 < POLLERS_PER_CHANNEL < self.count else self.count
        slot = (self.index - channel_index) % self.count
        if slot >= pollers:
            return None
        return POLL_INTERVAL * slot / pollers

    async def fast_channel_tracker(self, channel, offset):
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

        await asyncio.sleep(offset)

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
        for target in WATCH_CHANNELS:
            try:
                entity = await self.client.get_input_entity(target)
                chat_id = utils.get_peer_id(entity)
                self.channel_entities[target] = entity
                self.entities_by_chat[chat_id] = entity
                if target.lower() in GIVEAWAY_CHANNELS_LOWER:
                    GIVEAWAY_CHAT_IDS.add(chat_id)
            except Exception as err:
                print(f"[!] {self.name} entity error ({target}): {err}")

        for bot in [DEFAULT_BOT] + GIVEAWAY_BOTS:
            try:
                await self.client.get_input_entity(bot)
            except Exception as err:
                print(f"[!] {self.name} entity error ({bot}): {err}")

    async def start(self):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            print(f"[-] {self.name}: session invalid, skipping this account")
            await self.client.disconnect()
            return

        me = await self.client.get_me()
        await self.warm_up()

        self.client.add_event_handler(self.on_new, events.NewMessage(chats=WATCH_CHANNELS))
        self.client.add_event_handler(self.on_edit, events.MessageEdited(chats=WATCH_CHANNELS))
        if GIVEAWAY_BOTS:
            self.client.add_event_handler(
                self.on_bot_message,
                events.NewMessage(incoming=True, from_users=GIVEAWAY_BOTS),
            )

        HUB.register(self)

        polled = []
        for channel_index, channel in enumerate(WATCH_CHANNELS):
            offset = self.poll_offset_for(channel_index)
            if offset is None:
                continue
            polled.append(channel)
            self.spawn(self.fast_channel_tracker(channel, offset))

        self.spawn(self.keep_online())

        dc_id = self.client.session.dc_id
        print(f"[+] {self.name} armed and ready: {me.first_name} (home DC {dc_id})")
        if not self.wallet:
            print(f"[!] {self.name}: no GRAM_ADDRESS set, giveaway payouts will not be requested")

        await self.send_log(
            f"⚡ <b>Shared-Dispatch Sniper Armed!</b>\n"
            f"👤 User: <b>{me.first_name}</b>\n"
            f"🌍 Home DC: <b>{dc_id}</b>\n"
            f"🎯 Promo channels: <code>{', '.join(TARGET_CHANNELS)}</code>\n"
            f"🎁 Giveaway channels: <code>{', '.join(GIVEAWAY_CHANNELS) or '-'}</code>\n"
            f"🤖 Giveaway bots: <code>{', '.join(GIVEAWAY_BOTS) or '-'}</code>\n"
            f"🔄 Polling: {', '.join(polled) or '-'} every {POLL_INTERVAL}s\n"
            f"🟢 Keep-Online interval: {ONLINE_INTERVAL}s\n"
            f"💳 Wallet: {'set' if self.wallet else 'missing'}\n"
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
        SniperWorker(name, session, api_id, api_hash, wallet, index, count).start()
        for index, (name, session, api_id, api_hash, wallet) in enumerate(accounts)
    ]

    results = await asyncio.gather(*workers, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            print(f"[!] Worker exception: {result}")


if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
