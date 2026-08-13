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

# MongoDB bulk size. 1000 is a good default for Koyeb + Atlas.
INDEX_DB_BATCH = max(
    100,
    min(2000, int(os.environ.get("INDEX_DB_BATCH", "1000")))
)

# Do not spam Telegram with progress edits.
INDEX_PROGRESS_SECONDS = max(
    5,
    int(os.environ.get("INDEX_PROGRESS_SECONDS", "12"))
)


async def _safe_progress_edit(msg, text, reply_markup=None):
    try:
        await msg.edit_text(
            text=text,
            reply_markup=reply_markup
        )
    except FloodWait as e:
        # Progress UI is not important enough to pause the index job.
        # The next timed update will refresh it.
        pass
    except Exception:
        pass


async def _flush_batch(buffer):
    if not buffer:
        return 0, 0, 0

    batch = list(buffer)
    buffer.clear()
    return await save_files_bulk(batch)


def _progress_text(
    scanned,
    total_files,
    duplicate,
    no_media,
    unsupported,
    errors,
    pending,
    last_message_id,
    start_time,
):
    elapsed = max(0.001, time.time() - start_time)
    speed = scanned / elapsed

    return (
        "⚡ <b>BOT-SAFE FAST INDEXING</b>\n\n"
        f"Messages scanned: <code>{scanned}</code>\n"
        f"Files saved: <code>{total_files}</code>\n"
        f"Duplicates skipped: <code>{duplicate}</code>\n"
        f"Non-media skipped: <code>{no_media}</code>\n"
        f"Unsupported media: <code>{unsupported}</code>\n"
        f"Pending DB batch: <code>{pending}</code>\n"
        f"Errors: <code>{errors}</code>\n"
        f"Last message ID: <code>{last_message_id}</code>\n\n"
        f"Speed: <code>{speed:.1f} msg/sec</code>\n"
        f"Running: <code>{get_readable_time(elapsed)}</code>"
    )


@Client.on_callback_query(filters.regex(r"^index"))
async def index_files(bot, query):
    _, ident, chat, lst_msg_id, skip = query.data.split("#")

    if ident == "yes":
        msg = query.message
        await msg.edit(
            "<b>⚡ Bot-safe fast indexing started...</b>"
        )

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
        await query.message.edit(
            "Trying to cancel indexing safely..."
        )


@Client.on_message(
    filters.command("index")
    & filters.private
    & filters.incoming
    & filters.user(ADMINS)
)
async def send_for_index(bot, message):
    if lock.locked():
        return await message.reply(
            "Wait until previous indexing process completes."
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
            msg_link = msg.text.rstrip("/").split("/")
            last_msg_id = int(msg_link[-1])
            chat_id = msg_link[-2]

            if chat_id.isnumeric():
                chat_id = int("-100" + chat_id)
        except Exception:
            return await message.reply(
                "Invalid message link!"
            )

    elif (
        msg.forward_from_chat
        and msg.forward_from_chat.type
        == enums.ChatType.CHANNEL
    ):
        last_msg_id = msg.forward_from_message_id
        chat_id = (
            msg.forward_from_chat.username
            or msg.forward_from_chat.id
        )

    else:
        return await message.reply(
            "This is not a forwarded channel message or valid link."
        )

    try:
        chat = await bot.get_chat(chat_id)
    except Exception as exc:
        return await message.reply(
            f"Channel access error - {exc}"
        )

    if chat.type != enums.ChatType.CHANNEL:
        return await message.reply(
            "I can index only channels."
        )

    ask_skip = await message.reply(
        "Send skip count.\n\n"
        "For a fresh full index send <code>0</code>."
    )

    skip_msg = await bot.listen(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    await ask_skip.delete()

    try:
        skip = max(0, int(skip_msg.text))
    except Exception:
        return await message.reply(
            "Skip count is invalid."
        )

    buttons = [
        [
            InlineKeyboardButton(
                "🚀 START FAST INDEX",
                callback_data=(
                    f"index#yes#{chat_id}#"
                    f"{last_msg_id}#{skip}"
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
            f"<b>Channel:</b> {chat.title}\n"
            f"<b>Last message ID:</b> "
            f"<code>{last_msg_id}</code>\n"
            f"<b>Skip:</b> <code>{skip}</code>\n\n"
            "⚡ <b>BOT-SAFE FAST MODE</b>\n"
            "Uses Telegram's maximum bot-safe batch fetch (up to 200 IDs/request).\n"
            f"MongoDB batch: <code>{INDEX_DB_BATCH}</code>"
        ),
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@Client.on_message(filters.command("channel"))
async def channel_info(bot, message):
    if message.from_user.id not in ADMINS:
        await message.reply(
            "ᴏɴʟʏ ᴛʜᴇ ʙᴏᴛ ᴏᴡɴᴇʀ "
            "ᴄᴀɴ ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ... 😑"
        )
        return

    if not CHANNELS:
        return await message.reply(
            "Not set CHANNELS"
        )

    text = "**Indexed Channels:**\n\n"

    for channel_id in CHANNELS:
        chat = await bot.get_chat(channel_id)
        text += f"{chat.title}\n"

    text += f"\n**Total:** {len(CHANNELS)}"
    await message.reply(text)


async def index_files_to_db(
    lst_msg_id,
    chat,
    msg,
    bot,
    skip,
):
    """
    Bot-safe fast indexer.

    Telegram bot accounts cannot use messages.GetHistory/get_chat_history()
    for channel history. This implementation therefore uses the project's
    Bot.iter_messages(), which batches message IDs through get_messages().

    Performance improvements retained:
    - up to 200 message IDs per Telegram request (handled by bot.py)
    - MongoDB bulk insert batches (default 1000 files)
    - time-based progress edits instead of editing every few messages
    - safe final batch flush on cancel/error

    Telegram FloodWaits are server-side limits and cannot be bypassed safely.
    """

    start_time = time.time()
    last_progress = 0.0

    total_files = 0
    duplicate = 0
    errors = 0
    no_media = 0
    unsupported = 0
    scanned = 0
    last_message_id = lst_msg_id

    buffer = []

    async with lock:
        try:
            # BOT-SAFE MODE:
            # Telegram bots cannot call messages.GetHistory for channel
            # history. The custom Bot.iter_messages() implementation in
            # bot.py fetches up to 200 message IDs per request using
            # get_messages(), which is allowed for bots.
            #
            # "skip" is treated as the starting message ID.
            async for message in bot.iter_messages(
                chat,
                int(lst_msg_id),
                int(skip),
            ):
                scanned += 1
                last_message_id = getattr(
                    message,
                    "id",
                    last_message_id,
                )

                if temp.CANCEL:
                    ins, dup, err = await _flush_batch(buffer)
                    total_files += ins
                    duplicate += dup
                    errors += err

                    temp.CANCEL = False
                    elapsed = time.time() - start_time

                    await msg.edit(
                        (
                            "✅ <b>Indexing cancelled safely.</b>\n\n"
                            f"History scanned: <code>{scanned}</code>\n"
                            f"Saved: <code>{total_files}</code>\n"
                            f"Duplicates: <code>{duplicate}</code>\n"
                            f"Errors: <code>{errors}</code>\n"
                            f"Last message ID: "
                            f"<code>{last_message_id}</code>\n"
                            f"Completed in: "
                            f"<code>{get_readable_time(elapsed)}</code>"
                        )
                    )
                    return

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

                # One MongoDB request for up to 1000 files.
                if len(buffer) >= INDEX_DB_BATCH:
                    ins, dup, err = await _flush_batch(buffer)
                    total_files += ins
                    duplicate += dup
                    errors += err

                now = time.time()

                if (
                    now - last_progress
                    >= INDEX_PROGRESS_SECONDS
                ):
                    last_progress = now

                    btn = [[
                        InlineKeyboardButton(
                            "CANCEL",
                            callback_data=(
                                f"index#cancel#{chat}#"
                                f"{lst_msg_id}#{skip}"
                            ),
                        )
                    ]]

                    await _safe_progress_edit(
                        msg,
                        _progress_text(
                            scanned,
                            total_files,
                            duplicate,
                            no_media,
                            unsupported,
                            errors,
                            len(buffer),
                            last_message_id,
                            start_time,
                        ),
                        InlineKeyboardMarkup(btn),
                    )

            # Save the last incomplete batch.
            ins, dup, err = await _flush_batch(buffer)
            total_files += ins
            duplicate += dup
            errors += err

        except FloodWait as exc:
            # Normally Pyrofork waits automatically. If a FloodWait reaches
            # this level, save everything already collected before exiting.
            try:
                ins, dup, err = await _flush_batch(buffer)
                total_files += ins
                duplicate += dup
                errors += err
            except Exception:
                pass

            wait_for = getattr(
                exc,
                "value",
                getattr(exc, "x", 0),
            )

            await msg.edit(
                (
                    "⚠️ <b>Telegram FloodWait stopped this run.</b>\n\n"
                    f"Telegram requested wait: "
                    f"<code>{wait_for}s</code>\n"
                    f"History scanned: <code>{scanned}</code>\n"
                    f"Files saved: <code>{total_files}</code>\n"
                    f"Last message ID: "
                    f"<code>{last_message_id}</code>\n\n"
                    "Run /index again after the wait."
                )
            )
            return

        except Exception as exc:
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
    speed = scanned / max(elapsed, 0.001)

    await msg.edit(
        (
            "✅ <b>BOT-SAFE FAST INDEX COMPLETE</b>\n\n"
            f"Messages scanned: <code>{scanned}</code>\n"
            f"Files saved: <code>{total_files}</code>\n"
            f"Duplicates: <code>{duplicate}</code>\n"
            f"Non-media skipped: <code>{no_media}</code>\n"
            f"Unsupported media: <code>{unsupported}</code>\n"
            f"Errors: <code>{errors}</code>\n\n"
            f"Average speed: <code>{speed:.1f} msg/sec</code>\n"
            f"Completed in: "
            f"<code>{get_readable_time(elapsed)}</code>"
        )
    )
