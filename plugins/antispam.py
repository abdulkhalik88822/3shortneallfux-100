from pyrogram import Client, filters
from pyrogram.types import Message

# गंदे शब्द और स्पैम वर्ड्स की लिस्ट
BAD_WORDS = ["xxx", "porn", "sex", "hot video", "bitcoin", "crypto", "btc", "investment", "18+"]

# group=1 का मतलब है यह बाकी फिल्टर्स के साथ सही से काम करेगा
@Client.on_message(filters.group & (filters.text | filters.caption), group=1)
async def delete_spam(client: Client, message: Message):
    if not message.from_user:
        return

    # 1. सबसे पहले TEXT चेक करें (यह बहुत फास्ट होता है)
    text = message.text or message.caption
    if not text:
        return
    
    text_lower = text.lower()
    is_spam = False

    # (A) लिंक चेक (Links)
    if "http" in text_lower or "t.me" in text_lower or ".com" in text_lower:
        is_spam = True
    # (B) यूजरनेम चेक (@)
    elif "@" in text: 
        is_spam = True
    # (C) गंदे शब्द (Bad Words)
    elif any(word in text_lower for word in BAD_WORDS):
        is_spam = True

    # 2. अगर SPAM नहीं है, तो यहीं रुक जाएं (ताकि बॉट मूवी सर्च कर सके)
    if not is_spam:
        return 

    # 3. अगर SPAM पकड़ा गया, तो अब चेक करें कि वो ADMIN है या नहीं
    try:
        member = await client.get_chat_member(message.chat.id, message.from_user.id)
        if member.status in ["administrator", "creator"]:
            return # अगर एडमिन है तो माफ़ करें
    except Exception:
        pass 

    # 4. स्पैम है और एडमिन नहीं है -> DELETE
    try:
        await message.delete()
        # await message.reply(f"🚫 {message.from_user.mention}, लिंक और स्पैम यहाँ अलाउड नहीं है!", quote=True)
    except Exception as e:
        print(f"Error deleting message: {e}")
