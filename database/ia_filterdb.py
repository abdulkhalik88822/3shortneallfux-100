import base64
import hashlib
import json
import logging
import os
import re
import time
from struct import pack
from types import SimpleNamespace

from marshmallow.exceptions import ValidationError
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError
from pyrogram.file_id import FileId
from umongo import Document, Instance, fields

from info import COLLECTION_NAME, DATABASE_NAME, DATABASE_URI2, MAX_BTN
from utils import get_redis
from .smart_search import (
    build_fuzzy_candidate_filter,
    build_strict_filter,
    fuzzy_accept,
    parse_search_query,
    relevance_score,
)

logger = logging.getLogger(__name__)

client = AsyncIOMotorClient(DATABASE_URI2)
mydb = client[DATABASE_NAME]
instance = Instance.from_db(mydb)

# Search controls. Defaults are safe for a normal Koyeb instance.
SEARCH_CANDIDATE_LIMIT = max(100, int(os.environ.get("SEARCH_CANDIDATE_LIMIT", "600")))
SEARCH_CACHE_TTL = max(30, int(os.environ.get("SEARCH_CACHE_TTL", "300")))
SEARCH_CACHE_MAX = max(16, int(os.environ.get("SEARCH_CACHE_MAX", "128")))
_MEMORY_CACHE = {}


@instance.register
class Media(Document):
    file_id = fields.StrField(attribute="_id")
    file_ref = fields.StrField(allow_none=True)
    file_name = fields.StrField(required=True)
    file_size = fields.IntField(required=True)
    mime_type = fields.StrField(allow_none=True)
    caption = fields.StrField(allow_none=True)
    file_type = fields.StrField(allow_none=True)

    class Meta:
        indexes = ("$file_name",)
        collection_name = COLLECTION_NAME


def _serialize_doc(doc):
    """Convert Motor/UMongo media to a JSON-safe dict."""
    if isinstance(doc, dict):
        return {
            "file_id": str(doc.get("_id") or doc.get("file_id") or ""),
            "file_name": doc.get("file_name") or "",
            "file_size": int(doc.get("file_size") or 0),
            "caption": doc.get("caption"),
            "file_ref": doc.get("file_ref"),
            "mime_type": doc.get("mime_type"),
            "file_type": doc.get("file_type"),
        }
    return {
        "file_id": str(getattr(doc, "file_id", "")),
        "file_name": getattr(doc, "file_name", "") or "",
        "file_size": int(getattr(doc, "file_size", 0) or 0),
        "caption": getattr(doc, "caption", None),
        "file_ref": getattr(doc, "file_ref", None),
        "mime_type": getattr(doc, "mime_type", None),
        "file_type": getattr(doc, "file_type", None),
    }


def _as_media_obj(doc):
    data = _serialize_doc(doc)
    return SimpleNamespace(**data)


def _cache_get_memory(key):
    item = _MEMORY_CACHE.get(key)
    if not item:
        return None
    expires_at, value = item
    if expires_at <= time.monotonic():
        _MEMORY_CACHE.pop(key, None)
        return None
    return value


def _cache_set_memory(key, value):
    if len(_MEMORY_CACHE) >= SEARCH_CACHE_MAX:
        # Drop the oldest inserted item; Python dict preserves insertion order.
        try:
            _MEMORY_CACHE.pop(next(iter(_MEMORY_CACHE)))
        except (StopIteration, KeyError):
            pass
    _MEMORY_CACHE[key] = (time.monotonic() + SEARCH_CACHE_TTL, value)


def clear_search_cache():
    _MEMORY_CACHE.clear()


async def ensure_indexes():
    """Create indexes used by file lookup/admin operations.

    Smart search intentionally does not depend on MongoDB $text OR semantics,
    because that was the reason queries such as 'Moms 2016' returned every 2016 file.
    """
    try:
        await Media.collection.create_index([("file_name", 1)], background=True)
        await Media.collection.create_index([("file_size", 1)], background=True)
        await Media.collection.create_index([("file_type", 1)], background=True)
        print("✅ Database indexes created/verified successfully!")
    except Exception as e:
        print(f"Index creation warning: {e}")


async def get_files_db_size():
    return (await mydb.command("dbstats"))["dataSize"]


async def save_file(media):
    file_id, file_ref = unpack_new_file_id(media.file_id)
    file_name = re.sub(r"(_|\-|\.|\+)", " ", str(media.file_name or ""))
    file_name = re.sub(r"\s+", " ", file_name).strip()
    try:
        file = Media(
            file_id=file_id,
            file_ref=file_ref,
            file_name=file_name,
            file_size=media.file_size,
            mime_type=media.mime_type,
            caption=media.caption.html if media.caption else None,
            file_type=(media.mime_type.split("/")[0] if media.mime_type and "/" in media.mime_type else None),
        )
    except ValidationError:
        return "err"
    try:
        await file.commit()
    except DuplicateKeyError:
        return "dup"
    except Exception:
        logger.exception("Failed to save media")
        return "err"
    clear_search_cache()
    return "suc"


async def _load_cached_results(cache_key):
    memory = _cache_get_memory(cache_key)
    if memory is not None:
        return memory

    redis_conn = await get_redis()
    if redis_conn:
        try:
            raw = await redis_conn.get(cache_key)
            if raw:
                payload = json.loads(raw)
                if isinstance(payload, list):
                    _cache_set_memory(cache_key, payload)
                    return payload
        except Exception as exc:
            logger.warning("Redis search-cache read failed: %s", exc)
    return None


async def _store_cached_results(cache_key, docs):
    payload = [_serialize_doc(x) for x in docs]
    _cache_set_memory(cache_key, payload)
    redis_conn = await get_redis()
    if redis_conn:
        try:
            await redis_conn.setex(cache_key, SEARCH_CACHE_TTL, json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            logger.warning("Redis search-cache write failed: %s", exc)
    return payload


async def _run_smart_search(spec):
    projection = {
        "_id": 1,
        "file_name": 1,
        "file_size": 1,
        "caption": 1,
        "file_ref": 1,
        "mime_type": 1,
        "file_type": 1,
    }

    strict_filter = build_strict_filter(spec)
    docs = await Media.collection.find(strict_filter, projection).limit(SEARCH_CANDIDATE_LIMIT).to_list(length=SEARCH_CANDIDATE_LIMIT)
    fuzzy_mode = False

    # Controlled typo fallback. It runs only when strict search returns nothing,
    # so accuracy is never sacrificed for normal queries.
    if not docs and spec.get("title_tokens"):
        fuzzy_filter = build_fuzzy_candidate_filter(spec)
        if fuzzy_filter:
            candidates = await Media.collection.find(fuzzy_filter, projection).limit(min(SEARCH_CANDIDATE_LIMIT, 300)).to_list(length=min(SEARCH_CANDIDATE_LIMIT, 300))
            docs = [d for d in candidates if fuzzy_accept(d.get("file_name", ""), spec)]
            fuzzy_mode = bool(docs)

    docs.sort(
        key=lambda d: (
            relevance_score(d.get("file_name", ""), spec, fuzzy=fuzzy_mode),
            -(len(d.get("file_name", "") or "")),
        ),
        reverse=True,
    )
    return docs


async def get_search_results(query, max_results=MAX_BTN, offset=0, lang=None):
    """Strict smart search with pagination.

    Examples:
      rrr                -> every RRR-related file
      rrr 2022           -> RRR files that also contain year 2022
      rrr s01            -> RRR season 1
      rrr 2022 s01 e03   -> RRR + year + season + episode
      episode 1 / e01    -> episode 1 files
      Mom 2017           -> does not match Moms
      Moms 2016          -> requires both Moms AND 2016 (no 2016-only junk)
    """
    query = str(query or "").strip()
    if not query:
        return [], "", 0

    if lang and str(lang).lower() not in query.lower().split():
        query = f"{query} {lang}"

    spec = parse_search_query(query)
    max_results = max(1, int(max_results or MAX_BTN))
    try:
        offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        offset = 0

    cache_material = json.dumps(spec, sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha1(cache_material.encode("utf-8")).hexdigest()
    cache_key = f"smart-search:v4:{digest}"

    cached_docs = await _load_cached_results(cache_key)
    if cached_docs is None:
        docs = await _run_smart_search(spec)
        cached_docs = await _store_cached_results(cache_key, docs)

    total = len(cached_docs)
    if offset >= total:
        return [], "", total

    page = cached_docs[offset: offset + max_results]
    next_offset = offset + max_results
    next_offset_str = str(next_offset) if next_offset < total else ""
    return [_as_media_obj(d) for d in page], next_offset_str, total


async def get_bad_files(query, file_type=None, offset=0, filter=False):
    query = query.strip()
    if not query:
        raw_pattern = "."
    elif " " not in query:
        raw_pattern = r"(\b|[\.\+\-_])" + re.escape(query) + r"(\b|[\.\+\-_])"
    else:
        raw_pattern = re.escape(query).replace(r"\ ", r".*[\s\.\+\-_]")
    try:
        regex = re.compile(raw_pattern, flags=re.IGNORECASE)
    except re.error:
        return [], 0
    mongo_filter = {"file_name": regex}
    if file_type:
        mongo_filter["file_type"] = file_type
    cursor = Media.find(mongo_filter)
    files = await cursor.to_list(length=50)
    return files, 50


async def get_file_details(query):
    cursor = Media.find({"file_id": query})
    return await cursor.to_list(length=1)


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
            decoded.access_hash,
        )
    )
    file_ref = encode_file_ref(decoded.file_reference)
    return file_id, file_ref
