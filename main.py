
import asyncio
from pyrogram import Client
from config import API_ID, API_HASH, BOT_TOKEN
from handlers.start import register_start
from handlers.search import register_search
from handlers.callback import register_callback

app = Client(
    "advanced_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=50
)

def register_handlers(app):
    register_start(app)
    register_search(app)
    register_callback(app)

register_handlers(app)

if __name__ == "__main__":
    print("🚀 Bot is starting...")
    app.run()
