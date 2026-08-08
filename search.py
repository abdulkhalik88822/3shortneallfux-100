from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from ai_parser import parse_query
from database import get_all_movies
from difflib import get_close_matches

@Client.on_message(filters.text)
async def search(client, message):
    query = message.text.lower()

    parsed = parse_query(query)

    title_q = parsed["title"]
    year_q = parsed["year"]
    season_q = parsed["season"]
    episode_q = parsed["episode"]

    data = await get_all_movies()

    results = []
    all_titles = []

    for item in data:
        name = item['file_name'].lower()
        all_titles.append(name)

        score = 0

        if title_q in name:
            score += 50

        if year_q and year_q in name:
            score += 20

        if season_q:
            if f"s{season_q:02d}" in name:
                score += 20

        if episode_q:
            if f"e{episode_q:02d}" in name:
                score += 20

        if score > 0:
            results.append((score, item))

    results.sort(reverse=True, key=lambda x: x[0])

    if results:
        for score, r in results[:5]:
            caption = f"🎬 {r['file_name']}\n\n📥 Download below"

            buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬇️ Download", url=r.get("link", "https://t.me/your_channel"))]
            ])

            await message.reply_photo(
                photo=r.get("poster", "https://via.placeholder.com/300"),
                caption=caption,
                reply_markup=buttons
            )
    else:
        suggestions = get_close_matches(title_q, all_titles, n=5, cutoff=0.5)

        if suggestions:
            text = "❌ No result\n\n🤖 Did you mean:\n"
            for s in suggestions:
                text += f"• {s}\n"
            await message.reply(text)
        else:
            await message.reply("❌ No result found")
