from motor.motor_asyncio import AsyncIOMotorClient

client = AsyncIOMotorClient("mongodb://localhost:27017")
db = client["movie_db"]
collection = db["movies"]

async def get_all_movies():
    return await collection.find().limit(2000).to_list(2000)
