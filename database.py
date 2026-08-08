import re
from motor.motor_asyncio import AsyncIOMotorClient
from info import DATABASE_URI, DATABASE_NAME, COLLECTION_NAME

# -------------------------------
# ✅ MongoDB Connection
# -------------------------------
client = AsyncIOMotorClient(DATABASE_URI)
db = client[DATABASE_NAME]
collection = db[COLLECTION_NAME]

# -------------------------------
# 🔥 CLEAN QUERY
# -------------------------------
def clean_query(text):
    text = text.lower()

    # remove special chars
    text = re.sub(r'[^a-z0-9\s]', ' ', text)

    # normalize season/episode
    text = re.sub(r'\bseason\s*(\d+)\b', r's\1', text)
    text = re.sub(r'\bepisode\s*(\d+)\b', r'e\1', text)

    return text.strip()

# -------------------------------
# 🔍 EXTRACT DETAILS
# -------------------------------
def extract_parts(query):
    year = re.search(r'(19|20)\d{2}', query)
    season = re.search(r's(\d{1,2})', query)
    episode = re.search(r'e(\d{1,2})', query)

    return {
        "year": year.group() if year else None,
        "season": f"s{int(season.group(1)):02d}" if season else None,
        "episode": f"e{int(episode.group(1)):02d}" if episode else None
    }

# -------------------------------
# 🧠 SCORE SYSTEM (SMART SORT)
# -------------------------------
def calculate_score(item, words):
    name = item.get("file_name", "").lower()
    caption = item.get("caption", "").lower()

    score = 0

    for w in words:
        if w in name:
            score += 3   # file_name ज्यादा important
        if w in caption:
            score += 1

    return score

# -------------------------------
# 🚀 ULTRA SEARCH (FINAL)
# -------------------------------
async def search_movies(search, limit=50):
    search = clean_query(search)
    parts = extract_parts(search)

    words = search.split()
    and_conditions = []

    # ✅ STRICT WORD MATCH (WORD BOUNDARY)
    for word in words:
        and_conditions.append({
            "$or": [
                {"file_name": {"$regex": f"\\b{word}\\b", "$options": "i"}},
                {"caption": {"$regex": f"\\b{word}\\b", "$options": "i"}}
            ]
        })

    # ✅ YEAR FILTER
    if parts["year"]:
        and_conditions.append({
            "file_name": {"$regex": parts["year"], "$options": "i"}
        })

    # ✅ SEASON FILTER
    if parts["season"]:
        and_conditions.append({
            "file_name": {"$regex": parts["season"], "$options": "i"}
        })

    # ✅ EPISODE FILTER
    if parts["episode"]:
        and_conditions.append({
            "file_name": {"$regex": parts["episode"], "$options": "i"}
        })

    # 🔥 FINAL QUERY
    final_query = {"$and": and_conditions} if and_conditions else {}

    results = await collection.find(final_query).limit(limit).to_list(length=limit)

    # 🧠 SORT BY RELEVANCE
    results = sorted(results, key=lambda x: calculate_score(x, words), reverse=True)

    return results

# -------------------------------
# ⚡ GET ALL
# -------------------------------
async def get_all_movies(limit=2000):
    return await collection.find().limit(limit).to_list(length=limit)

# -------------------------------
# 🔥 CREATE INDEX (RUN ONCE)
# -------------------------------
async def create_indexes():
    await collection.create_index([("file_name", 1)])
    await collection.create_index([("caption", 1)])
