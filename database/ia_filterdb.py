import logging
import re
import base64
from struct import pack
from pyrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError
from umongo import Instance, Document, fields
from motor.motor_asyncio import AsyncIOMotorClient
from marshmallow.exceptions import ValidationError
from info import DATABASE_URI2, DATABASE_NAME, COLLECTION_NAME

# Error Fix: MAX_BTN ko info.py se nahi mangayenge, direct yahi likhenge
MAX_BTN = 8 

client = AsyncIOMotorClient(DATABASE_URI2)
mydb = client[DATABASE_NAME]
instance = Instance.from_db(mydb)

@instance.register
class Media(Document):
    file_id = fields.StrField(attribute='_id')
    file_ref = fields.StrField(allow_none=True)
    file_name = fields.StrField(required=True)
    file_size = fields.IntField(required=True)
    mime_type = fields.StrField(allow_none=True)
    caption = fields.StrField(allow_none=True)
    file_type = fields.StrField(allow_none=True)

    class Meta:
        indexes = ('$file_name', )
        collection_name = COLLECTION_NAME

# -------- 🚀 SPEED BOOST: Indexes ensure karo (Bot Start pe chalega) --------
async def ensure_indexes():
    try:
        # 1. Full Text Search Index (सबसे तेज़)
        await Media.collection.create_index([("file_name", "text")], default_language="none")
        # 2. Normal Index for Prefix Search
        await Media.collection.create_index([("file_name", 1)])
        # 3. Size Index (कभी कभी काम आता है)
        await Media.collection.create_index([("file_size", 1)])
        print("✅ Database indexes created/verified successfully!")
    except Exception as e:
        print(f"Index creation warning (ignore if already exists): {e}")

async def get_files_db_size():
    return (await mydb.command("dbstats"))['dataSize']
    
async def save_file(media):
    file_id, file_ref = unpack_new_file_id(media.file_id)
    file_name = re.sub(r"(_|\-|\.|\+)", " ", str(media.file_name))
    try:
        file = Media(
            file_id=file_id,
            file_ref=file_ref,
            file_name=file_name,
            file_size=media.file_size,
            mime_type=media.mime_type,
            caption=media.caption.html if media.caption else None,
            file_type=media.mime_type.split('/')[0]
        )
    except ValidationError:
        return 'err'
    else:
        try:
            await file.commit()
        except DuplicateKeyError:      
            return 'dup'
        else:
            return 'suc'

# -------- 🚀 ULTRA FAST SEARCH (Optimized) --------
async def get_search_results(query, max_results=MAX_BTN, offset=0, lang=None):
    query = query.strip()
    if not query:
        return [], '', 0

    # 1. Super Fast: Text Search (Indexed) - ये सबसे पहले try करेगा
    try:
        filter = {'$text': {'$search': query}}
        cursor = Media.find(filter).sort([('score', {'$meta': 'textScore'})]).limit(100)
        files = await cursor.to_list(length=100)
        if files:
            # Language filter (अगर लागू हो)
            if lang:
                files = [f for f in files if lang in f.file_name.lower()]
            # Pagination
            total = len(files)
            if offset >= total:
                return [], '', total
            next_offset = offset + max_results
            return files[offset:next_offset], str(next_offset) if next_offset < total else '', total
    except Exception as e:
        print(f"Text search fallback due to: {e}")

    # 2. Backup: Prefix Regex (जल्दी के लिए "^" use किया है, ताकि Index लगे)
    try:
        # अगर query में स्पेस है तो उसे ठीक करें
        search_query = re.escape(query)
        regex = re.compile(f"^{search_query}", re.IGNORECASE)  # "^" से शुरू होने वाली files
        filter = {'file_name': regex}
        # Index hint देना (MongoDB को बताओ file_name index use करे)
        cursor = Media.find(filter).hint([('file_name', 1)]).limit(100)
        files = await cursor.to_list(length=100)
        
        if lang:
            files = [f for f in files if lang in f.file_name.lower()]
        
        total = len(files)
        if offset >= total:
            return [], '', total
        next_offset = offset + max_results
        return files[offset:next_offset], str(next_offset) if next_offset < total else '', total
    except Exception as e:
        print(f"Regex search error: {e}")
        return [], '', 0

async def get_bad_files(query, file_type=None, offset=0, filter=False):
    query = query.strip()
    if not query:
        raw_pattern = '.'
    elif ' ' not in query:
        raw_pattern = r'(\b|[\.\+\-_])' + query + r'(\b|[\.\+\-_])'
    else:
        raw_pattern = query.replace(' ', r'.*[\s\.\+\-_]')
    try:
        regex = re.compile(raw_pattern, flags=re.IGNORECASE)
    except:
        return []
    filter = {'file_name': regex}
    if file_type:
        filter['file_type'] = file_type
    
    cursor = Media.find(filter)
    files = await cursor.to_list(length=50) 
    return files, 50 
    
async def get_file_details(query):
    filter = {'file_id': query}
    cursor = Media.find(filter)
    filedetails = await cursor.to_list(length=1)
    return filedetails

def encode_file_id(s: bytes) -> str:
    r = b""
    n = 0
    for i in s + bytes([22]) + bytes([4]):
        if i == 0:
            n += 1
        else:
            if n:
                r += b"\x00" + bytes([n])
                n = 0
            r += bytes([i])
    return base64.urlsafe_b64encode(r).decode().rstrip("=")

def encode_file_ref(file_ref: bytes) -> str:
    return base64.urlsafe_b64encode(file_ref).decode().rstrip("=")

def unpack_new_file_id(new_file_id):
    decoded = FileId.decode(new_file_id)
    file_id = encode_file_id(
        pack(
            "<iiqq",
            int(decoded.file_type),
            decoded.dc_id,
            decoded.media_id,
            decoded.access_hash
        )
    )
    file_ref = encode_file_ref(decoded.file_reference)
    return file_id, file_ref
