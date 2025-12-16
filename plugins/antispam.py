from pyrogram import Client, filters
from pyrogram.types import Message

# वो शब्द जो आप ब्लॉक करना चाहते हैं
BAD_WORDS = ["xxx", "porn", "sex", "hot video", "bitcoin", "crypto", "btc", "investment", "18+"]

@Client.on_message(filters.group & (filters.text | filters.caption))
async def delete_spam(client: Client, message: Message):
    # अगर मैसेज भेजने वाला खुद बॉट है, तो इग्नोर करें
    if message.from_user and message.from_user.is_self:
        return

    # 1. चेक करें कि यूजर Admin है या नहीं (Admin का मैसेज डिलीट नहीं होगा)
    try:
        member = await client.get_chat_member(message.chat.id, message.from_user.id)
        if member.status in ["administrator", "creator"]:
            return
    except Exception:
        pass # अगर कोई एरर आए तो सेफ साइड के लिए मैसेज चेक करें

    # 2. मैसेज का टेक्स्ट या कैप्शन निकालें
    text = message.text or message.caption
    if not text:
        return
    
    text_lower = text.lower()
    should_delete = False

    # (A) लिंक चेक (Links)
    if "http" in text_lower or "t.me" in text_lower or ".com" in text_lower:
        should_delete = True

    # (B) यूजरनेम चेक (@) - अगर आप चाहते हैं कि कोई यूजरनेम न भेजे
    elif "@" in text: 
        should_delete = True

    # (C) गंदे शब्द (Bad Words)
    elif any(word in text_lower for word in BAD_WORDS):
        should_delete = True

    # 3. डिलीट करें
    if should_delete:
        try:
            await message.delete()
            # चाहे तो यूजर को वार्निंग भी भेज सकते हैं (नीचे वाली लाइन से # हटा दें)
            # await message.reply(f"{message.from_user.mention}, लिंक और स्पैम यहाँ अलाउड नहीं है!", quote=True)
        except Exception as e:
            print(f"Error deleting message: {e}")
