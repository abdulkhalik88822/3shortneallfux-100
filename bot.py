from pyrogram import Client, __version__, filters
from pyrogram.raw.all import layer
from database.ia_filterdb import Media, ensure_indexes
from database.users_chats_db import db
from info import API_ID, API_HASH, ADMINS, BOT_TOKEN, LOG_CHANNEL, PORT, SUPPORT_GROUP
from utils import temp
from typing import Union, Optional, AsyncGenerator
from pyrogram import types
from Script import script 
from datetime import date, datetime 
import datetime
import pytz
from aiohttp import web
from plugins import web_server, check_expired_premium
from plugins.route import set_bot
import asyncio
import time

class Bot(Client):
    def __init__(self):
        super().__init__(
            name='aks',
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            sleep_threshold=5,
            workers=150,
            plugins={"root": "plugins"}
        )
        
    async def start(self):
        st = time.time()
        await super().start()

        # Make HTTP health endpoint available as early as possible so Koyeb
        # health checks do not fail while DB/index startup work continues.
        set_bot(self)
        self._web_runner = web.AppRunner(await web_server())
        await self._web_runner.setup()
        await web.TCPSite(self._web_runner, "0.0.0.0", PORT).start()

        # Non-critical DB state should not delay the web health endpoint.
        try:
            b_users, b_chats = await db.get_banned()
            temp.BANNED_USERS = b_users
            temp.BANNED_CHATS = b_chats
        except Exception as exc:
            print(f"Banned-list startup warning: {exc}")
            temp.BANNED_USERS = []
            temp.BANNED_CHATS = []

        await ensure_indexes()
        me = await self.get_me()
        temp.ME = me.id
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name
        temp.B_LINK = me.mention
        self.username = '@' + me.username

        self.loop.create_task(check_expired_premium(self))
        # Long historical indexing is background + Mongo-checkpointed. If Koyeb
        # restarts the instance, pending jobs resume automatically.
        try:
            from plugins.index import resume_pending_index_jobs
            self.loop.create_task(resume_pending_index_jobs(self))
        except Exception as exc:
            print(f"Index auto-resume setup warning: {exc}")

        print(f"{me.first_name} is started now ❤️")
        tz = pytz.timezone('Asia/Kolkata')
        today = date.today()
        now = datetime.datetime.now(tz)
        timee = now.strftime("%H:%M:%S %p")

        # Notification failures must never kill the bot process.
        async def safe_send(chat_id, text):
            try:
                await self.send_message(chat_id=chat_id, text=text)
            except Exception as exc:
                print(f"Startup notification warning for {chat_id}: {exc}")

        await safe_send(LOG_CHANNEL, f"<b>{me.mention} ʀᴇsᴛᴀʀᴛᴇᴅ 🤖\n\n📆 ᴅᴀᴛᴇ - <code>{today}</code>\n🕙 ᴛɪᴍᴇ - <code>{timee}</code>\n🌍 ᴛɪᴍᴇ ᴢᴏɴᴇ - <code>Asia/Kolkata</code></b>")
        await safe_send(SUPPORT_GROUP, f"<b>{me.mention} ʀᴇsᴛᴀʀᴛᴇᴅ 🤖</b>")
        tt = time.time() - st
        seconds = int(datetime.timedelta(seconds=tt).seconds)
        for admin in ADMINS:
            await safe_send(admin, f"<b>✅ ʙᴏᴛ ʀᴇsᴛᴀʀᴛᴇᴅ\n🕥 ᴛɪᴍᴇ ᴛᴀᴋᴇɴ - <code>{seconds} sᴇᴄᴏɴᴅs</code></b>")

    async def stop(self, *args):
        try:
            from plugins.index import shutdown_index_client
            await shutdown_index_client()
        except Exception:
            pass
        try:
            runner = getattr(self, "_web_runner", None)
            if runner:
                await runner.cleanup()
        except Exception:
            pass
        await super().stop()
        print("Bot stopped; saved index jobs will resume on next start.")
    
    # Safe batched iterator used by /index. get_messages is awaited; no async
    # generator is ever awaited here.
    async def iter_messages(
        self,
        chat_id: Union[int, str],
        limit: int,
        offset: int = 0,
    ) -> AsyncGenerator["types.Message", None]:
        current = max(1, int(offset or 1))
        last_id = max(current, int(limit))
        while current <= last_id:
            end = min(current + 199, last_id)
            ids = list(range(current, end + 1))
            try:
                messages = await self.get_messages(chat_id, ids)
                if not isinstance(messages, list):
                    messages = [messages]
                for message in messages:
                    if message is not None:
                        yield message
            except Exception as e:
                print(f"iter_messages error at {current}-{end}: {e}")
            current = end + 1


app = Bot()

if __name__ == "__main__":
    app.run()
