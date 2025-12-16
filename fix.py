import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
# अपनी info फाइल से DATABASE_URI import करें
from info import DATABASE_URI2, DATABASE_NAME, COLLECTION_NAME

async def make_db_fast():
    print("Connecting to Database...")
    client = AsyncIOMotorClient(DATABASE_URI2)
    db = client[DATABASE_NAME]
    col = db[COLLECTION_NAME]
    
    print("Creating Index... (Wait 2 minutes)")
    
    try:
        # यह लाइन सर्च को रॉकेट जैसा फास्ट कर देगी
        await col.create_index([("file_name", "text")])
        print("\n✅ SUCCESS! Index बन गया।")
        print("अब इस फाइल (fix.py) को डिलीट कर सकते हैं।")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(make_db_fast())
