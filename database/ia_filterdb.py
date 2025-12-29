import logging
import re
import base64
from struct import pack
from pyrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError
from umongo import Instance, Document, fields
from motor.motor_asyncio import AsyncIOMotorClient
from marshmallow.exceptions import ValidationError
from info import DATABASE_URI2, DATABASE_NAME, COLLECTION_NAME, MAX_BTN

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

async def get_search_results(query, max_results=MAX_BTN, offset=0, lang=None):
    query = query.strip()
    if not query:
        return [], '', 0

    # === 🚀 ULTRA FAST LOGIC (TEXT SEARCH) ===
    # यह कोड 8 लाख फाइल्स को स्कैन नहीं करेगा, सीधे इंडेक्स से उठाएगा।
    
    # 1. पहले Text Search (सबसे तेज़) कोशिश करें
    try:
        filter = {'$text': {'$search': query}}
        cursor = Media.find(filter)
        # Relevance के हिसाब से (जो सबसे अच्छा मैच हो)
        cursor.sort({'score': {'$meta': 'textScore'}})
        cursor.limit(100) # सिर्फ टॉप 100 देखो
    except Exception:
        # अगर Text Search फेल हो (Backup Plan)
        regex = re.compile(f".*{query}.*", flags=re.IGNORECASE)
        filter = {'file_name': regex}
        cursor = Media.find(filter)
        cursor.limit(50) # स्कैनिंग में सिर्फ 50 की लिमिट

    if lang:
        lang_files = [file async for file in cursor if lang in file.file_name.lower()]
        files = lang_files[offset:][:max_results]
        
        # Fake Count Logic
        if len(files) < max_results:
            total_results = offset + len(files)
        else:
            total_results = offset + max_results + 5
            
        next_offset = offset + max_results
        if next_offset >= total_results:
            next_offset = ''
        return files, next_offset, total_results
    
    # Direct Fetch
    cursor.skip(offset).limit(max_results)
    files = await cursor.to_list(length=max_results)
    
    # Fake Count Logic (No DB Load)
    if len(files) < max_results:
        total_results = offset + len(files)
    else:
        total_results = offset + max_results + 5
    
    next_offset = offset + max_results
    if next_offset >= total_results:
        next_offset = ''       
    return files, next_offset, total_results
    
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
