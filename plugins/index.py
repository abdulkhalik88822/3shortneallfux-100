import asyncio
import logging
import os
import time

from pyrogram import Client, enums, filters
from pyrogram.errors import FloodWait, PeerIdInvalid
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.ia_filterdb import (
    get_index_job,
    get_pending_index_jobs,
    save_index_job,
    save_source_files_bulk,
)
from info import ADMINS, API_HASH, API_ID, CHANNELS
from utils import get_readable_time, temp

logger = logging.getLogger(__name__)

# One active historical index task at a time. The search bot remains responsive
# because the long index is always run in its own asyncio task.
_INDEX_TASKS = {}
_USER_CLIENT = None
_USER_CLIENT_LOCK = asyncio.Lock()

INDEX_DB_BATCH = max(100, min(2000, int(os.environ.get("INDEX_DB_BATCH", "1000"))))
INDEX_PROGRESS_SECONDS = max(8, int(os.environ.get("INDEX_PROGRESS_SECONDS", "15")))
USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "").strip()


def _task_running(chat_id):
    task = _INDEX_TASKS.get(int(chat_id))
    return bool(task and not task.done())


async def _get_user_client():
    """Start the auxiliary USER session used only for historical indexing."""
    global _USER_CLIENT
    if _USER_CLIENT and getattr(_USER_CLIENT, "is_connected", False):
        return _USER_CLIENT

    if not USER_SESSION_STRING:
        raise RuntimeError(
            "USER_SESSION_STRING is not configured in Koyeb environment variables"
        )

    async with _USER_CLIENT_LOCK:
        if _USER_CLIENT and getattr(_USER_CLIENT, "is_connected", False):
            return _USER_CLIENT

        client = Client(
            "fast_index_user",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=USER_SESSION_STRING,
            in_memory=True,
            no_updates=True,
            workers=1,
            sleep_threshold=60,
        )
        await client.start()
        me = await client.get_me()
        if getattr(me, "is_bot", False):
            await client.stop()
            raise RuntimeError(
                "USER_SESSION_STRING belongs to a bot. A normal Telegram user session is required."
            )
        _USER_CLIENT = client
        logger.info("Fast index user session started as %s (%s)", me.first_name, me.id)
        return _USER_CLIENT


async def shutdown_index_client():
    global _USER_CLIENT
    if _USER_CLIENT:
        try:
            await _USER_CLIENT.stop()
        except Exception:
            pass
        _USER_CLIENT = None


async def _resolve_user_peer(user_client, chat_ref):
    """Make sure an in-memory user session knows the channel peer/access hash."""
    try:
        return await user_client.get_chat(chat_ref)
    except PeerIdInvalid:
        # Session strings do not persist Pyrogram's local peer cache. Loading
        # dialogs once repopulates peers for channels the user account joined.
        async for dialog in user_client.get_dialogs():
            if dialog.chat.id == chat_ref:
                return dialog.chat
        raise RuntimeError(
            "The USER session is not joined to this channel. Join the channel with that account first."
        )


def _media_payload(message, chat_id):
    if message.media not in (enums.MessageMediaType.VIDEO, enums.MessageMediaType.DOCUMENT):
        return None
    media = getattr(message, message.media.value, None)
    if not media:
        return None
    if media.mime_type not in ("video/mp4", "video/x-matroska"):
        return None
    if not getattr(media, "file_name", None) or not getattr(media, "file_size", None):
        return None
    caption_obj = message.caption
    caption = (getattr(caption_obj, "html", None) or str(caption_obj)) if caption_obj else None
    return {
        "chat_id": int(chat_id),
        "message_id": int(message.id),
        "file_name": media.file_name,
        "file_size": media.file_size,
        "mime_type": media.mime_type,
        "caption": caption,
    }


async def _safe_edit(msg, text, reply_markup=None):
    if not msg:
        return
    try:
        await msg.edit_text(text, reply_markup=reply_markup)
    except FloodWait:
        # A status-message flood wait must never pause the actual indexer.
        pass
    except Exception:
        pass


def _status_text(job):
    started_at = float(job.get("started_at") or time.time())
    elapsed = max(0.001, time.time() - started_at)
    scanned = int(job.get("scanned") or 0)
    speed = scanned / elapsed
    return (
        "🚀 <b>USER-SESSION ULTRA FAST INDEX</b>\n\n"
        f"Messages scanned: <code>{scanned}</code>\n"
        f"Files saved: <code>{int(job.get('saved') or 0)}</code>\n"
        f"Duplicates: <code>{int(job.get('duplicates') or 0)}</code>\n"
        f"Unsupported/non-media: <code>{int(job.get('skipped') or 0)}</code>\n"
        f"Errors: <code>{int(job.get('errors') or 0)}</code>\n"
        f"Current message ID: <code>{int(job.get('next_offset_id') or 0)}</code>\n"
        f"Stop-at ID: <code>{int(job.get('stop_id') or 0)}</code>\n\n"
        f"Speed: <code>{speed:.1f} msg/sec</code>\n"
        f"Running: <code>{get_readable_time(elapsed)}</code>\n\n"
        "✅ Search bot stays online while indexing.\n"
        "✅ Progress is saved in MongoDB for auto-resume after restart."
    )


async def _run_user_index(bot, chat_id, top_message_id, stop_id, status_msg=None, resume_job=None):
    chat_id = int(chat_id)
    top_message_id = int(top_message_id)
    stop_id = max(0, int(stop_id or 0))

    if resume_job:
        next_offset_id = int(resume_job.get("next_offset_id") or (top_message_id + 1))
        scanned = int(resume_job.get("scanned") or 0)
        saved = int(resume_job.get("saved") or 0)
        duplicates = int(resume_job.get("duplicates") or 0)
        skipped = int(resume_job.get("skipped") or 0)
        errors = int(resume_job.get("errors") or 0)
        started_at = float(resume_job.get("started_at") or time.time())
    else:
        next_offset_id = top_message_id + 1
        scanned = saved = duplicates = skipped = errors = 0
        started_at = time.time()

    await save_index_job(
        chat_id,
        status="starting",
        top_message_id=top_message_id,
        stop_id=stop_id,
        next_offset_id=next_offset_id,
        scanned=scanned,
        saved=saved,
        duplicates=duplicates,
        skipped=skipped,
        errors=errors,
        started_at=started_at,
    )

    buffer = []
    last_progress = 0.0

    try:
        user_client = await _get_user_client()
        peer = await _resolve_user_peer(user_client, chat_id)
        # Use resolved numeric peer id; get_chat_history is valid for the USER session.
        history_chat_id = peer.id

        await save_index_job(chat_id, status="running")

        async for message in user_client.get_chat_history(
            history_chat_id,
            limit=0,
            offset_id=next_offset_id,
        ):
            if message.id <= stop_id:
                break

            scanned += 1
            next_offset_id = int(message.id)

            payload = _media_payload(message, chat_id)
            if payload is None:
                skipped += 1
            else:
                buffer.append(payload)

            if len(buffer) >= INDEX_DB_BATCH:
                ins, dup, err = await save_source_files_bulk(buffer)
                buffer.clear()
                saved += ins
                duplicates += dup
                errors += err
                # Persist only after the DB batch has been committed. On a hard
                # restart, at worst one partial batch is re-read and safely upserted.
                await save_index_job(
                    chat_id,
                    status="running",
                    next_offset_id=next_offset_id,
                    scanned=scanned,
                    saved=saved,
                    duplicates=duplicates,
                    skipped=skipped,
                    errors=errors,
                )

            if temp.CANCEL:
                temp.CANCEL = False
                if buffer:
                    ins, dup, err = await save_source_files_bulk(buffer)
                    buffer.clear()
                    saved += ins
                    duplicates += dup
                    errors += err
                await save_index_job(
                    chat_id,
                    status="cancelled",
                    next_offset_id=next_offset_id,
                    scanned=scanned,
                    saved=saved,
                    duplicates=duplicates,
                    skipped=skipped,
                    errors=errors,
                )
                await _safe_edit(status_msg, "✅ Index cancelled safely. Saved progress will remain in MongoDB.")
                return

            now = time.time()
            if now - last_progress >= INDEX_PROGRESS_SECONDS:
                last_progress = now
                job = {
                    "started_at": started_at,
                    "scanned": scanned,
                    "saved": saved,
                    "duplicates": duplicates,
                    "skipped": skipped,
                    "errors": errors,
                    "next_offset_id": next_offset_id,
                    "stop_id": stop_id,
                }
                buttons = InlineKeyboardMarkup([[
                    InlineKeyboardButton("CANCEL", callback_data=f"index#cancel#{chat_id}#0#0")
                ]])
                await _safe_edit(status_msg, _status_text(job), buttons)

        if buffer:
            ins, dup, err = await save_source_files_bulk(buffer)
            saved += ins
            duplicates += dup
            errors += err
            buffer.clear()

        await save_index_job(
            chat_id,
            status="completed",
            next_offset_id=stop_id,
            scanned=scanned,
            saved=saved,
            duplicates=duplicates,
            skipped=skipped,
            errors=errors,
        )
        elapsed = time.time() - started_at
        await _safe_edit(
            status_msg,
            (
                "✅ <b>ULTRA FAST INDEX COMPLETE</b>\n\n"
                f"Messages scanned: <code>{scanned}</code>\n"
                f"Files saved: <code>{saved}</code>\n"
                f"Duplicates: <code>{duplicates}</code>\n"
                f"Skipped: <code>{skipped}</code>\n"
                f"Errors: <code>{errors}</code>\n"
                f"Completed in: <code>{get_readable_time(elapsed)}</code>"
            ),
        )

    except asyncio.CancelledError:
        # Process shutdown/redeploy: Mongo checkpoint lets the next instance resume.
        await save_index_job(
            chat_id,
            status="running",
            next_offset_id=next_offset_id,
            scanned=scanned,
            saved=saved,
            duplicates=duplicates,
            skipped=skipped,
            errors=errors,
        )
        raise
    except Exception as exc:
        logger.exception("Fast user index failed")
        if buffer:
            try:
                ins, dup, err = await save_source_files_bulk(buffer)
                saved += ins
                duplicates += dup
                errors += err
            except Exception:
                pass
        # Keep it resumable. A transient Telegram/Koyeb interruption will be
        # picked up automatically on the next bot start.
        await save_index_job(
            chat_id,
            status="interrupted",
            next_offset_id=next_offset_id,
            scanned=scanned,
            saved=saved,
            duplicates=duplicates,
            skipped=skipped,
            errors=errors + 1,
            last_error=f"{type(exc).__name__}: {exc}"[:500],
        )
        await _safe_edit(
            status_msg,
            (
                "⚠️ <b>Index paused by a transient error.</b>\n\n"
                f"{type(exc).__name__}: {exc}\n\n"
                "Progress is saved. The bot will auto-resume this job after restart, "
                "or you can run /index again."
            ),
        )
    finally:
        _INDEX_TASKS.pop(chat_id, None)


def _start_task(bot, chat_id, top_message_id, stop_id, status_msg=None, resume_job=None):
    chat_id = int(chat_id)
    if _task_running(chat_id):
        return _INDEX_TASKS[chat_id]
    task = asyncio.create_task(
        _run_user_index(
            bot,
            chat_id,
            top_message_id,
            stop_id,
            status_msg=status_msg,
            resume_job=resume_job,
        ),
        name=f"fast-index-{chat_id}",
    )
    _INDEX_TASKS[chat_id] = task
    return task


async def resume_pending_index_jobs(bot):
    """Called from bot.start(); resumes Mongo-persisted jobs after redeploy/restart."""
    await asyncio.sleep(3)
    if not USER_SESSION_STRING:
        logger.warning("USER_SESSION_STRING not configured; automatic fast-index resume is disabled")
        return
    jobs = await get_pending_index_jobs()
    for job in jobs:
        chat_id = int(job.get("chat_id"))
        if _task_running(chat_id):
            continue
        logger.warning("Auto-resuming index job for channel %s at message %s", chat_id, job.get("next_offset_id"))
        _start_task(
            bot,
            chat_id,
            int(job.get("top_message_id") or job.get("next_offset_id") or 0),
            int(job.get("stop_id") or 0),
            status_msg=None,
            resume_job=job,
        )


@Client.on_callback_query(filters.regex(r"^index"))
async def index_files(bot, query):
    _, ident, chat, lst_msg_id, skip = query.data.split("#")
    chat_id = int(chat)

    if ident == "yes":
        if not USER_SESSION_STRING:
            return await query.message.edit(
                "❌ <b>Fast index needs USER_SESSION_STRING.</b>\n\n"
                "Add a normal Telegram user session string in Koyeb Environment Variables, "
                "then redeploy. The search bot token is NOT used for this historical scan."
            )
        if _task_running(chat_id):
            return await query.answer("Index already running for this channel.", show_alert=True)
        await query.message.edit("🚀 Fast user-session indexing started in background. Bot remains online.")
        _start_task(bot, chat_id, int(lst_msg_id), int(skip), query.message)
        await query.answer("Started", cache_time=0)

    elif ident == "cancel":
        temp.CANCEL = True
        await query.answer("Cancel requested. Current DB batch will finish safely.", show_alert=True)


@Client.on_message(filters.command("index") & filters.private & filters.incoming & filters.user(ADMINS))
async def send_for_index(bot, message):
    i = await message.reply("Forward the channel's latest message or send its message link.")
    msg = await bot.listen(chat_id=message.chat.id, user_id=message.from_user.id)
    await i.delete()

    if msg.text and msg.text.startswith("https://t.me"):
        try:
            parts = msg.text.rstrip("/").split("/")
            last_msg_id = int(parts[-1])
            chat_ref = parts[-2]
            chat_id = int("-100" + chat_ref) if chat_ref.isnumeric() else chat_ref
        except Exception:
            return await message.reply("Invalid message link!")
    elif msg.forward_from_chat and msg.forward_from_chat.type == enums.ChatType.CHANNEL:
        last_msg_id = int(msg.forward_from_message_id)
        chat_id = msg.forward_from_chat.username or msg.forward_from_chat.id
    else:
        return await message.reply("This is not a forwarded channel message or valid link.")

    try:
        chat = await bot.get_chat(chat_id)
    except Exception as exc:
        return await message.reply(f"Channel access error - {exc}")

    # Always persist/use the numeric Telegram channel id. The user session must
    # also be joined to this channel.
    numeric_chat_id = int(chat.id)

    s = await message.reply(
        "Send the last already-indexed message ID.\n\n"
        "Fresh full index: <code>0</code>\n"
        "Example: if old index reached message 36601, send <code>36601</code>."
    )
    msg = await bot.listen(chat_id=message.chat.id, user_id=message.from_user.id)
    await s.delete()
    try:
        stop_id = max(0, int(msg.text))
    except Exception:
        return await message.reply("Message ID is invalid.")

    existing = await get_index_job(numeric_chat_id)
    resume_note = ""
    if existing and existing.get("status") in ("running", "starting", "interrupted"):
        resume_note = (
            f"\n\n♻️ Saved checkpoint found: <code>{existing.get('next_offset_id')}</code>. "
            "If you start, the saved job can auto-resume after Koyeb restarts."
        )

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 START ULTRA FAST INDEX", callback_data=f"index#yes#{numeric_chat_id}#{last_msg_id}#{stop_id}")],
        [InlineKeyboardButton("CLOSE", callback_data="close_data")],
    ])

    mode = "✅ READY" if USER_SESSION_STRING else "❌ USER_SESSION_STRING MISSING"
    await message.reply(
        (
            f"<b>Channel:</b> {chat.title}\n"
            f"<b>Last message ID:</b> <code>{last_msg_id}</code>\n"
            f"<b>Stop-at/already indexed ID:</b> <code>{stop_id}</code>\n\n"
            f"<b>User-session mode:</b> {mode}\n"
            f"<b>Mongo batch:</b> <code>{INDEX_DB_BATCH}</code>\n\n"
            "Historical scanning runs on a separate USER session; the search bot remains responsive."
            f"{resume_note}"
        ),
        reply_markup=buttons,
    )


@Client.on_message(filters.command("indexstatus") & filters.private & filters.user(ADMINS))
async def index_status(bot, message):
    if len(message.command) > 1:
        try:
            chat_id = int(message.command[1])
        except Exception:
            return await message.reply("Usage: /indexstatus -100xxxxxxxxxx")
    else:
        active = [cid for cid, task in _INDEX_TASKS.items() if not task.done()]
        if not active:
            jobs = await get_pending_index_jobs()
            if not jobs:
                return await message.reply("No active or resumable index job.")
            chat_id = int(jobs[0]["chat_id"])
        else:
            chat_id = active[0]

    job = await get_index_job(chat_id)
    if not job:
        return await message.reply("No saved index job for that channel.")
    await message.reply(_status_text(job) + f"\n\nStatus: <code>{job.get('status')}</code>")


@Client.on_message(filters.command("channel"))
async def channel_info(bot, message):
    if message.from_user.id not in ADMINS:
        return await message.reply("Only bot owner can use this command.")
    if not CHANNELS:
        return await message.reply("Not set CHANNELS")
    text = "**Indexed Channels:**\n\n"
    for channel_id in CHANNELS:
        chat = await bot.get_chat(channel_id)
        text += f"{chat.title}\n"
    text += f"\n**Total:** {len(CHANNELS)}"
    await message.reply(text)
