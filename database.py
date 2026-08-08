import re
from motor.motor_asyncio import AsyncIOMotorClient
from info import DATABASE_URI, DATABASE_NAME, COLLECTION_NAME

# MongoDB Connection (AUTO from info.py)
client = AsyncIOMotorClient(DATABASE_URI)
db = client[DATABASE_NAME]
collection = db[COLLECTION_NAME]

# -------------------------------
# 🔥 CLEAN SEARCH TEXT
# -------------------------------
def clean_query(text):
    text = text.lower()

    # Remove extra words
    text = re.sub(r'[^a-z0-9\s]', ' ', text)

    # Normalize episode formats
    text = re.sub(r'\bseason\s*(\d+)\b', r's\1', text)
    text = re.sub(r'\bepisode\s*(\d+)\b', r'e\1', text)

    return text.strip()


# -------------------------------
# 🔥 EXTRACT INFO (RRR 2022 S01 E03)
# -------------------------------
def extract_parts(query):
    query = query.lower()

    year = re.search(r'(19|20)\d{2}', query)
    season = re.search(r's(\d{1,2})', query)
    episode = re.search(r'e(\d{1,2})', query)

    return {
        "year": year.group() if year else None,
        "season": season.group() if season else None,
        "episode": episode.group() if episode else None
    }


# -------------------------------
# 🚀 ULTRA SEARCH FUNCTION
# -------------------------------
async def search_movies(search, limit=50):
    search = clean_query(search)
    parts = extract_parts(search)

    query_list = []

    # Base search (RRR type)
    query_list.append({
        "file_name": {"$regex": search, "$options": "i"}
    })

    query_list.append({
        "caption": {"$regex": search, "$options": "i"}
    })

    # Year filter
    if parts["year"]:
        query_list.append({
            "file_name": {"$regex": parts["year"], "$options": "i"}
        })

    # Season filter
    if parts["season"]:
        query_list.append({
            "file_name": {"$regex": parts["season"], "$options": "i"}
        })

    # Episode filter
    if parts["episode"]:
        query_list.append({
            "file_name": {"$regex": parts["episode"], "$options": "i"}
        })

    # FINAL QUERY
    final_query = {"$or": query_list}

    results = await collection.find(final_query).limit(limit).to_list(length=limit)

    return results


# -------------------------------
# ⚡ GET ALL (FAST LOAD)
# -------------------------------
async def get_all_movies(limit=2000):
    return await collection.find().limit(limit).to_list(length=limit)


# -------------------------------
# 🔥 INDEX CREATION (IMPORTANT)
# -------------------------------
async def create_indexes():
    await collection.create_index("file_name")
    await collection.create_index("caption")
