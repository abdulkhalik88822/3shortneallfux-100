import logging
import re
import base64
import json
from struct import pack
from pyrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError
from umongo import Instance, Document, fields
from motor.motor_asyncio import AsyncIOMotorClient
from marshmallow.exceptions import ValidationError
from info import DATABASE_URI2, DATABASE_NAME, COLLECTION_NAME, MAX_BTN
from utils import get_redis

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

async def ensure_indexes():
    try:
        await Media.collection.create_index([("file_name", "text")], default_language="none")
        await Media.collection.create_index([("file_name", 1)])
        await Media.collection.create_index([("file_size", 1)])
        print("✅ Database indexes created/verified successfully!")
    except Exception as e:
        print(f"Index creation warning: {e}")

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

    redis_conn = await get_redis()
    cache_key = f"sr:{query.lower()}:{lang or 'none'}:{max_results}:{offset}"
    if redis_conn:
        try:
            cached = await redis_conn.get(cache_key)
            if cached:
                data = json.loads(cached)
                return data['files'], data['next_offset'], data['total']
        except Exception as e:
            print(f"Redis cache error: {e}")

    try:
        filter = {'$text': {'$search': query}}
        cursor = Media.find(filter).sort([('score', {'$meta': 'textScore'})]).limit(100)
        files = await cursor.to_list(length=100)
        if files:
            if lang:
                files = [f for f in files if lang in f.file_name.lower()]
            total = len(files)
            if offset >= total:
                return [], '', total
            next_offset = offset + max_results
            result_files = files[offset:next_offset]
            next_offset_str = str(next_offset) if next_offset < total else ''
            if redis_conn:
                try:
                    serializable = []
                    for f in result_files:
                        d = {
                            'file_id': f.file_id,
                            'file_name': f.file_name,
                            'file_size': f.file_size,
                            'caption': f.caption,
                            'file_ref': f.file_ref,
                            'mime_type': f.mime_type,
                            'file_type': f.file_type
                        }
                        serializable.append(d)
                    await redis_conn.setex(cache_key, 300, json.dumps({'files': serializable, 'next_offset': next_offset_str, 'total': total}))
                except:
                    pass
            return result_files, next_offset_str, total
    except Exception as e:
        print(f"Text search fallback: {e}")

    try:
        search_query = re.escape(query)
        regex = re.compile(f"^{search_query}", re.IGNORECASE)
        filter = {'file_name': regex}
        cursor = Media.find(filter).hint([('file_name', 1)]).limit(100)
        files = await cursor.to_list(length=100)
        if lang:
            files = [f for f in files if lang in f.file_name.lower()]
        total = len(files)
        if offset >= total:
            return [], '', total
        next_offset = offset + max_results
        result_files = files[offset:next_offset]
        next_offset_str = str(next_offset) if next_offset < total else ''
        if redis_conn:
            try:
                serializable = []
                for f in result_files:
                    d = {
                        'file_id': f.file_id,
                        'file_name': f.file_name,
                        'file_size': f.file_size,
                        'caption': f.caption,
                        'file_ref': f.file_ref,
                        'mime_type': f.mime_type,
                        'file_type': f.file_type
                    }
                    serializable.append(d)
                await redis_conn.setex(cache_key, 300, json.dumps({'files': serializable, 'next_offset': next_offset_str, 'total': total}))
            except:
                pass
        return result_files, next_offset_str, total
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
