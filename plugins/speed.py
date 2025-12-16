from pyrogram import Client, filters
from motor.motor_asyncio import AsyncIOMotorClient
from info import ADMINS, DATABASE_URI2, DATABASE_NAME, COLLECTION_NAME

@Client.on_message(filters.command("speedfix") & filters.user(ADMINS))
async def fix_database_speed(client, message):
    status_msg = await message.reply("⚙️ **Speed Fix शुरू हो रहा है...**\nकृपया इंतज़ार करें...")
    
    try:
        mongo = AsyncIOMotorClient(DATABASE_URI2)
        db = mongo[DATABASE_NAME]
        col = db[COLLECTION_NAME]
        
        # यह बॉट को बताएगा कि फाइल नाम कैसे जल्दी ढूँढना है
        await col.create_index([("file_name", "text")])
        
        await status_msg.edit("✅ **SUCCESS!**\nIndexing पूरी हो गयी। अब बॉट सुपर फास्ट है! 🚀")
    except Exception as e:
        await status_msg.edit(f"❌ **Error:** {e}")
