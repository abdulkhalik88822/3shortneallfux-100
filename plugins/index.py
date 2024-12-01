import logging
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait
from pyrogram.errors.exceptions.bad_request_400 import (
    ChannelInvalid,
    ChatAdminRequired,
    UsernameInvalid,
    UsernameNotModified,
)
from info import ADMINS, LOG_CHANNEL
from database.ia_filterdb import save_file
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils import temp
import re

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
lock = asyncio.Lock()


@Client.on_callback_query(filters.regex(r'^index'))
async def index_files(bot, query):
    if query.data.startswith('index_cancel'):
        temp.CANCEL = True
        return await query.answer("Cancelling Indexing")
    _, action, chat, lst_msg_id, from_user = query.data.split("#")
    if action == 'reject':
        await query.message.delete()
        await bot.send_message(
            int(from_user),
            f'Your submission for indexing {chat} has been declined by our moderators.',
            reply_to_message_id=int(lst_msg_id),
        )
        return

    if lock.locked():
        return await query.answer('Wait until the previous process completes.', show_alert=True)
    msg = query.message

    await query.answer('Processing...⏳', show_alert=True)
    if int(from_user) not in ADMINS:
        await bot.send_message(
            int(from_user),
            f'Your submission for indexing {chat} has been accepted by our moderators and will be added soon.',
            reply_to_message_id=int(lst_msg_id),
        )
    await msg.edit(
        "Starting Indexing",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton('Cancel', callback_data='index_cancel')]]
        ),
    )
    try:
        chat = int(chat)
    except ValueError:
        chat = chat
    await index_files_to_db(int(lst_msg_id), chat, msg, bot)


@Client.on_message(
    (
        filters.forwarded
        | (
            filters.regex("(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")
            & filters.text
        )
    )
    & filters.private
    & filters.incoming
)
async def send_for_index(bot, message):
    if message.text:
        regex = re.compile("(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")
        match = regex.match(message.text)
        if not match:
            return await message.reply('Invalid link')
        chat_id = match.group(4)
        last_msg_id = int(match.group(5))
        if chat_id.isnumeric():
            chat_id = int(("-100" + chat_id))
    elif message.forward_from_chat and message.forward_from_chat.type == enums.ChatType.CHANNEL:
        last_msg_id = message.forward_from_message_id
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
    else:
        return
    try:
        await bot.get_chat(chat_id)
    except ChannelInvalid:
        return await message.reply(
            'This may be a private channel/group. Make me an admin over there to index the files.'
        )
    except (UsernameInvalid, UsernameNotModified):
        return await message.reply('Invalid link specified.')
    except Exception as e:
        logger.exception(e)
        return await message.reply(f'Error - {e}')
    try:
        k = await bot.get_messages(chat_id, last_msg_id)
    except:
        return await message.reply('Make sure I am an admin in the channel if it is private.')
    if k.empty:
        return await message.reply('This may be a group, and I am not an admin of the group.')

    if message.from_user.id in ADMINS:
        buttons = [
            [
                InlineKeyboardButton(
                    'Yes', callback_data=f'index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}'
                ),
            ],
            [
                InlineKeyboardButton('Close', callback_data='close_data'),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        return await message.reply(
            f'Do you want to index this channel/group?\n\nChat ID/Username: <code>{chat_id}</code>\nLast Message ID: <code>{last_msg_id}</code>',
            reply_markup=reply_markup,
        )

    if type(chat_id) is int:
        try:
            link = (await bot.create_chat_invite_link(chat_id)).invite_link
        except ChatAdminRequired:
            return await message.reply('Make sure I am an admin in the chat and have permission to invite users.')
    else:
        link = f"@{message.forward_from_chat.username}"
    buttons = [
        [
            InlineKeyboardButton(
                'Accept Index',
                callback_data=f'index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}',
            ),
        ],
        [
            InlineKeyboardButton(
                'Reject Index',
                callback_data=f'index#reject#{chat_id}#{message.id}#{message.from_user.id}',
            ),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await bot.send_message(
        LOG_CHANNEL,
        f'#IndexRequest\n\nBy : {message.from_user.mention} (<code>{message.from_user.id}</code>)\nChat ID/Username - <code>{chat_id}</code>\nLast Message ID - <code>{last_msg_id}</code>\nInviteLink - {link}',
        reply_markup=reply_markup,
    )
    await message.reply('Thank you for the contribution. Wait for my moderators to verify the files.')


@Client.on_message(filters.command('setskip') & filters.user(ADMINS))
async def set_skip_number(bot, message):
    if ' ' in message.text:
        _, skip = message.text.split(" ")
        try:
            skip = int(skip)
        except ValueError:
            return await message.reply("Skip number should be an integer.")
        await message.reply(f"Successfully set SKIP number as {skip}")
        temp.CURRENT = int(skip)
    else:
        await message.reply("Give me a skip number.")


async def save_files_in_bulk(messages):
    total_files = 0
    duplicate = 0
    errors = 0
    no_media = 0
    unsupported = 0

    for message in messages:
        if message.empty:
            continue
        elif not message.media:
            no_media += 1
            continue
        elif message.media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.AUDIO, enums.MessageMediaType.DOCUMENT]:
            unsupported += 1
            continue

        media = getattr(message, message.media.value, None)
        if not media:
            unsupported += 1
            continue

        media.file_type = message.media.value
        media.caption = message.caption
        result = await save_file(media)
        aynac, vnay = result[0], result[1]

        if aynac:
            total_files += 1
        elif vnay == 0:
            duplicate += 1
        elif vnay == 2:
            errors += 1

    return total_files, duplicate, errors, no_media, unsupported


async def index_files_to_db(lst_msg_id, chat, msg, bot):
    total_files = 0
    duplicate = 0
    errors = 0
    no_media = 0
    unsupported = 0
    batch_size = 50  # Adjusted batch size

    async with lock:
        try:
            current = temp.CURRENT
            temp.CANCEL = False
            messages_to_process = []

            async for message in bot.iter_messages(chat, lst_msg_id, temp.CURRENT):
                if temp.CANCEL:
                    await msg.edit(f"Successfully Cancelled!\n\nSaved <code>{total_files}</code> files to the database!")
                    break

                # Collect messages in batches
                messages_to_process.append(message)
                current += 1

                # Process the batch when full
                if len(messages_to_process) >= batch_size:
                    try:
                        batch_results = await save_files_in_bulk(messages_to_process)
                        total_files += batch_results[0]
                        duplicate += batch_results[1]
                        errors += batch_results[2]
                        no_media += batch_results[3]
                        unsupported += batch_results[4]
                        messages_to_process = []  # Clear batch

                        # Add delay to avoid flood waits
                        await asyncio.sleep(0.5)
                    except FloodWait as e:
                        logger.warning(f"Flood wait triggered. Sleeping for {e.value} seconds...")
                        await asyncio.sleep(e.value)

                # Update progress every 20 messages
                if current % 20 == 0:
                    can = [[InlineKeyboardButton('Cancel', callback_data='index_cancel')]]
                    reply = InlineKeyboardMarkup(can)
                    await msg.edit_text(
                        text=(
                            f"Total messages fetched: <code>{current}</code>\n"
                            f"Total messages saved: <code>{total_files}</code>\n"
                            f"Duplicate Files Skipped: <code>{duplicate}</code>\n"
                            f"Non-Media messages skipped: <code>{no_media + unsupported}</code>"
                            f"(Unsupported Media - `{unsupported}`)\nErrors Occurred: <code>{errors}</code>"
                        ),
                        reply_markup=reply,
                    )

            # Process remaining messages in batch
            if messages_to_process:
                batch_results = await save_files_in_bulk(messages_to_process)
                total_files += batch_results[0]
                duplicate += batch_results[1]
                errors += batch_results[2]
                no_media += batch_results[3]
                unsupported += batch_results[4]

        except Exception as e:
            logger.exception(e)
            await msg.edit(f"Error: {e}")
        else:
            await msg.edit(
                f"Successfully saved <code>{total_files}</code> files to the database!\n"
                f"Duplicate Files Skipped: <code>{duplicate}</code>\n"
                f"Non-Media messages skipped: <code>{no_media + unsupported}</code>"
                f"(Unsupported Media - `{unsupported}`)\nErrors Occurred: <code>{errors}</code>"
            )
