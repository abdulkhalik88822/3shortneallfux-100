"""Compatibility health module.

The bot's actual aiohttp web server is started from bot.py.
"""

def health():
    return {"status": "ok"}
