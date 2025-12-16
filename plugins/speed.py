from pyrogram import Client, filters
from motor.motor_asyncio import AsyncIOMotorClient
from info import DATABASE_URI2, DATABASE_NAME, COLLECTION_NAME

# यहाँ से '& filters.user(ADMINS)' हटा दिया गया है
@Client.on_message(filters.command("speedfix"))
async def fix_database_speed(client, message):
    status_msg = await message.reply("⚙️ **Speed Fix शुरू हो रहा है...**\nकृपया 2-3 मिनट इंतज़ार करें...")
    
    try:
        mongo = AsyncIOMotorClient(DATABASE_URI2)
        db = mongo[DATABASE_NAME]
        col = db[COLLECTION_NAME]
        
        # Indexing शुरू
        await col.create_index([("file_name", "text")])
        
        await status_msg.edit("✅ **SUCCESS!**\nIndexing पूरी हो गयी है। 🚀\nअब मूवी सर्च करके देखो!")
    except Exception as e:
        await status_msg.edit(f"❌ **Error:** {e}")
