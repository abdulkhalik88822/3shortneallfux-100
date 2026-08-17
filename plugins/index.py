import asyncio
import logging
import os
import time

from pyrogram import Client, enums, filters
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.ia_filterdb import (
    get_index_job,
    get_pending_index_jobs,
    save_files_bulk,
    save_index_job,
)
from info import ADMINS, CHANNELS
from utils import get_readable_time, temp

logger = logging.getLogger(__name__)

# One historical index job at a time. Search/download handlers stay available
# because indexing runs as a background asyncio task.
_INDEX_TASK = None
_INDEX_TASK_CHAT = None
_INDEX_LOCK = asyncio.Lock()

# Telegram get_messages supports at most 200 message IDs per call.
TELEGRAM_BATCH = 200

# MongoDB is not the bottleneck. Flush periodically so a restart loses only a
# small amount of progress.
INDEX_DB_BATCH = max(200, min(2000, int(os.environ.get("INDEX_DB_BATCH", "1000"))))
INDEX_CHECKPOINT_BATCHES = max(1, min(10, int(os.environ.get("INDEX_CHECKPOINT_BATCHES", "5"))))
INDEX_PROGRESS_SECONDS = max(10, int(os.environ.get("INDEX_PROGRESS_SECONDS", "20")))

# Permanent API/network errors are retried in the background instead of killing
# the bot. Backoff is capped so the job keeps attempting recovery.
RETRY_MAX_SECONDS = max(30, int(os.environ.get("INDEX_RETRY_MAX_SECONDS", "120")))


def _task_running():
    return bool(_INDEX_TASK and not _INDEX_TASK.done())


async def _safe_edit(msg, text, reply_markup=None):
    if not msg:
        return
    try:
        await msg.edit_text(text=text, reply_markup=reply_markup)
    except FloodWait:
        pass
    except Exception:
        pass


async def _flush(buffer):
    if not buffer:
        return 0, 0, 0

    batch = list(buffer)
    buffer.clear()
    return await save_files_bulk(batch)


def _wait_seconds(exc):
    value = getattr(exc, "value", None)
    if value is None:
        value = getattr(exc, "x", None)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 30


def _status_text(job):
    started_at = float(job.get("started_at") or time.time())
    elapsed = max(0.001, time.time() - started_at)

    start_id = int(job.get("start_id") or 1)
    top_id = int(job.get("top_message_id") or 0)
    next_id = int(job.get("next_message_id") or start_id)

    total_ids = max(1, top_id - start_id + 1)
    done_ids = max(0, min(total_ids, next_id - start_id))
    pct = min(100.0, (done_ids / total_ids) * 100.0)

    id_speed = done_ids / elapsed
    remaining = max(0, total_ids - done_ids)
    eta = remaining / id_speed if id_speed > 0 else 0

    wait_text = ""
    if job.get("status") == "waiting":
        wait_text = (
            f"\n⏳ Telegram wait: <code>{int(job.get('wait_seconds') or 0)}s</code>"
        )
    elif job.get("status") == "retrying":
        wait_text = (
            f"\n♻️ Retry in: <code>{int(job.get('retry_seconds') or 0)}s</code>"
        )

    return (
        "⚡ <b>BOT-ONLY AUTO-RESUME INDEX</b>\n\n"
        f"Progress: <code>{pct:.2f}%</code>\n"
        f"Message IDs checked: <code>{done_ids}</code> / <code>{total_ids}</code>\n"
        f"Existing messages received: <code>{int(job.get('received') or 0)}</code>\n"
        f"Files saved: <code>{int(job.get('saved') or 0)}</code>\n"
        f"Duplicates: <code>{int(job.get('duplicates') or 0)}</code>\n"
        f"Deleted/empty: <code>{int(job.get('deleted') or 0)}</code>\n"
        f"Non-media: <code>{int(job.get('non_media') or 0)}</code>\n"
        f"Unsupported: <code>{int(job.get('unsupported') or 0)}</code>\n"
        f"Errors: <code>{int(job.get('errors') or 0)}</code>\n"
        f"Next message ID: <code>{next_id}</code>{wait_text}\n\n"
        f"Effective speed: <code>{id_speed:.2f} IDs/sec</code>\n"
        f"Running: <code>{get_readable_time(elapsed)}</code>\n"
        f"ETA at current rate: <code>{get_readable_time(eta)}</code>\n\n"
        "✅ Search bot stays responsive while indexing.\n"
        "✅ Progress is saved in MongoDB and auto-resumes after restart."
    )


async def _notify_admin(bot, text):
    for admin in ADMINS:
        try:
            return await bot.send_message(admin, text)
        except Exception:
            continue
    return None


async def _save_job(
    chat_id,
    *,
    status,
    top_message_id,
    start_id,
    next_message_id,
    received,
    saved,
    duplicates,
    deleted,
    non_media,
    unsupported,
    errors,
    started_at,
    **extra,
):
    await save_index_job(
        chat_id,
        status=status,
        top_message_id=int(top_message_id),
        start_id=int(start_id),
        next_message_id=int(next_message_id),
        received=int(received),
        saved=int(saved),
        duplicates=int(duplicates),
        deleted=int(deleted),
        non_media=int(non_media),
        unsupported=int(unsupported),
        errors=int(errors),
        started_at=float(started_at),
        **extra,
    )


async def _run_index(
    bot,
    chat_id,
    top_message_id,
    start_id,
    status_msg=None,
    resume_job=None,
):
    """
    Fastest safe BOT-only historical indexer.

    Telegram bot accounts cannot use messages.GetHistory for channel history.
    Therefore we use channels.GetMessages/get_messages with the maximum
    supported batch of 200 message IDs.

    FloodWait is never bypassed. If Telegram asks us to wait, this coroutine
    sleeps asynchronously while the rest of the bot keeps serving users.
    """
    chat_id = int(chat_id)
    top_message_id = int(top_message_id)
    start_id = max(1, int(start_id or 1))

    if resume_job:
        next_id = max(
            start_id,
            int(resume_job.get("next_message_id") or start_id),
        )
        received = int(resume_job.get("received") or 0)
        saved = int(resume_job.get("saved") or 0)
        duplicates = int(resume_job.get("duplicates") or 0)
        deleted = int(resume_job.get("deleted") or 0)
        non_media = int(resume_job.get("non_media") or 0)
        unsupported = int(resume_job.get("unsupported") or 0)
        errors = int(resume_job.get("errors") or 0)
        started_at = float(resume_job.get("started_at") or time.time())
    else:
        next_id = start_id
        received = saved = duplicates = deleted = non_media = unsupported = errors = 0
        started_at = time.time()

    await _save_job(
        chat_id,
        status="running",
        top_message_id=top_message_id,
        start_id=start_id,
        next_message_id=next_id,
        received=received,
        saved=saved,
        duplicates=duplicates,
        deleted=deleted,
        non_media=non_media,
        unsupported=unsupported,
        errors=errors,
        started_at=started_at,
    )

    buffer = []
    batches_since_checkpoint = 0
    last_progress = 0.0
    consecutive_errors = 0

    try:
        while next_id <= top_message_id:
            if temp.CANCEL:
                ins, dup, err = await _flush(buffer)
                saved += ins
                duplicates += dup
                errors += err
                temp.CANCEL = False

                await _save_job(
                    chat_id,
                    status="cancelled",
                    top_message_id=top_message_id,
                    start_id=start_id,
                    next_message_id=next_id,
                    received=received,
                    saved=saved,
                    duplicates=duplicates,
                    deleted=deleted,
                    non_media=non_media,
                    unsupported=unsupported,
                    errors=errors,
                    started_at=started_at,
                )
                await _safe_edit(
                    status_msg,
                    "✅ <b>Index cancelled safely.</b>\n"
                    "Saved files and checkpoint remain in MongoDB.",
                )
                return

            batch_start = next_id
            batch_end = min(
                batch_start + TELEGRAM_BATCH - 1,
                top_message_id,
            )
            ids = list(range(batch_start, batch_end + 1))

            try:
                messages = await bot.get_messages(chat_id, ids)
                consecutive_errors = 0
            except FloodWait as exc:
                wait_for = _wait_seconds(exc) + 1

                await _save_job(
                    chat_id,
                    status="waiting",
                    top_message_id=top_message_id,
                    start_id=start_id,
                    next_message_id=next_id,
                    received=received,
                    saved=saved,
                    duplicates=duplicates,
                    deleted=deleted,
                    non_media=non_media,
                    unsupported=unsupported,
                    errors=errors,
                    started_at=started_at,
                    wait_seconds=wait_for,
                )

                await _safe_edit(
                    status_msg,
                    _status_text({
                        "status": "waiting",
                        "wait_seconds": wait_for,
                        "top_message_id": top_message_id,
                        "start_id": start_id,
                        "next_message_id": next_id,
                        "received": received,
                        "saved": saved,
                        "duplicates": duplicates,
                        "deleted": deleted,
                        "non_media": non_media,
                        "unsupported": unsupported,
                        "errors": errors,
                        "started_at": started_at,
                    }),
                )

                # Async sleep: indexing pauses, bot handlers do not.
                await asyncio.sleep(wait_for)
                continue

            except asyncio.CancelledError:
                ins, dup, err = await _flush(buffer)
                saved += ins
                duplicates += dup
                errors += err

                await _save_job(
                    chat_id,
                    status="running",
                    top_message_id=top_message_id,
                    start_id=start_id,
                    next_message_id=next_id,
                    received=received,
                    saved=saved,
                    duplicates=duplicates,
                    deleted=deleted,
                    non_media=non_media,
                    unsupported=unsupported,
                    errors=errors,
                    started_at=started_at,
                )
                raise

            except Exception as exc:
                errors += 1
                consecutive_errors += 1
                retry_for = min(
                    RETRY_MAX_SECONDS,
                    max(5, 5 * consecutive_errors),
                )

                logger.warning(
                    "Index batch %s-%s failed: %s; retrying in %ss",
                    batch_start,
                    batch_end,
                    exc,
                    retry_for,
                )

                await _save_job(
                    chat_id,
                    status="retrying",
                    top_message_id=top_message_id,
                    start_id=start_id,
                    next_message_id=next_id,
                    received=received,
                    saved=saved,
                    duplicates=duplicates,
                    deleted=deleted,
                    non_media=non_media,
                    unsupported=unsupported,
                    errors=errors,
                    started_at=started_at,
                    retry_seconds=retry_for,
                    last_error=str(exc)[:500],
                )

                await asyncio.sleep(retry_for)
                continue

            if not isinstance(messages, list):
                messages = [messages]

            # Pyrogram normally returns one entry per requested ID, including
            # Empty messages for missing/deleted IDs.
            seen_ids = set()

            for message in messages:
                if message is None:
                    continue

                msg_id = getattr(message, "id", None)
                if msg_id:
                    seen_ids.add(int(msg_id))

                if getattr(message, "empty", False):
                    deleted += 1
                    continue

                received += 1

                if not getattr(message, "media", None):
                    non_media += 1
                    continue

                if message.media not in (
                    enums.MessageMediaType.VIDEO,
                    enums.MessageMediaType.DOCUMENT,
                ):
                    unsupported += 1
                    continue

                media = getattr(
                    message,
                    message.media.value,
                    None,
                )
                if not media:
                    unsupported += 1
                    continue

                if getattr(media, "mime_type", None) not in (
                    "video/mp4",
                    "video/x-matroska",
                ):
                    unsupported += 1
                    continue

                media.caption = message.caption
                buffer.append(media)

            # Any requested ID not represented at all is treated as missing.
            # This keeps counters useful across different Pyrogram forks.
            deleted += max(0, len(ids) - len(seen_ids))

            next_id = batch_end + 1
            batches_since_checkpoint += 1

            # Flush on file volume OR every few Telegram calls. Because
            # Telegram is the dominant bottleneck, regular checkpoint writes
            # add negligible overhead but make restart recovery reliable.
            if (
                len(buffer) >= INDEX_DB_BATCH
                or batches_since_checkpoint >= INDEX_CHECKPOINT_BATCHES
            ):
                ins, dup, err = await _flush(buffer)
                saved += ins
                duplicates += dup
                errors += err
                batches_since_checkpoint = 0

                await _save_job(
                    chat_id,
                    status="running",
                    top_message_id=top_message_id,
                    start_id=start_id,
                    next_message_id=next_id,
                    received=received,
                    saved=saved,
                    duplicates=duplicates,
                    deleted=deleted,
                    non_media=non_media,
                    unsupported=unsupported,
                    errors=errors,
                    started_at=started_at,
                )

            now = time.time()
            if now - last_progress >= INDEX_PROGRESS_SECONDS:
                last_progress = now
                buttons = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "CANCEL",
                        callback_data=(
                            f"index#cancel#{chat_id}#"
                            f"{top_message_id}#{start_id}"
                        ),
                    )
                ]])

                await _safe_edit(
                    status_msg,
                    _status_text({
                        "status": "running",
                        "top_message_id": top_message_id,
                        "start_id": start_id,
                        "next_message_id": next_id,
                        "received": received,
                        "saved": saved,
                        "duplicates": duplicates,
                        "deleted": deleted,
                        "non_media": non_media,
                        "unsupported": unsupported,
                        "errors": errors,
                        "started_at": started_at,
                    }),
                    buttons,
                )

        # Final DB flush.
        ins, dup, err = await _flush(buffer)
        saved += ins
        duplicates += dup
        errors += err

        await _save_job(
            chat_id,
            status="completed",
            top_message_id=top_message_id,
            start_id=start_id,
            next_message_id=top_message_id + 1,
            received=received,
            saved=saved,
            duplicates=duplicates,
            deleted=deleted,
            non_media=non_media,
            unsupported=unsupported,
            errors=errors,
            started_at=started_at,
            completed_at=time.time(),
        )

        await _safe_edit(
            status_msg,
            _status_text({
                "status": "completed",
                "top_message_id": top_message_id,
                "start_id": start_id,
                "next_message_id": top_message_id + 1,
                "received": received,
                "saved": saved,
                "duplicates": duplicates,
                "deleted": deleted,
                "non_media": non_media,
                "unsupported": unsupported,
                "errors": errors,
                "started_at": started_at,
            }) + "\n\n✅ <b>INDEX COMPLETE</b>",
        )

    finally:
        global _INDEX_TASK, _INDEX_TASK_CHAT
        _INDEX_TASK = None
        _INDEX_TASK_CHAT = None


def _launch_index(bot, chat_id, top_message_id, start_id, status_msg=None, resume_job=None):
    global _INDEX_TASK, _INDEX_TASK_CHAT

    if _task_running():
        return False

    _INDEX_TASK_CHAT = int(chat_id)
    _INDEX_TASK = asyncio.create_task(
        _run_index(
            bot,
            int(chat_id),
            int(top_message_id),
            int(start_id),
            status_msg=status_msg,
            resume_job=resume_job,
        )
    )

    def _done(task):
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Background index task failed")

    _INDEX_TASK.add_done_callback(_done)
    return True


async def resume_pending_index_jobs(bot):
    """
    Called automatically from bot.start().

    If Koyeb restarts or redeploys while indexing, MongoDB contains the last
    safe checkpoint. This recreates the background task without requiring
    /index again.
    """
    await asyncio.sleep(3)

    if _task_running():
        return

    jobs = await get_pending_index_jobs()
    if not jobs:
        return

    # One index job at a time by design.
    job = jobs[0]

    try:
        chat_id = int(job["chat_id"])
        top_id = int(job["top_message_id"])
        start_id = int(job.get("start_id") or 1)
    except Exception:
        logger.exception("Invalid saved index job: %r", job)
        return

    status_msg = await _notify_admin(
        bot,
        (
            "♻️ <b>Previous indexing job auto-resumed.</b>\n\n"
            f"Channel: <code>{chat_id}</code>\n"
            f"Resume from message ID: "
            f"<code>{int(job.get('next_message_id') or start_id)}</code>"
        ),
    )

    _launch_index(
        bot,
        chat_id,
        top_id,
        start_id,
        status_msg=status_msg,
        resume_job=job,
    )


@Client.on_callback_query(filters.regex(r"^index"))
async def index_callback(bot, query):
    try:
        _, action, chat_id, top_id, start_id = query.data.split("#", 4)
    except ValueError:
        return await query.answer("Invalid index request", show_alert=True)

    if action == "cancel":
        temp.CANCEL = True
        await query.answer("Index will stop safely after current request.", show_alert=True)
        return

    if action != "yes":
        return

    if _task_running():
        return await query.answer(
            "An index job is already running.",
            show_alert=True,
        )

    chat_id = int(chat_id)
    top_id = int(top_id)
    start_id = max(1, int(start_id or 1))

    existing = await get_index_job(chat_id)
    resume_job = None

    if (
        existing
        and existing.get("status")
        in ("starting", "running", "waiting", "retrying")
        and int(existing.get("top_message_id") or 0) == top_id
    ):
        resume_job = existing
        start_id = int(existing.get("start_id") or start_id)

    await query.message.edit(
        "<b>⚡ Bot-only indexing started in background.</b>\n\n"
        "Search/download commands remain available."
    )

    launched = _launch_index(
        bot,
        chat_id,
        top_id,
        start_id,
        status_msg=query.message,
        resume_job=resume_job,
    )

    if not launched:
        await query.answer("Index job is already running.", show_alert=True)


@Client.on_message(
    filters.command("index")
    & filters.private
    & filters.incoming
    & filters.user(ADMINS)
)
async def send_for_index(bot, message):
    if _task_running():
        return await message.reply(
            "⚡ An index job is already running. Use /indexstatus."
        )

    ask = await message.reply(
        "Forward the channel's last message or send its message link."
    )
    msg = await bot.listen(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    await ask.delete()

    if msg.text and msg.text.startswith("https://t.me"):
        try:
            parts = msg.text.rstrip("/").split("/")
            top_id = int(parts[-1])
            chat_ref = parts[-2]
            if chat_ref.isnumeric():
                chat_ref = int("-100" + chat_ref)
        except Exception:
            return await message.reply("Invalid message link!")
    elif (
        msg.forward_from_chat
        and msg.forward_from_chat.type == enums.ChatType.CHANNEL
    ):
        top_id = int(msg.forward_from_message_id)
        chat_ref = msg.forward_from_chat.id
    else:
        return await message.reply(
            "This is not a forwarded channel message or valid link."
        )

    try:
        chat = await bot.get_chat(chat_ref)
    except Exception as exc:
        return await message.reply(
            f"Channel access error - {exc}"
        )

    if chat.type != enums.ChatType.CHANNEL:
        return await message.reply("I can index only channels.")

    ask_skip = await message.reply(
        "Send starting message ID.\n\n"
        "For a full index send <code>0</code>."
    )
    skip_msg = await bot.listen(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    await ask_skip.delete()

    try:
        start_id = max(1, int(skip_msg.text or "0"))
    except Exception:
        return await message.reply("Starting message ID is invalid.")

    existing = await get_index_job(chat.id)
    resume_note = ""

    if (
        existing
        and existing.get("status")
        in ("starting", "running", "waiting", "retrying")
        and int(existing.get("top_message_id") or 0) == top_id
    ):
        resume_from = int(
            existing.get("next_message_id")
            or existing.get("start_id")
            or start_id
        )
        resume_note = (
            "\n\n♻️ Saved checkpoint found. START will resume from "
            f"<code>{resume_from}</code>."
        )

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⚡ START BOT-ONLY INDEX",
                callback_data=(
                    f"index#yes#{chat.id}#{top_id}#{start_id}"
                ),
            )
        ],
        [
            InlineKeyboardButton(
                "CLOSE",
                callback_data="close_data",
            )
        ],
    ])

    await message.reply(
        (
            f"<b>Channel:</b> {chat.title}\n"
            f"<b>Last message ID:</b> <code>{top_id}</code>\n"
            f"<b>Start ID:</b> <code>{start_id}</code>\n\n"
            "⚡ <b>BOT-ONLY MODE</b>\n"
            "• No USER_SESSION_STRING required\n"
            "• 200 IDs per Telegram request\n"
            "• MongoDB bulk writes\n"
            "• Background indexing\n"
            "• MongoDB auto-resume checkpoint"
            f"{resume_note}"
        ),
        reply_markup=buttons,
    )


@Client.on_message(
    filters.command("indexstatus")
    & filters.private
    & filters.user(ADMINS)
)
async def index_status(bot, message):
    if _INDEX_TASK_CHAT is not None:
        job = await get_index_job(_INDEX_TASK_CHAT)
        if job:
            return await message.reply(_status_text(job))

    jobs = await get_pending_index_jobs()
    if jobs:
        return await message.reply(_status_text(jobs[0]))

    await message.reply("No active/pending index job.")


@Client.on_message(filters.command("channel"))
async def channel_info(bot, message):
    if message.from_user.id not in ADMINS:
        return await message.reply(
            "Only the bot owner can use this command."
        )

    if not CHANNELS:
        return await message.reply("Not set CHANNELS")

    text = "**Indexed Channels:**\n\n"
    for channel_id in CHANNELS:
        chat = await bot.get_chat(channel_id)
        text += f"{chat.title}\n"

    text += f"\n**Total:** {len(CHANNELS)}"
    await message.reply(text)
