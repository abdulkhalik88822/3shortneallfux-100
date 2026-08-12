import asyncio
import os
import time

from pyrogram import Client, enums, filters
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.ia_filterdb import save_files_bulk
from info import ADMINS, CHANNELS
from utils import get_readable_time, temp


# Only one /index job at a time.
lock = asyncio.Lock()

# Tune from Koyeb env if ever needed; no info.py change required.
INDEX_DB_BATCH = max(100, min(2000, int(os.environ.get("INDEX_DB_BATCH", "1000"))))
INDEX_PROGRESS_SECONDS = max(5, int(os.environ.get("INDEX_PROGRESS_SECONDS", "12")))


async def _safe_progress_edit(msg, text, reply_markup=None):
    """Progress UI must never become the indexing bottleneck."""
    try:
        await msg.edit_text(text=text, reply_markup=reply_markup)
    except FloodWait:
        # Do not stop the index just because the status message hit a flood limit.
        pass
    except Exception:
        pass


async def _flush_batch(buffer):
    if not buffer:
        return 0, 0, 0

    batch = list(buffer)
    buffer.clear()
    return await save_files_bulk(batch)


def _progress_text(current, total_files, duplicate, deleted, no_media, unsupported, errors, pending, start_time):
    elapsed = max(0.001, time.time() - start_time)
    scanned = max(0, current)
    speed = scanned / elapsed
    return (
        f"⚡ <b>SUPER FAST INDEXING</b>\n\n"
        f"Messages scanned: <code>{scanned}</code>\n"
        f"Files saved: <code>{total_files}</code>\n"
        f"Duplicates skipped: <code>{duplicate}</code>\n"
        f"Deleted skipped: <code>{deleted}</code>\n"
        f"Non-media skipped: <code>{no_media}</code>\n"
        f"Unsupported skipped: <code>{unsupported}</code>\n"
        f"Pending batch: <code>{pending}</code>\n"
        f"Errors: <code>{errors}</code>\n\n"
        f"Speed: <code>{speed:.1f} msg/sec</code>\n"
        f"Running: <code>{get_readable_time(elapsed)}</code>"
    )


@Client.on_callback_query(filters.regex(r"^index"))
async def index_files(bot, query):
    _, ident, chat, lst_msg_id, skip = query.data.split("#")

    if ident == "yes":
        msg = query.message
        await msg.edit("<b>⚡ Super-fast indexing started...</b>")

        try:
            chat = int(chat)
        except (TypeError, ValueError):
            pass

        await index_files_to_db(
            int(lst_msg_id),
            chat,
            msg,
            bot,
            int(skip),
        )

    elif ident == "cancel":
        temp.CANCEL = True
        await query.message.edit("Trying to cancel Indexing...")


@Client.on_message(
    filters.command("index")
    & filters.private
    & filters.incoming
    & filters.user(ADMINS)
)
async def send_for_index(bot, message):
    if lock.locked():
        return await message.reply("Wait until previous process complete.")

    i = await message.reply("Forward last message or send last message link.")
    msg = await bot.listen(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    await i.delete()

    if msg.text and msg.text.startswith("https://t.me"):
        try:
            msg_link = msg.text.split("/")
            last_msg_id = int(msg_link[-1])
            chat_id = msg_link[-2]
            if chat_id.isnumeric():
                chat_id = int("-100" + chat_id)
        except Exception:
            return await message.reply("Invalid message link!")

    elif (
        msg.forward_from_chat
        and msg.forward_from_chat.type == enums.ChatType.CHANNEL
    ):
        last_msg_id = msg.forward_from_message_id
        chat_id = msg.forward_from_chat.username or msg.forward_from_chat.id

    else:
        return await message.reply(
            "This is not forwarded message or link."
        )

    try:
        chat = await bot.get_chat(chat_id)
    except Exception as exc:
        return await message.reply(f"Errors - {exc}")

    if chat.type != enums.ChatType.CHANNEL:
        return await message.reply("I can index only channels.")

    s = await message.reply("Send skip message number.")
    msg = await bot.listen(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    await s.delete()

    try:
        skip = int(msg.text)
    except Exception:
        return await message.reply("Number is invalid.")

    buttons = [
        [
            InlineKeyboardButton(
                "YES",
                callback_data=(
                    f"index#yes#{chat_id}#{last_msg_id}#{skip}"
                ),
            )
        ],
        [
            InlineKeyboardButton(
                "CLOSE",
                callback_data="close_data",
            )
        ],
    ]

    await message.reply(
        (
            f"Do you want to index {chat.title} channel?\n"
            f"Total Messages: <code>{last_msg_id}</code>\n\n"
            f"⚡ DB Batch: <code>{INDEX_DB_BATCH}</code> files"
        ),
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@Client.on_message(filters.command("channel"))
async def channel_info(bot, message):
    if message.from_user.id not in ADMINS:
        await message.reply(
            "ᴏɴʟʏ ᴛʜᴇ ʙᴏᴛ ᴏᴡɴᴇʀ ᴄᴀɴ ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ... 😑"
        )
        return

    if not CHANNELS:
        return await message.reply("Not set CHANNELS")

    text = "**Indexed Channels:**\n\n"
    for channel_id in CHANNELS:
        chat = await bot.get_chat(channel_id)
        text += f"{chat.title}\n"

    text += f"\n**Total:** {len(CHANNELS)}"
    await message.reply(text)


async def index_files_to_db(lst_msg_id, chat, msg, bot, skip):
    start_time = time.time()
    last_progress = 0.0

    total_files = 0
    duplicate = 0
    errors = 0
    deleted = 0
    no_media = 0
    unsupported = 0
    current = int(skip)

    buffer = []

    async with lock:
        try:
            async for message in bot.iter_messages(
                chat,
                lst_msg_id,
                skip,
            ):
                current += 1

                if temp.CANCEL:
                    # Save already-scanned files before stopping.
                    ins, dup, err = await _flush_batch(buffer)
                    total_files += ins
                    duplicate += dup
                    errors += err

                    temp.CANCEL = False
                    elapsed = time.time() - start_time

                    await msg.edit(
                        (
                            "✅ <b>Indexing cancelled safely.</b>\n\n"
                            f"Saved: <code>{total_files}</code>\n"
                            f"Duplicates: <code>{duplicate}</code>\n"
                            f"Errors: <code>{errors}</code>\n"
                            f"Completed in: <code>{get_readable_time(elapsed)}</code>"
                        )
                    )
                    return

                if message.empty:
                    deleted += 1
                    continue

                if not message.media:
                    no_media += 1
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

                if media.mime_type not in (
                    "video/mp4",
                    "video/x-matroska",
                ):
                    unsupported += 1
                    continue

                media.caption = message.caption
                buffer.append(media)

                # THE BIG SPEEDUP:
                # one MongoDB request for up to 1000 files instead of
                # one awaited database commit for every single file.
                if len(buffer) >= INDEX_DB_BATCH:
                    ins, dup, err = await _flush_batch(buffer)
                    total_files += ins
                    duplicate += dup
                    errors += err

                # Telegram status edits are intentionally time-based.
                # The old code edited every 30 messages, which is extremely
                # expensive for a 900k-message channel.
                now = time.time()
                if now - last_progress >= INDEX_PROGRESS_SECONDS:
                    last_progress = now
                    btn = [[
                        InlineKeyboardButton(
                            "CANCEL",
                            callback_data=(
                                f"index#cancel#{chat}#{lst_msg_id}#{skip}"
                            ),
                        )
                    ]]
                    await _safe_progress_edit(
                        msg,
                        _progress_text(
                            current,
                            total_files,
                            duplicate,
                            deleted,
                            no_media,
                            unsupported,
                            errors,
                            len(buffer),
                            start_time,
                        ),
                        InlineKeyboardMarkup(btn),
                    )

            # Flush last partial batch.
            ins, dup, err = await _flush_batch(buffer)
            total_files += ins
            duplicate += dup
            errors += err

        except Exception as exc:
            # Try to preserve the current buffer even if the scanner fails.
            try:
                ins, dup, err = await _flush_batch(buffer)
                total_files += ins
                duplicate += dup
                errors += err
            except Exception:
                pass

            await msg.reply(
                f"Index canceled due to Error - {exc}"
            )
            return

    elapsed = time.time() - start_time
    speed = max(0, current - skip) / max(elapsed, 0.001)

    await msg.edit(
        (
            f"✅ <b>SUPER FAST INDEX COMPLETE</b>\n\n"
            f"Saved: <code>{total_files}</code>\n"
            f"Duplicates: <code>{duplicate}</code>\n"
            f"Deleted skipped: <code>{deleted}</code>\n"
            f"Non-media skipped: <code>{no_media}</code>\n"
            f"Unsupported skipped: <code>{unsupported}</code>\n"
            f"Errors: <code>{errors}</code>\n\n"
            f"Average speed: <code>{speed:.1f} msg/sec</code>\n"
            f"Completed in: <code>{get_readable_time(elapsed)}</code>"
        )
    )
