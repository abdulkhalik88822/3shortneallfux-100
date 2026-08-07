import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from telegraph import upload_file
from utils import get_file_id

@Client.on_message(filters.command("telegraph") & filters.private)
async def telegraph(bot, update):
    replied = update.reply_to_message
    if not replied:
        await update.reply_text("⚠️ ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴘʜᴏᴛᴏ ᴏʀ ᴠɪᴅᴇᴏ ᴜɴᴅᴇʀ 5 ᴍʙ")
        return
    file_info = get_file_id(replied)
    if not file_info:
        await update.reply_text("ɴᴏᴛ sᴜᴘᴘᴏʀᴛᴇᴅ 😑")
        return
    msg = await update.reply_text(text="<code>ᴘʀᴏᴄᴇssɪɴɢ....</code>", disable_web_page_preview=True)   
    media = await update.reply_to_message.download()   
    d=await msg.edit_text("<code>ᴅᴏɴᴇ :)</code>", disable_web_page_preview=True) 
    await asyncio.sleep(2)
    await d.delete()
    try:
        response = upload_file(media)
    except Exception as error:
        print(error)
        await text.edit_text(text=f"Error :- {error}", disable_web_page_preview=True)       
        return    
    try:
        os.remove(media)
    except Exception as error:
        print(error)
        return    
    await update.reply_photo(
        photo=f'https://graph.org{response[0]}',
        caption=f"<b>ʏᴏᴜʀ ᴛᴇʟᴇɢʀᴀᴘʜ ʟɪɴᴋ ᴄᴏᴍᴘʟᴇᴛᴇᴅ 👇</b>\n\n<code>https://graph.org{response[0]}</code>\n\n<b>⭐️ ᴘᴏᴡᴇʀᴇᴅ ʙʏ:- @Illegal_Developer</b>",       
        reply_markup=InlineKeyboardMarkup( [[
            InlineKeyboardButton(text="✓ ᴏᴘᴇɴ ʟɪɴᴋ ✓", url=f"https://graph.org{response[0]}"),
            InlineKeyboardButton(text="📱 sʜᴀʀᴇ ʟɪɴᴋ", url=f"https://telegram.me/share/url?url=https://graph.org{response[0]}")
            ],[
            InlineKeyboardButton(text="❌ ᴄʟᴏsᴇ ❌", callback_data="close_data")
            ]])
    )
